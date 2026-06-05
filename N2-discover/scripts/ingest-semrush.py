#!/usr/bin/env python3
"""
Ingest Semrush "Keyword Variations" + "Questions" exports into keywords-raw.csv
(node N2, Semrush-driven discovery).

This is the discovery engine for the manual phase. The user takes each surviving
seed (one that passed the volume gate) into the Semrush web app, opens its
"关键词变化 / Keyword Variations" and "问题 / Questions" panels, and exports/copies
the rows. Each exported row is a REAL keyword with REAL volume + KD — a far richer
signal than free Autocomplete. This script collects every export under a folder,
normalizes the (often Chinese) headers, tags each row with its source seed, dedups
across files, and writes a keywords-raw.csv that already carries volume/kd/cpc —
so N3 no longer needs a fragile after-the-fact merge.

Later the Semrush API replaces this manual export step (same output shape).

File-naming convention (drop the exports into runs/{date}_{site}/_semrush/):
    00_seed-overview.csv            seed gate export (the seeds themselves)  -> source=overview
    {seed-slug}__variations.csv     keyword variations for that seed         -> source=variation
    {seed-slug}__questions.csv      questions for that seed                  -> source=question
e.g. vpn-for-china__variations.csv , china-esim__questions.csv

The seed slug is matched (case/space/hyphen-insensitive) against the seeds in an
N1 product-profile.json (via --profile) to carry over each seed's cluster/layer.
Without --profile, seed is reconstructed from the slug and cluster/layer stay blank
(the LLM assigns cluster during N2's relevance-filtering step).

Output (default ./seo-grow/keywords-raw.csv, override with --output):
    keyword, seed, layer, source, country, lang, cluster, volume, kd, cpc, semrush_intent

Usage:
    python ingest-semrush.py --semrush runs/2026-06-04_chinaready/_semrush/*.csv \
        --profile runs/2026-06-04_chinaready/N1_product-profile.json \
        --output runs/2026-06-04_chinaready/N2_keywords-raw.csv
    python ingest-semrush.py --semrush _semrush/*.csv --min-volume 50
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
from pathlib import Path

# Header aliases (lowercased, stripped) -> canonical field. Covers English and the
# Chinese Semrush UI export headers shown in the web app.
HEADER_ALIASES = {
    # keyword
    "keyword": "keyword", "keywords": "keyword", "关键词": "keyword",
    # volume
    "volume": "volume", "search volume": "volume", "avg. search volume": "volume",
    "搜索量": "volume",
    # difficulty
    "keyword difficulty": "kd", "kd": "kd", "kd %": "kd", "kd (%)": "kd",
    "difficulty": "kd", "难度": "kd",
    # cpc
    "cpc": "cpc", "cpc (usd)": "cpc", "cpc usd": "cpc", "cpc(usd)": "cpc",
    # intent (Semrush's own intent column — used as a prior for N3)
    "intent": "semrush_intent", "意图": "semrush_intent",
}

# Semrush intent codes -> readable label (its column packs codes like "I" or "C, I").
INTENT_CODE = {"c": "commercial", "i": "informational",
               "n": "navigational", "t": "transactional"}


def _slugify(s: str) -> str:
    """Normalize a seed/keyword for slug comparison: lower, alnum runs -> single -."""
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


def _parse_filename(path):
    """From '<seed-slug>__variations.csv' derive (seed_slug, source).

    source is one of variation|question|overview. Unrecognized suffix -> variation.
    A bare '00_seed-overview.csv' (no '__') -> ('', 'overview').
    """
    stem = Path(path).stem
    if "__" in stem:
        slug, _, suffix = stem.rpartition("__")
        suffix = suffix.lower()
        if suffix.startswith("question"):
            return _slugify(slug), "question"
        if suffix.startswith("overview"):
            return _slugify(slug), "overview"
        return _slugify(slug), "variation"
    if "overview" in stem.lower():
        return "", "overview"
    # No convention followed: treat whole stem as the seed, rows as variations.
    return _slugify(stem), "variation"


def _sniff_reader(path):
    """Open a CSV/TSV and return (DictReader, filehandle), detecting delimiter."""
    f = open(path, newline="", encoding="utf-8-sig")
    sample = f.read(4096)
    f.seek(0)
    delim = "\t" if sample.count("\t") > sample.count(",") else ","
    return csv.DictReader(f, delimiter=delim), f


def _map_headers(fieldnames):
    """Map a file's headers to canonical field names via aliases."""
    mapping = {}
    for h in fieldnames or []:
        key = h.strip().lower()
        if key in HEADER_ALIASES:
            mapping[h] = HEADER_ALIASES[key]
    return mapping


def _clean_num(v):
    if v is None:
        return ""
    s = str(v).strip().replace(",", "").replace("%", "")
    if not s:
        return ""
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except ValueError:
        return ""


def _norm_intent(v):
    """Semrush intent cell ('I' / 'C, I' / 'Informational') -> readable label(s)."""
    if not v:
        return ""
    raw = str(v).strip()
    parts = [p.strip().lower() for p in re.split(r"[,/|]+", raw) if p.strip()]
    out = []
    for p in parts:
        if p in INTENT_CODE:
            out.append(INTENT_CODE[p])
        elif p in INTENT_CODE.values():
            out.append(p)
        elif len(p) == 1:
            continue
        else:
            out.append(p)
    # de-dup, keep order
    seen, res = set(), []
    for o in out:
        if o not in seen:
            seen.add(o)
            res.append(o)
    return ", ".join(res)


def load_profile_seeds(profile_path):
    """Return {seed_slug: {seed, layer, cluster}} from N1 profile."""
    if not profile_path:
        return {}
    try:
        data = json.load(open(profile_path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  ⚠ cannot read profile {profile_path}: {e}", file=sys.stderr)
        return {}
    out = {}
    for s in data.get("seed_keywords", []):
        kw = (s.get("keyword") if isinstance(s, dict) else str(s)) or ""
        if not kw:
            continue
        out[_slugify(kw)] = {
            "seed": kw,
            "layer": (s.get("layer", "") if isinstance(s, dict) else ""),
            "cluster": (s.get("cluster", "") if isinstance(s, dict) else ""),
        }
    return out


def _vol(r):
    try:
        return float(r.get("volume")) if r.get("volume") not in ("", None) else None
    except (ValueError, TypeError):
        return None


def _vol_ok(r, floor):
    if floor <= 0:
        return True
    v = _vol(r)
    return v is None or v >= floor  # keep blank-volume rows (e.g. overview seeds)


COLUMNS = ["keyword", "seed", "layer", "source", "country", "lang", "cluster",
           "volume", "kd", "cpc", "semrush_intent"]


# PLACEHOLDER_APPEND


def _merge_row(cur, new):
    """Keep the higher-volume metrics; prefer a question source label; union intent."""
    if (_vol(new) or -1) > (_vol(cur) or -1):
        for k in ("volume", "kd", "cpc"):
            if new[k] != "":
                cur[k] = new[k]
    for k in ("kd", "cpc", "volume"):
        if cur[k] == "" and new[k] != "":
            cur[k] = new[k]
    if new["source"] == "question":
        cur["source"] = "question"
    if not cur["seed"] and new["seed"]:
        cur["seed"] = new["seed"]
    for k in ("layer", "cluster"):
        if not cur[k] and new[k]:
            cur[k] = new[k]
    if new["semrush_intent"] and new["semrush_intent"] not in cur["semrush_intent"]:
        cur["semrush_intent"] = (
            new["semrush_intent"] if not cur["semrush_intent"]
            else f"{cur['semrush_intent']}, {new['semrush_intent']}")


def _write(rows, output):
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})


def _report(rows, dropped, floor, output):
    from collections import Counter
    src = Counter(r["source"] for r in rows)
    with_vol = sum(1 for r in rows if _vol(r) is not None)
    vols = [_vol(r) for r in rows if _vol(r) is not None]
    print(f"\n✅ Wrote {len(rows)} keyword(s) → {output}", file=sys.stderr)
    print("   sources: " + "  ".join(f"{k}={v}" for k, v in src.most_common()),
          file=sys.stderr)
    print(f"   volume present on {with_vol}/{len(rows)}"
          + (f"  (total monthly ≈ {int(sum(vols)):,})" if vols else ""),
          file=sys.stderr)
    if floor > 0:
        print(f"   dropped {dropped} row(s) below volume {floor:g}", file=sys.stderr)
    print("\n   Next: LLM relevance-filter (cut off-topic high-volume terms) + "
          "verify cluster, then hand to N3-classify.", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest Semrush variations/questions exports into keywords-raw.csv")
    ap.add_argument("--semrush", nargs="+", required=True,
                    help="Semrush export CSV/TSV(s); globs allowed")
    ap.add_argument("--profile", default="",
                    help="N1 product-profile.json (carries seed cluster/layer)")
    ap.add_argument("--output", "-o", default="seo-grow/keywords-raw.csv")
    ap.add_argument("--country", default="us", help="country tag for rows (gl)")
    ap.add_argument("--lang", default="en", help="language tag for rows (hl)")
    ap.add_argument("--min-volume", type=float, default=0.0,
                    help="drop keywords whose volume is below this (0 = keep all)")
    args = ap.parse_args()

    seed_meta = load_profile_seeds(args.profile)

    files = []
    for p in args.semrush:
        files.extend(sorted(glob.glob(p)) or ([p] if os.path.exists(p) else []))
    if not files:
        print("Error: no Semrush files matched.", file=sys.stderr)
        sys.exit(1)

    acc = {}  # (keyword.lower(), lang) -> row
    for path in files:
        seed_slug, source = _parse_filename(path)
        meta = seed_meta.get(seed_slug, {})
        seed = meta.get("seed") or (seed_slug.replace("-", " ") if seed_slug else "")
        try:
            reader, fh = _sniff_reader(path)
        except OSError as e:
            print(f"  ⚠ cannot open {path}: {e}", file=sys.stderr)
            continue
        with fh:
            hmap = _map_headers(reader.fieldnames)
            if "keyword" not in hmap.values():
                print(f"  ⚠ {path}: no Keyword column "
                      f"(headers: {reader.fieldnames}) — skipped", file=sys.stderr)
                continue
            n = 0
            for r in reader:
                rec = {"volume": "", "kd": "", "cpc": "", "semrush_intent": ""}
                kw = ""
                for orig, canon in hmap.items():
                    val = r.get(orig, "")
                    if canon == "keyword":
                        kw = str(val).strip()
                    elif canon == "semrush_intent":
                        rec[canon] = _norm_intent(val)
                    else:
                        rec[canon] = _clean_num(val)
                if not kw:
                    continue
                n += 1
                key = (kw.lower(), args.lang)
                row = {
                    "keyword": kw, "seed": seed,
                    "layer": meta.get("layer", ""), "source": source,
                    "country": args.country, "lang": args.lang,
                    "cluster": meta.get("cluster", ""),
                    "volume": rec["volume"], "kd": rec["kd"], "cpc": rec["cpc"],
                    "semrush_intent": rec["semrush_intent"],
                }
                if key not in acc:
                    acc[key] = row
                else:
                    _merge_row(acc[key], row)
            print(f"  · {Path(path).name}: {n} rows  (seed='{seed}', {source})",
                  file=sys.stderr)

    rows = list(acc.values())
    kept = [r for r in rows if _vol_ok(r, args.min_volume)]
    dropped = len(rows) - len(kept)
    kept.sort(key=lambda r: (-(_vol(r) or -1.0), r["keyword"].lower()))

    _write(kept, args.output)
    _report(kept, dropped, args.min_volume, args.output)


if __name__ == "__main__":
    main()
