# seo-audit — Basic Technical SEO Audit (N0)

A lightweight, single-page technical SEO audit skill. It fetches a page, runs
on-page + site-level checks, and renders a structured HTML report. In the
ChinaReady SEO agent chain this is the **N0 side-path**: a one-off technical
health check that is *not* on the keyword-research critical path (N1→N3), but
whose findings (which pages exist, soft-404s, missing trust pages) feed content
planning later.

## What it does

- **On-page checks** — title, meta description, headings, canonical, robots,
  Open Graph, structured data, etc.
- **Site-level checks** — sitemap, robots.txt, indexability signals.
- **Schema checks** — structured-data presence/validity.
- **Output** — a readable HTML report saved to `reports/<hostname>-<slug>-audit.html`
  (the skill never prints raw HTML to the terminal).

## Scripts

| Script | Role |
|--------|------|
| `scripts/fetch-page.py` | Fetch a page's HTML/headers |
| `scripts/check-page.py` | On-page SEO checks |
| `scripts/check-site.py` | Site-level checks (sitemap/robots/indexability) |
| `scripts/check-schema.py` | Structured-data checks |
| `assets/report-template.html` | The report template the LLM fills |
| `references/REFERENCE.md` | Check definitions and thresholds |

## Usage

In Claude Code: "audit this page" / "SEO check <url>" / "quick SEO check".
This is the default, fast entry point.

## Note on the sibling skill

`SKILL.md` references a deeper variant, **`seo-audit-full`** (technical/advanced
audits), for when the user asks for a "deep audit" or "full report". That sibling
skill is **not included in this repo** — only `seo-audit` (the basic/default
audit) was requested. If you want the full chain to offer the upgrade path, add
`seo-audit-full` separately.

## Install

```bash
cp -r seo-audit ~/.claude/skills/
```

Dependency: `pip install requests`.
