# Diagrams → SVG: plan for the new translation path

Date: 2026-07-18 · Branch: `ae/restart` · Prompt: `docs/prompts_v2/D diagrams to svg.txt`
Companions: [verification-methods.md](verification-methods.md) (Methods A/B/S/F/D),
[diagram-translation-plan.md](diagram-translation-plan.md) (the CeTZ/Fletcher program this supersedes for geometry),
[gap-census-report.md](gap-census-report.md) (what actually occurs in the corpus).

## 1. Why the pivot

Translating PPTX diagrams to CeTZ/Fletcher means re-implementing PowerPoint's
drawing model in a *layout* language: every one of ~187 preset geometries had
to be hand-coded as CeTZ path calls, curved freeforms fell back to bounding
boxes (93 of 160 corpus freeforms), and each new preset risked coordinate-sign
bugs (see the Session-2 `cy` bug). The gap census shows 865 shapes across 23
decks still hit unhandled presets.

SVG removes the impedance mismatch almost entirely: DrawingML and SVG share
the same primitives (paths with lines/cubics/arcs, fills, strokes, gradients,
affine transforms, z-order painting). A PPTX diagram can be translated
**shape-for-shape into an SVG document** and embedded in the Typst slide as
`#image("slideN-dM.svg", width: …pt)`. Fidelity becomes a rendering problem
we mostly don't own (typst's resvg pipeline), not a re-implementation problem.

What we give up: the SVG is not human-editable Typst (conflicts with the
"idiomatic flow output" goal for *text*, but diagrams were never really
editable as 40 CeTZ calls either). The flow emitter keeps owning text, lists,
grids, images, tables; only the **diagram clusters** (what today becomes a
CeTZ canvas) switch to SVG. The CeTZ path stays available behind a flag
during the transition.

## 2. Architecture decision: who produces the SVG?

| Option | Verdict |
|---|---|
| **(a) Own DrawingML→SVG translator in Python** | **Primary.** Deterministic, machine-independent, per-shape testable, no Office dependency at convert time. This is what the sessions below build. |
| (b) PowerPoint COM slide/shape export | **Reference renderer for benchmarks only** (COM verified available on this machine, see diagram-translation-plan Session 4). Not the product path: needs Windows+Office, exports whole slides (shape-range export is brittle), output is not attributable per shape. |
| (c) LibreOffice headless SVG export | Fallback reference on machines without Office; same non-product reasons. |

Key enabler for (a): OOXML preset geometries are *data*, not code. The spec's
`presetShapeDefinitions.xml` defines all ~187 presets as guide-formula programs
(`gd` elements with `*/`, `+-`, `sin`, `cos`, `at2`, …) over the shape's
adjust values (`avLst`). One **generic formula interpreter** (~15 operators)
evaluates any preset — including callout wedges, block arrows, cloud, arc —
into path commands that map 1:1 to SVG `<path d=…>`. That solves gap G1
wholesale instead of preset-by-preset, and `custGeom` (freeforms, G2) uses the
*same* path-emission code because custGeom is literally the same XML dialect.

## 3. New package layout (isolated, extractable)

```
src/typstpresenter/diagram2svg/        # no imports FROM the old code into here
    __init__.py                        #   except read-only helpers (see below)
    presets.py       # presetShapeDefinitions.xml loader + guide-formula interpreter
    geometry.py      # custGeom + preset path → normalized path segments (EMU→pt)
    style.py         # fill/stroke/gradient/theme-color resolution → SVG attrs
    text.py          # text bodies inside shapes → SVG <text>/<tspan> (wrap, anchor)
    connectors.py    # straight/elbow/curved connectors, arrowheads (SVG markers)
    svg_writer.py    # assembles per-cluster SVG documents (viewBox in pt, z-order)
    convert.py       # public API: cluster_to_svg(shapes, theme) -> SvgResult
tests/
    test_diagram2svg.py                # unit + per-level fidelity tests
    diagram2svg_data/                  # generated pptx test decks, L1..L3
```

Reuse policy (the prompt allows refactoring the old code): shared read-only
logic — `verify/pptx_geometry.py` (shape walking, ids, EMU→pt),
`convert/pptx_style.py` + `pptx_inherit.py` (theme colors, style inheritance)
— is imported *by* `diagram2svg`, never the reverse. If extraction to another
project happens later, those modules come along or get vendored; nothing in
the existing converter will depend on `diagram2svg` except one call site in
`flow.py` (cluster rendering dispatch) and one in `media.py`-style asset
writing (SVG file placement next to extracted images).

## 4. Test data: complexity ladder L1–L6

Generated decks live in `tests/diagram2svg_data/` (built by a
`generate_diagram_data.py` sibling of the existing `tests/generate_test_data.py`,
using python-pptx); real-deck extracts are copied, not regenerated.

- **L1 — single primitives** (one deck, one diagram per slide): rect, rounded
  rect, ellipse, diamond, triangle, straight line; solid fill + stroke,
  explicit RGB colors, no text, no rotation.
- **L2 — small assemblies**: 2–5 shapes with text labels; theme colors;
  straight connectors with arrowheads; simple z-order overlap; bold/size runs
  in labels.
- **L3 — hard single-shape features**: rotation + flips; elbow and curved
  connectors with adjust values; presets from the census histogram
  (`wedgeRectCallout`, `accentCallout1`, `rightArrow`, `can`, `chevron`,
  `cloud`, `arc`); gradients; dashed strokes; groups (`grpSp` with
  chOff/chExt); a curved freeform.
- **L4–L6 — real-deck extracts**, ordered by measured complexity (shape count,
  preset variety, connector count, presence of groups/freeforms/OLE — the gap
  census script already computes most of this per slide): single diagram
  slides pulled from `tests/data/*` and `IBN_presentations{,2}` into
  standalone one-slide pptx files (python-pptx can delete the other slides
  from a copy). L4 ≈ 6–10 shapes flowcharts (vl02 Komplexität class),
  L5 ≈ dense architecture diagrams (CPU/stack slides, 15–30 shapes,
  annotated screenshots), L6 ≈ worst-of-corpus (vl16-class canvases,
  multi-cluster slides, OLE-bearing slides like vlN01 s22).

## 5. Benchmarks: does the SVG look like the PPTX?

Three tiers, cheapest first — reusing the existing verification machinery
where it fits:

1. **Structural (exact, gating — the Method-B spirit).** We *generate* the
   SVG, so every shape carries `id="s{slide}-e{shape_id}"`. A checker parses
   our SVG (ElementTree; resolve transforms) and compares per shape against
   the `pptx_geometry.py` ground truth: bbox position/size (sub-pt), kind
   (path vs ellipse vs text), fill/stroke RGB, rotation angle, z-order index,
   connector endpoints. No matching heuristics needed — id-matched, like
   Method B. This is the pytest gate (`tests/test_diagram2svg.py`).
2. **Rendered-vector (Method D reuse).** Compile a minimal Typst page
   embedding the SVG, extract vector paths with PyMuPDF, run the existing
   `method_d.py` matcher against the source shapes. This validates the whole
   chain *including typst's SVG rasterization* (fonts, markers, transforms)
   and lets us compare SVG-path output against the current CeTZ output on
   identical slides — the direct old-vs-new scoreboard.
3. **Visual reference (informational, never gating).** Export the source
   slide via PowerPoint COM to PNG (available, cached per deck), render our
   SVG to PNG (resvg or `typst compile --format png`), compare the diagram
   region by edge-map similarity as sketched in diagram-translation-plan
   Session 4. Catches "brace rendered as bar"-class bugs that structure
   checks pass. Threshold calibrated on L1–L3 where we know the answer.

## 6. Human review drops

After each level: `tests/results_tmp/diagram_svg/L{n}/` containing per case
the one-slide `.pptx`, the generated `.svg`, the reference PNG (COM export)
and our rendered PNG side by side, plus an `index.html` contact sheet.
**The user is informed when L1 results land, and again per level.**

## 7. Session roadmap (autoresearch loop, gated per level)

Each step ends with: structural gate green for all levels so far, tier-2/3
reports regenerated, review drop updated, progress log appended here. Hard
rule carried over from the CeTZ program: validate every change against *all*
levels built so far, never one case.

- **S1 — Skeleton + L1** (prompt step 1+3): package scaffolding; L1 deck
  generation; rect/ellipse/roundRect/diamond/triangle/line via the preset
  interpreter (these exercise the formula engine on easy cases); solid
  fill/stroke; svg_writer with pt viewBox; structural checker; review drop;
  **notify user**.
- **S2 — L2**: text bodies (wrapping into shape width, anchors, insets, runs
  → `<tspan>`; font size in pt so typst renders text at true size), theme
  color resolution (reuse `pptx_style`), straight connectors + arrowhead
  markers, z-order. Wire tier-2 (Method D over SVG) here.
- **S3 — L3**: full preset interpreter coverage (load
  `presetShapeDefinitions.xml`, arcs→SVG `A`/bezier), rotation/flip
  transforms, elbow/curved connectors with avLst, gradients, dash patterns,
  groups, curved custGeom. Wire tier-3 (COM visual reference).
- **S4 — L4/L5 real decks + flow integration**: `flow.py` cluster dispatch
  switches to SVG behind `diagram_backend="svg"` (default stays cetz until
  the scoreboard says switch); asset writing; Method S/F full-corpus run to
  prove no regressions; old-vs-new tier-2 scoreboard on the extract decks.
- **S5 — L6 + hardening**: multi-cluster slides (G5 — clusters already
  detected in flow.py map 1:1 to separate SVGs), OLE preview images inside
  clusters (G6), symbol-font text (G7 — SVG can name Wingdings directly or
  map to Unicode), overflow behavior for text inside shapes (G3 — shrink to
  fit within the shape box, which SVG makes exact because *we* do the line
  breaking in `text.py`). Corpus-wide showcase regeneration; decide default
  backend.

## 8. Known risks, called out up front

- **Text inside SVG**: typst renders SVG text via its resvg pipeline with the
  document's font resolver; metrics differ from PowerPoint's, so `text.py`
  must do its own line breaking against measured/estimated advance widths
  (Pillow's `ImageFont` over the actual TTFs, cached) rather than trusting
  the renderer to wrap. Mitigation if font fidelity disappoints: convert text
  to outlines is *not* acceptable (file bloat, no search); fallback is
  keeping text out of the SVG and overlaying it in Typst — kept as a plan-B
  seam in `svg_writer` (text layer separable).
- **resvg feature coverage** inside typst (markers, `textLength`, filters):
  probe early in S1/S2 with tiny fixtures; avoid SVG features typst's
  embedder ignores (known: no external refs; filters partially unsupported —
  shadows will be approximated or dropped).
- **`presetShapeDefinitions.xml` sourcing**: ship a copy (ECMA-376 is freely
  licensed for this) under `diagram2svg/data/`; the interpreter unit-tests
  pin a handful of presets against hand-computed coordinates.
- **Scale/DPI**: SVG viewBox in pt, embedded with explicit `width:` in pt →
  1:1 with the existing geometry model; no scaling heuristics.

## Progress log

- **2026-07-18**: Plan written.
- **2026-07-18** (S1–S3, levels L1–L3 complete; all gates green):
  - **Package built** (`src/typstpresenter/diagram2svg/`): `presets.py`
    (loader + generic guide-formula interpreter over the genuine ECMA-376
    `presetShapeDefinitions.xml`, 187 presets, fetched from the LibreOffice
    mirror; also evaluates `custGeom` freeforms and preset text rectangles),
    `style.py` (solid/gradient fills, dashes, theme colors via `pptx_style`),
    `text.py` (own line breaking with Pillow-measured Calibri/Arial advances,
    per-run explicit x, preset text-rect layout, OOXML defaults: align left,
    anchor top), `svg_writer.py` (pt viewBox, z-order groups, arrowhead
    markers, linearGradient/dasharray defs), `convert.py` (public API),
    `structural.py` (benchmark), `review.py` (review drops: COM reference
    PNG + typst-rendered PNG + contact sheet).
  - **Test data**: `tests/generate_diagram_data.py` → `tests/diagram2svg_data/`
    L1 (primitives, adjustment values, flipped connectors), L2 (labels,
    wrapping, mixed runs, theme-styled shapes, arrowhead connectors,
    z-order), L3 (rotation/flips, census presets incl. cloud/can/mathPlus/
    lightningBolt, adjusted wedge callout, arc, elbow+curved connectors,
    gradients, dashes, group, freeform).
  - **Benchmarks**: structural gate = id-matched comparison of parsed SVG
    (independent path sampler incl. SVG-arc endpoint→center conversion)
    against python-pptx ground truth: geometry bounds, command profile,
    fill/stroke/width/dash/gradient, text content+anchors, marker presence,
    z-order. All 17 slides across L1–L3 verify with 0 findings;
    `tests/test_diagram2svg.py` (14 tests) pins it; full suite 98 passed.
  - **Learned/decided**: path bounds ≠ shape bbox for many presets
    (mathPlus spans 73.5 % of its box, default arc is a quarter ellipse,
    callout leaders exceed the box) — the checker therefore derives
    expected bounds from the evaluated geometry, while formula correctness
    is pinned by preset unit tests and the visual reference tier. DrawingML
    arcTo is interpreted parametrically; text in autoshapes defaults to
    align-left/anchor-top per OOXML (PowerPoint's UI-inserted `ctr` values
    come through the XML, not defaults).
  - **Visual tier**: PowerPoint COM reference vs. our typst-rendered SVG
    side-by-side in `tests/results_tmp/diagram_svg/L{1..3}/index.html` —
    spot-checked visually identical (wrap breaks at the same words; elbow/
    curved connector geometry matches; cloud shows tiny inner-arc stroke
    artifacts worth a later look).
  - **Next (S4)**: L4/L5 real-deck extracts, `flow.py` cluster dispatch
    behind `diagram_backend="svg"`, Method D old-vs-new scoreboard,
    full-corpus S+F regression run.
- **2026-07-18** (S4, in progress):
  - **L4/L5 extracts**: 10 one-slide decks pulled from the real IBN
    lectures (`tests/diagram2svg_data/L4-*.pptx`, `L5-*.pptx`; moderate
    flowcharts → dense 82-shape scheduling/architecture slides).
    **All pass the structural gate with 0 findings and 0 geometry
    fallbacks** (~340 shapes; the generic preset interpreter + custGeom
    covered everything, including 90°-rotated flipped curvedConnector2).
  - **Flow integration**: `flow.DIAGRAM_BACKEND = "svg"` (or env
    `TP_DIAGRAM_BACKEND=svg`) routes `_render_diagram_cluster` through
    `diagram2svg/cluster.py`: one SVG per cluster in the media dir,
    embedded `#image(..., width: …pt)`, same bounds/alignment/fit-scale
    contract, Fletcher lifting keeps priority, CeTZ fallback for
    absorbed tables and unembeddable images; absorbed pictures embed as
    data URIs (typst's SVG pipeline loads no external refs); canvas
    markers for Method D attribution supported. Smoke test (vl04
    process-states extract): S 0/0, F 0/0, page visually matches
    PowerPoint.
  - **Bugs found by the real decks**: `pptx_style._THEME_ENUM_TO_SCHEME`
    lacked TEXT_1/TEXT_2/BACKGROUND_1/BACKGROUND_2 — `schemeClr
    val="tx1"` connectors resolved to no stroke and vanished (latent in
    the CeTZ path as well); explicit `a:br` line breaks were reflowed
    away (now hard breaks); `a:fld` runs (slide numbers) were dropped.
  - **Symbol fonts (G7) closed for diagrams**: `symbols.py` maps
    Symbol/Wingdings runs and PUA F0xx chars to Unicode (λ, μ, ▪, ✓ …)
    with per-run `a:sym` detection and buFont-aware bullet glyphs.
  - 17 tests in tests/test_diagram2svg.py; scoreboard runs pending.
- **2026-07-18** (S4 complete):
  - **Scoreboard** (9 curated problem decks, fresh CeTZ baseline vs
    `TP_DIAGRAM_BACKEND=svg`, logs in tests/results_tmp/showcase_*.log,
    comparison script tests/results_tmp/compare_showcase_logs.py):
    - Method S: **0 issues on every deck under both backends**; warning
      counts comparable (svg lower on vlxN09 51 vs 65, vl04 10 vs 12).
    - Method F: CeTZ 1 issue total (vl16); **SVG 0 issues** after the
      hyperlink fallback (clusters whose text carries hyperlinks render
      via CeTZ, since typst cannot attach link annotations inside an
      embedded SVG — same fallback pattern as tables).
    - Method D: issues down across the board (vl16 10→2, vl12 7→6,
      vl08 4→3, vl06 1→0, vlxN09 1→0), but *coverage* drops (e.g.
      85→49 %) because typst flattens SVG text to glyph outlines, which
      floods the PDF with vector paths and triggers D's abstention.
      D on SVG output therefore under-reports what it checks; the
      structural gate on the SVG itself is the stronger instrument now.
  - Full test suite: 101 passed. Extract decks: structural gate 0
    findings / 0 fallbacks on all 10.
  - **Recommendation**: switch `DIAGRAM_BACKEND` default to "svg" —
    equal or better on every gated metric and categorically better on
    preset geometry (865 formerly bbox-fallback shapes now exact).
    Left at "cetz" pending the user's visual review of
    tests/results_tmp/showcase_svg (deliberate: default flips are
    corpus-visible and should be a human call).
  - **Remaining for S5**: multi-cluster slides as separate SVGs (G5),
    OLE preview images in clusters (G6), per-shape text overflow inside
    shapes (G3 — shrink-to-fit in text.py), decide default backend.
- **2026-07-19** (S5 complete — G3, G5, G6):
  - **G3**: `text.py` shrinks `normAutofit` text to its box by exact
    arithmetic (re-layout loop ≤5 rounds, floor 0.4) — only when the
    source declares autofit; genuine source overflow stays faithful.
  - **G6 root cause found**: `pptx_geometry.picture_image`'s OLE branch
    called `shape.part.related_parts`, which does not exist in this
    python-pptx version; a broad `except` had swallowed the
    AttributeError since the feature was written — OLE previews *never*
    extracted. Fixed via `part.rels[rId].target_part`; vlN01 s22's WMF
    equation previews now convert to PNG and render in both backends
    (shared-code fix, applies to all 135 corpus OLE shapes).
  - **G5**: `flow._spatial_components` splits a slide's diagram content
    into disjoint clusters (union-find over 25 pt-padded bboxes;
    text-only strays and single-shape specks merge into the nearest
    substantial group; split only when ≥2 substantial components
    remain). Each component renders as its own canvas/SVG
    (`cluster_index` finally > 0). vl04's states slide splits into 3
    clusters and renders identically (S/F 0/0).
  - **Corpus validation** (full showcase, both backends, after all
    three changes): Method S 0 issues everywhere; Method F 0 issues on
    the SVG backend, CeTZ keeps only its pre-existing vl16 issue.
    Warning counts rose slightly (e.g. vlxN09 S-warnings 51→82) —
    inspected: all "text overlaps image" source-condition downgrades
    that now fire because formerly-dropped OLE content renders and SVG
    clusters register as images. Full suite: 104 passed.
  - L6 extract `L6-vlN01-s22-ole.pptx` added to the ladder; tests for
    G3 (autofit shrink), G5 (component splitting), G6 (OLE preview).
  - **Open**: default backend still "cetz" — recommendation to flip to
    "svg" stands, pending the user's visual review; Session-4-style
    visual reference tier (edge-map similarity vs PowerPoint COM
    renders) remains unbuilt; structure lifting beyond the existing
    Fletcher detector untouched.
- **2026-07-19** (default backend flipped to "svg", user-approved):
  - `flow.DIAGRAM_BACKEND` defaults to "svg"; `TP_DIAGRAM_BACKEND=cetz`
    restores the old path. Three CeTZ-specific regression guards
    (freeform polygon, rotation, absorbed-text angle) now pin the CeTZ
    backend explicitly via monkeypatch. Full suite: 104 passed.
  - Human-facing showcase (tests/results_tmp/showcase) regenerated with
    the new default (log: showcase_default_svg.log).
