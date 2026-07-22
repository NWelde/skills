"""Tests for the Phase-0 baseline producer (seal-single-door.md §4(B))."""
from __future__ import annotations

import json

import pytest

import measure_contradictions as mc


def test_read_panel_skips_comments_and_blanks(tmp_path):
    p = tmp_path / "panel.txt"
    p.write_text("# header\n\nencode/httpx\n  pallets/flask  \n# trailing\n", encoding="utf-8")
    assert mc._read_panel(p) == ["encode/httpx", "pallets/flask"]


def test_find_pair_skips_ambiguous_bare_fallback(tmp_path):
    # Two panel slugs share the bare name `httpx`; a lone `httpx-report.md`/`httpx.json` pair
    # must NOT be mis-attributed via the bare fallback — only a mangled-stem file matches.
    (tmp_path / "httpx-report.md").write_text("# r\n", encoding="utf-8")
    (tmp_path / "httpx.json").write_text("{}", encoding="utf-8")
    (tmp_path / "a_httpx-report.md").write_text("# r\n", encoding="utf-8")
    (tmp_path / "a_httpx.json").write_text("{}", encoding="utf-8")
    amb = {"httpx"}
    assert mc._find_pair(tmp_path, "a/httpx", amb) is not None        # mangled stem matches
    assert mc._find_pair(tmp_path, "b/httpx", amb) is None            # bare fallback refused
    # With no ambiguity, the bare fallback still works (the common single-owner case).
    assert mc._find_pair(tmp_path, "b/httpx", set()) is not None


def test_phase0_check_names_match_verify_report():
    # Guard against drift: the names this script tallies as contradictions must EXACTLY match
    # the live verify_report Check.name strings, or the baseline silently measures nothing.
    vr = mc._load_verify_report()
    names = {c.name for c in vr.run_checks("# x\n", None, None, skill_repo=None)}
    assert mc._PHASE0_CHECK_NAMES <= names, mc._PHASE0_CHECK_NAMES - names


def _doc(gate, findings):
    return {"pr_critical_path": {"critical_path_check": gate}, "findings": findings}


def test_divergence_false_when_consumer_pole_base_equals_headline():
    # Same job base (only matrix params differ) → NOT a divergence (same fix).
    d, _ = mc._consumer_divergence(_doc(
        "build (ubuntu-py315)",
        [{"affected_jobs": ["build (windows-py310)"], "wall_clock_p50_s": 400.0}]))
    assert d is False


def test_divergence_true_when_consumer_pole_is_a_different_job():
    d, detail = mc._consumer_divergence(_doc(
        "Benchmark",
        [{"affected_jobs": ["Autobahn testsuite"], "wall_clock_p50_s": 500.0}]))
    assert d is True
    assert "Autobahn" in detail and "Benchmark" in detail


def test_divergence_strips_scope_prefix():
    # The check-run carries a monorepo `@scope/` prefix the renderer drops; the FINDING's job
    # name already lacks it (the better-auth shape) → after the strip they match, no divergence.
    d, _ = mc._consumer_divergence(_doc(
        "@better-auth-test/prisma-adapter Integration Test",
        [{"affected_jobs": ["prisma-adapter Integration Test"], "wall_clock_p50_s": 300.0}]))
    assert d is False


def test_divergence_ignores_off_spine_and_zero_wall_clock_findings():
    # An off_spine finding (or a zero-wall-clock one) is not what a consumer would optimize.
    d, detail = mc._consumer_divergence(_doc(
        "Build",
        [{"affected_jobs": ["Deploy"], "wall_clock_p50_s": 999.0, "off_spine": True},
         {"affected_jobs": ["Build"], "wall_clock_p50_s": 50.0}]))
    assert d is False, detail


def test_divergence_unmeasurable_without_gate_or_finding():
    assert mc._consumer_divergence(_doc(None, []))[0] is False
    assert mc._consumer_divergence(_doc("Build", []))[0] is False


def test_consumer_divergence_non_dict_findings_does_not_crash():
    # A findings JSON whose top level is a list/string must be "not measurable", never an
    # AttributeError (every caller passes raw json.loads output).
    assert mc._consumer_divergence([]) == (False, "findings is not a JSON object")
    assert mc._consumer_divergence("oops")[0] is False


def test_consumer_divergence_wrong_type_inner_containers_do_not_crash():
    # verify_report's containers were hardened to survive wrong-TYPE inner containers; this sibling
    # consumer shares grader_seeds' one try/except, so an unguarded crash here would discard a whole
    # grade for exactly that malformed-findings class. None of these may raise:
    cases = [
        {"findings": {"a": "b"}, "pr_critical_path": {"critical_path_check": "x"}},  # findings an OBJECT (iterable)
        {"findings": "nope", "pr_critical_path": {"critical_path_check": "x"}},      # findings a STRING (iterable)
        {"findings": 5, "pr_critical_path": {"critical_path_check": "x"}},           # findings a NON-ITERABLE scalar
        {"findings": True, "pr_critical_path": {"critical_path_check": "x"}},        # (pins the `isinstance(flist,list)` guard —
        {"findings": 3.7, "pr_critical_path": {"critical_path_check": "x"}},         #  an iterable wrong-type is masked by the entry guard)
        {"pr_critical_path": [1, 2], "findings": []},                                 # pr_critical_path a LIST
        {"findings": ["str", 1], "pr_critical_path": {"critical_path_check": "x"}},   # entry non-dict
        {"findings": [{"wall_clock_p50_s": 5, "affected_jobs": 9}],                   # affected_jobs scalar
         "pr_critical_path": {"critical_path_check": "x"}},
    ]
    for c in cases:
        diverges, _ = mc._consumer_divergence(c)   # must return cleanly, never raise
        assert diverges is False, c


# --- single-report CLI mode (main routing + the measured/unreadable contract) ----------------
def test_main_single_report_measured_divergence(tmp_path, capsys):
    fj = tmp_path / "div.json"
    fj.write_text(json.dumps(_doc(
        "Benchmark", [{"affected_jobs": ["Autobahn"], "wall_clock_p50_s": 500.0}])), encoding="utf-8")
    rc = mc.main(["--single-report", str(fj)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["measured"] is True and out["diverges"] is True


def test_main_single_report_unreadable_returns_2_and_is_distinguishable(tmp_path, capsys):
    # A measurement FAILURE must not read as "no divergence": measured:false, diverges:null, exit 2.
    rc = mc.main(["--single-report", str(tmp_path / "missing.json")])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert out["measured"] is False and out["diverges"] is None and "error" in out


def test_main_single_report_non_dict_is_measured_not_divergent_no_crash(tmp_path, capsys):
    # A wrong-shape (list) findings file is still READABLE, so it is measured:true — the shape guard
    # in _consumer_divergence reports it as not-divergent rather than crashing. (measured reflects
    # "the file parsed", not "the shape was usable".)
    fj = tmp_path / "list.json"
    fj.write_text("[]", encoding="utf-8")  # valid JSON, wrong shape
    rc = mc.main(["--single-report", str(fj)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["measured"] is True and out["diverges"] is False


def test_main_panel_mode_missing_reports_dir_errors(tmp_path):
    panel = tmp_path / "panel.txt"
    panel.write_text("encode/httpx\n", encoding="utf-8")
    # Panel mode needs BOTH --panel and --reports-dir; the relaxed (optional) args must still
    # p.error → SystemExit(2) when one is missing (the backward-compat guard).
    with pytest.raises(SystemExit) as ei:
        mc.main(["--panel", str(panel)])
    assert ei.value.code == 2
