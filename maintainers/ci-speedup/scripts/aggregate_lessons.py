#!/usr/bin/env python3
"""Cross-session recurrence gate for the ci-speedup transcript loop.

The transcript self-improvement loop (the GENERAL loop — see
``maintainers/ci-speedup/loops/loop-analysis-prompt.md``) emits one schema-valid ``summary.json``
per session, each carrying ``steering_events`` with a stable ``signature``. On
its own, a single session's steering lesson can **over-fit a one-off**: a
maintainer's situational correction in one run becomes a permanent contract
change even though it was a quirk of that repo / that day / that operator. The
gap → catalog loop already refuses to over-fit the catalog to one repo; this
module brings the same discipline to the transcript loop.

It reads every staged ``.ci-speedup-loop/transcripts/*/summary.json``, clusters
their lessons by the normalized ``signature``, and **promotes** a lesson to an
eligible ``SKILL.md`` / ``evals`` / doc edit only when the SAME signature recurs
across ``>= RECURRENCE_MIN`` **distinct sessions**. A below-floor lesson is
**recorded** (never dropped) in ``.ci-speedup-loop/pending.jsonl`` as un-promoted
feedstock, so it can cross the floor on a later session. Once a parked lesson
crosses the floor it leaves ``pending.jsonl`` (only still-below-floor lessons are
written back) — that bookkeeping is purely about the feedstock list, NOT about
re-clustering.

A consequence worth knowing: a cluster can promote by pairing two *pending*
entries (session A held in an earlier run, session B held in a later one) with no
currently-staged transcript backing it. That promotion is real, but because both
contributing entries are now in a promoted cluster they are NOT written back, so a
``--commit`` clears them from ``pending.jsonl``. If you ``--commit`` before acting
on PROMOTED, that pending-only promotion does not re-surface on the next run.
**Act on PROMOTED first, then ``--commit``** (the report is always printed before
any write, so the signal is never lost silently — only consumed if you persist
without acting).

This run reports on **whatever transcripts are currently staged** in
``transcripts/`` — it re-reads them all every run. So a cluster that already spans
``>= RECURRENCE_MIN`` staged sessions will re-appear in PROMOTED on every run while
those transcripts remain on disk; that is idempotent, not a second promotion. The
intended workflow is: stage a batch → run → act on PROMOTED → **remove (or archive)
the transcripts you've acted on** from ``transcripts/`` so the next run only weighs
what's left. The transcripts are disposable local scratch (gitignored); clearing
handled ones between batches is the normal habit.

Pending staleness is bounded so a fossil can't "confirm" an evolved contract:
each pending entry is stamped — at the aggregation run that first parks it — with
``recorded_at`` + the current ``skill_commit_sha`` (the FULL HEAD sha, not run.py's
short footer form; see ``_git_skill_sha``), and at aggregation an entry is
**discarded** (loudly — never silently) when it is older than ``PENDING_TTL_DAYS``
OR its ``skill_commit_sha`` is no longer an ancestor of the current ``SKILL.md``.
Note this bounds entries that have AGED IN ``pending.jsonl`` across runs — a
transcript staged for the first time is stamped with the *current* provenance
regardless of when its session actually ran, so a months-old transcript freshly
staged today still relies on the maintainer's "does this still reproduce against
the current SKILL.md?" check (below) as its backstop, not the TTL/ancestry gate.

Local-only, maintainer-only — like the rest of the loops. It reads/writes only
inside the gitignored ``.ci-speedup-loop/`` directory (transcripts + the
``pending.jsonl`` feedstock) and **never** commits. The human-gated PR step
(adapt a promoted lesson into the target file + paired eval) is unchanged.

**PR-C (loop-self-improvement-upgrades.md §2, Item 3):** the PROMOTED list this module prints is
filtered a second time through ``decision_ledger.py``'s ``.ci-speedup-loop/decisions.jsonl`` — a
maintainer's past ``--decide`` verdicts — before it reaches the report, via ``apply_decision_ledger``.
A signature the maintainer explicitly REJECTED is excluded (SUPPRESSED) until that rejection goes
stale (ancestry or a 90-day TTL); a signature that just went stale re-surfaces loudly, flagged, not as
a fresh promotion. See ``decision_ledger.py``'s module docstring for the full ledger contract.

Usage:
    aggregate_lessons.py [--loop-dir .ci-speedup-loop] [--recurrence-min N]
                         [--ttl-days D] [--rejection-ttl-days D] [--commit]
    # Prints the promoted clusters (post-ledger), any SUPPRESSED / RE-SURFACED signatures, the held
    # (below-floor) list, the expired pending entries, and any input issues. pending.jsonl is
    # rewritten ONLY with --commit, so observing the report is non-destructive by default; the
    # decision ledger itself is written only by `decision_ledger.py --decide`, never by this module.

This module is import-safe: the testable core (``aggregate``) takes injected
``now`` / ``current_skill_sha`` / ``is_ancestor`` so the gate can be exercised
on synthetic summaries without a git checkout or a wall clock. ``apply_decision_ledger`` follows the
same injection discipline.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_DIR = Path(__file__).resolve().parent

# Module logger — like collect_runs, it inherits the entry point's config (INFO by
# default, DEBUG under STARSLING_LOG_LEVEL; main() calls basicConfig). The HELD /
# EXPIRED lists AND the INPUT ISSUES section (unreadable summaries, no-transcript_id
# summaries, malformed-but-preserved pending lines) are ALL printed to stdout
# (no-silent-drops), so the loud surfacing never depends on the log level.
logger = logging.getLogger(__name__)

# --- Tunable gate constants -------------------------------------------------- #
# RECURRENCE_MIN too high stalls real lessons; too low re-admits the one-off
# over-fit this gate exists to prevent. Two distinct sessions is the floor.
RECURRENCE_MIN = 2
# A pending lesson older than this (or carrying a non-ancestor skill sha) is
# treated as a fossil and expired — it must not pair with a fresh lesson to
# cross the floor against a contract that has since moved on.
PENDING_TTL_DAYS = 90

_LOOP_DIR = ".ci-speedup-loop"
_PENDING_FILE = "pending.jsonl"
_TRANSCRIPTS = "transcripts"


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
@dataclass
class LessonRecord:
    """One steering lesson, carrying just enough to cluster + re-surface it."""

    signature: str  # normalized key used for clustering
    raw_signature: str  # as written in the summary (for display)
    session_id: str  # transcript_id — the unit of "distinct session"
    skill_commit_sha: str | None  # provenance at the time it was recorded
    recorded_at: str | None  # ISO-8601; when this lesson was first recorded
    lesson: dict = field(default_factory=dict)  # the steering_event body

    def pending_key(self) -> tuple[str, str]:
        """Dedup key for the pending file: one row per (session, signature)."""
        return (self.session_id, self.signature)


@dataclass
class Cluster:
    signature: str
    records: list[LessonRecord]

    @property
    def distinct_sessions(self) -> set[str]:
        # An empty / absent session id is unattributable, so it must NOT count toward the
        # recurrence floor — otherwise a single summary missing its transcript_id could
        # pair with one real session and self-promote across the floor.
        return {r.session_id for r in self.records if r.session_id}

    @property
    def raw_signature(self) -> str:
        # All records share a normalized signature; show the first raw form.
        return self.records[0].raw_signature if self.records else self.signature


@dataclass
class AggregationResult:
    promoted: list[Cluster]  # >= RECURRENCE_MIN distinct sessions — eligible to PR
    held: list[Cluster]  # below the floor — recorded, surfaced, not encoded
    expired: list[LessonRecord]  # pending entries dropped (logged, never silent)
    new_pending: list[dict]  # the pending.jsonl rows to persist


@dataclass
class LedgerFilterResult:
    """PR-C: `aggregate()`'s PROMOTED list filtered through the decision ledger
    (`decision_ledger.py`). Kept separate from `AggregationResult` — the recurrence gate itself
    (`aggregate`) stays ledger-agnostic and testable on its own; this is a second, composable pass."""

    promoted: list[Cluster]  # survives ledger suppression — what a caller should actually act on
    suppressed: list[dict]  # [{signature, reason, decided_at}] excluded by an ACTIVE rejection
    resurfaced: list[dict]  # [{signature, note, prior_reason}] a rejection that just went stale —
    # still promoted, but flagged loudly so it doesn't read as a brand-new lesson


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def normalize_signature(sig: str) -> str:
    """Fold case + whitespace so LLM phrasing drift can't split a real cluster.

    The schema `pattern` already pins the signature to a closed template, but the
    aggregation does its own normalization as a backstop: lowercase and strip ALL
    whitespace (the template has none, so an accidental stray space can't fork a
    cluster).

    A hand-edited `pending.jsonl` (or an off-shape LLM summary) can carry a non-string
    signature (e.g. a bare number); coerce it to str so `.split()` can't raise instead of
    crashing the whole aggregation run."""
    if not isinstance(sig, str):
        sig = str(sig)
    return "".join(sig.split()).lower()


def _parse_iso(ts: str) -> _dt.datetime | None:
    """Parse an ISO-8601 timestamp (tolerating a trailing 'Z'); None if unparseable.
    A naive timestamp is assumed UTC so age math never crashes on tz-mismatch.
    A non-string `recorded_at` (e.g. a hand-edited epoch number in pending.jsonl) is treated
    as unparseable rather than crashing on `.replace`."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


def _pending_expired(
    rec: LessonRecord,
    *,
    now: _dt.datetime,
    ttl_days: int,
    current_skill_sha: str | None,
    is_ancestor,
) -> str | None:
    """Return a human-readable reason if this pending entry should be discarded,
    else None. Two independent gates (either fires): TTL age, and skill-sha
    ancestry. If exactly one provenance field is present, only that gate applies;
    if NEITHER is usable the entry can never be aged out — so it is expired as
    unverifiable (an immortal fossil could otherwise confirm any future contract)."""
    recorded = _parse_iso(rec.recorded_at) if rec.recorded_at else None
    has_time = recorded is not None
    has_sha = bool(rec.skill_commit_sha)
    if not has_time and not has_sha:
        return "unverifiable provenance (no parseable recorded_at and no skill_commit_sha)"
    if has_time:
        age = now - recorded
        if age > _dt.timedelta(days=ttl_days):
            return f"older than TTL ({age.days}d > {ttl_days}d)"
    if has_sha and current_skill_sha:
        try:
            still_ancestor = is_ancestor(rec.skill_commit_sha, current_skill_sha)
        except Exception as e:
            # A TRANSIENT ancestry-check failure (git timeout / subprocess error) must NOT
            # masquerade as "not an ancestor" and destroy valid feedstock — keep the entry
            # this run. Only a clean verdict (below) expires it.
            logger.warning(
                "ancestry check for %r failed (%s); keeping the entry this run",
                rec.raw_signature, e,
            )
            still_ancestor = True
        if not still_ancestor:
            return (
                f"skill_commit_sha {rec.skill_commit_sha} is no longer an "
                f"ancestor of the current SKILL.md ({current_skill_sha})"
            )
    return None


def _record_to_pending(rec: LessonRecord) -> dict:
    return {
        "signature": rec.raw_signature,
        "session_id": rec.session_id,
        "skill_commit_sha": rec.skill_commit_sha,
        "recorded_at": rec.recorded_at,
        "lesson": rec.lesson,
    }


def _pending_to_record(row: dict) -> LessonRecord:
    raw = row.get("signature", "")
    return LessonRecord(
        signature=normalize_signature(raw),
        raw_signature=raw,
        session_id=row.get("session_id", ""),
        skill_commit_sha=row.get("skill_commit_sha"),
        recorded_at=row.get("recorded_at"),
        lesson=row.get("lesson", {}),
    )


def lessons_from_summary(
    summary: dict, *, recorded_at: str, skill_commit_sha: str | None
) -> list[LessonRecord]:
    """Extract one LessonRecord per signed steering_event in a summary. A lesson
    repeated within one session collapses later (distinct-session counting), so we
    keep them all here. Fresh lessons are stamped with the CURRENT recorded_at +
    skill sha (the summary itself carries neither)."""
    sid = summary.get("transcript_id") or ""
    out: list[LessonRecord] = []
    for ev in summary.get("steering_events", []) or []:
        # Per-event isolation: the summary is LLM-written and unvalidated, so a single off-shape
        # event (a stray string / null element, or a wrong-typed field) must not raise and abort
        # the whole aggregation — which would lose every other valid session's lessons before any
        # report prints. Mirror the no-signature loud-skip below rather than crash. (A non-string
        # signature is tolerated by `normalize_signature`'s coercion, so it is NOT dropped here.)
        if not isinstance(ev, dict):
            logger.warning(
                "steering event in session %s is not an object (%s); skipped",
                sid or "<unknown>", type(ev).__name__,
            )
            continue
        raw = ev.get("signature")
        if not raw:
            # A summary predating the signature field, or a malformed event: skip
            # it loudly rather than silently mis-clustering an unsigned lesson.
            logger.warning(
                "steering event %s in session %s has no signature; skipped",
                ev.get("id"), sid or "<unknown>",
            )
            continue
        out.append(
            LessonRecord(
                signature=normalize_signature(raw),
                raw_signature=raw,
                session_id=sid,
                skill_commit_sha=skill_commit_sha,
                recorded_at=recorded_at,
                lesson=ev,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #
def aggregate(
    fresh: list[LessonRecord],
    pending: list[dict],
    *,
    now: _dt.datetime,
    current_skill_sha: str | None,
    is_ancestor,
    recurrence_min: int = RECURRENCE_MIN,
    ttl_days: int = PENDING_TTL_DAYS,
) -> AggregationResult:
    """Cluster fresh + (non-expired) pending lessons by signature, promote the
    clusters that span >= recurrence_min distinct sessions, and compute the new
    pending feedstock (the below-floor lessons, kept for next time).

    Injected `now` / `current_skill_sha` / `is_ancestor` keep this pure + testable.
    `is_ancestor(ancestor_sha, descendant_sha) -> bool`."""
    # 1. Age out fossil pending entries (loudly). Survivors keep their ORIGINAL
    #    recorded_at + sha so the TTL keeps counting from first sighting.
    valid_pending: list[LessonRecord] = []
    expired: list[LessonRecord] = []
    for row in pending:
        rec = _pending_to_record(row)
        reason = _pending_expired(
            rec, now=now, ttl_days=ttl_days,
            current_skill_sha=current_skill_sha, is_ancestor=is_ancestor,
        )
        if reason:
            logger.info(
                "expiring pending lesson %r (session %s): %s",
                rec.raw_signature, rec.session_id, reason,
            )
            expired.append(rec)
        else:
            valid_pending.append(rec)

    # Conservation: every input pending row is either expired or survived — never dropped.
    # A raise (not assert) so the no-silent-drops guard holds even under `python -O`.
    if len(expired) + len(valid_pending) != len(pending):
        raise RuntimeError(
            f"pending conservation violated: {len(expired)} expired + "
            f"{len(valid_pending)} survived != {len(pending)} input rows"
        )

    # 2. Cluster fresh + surviving pending by normalized signature.
    clusters: dict[str, Cluster] = {}
    for rec in [*fresh, *valid_pending]:
        c = clusters.get(rec.signature)
        if c is None:
            c = clusters[rec.signature] = Cluster(rec.signature, [])
        c.records.append(rec)

    # Conservation: every fresh + surviving record lands in exactly one cluster (a refactor
    # that silently dropped a record would trip this). A raise (not assert) so it holds
    # under `python -O` too.
    clustered = sum(len(c.records) for c in clusters.values())
    if clustered != len(fresh) + len(valid_pending):
        raise RuntimeError(
            f"clustering conservation violated: {clustered} clustered != "
            f"{len(fresh)} fresh + {len(valid_pending)} surviving pending"
        )

    # 3. Promotion gate: distinct SESSIONS, not distinct lessons.
    promoted: list[Cluster] = []
    held: list[Cluster] = []
    for c in clusters.values():
        (promoted if len(c.distinct_sessions) >= recurrence_min else held).append(c)

    # 4. New pending = the below-floor records ONLY (fresh that didn't promote +
    #    pending that's still below floor). A signature that crossed the floor is not
    #    written back — pending.jsonl is just the below-floor feedstock list (this is
    #    bookkeeping for that list, NOT a re-promotion guard; staged transcripts still
    #    re-cluster every run — see the module docstring). Dedup by (session,
    #    signature), keeping the EARLIEST recorded_at so a re-run can't reset its TTL.
    dedup: dict[tuple[str, str], LessonRecord] = {}
    for c in held:
        for rec in c.records:
            key = rec.pending_key()
            prev = dedup.get(key)
            if prev is None or _earlier(rec.recorded_at, prev.recorded_at):
                dedup[key] = rec
    new_pending = [_record_to_pending(r) for r in dedup.values()]

    return AggregationResult(
        promoted=sorted(promoted, key=lambda c: -len(c.distinct_sessions)),
        held=held,
        expired=expired,
        new_pending=new_pending,
    )


def apply_decision_ledger(
    promoted: list[Cluster],
    decisions,  # list[decision_ledger.Decision]
    *,
    now: _dt.datetime,
    current_skill_sha: str | None,
    is_ancestor,
    ttl_days: int | None = None,
) -> LedgerFilterResult:
    """PR-C wiring (spec §2, Item 3): filter a PROMOTED cluster list through the decision ledger. A
    cluster whose signature carries an ACTIVE `rejected` decision is excluded (SUPPRESSED, not
    handed to the maintainer again); one whose rejection has gone stale (ancestry OR TTL) is kept
    PROMOTED but flagged RESURFACED — loud, with the prior reason — so it reads as "this came back",
    not as a fresh lesson. Lazy-imports `decision_ledger` (see that module's docstring for why: no
    load-time coupling between the two sibling modules)."""
    import decision_ledger as dl  # lazy — see module docstrings on both sides

    kwargs = {} if ttl_days is None else {"ttl_days": ttl_days}
    kept: list[Cluster] = []
    suppressed: list[dict] = []
    resurfaced: list[dict] = []
    for c in promoted:
        res = dl.is_suppressed(
            c.signature, decisions, now=now, current_skill_sha=current_skill_sha,
            is_ancestor=is_ancestor, **kwargs)
        if res.suppressed:
            suppressed.append({
                "signature": c.raw_signature,
                "reason": res.decision.reason,
                "decided_at": res.decision.decided_at,
            })
            logger.info("suppressing PROMOTED %r — rejected (%s)", c.raw_signature, res.decision.reason)
            continue
        if res.resurfaced_reason:
            resurfaced.append({
                "signature": c.raw_signature,
                "note": res.resurfaced_reason,
                "prior_reason": res.decision.reason,
            })
            logger.info("re-surfacing PROMOTED %r — %s", c.raw_signature, res.resurfaced_reason)
        kept.append(c)
    return LedgerFilterResult(promoted=kept, suppressed=suppressed, resurfaced=resurfaced)


def _earlier(a: str | None, b: str | None) -> bool:
    """True if timestamp a is strictly earlier than b (None sorts as 'unknown',
    never earlier)."""
    da, db = _parse_iso(a or ""), _parse_iso(b or "")
    if da is None:
        return False
    if db is None:
        return True
    return da < db


# --------------------------------------------------------------------------- #
# I/O + git glue (the impure edges)
# --------------------------------------------------------------------------- #
def _git_skill_sha(skill_dir: Path) -> str | None:
    """FULL HEAD sha of the skill checkout (run.py's provenance, but un-abbreviated).
    None if not a git tree / git unavailable. We use the full sha here — not run.py's
    short form — because this value is fed to `merge-base --is-ancestor`, never
    rendered: an abbreviated sha that collides on its prefix makes git exit non-zero
    ('short SHA is ambiguous'), which `_git_is_ancestor` would read as 'not an
    ancestor' and silently expire an otherwise-valid pending entry."""
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
    """Return an is_ancestor(anc, desc) checker over this checkout. A clean nonzero
    exit is a real verdict (1 = not an ancestor; 128 = unknown / gc'd / rewritten
    object) → NOT an ancestor → conservative expiry. A TRANSIENT failure (timeout /
    subprocess error / git missing) is let PROPAGATE so the caller keeps the entry
    rather than expiring valid feedstock on a hiccup."""

    def check(anc: str, desc: str) -> bool:
        r = subprocess.run(
            ["git", "-C", str(skill_dir), "merge-base", "--is-ancestor", anc, desc],
            capture_output=True, text=True, timeout=10,
        )  # TimeoutExpired / FileNotFoundError propagate → _pending_expired keeps the entry
        return r.returncode == 0

    return check


def load_summaries(loop_dir: Path) -> tuple[list[dict], list[str]]:
    """Read every transcripts/*/summary.json under the loop dir. Returns
    (summaries, problems): an unreadable/invalid summary is collected as a problem
    string (and logged) so the caller can surface it LOUDLY in the report rather than
    silently dropping a whole session's lessons (a dropped session could be the one
    that would have tipped a lesson over the recurrence floor)."""
    out: list[dict] = []
    problems: list[str] = []
    base = loop_dir / _TRANSCRIPTS
    if not base.is_dir():
        return out, problems
    for path in sorted(base.glob("*/summary.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            msg = f"unreadable summary {path.parent.name}/summary.json: {e}"
            logger.warning("skipping %s", msg)
            problems.append(msg)
            continue
        # Valid-but-non-dict JSON (top-level null / array / scalar) parses without raising but
        # would crash main()'s `summary.get(...)` and abort the whole run — losing every OTHER
        # session's lessons. Surface it as a problem (same as a decode error) instead.
        if not isinstance(data, dict):
            msg = f"non-object summary {path.parent.name}/summary.json (got {type(data).__name__})"
            logger.warning("skipping %s", msg)
            problems.append(msg)
            continue
        out.append(data)
    return out, problems


def load_pending(loop_dir: Path) -> tuple[list[dict], list[str]]:
    """Returns (parsed_rows, malformed_raw_lines). A malformed JSONL line is NOT
    discarded: its raw text is returned so the caller can PRESERVE it verbatim on
    rewrite (pending.jsonl is gitignored + unrecoverable, so a parse error must never
    shrink it) and surface the count loudly."""
    path = loop_dir / _PENDING_FILE
    if not path.is_file():
        return [], []
    rows: list[dict] = []
    malformed: list[str] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            logger.warning("preserving malformed pending line %d: %s", i, e)
            malformed.append(line)
            continue
        # A valid-but-non-dict line (e.g. a hand-edit leaving `42` / `null` / `[...]`) parses
        # cleanly but would crash `_pending_to_record`'s `row.get(...)` and abort aggregation.
        # Preserve it verbatim (don't shrink the unrecoverable file) and surface it, like a
        # decode error, rather than crashing the run.
        if not isinstance(obj, dict):
            logger.warning("preserving non-object pending line %d (got %s)", i, type(obj).__name__)
            malformed.append(line)
            continue
        rows.append(obj)
    return rows, malformed


def write_pending(loop_dir: Path, rows: list[dict], *, preserved_raw: list[str] = ()) -> None:
    """Atomically rewrite pending.jsonl (write to a temp sibling, then replace), so
    an interrupted run can't truncate or empty the feedstock — it is gitignored and
    unrecoverable if lost. `preserved_raw` (malformed lines load_pending couldn't parse)
    is appended verbatim so a parse error never destroys un-promotable feedstock."""
    path = loop_dir / _PENDING_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    for raw in preserved_raw:
        body += raw.rstrip("\n") + "\n"
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


def _format_report(
    result: AggregationResult,
    *,
    recurrence_min: int,
    input_problems: list[str] = (),
    skill_sha_available: bool = True,
    ledger: LedgerFilterResult | None = None,
) -> str:
    # PR-C: when a ledger filter ran, PROMOTED shows what SURVIVES it (what the maintainer should
    # actually act on) — not aggregate()'s raw promoted list, which a ledger-blind report would
    # wrongly re-present a rejected lesson from every run.
    promoted = ledger.promoted if ledger is not None else result.promoted
    lines: list[str] = []
    lines.append(
        f"PROMOTED — recurred across >= {recurrence_min} distinct sessions "
        f"({len(promoted)}):"
    )
    if promoted:
        for c in promoted:
            sids = ", ".join(sorted(c.distinct_sessions))
            lines.append(f"  • {c.raw_signature}  [{len(c.distinct_sessions)} sessions: {sids}]")
    else:
        lines.append("  (none — nothing has recurred yet)")

    if ledger is not None and ledger.suppressed:
        lines.append("")
        lines.append(
            f"SUPPRESSED — PROMOTED but excluded by an active REJECTED decision ({len(ledger.suppressed)}):"
        )
        for s in ledger.suppressed:
            lines.append(f"  • {s['signature']}  [rejected {s['decided_at']}: {s['reason']}]")

    if ledger is not None and ledger.resurfaced:
        lines.append("")
        lines.append(
            f"RE-SURFACED — a prior REJECTED decision went stale; PROMOTED again ({len(ledger.resurfaced)}):"
        )
        for r in ledger.resurfaced:
            lines.append(f"  • {r['signature']}  [{r['note']}; prior reason: {r['prior_reason']}]")

    lines.append("")
    lines.append(f"HELD — below the floor, recorded as pending feedstock ({len(result.held)}):")
    if result.held:
        for c in result.held:
            sids = ", ".join(sorted(c.distinct_sessions))
            lines.append(f"  • {c.raw_signature}  [{len(c.distinct_sessions)} session(s): {sids}]")
    else:
        lines.append("  (none)")

    if result.expired:
        lines.append("")
        lines.append(f"EXPIRED — aged-out pending, dropped this run ({len(result.expired)}):")
        for r in result.expired:
            lines.append(f"  • {r.raw_signature}  [session {r.session_id}]")

    if input_problems:
        lines.append("")
        lines.append(
            f"INPUT ISSUES — inputs skipped / preserved this run, NOT counted toward "
            f"recurrence ({len(input_problems)}):"
        )
        for p in input_problems:
            lines.append(f"  • {p}")

    if not skill_sha_available:
        lines.append("")
        lines.append(
            "NOTE: current skill sha unavailable (not a git checkout / git unavailable) — "
            "the ancestry expiry gate was SKIPPED this run; only the TTL gate applied."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--loop-dir", type=Path, default=Path(_LOOP_DIR),
        help="The gitignored loop dir holding transcripts/ + pending.jsonl.",
    )
    parser.add_argument("--recurrence-min", type=int, default=RECURRENCE_MIN)
    parser.add_argument("--ttl-days", type=int, default=PENDING_TTL_DAYS)
    parser.add_argument(
        "--rejection-ttl-days", type=int, default=None,
        help="PR-C: override decision_ledger.REJECTION_TTL_DAYS (default: that module's own "
             "90-day default) for how long a REJECTED lesson stays suppressed before re-surfacing.",
    )
    parser.add_argument(
        "--commit", action="store_true",
        help="Rewrite pending.jsonl with the new feedstock (drop promoted + expired). "
             "WITHOUT --commit the run only prints the report and does NOT mutate "
             "pending.jsonl, so merely observing it is non-destructive.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("STARSLING_LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )

    now = _dt.datetime.now(_dt.timezone.utc)
    skill_sha = _git_skill_sha(_DIR)
    recorded_at = now.isoformat()

    summaries, problems = load_summaries(args.loop_dir)
    fresh: list[LessonRecord] = []
    for s in summaries:
        # A summary with no transcript_id can't be attributed to a session, so it can't
        # count toward recurrence — skip it but SURFACE it (loud, in the report), never a
        # silent coverage gap.
        if not (s.get("transcript_id") or ""):
            problems.append("summary with no transcript_id (unattributable to a session) — skipped")
            logger.warning("skipping a summary with no transcript_id")
            continue
        fresh.extend(
            lessons_from_summary(s, recorded_at=recorded_at, skill_commit_sha=skill_sha)
        )
    pending, malformed = load_pending(args.loop_dir)
    if malformed:
        problems.append(
            f"{len(malformed)} malformed pending line(s) preserved verbatim — fix by hand"
        )

    result = aggregate(
        fresh, pending,
        now=now, current_skill_sha=skill_sha,
        is_ancestor=_git_is_ancestor(_DIR),
        recurrence_min=args.recurrence_min, ttl_days=args.ttl_days,
    )

    # PR-C: filter PROMOTED through the decision ledger (a maintainer's past `--decide` verdicts,
    # via decision_ledger.py's `.ci-speedup-loop/decisions.jsonl`) so a REJECTED lesson doesn't
    # re-surface as noise on every run while its transcripts stay staged.
    import decision_ledger as dl  # lazy — see decision_ledger.py's module docstring

    decisions, decision_problems = dl.load_decisions(args.loop_dir)
    if decision_problems:
        problems.extend(decision_problems)
    ledger_kwargs = {} if args.rejection_ttl_days is None else {"ttl_days": args.rejection_ttl_days}
    ledger = apply_decision_ledger(
        result.promoted, decisions,
        now=now, current_skill_sha=skill_sha, is_ancestor=_git_is_ancestor(_DIR),
        **ledger_kwargs,
    )

    print(_format_report(
        result, recurrence_min=args.recurrence_min,
        input_problems=problems, skill_sha_available=skill_sha is not None,
        ledger=ledger,
    ))

    if args.commit:
        write_pending(args.loop_dir, result.new_pending, preserved_raw=malformed)
    else:
        print("\n(no --commit — pending.jsonl left unchanged; pass --commit to persist)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
