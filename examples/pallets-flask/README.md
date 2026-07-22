# ci-speedup first run — pallets/flask

A real, unedited-except-for-sanitization first-run report produced by the shipped
`ci-speedup` skill, audited against
[`pallets/flask`](https://github.com/pallets/flask) at commit `36e4a82` on
2026-07-21. Nothing here is hand-authored: it is exactly what the pipeline emitted
(only local filesystem paths were stripped). Every provenance and evidence link
resolves to `pallets/flask` run/job/commit pages or the `starslingdev/skills`
pattern catalog.

**Result:** a typical flask PR waits **34s** for all checks to finish; the biggest
single measured win is **~8s** off the slowest check, `Windows` (its
`uv run … tox run` step is the addressable lever). Full breakdown, per-check
drill-downs, and copy-paste agent prompts are in
[`ci-speedup-findings-report.md`](./ci-speedup-findings-report.md).

Produced by installing and running the skill:

```bash
npx skills add starslingdev/skills --skill ci-speedup
# then, in your coding agent: "audit pallets/flask for CI speedups"
```
