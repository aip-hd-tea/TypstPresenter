"""
Method B: verification via Typst introspection.

The emitted Typst source wraps every placed element in a ``probe`` call
(see PROBE_PRELUDE). Each probe records, directly inside the Typst layout
engine:

- the final absolute position of the element (``here().position()``),
- the designed box size,
- the *measured* natural size of the content constrained to the box width
  (``measure``), which yields an exact overflow check: content taller than
  its box overflows -- no pixels or heuristics involved.

``typst query`` evaluates the document without exporting a PDF and returns
the probe payloads as JSON. Diagram nodes inside Fletcher/CeTZ can be
probed too by placing a node-probe inside the node label content.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from typstpresenter.verify.geometry import (
    BBox,
    DocGeometry,
    ElementGeometry,
    ElementKind,
    SlideGeometry,
)
from typstpresenter.verify.typst_tools import query

# Typst helper functions emitted into instrumented documents.
# probe(): wraps an absolutely placed block and reports geometry + overflow.
# node-probe(): zero-size marker for diagram node positions (place inside
# the node's label content; reports the label's top-left position).
PROBE_PRELUDE = """\
#let tp-probe(id, x, y, w, h, body) = place(top + left, dx: x, dy: y,
  block(width: w, height: h, {
    context {
      let pos = here().position()
      let natural = measure(block(width: w, body))
      [#metadata((
        id: id,
        page: pos.page,
        x: pos.x.pt(),
        y: pos.y.pt(),
        w: w.pt(),
        h: h.pt(),
        content-w: natural.width.pt(),
        content-h: natural.height.pt(),
      ))<tp-probe>]
    }
    body
  })
)

#let tp-node-probe(id) = context {
  let pos = here().position()
  [#metadata((id: id, page: pos.page, x: pos.x.pt(), y: pos.y.pt()))<tp-probe>]
}

#let tp-label-probe(id, body) = {
  context {
    let pos = here().position()
    let size = measure(body)
    [#metadata((
      id: id, page: pos.page, x: pos.x.pt(), y: pos.y.pt(),
      label-w: size.width.pt(), label-h: size.height.pt(),
    ))<tp-probe>]
  }
  body
}
"""

PROBE_SELECTOR = "<tp-probe>"


@dataclass
class MethodBResult:
    geometry: DocGeometry
    query_seconds: float
    # id -> vertical overflow in pt (content height minus box height, > 0 means
    # the content does not fit its box)
    overflows: dict[str, float] | None = None


def run_method_b(
    typ_path: Path | str,
    page_width: float,
    page_height: float,
) -> MethodBResult:
    """
    Query the instrumented Typst document and build its geometry.

    ``page_width``/``page_height`` (pt) are taken from the ground truth,
    since ``typst query`` does not report page dimensions. Both probe
    kinds share one label, so a single query suffices; node probes are
    recognized by their payload (no ``w`` field).
    """
    typ_path = Path(typ_path)
    timed = query(typ_path, PROBE_SELECTOR)

    slides: dict[int, SlideGeometry] = {}

    def slide_for(page: int) -> SlideGeometry:
        index = page - 1  # typst pages are 1-based
        if index not in slides:
            slides[index] = SlideGeometry(index=index, width=page_width, height=page_height)
        return slides[index]

    overflows: dict[str, float] = {}
    for probe in timed.value:
        sg = slide_for(probe["page"])
        if "w" not in probe:  # node/label probe: marker without designed box
            meta = {"node_probe": True}
            if "label-h" in probe:
                meta["label_w"] = probe["label-w"]
                meta["label_h"] = probe["label-h"]
            sg.elements.append(
                ElementGeometry(
                    kind=ElementKind.SHAPE,
                    bbox=BBox(probe["x"], probe["y"], 0.0, 0.0),
                    id=probe["id"],
                    meta=meta,
                )
            )
            continue
        overflow_pt = probe["content-h"] - probe["h"]
        overflows[probe["id"]] = overflow_pt
        sg.elements.append(
            ElementGeometry(
                kind=ElementKind.TEXT,
                bbox=BBox(probe["x"], probe["y"], probe["w"], probe["h"]),
                id=probe["id"],
                meta={
                    "content_w": probe["content-w"],
                    "content_h": probe["content-h"],
                    "overflow_pt": overflow_pt,
                },
            )
        )

    geometry = DocGeometry(
        slides=[slides[i] for i in sorted(slides)],
        source=str(typ_path),
    )
    return MethodBResult(geometry=geometry, query_seconds=timed.seconds, overflows=overflows)
