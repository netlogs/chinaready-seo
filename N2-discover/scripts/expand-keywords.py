#!/usr/bin/env python3
"""
Expand seed keywords into a long-tail set using REAL search signals — across
LANGUAGES, not just countries (node N2).

Why this matters: a German traveler searching for a China eSIM does not type
"china esim for tourists" — they type "china esim für touristen" or
"china esim mit nummer". A French one types "esim chine pas cher". The keyword
itself is in their language. Capturing that means probing Google Autocomplete
with (a) seeds translated into the target language and (b) question/comparison/
modifier templates ALSO translated — under that language's hl/gl. Every row
returned is a query real users in that locale actually type.

Two input modes:

  1. LOCALES MODE (multilingual) — `--locales-file locales.json`:
     Full control. Each locale carries its own language, country, translated
     seeds, and translated probe templates. This is how you get true
     localization (de/fr/es/...). The LLM produces this file (it does the
     translation); the script just executes the probes.

  2. SIMPLE MODE (single language) — positional seeds or `--seeds-file` +
     `--gl us,gb`:  English seeds, English templates, one locale per --gl
     country (the geo axis only). Backward-compatible; good for English markets.

Output: keywords-raw.csv with columns
    keyword, seed, layer, source, country, lang, cluster

This is discovery only. Intent layering / difficulty / scoring happen in N3.

Usage:
    # multilingual
    python expand-keywords.py --locales-file locales.json --depth base \
        --output runs/2026-06-04_chinaready/N2_keywords-raw.csv

    # simple English, multiple countries
    python expand-keywords.py "china vpn" "alipay for tourists" --gl us,gb,in

Dependencies: pip install requests
"""

import argparse
import csv
import json
import string
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests required. pip install requests", file=sys.stderr)
    sys.exit(1)

AUTOCOMPLETE_URL = "https://suggestqueries.google.com/complete/search"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Output schema — fixed column order. N3 reads this file.
COLUMNS = ["keyword", "seed", "layer", "source", "country", "lang", "cluster"]

# Default English probe templates (SIMPLE MODE / fallback). {s} = seed phrase.
# In LOCALES MODE these are overridden per-locale with translated templates.
DEFAULT_TEMPLATES = {
    "question": [
        "do i need {s}", "can i {s}", "can tourists {s}", "how to {s}",
        "is {s}", "what is {s}", "do you need {s}", "why {s}", "when {s}",
    ],
    "comparison": [
        "{s} vs", "{s} or", "best {s}", "{s} alternative", "is {s} better",
    ],
    "modifier": [
        "{s} for tourists", "{s} for foreigners", "{s} 2026", "{s} free",
        "{s} without", "{s} app", "{s} reddit", "{s} step by step", "{s} guide",
    ],
}


def _build_probes(seed: str, templates: dict, depth: str) -> list:
    """Return (probe_query, source_label) pairs for one seed under one locale.

    `templates` maps source-label -> list of templates with a {s} slot.
    depth='base' uses the templates; depth='full' also adds a-z alphabet soup.
    """
    seed = seed.strip()
    probes = [(seed, "base")]
    for source, tmpls in templates.items():
        for t in tmpls:
            probes.append((t.format(s=seed), source))
    if depth == "full":
        probes += [(f"{seed} {c}", "alphabet") for c in string.ascii_lowercase]
    return probes


def fetch_suggestions(query: str, gl: str, hl: str, timeout: int = 12) -> list:
    """Query Google Autocomplete once; return the list of completion strings.

    client=firefox returns: [ query, [completions...], [], {meta} ]. hl sets the
    language of the suggestions, gl the country. Returns [] on any error.
    """
    params = {"client": "firefox", "q": query}
    if hl:
        params["hl"] = hl
    if gl:
        params["gl"] = gl
    try:
        resp = requests.get(
            AUTOCOMPLETE_URL, params=params,
            headers={"User-Agent": USER_AGENT}, timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        data = json.loads(resp.text)
        if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
            return [str(s).strip() for s in data[1] if str(s).strip()]
    except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError):
        return []
    return []


def _seed_objs(raw) -> list:
    """Coerce a seeds list (strings or dicts) into [{keyword, layer, cluster}]."""
    out, seen = [], set()
    for item in raw or []:
        if isinstance(item, str):
            kw, layer, cluster = item.strip(), "", ""
        elif isinstance(item, dict):
            kw = str(item.get("keyword", item.get("seed", ""))).strip()
            layer = str(item.get("layer", "")).strip()
            cluster = str(item.get("cluster", "")).strip()
        else:
            continue
        if kw and kw.lower() not in seen:
            seen.add(kw.lower())
            out.append({"keyword": kw, "layer": layer, "cluster": cluster})
    return out


def _load_locales(args) -> list:
    """Build the list of locale configs to run.

    LOCALES MODE (--locales-file): a JSON list of locale objects, each:
        {
          "lang": "de",                  # hl code
          "country": "de",               # gl code
          "seeds": [ "china esim", {"keyword": "...", "layer": "...", "cluster": "..."} ],
          "templates": {                 # optional; translated probe templates
              "question":   ["brauche ich {s}", "wie {s}", ...],
              "comparison": ["{s} oder", "beste {s}", ...],
              "modifier":   ["{s} für touristen", "{s} 2026", ...]
          }
        }
    Missing `templates` falls back to DEFAULT_TEMPLATES (English) — only sensible
    for English locales.

    SIMPLE MODE (positional seeds / --seeds-file + --gl): one locale per --gl
    country, all sharing the same English seeds and DEFAULT_TEMPLATES.
    """
    if args.locales_file:
        with open(args.locales_file, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("locales", [])
        locales = []
        for loc in data:
            seeds = _seed_objs(loc.get("seeds", []))
            if not seeds:
                continue
            templates = loc.get("templates") or DEFAULT_TEMPLATES
            # keep only known source buckets, ensure list values
            templates = {k: list(v) for k, v in templates.items()
                         if k in DEFAULT_TEMPLATES and isinstance(v, list)}
            if not templates:
                templates = DEFAULT_TEMPLATES
            locales.append({
                "lang": str(loc.get("lang", "")).strip(),
                "country": str(loc.get("country", "")).strip(),
                "seeds": seeds,
                "templates": templates,
            })
        return locales

    # SIMPLE MODE
    raw = []
    if args.seeds_file:
        with open(args.seeds_file, encoding="utf-8") as f:
            sf = json.load(f)
        raw = sf.get("seeds", sf.get("keywords", [])) if isinstance(sf, dict) else sf
    seeds = _seed_objs(list(raw) + list(args.seeds or []))
    countries = [c.strip() for c in args.gl.split(",") if c.strip()] or [""]
    return [{"lang": args.hl, "country": c, "seeds": seeds,
             "templates": DEFAULT_TEMPLATES} for c in countries]


def main() -> None:
    p = argparse.ArgumentParser(
        description="Expand seeds into long-tail via Google Autocomplete (multilingual)"
    )
    p.add_argument("seeds", nargs="*", help="Seed keywords (SIMPLE mode)")
    p.add_argument("--seeds-file", help="JSON seeds file (SIMPLE mode)")
    p.add_argument("--locales-file",
                   help="JSON locales file (LOCALES mode: per-language seeds + "
                        "translated templates). Overrides seeds/--gl/--hl.")
    p.add_argument("--gl", default="us",
                   help="SIMPLE mode: comma-separated country codes (default us)")
    p.add_argument("--hl", default="en",
                   help="SIMPLE mode: suggestion language (default en)")
    p.add_argument("--depth", choices=["base", "full"], default="base",
                   help="'base' = translated templates; 'full' = also a-z soup")
    p.add_argument("--output", "-o", default="seo-grow/keywords-raw.csv")
    p.add_argument("--sleep", type=float, default=0.4,
                   help="Delay between requests, seconds (default 0.4)")
    args = p.parse_args()

    locales = _load_locales(args)
    if not locales or not any(loc["seeds"] for loc in locales):
        print("Error: no seeds. Use positional seeds, --seeds-file, or "
              "--locales-file.", file=sys.stderr)
        sys.exit(1)

    harvested = {}   # lowercase keyword -> row (dedup, first origin wins)
    total_calls = 0

    for loc in locales:
        lang, country = loc["lang"], loc["country"]
        tag = f"{lang or '-'}/{country or '-'}"
        loc_count_before = len(harvested)
        for seed in loc["seeds"]:
            probes = _build_probes(seed["keyword"], loc["templates"], args.depth)
            for probe_query, source in probes:
                completions = fetch_suggestions(probe_query, country, lang)
                total_calls += 1
                for c in completions:
                    key = (c.lower(), lang)   # same string in 2 langs = 2 rows
                    if key in harvested:
                        continue
                    harvested[key] = {
                        "keyword": c, "seed": seed["keyword"], "layer": seed["layer"],
                        "source": source, "country": country, "lang": lang,
                        "cluster": seed["cluster"],
                    }
                if args.sleep:
                    time.sleep(args.sleep)
        print(f"  · locale {tag}: +{len(harvested) - loc_count_before} keywords "
              f"({len(loc['seeds'])} seeds)", file=sys.stderr)

    # Ensure every seed is present even if Autocomplete added nothing for it.
    for loc in locales:
        for s in loc["seeds"]:
            key = (s["keyword"].lower(), loc["lang"])
            if key not in harvested:
                harvested[key] = {
                    "keyword": s["keyword"], "seed": s["keyword"], "layer": s["layer"],
                    "source": "seed", "country": loc["country"], "lang": loc["lang"],
                    "cluster": s["cluster"],
                }

    rows = sorted(harvested.values(),
                  key=lambda r: (r["lang"], r["seed"].lower(), r["keyword"].lower()))

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    langs = sorted({r["lang"] for r in rows})
    print(f"\n✅ Wrote {len(rows)} keywords across {len(langs)} language(s) "
          f"[{', '.join(l or '-' for l in langs)}], {total_calls} calls "
          f"→ {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
