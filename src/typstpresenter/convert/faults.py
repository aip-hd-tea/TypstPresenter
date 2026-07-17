"""Deliberate corruptions of emitted geometry, used to evaluate verifiers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fault:
    """A deliberate corruption of one emitted element (for evaluation)."""
    element_id: str
    dx: float = 0.0        # shift in pt
    dy: float = 0.0
    scale_w: float = 1.0   # box resize factors
    scale_h: float = 1.0
    extra_text: str = ""   # appended to the content (provokes overflow)
    drop: bool = False     # omit the element entirely

    def expected_issues(self) -> set[str]:
        """Issue kinds a verifier with access to box geometry (Method B)
        should report for this fault."""
        expected = set()
        if self.drop:
            return {"missing"}
        if self.dx or self.dy:
            expected.add("moved")
        if self.scale_w != 1.0 or self.scale_h != 1.0:
            expected.add("resized")
        if self.extra_text or self.scale_h < 1.0:
            expected.add("overflow")
        return expected

    def expected_issues_ink(self) -> set[str]:
        """Issue kinds detectable from rendered ink alone (Method A).

        Boxes without fill or stroke leave no trace in the PDF, so pure
        box resizing (and the overflow it causes within the original
        bounds) is invisible to ink-based verification.
        """
        expected = set()
        if self.drop:
            return {"missing"}
        if self.dx or self.dy:
            expected.add("moved")
        if self.extra_text:
            expected.add("overflow")
        return expected
