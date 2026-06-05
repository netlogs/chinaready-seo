#!/usr/bin/env python3
"""
Write a structured product profile to product-profile.json (node N1).

The analyst (LLM) reads the fetched site JSON and reasons out the profile —
value proposition, ICP, JTBD scenarios, pain points, core offers, and seed
keywords. This script owns only the mechanical part: validating that required
keys are present, normalizing shapes, filling optional fields, and writing
stable pretty UTF-8 JSON. Keeping serialization here guarantees N2/N3/N5 can
rely on a fixed schema.

Input (stdin): a JSON object. Required top-level keys:
    site            (str)   domain, e.g. "chinaready.org"
    value_prop      (str)   one line: what it does for whom, in searcher terms
    seed_keywords   (list)  list of {keyword, layer, cluster, landing_page?}
                            or bare strings (coerced to {keyword})

Recommended keys (filled empty if absent):
    icp             (list of {who, anxiety})
    scenarios       (list of {situation, questions:[...]})
    pain_points     (list of str)
    core_offers     (list of str  OR  {name, path})
    site_pages      (list of {url, theme})   from sitemap, for N5 internal links
    assumptions     (list of str)            explicit inferences made
    source_url      (str)

Usage:
    python write-profile.py < profile.json
    python write-profile.py --output runs/2026-06-04_chinaready/N1_product-profile.json < profile.json

Default output: ./seo-grow/product-profile.json
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REQUIRED = ["site", "value_prop", "seed_keywords"]
VALID_LAYERS = {"core", "scenario", "pain", "核心词", "场景词", "痛点词"}

def _norm_seed(item) -> dict:
    """Coerce a seed (str or dict) into {keyword, layer, cluster, landing_page}."""
    if isinstance(item, str):
        return {"keyword": item.strip(), "layer": "", "cluster": "", "landing_page": ""}
    if isinstance(item, dict):
        return {
            "keyword": str(item.get("keyword", item.get("seed", ""))).strip(),
            "layer": str(item.get("layer", "")).strip(),
            "cluster": str(item.get("cluster", "")).strip(),
            "landing_page": str(item.get("landing_page", "")).strip(),
        }
    return {"keyword": "", "layer": "", "cluster": "", "landing_page": ""}


def main() -> None:
    ap = argparse.ArgumentParser(description="Write N1 product profile JSON")
    ap.add_argument("--output", "-o", default="seo-grow/product-profile.json")
    args = ap.parse_args()

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: stdin is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, dict):
        print("Error: expected a JSON object (the profile).", file=sys.stderr)
        sys.exit(1)

    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        print(f"Error: missing required key(s): {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    warnings = []

    # Normalize seed_keywords
    seeds_in = data.get("seed_keywords", [])
    seeds, seen = [], set()
    for s in seeds_in:
        ns = _norm_seed(s)
        key = ns["keyword"].lower()
        if not ns["keyword"] or key in seen:
            continue
        seen.add(key)
        if ns["layer"] and ns["layer"] not in VALID_LAYERS:
            warnings.append(f"seed '{ns['keyword']}': unusual layer '{ns['layer']}'")
        seeds.append(ns)

    if not seeds:
        print("Error: seed_keywords produced no valid entries.", file=sys.stderr)
        sys.exit(1)

    # Assemble the canonical profile with a stable key order.
    profile = {
        "site": str(data["site"]).strip(),
        "source_url": str(data.get("source_url", "")).strip(),
        "generated": str(data.get("generated", date.today().isoformat())),
        "value_prop": str(data["value_prop"]).strip(),
        "icp": data.get("icp", []),
        "scenarios": data.get("scenarios", []),
        "pain_points": data.get("pain_points", []),
        "core_offers": data.get("core_offers", []),
        "site_pages": data.get("site_pages", []),
        "seed_keywords": seeds,
        "assumptions": data.get("assumptions", []),
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"✅ Wrote product profile → {out_path}", file=sys.stderr)
    print(f"   {len(seeds)} seed keyword(s), {len(profile['scenarios'])} scenario(s), "
          f"{len(profile['icp'])} ICP segment(s)", file=sys.stderr)
    for w in warnings:
        print(f"   ⚠ {w}", file=sys.stderr)
    print("\n   Next: review ICP/scenarios, then feed seed_keywords to "
          "N2-discover.", file=sys.stderr)


if __name__ == "__main__":
    main()
