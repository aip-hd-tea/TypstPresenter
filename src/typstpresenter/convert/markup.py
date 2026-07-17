"""Typst markup escaping shared by all emitting modules."""

from __future__ import annotations

# Every Typst markup-active character must be escaped: braces/brackets and
# inline markers, but also '/' (starts a comment after another '/'), and the
# line-start markers =,-,+ (heading/list/enum). Escaping also suppresses
# smart-dash substitution -- PPTX text is literal.
_ESCAPE = str.maketrans({c: f"\\{c}" for c in '\\#$*_`@<>"~[]{}/=-+\''})


def escape_typst(text: str) -> str:
    return text.translate(_ESCAPE)
