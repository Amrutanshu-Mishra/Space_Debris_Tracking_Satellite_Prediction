# PRAHARI — console design plan

Operator console for space situational awareness. Shows upcoming close
approaches between catalogue objects so an operator can decide whether to
manoeuvre.

## The one problem this design exists to solve

Every `ConjunctionEvent` carries **two independent axes** that the schema
keeps separate on purpose and that this UI must never let collapse into one
number or one colour:

| axis | field(s) | question it answers |
|------|----------|---------------------|
| **risk** | `risk_tier` (GREEN/AMBER/RED), `risk_score` 0–1 | how dangerous is the geometry? |
| **confidence** | `confidence` 0–1, `max_epoch_age_hours`, `confidence_note` | how much can the underlying TLE data be trusted? |

A stale-data RED and a fresh-data RED are different operational situations.
Most dashboards have one severity axis. Showing both, legibly, at a glance,
is the entire job. The signature element (§4) is the literal geometric
answer: give the operator two axes and plot every event against both.

Reference vernacular is engineering and charting software — STK read-outs,
aeronautical sectionals, nautical charts, ledger tables — not a consumer
analytics dashboard. Dense, tabular, ruled, monospace numerals, no
decoration.

---

## 1. Colour

Light, warm, paper-like — the palette of a printed chart or a drafting
sheet, chosen deliberately against the "near-black space console with one
glowing accent" cliché. Long shifts reading numerals are easier on a
low-glare warm ground than on black, and the earth-toned tiers below read
as printed chart symbology rather than alert LEDs.

### Base — 6 named values

| token | hex | role & justification |
|-------|-----|----------------------|
| `--paper` | `#F4F1E8` | App background — "the desk". Warm off-white vellum; not white, not black. |
| `--field` | `#FCFBF7` | Table surface and detail read-out panels — a hair brighter than paper so the data table reads as *the instrument* sitting on the desk. |
| `--ink` | `#1A1D21` | Primary text and every numeral. Near-black, slightly warm — the colour of printed technical type, not pure `#000`. |
| `--mute` | `#585E66` | Labels, units, axis captions, timestamps' date portion, secondary rows. Recedes behind the numbers it annotates. |
| `--rule` | `#C9C3B4` | Every hairline: table grid, column dividers, plot axes, panel edges. Structure comes from ruling, never from shadow. |
| `--control` | `#1D4E6B` | Interaction only — focus ring, selected-row edge, active sort column, links. **Rendered as lines and underlines, never as a fill**, so it can never be mistaken for the GREEN tier. |

### Tiers — 3 values

Picked at deliberately *similar* value and chroma so no single tier glows
brighter than the others; the hierarchy is carried by hue meaning and by
the numeric `risk_score`, not by brightness.

| token | hex | `risk_tier` | justification |
|-------|-----|-------------|---------------|
| `--tier-clear` | `#3E7A5E` | `GREEN` | Muted pine. Most events are GREEN — this has to sit calmly in a table that is mostly this colour. Desaturated so a screen full of it is not a screen full of noise. |
| `--tier-caution` | `#B9791F` | `AMBER` | Ochre / burnt caution-yellow. Pure yellow is illegible on paper; ochre holds contrast and still reads as "look at this". |
| `--tier-act` | `#A5301F` | `RED` | Oxide / signal red — a deep brick, not fire-engine vermilion. Serious without being alarmist, and clearly separated from the ochre in both hue and value. |

**Tints** (no new tokens): each tier hue at 8–10% alpha over `--paper`, used
for the `risk_score` cell background in the list and for the single
weighted region of the signature plot. Nothing else gets a fill.

### Dark variant (footnote, not the default)

A "night console" theme swaps `--paper` `#14171A`, `--field` `#1B1F23`,
`--ink` `#E8E4D9`, `--mute` `#9AA0A6`, `--rule` `#3A3F45`; tier hues keep
their identity with chroma lifted ~8%. Only offered because the table
density earns a dark mode — it is not where the design starts.

---

## 2. Type

Two families from one superfamily, so they cohere without friction.

| family | fallback stack | roles |
|--------|----------------|-------|
| **IBM Plex Sans** | `"IBM Plex Sans", system-ui, "Segoe UI", sans-serif` | View titles, nav, column headers, filter controls, `confidence_note` prose, the plain-language decode lines. |
| **IBM Plex Mono** | `"IBM Plex Mono", ui-monospace, "Cascadia Mono", Consolas, monospace` | **Every measured quantity**: miss distance, relative velocity, RTN components, `risk_score`, `confidence`, `max_epoch_age_hours`, timestamps, NORAD IDs, `event_id`. |

This interface is almost entirely numbers, so figure alignment is a
functional requirement, not a flourish. Rules:

- **Every measurement is set in the mono face**, so decimal points align
  down a column and a column becomes scannable at a glance. The monospace
  read-out is also the instrument idiom.
- Numeric columns are **right-aligned**; where a column mixes signs
  (`radial_km`, `in_track_km`, `cross_track_km`) the sign column is
  reserved so digits still align.
- **Fixed decimal places per quantity**, always shown: miss distance 3 dp
  (km), relative velocity 2 dp (km/s), `risk_score` / `confidence` 2 dp,
  `combined_radius_m` 1 dp (m), `max_epoch_age_hours` integer h.
- **Units live once in the column header** (`miss / km`), in `--mute`, not
  repeated per cell. In the detail read-out the unit is a `--mute` suffix.
- Timestamps are ISO-8601 UTC, mono, e.g. `2026-08-27 11:05:06Z`; the date
  portion in `--mute`, the time in `--ink`.
- NORAD IDs are identifiers, not amounts — mono, no thousands separator.
- `font-variant-numeric: tabular-nums` everywhere numbers appear, including
  the Sans headers.

Scale is small and dense: 13 px data rows, 12 px labels/units, 15 px view
titles, 20 px the single value that matters on the detail view
(`risk_score`). Weights: 400 throughout; 600 only for column headers and
for a RED-tier `risk_score` value. No weights below 400.

---

## 3. Layout

### Concept

Two views, one frame. The frame is a single fixed header — product mark
`PRAHARI`, the `PRAHARI_DATA_SOURCE` state (`mock` / `live`) as a bordered
tag, the screening timestamp, and the catalogue funnel
(`pairs_considered`, `pairs_fine_screened`, `events_found`) shown as three
labelled figures in a hairline-ruled row, **no arrows, no middle dots**.
No sidebar — a two-view prototype does not need one.

**List view** is a real data table, full-bleed, no cards, no shadows, rows
separated by `--rule` hairlines at ~28 px height. It is a worklist: the
operator scans it top to bottom. Default sort is `tca` ascending — soonest
approach first. Columns are sortable; the active sort column's header rule
is drawn in `--control`.

The table's **left gutter** is the compact carrier of both axes (§4). To
its right, a persistent panel holds the **Risk–Confidence field** (§4) —
the same panel, unchanged, in both views. It is a control, not a widget
shelf: hovering a row lights its mark in the field; clicking a mark selects
the row.

A filter strip sits between header and table: tier toggles `[G] [A] [R]`,
a `risk ≥` threshold, an `epoch ≤ … h` cap, and a time window. Filtering
never reorders; it only hides.

**Detail view** is a two-column read: a key–value column on the left with
every scalar from the event, decimal-aligned, units in `--mute`; and on the
right the same Risk–Confidence field (now showing just this event's mark
with a dropped crosshair and the two values on the axes) above a small
**RTN miss-geometry plot** — `in_track` × `cross_track` with `radial`
annotated, and `combined_radius_m` drawn as a to-scale circle at the
origin. Two short plain-language lines decode the two axes independently
("geometry is severe." / "data is current.") so neither number is read in
the other's shadow.

### List view wireframe

```
┌──────────────────────────────────────────────────────────────────────────────┬───────────────────────┐
│ PRAHARI   [mock]   screening 2026-08-26 09:00:12Z                             │  Risk–Confidence field│
│   pairs considered     pairs fine-screened     events found                   │                       │
│   4.5e8            │    11,024             │   41                              │  cf 1 ┼───────┬───────┐│
├──────────────────────────────────────────────────────────────────────────────┤     │  ·    │    ▪   ││
│ tier [G][A][R]   risk ≥ 0.00   epoch ≤ — h   window 72 h            41 events  │  .70 ├───────┼───────┤│
├─────┬───────────────────┬──────────────────┬──────────┬────────┬──────┬───────┤     │   ▫   │ ·   ▪  ││
│     │ tca (UTC)         │ primary          │ secondary│ miss   │ rel  │ risk  │  .40 ├───────┼───────┤│
│     │                   │ norad            │ norad    │ / km   │ km/s │  cf   │     │ ▫  ·  │       ││
├─────┼───────────────────┼──────────────────┼──────────┼────────┼──────┼───────┤   0 └───────┴───────┘│
│ █ R │ 2026-08-27 11:05:06│ PSLV R/B        │ COSMOS-  │  0.379 │13.27 │ 0.99  │     0    .40  .70  1 │
│ G→A │   25799            │                 │  5215    │        │      │ 0.84  │          risk_score   │
├─────┼───────────────────┼──────────────────┼──────────┼────────┼──────┼───────┤                      │
│ ▓ R │ 2026-08-27 21:35:44│ YAOGAN-5368     │ SL-16 R/B│  0.493 │13.21 │ 0.91  │  █ solid  cf ≥ .70   │
│ A→R │   16288            │                 │  22912   │        │      │ 0.68  │  ▓ hatch  .40–.70    │
├─────┼───────────────────┼──────────────────┼──────────┼────────┼──────┼───────┤  ░ open   cf < .40   │
│ ░ G │ 2026-08-28 22:27:25│ ARIANE 44 R/B   │ ONEWEB-  │  3.811 │ 1.26 │ 0.18  │                      │
│ R→G │   25545            │                 │  5032    │        │      │ 0.15 ⚠│  glyph colour = tier │
├─────┼───────────────────┼──────────────────┼──────────┼────────┼──────┼───────┤  glyph fill  = conf  │
│ █ G │ 2026-08-26 15:51:23│ IRIDIUM 33 DEB…  │ CZ-4C    │  5.681 │ 1.19 │ 0.03  │  letter G/A/R also   │
│ G→G │   33456            │  DEB 84          │  59442   │        │      │ 0.95  │  states the tier     │
│ …   │                   │                  │          │        │      │       │                      │
└─────┴───────────────────┴──────────────────┴──────────┴────────┴──────┴───────┴──────────────────────┘
   gutter cell = signature stripe:  colour → risk_tier   |   fill (█ ▓ ░) → confidence band
                                    G/A/R letter repeats the tier for colour-blind read
   risk column: risk_score (2 dp, tier-tinted cell) over confidence (2 dp); ⚠ = confidence < .40
```

### Detail view wireframe

```
┌───────────────────────────────────────────────────┬──────────────────────────────────┐
│ ‹ back to screening                               │   Risk–Confidence field          │
│ event 00000016-65dd-4595-a46e-a6725ae86d18        │    cf 1 ┼───────────────┬──────┐  │
├───────────────────────────────────────────────────┤     .70 ├───────────────┼──▣───┤  │
│  R   risk_score 0.99          confidence 0.84      │     .40 ├───────────────┼──────┤  │
│  ──                           ──────────           │      0  └───────────────┴──────┘  │
│  geometry is severe.          data is current.     │         0     .40    .70  .99 1  │
│                                                    │   ▣ this event   0.99 risk / .84 │
│  tca               2026-08-27 11:05:06Z            ├──────────────────────────────────┤
│                    in 26.1 h                       │   RTN miss geometry  (primary RIC)│
│  miss distance          0.379  km                  │            cross-track →          │
│  relative velocity     13.27   km/s                │      ┌─────────────────────┐      │
│  combined radius        12.5   m                   │      │        · (0,0)      │  ↑   │
│                                                    │      │       ◯ r 12.5 m    │ in-  │
│  radial                −0.071  km                  │      │          ✕          │ track│
│  in-track              −0.059  km                  │      └─────────────────────┘      │
│  cross-track            0.367  km                  │   ✕ closest approach, to scale    │
│                                                    │     with hard-body circle ◯      │
│  max epoch age          38.7   h   (stale @ 168)   │     radial −0.071 km (out of page)│
│  ┌───────────────────────────────────────┐         │                                  │
│  │███████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│ 38.7/168│                                  │
│  └───────────────────────────────────────┘         │                                  │
│  confidence_note                                   │                                  │
│  Both TLE epochs are fresh and perigees are above  │                                  │
│  500 km.                                           │                                  │
│                                                    │                                  │
│  screened_at            2026-08-26 09:00:12Z       │                                  │
└───────────────────────────────────────────────────┴──────────────────────────────────┘
```

---

## 4. The signature element — the Risk–Confidence field

**One fixed 2-D field, present unchanged in both views, that plots every
event against both axes at once.**

- **X = `risk_score`** (0 → 1, calm on the left).
- **Y = `confidence`** (0 at the bottom = distrust the data, 1 at the top =
  trust it).
- The field is **ruled into a 3 × 3 grid at the decision thresholds** — X
  at `0.40` and `0.70` (the `RISK_TIER_AMBER/RED` cuts from `scoring.py`),
  Y at `0.40` and `0.70` (fresh / reduced / low confidence bands). The
  operator reads a cell, not a coordinate.
- Every event is a **small square in its tier hue**, dropped at its exact
  `(risk_score, confidence)` inside the cell — so the cell gives the
  category and the position keeps the precision.
- **Only one region carries any weight**: the top-right cell — high risk,
  high confidence, *act now* — is washed with `--tier-act` at ~8% alpha.
  Everywhere else is bare `--field`.
- It is **the navigation control**: hover a table row → its square fills
  and enlarges; click a square → that row selects and scrolls into view.
  In the detail view the field shows this event's square alone, with a
  crosshair dropped to both axes and the two numeric values printed at the
  axis ends.
- No zoom, no pan, no animation, no tooltip cloud, no legend chrome, no
  gradient. A targeting reticle, not an analytics scatter.

Why this is the answer to the brief: the product thesis is "two axes that
must never collapse". The signature literally *is* those two axes. A stale
RED (`#A5301F` square, low on Y) and a fresh RED (`#A5301F` square, high on
Y) are the same colour in different rows of the field — the difference you
cannot see in a one-axis dashboard is the first thing you see here.

### Quiet co-signature: the gutter stripe

The list's left gutter cell encodes the same two axes in one glyph so the
table carries the full story without the field:

- **Glyph colour = `risk_tier`** (`--tier-clear` / `--tier-caution` /
  `--tier-act`).
- **Glyph fill = confidence band**: `█` solid at `confidence ≥ 0.70`, `▓`
  coarse hatch at `0.40–0.70`, `░` open outline below `0.40`. Stale data
  literally looks unresolved — the dashed-contour convention from nautical
  charts, where an unsurveyed line is drawn broken.
- A `G` / `A` / `R` letter under the glyph states the tier without relying
  on colour.

Everything else on the screen stays quiet: no other fills, no other
textures, no other saturated colour, hairline rules only.

---

## 5. Self-critique — would I have built this for any other dashboard?

For each element: is it subject-driven or a generated-design default? What
changed.

**Palette.** A generic dashboard defaults to white-or-near-black with
saturated blue/green/red. Warm drafting-paper with desaturated
oxide/ochre/pine tiers is driven by the charting vernacular and would look
wrong on a generic BI tool — kept. *Risk found in review:* pine
`--tier-clear` (#3E7A5E) and the original interactive blue sat close in
hue and could be confused where both appeared as fills. *Changed:* moved
`--control` to a colder `#1D4E6B` **and** made it a strict lines-only
token — the GREEN tier is always a filled glyph, `--control` is never a
fill — so the two can't collide. Documented in §1.

**Type.** IBM Plex is a common "technical" pick and on its own is a mild
default. *Kept the families but re-anchored the justification* on the
functional requirement — every measurement in the mono face, fixed decimal
places, right-aligned, units hoisted to the header — which is specific to
an all-numbers instrument and is the actual reason, not the family name.
Noted the concrete rule set in §2 so it's enforced, not decorative.

**Layout.** A generic brief gets identical rounded cards with soft grey
shadows. *Changed to* a full-bleed ruled ledger table with hairline
separators, ~28 px rows, zero radius, zero shadow — a worklist, not a card
wall. The one dashboard-shaped move (the persistent right panel) is
justified as a single unchanging control, not a widgets area.

**Signature.** A scatter plot is itself a dashboard cliché. *Changed to
distance it:* ruled to the `scoring.py` decision thresholds rather than to
the data range, snapped to a 3 × 3 decision grid (read a cell, not a
coordinate), stripped of zoom / pan / animation / tooltips / legend, given
exactly one weighted region, and made the primary navigation control
rather than a read-only chart. The exact-position square inside each cell
keeps precision without reintroducing scatter chrome.

**Header funnel.** First draft joined `pairs → screened → events` with
arrows — exactly the "arrows appended" and "meta strings" defaults.
*Changed to* three labelled figures in a hairline-ruled row, label above
value, no arrows, no dots.

**Detail decode lines.** "geometry is severe." / "data is current." risked
reading as marketing copy. *Kept but constrained* to two lowercase
clauses, one per axis, whose only job is to force the two numbers to be
read independently — which is the core requirement, not embellishment.

**Back affordance.** `‹ back to screening` uses a left chevron. This is a
navigation convention, not an arrow appended to a button label (the
calibration target); kept, and it is the only glyph of its kind in the UI.
