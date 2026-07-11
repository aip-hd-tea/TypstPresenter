"""
Benchmark: accuracy and speed of verification Methods A and B.

Runs both methods over the generated corpus (clean cases plus
fault-injected variants with known ground truth) and scores:

- false positives: issues reported on elements without an injected fault
  (in clean cases: any issue at all),
- detection: for every injected fault, whether all expected issue kinds
  were reported. Expectations are method-specific -- ink-based Method A
  cannot in principle see resizing of borderless boxes, so those faults
  are excluded from its expectations (see ``Fault.expected_issues_ink``).

Timings are wall-clock, repeated to smooth OS noise.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from typstpresenter.verify.compare import (
    Issue,
    Tolerances,
    compare_by_id,
    compare_spatial,
)
from typstpresenter.verify.corpus import CorpusCase, generate_corpus
from typstpresenter.verify.method_a import run_method_a
from typstpresenter.verify.method_b import run_method_b


@dataclass
class MethodScore:
    seconds: list[float] = field(default_factory=list)
    detected_faults: int = 0
    expected_faults: int = 0
    false_positives: int = 0
    issue_log: list[str] = field(default_factory=list)

    @property
    def mean_seconds(self) -> float:
        return sum(self.seconds) / len(self.seconds) if self.seconds else 0.0

    @property
    def recall(self) -> float:
        return self.detected_faults / self.expected_faults if self.expected_faults else 1.0


@dataclass
class CaseResult:
    case: CorpusCase
    a: MethodScore
    b: MethodScore


def _score(issues: list[Issue], expected: dict[str, set[str]],
           score: MethodScore, has_extra_text_fault: bool) -> None:
    reported: dict[str | None, set[str]] = {}
    for issue in issues:
        reported.setdefault(issue.element_id, set()).add(issue.kind)

    for element_id, expected_kinds in expected.items():
        if not expected_kinds:
            continue
        score.expected_faults += 1
        if expected_kinds <= reported.get(element_id, set()):
            score.detected_faults += 1
        else:
            missing = expected_kinds - reported.get(element_id, set())
            score.issue_log.append(f"MISSED {element_id}: {sorted(missing)}")

    for element_id, kinds in reported.items():
        if element_id in expected:
            continue
        if element_id is None and has_extra_text_fault:
            # 'extra' reports on injected text are correct detections
            continue
        score.false_positives += len(kinds)
        score.issue_log.append(f"FALSE POSITIVE {element_id}: {sorted(kinds)}")


def run_benchmark(corpus_dir: Path | str, repeats: int = 3,
                  tol: Tolerances = Tolerances()) -> list[CaseResult]:
    cases = generate_corpus(Path(corpus_dir))
    results: list[CaseResult] = []

    for case in cases:
        slide0 = case.truth.slides[0]
        score_a, score_b = MethodScore(), MethodScore()

        for repeat in range(repeats):
            start = time.perf_counter()
            b = run_method_b(case.typ_path, slide0.width, slide0.height)
            report_b = compare_by_id(case.truth, b.geometry,
                                     overflows=b.overflows, tol=tol)
            score_b.seconds.append(time.perf_counter() - start)

            start = time.perf_counter()
            a = run_method_a(case.typ_path)
            report_a = compare_spatial(case.truth, a.geometry, tol=tol)
            score_a.seconds.append(time.perf_counter() - start)

            if repeat == 0:
                # warnings participate in detection: they are reported to the
                # user, merely tagged as pre-existing in the source
                _score(report_a.issues + report_a.warnings,
                       case.expected_issues_a, score_a, case.allows_extra_text)
                _score(report_b.issues + report_b.warnings,
                       case.expected_issues_b, score_b, False)

        results.append(CaseResult(case=case, a=score_a, b=score_b))
    return results


def to_markdown(results: list[CaseResult]) -> str:
    lines = [
        "| case | kind | A time (s) | B time (s) | A found/expected | B found/expected | A false pos. | B false pos. |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.case.name} | {r.case.kind} "
            f"| {r.a.mean_seconds:.3f} | {r.b.mean_seconds:.3f} "
            f"| {r.a.detected_faults}/{r.a.expected_faults} "
            f"| {r.b.detected_faults}/{r.b.expected_faults} "
            f"| {r.a.false_positives} | {r.b.false_positives} |"
        )

    total_a_time = sum(r.a.mean_seconds for r in results)
    total_b_time = sum(r.b.mean_seconds for r in results)
    exp_a = sum(r.a.expected_faults for r in results)
    det_a = sum(r.a.detected_faults for r in results)
    exp_b = sum(r.b.expected_faults for r in results)
    det_b = sum(r.b.detected_faults for r in results)
    fp_a = sum(r.a.false_positives for r in results)
    fp_b = sum(r.b.false_positives for r in results)
    lines += [
        "",
        f"**Totals** -- Method A: {total_a_time:.2f}s, detected {det_a}/{exp_a}, "
        f"{fp_a} false positives. "
        f"Method B: {total_b_time:.2f}s, detected {det_b}/{exp_b}, "
        f"{fp_b} false positives.",
        "",
        "Note: expectations are method-specific; faults that are invisible in "
        "rendered ink (resizing of borderless boxes) are not expected from "
        "Method A. Measured against the *full* fault set, Method A's recall "
        f"would be {det_a}/{exp_b}.",
    ]
    logs = [(r.case.name, m, line)
            for r in results for m, s in (("A", r.a), ("B", r.b)) for line in s.issue_log]
    if logs:
        lines += ["", "Scoring details:"]
        lines += [f"- [{name}/{method}] {entry}" for name, method, entry in logs]
    return "\n".join(lines)
