# microsoft/playwright - why is the merge slow?

| Repository | `microsoft/playwright` |
| :--- | :--- |
| **Audited commit** | [`4037273`](https://github.com/microsoft/playwright/commit/403727349cc6b484206f5984aac4eb838afee10a) - file & line references are anchored to this tree |
| **Runs analyzed** | 145 runs / 1484 jobs across 18 workflows |
| **Runs window** | 2026-06-21 → 2026-07-21 (30-day window) |
| **PR gate sample** | 20 / 20 PRs |
| **Audit** | ran 2026-07-21 · ci-speedup skill commit `3bb6e2e` (pre-public archive) |

> **Bottom line.** A typical PR waits **39m 58s** for all checks to finish. The biggest single measured win is **~2m 56s** off the slowest fixable check, `ubuntu-22.04 (webkit - Node.js 2…` - see [Long pole 1](#pole-1) for the drill-down to the biggest lever.
>
> **39m 58s until all checks finish** - the slowest check a typical PR waits on is `Windows (firefox)` (~72m 57s), but it ran on only 2/20 sampled PRs, so a typical PR finishes in 39m 58s; `ubuntu-22.04 (webkit - Node.js 20)` is the check most PRs gate on (drilled below). (`Test chrome on macos-latest` is slower (~66m 59s) but it ran on only 2/20 sampled PRs - it looks opt-in / conditional (e.g. label-gated), so a typical PR doesn't wait on it and its time is throughput/cost, not merge-wait; unless it's a *required* status check it isn't the gate here. See its long pole below.) 
>
> **`.github/workflows/publish_release.yml` changed ~6 days ago - narrowed to the current configuration.** This audit measures only the 6 runs since that change; the 14 earlier runs measured the retired configuration and were excluded so no drill-down blends the two.
>
> **`.github/workflows/tests_bidi.yml` changed ~10 days ago - narrowed to the current configuration.** This audit measures only the 8 runs since that change; the 12 earlier runs measured the retired configuration and were excluded so no drill-down blends the two.
>
> **`.github/workflows/tests_secondary.yml` changed ~18 days ago - narrowed to the current configuration.** This audit measures only the 15 runs since that change; the 5 earlier runs measured the retired configuration and were excluded so no drill-down blends the two.
>
> **Fileless status gate (disclosed, not headlined).** `copilot` shows ~23m 24s (+1 more fileless status check), but that span is PR-lifetime status-gating latency - how long a bot/label/external-app check sat open on the PR, not CI compute - so it is excluded from the merge-wait headline above (which measures what CI makes a typical PR wait). It is disclosed here so the wait is never hidden.
>
> **After the gate.** 6,756 min/mo of wall-clock-neutral runner minutes is recoverable (11 neutral findings; none can slow a merge).

## 📋 Contents

**🐌 Critical path** - the checks that gate your merge, each linking to its long-pole drill-down (waterfall → biggest lever → agent prompt):

1. 🔴 [ubuntu-22.04 (webkit - Node.js 2…](#pole-1) - 40m 02s · `tests_primary.yml` gates 14/20 PRs
2. 🔴 [Windows (firefox)](#pole-2) - 72m 57s · `tests_secondary.yml` gates 2/20 PRs
3. 🔴 [windows-latest - firefox](#pole-3) - 37m 06s · `tests_mcp.yml` gates 3/20 PRs
4. 🔴 [Test chrome on macos-latest](#pole-4) - 66m 59s · rarely the merge pole

**💸 Runner-minute reductions** - ~6,756 min/mo of measured, merge-safe runner-minute savings, backed by a 160-row cost spine: [section](#runner-minute-reductions).

1. 🟢 [Repeated Workflow Attempts From Same…](#r-1) - 2,257 min/mo
2. 🟢 [Repeated Workflow Attempts From Same…](#r-2) - 2,166 min/mo
3. 🟢 [Superseded Runs Not Cancelled](#r-3) - 1,519 min/mo
4. 🟢 [Repeated Workflow Attempts From Same…](#r-4) - 367 min/mo
5. 🟢 [Superseded Runs Not Cancelled](#r-5) - 139 min/mo
6. 🟢 [Repeated Workflow Attempts From Same…](#r-6) - 112 min/mo
7. 🟢 [Superseded Runs Not Cancelled](#r-7) - 101 min/mo
8. 🟢 [Repeated Workflow Attempts From Same…](#r-8) - 74 min/mo
9. 🟢 [Cron Schedule Too Frequent](#r-9) - 12 min/mo
10. 🟢 [Repeated Workflow Attempts From Same…](#r-10) - 8 min/mo
11. 🟢 [Repeated Workflow Attempts From Same…](#r-11) - 0.7 min/mo

**🧹 Also noticed** - 16 findings (mostly off-path runner-minute savings; **one or more flagged DO sit on the critical path** and cut wall-clock): [see below](#also-noticed).

<a id="long-pole-map"></a>

## 🗺️ Long pole map

A **workflow** is one YAML file under `.github/workflows/`; a run of it executes its **jobs** in parallel (each on its own runner); each job runs its **steps** in sequence.

```text
Level 1 - checks racing on a typical PR; the merge waits for the slowest - rows marked † ran on a minority of sampled PRs (path-conditional - they gate only the PRs that trigger them):

   Windows (firefox) · tests_seco… †  ██████████████████████  72m 57s
   ubuntu-22.04 (webkit - Node.js 2…  ████████████            40m 02s       ◀┐
   windows-latest - firefox · tests…  ███████████             37m 06s        │
   ┌─────────────────────────────────────────────────────────────────────────┘

   ▼ Level 2 - inside ubuntu-22.04 (webkit - Node.js 20), steps run one after another:

   Run ./.github/actions/run-test     ██████████████████████  39m 55s  100% ◀
   Run actions/checkout@v6            █                            2s    0%
   Set up job                         █                            1s    0%
   Post Run actions/checkout@v6       █                            1s    0%
   Post Run ./.github/actions/run-t…  █                            1s    0%
```

Each ◀ marks the blocker the next level opens. Long pole 1 below drills the marked step to its root cause and hand-off prompt.

† `Windows (firefox)` ran on 2/20 sampled PRs.

> Also slower on **some** of the sampled PRs (not the typical path, not in the Contents critical path): opt-in / conditional workflow check(s) that ran on a minority of sampled PRs (label-gated or path-filtered - a typical PR doesn't wait on them): `Test chrome on macos-latest` (~66m 59s), `Test chrome on windows-latest` (~51m 41s), `Test msedge-dev on windows-latest` (~44m 39s). Unless one is a *required* status check it does not gate the merge - treat it as throughput/cost (an opt-in job) or make an external check non-blocking, rather than the long pole.

<a id="pole-1"></a>

## 🔴 Long pole 1: `tests_primary.yml` ▸ `ubuntu-22.04 (webkit - Node.js 20)` - 40m 02s

**The check most PRs gate on.** A typical PR waits on this most often; the slowest concurrent check is `Windows (firefox)` (~72m 57s).

> **What a change here can buy (wall-clock):** this job's matrix legs run in parallel, so speeding **this one leg** saves only ~2m 56s (the next leg, `windows-latest - firefox`, is 37m 06s). Because the legs share one job config, a change that speeds *every* leg at once drops the whole matrix toward the next check, `windows-latest - firefox` (37m 06s), for up to **~2m 56s** of merge wait.

```text
Level 2 - inside that one job, its steps run **one after another** (← 0:00 job start … 39:59 → ; `░` = time already elapsed, `█` = the step running) and sum to the job's **39m 59s** wall time on this run - the run closest to the typical (P50) time. Because they're sequential, time cut from any step comes straight off the job's wall-clock (and off the merge wait, down to the next concurrent check):

   Run ./.github/actions/run-test     ██████████████████████  39m 49s  100%
   (+5 setup/cleanup steps of 36s or less not shown)

   (no log-level detector fired, but a **structural catalog pattern** matched this pole - see the **structural root-cause** below; the dominant step is the addressable lever.)
```

_The timeline and the per-step times above are from **one representative run** - the one whose duration is closest to the typical (P50) time, [run 29794613208](https://github.com/microsoft/playwright/actions/runs/29794613208). The dominant step's wall time is validated across runs in the cross-run check below._

**🔗 Audit:** run [29794613208](https://github.com/microsoft/playwright/actions/runs/29794613208) → [the `ubuntu-22.04 (webkit - Node.js 2…` job](https://github.com/microsoft/playwright/actions/runs/29794613208/job/88523305546) → [the `Run ./.github/actions/run-test` step](https://github.com/microsoft/playwright/actions/runs/29794613208/job/88523305546#step:3:1) - open the step to inspect its log directly (no known root-cause pattern matched, so there is no specific callout to search for).

**🔬 Cross-run check** - the `Run ./.github/actions/run-test` step (wall): **39m 49s** in the drilled run, 3 runs sampled, range 38m 01s-41m 23s (a tight spread, so the number is stable across runs). This is the dominant step's own wall time, measured per run:

- [run 29794613208](https://github.com/microsoft/playwright/actions/runs/29794613208) - 39m 49s - drilled above
- [run 29819836716](https://github.com/microsoft/playwright/actions/runs/29819836716) - 38m 01s
- [run 29832513909](https://github.com/microsoft/playwright/actions/runs/29832513909) - 41m 23s

**📐 Structural root-cause - OPT75 · The long pole's time is one addressable step - speed it up or move it off the PR path - `ubuntu-22.04 (webkit - Node.js 20)`** - risk **MEDIUM**

A measured **structural** lever on the critical path (it IS this pole, so it's not repeated in the off-path appendix). It carries a risk profile - review the guardrail and rollout before shipping:

- **What ci-speedup measured:** critical-path check `ubuntu-22.04 (webkit - Node.js 20)` (2402s): dominant step `Run ./.github/actions/run-test` (test, 100% of job `ubuntu-22.04 (webkit - Node.js 20)`)
- **Guardrail:** carry the guardrail of the routed lever (e.g. OPT70's full-suite fallback if the dominant step is a test being scoped); never present the decomposition as free
- **Rollout:** the routed lever's rollout; re-measure the pole's p50 after the dominant step is attacked - the next-largest step becomes the target
- **Failure mode:** the dominant-step remedy ranges from LOW (cache an install) to HIGH (scope a test/build, inheriting OPT70) - the candidate carries the risk of whichever specific lever its dominant category routes to
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt75--long-pole-optimize-or-relocate-the-dominant-step

#### 🤖 Prompt for your coding agent

```text
starslingdev/ci-speedup measured where the time goes below but does NOT prescribe the fix - a structural catalog pattern (OPT75) matched this pole (see the **structural root-cause** section above for the measured lever + its risk axis); the dominant step below is where that lever's time is spent.

REPO: microsoft/playwright (audited at commit 4037273)

THE GATE
- Workflow `tests_primary.yml`, job `ubuntu-22.04 (webkit - Node.js 20)`.
- Slowest check a typical PR waits on: P50 40m 02s; its workflow `tests_primary.yml` gates 14/20 sampled PRs.

WHERE THE TIME GOES (representative run 29794613208)
- The job's time is dominated by the `Run ./.github/actions/run-test` step: ~39m 49s (100% of the job wall, validated across runs in the cross-run check above).

STRUCTURAL CATALOG PATTERN MATCHED
- A structural catalog pattern (OPT75) matched this pole - see the **structural root-cause** section above for the measured lever, its risk / guardrail / rollout, and the catalog fix recipe. The step above is the load-bearing one that lever targets; open its log (the Audit link) to see exactly what inside it the lever reshapes.

WHAT'S ADDRESSABLE (wall-clock ceiling - don't over-promise)
- this job's matrix legs run in parallel, so speeding this one leg saves only ~2m 56s (the next leg, `windows-latest - firefox`, is 37m 06s). Because the legs share one job config, a change that speeds *every* leg at once drops the whole matrix toward the next check, `windows-latest - firefox` (37m 06s), for up to ~2m 56s of merge wait.

WHERE TO LOOK
- The `tests_primary.yml` workflow definition for the `Run ./.github/actions/run-test` step, and the tool/config it invokes (build tool, test runner, or install) - that's where its time is spent.

DELIVER & VERIFY
- A change that cuts the `Run ./.github/actions/run-test` step's wall time without dropping coverage; re-measure the step on a PR run to confirm the reduction.
```


<a id="pole-2"></a>

## 🔴 Long pole 2: `tests_secondary.yml` ▸ `Windows (firefox)` - 72m 57s

_Runs concurrently - becomes the gate once the slower checks above it drop below 72m 57s._

> **What a change here can buy (wall-clock):** this job's matrix legs run in parallel, so speeding **this one leg** saves only ~5m 58s (the next leg, `Test chrome on macos-latest`, is 66m 59s). Because the legs share one job config, a change that speeds *every* leg at once drops the whole matrix toward the next check, `Test chrome on macos-latest` (66m 59s), for up to **~5m 58s** of merge wait.

```text
Level 2 - inside that one job, its steps run **one after another** (← 0:00 job start … 72:57 → ; `░` = time already elapsed, `█` = the step running) and sum to the job's **72m 57s** wall time on this run - the run closest to the typical (P50) time. Because they're sequential, time cut from any step comes straight off the job's wall-clock (and off the merge wait, down to the next concurrent check):

   Run ./.github/actions/run-test     ██████████████████████  72m 46s  100%
   (+5 setup/cleanup steps of 1m 06s or less not shown)

   (no log-level detector fired, but a **structural catalog pattern** matched this pole - see the **structural root-cause** below; the dominant step is the addressable lever.)
```

_The timeline and the per-step times above are from **one representative run** - the one whose duration is closest to the typical (P50) time, [run 29780743634](https://github.com/microsoft/playwright/actions/runs/29780743634)._

**🔗 Audit:** run [29780743634](https://github.com/microsoft/playwright/actions/runs/29780743634) → [the `Windows (firefox)` job](https://github.com/microsoft/playwright/actions/runs/29780743634/job/88481132703) → [the `Run ./.github/actions/run-test` step](https://github.com/microsoft/playwright/actions/runs/29780743634/job/88481132703#step:3:1) - open the step to inspect its log directly (no known root-cause pattern matched, so there is no specific callout to search for).

**📐 Structural root-cause - OPT75 · The long pole's time is one addressable step - speed it up or move it off the PR path - `Windows (firefox)`** - risk **MEDIUM**

A measured **structural** lever on the critical path (it IS this pole, so it's not repeated in the off-path appendix). It carries a risk profile - review the guardrail and rollout before shipping:

- **What ci-speedup measured:** critical-path check `Windows (firefox)` (4377s): dominant step `Run ./.github/actions/run-test` (test, 100% of job `Windows (firefox)`)
- **Guardrail:** carry the guardrail of the routed lever (e.g. OPT70's full-suite fallback if the dominant step is a test being scoped); never present the decomposition as free
- **Rollout:** the routed lever's rollout; re-measure the pole's p50 after the dominant step is attacked - the next-largest step becomes the target
- **Failure mode:** the dominant-step remedy ranges from LOW (cache an install) to HIGH (scope a test/build, inheriting OPT70) - the candidate carries the risk of whichever specific lever its dominant category routes to
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt75--long-pole-optimize-or-relocate-the-dominant-step

#### 🤖 Prompt for your coding agent

```text
starslingdev/ci-speedup measured where the time goes below but does NOT prescribe the fix - a structural catalog pattern (OPT75) matched this pole (see the **structural root-cause** section above for the measured lever + its risk axis); the dominant step below is where that lever's time is spent.

REPO: microsoft/playwright (audited at commit 4037273)

THE GATE
- Workflow `tests_secondary.yml`, job `Windows (firefox)`.
- Slowest check a typical PR waits on: P50 72m 57s; its workflow `tests_secondary.yml` gates 2/20 sampled PRs.

WHERE THE TIME GOES (representative run 29780743634)
- The job's time is dominated by the `Run ./.github/actions/run-test` step: ~72m 46s (100% of the job wall, measured in the drilled run).

STRUCTURAL CATALOG PATTERN MATCHED
- A structural catalog pattern (OPT75) matched this pole - see the **structural root-cause** section above for the measured lever, its risk / guardrail / rollout, and the catalog fix recipe. The step above is the load-bearing one that lever targets; open its log (the Audit link) to see exactly what inside it the lever reshapes.

WHAT'S ADDRESSABLE (wall-clock ceiling - don't over-promise)
- this job's matrix legs run in parallel, so speeding this one leg saves only ~5m 58s (the next leg, `Test chrome on macos-latest`, is 66m 59s). Because the legs share one job config, a change that speeds *every* leg at once drops the whole matrix toward the next check, `Test chrome on macos-latest` (66m 59s), for up to ~5m 58s of merge wait.

WHERE TO LOOK
- The `tests_secondary.yml` workflow definition for the `Run ./.github/actions/run-test` step, and the tool/config it invokes (build tool, test runner, or install) - that's where its time is spent.

DELIVER & VERIFY
- A change that cuts the `Run ./.github/actions/run-test` step's wall time without dropping coverage; re-measure the step on a PR run to confirm the reduction.
```


<a id="pole-3"></a>

## 🔴 Long pole 3: `tests_mcp.yml` ▸ `windows-latest - firefox` - 37m 06s

_Runs concurrently behind `Windows (firefox)` (72m 57s); it becomes the gate only once every slower concurrent check drops below 37m 06s._

> **What a change here can buy (wall-clock):** this job's matrix legs run in parallel, so speeding **this one leg** saves only ~9m 16s (the next leg, `macos-latest - firefox`, is 27m 50s). Because the legs share one job config, a change that speeds *every* leg at once drops the whole matrix toward the next check, `macos-latest - chrome` (19m 12s), for up to **~17m 54s** of merge wait.

```text
Where the job's ~37m 06s goes - every step, slowest first; they run in sequence and roughly add up to the job:

   Run ./.github/actions/run-test     ██████████████████████  36m 48s       ◀
   Run actions/checkout@v6            █                            8s
   Post Run actions/checkout@v6       █                            2s
   Post Run ./.github/actions/run-t…  █                            1s
   Set up job                         █                            1s
   Complete job                       █                            1s

(no log-level detector fired, but a **structural catalog pattern** matched this pole - see the **structural root-cause** below; the dominant step is the addressable lever.)
```

**📐 Structural root-cause - OPT75 · The long pole's time is one addressable step - speed it up or move it off the PR path - `windows-latest - firefox`** - risk **MEDIUM**

A measured **structural** lever on the critical path (it IS this pole, so it's not repeated in the off-path appendix). It carries a risk profile - review the guardrail and rollout before shipping:

- **What ci-speedup measured:** critical-path check `windows-latest - firefox` (2226s): dominant step `Run ./.github/actions/run-test` (test, 99% of job `windows-latest - firefox`)
- **Guardrail:** carry the guardrail of the routed lever (e.g. OPT70's full-suite fallback if the dominant step is a test being scoped); never present the decomposition as free
- **Rollout:** the routed lever's rollout; re-measure the pole's p50 after the dominant step is attacked - the next-largest step becomes the target
- **Failure mode:** the dominant-step remedy ranges from LOW (cache an install) to HIGH (scope a test/build, inheriting OPT70) - the candidate carries the risk of whichever specific lever its dominant category routes to
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt75--long-pole-optimize-or-relocate-the-dominant-step

#### 🤖 Prompt for your coding agent

```text
starslingdev/ci-speedup measured where the time goes below but does NOT prescribe the fix - a structural catalog pattern (OPT75) matched this pole (see the **structural root-cause** section above for the measured lever + its risk axis); the dominant step below is where that lever's time is spent.

REPO: microsoft/playwright (audited at commit 4037273)

THE GATE
- Workflow `tests_mcp.yml`, job `windows-latest - firefox`.
- Slowest check a typical PR waits on: P50 37m 06s; its workflow `tests_mcp.yml` gates 3/20 sampled PRs.

WHERE THE TIME GOES
- The job's time is dominated by the `Run ./.github/actions/run-test` step: ~36m 48s (99% of the job wall), from the sampled per-step decomposition (no single-run timeline was captured for this job).

STRUCTURAL CATALOG PATTERN MATCHED
- A structural catalog pattern (OPT75) matched this pole - see the **structural root-cause** section above for the measured lever, its risk / guardrail / rollout, and the catalog fix recipe. The step above is the load-bearing one that lever targets; open its log (the Audit link) to see exactly what inside it the lever reshapes.

WHAT'S ADDRESSABLE (wall-clock ceiling - don't over-promise)
- this job's matrix legs run in parallel, so speeding this one leg saves only ~9m 16s (the next leg, `macos-latest - firefox`, is 27m 50s). Because the legs share one job config, a change that speeds *every* leg at once drops the whole matrix toward the next check, `macos-latest - chrome` (19m 12s), for up to ~17m 54s of merge wait.

WHERE TO LOOK
- The `tests_mcp.yml` workflow definition for the dominant step, and the tool/config it invokes (build tool, test runner, or install) - that's where its time is spent.

DELIVER & VERIFY
- A change that cuts the dominant step's wall time without dropping coverage; re-measure the step on a PR run to confirm the reduction.
```


<a id="pole-4"></a>

## 🔴 Long pole 4: `tests_secondary.yml` ▸ `Test chrome on macos-latest` - 66m 59s

**Rarely the merge gate - the actual slowest check a PR waits on, on only 0/20 sampled PRs.** Present on 2/20 PRs, but a slower concurrent check almost always gates ahead of it, so its 66m 59s is throughput/cost, not merge-wait. Speeding it helps only the PRs where it IS the pole - it won't move typical merge-wait.

> **What a change here can buy (wall-clock):** this job's matrix legs run in parallel, so speeding **this one leg** saves only ~26m 58s (the next leg, `ubuntu-22.04 (webkit - Node.js 20)`, is 40m 02s). Because the legs share one job config, a change that speeds *every* leg at once drops the whole matrix toward the next check, `ubuntu-22.04 (webkit - Node.js 20)` (40m 02s), for up to **~26m 58s** of merge wait.

```text
Where the job's ~66m 59s goes - every step, slowest first; they run in sequence and roughly add up to the job:

   Run ./.github/actions/run-test     ██████████████████████  66m 44s       ◀
   Run actions/checkout@v6            █                            5s
   Complete job                       █                            4s
   Set up job                         █                            2s
   Post Run ./.github/actions/run-t…  █                            1s

(no log-level detector fired, but a **structural catalog pattern** matched this pole - see the **structural root-cause** below; the dominant step is the addressable lever.)
```

**📐 Structural root-cause - OPT75 · The long pole's time is one addressable step - speed it up or move it off the PR path - `Test chrome on macos-latest`** - risk **MEDIUM**

A measured **structural** lever on the critical path (it IS this pole, so it's not repeated in the off-path appendix). It carries a risk profile - review the guardrail and rollout before shipping:

- **What ci-speedup measured:** critical-path check `Test chrome on macos-latest` (4019s): dominant step `Run ./.github/actions/run-test` (test, 100% of job `Test chrome on macos-latest`)
- **Guardrail:** carry the guardrail of the routed lever (e.g. OPT70's full-suite fallback if the dominant step is a test being scoped); never present the decomposition as free
- **Rollout:** the routed lever's rollout; re-measure the pole's p50 after the dominant step is attacked - the next-largest step becomes the target
- **Failure mode:** the dominant-step remedy ranges from LOW (cache an install) to HIGH (scope a test/build, inheriting OPT70) - the candidate carries the risk of whichever specific lever its dominant category routes to
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt75--long-pole-optimize-or-relocate-the-dominant-step

**Sibling legs carry the same lever on the same step** - `Test chrome on windows-latest` 3101s · 99%; one fix reshapes all legs (each leg's own p50 · share shown; the guardrail, rollout, and failure mode above apply unchanged).

#### 🤖 Prompt for your coding agent

```text
starslingdev/ci-speedup measured where the time goes below but does NOT prescribe the fix - a structural catalog pattern (OPT75) matched this pole (see the **structural root-cause** section above for the measured lever + its risk axis); the dominant step below is where that lever's time is spent.

REPO: microsoft/playwright (audited at commit 4037273)

THE GATE
- Workflow `tests_secondary.yml`, job `Test chrome on macos-latest`.
- Rarely the merge pole - the actual slowest check a PR waits on, on only 0/20 sampled PRs (present on 2/20): P50 66m 59s. A slower concurrent check usually gates ahead, so speeding it helps only the PRs where it IS the pole, not typical merge-wait.

WHERE THE TIME GOES
- The job's time is dominated by the `Run ./.github/actions/run-test` step: ~66m 44s (100% of the job wall), from the sampled per-step decomposition (no single-run timeline was captured for this job).

STRUCTURAL CATALOG PATTERN MATCHED
- A structural catalog pattern (OPT75) matched this pole - see the **structural root-cause** section above for the measured lever, its risk / guardrail / rollout, and the catalog fix recipe. The step above is the load-bearing one that lever targets; open its log (the Audit link) to see exactly what inside it the lever reshapes.

WHAT'S ADDRESSABLE (wall-clock ceiling - don't over-promise)
- this job's matrix legs run in parallel, so speeding this one leg saves only ~26m 58s (the next leg, `ubuntu-22.04 (webkit - Node.js 20)`, is 40m 02s). Because the legs share one job config, a change that speeds *every* leg at once drops the whole matrix toward the next check, `ubuntu-22.04 (webkit - Node.js 20)` (40m 02s), for up to ~26m 58s of merge wait.

WHERE TO LOOK
- The `tests_secondary.yml` workflow definition for the dominant step, and the tool/config it invokes (build tool, test runner, or install) - that's where its time is spent.

DELIVER & VERIFY
- A change that cuts the dominant step's wall time without dropping coverage; re-measure the step on a PR run to confirm the reduction.
```


---

<a id="runner-minute-reductions"></a>

## Runner-minute reductions (wall-clock-neutral)

<!-- ci-speedup:runner-minute-spine -->
### Cost spine: where runner minutes go

All figures are runner-minutes; multiply by your runner's per-minute rate to get dollars.

| Workflow | Job | Runner | Event | Status | Attempt | Volume | Raw min/mo | Billable min/mo | Share |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: |
| .github/workflows/tests_primary.yml | ubuntu-22.04 (webkit - Node.js 20) | ubuntu-22.04 | all-events | success | latest | all-status | 29840.000 | 30225.000 | 3.100% |
| .github/workflows/tests_mcp.yml | windows-latest - firefox | windows-latest | all-events | success | latest | all-status | 27816.557 | 28203.039 | 2.900% |
| .github/workflows/tests_primary.yml | ubuntu-22.04 (firefox - Node.js 20) | ubuntu-22.04 | all-events | success | latest | all-status | 25570.000 | 25912.500 | 2.700% |
| .github/workflows/tests_secondary.yml | Windows (firefox) | windows-latest | all-events | success | latest | all-status | 24990.780 | 25116.000 | 2.600% |
| .github/workflows/tests_primary.yml | Test Runner (macos-latest, 22, 2, 2, 58:42) | macos-latest | all-events | success | latest | all-status | 24168.125 | 24562.500 | 2.500% |
| .github/workflows/tests_mcp.yml | macos-latest - firefox | macos-latest | all-events | success | latest | all-status | 21691.426 | 22001.658 | 2.300% |
| .github/workflows/tests_primary.yml | Installation Test windows-latest | windows-latest | all-events | success | latest | all-status | 21082.500 | 21337.500 | 2.200% |
| .github/workflows/tests_primary.yml | Test Runner (macos-latest, 22, 1, 2, 58:42) | macos-latest | all-events | success | latest | all-status | 20460.000 | 20812.500 | 2.200% |
| .github/workflows/tests_mcp.yml | windows-latest - msedge | windows-latest | all-events | success | latest | all-status | 20192.403 | 20579.461 | 2.100% |
| .github/workflows/tests_mcp.yml | windows-latest - chrome | windows-latest | all-events | success | latest | all-status | 18825.705 | 19197.039 | 2.000% |
| .github/workflows/tests_secondary.yml | Test chrome on macos-latest | macos-latest | all-events | success | latest | all-status | 18873.134 | 19019.574 | 2.000% |
| .github/workflows/tests_mcp.yml | windows-latest - chromium | windows-latest | all-events | success | latest | all-status | 18606.471 | 18920.855 | 2.000% |
| Total |  |  |  |  |  |  | 941867.537 | 965063.392 | 100.000% |
+148 more runner-minute rows hidden

> These findings cut wall-clock-neutral runner spend without touching your merge gate; each R-numbered finding carries a machine-derived proof it cannot slow a PR.
> **6,756 min/mo credited after de-overlap** (naive sum 6,756 min/mo; 11 neutral findings; not promoted: 3 measured item(s) (3 without source rows) · 8 modeled item(s) · 6 structural shared-step item(s); see Also noticed). All figures are runner-minutes; multiply by your runner's per-minute rate to get dollars.

<!-- ci-speedup:tier2-finding id=f53 pattern=OPT64 -->
<a id="r-1"></a>

## 🟢 Runner saving 1: `tests_mcp.yml` - 2,257 min/mo

**The largest merge-safe runner-minute saving measured on this repo.**

| Run | Latest attempt | Dominant failing job | Prior attempts | Prior attempt compute min | Dominant failure min |
| --- | --- | --- | --- | --- | --- |
| `29661317313` | 3 | `macos-latest - chrome` | 1 | 285.7 | 19.3 |

_Measured from GitHub jobs API `filter=all` minus `filter=latest` for workflow runs whose run_attempt > 1. The finding is emitted only when each credited prior attempt has the same unique dominant failed/timed-out job and that dominant failing job appears in the latest attempt; ambiguous ties, mixed-cause attempts, and retry-only volume are withheld._

**💸 Bill root-cause - OPT64 · Repeated Workflow Attempts From Same Failing Job** - risk **LOW**

- **What ci-speedup measured:** 1 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `macos-latest - chrome` (1 failed/timed-out prior-attempt job(s), 19.3 failed min) and it appeared again in the latest attempt. ~2257 runner-min/mo of prior-attempt compute (790/30d ÷ 100 sampled all-status run(s)).
- **Why this can't slow your merge:** machine-derived proof: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `macos-latest - chrome` identifies the retry cause, so prior-attempt compute is post-completion waste).
- **Source block:** `runner_minute_spine` matched 14 prior-attempt rows for `.github/workflows/tests_mcp.yml`; current measured cost spine for those rows is 7173.727 raw min/mo, 7307.508 billable min/mo.
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT64 - Repeated Workflow Attempts From Same Failing Job.
Where: tests_mcp.yml.
What ci-speedup saw: 1 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `macos-latest - chrome` (1 failed/timed-out prior-attempt job(s), 19.3 failed min) and it appeared again in the latest attempt. ~2257 runner-min/mo of prior-attempt compute (790/30d ÷ 100 sampled all-status run(s)).
Saving: 2,257 min/mo of runner capacity - a bill/capacity reduction, not a merge-wait cut. Neutrality certificate: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `macos-latest - chrome` identifies the retry cause, so prior-attempt compute is post-completion waste).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

<!-- ci-speedup:tier2-finding id=f54 pattern=OPT64 -->
<a id="r-2"></a>

## 🟢 Runner saving 2: `tests_mcp.yml` - 2,166 min/mo

**The #2 merge-safe runner-minute saving measured on this repo, by size.**

| Run | Latest attempt | Dominant failing job | Prior attempts | Prior attempt compute min | Dominant failure min |
| --- | --- | --- | --- | --- | --- |
| `29544632336` | 2 | `macos-latest - firefox` | 1 | 274.2 | 26.2 |

_Measured from GitHub jobs API `filter=all` minus `filter=latest` for workflow runs whose run_attempt > 1. The finding is emitted only when each credited prior attempt has the same unique dominant failed/timed-out job and that dominant failing job appears in the latest attempt; ambiguous ties, mixed-cause attempts, and retry-only volume are withheld._

**💸 Bill root-cause - OPT64 · Repeated Workflow Attempts From Same Failing Job** - risk **LOW**

- **What ci-speedup measured:** 1 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `macos-latest - firefox` (1 failed/timed-out prior-attempt job(s), 26.2 failed min) and it appeared again in the latest attempt. ~2166 runner-min/mo of prior-attempt compute (790/30d ÷ 100 sampled all-status run(s)).
- **Why this can't slow your merge:** machine-derived proof: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `macos-latest - firefox` identifies the retry cause, so prior-attempt compute is post-completion waste).
- **Source block:** `runner_minute_spine` matched 14 prior-attempt rows for `.github/workflows/tests_mcp.yml`; current measured cost spine for those rows is 7173.727 raw min/mo, 7307.508 billable min/mo.
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT64 - Repeated Workflow Attempts From Same Failing Job.
Where: tests_mcp.yml.
What ci-speedup saw: 1 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `macos-latest - firefox` (1 failed/timed-out prior-attempt job(s), 26.2 failed min) and it appeared again in the latest attempt. ~2166 runner-min/mo of prior-attempt compute (790/30d ÷ 100 sampled all-status run(s)).
Saving: 2,166 min/mo of runner capacity - a bill/capacity reduction, not a merge-wait cut. Neutrality certificate: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `macos-latest - firefox` identifies the retry cause, so prior-attempt compute is post-completion waste).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

<!-- ci-speedup:tier2-finding id=f43 pattern=OPT46 -->
<a id="r-3"></a>

## 🟢 Runner saving 3: `tests_components.yml` - 1,519 min/mo

**The #3 merge-safe runner-minute saving measured on this repo, by size.**

| Workflow | Overlapping (raced) runs | Mean compute/run (timed basis) | Reclaimable remainder (mean per run) | Reclaimable runner-min/mo (range) |
| --- | --- | --- | --- | --- |
| `.github/workflows/tests_components.yml` | 10 confirmed (naive 54) | 28.7 job-min over 4 timed run(s) | 71% of run (Σremainder/Σduration 70%) | ~1519-11608 (lower=remainder, upper=naive runs-1) |

_Superseded = a run a NEWER run started before it finished - measured by timestamp overlap, so sequential (non-racing) commits are NOT charged. Cancellation cause is unknowable from the API, so the attribution is INFERENCE. REMAINDER BASIS: cancel-in-progress cancels a superseded run the moment its successor starts, so only the compute AFTER that moment is reclaimable - the credited (lower) figure prices the MEAN per-run compute pro-rated by each superseded run's wall-clock remainder fraction (mean 71%; Σremainder/Σduration 70%), NOT the whole run; exact per-second compute is unknowable because a run's jobs run in parallel, so the pro-rata of the mean is the honest estimate. The whole-run figure is now only the loose UPPER bound (naive runs-1). Basis: the superseded COUNT and the remainder ratio are from the all-status slice (100 runs, from each run's own timestamps); the per-run PRICE is the mean of 4 PR-success timed runs (superseded runs' own jobs aren't fetched) - different populations. GUARDRAIL: verify this is NOT a deploy/release/publish workflow (a mid-flight run may be uploading artifacts / pushing a tag) before enabling cancellation - and take the predicate from the catalog recipe, which scopes cancellation with an expression; never a bare `cancel-in-progress: true`, which also kills in-flight runs on the default branch and on release tags. ROUTING: this workflow triggers on `pull_request`/`push` - with a `pull_request` trigger use the catalog's DEFAULT (PR-scoped) predicate; without one, the PR-scoped predicate is never true and saves nothing, so use the catalog's WIDENED predicate._

**💸 Bill root-cause - OPT46 · Superseded Runs Not Cancelled (Missing Concurrency or `cancel-in-progress: false`)** - risk **MEDIUM**

- **What ci-speedup measured:** 10 run(s) across 4 branch(es) were superseded (a newer run started before they finished) in the sampled window; ~1519-11608 runner-min/mo of cancellable-remainder compute - the lower figure credits only the 71% mean remainder each superseded run would have burned AFTER its successor started, not the whole run (mean over 4 timed run(s); ×7.50 to the 30d volume (750 runs); 100-run recent slice (not a full 30d census)). Superseded attribution is INFERENCE - the API marks no run 'cancelled-by-concurrency'. (sensitivity range: 1,519 min/mo to 11,608 min/mo)
- **Why this can't slow your merge:** machine-derived proof: `post_completion_waste` - compute burned after the run signal is already decided (superseded runs: same head_branch, a newer run started before this one finished (timestamp overlap); cancellation cause is inference).
- **Source block:** `runner_minute_spine` matched 5 rows for `.github/workflows/tests_components.yml`; current measured cost spine for those rows is 20756.250 raw min/mo, 22462.500 billable min/mo.
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt46--superseded-runs-not-cancelled-missing-concurrency-or-cancel-in-progress-false

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT46 - Superseded Runs Not Cancelled (Missing Concurrency or `cancel-in-progress: false`).
Where: tests_components.yml.
What ci-speedup saw: 10 run(s) across 4 branch(es) were superseded (a newer run started before they finished) in the sampled window; ~1519-11608 runner-min/mo of cancellable-remainder compute - the lower figure credits only the 71% mean remainder each superseded run would have burned AFTER its successor started, not the whole run (mean over 4 timed run(s); ×7.50 to the 30d volume (750 runs); 100-run recent slice (not a full 30d census)). Superseded attribution is INFERENCE - the API marks no run 'cancelled-by-concurrency'.
Saving: 1,519 min/mo of runner capacity - a bill/capacity reduction, not a merge-wait cut. Neutrality certificate: `post_completion_waste` - compute burned after the run signal is already decided (superseded runs: same head_branch, a newer run started before this one finished (timestamp overlap); cancellation cause is inference). GUARDRAIL: verify this is NOT a deploy/release/publish workflow (a mid-flight run may be uploading artifacts / pushing a tag) before enabling cancellation - and take the predicate from the catalog recipe, which scopes cancellation with an expression; never a bare `cancel-in-progress: true`, which also kills in-flight runs on the default branch and on release tags. ROUTING: this workflow triggers on `pull_request`/`push` - with a `pull_request` trigger use the catalog's DEFAULT (PR-scoped) predicate; without one, the PR-scoped predicate is never true and saves nothing, so use the catalog's WIDENED predicate.

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt46--superseded-runs-not-cancelled-missing-concurrency-or-cancel-in-progress-false

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

<!-- ci-speedup:tier2-finding id=f69 pattern=OPT64 -->
<a id="r-4"></a>

## 🟢 Runner saving 4: `tests_webview_simulator.yml` - 367 min/mo

**The #4 merge-safe runner-minute saving measured on this repo, by size.**

| Run | Latest attempt | Dominant failing job | Prior attempts | Prior attempt compute min | Dominant failure min |
| --- | --- | --- | --- | --- | --- |
| `28560703032` | 2 | `WebView on iOS Simulator (4/4)` | 1 | 65.7 | 21.8 |
| `28555153022` | 3 | `WebView on iOS Simulator (4/4)` | 2 | 155.0 | 50.0 |
| `28470726784` | 2 | `WebView on iOS Simulator (4/4)` | 1 | 69.1 | 27.2 |
| `28412462737` | 4 | `WebView on iOS Simulator (4/4)` | 3 | 203.8 | 65.0 |
| `27986856884` | 2 | `WebView on iOS Simulator (4/4)` | 1 | 62.1 | 26.4 |
| `27973339667` | 2 | `WebView on iOS Simulator (4/4)` | 1 | 66.5 | 30.5 |

_Measured from GitHub jobs API `filter=all` minus `filter=latest` for workflow runs whose run_attempt > 1. The finding is emitted only when each credited prior attempt has the same unique dominant failed/timed-out job and that dominant failing job appears in the latest attempt; ambiguous ties, mixed-cause attempts, and retry-only volume are withheld._

**💸 Bill root-cause - OPT64 · Repeated Workflow Attempts From Same Failing Job** - risk **LOW**

- **What ci-speedup measured:** 6 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `WebView on iOS Simulator (4/4)` (9 failed/timed-out prior-attempt job(s), 221.0 failed min) and it appeared again in the latest attempt. ~367 runner-min/mo of prior-attempt compute (59/30d ÷ 100 sampled all-status run(s)).
- **Why this can't slow your merge:** machine-derived proof: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `WebView on iOS Simulator (4/4)` identifies the retry cause, so prior-attempt compute is post-completion waste).
- **Source block:** `runner_minute_spine` matched 4 prior-attempt rows for `.github/workflows/tests_webview_simulator.yml`; current measured cost spine for those rows is 553.233 raw min/mo, 570.527 billable min/mo.
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT64 - Repeated Workflow Attempts From Same Failing Job.
Where: tests_webview_simulator.yml.
What ci-speedup saw: 6 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `WebView on iOS Simulator (4/4)` (9 failed/timed-out prior-attempt job(s), 221.0 failed min) and it appeared again in the latest attempt. ~367 runner-min/mo of prior-attempt compute (59/30d ÷ 100 sampled all-status run(s)).
Saving: 367 min/mo of runner capacity - a bill/capacity reduction, not a merge-wait cut. Neutrality certificate: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `WebView on iOS Simulator (4/4)` identifies the retry cause, so prior-attempt compute is post-completion waste).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

<!-- ci-speedup:tier2-finding id=f42 pattern=OPT46 -->
<a id="r-5"></a>

## 🟢 Runner saving 5: `tests_bidi.yml` - 139 min/mo

**The #5 merge-safe runner-minute saving measured on this repo, by size.**

| Workflow | Overlapping (raced) runs | Mean compute/run (timed basis) | Reclaimable remainder (mean per run) | Reclaimable runner-min/mo (range) |
| --- | --- | --- | --- | --- |
| `.github/workflows/tests_bidi.yml` | 9 confirmed (naive 75) | 36.2 job-min over 8 timed run(s) | 64% of run (Σremainder/Σduration 64%) | ~139-1819 (lower=remainder, upper=naive runs-1) |

_Superseded = a run a NEWER run started before it finished - measured by timestamp overlap, so sequential (non-racing) commits are NOT charged. Cancellation cause is unknowable from the API, so the attribution is INFERENCE. REMAINDER BASIS: cancel-in-progress cancels a superseded run the moment its successor starts, so only the compute AFTER that moment is reclaimable - the credited (lower) figure prices the MEAN per-run compute pro-rated by each superseded run's wall-clock remainder fraction (mean 64%; Σremainder/Σduration 64%), NOT the whole run; exact per-second compute is unknowable because a run's jobs run in parallel, so the pro-rata of the mean is the honest estimate. The whole-run figure is now only the loose UPPER bound (naive runs-1). Basis: the superseded COUNT and the remainder ratio are from the all-status slice (100 runs, from each run's own timestamps); the per-run PRICE is the mean of 8 PR-success timed runs (superseded runs' own jobs aren't fetched) - different populations. GUARDRAIL: verify this is NOT a deploy/release/publish workflow (a mid-flight run may be uploading artifacts / pushing a tag) before enabling cancellation - and take the predicate from the catalog recipe, which scopes cancellation with an expression; never a bare `cancel-in-progress: true`, which also kills in-flight runs on the default branch and on release tags. ROUTING: this workflow triggers on `pull_request` - with a `pull_request` trigger use the catalog's DEFAULT (PR-scoped) predicate; without one, the PR-scoped predicate is never true and saves nothing, so use the catalog's WIDENED predicate._

**💸 Bill root-cause - OPT46 · Superseded Runs Not Cancelled (Missing Concurrency or `cancel-in-progress: false`)** - risk **MEDIUM**

- **What ci-speedup measured:** 9 run(s) across 4 branch(es) were superseded (a newer run started before they finished) in the sampled window; ~139-1819 runner-min/mo of cancellable-remainder compute - the lower figure credits only the 64% mean remainder each superseded run would have burned AFTER its successor started, not the whole run (mean over 8 timed run(s); ×0.67 to the 30d volume (67 runs); 100-run recent slice (not a full 30d census)). Superseded attribution is INFERENCE - the API marks no run 'cancelled-by-concurrency'. (sensitivity range: 139 min/mo to 1,819 min/mo)
- **Why this can't slow your merge:** machine-derived proof: `post_completion_waste` - compute burned after the run signal is already decided (superseded runs: same head_branch, a newer run started before this one finished (timestamp overlap); cancellation cause is inference).
- **Source block:** `runner_minute_spine` matched 1 row for `.github/workflows/tests_bidi.yml`; current measured cost spine for those rows is 2320.309 raw min/mo, 2356.189 billable min/mo.
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt46--superseded-runs-not-cancelled-missing-concurrency-or-cancel-in-progress-false

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT46 - Superseded Runs Not Cancelled (Missing Concurrency or `cancel-in-progress: false`).
Where: tests_bidi.yml.
What ci-speedup saw: 9 run(s) across 4 branch(es) were superseded (a newer run started before they finished) in the sampled window; ~139-1819 runner-min/mo of cancellable-remainder compute - the lower figure credits only the 64% mean remainder each superseded run would have burned AFTER its successor started, not the whole run (mean over 8 timed run(s); ×0.67 to the 30d volume (67 runs); 100-run recent slice (not a full 30d census)). Superseded attribution is INFERENCE - the API marks no run 'cancelled-by-concurrency'.
Saving: 139 min/mo of runner capacity - a bill/capacity reduction, not a merge-wait cut. Neutrality certificate: `post_completion_waste` - compute burned after the run signal is already decided (superseded runs: same head_branch, a newer run started before this one finished (timestamp overlap); cancellation cause is inference). GUARDRAIL: verify this is NOT a deploy/release/publish workflow (a mid-flight run may be uploading artifacts / pushing a tag) before enabling cancellation - and take the predicate from the catalog recipe, which scopes cancellation with an expression; never a bare `cancel-in-progress: true`, which also kills in-flight runs on the default branch and on release tags. ROUTING: this workflow triggers on `pull_request` - with a `pull_request` trigger use the catalog's DEFAULT (PR-scoped) predicate; without one, the PR-scoped predicate is never true and saves nothing, so use the catalog's WIDENED predicate.

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt46--superseded-runs-not-cancelled-missing-concurrency-or-cancel-in-progress-false

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

<!-- ci-speedup:tier2-finding id=f70 pattern=OPT64 -->
<a id="r-6"></a>

## 🟢 Runner saving 6: `tests_webview_simulator.yml` - 112 min/mo

**The #6 merge-safe runner-minute saving measured on this repo, by size.**

| Run | Latest attempt | Dominant failing job | Prior attempts | Prior attempt compute min | Dominant failure min |
| --- | --- | --- | --- | --- | --- |
| `28043360084` | 2 | `WebView on iOS Simulator (3/4)` | 1 | 88.1 | 20.2 |
| `27850434623` | 2 | `WebView on iOS Simulator (3/4)` | 1 | 44.2 | 9.1 |
| `27849871516` | 2 | `WebView on iOS Simulator (3/4)` | 1 | 57.9 | 16.9 |

_Measured from GitHub jobs API `filter=all` minus `filter=latest` for workflow runs whose run_attempt > 1. The finding is emitted only when each credited prior attempt has the same unique dominant failed/timed-out job and that dominant failing job appears in the latest attempt; ambiguous ties, mixed-cause attempts, and retry-only volume are withheld._

**💸 Bill root-cause - OPT64 · Repeated Workflow Attempts From Same Failing Job** - risk **LOW**

- **What ci-speedup measured:** 3 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `WebView on iOS Simulator (3/4)` (3 failed/timed-out prior-attempt job(s), 46.1 failed min) and it appeared again in the latest attempt. ~112 runner-min/mo of prior-attempt compute (59/30d ÷ 100 sampled all-status run(s)).
- **Why this can't slow your merge:** machine-derived proof: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `WebView on iOS Simulator (3/4)` identifies the retry cause, so prior-attempt compute is post-completion waste).
- **Source block:** `runner_minute_spine` matched 4 prior-attempt rows for `.github/workflows/tests_webview_simulator.yml`; current measured cost spine for those rows is 553.233 raw min/mo, 570.527 billable min/mo.
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT64 - Repeated Workflow Attempts From Same Failing Job.
Where: tests_webview_simulator.yml.
What ci-speedup saw: 3 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `WebView on iOS Simulator (3/4)` (3 failed/timed-out prior-attempt job(s), 46.1 failed min) and it appeared again in the latest attempt. ~112 runner-min/mo of prior-attempt compute (59/30d ÷ 100 sampled all-status run(s)).
Saving: 112 min/mo of runner capacity - a bill/capacity reduction, not a merge-wait cut. Neutrality certificate: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `WebView on iOS Simulator (3/4)` identifies the retry cause, so prior-attempt compute is post-completion waste).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

<!-- ci-speedup:tier2-finding id=f38 pattern=OPT46 -->
<a id="r-7"></a>

## 🟢 Runner saving 7: `infra.yml` - 101 min/mo

**The #7 merge-safe runner-minute saving measured on this repo, by size.**

| Workflow | Overlapping (raced) runs | Mean compute/run (timed basis) | Reclaimable remainder (mean per run) | Reclaimable runner-min/mo (range) |
| --- | --- | --- | --- | --- |
| `.github/workflows/infra.yml` | 6 confirmed (naive 49) | 4.4 job-min over 4 timed run(s) | 47% of run (Σremainder/Σduration 46%) | ~101-1752 (lower=remainder, upper=naive runs-1) |

_Superseded = a run a NEWER run started before it finished - measured by timestamp overlap, so sequential (non-racing) commits are NOT charged. Cancellation cause is unknowable from the API, so the attribution is INFERENCE. REMAINDER BASIS: cancel-in-progress cancels a superseded run the moment its successor starts, so only the compute AFTER that moment is reclaimable - the credited (lower) figure prices the MEAN per-run compute pro-rated by each superseded run's wall-clock remainder fraction (mean 47%; Σremainder/Σduration 46%), NOT the whole run; exact per-second compute is unknowable because a run's jobs run in parallel, so the pro-rata of the mean is the honest estimate. The whole-run figure is now only the loose UPPER bound (naive runs-1). Basis: the superseded COUNT and the remainder ratio are from the all-status slice (100 runs, from each run's own timestamps); the per-run PRICE is the mean of 4 PR-success timed runs (superseded runs' own jobs aren't fetched) - different populations. GUARDRAIL: verify this is NOT a deploy/release/publish workflow (a mid-flight run may be uploading artifacts / pushing a tag) before enabling cancellation - and take the predicate from the catalog recipe, which scopes cancellation with an expression; never a bare `cancel-in-progress: true`, which also kills in-flight runs on the default branch and on release tags. ROUTING: this workflow triggers on `pull_request`/`push` - with a `pull_request` trigger use the catalog's DEFAULT (PR-scoped) predicate; without one, the PR-scoped predicate is never true and saves nothing, so use the catalog's WIDENED predicate._

**💸 Bill root-cause - OPT46 · Superseded Runs Not Cancelled (Missing Concurrency or `cancel-in-progress: false`)** - risk **MEDIUM**

- **What ci-speedup measured:** 6 run(s) across 3 branch(es) were superseded (a newer run started before they finished) in the sampled window; ~101-1752 runner-min/mo of cancellable-remainder compute - the lower figure credits only the 47% mean remainder each superseded run would have burned AFTER its successor started, not the whole run (mean over 4 timed run(s); ×8.12 to the 30d volume (812 runs); 100-run recent slice (not a full 30d census)). Superseded attribution is INFERENCE - the API marks no run 'cancelled-by-concurrency'. (sensitivity range: 101 min/mo to 1,752 min/mo)
- **Why this can't slow your merge:** machine-derived proof: `post_completion_waste` - compute burned after the run signal is already decided (superseded runs: same head_branch, a newer run started before this one finished (timestamp overlap); cancellation cause is inference).
- **Source block:** `runner_minute_spine` matched 2 rows for `.github/workflows/infra.yml`; current measured cost spine for those rows is 3552.500 raw min/mo, 4384.800 billable min/mo.
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt46--superseded-runs-not-cancelled-missing-concurrency-or-cancel-in-progress-false

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT46 - Superseded Runs Not Cancelled (Missing Concurrency or `cancel-in-progress: false`).
Where: infra.yml.
What ci-speedup saw: 6 run(s) across 3 branch(es) were superseded (a newer run started before they finished) in the sampled window; ~101-1752 runner-min/mo of cancellable-remainder compute - the lower figure credits only the 47% mean remainder each superseded run would have burned AFTER its successor started, not the whole run (mean over 4 timed run(s); ×8.12 to the 30d volume (812 runs); 100-run recent slice (not a full 30d census)). Superseded attribution is INFERENCE - the API marks no run 'cancelled-by-concurrency'.
Saving: 101 min/mo of runner capacity - a bill/capacity reduction, not a merge-wait cut. Neutrality certificate: `post_completion_waste` - compute burned after the run signal is already decided (superseded runs: same head_branch, a newer run started before this one finished (timestamp overlap); cancellation cause is inference). GUARDRAIL: verify this is NOT a deploy/release/publish workflow (a mid-flight run may be uploading artifacts / pushing a tag) before enabling cancellation - and take the predicate from the catalog recipe, which scopes cancellation with an expression; never a bare `cancel-in-progress: true`, which also kills in-flight runs on the default branch and on release tags. ROUTING: this workflow triggers on `pull_request`/`push` - with a `pull_request` trigger use the catalog's DEFAULT (PR-scoped) predicate; without one, the PR-scoped predicate is never true and saves nothing, so use the catalog's WIDENED predicate.

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt46--superseded-runs-not-cancelled-missing-concurrency-or-cancel-in-progress-false

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

<!-- ci-speedup:tier2-finding id=f71 pattern=OPT64 -->
<a id="r-8"></a>

## 🟢 Runner saving 8: `tests_webview_simulator.yml` - 74 min/mo

**The #8 merge-safe runner-minute saving measured on this repo, by size.**

| Run | Latest attempt | Dominant failing job | Prior attempts | Prior attempt compute min | Dominant failure min |
| --- | --- | --- | --- | --- | --- |
| `29045183195` | 2 | `WebView on iOS Simulator (2/4)` | 1 | 65.3 | 20.2 |
| `28843490162` | 2 | `WebView on iOS Simulator (2/4)` | 1 | 59.9 | 24.4 |

_Measured from GitHub jobs API `filter=all` minus `filter=latest` for workflow runs whose run_attempt > 1. The finding is emitted only when each credited prior attempt has the same unique dominant failed/timed-out job and that dominant failing job appears in the latest attempt; ambiguous ties, mixed-cause attempts, and retry-only volume are withheld._

**💸 Bill root-cause - OPT64 · Repeated Workflow Attempts From Same Failing Job** - risk **LOW**

- **What ci-speedup measured:** 2 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `WebView on iOS Simulator (2/4)` (2 failed/timed-out prior-attempt job(s), 44.6 failed min) and it appeared again in the latest attempt. ~74 runner-min/mo of prior-attempt compute (59/30d ÷ 100 sampled all-status run(s)).
- **Why this can't slow your merge:** machine-derived proof: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `WebView on iOS Simulator (2/4)` identifies the retry cause, so prior-attempt compute is post-completion waste).
- **Source block:** `runner_minute_spine` matched 4 prior-attempt rows for `.github/workflows/tests_webview_simulator.yml`; current measured cost spine for those rows is 553.233 raw min/mo, 570.527 billable min/mo.
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT64 - Repeated Workflow Attempts From Same Failing Job.
Where: tests_webview_simulator.yml.
What ci-speedup saw: 2 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `WebView on iOS Simulator (2/4)` (2 failed/timed-out prior-attempt job(s), 44.6 failed min) and it appeared again in the latest attempt. ~74 runner-min/mo of prior-attempt compute (59/30d ÷ 100 sampled all-status run(s)).
Saving: 74 min/mo of runner capacity - a bill/capacity reduction, not a merge-wait cut. Neutrality certificate: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `WebView on iOS Simulator (2/4)` identifies the retry cause, so prior-attempt compute is post-completion waste).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

<!-- ci-speedup:tier2-finding id=f40 pattern=OPT36 -->
<a id="r-9"></a>

## 🟢 Runner saving 9: `publish_release.yml` - 12 min/mo

**The #9 merge-safe runner-minute saving measured on this repo, by size.**

| Workflow | Consecutive same-head_sha schedule runs | Mean compute/run | Credited runner-min/mo |
| --- | --- | --- | --- |
| `.github/workflows/publish_release.yml` | 18 redundant run(s) in 12 group(s) | 2.3 job-min over 20 timed run(s) | ~12 |

_Schedule burn is counted only on event=schedule runs whose head_sha repeats consecutively, so the detector proves the workflow ran again without a code change. Basis: the count is from the all-status schedule slice; the per-run price is the mean of 20 successful schedule-event timed run(s). GUARDRAIL: confirm the current cadence is not an operational SLA before increasing the cron interval._

**💸 Bill root-cause - OPT36 · Cron Schedule Too Frequent** - risk **LOW**

- **What ci-speedup measured:** 18 scheduled run(s) in 12 consecutive same-head_sha group(s) re-ran without a code change in the sampled schedule slice (18% of 100 schedule run(s)); ~12 runner-min/mo of schedule-event compute (mean over 20 timed run(s); ×0.30 to the 30d volume (30 runs); 100-run recent slice (not a full 30d census)).
- **Why this can't slow your merge:** machine-derived proof: `non_pr_event` - `schedule` runs do not gate a PR merge (event=schedule subset only; consecutive same-head_sha schedule runs; schedule is not a developer PR/merge event).
- **Source block:** `runner_minute_spine` matched 2 rows for `.github/workflows/publish_release.yml`; current measured cost spine for those rows is 87.084 raw min/mo, 120.346 billable min/mo.
- **Guardrail:** Confirm the cron cadence is not an operational SLA; prefer widening the interval only for cleanup/triage/build jobs where delayed execution is acceptable.
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt36--cron-schedule-too-frequent

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT36 - Cron Schedule Too Frequent.
Where: publish_release.yml.
What ci-speedup saw: 18 scheduled run(s) in 12 consecutive same-head_sha group(s) re-ran without a code change in the sampled schedule slice (18% of 100 schedule run(s)); ~12 runner-min/mo of schedule-event compute (mean over 20 timed run(s); ×0.30 to the 30d volume (30 runs); 100-run recent slice (not a full 30d census)).
Saving: 12 min/mo of runner capacity - a bill/capacity reduction, not a merge-wait cut. Neutrality certificate: `non_pr_event` - `schedule` runs do not gate a PR merge (event=schedule subset only; consecutive same-head_sha schedule runs; schedule is not a developer PR/merge event). GUARDRAIL: confirm the current cadence is not an operational SLA before increasing the cron interval.

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt36--cron-schedule-too-frequent

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

<!-- ci-speedup:tier2-finding id=f44 pattern=OPT64 -->
<a id="r-10"></a>

## 🟢 Runner saving 10: `tests_docker_changes.yml` - 8 min/mo

**The #10 merge-safe runner-minute saving measured on this repo, by size.**

| Run | Latest attempt | Dominant failing job | Prior attempts | Prior attempt compute min | Dominant failure min |
| --- | --- | --- | --- | --- | --- |
| `26806344641` | 2 | `test_linux_docker / Docker noble amd64` | 1 | 16.8 | 1.4 |

_Measured from GitHub jobs API `filter=all` minus `filter=latest` for workflow runs whose run_attempt > 1. The finding is emitted only when each credited prior attempt has the same unique dominant failed/timed-out job and that dominant failing job appears in the latest attempt; ambiguous ties, mixed-cause attempts, and retry-only volume are withheld._

**💸 Bill root-cause - OPT64 · Repeated Workflow Attempts From Same Failing Job** - risk **LOW**

- **What ci-speedup measured:** 1 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `test_linux_docker / Docker noble amd64` (1 failed/timed-out prior-attempt job(s), 1.4 failed min) and it appeared again in the latest attempt. ~8 runner-min/mo of prior-attempt compute (11/30d ÷ 24 sampled all-status run(s)).
- **Why this can't slow your merge:** machine-derived proof: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `test_linux_docker / Docker noble amd64` identifies the retry cause, so prior-attempt compute is post-completion waste).
- **Source block:** `runner_minute_spine` matched 4 prior-attempt rows for `.github/workflows/tests_docker_changes.yml`; current measured cost spine for those rows is 7.715 raw min/mo, 8.251 billable min/mo.
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT64 - Repeated Workflow Attempts From Same Failing Job.
Where: tests_docker_changes.yml.
What ci-speedup saw: 1 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `test_linux_docker / Docker noble amd64` (1 failed/timed-out prior-attempt job(s), 1.4 failed min) and it appeared again in the latest attempt. ~8 runner-min/mo of prior-attempt compute (11/30d ÷ 24 sampled all-status run(s)).
Saving: 8 min/mo of runner capacity - a bill/capacity reduction, not a merge-wait cut. Neutrality certificate: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `test_linux_docker / Docker noble amd64` identifies the retry cause, so prior-attempt compute is post-completion waste).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

<!-- ci-speedup:tier2-finding id=f39 pattern=OPT64 -->
<a id="r-11"></a>

## 🟢 Runner saving 11: `publish_release.yml` - 0.7 min/mo

**The #11 merge-safe runner-minute saving measured on this repo, by size.**

| Run | Latest attempt | Dominant failing job | Prior attempts | Prior attempt compute min | Dominant failure min |
| --- | --- | --- | --- | --- | --- |
| `28022804749` | 2 | `publish NPM and driver` | 1 | 1.9 | 1.0 |

_Measured from GitHub jobs API `filter=all` minus `filter=latest` for workflow runs whose run_attempt > 1. The finding is emitted only when each credited prior attempt has the same unique dominant failed/timed-out job and that dominant failing job appears in the latest attempt; ambiguous ties, mixed-cause attempts, and retry-only volume are withheld._

**💸 Bill root-cause - OPT64 · Repeated Workflow Attempts From Same Failing Job** - risk **LOW**

- **What ci-speedup measured:** 1 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `publish NPM and driver` (1 failed/timed-out prior-attempt job(s), 1.0 failed min) and it appeared again in the latest attempt. ~1 runner-min/mo of prior-attempt compute (38/30d ÷ 100 sampled all-status run(s)).
- **Why this can't slow your merge:** machine-derived proof: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `publish NPM and driver` identifies the retry cause, so prior-attempt compute is post-completion waste).
- **Source block:** `runner_minute_spine` matched 2 prior-attempt rows for `.github/workflows/publish_release.yml`; current measured cost spine for those rows is 0.729 raw min/mo, 1.140 billable min/mo.
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT64 - Repeated Workflow Attempts From Same Failing Job.
Where: publish_release.yml.
What ci-speedup saw: 1 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `publish NPM and driver` (1 failed/timed-out prior-attempt job(s), 1.0 failed min) and it appeared again in the latest attempt. ~1 runner-min/mo of prior-attempt compute (38/30d ÷ 100 sampled all-status run(s)).
Saving: 0.7 min/mo of runner capacity - a bill/capacity reduction, not a merge-wait cut. Neutrality certificate: `post_completion_waste` - compute burned after the run signal is already decided (run_attempt>1: `filter=all` exposes prior-attempt jobs, `filter=latest` is the superseding latest attempt; the dominant failing job `publish NPM and driver` identifies the retry cause, so prior-attempt compute is post-completion waste).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

---

<a id="also-noticed"></a>

## 🧹 Also noticed - residual hygiene

> Most of these stay outside the wall-clock-neutral runner-minute section and do **not** sit on the merge-gating critical path above, so fixing them removes little or no developer wall-clock. **One or more exceptions are flagged inline** with a **Wall-clock** note: those DO sit on the critical path and their fix cuts developer wall-clock (shown first). **Expand any finding** for its locations, evidence, the catalog fix recipe, and a copy-paste agent prompt; exact per-occurrence lines + evidence also live in the findings JSON.

> ⚠️ _Approximate: computed across all workflows, but 7 capped workflow(s) still use the shallow 10-run job sample for finding/queue values; 8 runner-minute source workflow(s) still use a shallow 10-run cost-spine sample. Figures can shift run-to-run; re-run with `--shallow-runs 20` to confirm exact values._

<details>
<summary><strong>OPT73 - Shared step recurs across the cluster - fix once, lower the floor</strong> · ~2m 15s wall-clock · HIGH · 1 across 1 wf</summary>

**Where:** `tests_primary.yml` (ubuntu-22.04 (webkit - Node.js 20))
**Wall-clock:** unlike the other findings in this section, this one **sits ON the merge-gating critical path** (a long pole) - its catalog fix **cuts developer wall-clock**, it is not a bill-only cleanup. See the spine above and this pattern's catalog recipe below for the remedy.
**Evidence:** the `Run ./.github/actions/run-test` step is 100% of the slowest cluster job `ubuntu-22.04 (webkit - Node.js 20)` (2400s) and recurs across 5 concurrent jobs of `.github/workflows/tests_primary.yml` (~1650-2395s per job) - a cluster-floor lever
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt73--shared-sub-step-across-critical-path-jobs-cluster-floor-lever

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT73 - Shared step recurs across the cluster - fix once, lower the floor.
Where: tests_primary.yml (ubuntu-22.04 (webkit - Node.js 20)).
What ci-speedup saw: the `Run ./.github/actions/run-test` step is 100% of the slowest cluster job `ubuntu-22.04 (webkit - Node.js 20)` (2400s) and recurs across 5 concurrent jobs of `.github/workflows/tests_primary.yml` (~1650-2395s per job) - a cluster-floor lever
Saving: developer WALL-CLOCK (~2m 15s) - this job is a long pole ON the merge-gating critical path, so its catalog fix shortens the merge wait. NOT a runner-bill cut, and NOT off the critical path.

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt73--shared-sub-step-across-critical-path-jobs-cluster-floor-lever

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

<details>
<summary><strong>OPT24 - Long Test Job Without Sharding</strong> · ~2m 15s wall-clock · HIGH · 4 across 2 wf</summary>

**Where:** `tests_primary.yml` (Installation Test macos-latest), `tests_primary.yml` (Installation Test ubuntu-latest), `tests_primary.yml` (Installation Test windows-latest), `tests_secondary.yml` (Installation Test ubuntu-latest)
**Wall-clock:** unlike the other findings in this section, this one **sits ON the merge-gating critical path** (a long pole) - its catalog fix **cuts developer wall-clock**, it is not a bill-only cleanup. See the spine above and this pattern's catalog recipe below for the remedy.
**Evidence:** job `Installation Test windows-latest` p50 1694s over 12 runs, no shard axis observed (job names lack a `shard` / `partition` matrix marker)
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt24--long-test-job-without-sharding

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT24 - Long Test Job Without Sharding.
Where: tests_primary.yml (Installation Test macos-latest); tests_primary.yml (Installation Test ubuntu-latest); tests_primary.yml (Installation Test windows-latest); tests_secondary.yml (Installation Test ubuntu-latest).
What ci-speedup saw: job `Installation Test windows-latest` p50 1694s over 12 runs, no shard axis observed (job names lack a `shard` / `partition` matrix marker)
Saving: developer WALL-CLOCK (~2m 15s) - this job is a long pole ON the merge-gating critical path, so its catalog fix shortens the merge wait. NOT a runner-bill cut, and NOT off the critical path.

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt24--long-test-job-without-sharding

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

<details>
<summary><strong>OPT25 - Matrix Leg Imbalance</strong> · ~2m 09s wall-clock · MEDIUM · 2 across 2 wf</summary>

**Where:** `tests_primary.yml` (ubuntu-22.04), `tests_secondary.yml` (Windows)
**Wall-clock:** unlike the other findings in this section, this one **sits ON the merge-gating critical path** (a long pole) - its catalog fix **cuts developer wall-clock**, it is not a bill-only cleanup. See the spine above and this pattern's catalog recipe below for the remedy.
**Evidence:** leg `ubuntu-22.04 (webkit - Node.js 20)` median 2402s vs `ubuntu-22.04 (chromium - Node.js 24)` 1086s - 2.2× imbalance over 60 sampled runs (heterogeneous legs - split the slow leg, don't rebalance)
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt25--shard-imbalance

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT25 - Matrix Leg Imbalance.
Where: tests_primary.yml (ubuntu-22.04); tests_secondary.yml (Windows).
What ci-speedup saw: leg `ubuntu-22.04 (webkit - Node.js 20)` median 2402s vs `ubuntu-22.04 (chromium - Node.js 24)` 1086s - 2.2× imbalance over 60 sampled runs (heterogeneous legs - split the slow leg, don't rebalance)
Saving: developer WALL-CLOCK (~2m 09s) - this job is a long pole ON the merge-gating critical path, so its catalog fix shortens the merge wait. NOT a runner-bill cut, and NOT off the critical path.

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt25--shard-imbalance

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

<details>
<summary><strong>OPT73 - Shared step recurs across the cluster - fix once, lower the floor</strong> · 108,230 min/mo · HIGH · 1 across 1 wf</summary>

**Where:** `tests_mcp.yml` (windows-latest - firefox)
**Evidence:** the `Run ./.github/actions/run-test` step is 99% of the slowest cluster job `windows-latest - firefox` (2220s) and recurs across 6 concurrent jobs of `.github/workflows/tests_mcp.yml` (~1380-2208s per job) - a cluster-floor lever
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt73--shared-sub-step-across-critical-path-jobs-cluster-floor-lever

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT73 - Shared step recurs across the cluster - fix once, lower the floor.
Where: tests_mcp.yml (windows-latest - firefox).
What ci-speedup saw: the `Run ./.github/actions/run-test` step is 99% of the slowest cluster job `windows-latest - firefox` (2220s) and recurs across 6 concurrent jobs of `.github/workflows/tests_mcp.yml` (~1380-2208s per job) - a cluster-floor lever
Saving: ~108,230 runner-min/mo - off the merge-gating critical path, so ~0 developer wall-clock (a cloud-bill cut, not a merge-wait cut).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt73--shared-sub-step-across-critical-path-jobs-cluster-floor-lever

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

<details>
<summary><strong>OPT73 - Shared step recurs across the cluster - fix once, lower the floor</strong> · 70,894 min/mo · HIGH · 1 across 1 wf</summary>

**Where:** `tests_secondary.yml` (Windows (firefox))
**Evidence:** the `Run ./.github/actions/run-test` step is 100% of the slowest cluster job `Windows (firefox)` (4375s) and recurs across 5 concurrent jobs of `.github/workflows/tests_secondary.yml` (~2652-4366s per job) - a cluster-floor lever
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt73--shared-sub-step-across-critical-path-jobs-cluster-floor-lever

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT73 - Shared step recurs across the cluster - fix once, lower the floor.
Where: tests_secondary.yml (Windows (firefox)).
What ci-speedup saw: the `Run ./.github/actions/run-test` step is 100% of the slowest cluster job `Windows (firefox)` (4375s) and recurs across 5 concurrent jobs of `.github/workflows/tests_secondary.yml` (~2652-4366s per job) - a cluster-floor lever
Saving: ~70,894 runner-min/mo - off the merge-gating critical path, so ~0 developer wall-clock (a cloud-bill cut, not a merge-wait cut).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt73--shared-sub-step-across-critical-path-jobs-cluster-floor-lever

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

<details>
<summary><strong>OPT64 - Repeated Workflow Attempts From Same Failing Job</strong> · 2,769 min/mo · LOW · 1 across 1 wf</summary>

**Where:** `tests_secondary.yml`
**Tier-2 note:** measured wall-clock-neutral instances of this same pattern are promoted above; this appendix row shows only the remaining modeled, uncertified, or source-unbacked instance(s).
**Evidence:** 1 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `macos-15-large (firefox)` (1 failed/timed-out prior-attempt job(s), 51.1 failed min) and it appeared again in the latest attempt. ~2769 runner-min/mo of prior-attempt compute (322/30d ÷ 100 sampled all-status run(s)).
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT64 - Repeated Workflow Attempts From Same Failing Job.
Where: tests_secondary.yml.
What ci-speedup saw: 1 sampled run_attempt>1 workflow run(s) had prior-attempt jobs present in `filter=all` but absent from `filter=latest`; the unique dominant failing job was `macos-15-large (firefox)` (1 failed/timed-out prior-attempt job(s), 51.1 failed min) and it appeared again in the latest attempt. ~2769 runner-min/mo of prior-attempt compute (322/30d ÷ 100 sampled all-status run(s)).
Saving: ~2,769 runner-min/mo - off the merge-gating critical path, so ~0 developer wall-clock (a cloud-bill cut, not a merge-wait cut).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt64--repeated-workflow-attempts-from-same-failing-job

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

<details>
<summary><strong>OPT73 - Shared step recurs across the cluster - fix once, lower the floor</strong> · 1,313 min/mo · HIGH · 1 across 1 wf</summary>

**Where:** `tests_webview_simulator.yml` (WebView on iOS Simulator (2/4))
**Evidence:** the `Run WebView tests` step is 81% of the slowest cluster job `WebView on iOS Simulator (2/4)` (1610s) and recurs across 3 concurrent jobs of `.github/workflows/tests_webview_simulator.yml` (~455-1308s per job) - a cluster-floor lever
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt73--shared-sub-step-across-critical-path-jobs-cluster-floor-lever

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT73 - Shared step recurs across the cluster - fix once, lower the floor.
Where: tests_webview_simulator.yml (WebView on iOS Simulator (2/4)).
What ci-speedup saw: the `Run WebView tests` step is 81% of the slowest cluster job `WebView on iOS Simulator (2/4)` (1610s) and recurs across 3 concurrent jobs of `.github/workflows/tests_webview_simulator.yml` (~455-1308s per job) - a cluster-floor lever
Saving: ~1,313 runner-min/mo - off the merge-gating critical path, so ~0 developer wall-clock (a cloud-bill cut, not a merge-wait cut).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt73--shared-sub-step-across-critical-path-jobs-cluster-floor-lever

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

<details>
<summary><strong>OPT2 - Uncached Large Downloads</strong> · 1,231 min/mo · MEDIUM · 5 across 5 wf</summary>

**Where:** `infra.yml:24` (doc-and-lint), `tests_bidi.yml:54` (test_bidi), `tests_components.yml:46` (test_components), `tests_extension.yml:50` (test_extension), `tests_primary.yml:155` (test_vscode_extension)
**Evidence:** job `doc-and-lint` runs `playwright install` with no preceding `actions/cache` step keyed on the Playwright version; job `test_bidi` runs `playwright install` with no preceding `actions/cache` step keyed on the Playwright version; job `test_components` runs `playwright install` with no preceding `actions/cache` step keyed on the Playwright version; job `test_extension` runs `playwright install` with no preceding `actions/cache` step keyed on the Playwright version; job `test_vscode_extension` runs `playwright install` with no preceding `actions/cache` step keyed on the Playwright version
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt2--uncached-large-downloads

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT2 - Uncached Large Downloads.
Where: infra.yml:24 (doc-and-lint); tests_bidi.yml:54 (test_bidi); tests_components.yml:46 (test_components); tests_extension.yml:50 (test_extension); tests_primary.yml:155 (test_vscode_extension).
What ci-speedup saw: job `doc-and-lint` runs `playwright install` with no preceding `actions/cache` step keyed on the Playwright version; job `test_bidi` runs `playwright install` with no preceding `actions/cache` step keyed on the Playwright version; job `test_components` runs `playwright install` with no preceding `actions/cache` step keyed on the Playwright version; job `test_extension` runs `playwright install` with no preceding `actions/cache` step keyed on the Playwright version; job `test_vscode_extension` runs `playwright install` with no preceding `actions/cache` step keyed on the Playwright version
Saving: ~1,231 runner-min/mo - off the merge-gating critical path, so ~0 developer wall-clock (a cloud-bill cut, not a merge-wait cut).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt2--uncached-large-downloads

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

<details>
<summary><strong>OPT14 - Repeated Checkout/Setup Without Artifact Handoff (and Slow Tool Replacement)</strong> · 1,172 min/mo · MEDIUM · 2 across 2 wf</summary>

**Where:** `infra.yml:1` (doc-and-lint), `tests_primary.yml:1` (test_vscode_extension)
**Wall-clock:** this saves runner-minutes but its fix is **wall-clock-negative** (build-once-then-fan-out adds a serial gate), so it lengthens the merge wait. Treat it as a bill saving, not a speed win.
**Evidence:** 2 jobs each run checkout + dependency install with no `actions/upload-artifact` / `download-artifact` handoff: doc-and-lint, lint-snippets; 2 jobs each run checkout + dependency install with no `actions/upload-artifact` / `download-artifact` handoff: test_vscode_extension, test_package_installations
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt14--repeated-checkout-setup-without-artifact-handoff-and-slow-tool-replacement

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT14 - Repeated Checkout/Setup Without Artifact Handoff (and Slow Tool Replacement).
Where: infra.yml:1 (doc-and-lint); tests_primary.yml:1 (test_vscode_extension).
What ci-speedup saw: 2 jobs each run checkout + dependency install with no `actions/upload-artifact` / `download-artifact` handoff: doc-and-lint, lint-snippets; 2 jobs each run checkout + dependency install with no `actions/upload-artifact` / `download-artifact` handoff: test_vscode_extension, test_package_installations
Saving: ~1,172 runner-min/mo - off the merge-gating critical path, so ~0 developer wall-clock (a cloud-bill cut, not a merge-wait cut).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt14--repeated-checkout-setup-without-artifact-handoff-and-slow-tool-replacement

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

<details>
<summary><strong>OPT35 - Missing `fail-fast` on Non-Diagnostic Matrix Dimensions</strong> · 560 min/mo · LOW · 2 across 2 wf</summary>

**Where:** `tests_primary.yml` (test_test_runner), `tests_webview_simulator.yml` (test_webview_simulator)
**Tier-2 note:** measured wall-clock-neutral instance(s) of this pattern did not have matching render-ready `runner_minute_spine` source rows, so they are kept here instead of rendered as source-backed savings cards. Their computed neutrality certificate(s) (`post_completion_waste`) are stamped in findings.json and re-derived by verify_report.
**Evidence:** 4 sampled failed matrix occurrence(s) left shard sibling jobs running after the first failed shard; ~325 runner-min/mo of post-failure matrix compute (750/30d ÷ 100 sampled all-status run(s)).; 39 sampled failed matrix occurrence(s) left shard sibling jobs running after the first failed shard; ~235 runner-min/mo of post-failure matrix compute (59/30d ÷ 100 sampled all-status run(s)).
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt35--missing-fail-fast-on-non-diagnostic-matrix-dimensions

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT35 - Missing `fail-fast` on Non-Diagnostic Matrix Dimensions.
Where: tests_primary.yml (test_test_runner); tests_webview_simulator.yml (test_webview_simulator).
What ci-speedup saw: 4 sampled failed matrix occurrence(s) left shard sibling jobs running after the first failed shard; ~325 runner-min/mo of post-failure matrix compute (750/30d ÷ 100 sampled all-status run(s)).; 39 sampled failed matrix occurrence(s) left shard sibling jobs running after the first failed shard; ~235 runner-min/mo of post-failure matrix compute (59/30d ÷ 100 sampled all-status run(s)).
Saving: ~560 runner-min/mo - off the merge-gating critical path, so ~0 developer wall-clock (a cloud-bill cut, not a merge-wait cut).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt35--missing-fail-fast-on-non-diagnostic-matrix-dimensions

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

<details>
<summary><strong>OPT73 - Shared step recurs across the cluster - fix once, lower the floor</strong> · 72 min/mo · HIGH · 1 across 1 wf</summary>

**Where:** `tests_docker_changes.yml` (test_linux_docker / Docker noble arm64)
**Evidence:** the `Run @smoke tests inside docker` step is 27% of the slowest cluster job `test_linux_docker / Docker noble arm64` (288s) and recurs across 6 concurrent jobs of `.github/workflows/tests_docker_changes.yml` (~75-112s per job) - a cluster-floor lever
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt73--shared-sub-step-across-critical-path-jobs-cluster-floor-lever

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT73 - Shared step recurs across the cluster - fix once, lower the floor.
Where: tests_docker_changes.yml (test_linux_docker / Docker noble arm64).
What ci-speedup saw: the `Run @smoke tests inside docker` step is 27% of the slowest cluster job `test_linux_docker / Docker noble arm64` (288s) and recurs across 6 concurrent jobs of `.github/workflows/tests_docker_changes.yml` (~75-112s per job) - a cluster-floor lever
Saving: ~72 runner-min/mo - off the merge-gating critical path, so ~0 developer wall-clock (a cloud-bill cut, not a merge-wait cut).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt73--shared-sub-step-across-critical-path-jobs-cluster-floor-lever

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

<details>
<summary><strong>OPT73 - Shared step recurs across the cluster - fix once, lower the floor</strong> · 27 min/mo · HIGH · 1 across 1 wf</summary>

**Where:** `tests_docker_release.yml` (test_linux_docker / Docker resolute arm64)
**Evidence:** the `Run @smoke tests inside docker` step is 26% of the slowest cluster job `test_linux_docker / Docker resolute arm64` (308s) and recurs across 6 concurrent jobs of `.github/workflows/tests_docker_release.yml` (~77-114s per job) - a cluster-floor lever
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt73--shared-sub-step-across-critical-path-jobs-cluster-floor-lever

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT73 - Shared step recurs across the cluster - fix once, lower the floor.
Where: tests_docker_release.yml (test_linux_docker / Docker resolute arm64).
What ci-speedup saw: the `Run @smoke tests inside docker` step is 26% of the slowest cluster job `test_linux_docker / Docker resolute arm64` (308s) and recurs across 6 concurrent jobs of `.github/workflows/tests_docker_release.yml` (~77-114s per job) - a cluster-floor lever
Saving: ~27 runner-min/mo - off the merge-gating critical path, so ~0 developer wall-clock (a cloud-bill cut, not a merge-wait cut).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt73--shared-sub-step-across-critical-path-jobs-cluster-floor-lever

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

> [!TIP]
> **+4 more hygiene pattern(s) (23 occurrence(s)) not shown** - lower bill saving, kept in the findings JSON so nothing is dropped.

## 🗄️ Data sources

> **Where this data comes from**
>
> - **Critical path + step P50:** the committed ci-speedup audit of `microsoft/playwright`, scanned **2026-07-21** - P50 over **145 runs / 1484 jobs** across 18 workflows (latest runs at scan time).
> - **Data-collection cost:** **824 gh API call(s)** in ~3m 07s - adaptive sampling - a 10-run shallow pass over every workflow, then 3 of 9 PR-gating pole candidate(s) deepened to 20 runs, plus 6 bill-pole workflow candidate(s) deepened to 20 runs for the runner-minute source block (the gate, drill-set, and floor are full-depth; other finding-level values may still rest on the shallow sample).
> - **Which checks gate (the critical-path ordering):** measured from **20/20 sampled PRs**.
> - ⚠️ **Required checks were unreadable** (no admin / branch protection 404), so 'gate' here means the **slowest check on a typical PR** (observed), not a *confirmed required* check. Slow checks that run on only a minority of PRs are shown as a footnote, not the headline.
> - **Step internals + cross-run checks (the per-pole drill-downs):** the pole jobs' raw logs, fetched **2026-07-21T16:12:52.475507+00:00** (newer than the critical-path audit above). Each drill-down is **one representative run** of that job - the one closest to its typical time (for a bimodal job, a representative of the slow mode the drill explains), linked + labelled per pole - and the **Cross-run check** validates the load-bearing magnitude (median + range) across several runs.

| Source | Coverage | Used for |
| --- | --- | --- |
| ci-speedup static scan (skill commit `3bb6e2e`, scripts tree `4c21de6`) | All `.github/workflows/*.yml` under the analyzed tree (4037273) | Static pattern detection (OPT1-OPT69 catalog) |
| gh runs/jobs API (timestamps) | 145 runs / 1484 jobs sampled | Critical-path + per-step P50 |
| job logs | 2 job log(s) sampled | Step internals + cross-run magnitude (deeper levels) |
| workflow YAML | 18 from the analyzed checkout | `on:` triggers, matrix/shard axes, job timeouts (detector inputs) |

**Data freshness.** Analyzer ran at `2026-07-21T16:12:52.475507+00:00`; workflow YAML is read from the analyzed tree at commit `4037273`. Timing and activity counts reflect the sampled runs over a rolling 30-day window at scan time. 824 gh API queries were made.

> _The runner-minute / cost-spine figures in this report keep the full sample by design (they size total compute, not the critical path), so they still include the earlier configuration; a duration- or structure-changing edit (e.g. a shard split) blends both layouts._

_The concurrent checks (the Contents critical path) are P50 across sampled PRs. The per-step timeline + the drill are **one representative run** - the one closest to the P50 time - so they are absolute for that run, not P50. The **categorical cause** is stable across runs; where a **Cross-run check** is shown it gives the magnitude's median + range across several runs, so the single run's number isn't taken on faith. Per-step bars are scaled within each drill._

_The drill bars are plain-English labels for what's in the job log (e.g. a `DB migrations` bar is logged as `Total Migration Time:`). To verify any number, follow the pole's **🔗 Audit** link to the gating step, expand it, and search (Ctrl-F) for the verbatim strings the Audit line lists - GitHub anchors to the step, not an exact log line._

---

Generated by [StarSling](https://starsling.dev) 💫
