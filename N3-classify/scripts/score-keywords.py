#!/usr/bin/env python3
"""
Score and prioritize keywords; write keywords-scored.csv (node N3, final step).

The LLM does the judgment (intent, funnel, target page type, difficulty band,
notes) and hands this script a JSON array of per-keyword rows. This script owns
the *deterministic* part: the scoring formula and CSV serialization. Keeping the
formula here means every run scores consistently and the weights live in one
tunable place.

Scoring (0-100). Three components, each 0-1, then weighted:

    intent_weight   transactional/BOFU tool queries score highest (fast wins for
                    a new SaaS); informational/TOFU lowest.
    ease            inverse of difficulty. Prefer KD from Semrush when present;
                    else use the SERP difficulty band; else neutral 0.5.
    demand          volume signal when Semrush is merged; else neutral (so the
                    score still works on free data alone).

    score = 100 * (W_INTENT*intent_weight + W_EASE*ease + W_DEMAND*demand)

When volume is absent (no Semrush), demand falls back to neutral and the weights
renormalize so the score stays comparable. Priority bands map off the score and
a hard rule: a BOFU/transactional keyword with an existing landing page and
easy/medium difficulty is forced to at least P1 (these are the wins).

Input (stdin): JSON array of objects:
    keyword (req), lang, cluster, intent, funnel, serp_difficulty (easy|medium|
    hard), serp_signal, volume (num), kd (num 0-100), cpc (num),
    target_page_type, landing_page, note

Usage:
    python score-keywords.py < scored-rows.json
    python score-keywords.py --output runs/.../N3_keywords-scored.csv < rows.json

Default output: ./seo-grow/keywords-scored.csv
"""

import argparse
import csv
import json
import sys
from pathlib import Path

COLUMNS = [
    "keyword", "lang", "cluster", "intent", "funnel",
    "serp_difficulty", "serp_signal", "volume", "kd", "cpc",
    "target_page_type", "landing_page", "score", "priority", "note",
]

# Scoring weights (sum to 1.0 when all components present).
W_INTENT, W_EASE, W_DEMAND = 0.45, 0.30, 0.25

# Intent → weight. Combines search-intent and the funnel it usually implies.
# For a new SaaS the fastest wins are transactional/tool + question/comparison.
INTENT_WEIGHT = {
    "transactional": 1.00,
    "comparison": 0.80,
    "question": 0.65,
    "informational": 0.45,
    "navigational": 0.20,
    "": 0.50,
}
# Funnel nudges the intent weight a little (BOFU up, TOFU down).
FUNNEL_ADJUST = {"BOFU": 0.10, "MOFU": 0.0, "TOFU": -0.10, "": 0.0}

DIFFICULTY_EASE = {"easy": 0.85, "medium": 0.55, "hard": 0.25, "": 0.5}


def _num(v):
    """Parse a number from messy CSV/JSON cells; return None if not numeric."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def _ease(row) -> float:
    """Difficulty → ease (0-1). KD from Semrush wins; else SERP band; else 0.5."""
    kd = _num(row.get("kd"))
    if kd is not None:
        return max(0.0, min(1.0, 1.0 - kd / 100.0))
    band = str(row.get("serp_difficulty", "")).strip().lower()
    return DIFFICULTY_EASE.get(band, 0.5)


def _demand(row, vol_stats) -> float:
    """Volume → demand (0-1) via log scaling against the run's max; None if no vol."""
    vol = _num(row.get("volume"))
    if vol is None or vol_stats["max_log"] <= 0:
        return None
    import math
    return max(0.0, min(1.0, math.log10(vol + 1) / vol_stats["max_log"]))


def _intent_weight(row) -> float:
    base = INTENT_WEIGHT.get(str(row.get("intent", "")).strip().lower(), 0.5)
    adj = FUNNEL_ADJUST.get(str(row.get("funnel", "")).strip().upper(), 0.0)
    return max(0.0, min(1.0, base + adj))


def _score_row(row, vol_stats) -> float:
    iw = _intent_weight(row)
    ease = _ease(row)
    demand = _demand(row, vol_stats)
    if demand is None:
        # Renormalize over the two present components so scores stay comparable.
        total = W_INTENT + W_EASE
        s = (W_INTENT * iw + W_EASE * ease) / total
    else:
        s = W_INTENT * iw + W_EASE * ease + W_DEMAND * demand
    return round(100 * s, 1)


def _priority(row, score: float) -> str:
    """Bands off the score, with a hard rule that protects clear BOFU wins."""
    intent = str(row.get("intent", "")).strip().lower()
    funnel = str(row.get("funnel", "")).strip().upper()
    band = str(row.get("serp_difficulty", "")).strip().lower()
    has_page = bool(str(row.get("landing_page", "")).strip())
    kd = _num(row.get("kd"))

    is_bottom = intent in ("transactional", "comparison") or funnel == "BOFU"
    is_winnable = band in ("easy", "medium", "") and (kd is None or kd <= 50)
    if is_bottom and has_page and is_winnable:
        return "P0" if score >= 60 else "P1"

    if score >= 70:
        return "P0"
    if score >= 50:
        return "P1"
    return "P2"


def main() -> None:
    ap = argparse.ArgumentParser(description="Score keywords → keywords-scored.csv")
    ap.add_argument("--output", "-o", default="seo-grow/keywords-scored.csv")
    args = ap.parse_args()

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: stdin is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    if isinstance(payload, dict):
        payload = payload.get("keywords", payload.get("rows", []))
    if not isinstance(payload, list) or not payload:
        print("Error: expected a non-empty JSON array of keyword rows.", file=sys.stderr)
        sys.exit(1)

    import math
    vols = [_num(r.get("volume")) for r in payload if isinstance(r, dict)]
    vols = [v for v in vols if v is not None]
    vol_stats = {"max_log": math.log10(max(vols) + 1) if vols else 0.0}

    rows, seen, skipped = [], set(), 0
    for raw in payload:
        if not isinstance(raw, dict) or not str(raw.get("keyword", "")).strip():
            skipped += 1
            continue
        kw = str(raw["keyword"]).strip()
        lang = str(raw.get("lang", "")).strip()
        key = (kw.lower(), lang)
        if key in seen:
            continue
        seen.add(key)

        score = _score_row(raw, vol_stats)
        out = {c: "" for c in COLUMNS}
        for c in COLUMNS:
            if c in raw and raw[c] is not None:
                out[c] = raw[c]
        out["keyword"], out["lang"] = kw, lang
        out["score"] = score
        out["priority"] = _priority(raw, score)
        rows.append(out)

    rows.sort(key=lambda r: (-float(r["score"]), r["lang"], r["keyword"].lower()))

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})

    from collections import Counter
    pri = Counter(r["priority"] for r in rows)
    with_vol = sum(1 for r in rows if _num(r.get("volume")) is not None)
    print(f"✅ Wrote {len(rows)} scored keyword(s) → {out_path}", file=sys.stderr)
    print(f"   P0={pri['P0']}  P1={pri['P1']}  P2={pri['P2']}  "
          f"| Semrush volume on {with_vol}/{len(rows)}", file=sys.stderr)
    if skipped:
        print(f"   Skipped {skipped} row(s) with empty keyword", file=sys.stderr)


if __name__ == "__main__":
    main()
