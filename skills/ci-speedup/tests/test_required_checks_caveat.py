"""Guard: the required-checks caveat rides every fix direction that splits work OUT
of a check into new jobs.

A real `/ci-speedup` run diagnosed a 6m10s serial mutation-testing step as the merge
gate's dominant lever; the operator's local agent sharded it out of the single required
`test` check into a 4-way CI matrix. That silently ungates main — the new shard jobs are
NOT required status checks until someone adds them to branch protection, so the split-out
work stops gating merges while everything stays green. The run only avoided a silently
ungated main because the agent caught it unprompted.

These pins make the caveat a durable invariant, on BOTH surfaces a user/agent actually
reads: the rendered per-pole agent prompts (`_FIX_META` constraints) and the catalog doc.
Reword the caveat freely — but if you DROP it from any of these split-into-new-jobs sites,
this fails loudly rather than letting the report hand out a silently-ungating fix.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import blocking_path as bp  # noqa: E402  (uniquely-named module; no cross-skill clash)

# Fix directions whose deliver INCLUDES a split-into-new-jobs / matrix path (primary for
# cargo-test-shard and android-emulator-shard; a secondary "or"/"and/or" alternative for the
# others — see the per-key notes) — so the new jobs need re-gating in branch protection.
_SPLIT_INTO_NEW_JOBS_FIX_KEYS = [
    "cargo-test-shard",
    "android-emulator-shard",
    "gradle-test-parallelism",
    "pytest-no-xdist",         # the "shard by directory across matrix jobs" alternative
    "playwright-parallel",     # the "shard across jobs" alternative
    "benchmark-serial-reruns", # the "parallelise across runners" alternative
]

_CATALOG = (Path(__file__).resolve().parents[1] / "references" / "optimization-patterns.md").read_text()


def _has_required_checks_caveat(text: str) -> bool:
    """The caveat's load-bearing shape: it names branch protection AND required checks AND
    the silent-gating failure. Keyed on stable nouns, not exact wording, so a reword stays
    green but a DROP goes red."""
    t = re.sub(r"\s+", " ", text).lower()
    names_the_mechanism = "branch protection" in t and "required" in t
    names_the_failure = "silently" in t and "gat" in t  # "...silently stop gating merges"
    return names_the_mechanism and names_the_failure


def test_split_into_new_jobs_fix_meta_carries_the_caveat():
    for key in _SPLIT_INTO_NEW_JOBS_FIX_KEYS:
        meta = bp._FIX_META[key]
        assert _has_required_checks_caveat(meta["constraints"]), (
            f"_FIX_META['{key}'] renders a split-into-new-jobs fix but its constraints no "
            "longer warn that the new jobs must be re-added to branch protection as required "
            "checks or the split-out work silently stops gating merges."
        )


def test_catalog_sharding_patterns_carry_the_caveat():
    # OPT24 (Long Test Job Without Sharding), OPT25 (Shard Imbalance — split a leg into new
    # jobs), OPT22 (consolidate workflows — renames the check) each hand out a fix that
    # changes/adds check names, so each must carry the caveat.
    for anchor in ("Long Test Job Without Sharding", "Shard Imbalance",
                   "Sequential Workflows via `workflow_run`"):
        assert anchor in _CATALOG, (
            f"catalog anchor {anchor!r} not found — was the pattern title renamed?"
        )
        start = _CATALOG.index(anchor)
        # Bound the window at the NEXT pattern's `### ` header so each pattern's pin bites on
        # its OWN caveat — a fixed char window could bleed into the next pattern's caveat and
        # false-pass if this pattern's were dropped.
        nxt = _CATALOG.find("\n### ", start + 1)
        section = _CATALOG[start:nxt] if nxt != -1 else _CATALOG[start:]
        assert "Required-checks caveat" in section and _has_required_checks_caveat(section), (
            f"the catalog pattern near {anchor!r} lost its required-checks caveat"
        )


def test_caveat_predicate_discriminates_absent_from_present():
    """Red-proof: the SAME predicate must return False on constraints prose that has no
    caveat and True once the caveat is appended, so this guard can't silently regress into a
    tautology that always passes."""
    without = ("Tests sharded across runners must stay ISOLATED: each shard needs its own "
               "fresh backend, keep the full test count, and confirm pass/fail parity.")
    assert not _has_required_checks_caveat(without)
    with_it = without + (" If this job is a required status check, add the new shard jobs to "
                         "branch protection as required checks or the split-out tests silently "
                         "stop gating merges.")
    assert _has_required_checks_caveat(with_it)
