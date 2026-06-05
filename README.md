# ChinaReady SEO Agent — Skills

A chain of Claude Code skills that turns a product website into a demand-validated,
prioritized keyword plan. Built for [ChinaReady](https://chinaready.org) but
site-agnostic. Each node is one skill; nodes communicate only through files on
disk, and a human reviews between them.

```
                ┌─ N0 side-path: technical health check ─┐
                │            seo-audit → audit.html        │
官网 URL ─▶ N1-understand ─▶ N2-discover ─▶ N3-classify ─▶ (N4-report) ─▶ (N5-brief)
              product-          keywords-       keywords-
              profile.json      raw.csv         scored.csv
                                (含 volume/kd)
                                   ▲
                            人工导 Semrush
                         (关键词变化 + 问题)
```

## Nodes

| Node | Skill | Job | Input | Output |
|------|-------|-----|-------|--------|
| N0 | `seo-audit` | Single-page technical SEO health check (side-path) | page URL | `audit.html` report |
| N1 | `N1-understand` | Site → structured product profile + short-root seeds | homepage URL | `product-profile.json` |
| N2 | `N2-discover` | Gate seeds by volume, then expand survivors via Semrush variations/questions | seeds | `keywords-raw.csv` (with volume/kd/cpc) |
| N3 | `N3-classify` | Layer intent, route page type, score & prioritize | `keywords-raw.csv` | `keywords-scored.csv` |

`seo-audit` (N0) is a side-path: it's not on the keyword-research critical path
(N1→N3), but it's the recommended first run on a new site, and its findings feed
later content planning. See [`seo-audit/README.md`](seo-audit/README.md).

## Design

- **Paid data (Semrush) is the discovery engine at N2**, not an after-the-fact
  patch. Each Semrush "Keyword Variations / Questions" row carries real volume +
  KD, so the keyword set is demand-validated from the start. Free Google
  Autocomplete (`expand-keywords.py`) is a fallback only.
- **Manual phase now, API later.** No Semrush API yet — the user exports CSVs and
  the skill ingests them (`ingest-semrush.py`, handles Chinese Semrush headers).
  The Semrush API will later replace the manual export with the same output shape.
- **English first; multilingual second.** Run English to completion, find the
  winners, then translate *those* into other languages — not dead seeds.
- **Scripts are deterministic; the LLM judges.** Scoring/serialization live in
  scripts so every run is consistent; the LLM supplies intent, page-type routing,
  and relevance filtering.

## Install

Drop the skill folders into your skills directory:

```bash
cp -r seo-audit N1-understand N2-discover N3-classify ~/.claude/skills/
```

Dependency: `pip install requests` (used by seo-audit and the N2 Autocomplete
fallback).

## Usage

In Claude Code: "use N1-understand to analyze chinaready.org", then
"use N2-discover", then "use N3-classify". Each skill's `SKILL.md` documents its
workflow, scripts, and the manual Semrush handoff points.
