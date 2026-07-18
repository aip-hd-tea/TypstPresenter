# Diagram translation: multi-session plan

Date: 2026-07-18 · Branch: `ae/restart` · Companion to
[verification-methods.md](verification-methods.md) (Methods A/B/S/F/D).

## Why diagrams are the hard core of the problem

Slide *text* translates to flowing Typst almost losslessly because both
sides agree on the abstractions (paragraphs, lists, sizes). Diagrams do
not: a PPTX diagram is a soup of absolutely-positioned, z-ordered,
rotated, theme-styled shapes from ~185 preset geometries, plus freeform
paths, connectors with attachment semantics, and text that PowerPoint
reflows *inside* shapes with its own line metrics. Any of these being
slightly off is immediately visible (a brace rendered as a filled bar, a
table torn out of its diagram), and none of it is checkable by text-level
verification. Getting diagrams right therefore needs its own program:
**measure first, then complete the geometry, then lift structure** —
spread over multiple sessions, each gated by corpus-wide verification.

## Current state (what already works)

- One CeTZ canvas per diagram cluster; absolute source positions;
  absorbed text boxes, small pictures, annotated screenshots and (since
  2026-07-18) **tables lying inside the diagram area**, all at their
  source-relative positions, emitted in **source z-order** (annotation
  rectangles paint after the screenshot they frame).
- Shape rotation (auto-shapes and absorbed text boxes, e.g. vertical
  axis labels), rotated-footprint canvas sizing.
- Presets: rect, rounded rect, oval, diamond, isosceles triangle,
  **braces/brackets as open strokes**; straight-edged freeform polygons;
  straight + elbow connectors with arrowheads and flips; theme
  fill/stroke/font colors; labels width-constrained with PPT line pitch.
- Verification: Method D compares source shapes against PDF vector paths
  — exact on the synthetic benchmark corpus, but on real decks it
  *abstains* whenever a page's paths aren't attributable (tables, absorbed
  content, multiple clusters) and is informational only.

## Gap taxonomy (ranked by observed corpus impact)

| # | Gap | Effect today |
|---|-----|--------------|
| G1 | Preset coverage (~175 presets fall back to a bbox rect: block arrows, chevrons, callouts, cylinders, stars, pie/arc …) | wrong-looking shapes, sometimes solid bars over content |
| G2 | Curved freeforms (cubicBezTo/quadBezTo/arcTo; 93 of 160 corpus freeforms) → bbox fallback | blobs instead of curves |
| G3 | Text reflow inside fixed canvas boxes taller than the source budget (vl16 class) | text overlaps neighboring shapes |
| G4 | Curved connectors, elbow adjustment values, connection-site semantics | connectors detach from their shapes |
| G5 | Several disjoint clusters on one slide render as one union canvas | oversized sparse canvases; Method D abstains |
| G6 | Embedded OLE objects silently dropped | missing content (vlN01 slide 22) |
| G7 | Symbol fonts (Wingdings) | tofu glyphs |
| G8 | No structure recognition: N primitives instead of one idiom | unreadable generated code, no reuse |

## Session roadmap

Each session ends with: full-corpus Method S+F+D run, showcase
regeneration, and an update of this file's "Progress log". Hard lessons
already learned and to be re-applied: validate every heuristic against
the *full* corpus, never a single deck (the animation-visibility and
connected-component-clustering attempts both looked right locally and
were corpus-wide regressions); keep transforms narrow and evidence-gated.

### Session 1 — Measurement before mechanism

Goal: turn Method D from "informational, often abstaining" into a
trustworthy per-shape diagnostic. Without this, later geometry work
cannot be validated at scale.

1. **Attributable canvases.** The flow emitter knows every canvas's page
   region. Emit (in a verification-only compile, like the calibration
   pass) a hidden metadata marker per canvas with its cluster id and
   declared bounds; `typst query` maps every PDF vector path to its
   cluster. This removes the main abstention cause and fixes G5's
   verification side (per-cluster matching instead of one global affine).
2. **Per-shape verdicts.** Report `missing / displaced / wrong-kind /
   wrong-style` per source shape id, aggregated into a corpus dashboard
   (extend the showcase `D:` column with coverage %: shapes checked /
   shapes present).
3. **Gap census.** One script walks all 46 decks and counts, per gap
   G1–G8: affected shapes, slides, decks. Output = the priority order and
   the success metric for every later session. (Preset histogram tells us
   which of the ~175 unhandled presets actually occur.)

### Session 2 — Geometry completeness

Driven by the Session-1 census, most frequent first. Likely contents:

- Top presets as real CeTZ paths (block arrows, chevron, callout with
  leader line, cylinder, hexagon, parallelogram). A preset is "done" when
  Method D stops flagging it and it is visually right in the showcase.
- Curved freeforms via `cetz.draw.bezier` (custGeom cubicBezTo is a
  direct control-point mapping; arcTo needs arc→bezier conversion).
- Curved connectors (`curvedConnector2..5`) as beziers; honor elbow
  `avLst` adjustments; resolve `a:stCxn/endCxn` to shape connection
  sites so endpoints touch the shapes they logically attach to.
- G6: extract the OLE preview image (same relationship mechanism as
  pictures) and place it as an image.

### Session 3 — Text inside diagrams

- Measured-height guard: estimate (or measure via `typst query` in the
  calibration pass) each absorbed text's rendered height; when it
  exceeds its source box beyond tolerance, shrink that box's font or
  re-flow the layout instead of overlapping neighbors (fixes the vl16
  class of Method-S overlaps).
- Per-shape autofit inside canvases; vertical anchor within shapes
  (already correct for plain shapes; verify for rotated/absorbed ones).
- G7: map Wingdings/Webdings codepoints to Unicode equivalents.

### Session 4 — Rendered-reference visual check

Structural checks can't see that a shape *looks* wrong (the brace-as-bar
bug passed S and F). Add an optional rendered-baseline comparison:

- Render the source PPTX. On this machine **PowerPoint itself is
  available via COM** (verified 2026-07-18: `New-Object -ComObject
  PowerPoint.Application`; `Slides.Item(n).Export(png, "PNG", w, h)`),
  which is the perfect reference renderer — LibreOffice headless is the
  fallback for machines without Office. Cache exports per deck.
- Per diagram region: edge-map similarity (not pixel-exact SSIM; the
  fonts and antialiasing differ) between source render and our render,
  normalized to the region size; calibrate the threshold on the corpus,
  report as a new `V:` (visual) column. Findings are hints for a human,
  never a hard gate — the experience with matcher noise says visual
  metrics must not block.

### Session 5 — Structure lifting and a diagram library

Only after fidelity is measurable (S1) and geometry is mostly complete
(S2), because every lifting transform risks fidelity and must be caught
by the tooling if it regresses.

- **`diagrams.typ`** shipped next to `styles.typ` (same mechanism: one
  copy per output directory, imported when used): helpers like
  `stack-frame(rows)`, `brace-label(side, body)`, `annotated-image(img,
  ..boxes)`, `labeled-arrow(dir, body)` — chosen from the Session-1
  census of *recurring* multi-shape patterns, not invented up front.
- **Pattern detectors** in the converter map shape constellations to
  helper calls: vertical stack of same-width touching rects → one
  `stack-frame`; grid of same-size boxes + connectors → a Fletcher
  node/edge graph (relative coordinates, elastic layout); box + brace +
  rotated label → `brace-label`. Each detector is narrow, evidence-gated
  and validated corpus-wide before being trusted.
- Success metric is twofold: Method D/F stay clean *and* the generated
  line count for the affected slides drops substantially (readability is
  the point of lifting).

## Progress log

- **2026-07-18** (this session): z-order-correct canvases; tables
  absorbed into diagram areas; rotated absorbed text; brace/bracket
  presets as strokes; grid cells sized for their widest occupant
  (extras included). vl02 slides 9/12/15 (Komplexität, CPU, Stack)
  verified visually fixed; vl01 slide 31 checked against a PowerPoint
  COM reference export — the faithful z-order hides a label the source
  also hides; corpus S+F unchanged elsewhere.
