# Design plan — FraudGraph AI

## Subject
An investigator's console for a financial-crime analyst: dense transaction
tables, a network graph, risk scores, case-style ring reports. The audience
works in bank compliance / fraud-ops teams — not consumers. Tone: precise,
forensic, quiet confidence — closer to an intelligence dashboard or an audit
tool than a consumer fintech app.

## Color (4-6 tokens)
- `--ink: #0E1420`      near-black navy — primary text, headers
- `--paper: #F6F5F1`    warm bone paper — page background (not pure white, not cream/#F4F1EA)
- `--panel: #FFFFFF`    card surfaces
- `--line: #DAD7CE`     hairline borders on paper
- `--signal: #C4491D`   burnt vermilion — the one alert/action color (rings, high risk)
- `--wire: #1B6B5A`     deep teal-green — graph edges / "normal flow", used sparingly as a second accent
Risk tiers reuse ink/wire/signal at different weights rather than adding a
fourth semantic color: low = ink at low opacity, medium = ink solid, high = signal.

## Type
- Display/headers: "Fraction Mono" fallback → since custom fonts aren't guaranteed,
  use a real Google Font: **Spectral** (serif, slab-like weight contrast) for headings —
  gives the "case file" gravity without being a generic display serif.
- Body/UI/data: **IBM Plex Sans** — built for dashboards, has a mono sibling.
- Data/numbers/ring codes: **IBM Plex Mono** — transaction IDs, account codes, risk scores
  get tabular figures so columns align.
Type scale: 13/15/18/24/34/52, line-height 1.5 body / 1.15 headings.

## Layout
Left-aligned throughout (this is a working tool, not a marketing page).
Landing page: a single wide hero built from a live-feeling animated transaction
diagram (three nodes, money looping) rather than a big-number hero — the loop
*is* the product's idea, shown not told.

```
┌────────────────────────────────────────────┐
│ FRAUDGRAPH · nav                            │
├────────────────────────────────────────────┤
│  H1: the idea, in one line                  │
│  [diagram: A→B→C→A, drawn once on load]     │
│  three short proof points, left column      │
├────────────────────────────────────────────┤
│  "why individual checks miss it" — 2 col    │
│  before/after: flat list vs graph           │
├────────────────────────────────────────────┤
│  pipeline strip (5 stage labels, one rule)  │
└────────────────────────────────────────────┘
```
App shell: fixed left icon+label rail (not a hamburger), content in a
max-width working column, tables get full bleed inside cards so numeric
columns aren't cramped.

## Principles
1. The transaction loop (A→B→C→A) is the one recurring visual motif — it
   appears once, large, on the landing page, and small as a glyph in the
   product mark. Nowhere else.
2. No card-soup: only rings/alerts get a border in `--signal`; everything
   else is separated by hairlines, not shadows.
3. Numbers are set in Plex Mono with tabular-nums; every score has its
   0-100 bar drawn as a simple inline rule, not a gauge/donut widget.
4. Motion: exactly one animated sequence (the landing hero loop drawing
   itself). Nothing else moves on load; hover states are instant, not eased.

## Self-check against generic defaults
- Not cream+terracotta+serif (#39 trait 1): paper is bone-grey #F6F5F1, accent
  is vermilion #C4491D, not the Claude-adjacent #D97757 clay.
  → checked: distinct hue and value.
- Not SaaS-card-kit: rejected rounded-corner shadow cards; using flat panels
  with 1px hairlines and a signal-colored left border only for alerts.
- No ALL-CAPS eyebrows, no "01/02/03" step numbers except the pipeline strip,
  which genuinely is a sequence.
