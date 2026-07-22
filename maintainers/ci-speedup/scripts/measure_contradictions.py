#!/usr/bin/env python3
"""Phase-0 baseline producer (maintainers-only) — seal-single-door.md §4(B).

Runs the cross-seam **contradiction property** (`verify_report`'s Phase-0 checks) over a panel
of already-rendered reports and prints the two baseline rates that the relocation **Decision
gate** (§4) consumes:

  - **contradiction rate** — % of panel repos whose report trips the contradiction property or
    the headline↔stamp comparator. This is the internal-correctness signal; with Phase 0 wired
    into CI it should trend to 0 on fresh renders.
  - **consumer-divergence rate** — % of panel repos where the cross-repo consumer's pole pick
    would differ from the report's headline gate. PROXY here (the precise pick lives in
    `ci-harness`): we compare `critical_path_check` (what the report headlines, a CHECK name)
    against the job of the MAX-`wall_clock_p50_s` ON-SPINE finding (a JOB name — what a
    `sort_by(-wall_clock_p50_s)` consumer would grab, restricted to on-spine findings via the
    `off_spine` stamp). A divergence means the auto-fixer would optimize a different pole than the
    report shows — the ONLY thing the data-layer relocation buys, hence the gate's input. TWO
    known crudenesses (why it is non-decisive): it compares a JOB to a CHECK (different namespaces
    — inflates), and `off_spine` is absent from OLD stampless bundles so the on-spine restriction
    only bites on freshly-rendered reports. Confirm the real rate in `ci-harness` before gating.

This is a LOCAL maintainer step, NOT a CI peer of verify_report (it needs rendered reports for
the whole panel). It does not clone or call gh; point it at a directory of pre-rendered
`<slug>-report.md` + `<slug>.json` (or `<slug>-findings.json`) pairs produced by the fleet
runner. Slugs are matched by their `owner_repo` mangling (``/`` -> ``_``) and by basename.

    python3 measure_contradictions.py --panel panel.txt --reports-dir /tmp/cisp-val

A second, single-report mode prints the consumer-divergence verdict for ONE findings JSON (reusing
the same `_consumer_divergence`). It is a STANDALONE / manual probe — the wired dogfood
grader-seeding loop (loop-self-improvement-upgrades.md §2-A) does NOT shell out to this CLI; it
reuses the `_consumer_divergence` FUNCTION in-process via `grader_seeds.py`. This mode exposes the
same verdict for ad-hoc use and for the before/after panel-rate context:

    python3 measure_contradictions.py --single-report findings.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parents[3] / "skills" / "ci-speedup"


def _load_verify_report():
    """Load THIS skill's verify_report by path under a unique name (ci-secure ships one too)."""
    path = _SKILL_DIR / "tests" / "verify_report.py"
    spec = importlib.util.spec_from_file_location("ci_speedup_verify_report", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ci_speedup_verify_report"] = mod
    spec.loader.exec_module(mod)
    return mod


# The two Phase-0 checks whose FAIL == a shipped cross-seam contradiction.
_PHASE0_CHECK_NAMES = {
    "no spine-dropped check is also framed on the merge-gating critical path",
    "headline 'slowest check' names the data layer's critical_path_check",
}


def _read_panel(path: Path) -> list[str]:
    slugs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            slugs.append(line)
    return slugs


def _find_pair(reports_dir: Path, slug: str,
               ambiguous_bare: "set[str] | None" = None) -> tuple[Path, Path] | None:
    """Locate (report.md, findings.json) for a slug. Tries the `owner_repo` mangling FIRST, then
    the bare repo name, against the fleet runner's `<name>-report.md` + `<name>.json` convention
    (the runner sometimes names files by the bare repo). The bare fallback is SKIPPED when the
    bare name is shared by >1 panel slug (`ambiguous_bare`), so `a/httpx` and `b/httpx` can't
    silently bind the same `httpx-report.md` — an ambiguous repo must match on its mangled stem
    or be reported missing, never mis-attributed."""
    mangled = slug.replace("/", "_")
    bare = slug.split("/")[-1]
    stems = [mangled] if (ambiguous_bare and bare in ambiguous_bare) else [mangled, bare]
    for stem in stems:
        md = reports_dir / f"{stem}-report.md"
        for fj in (reports_dir / f"{stem}.json", reports_dir / f"{stem}-findings.json"):
            if md.exists() and fj.exists():
                return md, fj
    return None


def _consumer_divergence(findings: dict) -> tuple[bool, str]:
    """PROXY consumer-divergence: does the job of the max-`wall_clock_p50_s` ON-SPINE finding
    differ from the report's headline gate (`critical_path_check`)? Returns (diverges, detail).
    `off_spine` findings are skipped (they aren't on the merge gate the auto-fixer optimizes —
    though that stamp is absent from old stampless bundles, so the skip only bites on fresh
    reports); a finding with no positive wall-clock, or no stamped gate, is 'no divergence
    measurable'. See the module docstring for the two crudenesses that make this non-decisive.

    A non-dict `findings` (e.g. a JSON file whose top level is a list/string) is 'not measurable',
    NOT a crash — every caller (panel loop, single-report CLI, grader_seeds) passes whatever
    `json.loads` returned, so guard the shape here once rather than at each callsite."""
    if not isinstance(findings, dict):
        return False, "findings is not a JSON object"
    # Shape-guard the inner containers too (not just the top-level dict): a wrong-TYPE
    # `pr_critical_path` (a list) or `findings` (an object) is 'not measurable', NOT a crash. This
    # matters since verify_report's containers were hardened the same way — and `_consumer_divergence`
    # shares grader_seeds' one `try/except`, so an unguarded crash here would discard a whole grade for
    # exactly the malformed-findings class verify_report now survives.
    cp = findings.get("pr_critical_path")
    cp = cp if isinstance(cp, dict) else {}
    gate = cp.get("critical_path_check")
    if not gate:
        return False, "no critical_path_check"
    best, best_wc = None, 0.0
    flist = findings.get("findings")
    for f in (flist if isinstance(flist, list) else []):
        if not isinstance(f, dict):
            continue
        try:
            wc = float(f.get("wall_clock_p50_s") or 0.0)
        except (TypeError, ValueError):
            wc = 0.0
        if wc > best_wc and not f.get("off_spine"):
            aj = f.get("affected_jobs")
            jobs = [j for j in (aj if isinstance(aj, list) else []) if str(j)]
            if jobs:
                best, best_wc = jobs[0], wc
    if best is None:
        return False, "no wall-clock-positive on-spine finding"
    # Compare at JOB-BASE level: strip the @scope/ prefix the renderer drops AND the trailing
    # `(matrix params)`, so two legs of the SAME job (`build (win)` vs `build (ubuntu)` — the
    # same fix) are NOT counted as a divergence. Only a different JOB is a meaningful "consumer
    # optimizes the wrong thing". (This proxy still uses the max-wall_clock finding, not the
    # harness's real `checks[0]` gate pick — confirm the true rate in ci-harness before gating.)
    def _base(s: str) -> str:
        s = re.sub(r"^@[^ /]+/", "", str(s))      # drop @scope/
        s = re.sub(r"\s*\(.*\)\s*$", "", s)        # drop trailing (matrix params)
        return s.strip().lower()
    diverges = _base(best) != _base(gate)
    return diverges, f"consumer→`{best}` vs headline→`{gate}`"


def _single_report_divergence(findings_path: Path) -> int:
    """`--single-report`/`--divergence-only` mode (loop-self-improvement-upgrades.md §2-A, PR-A).

    Run the SAME `_consumer_divergence` the panel loop uses against ONE findings JSON and print a
    structured (JSON) verdict, reusing the function rather than re-implementing it (which would
    drift from the panel's definition). A MEASURED verdict carries `"measured": true` + a `diverges`
    boolean and exits 0 (a divergence is a SIGNAL, not a gate failure — the caller decides). An
    unreadable / non-JSON findings file is a measurement FAILURE, not a clean result: it emits
    `"measured": false, "diverges": null` + an `error`, and exits 2 — so a caller can never read a
    couldn't-measure as a "no divergence" (the no-silent-drops rule). Never crashes."""
    try:
        findings = json.loads(findings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(json.dumps({"mode": "divergence-only", "findings": str(findings_path),
                          "measured": False, "diverges": None, "error": f"findings unreadable: {e}"}))
        return 2
    diverges, detail = _consumer_divergence(findings)
    print(json.dumps({"mode": "divergence-only", "findings": str(findings_path),
                      "measured": True, "diverges": bool(diverges), "detail": detail}))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase-0 contradiction/divergence baseline.")
    p.add_argument("--panel", type=Path, help="repo-slug panel (panel mode)")
    p.add_argument("--reports-dir", type=Path,
                   help="dir of pre-rendered <slug>-report.md + <slug>.json pairs (panel mode)")
    p.add_argument("--single-report", "--divergence-only", dest="single_report", type=Path,
                   metavar="FINDINGS_JSON",
                   help="single-report mode: print the consumer-divergence verdict for ONE "
                        "findings JSON (reuses the panel's _consumer_divergence; no re-impl)")
    args = p.parse_args(argv)

    # Single-report mode is a self-contained probe — no panel/reports-dir needed.
    if args.single_report is not None:
        return _single_report_divergence(args.single_report)

    # Panel mode needs both --panel and --reports-dir (was required=True before the mode split).
    if args.panel is None or args.reports_dir is None:
        p.error("panel mode needs --panel and --reports-dir (or use --single-report FINDINGS_JSON)")

    vr = _load_verify_report()
    slugs = _read_panel(args.panel)
    # Bare repo names shared by >1 panel slug — their bare-name file match is ambiguous, so
    # `_find_pair` must not use the bare fallback for them (avoids mis-attributing a report).
    _bare = [s.split("/")[-1] for s in slugs]
    ambiguous_bare = {b for b in _bare if _bare.count(b) > 1}
    contradiction = divergence = measured = missing = 0
    rows: list[str] = []
    for slug in slugs:
        pair = _find_pair(args.reports_dir, slug, ambiguous_bare)
        if pair is None:
            missing += 1
            rows.append(f"  {slug}: (no rendered report found — not measured)")
            continue
        md, fj = pair
        report = md.read_text(encoding="utf-8")
        try:
            findings = json.loads(fj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            missing += 1
            rows.append(f"  {slug}: (findings unreadable — not measured)")
            continue
        measured += 1
        fails = [c for c in vr.run_checks(report, md, fj, skill_repo=None)
                 if c.name in _PHASE0_CHECK_NAMES and not c.skipped and not c.ok]
        diverges, detail = _consumer_divergence(findings)
        contradiction += bool(fails)
        divergence += bool(diverges)
        flag = "CONTRADICTION" if fails else ("diverge" if diverges else "ok")
        rows.append(f"  {slug}: {flag}  [{detail}]"
                    + ("".join(f"\n      FAIL: {c.name} — {c.detail}" for c in fails)))

    print("\n".join(rows))
    print(f"\n=== Phase-0 baseline over {measured} measured panel repo(s)"
          + (f" ({missing} missing)" if missing else "") + " ===")
    if not measured:
        # Nothing measured (no report pairs matched the panel) is NOT success — exit non-zero
        # so an automated caller can't read a baseline-less run as "0% clean".
        print(f"\n⚠️  measured 0 / {len(slugs)} panel repo(s) — no rendered report pairs found "
              f"in {args.reports_dir}; baseline NOT produced.")
        return 1
    print(f"contradiction rate:      {contradiction}/{measured} "
          f"({100*contradiction/measured:.0f}%)  [target → 0 with Phase 0 in CI]")
    print(f"consumer-divergence rate: {divergence}/{measured} "
          f"({100*divergence/measured:.0f}%)  [the Decision-gate input; PROXY — confirm in ci-harness]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
