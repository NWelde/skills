# ci-speedup first run — microsoft/playwright

A real, unedited-except-for-sanitization first-run report produced by the shipped
`ci-speedup` skill, audited against
[`microsoft/playwright`](https://github.com/microsoft/playwright) at commit
`4037273` on 2026-07-21. Nothing here is hand-authored: it is exactly what the
pipeline emitted (only local filesystem paths were stripped). Every provenance and
evidence link resolves to `microsoft/playwright` run/job/commit pages or the
`starslingdev/skills` pattern catalog.

**Result:** a typical playwright PR waits **39m 58s** for all checks to finish; the
biggest single measured win is **~2m 56s** off the slowest fixable check,
`ubuntu-22.04 (webkit - Node.js 20)` — also the check most PRs gate on (gates 14/20
sampled PRs). Because that job's matrix legs run in parallel and share one config,
speeding a single leg buys only ~2m 56s, but one shared-config fix to the `Run
./.github/actions/run-test` step drops the whole `tests_primary.yml` cluster toward the
next check in lockstep. A dense, well-tuned pipeline gets an honest ceiling and the
exact root cause, not an invented windfall. Full breakdown, per-check drill-downs, and
copy-paste agent prompts are in
[`ci-speedup-findings-report.md`](./ci-speedup-findings-report.md).

Produced by installing and running the skill:

```bash
npx skills add starslingdev/skills --skill ci-speedup
# then, in your coding agent: "audit microsoft/playwright for CI speedups"
```
