"""
image_naming.py
---------------
Derives a stable, human-readable filename for an image from its raw bytes.

The name is built by hashing the blob with SHA-256, then using the hash to
select an adjective and a noun from curated word-lists, plus a short numeric
suffix.  This makes the name:

  * Position-independent  – does not depend on slide or element index.
  * Deterministic         – the same image always yields the same name.
  * Human-readable        – looks like "golden-horizon-07".
  * Collision-resistant   – 48 adjectives × 48 nouns × 100 suffixes = 230 400
                            distinct names.
"""

import hashlib

# ── word lists ────────────────────────────────────────────────────────────────
# Keep both lists the same length so the modulo arithmetic is symmetric.

_ADJECTIVES: tuple[str, ...] = (
    "amber", "arctic", "azure", "bold", "bright", "calm", "cerulean",
    "cosmic", "crimson", "crystal", "deep", "dusk", "emerald", "ethereal",
    "faint", "frosted", "gentle", "gilded", "glacial", "golden", "grand",
    "hollow", "icy", "indigo", "jade", "keen", "lavender", "lunar",
    "misty", "noble", "north", "opal", "pale", "radiant", "rising",
    "ruby", "sapphire", "serene", "shining", "silent", "silver", "solar",
    "starlit", "still", "swift", "velvet", "warm", "wild",
)

_NOUNS: tuple[str, ...] = (
    "aurora", "beacon", "cedar", "cloud", "comet", "coral", "creek",
    "delta", "dune", "echo", "ember", "fjord", "forest", "gale", "glacier",
    "grove", "harbor", "haven", "horizon", "isle", "lagoon", "lake",
    "leaf", "mesa", "meteor", "mist", "moon", "nebula", "nova", "ocean",
    "orbit", "peak", "pine", "plain", "prism", "quartz", "reef", "ridge",
    "river", "sky", "solstice", "star", "stone", "storm", "summit",
    "tide", "trail", "universe",
)

assert len(_ADJECTIVES) == len(_NOUNS), "Word lists must be the same length."

_N = len(_ADJECTIVES)   # 48


# ── public API ────────────────────────────────────────────────────────────────

def name_for_image(blob: bytes, ext: str) -> str:
    """
    Return a stable, human-readable filename for *blob*.

    The extension is appended without a leading dot being required in *ext*
    (e.g. ``ext="png"`` → ``"warm-universe-05.png"``).

    The name is derived exclusively from the image content, so it is
    independent of slide order or element position.
    """
    digest = hashlib.sha256(blob).digest()

    # Use the first three bytes to pick adjective, noun and suffix
    adj_idx    = digest[0] % _N          # 0–47
    noun_idx   = digest[1] % _N          # 0–47
    suffix     = digest[2] % 100         # 00–99

    adj  = _ADJECTIVES[adj_idx]
    noun = _NOUNS[noun_idx]

    return f"{adj}-{noun}-{suffix:02d}.{ext}"
