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
