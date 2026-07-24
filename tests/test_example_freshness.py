"""Freshness guard for the shipped worked examples' `findings.json` (issue #6).

The two committed worked examples (`examples/<repo>/ci-speedup-findings-report.md`)
are the front-door artifacts a public reader opens first. `test_committed_reports.py`
fresh-renders and verifies the analogous corpus under `skills/ci-speedup/reports/`,
but that guard globs `reports/` only and never sees `examples/` — and until now,
`examples/` shipped only the rendered `.md`, with no committed `findings.json` for
anything to re-verify against. A renderer change could silently make a committed
example stop matching what the current code actually produces, with nothing to
catch it.

This guard closes that gap: for each committed `examples/<repo>/findings.json`, it
re-renders with the CURRENT `blocking_path.py` (no `gh` calls — a fresh render is a
pure, local, offline recomputation from already-collected data) and checks the
result (a) matches the committed `.md` byte-for-byte, provenance stamp aside, and
(b) passes `verify_report`'s content invariants.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

# A healthy report fires ~20 non-skipped checks; far below this means the render
# degraded (near-empty) or run_checks silently shrank — a vacuous-pass guard.
_MIN_CHECKS_FIRED = 12

_REPO = Path(__file__).resolve().parents[1]
_EXAMPLES = _REPO / "examples"

# The provenance footer is the one line that legitimately differs between a fresh
# render and the committed bytes: it stamps the renderer's own git state (which
# commit produced this render), so re-rendering today always changes it even when
# nothing else did. Normalize it out before comparing.
_PROVENANCE_RE = re.compile(r"\(skill commit `[^`]*`(?:, scripts tree `[^`]*`)?\)")


def _sans_provenance(report: str) -> str:
    return _PROVENANCE_RE.sub("(skill commit `X`, scripts tree `X`)", report)


def _example_findings() -> list[Path]:
    fs = sorted(_EXAMPLES.glob("*/findings.json"))
    if not fs:
        pytest.skip("no findings.json found under examples/ — nothing to freshness-check")
    return fs


def _load_verify_report():
    # `verify_report` is not a unique module name (other skills ship one too), so
    # load THIS skill's copy by file path under a unique name, avoiding a cross-skill
    # import clash — same reasoning test_committed_reports.py uses for this helper.
    path = _REPO / "skills" / "ci-speedup" / "tests" / "verify_report.py"
    name = "ci_speedup_verify_report_for_examples"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _render_fresh(findings_path: Path, out_path: Path) -> str:
    """Render `findings.json` with the CURRENT renderer and return the markdown."""
    r = subprocess.run(
        [sys.executable, str(_REPO / "skills" / "ci-speedup" / "scripts" / "blocking_path.py"),
         "--in", str(findings_path), "--out", str(out_path)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"fresh render failed for {findings_path.parent.name}:\n{r.stderr}"
    report = out_path.read_text(encoding="utf-8")
    assert len(report) > 2000, (
        f"fresh render of {findings_path.parent.name} is only {len(report)} chars — "
        "degenerate render (would pass content scans vacuously)")
    return report


@pytest.fixture(scope="module")
def fresh_reports(tmp_path_factory):
    """Render each committed examples/*/findings.json ONCE, shared across every
    test below that asks for it — a list of (repo, findings_path, md_path, rendered_text)."""
    out_dir = tmp_path_factory.mktemp("fresh_examples")
    out = []
    for fj in _example_findings():
        repo = fj.parent.name
        md = out_dir / f"{repo}.md"
        out.append((repo, fj, md, _render_fresh(fj, md)))
    return out


def test_example_report_matches_a_fresh_render(fresh_reports):
    """A committed example must be exactly what today's renderer produces from its
    committed findings.json — provenance stamp aside. Catches silent staleness."""
    stale = []
    for repo, fj, _md, fresh in fresh_reports:
        committed_md = fj.parent / "ci-speedup-findings-report.md"
        committed = committed_md.read_text(encoding="utf-8")
        if _sans_provenance(committed) != _sans_provenance(fresh):
            stale.append(repo)
    assert not stale, (
        f"committed example report(s) no longer match a fresh render: {stale}. "
        "Re-render (`blocking_path.py --in findings.json --out "
        "ci-speedup-findings-report.md`) and commit the result.")


def test_example_fresh_render_passes_verify_report_invariants(fresh_reports):
    """verify_report over a FRESH render of each committed examples/*/findings.json
    (real data, current renderer) — a renderer/verifier drift fails here, not just
    a byte-level staleness. Every example runs the FULL check set; nothing is
    skipped wholesale, so a real regression can't hide behind a whole-repo skip."""
    vr = _load_verify_report()
    failures: list[str] = []
    for repo, fj, md, report in fresh_reports:
        fired: set[str] = set()
        for c in vr.run_checks(report, md, fj, skill_repo=None):
            if c.skipped:
                continue
            fired.add(c.name)
            if not c.ok:
                failures.append(f"{repo}: {c.name} - {c.detail}")
        if len(fired) < _MIN_CHECKS_FIRED:
            failures.append(
                f"{repo}: only {len(fired)} checks fired (< {_MIN_CHECKS_FIRED}) — "
                "render degraded or run_checks shrank (vacuous-pass risk)")
    assert not failures, (
        "fresh-render verify_report invariant failures:\n" + "\n".join(failures))
