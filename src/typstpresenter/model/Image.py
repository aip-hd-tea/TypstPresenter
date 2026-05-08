from dataclasses import dataclass
from typstpresenter.model.Element import Element

@dataclass(frozen=True)
class Image(Element):
    name: str # Stable, human-readable filename derived from image content (e.g. "golden-horizon-07.png")
    blob: bytes
    ext: str
    width_pt: float | None = None
    height_pt: float | None = None
