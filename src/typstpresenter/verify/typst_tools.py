"""
Thin wrappers around the ``typst`` CLI for compiling and querying documents.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class TypstError(RuntimeError):
    pass


@dataclass
class TimedResult:
    """Result of a typst invocation plus wall-clock duration in seconds."""
    value: object
    seconds: float


def _run(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise TypstError(f"{' '.join(args)} failed:\n{proc.stderr}")
    return proc.stdout


def compile_pdf(typ_path: Path, pdf_path: Path | None = None) -> TimedResult:
    """Compile a Typst file to PDF; returns the PDF path and elapsed time."""
    typ_path = Path(typ_path)
    pdf_path = pdf_path or typ_path.with_suffix(".pdf")
    start = time.perf_counter()
    _run(["typst", "compile", str(typ_path), str(pdf_path)])
    return TimedResult(pdf_path, time.perf_counter() - start)


def query(typ_path: Path, selector: str, field: str = "value") -> TimedResult:
    """
    Run ``typst query`` and parse the JSON result.

    With ``field="value"`` on a metadata selector this returns the plain
    list of metadata payloads. No PDF is exported.
    """
    start = time.perf_counter()
    out = _run(["typst", "query", str(typ_path), selector, "--field", field])
    return TimedResult(json.loads(out), time.perf_counter() - start)
