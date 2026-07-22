#!/usr/bin/env python3
"""Decision ledger for the ci-speedup transcript self-improvement loop (PR-C, maintainers-only).

loop-self-improvement-upgrades.md §2, Item 3 (PR-C, TRANSCRIPT half only — the gap-loop half is
explicitly DEFERRED, see the module-end note). The cross-session recurrence gate in
``aggregate_lessons.py`` promotes a lesson once it recurs across ``>= RECURRENCE_MIN`` distinct
sessions, but it has no memory of a maintainer's PAST verdict on a promoted lesson. Without a ledger,
a lesson the maintainer explicitly REJECTED (bad idea, too narrow, wrong root cause) re-surfaces as
PROMOTED on every subsequent run for as long as its transcripts stay staged — pure noise that trains
the maintainer to stop reading PROMOTED.

This module is that memory: a gitignored, append-only ``.ci-speedup-loop/decisions.jsonl``, one row
per maintainer decision, written by a NEW ``--decide`` step the maintainer runs at the land gate
(after acting on a PROMOTED cluster — approve it into SKILL.md/evals, land it in modified form, or
decline it). A row is ``{signature, disposition, reason, skill_commit_sha, decided_at}``.
``disposition`` is exactly one of:

  - ``approved``   — the lesson landed in SKILL.md/evals verbatim. It SELF-suppresses (it's now in
                     the contract, so the analysis prompt won't re-propose it) — this row is an
                     AUDIT RECORD, not a suppressor. ``is_suppressed`` never returns True for it.
  - ``superseded`` — landed in a MODIFIED form (the maintainer edited the proposal before landing).
                     Same suppression behavior as ``approved`` (it landed) — kept as a distinct value
                     purely so the audit trail shows the loop's text was edited, not adopted verbatim.
  - ``rejected``   — the maintainer declined it; ``reason`` says why. THIS is the one disposition
                     ``is_suppressed`` acts on: the signature is excluded from
                     ``aggregate_lessons.py``'s PROMOTED list until the rejection goes STALE.

A rejection re-surfaces (loudly, carrying the prior reason) on EITHER:
  (i)  ancestry staleness — the rejection's ``skill_commit_sha`` is no longer an ancestor of the
       current ``SKILL.md`` (the code it was judged against has since changed), or
  (ii) a ``REJECTION_TTL_DAYS`` TTL (mirrors ``aggregate_lessons.PENDING_TTL_DAYS`` = 90) — a
       rejection against never-changing code must not suppress a real lesson FOREVER.
A fresh ``--decide … rejected`` for the same signature always wins (the newest row governs — "resets
the clock"). Safe default: NO row for a signature -> never suppressed (suppression is opt-in via the
``--decide`` habit, not a silent default that could hide a real lesson nobody ever decided on).

Local-only, maintainer-only, like the rest of the loops: reads/writes only inside the gitignored
``.ci-speedup-loop/`` directory (already covered by the repo's ``.gitignore`` — the WHOLE directory
is ignored) and never commits.

Usage:
    decision_ledger.py --decide SIGNATURE {approved,rejected,superseded} --reason "..."
                        [--skill-commit-sha SHA] [--loop-dir .ci-speedup-loop]
        # Appends ONE row to decisions.jsonl. --skill-commit-sha defaults to the current git HEAD
        # sha of this checkout (mirrors aggregate_lessons' own provenance stamp); pass it explicitly
        # when running outside a git checkout.

    decision_ledger.py --check SIGNATURE [--loop-dir .ci-speedup-loop]
        # Prints the current suppression verdict for SIGNATURE against the ledger (read-only, no
        # write) — a manual/debugging entry point; aggregate_lessons.py is the real consumer.

This module is import-safe: ``is_suppressed`` takes injected ``now`` / ``current_skill_sha`` /
``is_ancestor`` so the gate is exercised on synthetic decisions without a git checkout or a wall
clock — exactly like ``aggregate_lessons.aggregate``. It reuses ``aggregate_lessons.normalize_signature``
for keys (per spec §2, Item 3), imported LAZILY (inside the function, not at module top) so this
module and ``aggregate_lessons.py`` never form a load-time import cycle even though each calls into
the other (``aggregate_lessons.py``'s own ledger wiring lazy-imports THIS module the same way).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_DIR = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)

_LOOP_DIR = ".ci-speedup-loop"
_DECISIONS_FILE = "decisions.jsonl"

DISPOSITIONS = {"approved", "rejected", "superseded"}
# Only `rejected` ever suppresses promotion — approved/superseded landed, so the ledger row for them
# is an audit record only (see module docstring).
SUPPRESSING_DISPOSITIONS = {"rejected"}

# Mirrors aggregate_lessons.PENDING_TTL_DAYS: a rejection against never-changing code must not
# suppress a real lesson forever.
REJECTION_TTL_DAYS = 90


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
@dataclass
class Decision:
    """One ledger row: a maintainer's verdict on one signature, at one point in time."""

    signature: str            # raw, as recorded (normalized for comparison, not for display)
    disposition: str          # approved | rejected | superseded
    reason: str
    skill_commit_sha: str | None
    decided_at: str           # ISO-8601


@dataclass
class SuppressionResult:
    """The verdict `is_suppressed` returns for one signature."""

    suppressed: bool
    # The governing decision (most recent row for this signature), or None if there is no row at
    # all. Present even when NOT suppressed, so a caller can still show "cleared" / "resurfaced" context.
    decision: Decision | None = None
    # Set ONLY when a `rejected` decision stopped suppressing this run (ancestry-stale or
    # TTL-expired) — the loud "why it came back" note a caller should surface, never silently.
    resurfaced_reason: str | None = None


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def _normalize_signature(sig: str) -> str:
    from aggregate_lessons import normalize_signature  # lazy — see module docstring

    return normalize_signature(sig)


def _parse_iso(ts: str) -> _dt.datetime | None:
    """Same tolerant ISO-8601 parse as aggregate_lessons._parse_iso (duplicated, not imported, to
    keep this module's pure core independently testable without pulling in aggregate_lessons at
    load time; both are tiny and drift-checked by shared fixture-replay behavior in the tests)."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


def _decision_from_row(row: dict) -> Decision:
    return Decision(
        signature=row.get("signature", ""),
        disposition=row.get("disposition", ""),
        reason=row.get("reason", ""),
        skill_commit_sha=row.get("skill_commit_sha"),
        decided_at=row.get("decided_at", ""),
    )


def _latest_decision(signature: str, decisions: list[Decision]) -> Decision | None:
    """The governing decision for a NORMALIZED signature: the LAST-APPENDED matching row (file
    order, which `load_decisions` preserves), NOT the max-`decided_at` row.

    Why append order, not a `decided_at` sort: decisions.jsonl is append-only and the `--decide`
    CLI stamps `decided_at = now` at append time, so file order IS chronological order — and using
    it directly means the maintainer's most recent verdict always governs even when its timestamp
    is missing or unparseable. A `decided_at`-sort would let a newest row with a garbage/empty
    timestamp (which sorts to `datetime.min`) be silently OUTVOTED by an older valid-ts row — e.g.
    a fresh `approved` with a bad ts losing to a stale `rejected`, violating "newest governs" and
    re-suppressing a lesson the maintainer just cleared. `decided_at` is still consulted downstream
    (the TTL age math in `is_suppressed`); it just no longer decides WHICH row wins."""
    matches = [d for d in decisions if _normalize_signature(d.signature) == signature]
    return matches[-1] if matches else None


def is_suppressed(
    signature: str,
    decisions: list[Decision],
    *,
    now: _dt.datetime,
    current_skill_sha: str | None,
    is_ancestor,
    ttl_days: int = REJECTION_TTL_DAYS,
) -> SuppressionResult:
    """Whether `signature` (already `normalize_signature`'d — same convention as
    `aggregate_lessons.Cluster.signature`) should be excluded from promotion right now.

    `is_ancestor(anc, desc) -> bool`, injected exactly like aggregate_lessons' own ancestry checker.

    Only a GOVERNING `rejected` decision (the latest row for this signature) suppresses, and only
    while it is neither ancestry-stale nor TTL-expired — either check firing re-surfaces it.
    `approved` / `superseded` (or any unrecognized disposition — this must never silently grow power
    over promotion) never suppress. No row at all -> never suppressed (opt-in, safe default)."""
    d = _latest_decision(signature, decisions)
    if d is None:
        return SuppressionResult(suppressed=False)
    if d.disposition not in SUPPRESSING_DISPOSITIONS:
        return SuppressionResult(suppressed=False, decision=d)

    # FAIL OPEN on a missing/unparseable `decided_at`: the TTL is the escape hatch that GUARANTEES a
    # rejection can't suppress forever, and it can only run with a parseable timestamp. If it's
    # missing (a schema-drifted / hand-appended row) the TTL block would be skipped AND — if the sha
    # is also absent — the ancestry hatch too, locking in PERMANENT suppression with zero signal:
    # exactly the module's fail-CLOSED anti-pattern. So a governing `rejected` row we can't age-bound
    # must RESURFACE for re-review (loudly), never suppress. `load_decisions` also surfaces this as a
    # coverage problem so it isn't only visible here.
    decided = _parse_iso(d.decided_at)
    if decided is None:
        return SuppressionResult(
            suppressed=False, decision=d,
            resurfaced_reason=(
                "rejected row has no valid decided_at (missing or unparseable) — resurfacing for "
                "re-review rather than suppressing forever (the TTL escape hatch can't run without "
                "a timestamp; fail OPEN, never lock in permanent suppression)"))
    age = now - decided
    # FAIL OPEN on a materially-FUTURE decided_at (a garbage/absurd timestamp the CLI never emits,
    # since `--decide` stamps `now`). A future date makes `age` negative, so `age > ttl_days` is
    # forever false and the row suppresses until wall-clock passes it — the same suppress-FOREVER
    # failure the missing-timestamp case above guards, reached via a different input. A ~1-day grace
    # absorbs ordinary clock skew (a few-seconds-future stamp is a fresh, legitimate rejection).
    if age < -_dt.timedelta(days=1):
        return SuppressionResult(
            suppressed=False, decision=d,
            resurfaced_reason=(
                f"rejected row decided_at is materially in the future ({-age.days}d ahead) — "
                "resurfacing for re-review rather than suppressing until that date (a future "
                "timestamp defeats the TTL escape hatch; fail OPEN)"))
    if age > _dt.timedelta(days=ttl_days):
        return SuppressionResult(
            suppressed=False, decision=d,
            resurfaced_reason=f"rejection TTL-expired ({age.days}d > {ttl_days}d)")
    if d.skill_commit_sha and current_skill_sha:
        try:
            still_ancestor = is_ancestor(d.skill_commit_sha, current_skill_sha)
        except Exception as e:
            # A TRANSIENT ancestry-check failure must not masquerade as "not an ancestor" and
            # silently re-surface a lesson the maintainer already declined — keep the suppression
            # this run (mirrors aggregate_lessons._pending_expired's identical stance).
            logger.warning(
                "ancestry check for rejected %r failed (%s); keeping the suppression this run",
                signature, e,
            )
            still_ancestor = True
        if not still_ancestor:
            return SuppressionResult(
                suppressed=False, decision=d,
                resurfaced_reason=(
                    f"rejection's skill_commit_sha {d.skill_commit_sha} is no longer an ancestor "
                    f"of the current SKILL.md ({current_skill_sha}) — ancestry-stale"))
    return SuppressionResult(suppressed=True, decision=d)


# --------------------------------------------------------------------------- #
# I/O + git glue (the impure edges)
# --------------------------------------------------------------------------- #
def load_decisions(loop_dir: Path) -> tuple[list[Decision], list[str]]:
    """Returns (decisions, problems). decisions.jsonl is append-only (never rewritten wholesale by
    this module, unlike aggregate_lessons' pending.jsonl), so a malformed line is simply skipped
    loudly (recorded in `problems`, logged) rather than preserved for a later rewrite — there is no
    rewrite path here to lose it from."""
    path = loop_dir / _DECISIONS_FILE
    if not path.is_file():
        return [], []
    decisions: list[Decision] = []
    problems: list[str] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            msg = f"malformed decisions.jsonl line {i}: {e}"
            logger.warning(msg)
            problems.append(msg)
            continue
        if not isinstance(obj, dict):
            msg = f"non-object decisions.jsonl line {i} (got {type(obj).__name__})"
            logger.warning(msg)
            problems.append(msg)
            continue
        d = _decision_from_row(obj)
        decisions.append(d)
        # A suppressing (rejected) row missing its expiry provenance is a fail-CLOSED hazard, and
        # `_decision_from_row` fills such gaps SILENTLY (decided_at→"", skill_commit_sha→None). Left
        # unsurfaced, a schema-drifted / hand-appended `{"disposition":"rejected"}` with no
        # decided_at and no sha would look like a clean row while permanently suppressing its
        # signature. `is_suppressed` already fails OPEN on a missing decided_at, but flag it here too
        # (a coverage signal, not a swallow): an unparseable/missing decided_at disables the TTL
        # hatch; a missing sha disables the ancestry hatch. The row is KEPT (not dropped) — it's the
        # newest verdict; it's just visibly under-specified.
        if d.disposition in SUPPRESSING_DISPOSITIONS:
            missing = []
            if _parse_iso(d.decided_at) is None:
                missing.append("decided_at (missing/unparseable → TTL expiry can't run)")
            if not d.skill_commit_sha:
                missing.append("skill_commit_sha (missing → ancestry expiry can't run)")
            if missing:
                msg = (f"decisions.jsonl line {i}: {d.disposition} row for {d.signature!r} lacks "
                       f"{'; '.join(missing)} — it will RESURFACE for re-review rather than suppress "
                       f"(fail-open), not silently suppress forever")
                logger.warning(msg)
                problems.append(msg)
    return decisions, problems


def _git_head_sha(skill_dir: Path) -> str | None:
    """FULL HEAD sha of this checkout (mirrors aggregate_lessons._git_skill_sha — un-abbreviated,
    since it feeds `merge-base --is-ancestor`, never rendered)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(skill_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    sha = r.stdout.strip()
    return sha if r.returncode == 0 and sha else None


def _git_is_ancestor(skill_dir: Path):
    """Return an is_ancestor(anc, desc) checker over this checkout (identical contract to
    aggregate_lessons._git_is_ancestor: a clean nonzero exit is a real 'not an ancestor' verdict; a
    TRANSIENT failure propagates so the caller keeps the suppression rather than dropping it)."""

    def check(anc: str, desc: str) -> bool:
        r = subprocess.run(
            ["git", "-C", str(skill_dir), "merge-base", "--is-ancestor", anc, desc],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0

    return check


def append_decision(loop_dir: Path, decision: Decision) -> None:
    """Append ONE row. decisions.jsonl is append-only by design (never rewritten wholesale like
    pending.jsonl), so a plain append is the right primitive — no atomic-rewrite dance needed, and an
    interrupted append can lose at most the ONE row being written, never any prior history."""
    path = loop_dir / _DECISIONS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "signature": decision.signature,
        "disposition": decision.disposition,
        "reason": decision.reason,
        "skill_commit_sha": decision.skill_commit_sha,
        "decided_at": decision.decided_at,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--decide", nargs=2, metavar=("SIGNATURE", "DISPOSITION"),
        help="record a decision: SIGNATURE (the raw lesson signature, as shown in aggregate_lessons' "
             "PROMOTED report) and DISPOSITION (one of approved/rejected/superseded).",
    )
    parser.add_argument("--reason", default="",
                         help="why (REQUIRED for --decide … rejected; recommended always).")
    parser.add_argument("--skill-commit-sha", default=None,
                         help="provenance sha (default: current git HEAD of this checkout).")
    parser.add_argument("--loop-dir", type=Path, default=Path(_LOOP_DIR))
    parser.add_argument("--check", metavar="SIGNATURE",
                         help="print the CURRENT suppression verdict for SIGNATURE against the "
                              "ledger, then exit (read-only, no write).")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("STARSLING_LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.decide:
        sig, disposition = args.decide
        if disposition not in DISPOSITIONS:
            parser.error(f"DISPOSITION must be one of {sorted(DISPOSITIONS)}, got {disposition!r}")
        if disposition == "rejected" and not args.reason.strip():
            parser.error(
                "--decide … rejected requires --reason — the suppression's whole point is a "
                "legible why the next maintainer can read.")
        sha = args.skill_commit_sha or _git_head_sha(_DIR)
        decided_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
        d = Decision(signature=sig, disposition=disposition, reason=args.reason,
                     skill_commit_sha=sha, decided_at=decided_at)
        append_decision(args.loop_dir, d)
        print(
            f"recorded: {disposition} {sig!r}" + (f" ({args.reason})" if args.reason else "")
            + f" @ skill_commit_sha={sha or '(unknown — not a git checkout)'} decided_at={decided_at}")
        return 0

    if args.check:
        decisions, problems = load_decisions(args.loop_dir)
        for p in problems:
            print(f"INPUT ISSUE: {p}")
        now = _dt.datetime.now(_dt.timezone.utc)
        sha = _git_head_sha(_DIR)
        res = is_suppressed(
            _normalize_signature(args.check), decisions, now=now,
            current_skill_sha=sha, is_ancestor=_git_is_ancestor(_DIR))
        if res.suppressed:
            print(f"SUPPRESSED — rejected {res.decision.decided_at} (reason: {res.decision.reason})")
        elif res.resurfaced_reason:
            print(
                f"RE-SURFACED — was rejected {res.decision.decided_at} but {res.resurfaced_reason} "
                f"(prior reason: {res.decision.reason})")
        elif res.decision:
            print(f"not suppressed — governing decision is {res.decision.disposition} (audit record only)")
        else:
            print("not suppressed — no decision on record")
        return 0

    parser.error("pass --decide SIGNATURE DISPOSITION [--reason ...] or --check SIGNATURE")
    return 2  # unreachable (parser.error exits), kept for clarity/lint


if __name__ == "__main__":
    raise SystemExit(main())
