#!/usr/bin/env python3
"""
Merge a Semrush CSV export onto N2's raw keywords by exact keyword match (N3).

This is the one place the chain touches paid data. In the manual phase the user
exports a "Keyword Overview" or "Keyword Magic Tool" CSV from the Semrush web
app and drops it in; this script attaches volume / KD / CPC to each raw keyword.
Later the same role is filled by the Semrush API — same output shape, no manual
export. Until then, this keeps Semrush optional and swappable.

Semrush column names vary by export and locale, so we match headers fuzzily:
    keyword : "Keyword"
    volume  : "Volume" | "Search Volume"
    kd      : "Keyword Difficulty" | "KD" | "KD %" | "Difficulty"
    cpc     : "CPC" | "CPC (USD)" | "CPC ..."

Output (stdout): a JSON array of merged rows — every raw keyword, with volume/kd/
cpc filled where Semrush had a match (blank otherwise). Pass this to the LLM /
score-keywords.py. Match rate is reported on stderr.

Usage:
    python merge-semrush.py --raw keywords-raw.csv --semrush _semrush/*.csv > merged.json
    python merge-semrush.py --raw keywords-raw.csv --semrush a.csv b.csv > merged.json
"""

import argparse
import csv
import glob
import json
import sys

# Header aliases (lowercased, stripped) → canonical metric name.
HEADER_ALIASES = {
    "keyword": "keyword", "keywords": "keyword",
    "volume": "volume", "search volume": "volume", "avg. search volume": "volume",
    "keyword difficulty": "kd", "kd": "kd", "kd %": "kd", "difficulty": "kd",
    "cpc": "cpc", "cpc (usd)": "cpc", "cpc usd": "cpc",
}

def _sniff_reader(path):
    """Open a CSV/TSV and return a DictReader, detecting delimiter."""
    f = open(path, newline="", encoding="utf-8-sig")
    sample = f.read(4096)
    f.seek(0)
    delim = "\t" if sample.count("\t") > sample.count(",") else ","
    return csv.DictReader(f, delimiter=delim), f


def _map_headers(fieldnames):
    """Map a file's headers to canonical metric names via aliases."""
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


def load_semrush(paths):
    """Return {lowercase keyword: {volume, kd, cpc}} from all export files."""
    metrics = {}
    files = []
    for p in paths:
        files.extend(sorted(glob.glob(p)) or ([p] if p else []))

    for path in files:
        try:
            reader, fh = _sniff_reader(path)
        except OSError as e:
            print(f"  ⚠ cannot open {path}: {e}", file=sys.stderr)
            continue
        with fh:
            hmap = _map_headers(reader.fieldnames)
            if "keyword" not in hmap.values():
                print(f"  ⚠ {path}: no Keyword column found "
                      f"(headers: {reader.fieldnames}) — skipped", file=sys.stderr)
                continue
            rows = 0
            for r in reader:
                rec = {}
                kw = ""
                for orig, canon in hmap.items():
                    val = r.get(orig, "")
                    if canon == "keyword":
                        kw = str(val).strip()
                    else:
                        rec[canon] = _clean_num(val)
                if kw:
                    metrics.setdefault(kw.lower(), {}).update(
                        {k: v for k, v in rec.items() if v != ""}
                    )
                    rows += 1
            print(f"  · {path}: {rows} rows", file=sys.stderr)
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge Semrush export onto raw keywords")
    ap.add_argument("--raw", required=True, help="N2 keywords-raw.csv")
    ap.add_argument("--semrush", nargs="+", required=True,
                    help="Semrush export CSV(s); globs allowed")
    args = ap.parse_args()

    metrics = load_semrush(args.semrush)

    out, matched = [], 0
    with open(args.raw, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            kw = (r.get("keyword") or "").strip()
            if not kw:
                continue
            row = dict(r)
            m = metrics.get(kw.lower())
            if m:
                matched += 1
                for k in ("volume", "kd", "cpc"):
                    if k in m:
                        row[k] = m[k]
            row.setdefault("volume", "")
            row.setdefault("kd", "")
            row.setdefault("cpc", "")
            out.append(row)

    total = len(out)
    rate = (100.0 * matched / total) if total else 0.0
    print(f"\n✅ Merged Semrush metrics: {matched}/{total} keywords matched "
          f"({rate:.0f}%), {len(metrics)} unique Semrush keywords loaded.",
          file=sys.stderr)
    if rate < 30 and total:
        print("   ⚠ Low match rate — check the export's keyword phrasing/locale "
              "matches the raw set, or the right CSV was passed.", file=sys.stderr)

    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
