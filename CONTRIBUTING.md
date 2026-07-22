# Contributing

Thanks for your interest in improving `ci-speedup`. Pull requests are welcome.

## Ground rules

- **Open a PR — never push to `main`.** `main` is protected; branch protection
  requires the `test` check (the full `pytest -v` suite) to pass before a PR can
  merge.
- **The full test suite must pass.** From the repo root:

  ```bash
  python3 -m pytest -v
  ```

  CI runs the same command on every push and PR (`.github/workflows/ci.yml`).
  Tests live under `skills/ci-speedup/tests/`, `maintainers/ci-speedup/tests/`,
  and the repo-root `tests/`; the root `pyproject.toml` wires the paths so one
  `pytest -v` finds them all. A pre-commit hook (`.githooks/pre-commit`, enable
  with `git config core.hooksPath .githooks`) runs the same suite locally.

- **Keep the changelog current.** Every change that alters skill behavior adds a
  dated (UTC) bullet to
  [`skills/ci-speedup/CHANGELOG.md`](skills/ci-speedup/CHANGELOG.md) under the
  right Added / Changed / Fixed heading, **in the same PR** — if you changed the
  skill and didn't touch its changelog, the PR is incomplete. Pure-docs or
  test-only refactors that don't change behavior can be noted briefly or skipped.

- **Stage by explicit path.** When committing, `git add` only the files you
  changed — never `git add -A` / `git add .`, which sweeps in unrelated or
  generated files.

- **Don't commit local run data.** `.ci-speedup-gaps/`, `.ci-speedup-loop/`, and
  `.ci-speedup-dogfood/` are gitignored maintainer-loop capture dirs — they may
  hold third-party job logs (and, for the dogfood dir, full repo clones) and are
  never committed.

## Pull requests from forks

External contributions are welcome and follow the standard fork flow:

- **Fork, branch, and open a PR against `main`.**
- **CI runs the full test suite on your PR** on GitHub-hosted runners
  (`ci-fork.yml`), with no access to repo secrets.
- **Internal pushes and PRs run on StarSling's own runners** (`ci.yml` — we
  dogfood what we sell). By design, fork-PR code never executes on those
  self-hosted runners; the hosted workflow gives you the identical suite.
- **Local gate: green on your machine means green in CI.** The same
  `python3 -m pytest -v` runs in both places, so you can reproduce CI locally
  before you push.

## Adding or changing detection patterns

The pattern catalog is
[`skills/ci-speedup/references/optimization-patterns.md`](skills/ci-speedup/references/optimization-patterns.md);
each pattern's detector is registered in `skills/ci-speedup/scripts/`. See
[`skills/ci-speedup/ARCHITECTURE.md`](skills/ci-speedup/ARCHITECTURE.md) for how
the pipeline fits together and
[`maintainers/ci-speedup/MAINTAINERS.md`](maintainers/ci-speedup/MAINTAINERS.md)
for the maintainer runbook.

## Support

Issues are welcome and handled on a **best-effort basis — there is no SLA**. For
a security vulnerability, use private reporting instead (see
[SECURITY.md](SECURITY.md)).
