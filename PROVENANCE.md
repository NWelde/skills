# Provenance

How `ci-speedup` was built and why you can trust its numbers — stated in the
aggregate. This repo starts its public history at the initial release; the
receipts below are what that history rests on.

## Developed against real CI

`ci-speedup` was developed and dogfooded against the CI run histories of **dozens
of public open-source repositories** — a deliberately varied set spanning small
libraries to large monorepos, across multiple language ecosystems and CI shapes
(matrix fan-outs, sharded suites, path-partitioned monorepos, external/managed
merge gates). The skill's own dogfood loop repeatedly ran the real pipeline
end-to-end against these repos and audited each run for defects, which is how the
detection and measurement logic was hardened.

## The detection catalog was calibrated across 31 repos

The pattern catalog and the measurement pipeline behind it were exercised in a
**31-repo calibration run** spanning small-to-large public OSS repositories. Each
repo was taken through the real scan + `gh` data pipeline; the calibration was
the pre-publication spread check that the catalog behaves sensibly across a wide
range of CI configurations, not just the few it was first written against. The
calibration inputs and outputs are maintained privately; only these aggregate
statements are published (no third-party findings, no named repositories).

## Every report is self-checking

`ci-speedup` does not ask you to take its numbers on faith:

- **Invariant checks.** Every rendered report is validated against a suite of
  invariants (`skills/ci-speedup/tests/verify_report.py`) before it is trusted —
  the headline names the wall-clock axis, every gating pole is fully drilled to a
  named root cause, cross-references resolve, no finding dead-ends, and the report
  hands off (it never prescribes a fix). A report that fails an invariant is not
  returned.
- **Stamped provenance.** Each report records the **commit of the audited repo**
  and the **skill's own commit**, plus a **`scripts/` tree hash** that pins the
  exact detection/render code that produced it (the hash survives a squash-merge,
  where a commit sha would not). A report never records a null provenance, and an
  uncommitted (dirty) scripts tree is stamped as such.
- **Deterministic core.** Detection, ranking, the critical-path spine, and every
  measured magnitude are computed deterministically from sampled `gh` run history
  — reproducible from the findings JSON. The single non-deterministic step is a
  log-grounded gap-fill reading when a pole matches no catalog detector, and it is
  clearly labelled as such and never invents magnitudes.

## What travels with the code

The methodology ([`docs/methodology.md`](docs/methodology.md) and the in-skill
references) and a sanitized sample report ([`examples/`](examples/)) live in this
repo alongside the code that produces them, so the credibility can be checked
against the shipped implementation rather than a claim made elsewhere.

One honest caveat: the two shipped worked examples were generated shortly
*before* this repository's public root commit, so their stamped skill commit and
`scripts/` tree hash resolve in the maintainers' pre-public development archive,
not here — they are labelled "(pre-public archive)" in the reports. Every report
generated from this repository's code stamps hashes you can resolve right here;
a test (`tests/test_examples_provenance.py`) forbids any future example from
claiming the archive label.
