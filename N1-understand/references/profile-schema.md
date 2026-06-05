# Profile Schema + JTBD Framework — node N1

Reference for `N1-understand`. SKILL.md holds the *workflow*; this file
holds the *thinking framework* and the exact output schema.

## Core premise

A new SaaS has ~zero brand volume. Users type the **problem they have right
before they need the product**, not the product name. N1's whole job: from the
site's own content, reconstruct *what situation the user is in* and *what they'd
type in that moment* — as a structured profile that grounds every later node.

This is a hypothesis set, not validated volume. Volume/difficulty come later
(N3, via Semrush). N1 decides **what we even believe about the user**.

---

## The JTBD frame (how to derive scenarios)

For each capability the product offers, answer:

- **Who** is the user? (e.g. first-time foreign traveler to China)
- **When / what trigger?** the moment of need — "just booked tickets",
  "1-2 weeks before flying", "at the airport mid-transit".
- **What are they anxious about / trying to accomplish?** the *need*.
- **What would they type** to resolve it right then?

Write a scenario as `situation + timing`, concrete, not a demographic.
- Good: `出发前 1-2 周 / 担心支付不通`
- Bad: `年轻游客`

One capability usually spawns several scenarios at different funnel distances
(researching → comparing → deciding). That spread feeds N2's expansion and N3's
funnel layering.

---

## Output schema — product-profile.json

Written by `write-profile.py`. Stable key order:

| key | type | meaning |
|---|---|---|
| `site` | str (required) | domain, e.g. `chinaready.org` |
| `source_url` | str | the URL analyzed |
| `generated` | str | ISO date, auto-filled |
| `value_prop` | str (required) | one line, in searcher terms: what it does for whom |
| `icp` | list of `{who, anxiety}` | ideal-customer segments + their core anxiety |
| `scenarios` | list of `{situation, questions:[...]}` | JTBD moments + what they'd type |
| `pain_points` | list of str | the anxieties the product resolves |
| `core_offers` | list of str or `{name, path}` | the pages/tools that resolve them; free tools first |
| `site_pages` | list of `{url, theme}` | sitemap inventory — used by N5 for internal-link planning |
| `seed_keywords` | list (required) | `{keyword, layer, cluster, landing_page}` — seeds for N2 |
| `assumptions` | list of str | explicit inferences made when info was missing |

### seed_keywords fields

| field | values | meaning |
|---|---|---|
| `keyword` | searcher's language | a broad, productive probe phrase (NOT long-tail) |
| `layer` | core / scenario / pain | which kind of seed it is |
| `cluster` | short slug: `vpn-internet`, `payments`, `transit-visa`, `esim`, `apps`, `navigation`, `checklist` | topic group, reused across nodes |
| `landing_page` | path, e.g. `/transit-checker` | best existing page, blank if none (a gap) |

---

## Worked example (ChinaReady)

```json
{
  "site": "chinaready.org",
  "value_prop": "Before you land in China, check whether your payment, internet, visa and essential apps are ready.",
  "icp": [
    { "who": "first-time foreign tourist to China", "anxiety": "will my cards, phone and apps even work after I land" },
    { "who": "short-layover transit passenger", "anxiety": "do I actually qualify for 240-hour visa-free transit" }
  ],
  "scenarios": [
    { "situation": "just booked tickets / 1-2 weeks before flying", "questions": ["do i need a vpn in china", "can tourists use alipay"] },
    { "situation": "comparing connectivity options", "questions": ["esim or vpn for china"] }
  ],
  "pain_points": ["payments don't work", "Google/Maps blocked", "visa/transit rules unclear"],
  "core_offers": [
    { "name": "240-hour transit checker", "path": "/transit-checker" },
    { "name": "eSIM vs VPN checker", "path": "/esim-vpn-checker" }
  ],
  "seed_keywords": [
    { "keyword": "china vpn", "layer": "pain", "cluster": "vpn-internet", "landing_page": "/esim-vpn-checker" },
    { "keyword": "alipay for tourists", "layer": "scenario", "cluster": "payments", "landing_page": "/guides/how-to-set-up-alipay-wechat-pay-as-tourist" },
    { "keyword": "china 240 hour transit visa", "layer": "core", "cluster": "transit-visa", "landing_page": "/transit-checker" }
  ],
  "assumptions": ["Audience is English-speaking inbound tourists; keywords written in English accordingly."]
}
```

---

## Quality bar

- Every seed traces to observable site content, or is flagged in `assumptions`.
- Seeds are **broad probes**, not pre-expanded long-tail (don't list
  `do i need a vpn in china 2026` here — N2 will harvest it from `china vpn`).
- Scenarios are situations, not demographics.
- Free tools / interactive pages are always captured as `core_offers` — they are
  the highest-intent landing targets for the whole chain.
