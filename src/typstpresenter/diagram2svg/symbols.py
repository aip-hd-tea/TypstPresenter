"""Symbol/Wingdings → Unicode mapping (gap G7).

Legacy decks encode Greek letters as Symbol-font runs ('l' = λ) and
bullets as Wingdings characters, often in the F0xx private-use area.
Modern fonts render those as tofu; map them to real Unicode instead.
"""

from __future__ import annotations

# Adobe Symbol encoding, ASCII slot -> Unicode (letters + common math)
_SYMBOL = {
    "a": "α", "b": "β", "g": "γ", "d": "δ", "e": "ε", "z": "ζ",
    "h": "η", "q": "θ", "i": "ι", "k": "κ", "l": "λ", "m": "μ",
    "n": "ν", "x": "ξ", "o": "ο", "p": "π", "r": "ρ", "s": "σ",
    "t": "τ", "u": "υ", "f": "φ", "c": "χ", "y": "ψ", "w": "ω",
    "A": "Α", "B": "Β", "G": "Γ", "D": "Δ", "E": "Ε", "Z": "Ζ",
    "H": "Η", "Q": "Θ", "I": "Ι", "K": "Κ", "L": "Λ", "M": "Μ",
    "N": "Ν", "X": "Ξ", "O": "Ο", "P": "Π", "R": "Ρ", "S": "Σ",
    "T": "Τ", "U": "Υ", "F": "Φ", "C": "Χ", "Y": "Ψ", "W": "Ω",
    "J": "ϑ", "j": "φ", "V": "ς",
    "¥": "∞", "£": "≤", "³": "≥", "¹": "≠", "»": "≈", "×": "⋅",
    "¬": "←", "­": "↑", "®": "→", "¯": "↓", "«": "↔",
    "Î": "∈", "Ï": "∉", "Ç": "∩", "È": "∪", "Ì": "⊂", "Í": "⊆",
    "$": "∃", '"': "∀", "Ø": "∅", "¶": "∂", "Ö": "√", "å": "∑",
    "±": "±", "·": "•",
}

# Wingdings characters seen as bullets in the corpus
_WINGDINGS = {
    "§": "▪", "n": "■", "l": "●", "u": "◆", "Ø": "➢", "ü": "✓",
    "û": "✗", "F": "☞", "à": "→", "ß": "←", "á": "↑", "â": "↓",
    "w": "◆", "v": "❖", "Ú": "❒", "o": "□", "¡": "○", "·": "•",
}

_BY_FONT = {
    "symbol": _SYMBOL,
    "wingdings": _WINGDINGS,
    "wingdings 2": _WINGDINGS,
    "wingdings 3": _WINGDINGS,
    "webdings": _WINGDINGS,
}


def is_symbol_font(name: str | None) -> bool:
    return bool(name) and name.lower() in _BY_FONT


def map_symbol_text(text: str, font_name: str | None) -> str:
    """Translate a symbol-font run (or PUA-encoded chars) to Unicode."""
    table = _BY_FONT.get((font_name or "").lower())
    out = []
    for ch in text:
        # F0xx private-use chars carry the original codepoint + 0xF000
        key = chr(ord(ch) - 0xF000) if 0xF000 <= ord(ch) <= 0xF0FF else ch
        if table is not None:
            out.append(table.get(key, key))
        elif key != ch:
            # PUA char but the declared font is not a symbol font: assume
            # Symbol first, then Wingdings (bullet chars land here)
            out.append(_SYMBOL.get(key) or _WINGDINGS.get(key) or "•")
        else:
            out.append(ch)
    return "".join(out)


def run_symbol_font(run) -> str | None:
    """The run's a:sym typeface (python-pptx does not expose it)."""
    from pptx.oxml.ns import qn

    rPr = run._r.find(qn("a:rPr"))
    if rPr is None:
        return None
    sym = rPr.find(qn("a:sym"))
    return sym.get("typeface") if sym is not None else None


def bullet_font(paragraph) -> str | None:
    """The paragraph's a:buFont typeface, if declared."""
    from pptx.oxml.ns import qn

    pPr = paragraph._p.find(qn("a:pPr"))
    if pPr is None:
        return None
    bu = pPr.find(qn("a:buFont"))
    return bu.get("typeface") if bu is not None else None
