# Verifying PPTX → Typst translation accuracy: Method A (PDF) vs. Method B (introspection)

Date: 2026-07-11 · Branch: `ae/restart` · typst 0.14.2, Touying 0.6.1, CeTZ 0.5.2, Fletcher 0.5.8

## Goal

The converter translates PowerPoint presentations to Touying (slides) and
CeTZ/Fletcher (diagrams). To develop it — partly in an automated
"autoresearch loop" — we need fast, precise checks that the Typst output
matches the PPTX original: no text escaping its box, no wrong proportions,
no misplaced elements. Two independent verification methods were built and
compared (package `typstpresenter.verify`).

## Shared foundation

All three worlds are reduced to one geometry model
([geometry.py](../src/typstpresenter/verify/geometry.py)): bounding boxes
in **pt with top-left origin**. PPTX EMU divides by 12700; PDF and Typst
already use pt. The baseline emitter
([emitter.py](../src/typstpresenter/verify/emitter.py)) sets the Typst page
size to the PPTX slide size with margin 0, so coordinates map **1:1** —
each comparison is exact, without scaling heuristics.

The ground truth comes from python-pptx
([pptx_geometry.py](../src/typstpresenter/verify/pptx_geometry.py)); every
shape gets a stable id `s{slide}-e{shape_id}` that Method B's probes carry
as well.

## Method A: compile to PDF, extract with PyMuPDF

[method_a.py](../src/typstpresenter/verify/method_a.py) compiles with
`typst compile` and reads the PDF with PyMuPDF:

- **text** at *line* granularity (block granularity proved wrong: PyMuPDF
  merges side-by-side boxes sharing a baseline into one block),
- **images** as blocks,
- **vector drawings** as path bounding boxes (diagram shapes; connectors
  split into line body + arrowhead and are re-assembled by containment
  matching).

PDF elements are anonymous, so
[compare.compare_spatial](../src/typstpresenter/verify/compare.py) matches
text by similarity (with containment shortcut), images/shapes by IoU,
connectors by containment. Checks: text ink must stay inside its designed
box (with a font-ascent-dependent slack — PDF line boxes overshoot the
layout box by ~0.3 em), ink anchor must stay near the box origin, shapes
must sit at the right place with the right size.

## Method B: Typst introspection via `typst query`

[method_b.py](../src/typstpresenter/verify/method_b.py). The emitter wraps
every placed element in a `tp-probe(id, x, y, w, h)[...]` call which, inside
the layout engine, records as `metadata`:

- the final absolute position (`here().position()`),
- the designed box size,
- the **measured** natural content size (`measure(block(width: w, body))`).

`typst query doc.typ "<tp-probe>" --field value` returns all payloads as
JSON **without exporting a PDF**. `content-h > h` is an *exact* overflow
check, independent of rendering. Diagram nodes get `tp-node-probe(id)`
markers inside their label content — this works both in Fletcher node
labels and in CeTZ `content()`, so individual diagram nodes and even
connectors (edge labels / midpoint markers) are verifiable.

Findings on feasibility (the open question from the project plan):

- Introspection works reliably for this purpose. Positions come back with
  sub-pt precision (measured: exact to the emitted coordinate).
- `measure` + fixed box width turns overflow detection into arithmetic,
  no image analysis needed.
- Inside CeTZ canvases only *content* elements (labels) are introspectable,
  not raw paths — pure geometry (a line without label) needs an explicit
  invisible marker, which the emitter adds.
- One pitfall: CeTZ shrink-wraps its canvas, which silently shifts all
  absolute coordinates; the emitter pins the canvas with an invisible
  full-page rectangle.
- Prior art: packages like `pinit` and `drafting` use exactly this
  pattern (metadata/locate + measure) for position-based annotations.

## Test corpus

[corpus.py](../src/typstpresenter/verify/corpus.py) generates paired
(PPTX, Typst) cases:

- (i) layouts: title+content, title+two columns, 2×2 grids,
- (ii) diagrams: flowchart and mixed shapes as CeTZ (via emitter) and the
  flowchart additionally as Fletcher diagram,
- fault variants with known ground truth: moved, box shrunk (→ overflow),
  box narrowed, element dropped, extra text injected.

`uv run typstpresenter benchmark -o <dir>` regenerates everything and runs
the comparison; `uv run pytest tests/test_verify.py` (24 tests, ~5 s) is the
CI-style check.

## Results (5 timing repetitions per case)

| case | kind | A time (s) | B time (s) | A found/expected | B found/expected | A false pos. | B false pos. |
|---|---|---|---|---|---|---|---|
| layout_title_content | layout | 0.126 | 0.119 | 0/0 | 0/0 | 0 | 0 |
| layout_two_columns | layout | 0.129 | 0.120 | 0/0 | 0/0 | 0 | 0 |
| layout_grid | layout | 0.135 | 0.126 | 0/0 | 0/0 | 0 | 0 |
| diagram_flowchart | diagram-cetz | 0.157 | 0.149 | 0/0 | 0/0 | 0 | 0 |
| diagram_mixed_shapes | diagram-cetz | 0.147 | 0.141 | 0/0 | 0/0 | 0 | 0 |
| diagram_flowchart_fletcher | diagram-fletcher | 0.217 | 0.200 | 0/0 | 0/0 | 0 | 0 |
| …faulty_moved | layout | 0.127 | 0.119 | 1/1 | 1/1 | 0 | 0 |
| …faulty_overflow | layout | 0.131 | 0.118 | 0/0 ¹ | 1/1 | 0 | 0 |
| …faulty_resized | layout | 0.127 | 0.123 | 0/0 ¹ | 1/1 | 0 | 0 |
| …faulty_missing | layout | 0.131 | 0.116 | 1/1 | 1/1 | 0 | 0 |
| …faulty_extra_text | layout | 0.131 | 0.119 | 1/1 | 1/1 | 0 | 0 |

¹ method-specific expectation: not detectable from ink in principle, see below.

**Method B: 5/5 faults, Method A: 3/5 of the full fault set** (3/3 of what
ink can show). Both methods: **zero false positives** on all clean cases.

## Conclusions

1. **Accuracy: Method B wins clearly.** It reads the *designed* geometry
   (box position and size) plus the measured content size directly from
   the layout engine — sub-pt precise, id-matched, no matching heuristics.
   Method A only sees *ink*: a borderless box that was resized or whose
   content overflows within larger empty space leaves no PDF evidence.
   Moves inside a large box are only caught via the ink-anchor heuristic,
   which will misfire on centered text.
2. **Speed: nearly identical** (~0.12–0.20 s per presentation for both;
   B ~5–8 % faster). `typst query` performs the full layout, so it saves
   only the PDF export and parse. Speed is *not* the differentiator at
   this corpus size; robustness of matching is.
3. **Method A remains valuable as a complement**: it verifies what is
   *actually rendered* (fonts, final PDF, things probes cannot cover) and
   works on documents we did not emit ourselves. B requires instrumented
   sources — free for us, since the converter emits the probes.
4. **Recommended setup for the autoresearch loop**: Method B as the
   primary, gating check (exact, id-matched, extensible per element);
   Method A as a slower cross-check on corpus additions and releases.
   Both are wired into pytest already.

## Autoresearch loop: converter build-out (updated 2026-07-11)

The emitter was grown level by level, each level adding harder test cases
that must verify clean before moving on (corpus registry in
[corpus.py](../src/typstpresenter/verify/corpus.py)):

- **L1 rich text**: styled runs, alignment, vertical anchor, bullets.
- **L2 inherited styles**: placeholder chain (layout → master → txStyles),
  pinned to Office defaults by unit test.
- **L3 styled shapes**: theme colors (clrScheme + p:style refs),
  diamond/triangle, elbow and flipped connectors; found: line width 0 EMU
  means hairline.
- **L4 2D diagrams**: decision flowchart in CeTZ and Fletcher; Fletcher
  needs half-size nodes with `diamond.with(fit: 1)` and a measured
  calibration pass because its outer bbox is not the node hull. Method A
  caught an undersized Fletcher diamond that B accepted — the
  rendered-ink cross-check pays off.
- **L5 real decks** (tests/data): field text (slide numbers), tables with
  exact column/row extents, smartquotes off (PPTX text is literal),
  PowerPoint line metrics (Calibri pitch 1.22 em vs typst 0.632 em +
  leading), `normAutofit` including a measure-based shrink calibration
  (PowerPoint stores `fontScale` only after editing — generated decks need
  it computed). Overflow that already exists in the source (no
  shrink-autofit) is downgraded to a *warning*: it is not a translation
  error.
- **L6 dense lecture decks** (tests/data/IBN_presentations*): group
  flattening with chOff/chExt transforms, freeforms as bbox shapes,
  invisible text-container shapes, run merging (a chain of `#text()` calls
  creates a break opportunity at every run boundary and shreds
  formula-heavy labels), labels constrained to shape width.

Result on a real 34-slide lecture deck (vlxN04): **Method B: 0 issues**
(9 source-overflow warnings), end-to-end ~2 s. Method A degrades on dense
slides (~180 findings from heuristic matching noise) — dense decks are
therefore gated by Method B only (`CorpusCase.verify_with_a = False`),
another point for B as the primary gate.

Continued iterations on all 26 IBN lecture decks added: full markup
escaping (`//` comments, line-start markers), WMF→PNG conversion via
Pillow with placeholder fallback, per-slide canvas drift calibration
(labels/shapes reaching beyond the page inflate cetz's canvas bounds),
scaling of point-based paragraph spacing under autofit (fixed `#v` floors
otherwise block shrink convergence), and measured label probes
(`tp-label-probe`) that classify labels taller than their shape as source
conditions. Final state: **all 44 showcase decks verify with 0 Method-B
issues**. (The former vl06 residual is fixed: em-based paragraph
leading/spacing resolved against the unshrunk context size and formed a
fixed floor — `emit_text_body` now scales the context `#set text` size
with the autofit factor, and the calibration runs up to 14 rounds because
many-paragraph bodies respond sub-linearly to font scale.)
`uv run typstpresenter showcase` regenerates .typ+PDF for all decks into
`tests/results_tmp/showcase` for human review. Known visual gaps for the
next levels: symbol-font runs (Wingdings bullets render as tofu), shape
rotation is ignored, freeform geometry is approximated by its bbox.

## Flow mode ("minimal") and Method S (added 2026-07-11, B-prompt session)

Priorities changed: the generated Typst must be **human-editable and
idiomatic** — simple code and a coherent, overlap-free layout now outrank
coordinate fidelity. `emit_touying(..., minimal=True)` therefore no longer
strips probes from the absolute-placement output; it delegates to
`emit_minimal` (package `typstpresenter.convert`, module `flow.py`), which
rebuilds each slide as normal document flow:

- title placeholder → `== Heading` (Touying renders it),
- bullet/numbered paragraphs → native `-` / `+` list items (nested by
  indentation), plain paragraphs as plain markup,
- one `#set text(size: …)` for the deck (dominant body size) plus at most
  one per deviating slide — instead of per-run `#text(size: …)`,
- bold/italic runs → `*…*` / `_…_` where word boundaries allow,
- side-by-side placeholders → `#grid(columns: (…fr), …)`,
- pictures/tables in reading order (`#image` with pt width, `#table` with
  auto rows; dense tables >8 rows keep the source row heights),
- autoshapes/connectors → one CeTZ canvas per slide, **absorbing** text
  boxes and small pictures whose bbox lies in the diagram area (scattered
  labels, annotated screenshots) at their original relative positions,
- slide chrome (page number/footer/date placeholders, bottom-edge mini
  text boxes) is dropped — the theme owns it; off-page parked shapes too.

Minimal escaping keeps the text readable (only ``\#$*_`@<>[]`` plus `//`
and line-start markers); a `;` terminates hash expressions where a literal
`(`/`[`/`.` would extend their parse.

**Overflow calibration without probes:** flowing content has no fixed
boxes, so instead of PPTX autofit the emitter compiles the deck with
temporary invisible markers (`#place(hide(context metadata(…)))` after
each heading), reads the page each slide starts on via `typst query`, and
shrinks slides spanning several pages (font scale ×0.85/×0.7 per round,
floor 0.4, ≤6 rounds). The final file is written without markers.
Touying pitfalls encoded in the emitter: a bare top-level `#set`, a
`#[…]` scope containing `#align`, or a marker element without a blank
line after the heading each *split the slide into two pages*; the only
tested-safe wrapper for per-slide set rules is `#block(width: 100%)[…]`.

**Method S** (`verify/method_s.py`, CLI `verify --method s`) gates flow
output: document compiles, page count == slide count, no ink outside the
page (4 pt slack), no text/text or text/image collisions (>35 % of the
smaller box) — collisions that the *source slide already contains*
(labels on screenshots etc.) are downgraded to warnings — plus
simplicity metrics (#place count must stay 0, probe defs 0).
`tests/test_flow.py` pins the contract; the showcase command reports
`S: <issues>` per deck.

Result: **all 32 real decks (tests/data + IBN_presentations{,2}) emit,
compile and pass Method S with 0 issues**; the emitted source contains
zero `#place` calls (previously every text box was absolutely placed).

## Known limitations / next steps

- Ground truth uses the *declared* PPTX box; PowerPoint's own text
  rendering (autofit, insets, font substitution) is not simulated. A
  rendered-PPTX baseline (LibreOffice/PowerPoint export) could later
  calibrate tolerances.
- The emitter is a deliberate baseline (absolute placement); as the real
  converter becomes more idiomatic (grids, Touying layouts), probes stay
  valid because they wrap content, not coordinates.
- Fletcher pairing currently forces node sizes/spacings from PPTX; elastic
  fletcher layouts will need looser node tolerances (`Tolerances.node_pos_pt`).
- Method A's ink-anchor check assumes top-left-aligned text.
