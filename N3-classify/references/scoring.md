# Scoring Framework — node N3

Reference for `N3-classify`. SKILL.md holds the *workflow*; this file
defines the intent/funnel framework, difficulty bands, the scoring formula, and
the output schema.

## What N3 decides

N2 produced real keywords — in the Semrush flow, each already carrying volume/KD/
CPC. N3 answers two things: **which to write first** (priority score) and **what
page type carries each** (the routing N4/N5 act on). It uses Semrush KD/volume
directly when present, and degrades to intent + LLM difficulty when N2 fell back
to Autocomplete. Output is a ranked, routed, prioritized CSV that feeds N4
(report) and N5 (briefs).

---

## Intent layers (`intent`)

| intent | searcher wants | typical pattern | weight |
|---|---|---|---:|
| `transactional` | act / use a tool / get a thing | "X checker", "X calculator", "download X", "best X" | 1.00 |
| `comparison` | choose between options | "X vs Y", "X or Y", "best X for Y" | 0.80 |
| `question` | a direct yes/no or fact | "do I need X", "can I X", "is X allowed" | 0.65 |
| `informational` | learn / understand | "how X works", "X explained", "X guide" | 0.45 |
| `navigational` | reach a specific brand | brand names (low value for a new SaaS) | 0.20 |

**Judge by meaning, across languages.** `chine sans visa combien de temps`
("how long China without visa") is a `question`, exactly like its English twin.
`beste china esim` is `comparison`. Use the `lang` column as context, never
pattern-match only English words. N2's `semrush_intent` column is a useful
**prior** (Semrush's own intent label), but the LLM makes the final call.

## Funnel stage (`funnel`)

- `TOFU` — broad awareness, just realizing the problem. (score −0.10)
- `MOFU` — actively researching / comparing. (neutral)
- `BOFU` — ready to act; highest conversion (tool/checker/very specific
  long-tail). (score +0.10)

For a new SaaS, **BOFU + the product's free tools are the fastest wins** — low
volume, high conversion, low competition.

## Target page type (`target_page_type`)

Drives N5's content plan. One of:

- `tool` — maps to a free tool/checker (highest conversion). e.g. transit
  eligibility, esim/vpn recommendation.
- `comparison` — "X vs Y" decision pages.
- `pillar` — the big canonical guide for a core term.
- `blog` — a specific long-tail question/how-to article.
- `faq` — short Q&A, good for FAQ-schema and AI-citation (GEO).

---

## Difficulty (`serp_difficulty`, `serp_signal`)

Bands: `easy` / `medium` / `hard`. Two sources, in priority order:

1. **Semrush KD** (carried from N2): KD ≤ ~30 → easy, ~30-50 → medium, > 50 →
   hard. Authoritative; used directly and overrides any estimate.
2. **LLM estimate** (only for rows without KD, e.g. Autocomplete fallback): reason
   about who owns page 1 for this query in this niche, and record it in
   `serp_signal`:
   - **hard** — gov sites, Trip.com/Klook/big OTAs, major media own the page
     (e.g. `china visa free`, `best time to visit china`).
   - **medium** — a mix of mid-size blogs + some brands.
   - **easy** — only forum threads (Reddit/Quora), thin/outdated blogs, or the
     query is a narrow localized long-tail nobody targeted
     (`china esim mit nummer`, `chine sans visa pour les français`).

Free live SERP scraping is deliberately not used — Google's SERP HTML is
JS-gated, so it returns nothing reliable. A paid SERP API is the future upgrade.
Flag any low-confidence difficulty call in `note`.

---

## Scoring formula

`score-keywords.py` computes a 0-100 score from three components, each 0-1:

```
intent_weight = INTENT_WEIGHT[intent] + FUNNEL_ADJUST[funnel]   (clamped 0-1)
ease          = 1 - KD/100            (if Semrush KD present)
              | DIFFICULTY_EASE[band] (else: easy .85 / medium .55 / hard .25)
demand        = log10(volume+1) / log10(maxVolume+1)   (if volume present)

score = 100 * ( 0.45*intent_weight + 0.30*ease + 0.25*demand )
```

**Graceful degradation:** when `volume` is absent (N2 used the Autocomplete
fallback), `demand` drops out and the remaining weights renormalize (0.45/0.30 →
0.60/0.40), so free-data scores stay comparable to Semrush-backed ones. This is
what keeps the node working with or without paid data.

### Priority bands

Off the score, with a hard rule that protects clear wins:

- **Win rule:** a `transactional`/`comparison` or `BOFU` keyword **with an
  existing landing page** and easy/medium difficulty (KD ≤ 50) → at least `P1`,
  `P0` if score ≥ 60. These are the do-first opportunities for a new SaaS.
- Otherwise: score ≥ 70 → `P0`, ≥ 50 → `P1`, else `P2`.

Weights live in `score-keywords.py` (`W_INTENT/W_EASE/W_DEMAND`,
`INTENT_WEIGHT`, etc.) — tune in one place; every run stays consistent.

---

## Output schema — keywords-scored.csv

| column | source | meaning |
|---|---|---|
| `keyword` | N2 | the query |
| `lang` | N2 | language harvested in |
| `cluster` | N2 | topic group |
| `intent` | LLM | transactional/comparison/question/informational/navigational |
| `funnel` | LLM | TOFU/MOFU/BOFU |
| `serp_difficulty` | LLM or KD | easy/medium/hard |
| `serp_signal` | LLM | one-line reason for the difficulty call |
| `volume` | N2/Semrush | monthly search volume (blank only on Autocomplete fallback) |
| `kd` | N2/Semrush | keyword difficulty 0-100 (blank only on Autocomplete fallback) |
| `cpc` | N2/Semrush | cost per click (blank only on Autocomplete fallback) |
| `target_page_type` | LLM | tool/comparison/pillar/blog/faq |
| `landing_page` | LLM | best existing page path, blank = content gap |
| `score` | script | 0-100 priority score |
| `priority` | script | P0/P1/P2 |
| `note` | LLM | caveats, gaps, low-confidence flags |

---

## Quality bar

- A good P0 row reads: *this kind of searcher, in this language, wants to act,
  the page exists, and nobody strong owns the SERP.*
- Always surface high-value keywords with **no** landing page — those are the
  content gaps N5 should fill first.
- Don't let raw volume dominate: a high-volume `informational`/`hard` head term
  (`china travel`) should rank below a low-volume `transactional`/`easy`
  long-tail with a matching tool. The weights are tuned for this; trust them.
