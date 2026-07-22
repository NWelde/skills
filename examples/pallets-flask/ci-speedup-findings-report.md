# pallets/flask - why is the merge slow?

| Repository | `pallets/flask` |
| :--- | :--- |
| **Audited commit** | [`36e4a82`](https://github.com/pallets/flask/commit/36e4a824f340fdee7ed50937ba8e7f6bc7d17f81) - file & line references are anchored to this tree |
| **Runs analyzed** | 45 runs / 126 jobs across 5 workflows |
| **Runs window** | 2026-06-21 → 2026-07-21 (30-day window) |
| **PR gate sample** | 20 / 20 PRs |
| **Audit** | ran 2026-07-21 · ci-speedup skill commit `3bb6e2e` (pre-public archive) |

> **Bottom line.** A typical PR waits **34s** for all checks to finish. The biggest single measured win is **~8s** off the slowest fixable check, `Windows` - see [Long pole 1](#pole-1) for the drill-down to the biggest lever.
>
> **34s until all checks finish** - `Windows` is the slowest check a typical PR waits on. 
>
> **`.github/workflows/tests.yaml` changed ~106 days ago - narrowed to the current configuration.** This audit measures only the 7 runs since that change; the 13 earlier runs measured the retired configuration and were excluded so no drill-down blends the two.
>
> **`.github/workflows/zizmor.yaml` changed ~108 days ago - narrowed to the current configuration.** This audit measures only the 6 runs since that change; the 4 earlier runs measured the retired configuration and were excluded so no drill-down blends the two.
>
> **Fileless status gate (disclosed, not headlined).** `3.9` shows ~19s, but that span is PR-lifetime status-gating latency - how long a bot/label/external-app check sat open on the PR, not CI compute - so it is excluded from the merge-wait headline above (which measures what CI makes a typical PR wait). It is disclosed here so the wait is never hidden.
>
> **After the gate.** 3 min/mo of wall-clock-neutral runner minutes is recoverable (1 neutral finding; none can slow a merge).

## 📋 Contents

**🐌 Critical path** - the checks that gate your merge, each linking to its long-pole drill-down (waterfall → biggest lever → agent prompt):

1. 🟡 [Windows](#pole-1) - 34s (the gate)
2. 🟡 [PyPy](#pole-2) - 26s · rarely the merge pole
3. 🟡 [3.14t](#pole-3) - 24s · rarely the merge pole
4. 🟡 [Mac](#pole-4) - 20s · rarely the merge pole
5. 🟡 [main](#pole-5) - 19s · rarely the merge pole

**💸 Runner-minute reductions** - ~3 min/mo of measured, merge-safe runner-minute savings, backed by a 18-row cost spine: [section](#runner-minute-reductions).

1. 🟢 [Cron Schedule Too Frequent](#r-1) - 3 min/mo

**🧹 Also noticed** - 2 additional hygiene findings kept outside the neutral runner-minute section (modeled/uncertified, mostly ~0 wall-clock), below the critical path: [see below](#also-noticed).

<a id="long-pole-map"></a>

## 🗺️ Long pole map

A **workflow** is one YAML file under `.github/workflows/`; a run of it executes its **jobs** in parallel (each on its own runner); each job runs its **steps** in sequence.

```text
Level 2 - inside Windows, steps run one after another:

   Run uv run --locked --no-default…  ██████████████████████      15s   45% ◀
   Run actions/checkout@de0fac2e450…  ██████████                   7s   21%
   Run astral-sh/setup-uv@cec208311…  ███████                      4s   13%
   Post Run actions/checkout@de0fac…  ███                          2s    6%
   Post Run astral-sh/setup-uv@cec2…  ██                           2s    4%
   Set up job                         █                            1s    3%
```

Each ◀ marks the blocker the next level opens. Long pole 1 below drills the marked step to its root cause and hand-off prompt.

<a id="pole-1"></a>

## 🟡 Long pole 1: `tests.yaml` ▸ `Windows` - 34s

**The slowest check a typical PR waits on.**

> **What a change here can buy (wall-clock):** up to **~8s** - it gates until it drops to the next concurrent check, `PyPy` (26s); below that the gate moves and further savings are runner-minutes, not wall-clock.

```text
Where the job's ~34s goes - every step, slowest first; they run in sequence and roughly add up to the job:

   Run uv run --locked --no-default…  ██████████████████████      15s       ◀
   Run actions/checkout@de0fac2e450…  ██████████                   7s
   Run astral-sh/setup-uv@cec208311…  ███████                      4s
   Post Run actions/checkout@de0fac…  ███                          2s
   Post Run astral-sh/setup-uv@cec2…  ██                           2s
   Set up job                         █                            1s
   …1 smaller steps (setup, cache, …  █                           ~1s

(no log-level detector fired, but a **structural catalog pattern** matched this pole - see the **structural root-cause** below; the dominant step is the addressable lever.)
```

**📐 Structural root-cause - OPT75 · The long pole's time is one addressable step - speed it up or move it off the PR path - `Windows`** - risk **MEDIUM**

A measured **structural** lever on the critical path (it IS this pole, so it's not repeated in the off-path appendix). It carries a risk profile - review the guardrail and rollout before shipping:

- **What ci-speedup measured:** critical-path check `Windows` (34s): dominant step `Run uv run --locked --no-default-groups --group dev tox run + 1 more other step` (other, 61% of job `Windows`)
- **Guardrail:** carry the guardrail of the routed lever (e.g. OPT70's full-suite fallback if the dominant step is a test being scoped); never present the decomposition as free
- **Rollout:** the routed lever's rollout; re-measure the pole's p50 after the dominant step is attacked - the next-largest step becomes the target
- **Failure mode:** the dominant-step remedy ranges from LOW (cache an install) to HIGH (scope a test/build, inheriting OPT70) - the candidate carries the risk of whichever specific lever its dominant category routes to
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt75--long-pole-optimize-or-relocate-the-dominant-step

#### 🤖 Prompt for your coding agent

```text
starslingdev/ci-speedup measured where the time goes below but does NOT prescribe the fix - a structural catalog pattern (OPT75) matched this pole (see the **structural root-cause** section above for the measured lever + its risk axis); the dominant step below is where that lever's time is spent.

REPO: pallets/flask (audited at commit 36e4a82)

THE GATE
- Workflow `tests.yaml`, job `Windows`.
- Slowest check a typical PR waits on: P50 34s.

WHERE THE TIME GOES
- The job's time is dominated by the `Run uv run --locked --no-default-groups --group dev tox run + 1 more other step` step: ~20s (61% of the job wall), from the sampled per-step decomposition (no single-run timeline was captured for this job).

STRUCTURAL CATALOG PATTERN MATCHED
- A structural catalog pattern (OPT75) matched this pole - see the **structural root-cause** section above for the measured lever, its risk / guardrail / rollout, and the catalog fix recipe. The step above is the load-bearing one that lever targets; open its log (the Audit link) to see exactly what inside it the lever reshapes.

WHAT'S ADDRESSABLE (wall-clock ceiling - don't over-promise)
- up to ~8s - it gates until it drops to the next concurrent check, `PyPy` (26s); below that the gate moves and further savings are runner-minutes, not wall-clock.

WHERE TO LOOK
- The `tests.yaml` workflow definition for the dominant step, and the tool/config it invokes (build tool, test runner, or install) - that's where its time is spent.

DELIVER & VERIFY
- A change that cuts the dominant step's wall time without dropping coverage; re-measure the step on a PR run to confirm the reduction.
```


<a id="pole-2"></a>

## 🟡 Long pole 2: `tests.yaml` ▸ `PyPy` - 26s

**Rarely the merge gate - the actual slowest check a PR waits on, on only 0/20 sampled PRs.** Present on 19/20 PRs, but a slower concurrent check almost always gates ahead of it, so its 26s is throughput/cost, not merge-wait. Speeding it helps only the PRs where it IS the pole - it won't move typical merge-wait.

```text
Level 2 - inside that one job, its steps run **one after another** (← 0:00 job start … 0:30 → ; `░` = time already elapsed, `█` = the step running) and sum to the job's **30s** wall time on this run - the run closest to the typical (P50) time. Because they're sequential, time cut from any step comes straight off the job's wall-clock (and off the merge wait, down to the next concurrent check):

   Run astral-sh/setup-uv@cec208311…  ░░█                          2s    7%
   Run uv run --locked --no-default…  ░░░░████████████████        22s   73%
   (+7 setup/cleanup steps of 2s or less not shown)

   (no log-level detector fired, but a **structural catalog pattern** matched this pole - see the **structural root-cause** below; the dominant step is the addressable lever.)
```

_The timeline and the per-step times above are from **one representative run** - the one whose duration is closest to the typical (P50) time, [run 28604968127](https://github.com/pallets/flask/actions/runs/28604968127)._

**🔗 Audit:** run [28604968127](https://github.com/pallets/flask/actions/runs/28604968127) → [the `PyPy` job](https://github.com/pallets/flask/actions/runs/28604968127/job/84822683597) - open the step to inspect its log directly (no known root-cause pattern matched, so there is no specific callout to search for).

**📐 Structural root-cause - OPT75 · The long pole's time is one addressable step - speed it up or move it off the PR path - `PyPy`** - risk **MEDIUM**

A measured **structural** lever on the critical path (it IS this pole, so it's not repeated in the off-path appendix). It carries a risk profile - review the guardrail and rollout before shipping:

- **What ci-speedup measured:** critical-path check `PyPy` (26s): dominant step `Run uv run --locked --no-default-groups --group dev tox run + 1 more other step` (other, 79% of job `PyPy`)
- **Guardrail:** carry the guardrail of the routed lever (e.g. OPT70's full-suite fallback if the dominant step is a test being scoped); never present the decomposition as free
- **Rollout:** the routed lever's rollout; re-measure the pole's p50 after the dominant step is attacked - the next-largest step becomes the target
- **Failure mode:** the dominant-step remedy ranges from LOW (cache an install) to HIGH (scope a test/build, inheriting OPT70) - the candidate carries the risk of whichever specific lever its dominant category routes to
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt75--long-pole-optimize-or-relocate-the-dominant-step

#### 🤖 Prompt for your coding agent

```text
starslingdev/ci-speedup measured where the time goes below but does NOT prescribe the fix - a structural catalog pattern (OPT75) matched this pole (see the **structural root-cause** section above for the measured lever + its risk axis); the dominant step below is where that lever's time is spent.

REPO: pallets/flask (audited at commit 36e4a82)

THE GATE
- Workflow `tests.yaml`, job `PyPy`.
- Rarely the merge pole - the actual slowest check a PR waits on, on only 0/20 sampled PRs (present on 19/20): P50 26s. A slower concurrent check usually gates ahead, so speeding it helps only the PRs where it IS the pole, not typical merge-wait.

WHERE THE TIME GOES (representative run 28604968127)
- The job's time is dominated by the `Run uv run --locked --no-default-groups --group dev tox run` step: ~22s (73% of the job wall, measured in the drilled run).

STRUCTURAL CATALOG PATTERN MATCHED
- A structural catalog pattern (OPT75) matched this pole - see the **structural root-cause** section above for the measured lever, its risk / guardrail / rollout, and the catalog fix recipe. The step above is the load-bearing one that lever targets; open its log (the Audit link) to see exactly what inside it the lever reshapes.

WHERE TO LOOK
- The `tests.yaml` workflow definition for the `Run uv run --locked --no-default-groups --group dev tox run` step, and the tool/config it invokes (build tool, test runner, or install) - that's where its time is spent.

DELIVER & VERIFY
- A change that cuts the `Run uv run --locked --no-default-groups --group dev tox run` step's wall time without dropping coverage; re-measure the step on a PR run to confirm the reduction.
```


<a id="pole-3"></a>

## 🟡 Long pole 3: `tests.yaml` ▸ `3.14t` - 24s

**Rarely the merge gate - the actual slowest check a PR waits on, on only 0/20 sampled PRs.** Present on 19/20 PRs, but a slower concurrent check almost always gates ahead of it, so its 24s is throughput/cost, not merge-wait. Speeding it helps only the PRs where it IS the pole - it won't move typical merge-wait.

```text
Where the job's ~24s goes - every step, slowest first; they run in sequence and roughly add up to the job:

   Run actions/setup-python@a309ff8…  ██████████████████████      10s       ◀
   Run uv run --locked --no-default…  █████████████                6s
   Run astral-sh/setup-uv@cec208311…  ████                         2s
   Set up job                         ██                           1s
   Run actions/checkout@de0fac2e450…  ██                           1s
   Post Run astral-sh/setup-uv@cec2…  ██                           1s

(no log-level detector fired, but a **structural catalog pattern** matched this pole - see the **structural root-cause** below; the dominant step is the addressable lever.)
```

**📐 Structural root-cause - OPT75 · The long pole's time is one addressable step - speed it up or move it off the PR path - `3.14t`** - risk **MEDIUM**

A measured **structural** lever on the critical path (it IS this pole, so it's not repeated in the off-path appendix). It carries a risk profile - review the guardrail and rollout before shipping:

- **What ci-speedup measured:** critical-path check `3.14t` (24s): dominant step `Run actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405` (install, 49% of job `3.14t`)
- **Guardrail:** carry the guardrail of the routed lever (e.g. OPT70's full-suite fallback if the dominant step is a test being scoped); never present the decomposition as free
- **Rollout:** the routed lever's rollout; re-measure the pole's p50 after the dominant step is attacked - the next-largest step becomes the target
- **Failure mode:** the dominant-step remedy ranges from LOW (cache an install) to HIGH (scope a test/build, inheriting OPT70) - the candidate carries the risk of whichever specific lever its dominant category routes to
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt75--long-pole-optimize-or-relocate-the-dominant-step

#### 🤖 Prompt for your coding agent

```text
starslingdev/ci-speedup measured where the time goes below but does NOT prescribe the fix - a structural catalog pattern (OPT75) matched this pole (see the **structural root-cause** section above for the measured lever + its risk axis); the dominant step below is where that lever's time is spent.

REPO: pallets/flask (audited at commit 36e4a82)

THE GATE
- Workflow `tests.yaml`, job `3.14t`.
- Rarely the merge pole - the actual slowest check a PR waits on, on only 0/20 sampled PRs (present on 19/20): P50 24s. A slower concurrent check usually gates ahead, so speeding it helps only the PRs where it IS the pole, not typical merge-wait.

WHERE THE TIME GOES
- The job's time is dominated by the `Run actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405` step: ~10s (49% of the job wall), from the sampled per-step decomposition (no single-run timeline was captured for this job).

STRUCTURAL CATALOG PATTERN MATCHED
- A structural catalog pattern (OPT75) matched this pole - see the **structural root-cause** section above for the measured lever, its risk / guardrail / rollout, and the catalog fix recipe. The step above is the load-bearing one that lever targets; open its log (the Audit link) to see exactly what inside it the lever reshapes.

WHERE TO LOOK
- The `tests.yaml` workflow definition for the dominant step, and the tool/config it invokes (build tool, test runner, or install) - that's where its time is spent.

DELIVER & VERIFY
- A change that cuts the dominant step's wall time without dropping coverage; re-measure the step on a PR run to confirm the reduction.
```


<a id="pole-4"></a>

## 🟡 Long pole 4: `tests.yaml` ▸ `Mac` - 20s

**Rarely the merge gate - the actual slowest check a PR waits on, on only 0/20 sampled PRs.** Present on 19/20 PRs, but a slower concurrent check almost always gates ahead of it, so its 20s is throughput/cost, not merge-wait. Speeding it helps only the PRs where it IS the pole - it won't move typical merge-wait.

```text
Where the job's ~20s goes - every step, slowest first; they run in sequence and roughly add up to the job:

   Run uv run --locked --no-default…  ██████████████████████       6s       ◀
   Run astral-sh/setup-uv@cec208311…  ████████████████             4s
   Post Run astral-sh/setup-uv@cec2…  ████████████                 3s
   Run actions/checkout@de0fac2e450…  ██████████                   2s
   Set up job                         ████████                     2s
   Post Run actions/checkout@de0fac…  ████                         1s
   …2 smaller steps (setup, cache, …  ████████                    ~2s

(no log-level detector fired, but a **structural catalog pattern** matched this pole - see the **structural root-cause** below; the dominant step is the addressable lever.)
```

**📐 Structural root-cause - OPT75 · The long pole's time is one addressable step - speed it up or move it off the PR path - `Mac`** - risk **MEDIUM**

A measured **structural** lever on the critical path (it IS this pole, so it's not repeated in the off-path appendix). It carries a risk profile - review the guardrail and rollout before shipping:

- **What ci-speedup measured:** critical-path check `Mac` (20s): dominant step `Run uv run --locked --no-default-groups --group dev tox run + 1 more other step` (other, 48% of job `Mac`)
- **Guardrail:** carry the guardrail of the routed lever (e.g. OPT70's full-suite fallback if the dominant step is a test being scoped); never present the decomposition as free
- **Rollout:** the routed lever's rollout; re-measure the pole's p50 after the dominant step is attacked - the next-largest step becomes the target
- **Failure mode:** the dominant-step remedy ranges from LOW (cache an install) to HIGH (scope a test/build, inheriting OPT70) - the candidate carries the risk of whichever specific lever its dominant category routes to
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt75--long-pole-optimize-or-relocate-the-dominant-step

#### 🤖 Prompt for your coding agent

```text
starslingdev/ci-speedup measured where the time goes below but does NOT prescribe the fix - a structural catalog pattern (OPT75) matched this pole (see the **structural root-cause** section above for the measured lever + its risk axis); the dominant step below is where that lever's time is spent.

REPO: pallets/flask (audited at commit 36e4a82)

THE GATE
- Workflow `tests.yaml`, job `Mac`.
- Rarely the merge pole - the actual slowest check a PR waits on, on only 0/20 sampled PRs (present on 19/20): P50 20s. A slower concurrent check usually gates ahead, so speeding it helps only the PRs where it IS the pole, not typical merge-wait.

WHERE THE TIME GOES
- The job's time is dominated by the `Run uv run --locked --no-default-groups --group dev tox run + 1 more other step` step: ~10s (48% of the job wall), from the sampled per-step decomposition (no single-run timeline was captured for this job).

STRUCTURAL CATALOG PATTERN MATCHED
- A structural catalog pattern (OPT75) matched this pole - see the **structural root-cause** section above for the measured lever, its risk / guardrail / rollout, and the catalog fix recipe. The step above is the load-bearing one that lever targets; open its log (the Audit link) to see exactly what inside it the lever reshapes.

WHERE TO LOOK
- The `tests.yaml` workflow definition for the dominant step, and the tool/config it invokes (build tool, test runner, or install) - that's where its time is spent.

DELIVER & VERIFY
- A change that cuts the dominant step's wall time without dropping coverage; re-measure the step on a PR run to confirm the reduction.
```


<a id="pole-5"></a>

## 🟡 Long pole 5: `pre-commit.yaml` ▸ `main` - 19s

**Rarely the merge gate - the actual slowest check a PR waits on, on only 1/20 sampled PRs.** Present on 20/20 PRs, but a slower concurrent check almost always gates ahead of it, so its 19s is throughput/cost, not merge-wait. Speeding it helps only the PRs where it IS the pole - it won't move typical merge-wait.

```text
Where the job's ~19s goes - every step, slowest first; they run in sequence and roughly add up to the job:

   Run uv run --locked --no-default…  ██████████████████████       9s       ◀
   Run astral-sh/setup-uv@cec208311…  ███████                      3s
   Run actions/cache@668228422ae6a0…  ████                         2s
   Set up job                         ██                           1s
   Run actions/checkout@de0fac2e450…  ██                           1s
   Post Run actions/checkout@de0fac…  ██                           1s
   …4 smaller steps (setup, cache, …  ██████████                  ~4s

(no log-level detector fired, but a **structural catalog pattern** matched this pole - see the **structural root-cause** below; the dominant step is the addressable lever.)
```

**📐 Structural root-cause - OPT75 · The long pole's time is one addressable step - speed it up or move it off the PR path - `main`** - risk **MEDIUM**

A measured **structural** lever on the critical path (it IS this pole, so it's not repeated in the off-path appendix). It carries a risk profile - review the guardrail and rollout before shipping:

- **What ci-speedup measured:** critical-path check `main` (19s): dominant step `Run uv run --locked --no-default-groups --group pre-commit pre-commit run --show-diff-on-failure --color=always --all-files + 1 more other step` (other, 58% of job `main`)
- **Guardrail:** carry the guardrail of the routed lever (e.g. OPT70's full-suite fallback if the dominant step is a test being scoped); never present the decomposition as free
- **Rollout:** the routed lever's rollout; re-measure the pole's p50 after the dominant step is attacked - the next-largest step becomes the target
- **Failure mode:** the dominant-step remedy ranges from LOW (cache an install) to HIGH (scope a test/build, inheriting OPT70) - the candidate carries the risk of whichever specific lever its dominant category routes to
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt75--long-pole-optimize-or-relocate-the-dominant-step

#### 🤖 Prompt for your coding agent

```text
starslingdev/ci-speedup measured where the time goes below but does NOT prescribe the fix - a structural catalog pattern (OPT75) matched this pole (see the **structural root-cause** section above for the measured lever + its risk axis); the dominant step below is where that lever's time is spent.

REPO: pallets/flask (audited at commit 36e4a82)

THE GATE
- Workflow `pre-commit.yaml`, job `main`.
- Rarely the merge pole - the actual slowest check a PR waits on, on only 1/20 sampled PRs (present on 20/20): P50 19s. A slower concurrent check usually gates ahead, so speeding it helps only the PRs where it IS the pole, not typical merge-wait.

WHERE THE TIME GOES
- The job's time is dominated by the `Run uv run --locked --no-default-groups --group pre-commit pre-commit run --show-diff-on-failure --color=always --all-files + 1 more other step` step: ~12s (58% of the job wall), from the sampled per-step decomposition (no single-run timeline was captured for this job).

STRUCTURAL CATALOG PATTERN MATCHED
- A structural catalog pattern (OPT75) matched this pole - see the **structural root-cause** section above for the measured lever, its risk / guardrail / rollout, and the catalog fix recipe. The step above is the load-bearing one that lever targets; open its log (the Audit link) to see exactly what inside it the lever reshapes.

WHERE TO LOOK
- The `pre-commit.yaml` workflow definition for the dominant step, and the tool/config it invokes (build tool, test runner, or install) - that's where its time is spent.

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
| .github/workflows/tests.yaml | Windows | windows-latest | all-events | success | latest | all-status | 27.953 | 44.460 | 8.800% |
| .github/workflows/pre-commit.yaml | main | ubuntu-latest | all-events | success | latest | all-status | 12.272 | 37.000 | 7.300% |
| .github/workflows/tests.yaml | PyPy | ubuntu-latest | all-events | success | latest | all-status | 19.941 | 36.000 | 7.100% |
| .github/workflows/tests.yaml | 3.14t | ubuntu-latest | all-events | success | latest | all-status | 14.859 | 36.000 | 7.100% |
| .github/workflows/tests.yaml | Mac | macos-latest | all-events | success | latest | all-status | 13.483 | 36.000 | 7.100% |
| .github/workflows/tests.yaml | typing | ubuntu-latest | all-events | success | latest | all-status | 12.635 | 36.000 | 7.100% |
| .github/workflows/tests.yaml | Minimum Versions | ubuntu-latest | all-events | success | latest | all-status | 11.294 | 36.000 | 7.100% |
| .github/workflows/tests.yaml | Development Versions | ubuntu-latest | all-events | success | latest | all-status | 11.259 | 36.000 | 7.100% |
| .github/workflows/tests.yaml | 3.14 | ubuntu-latest | all-events | success | latest | all-status | 10.588 | 36.000 | 7.100% |
| .github/workflows/tests.yaml | 3.13 | ubuntu-latest | all-events | success | latest | all-status | 10.306 | 36.000 | 7.100% |
| .github/workflows/tests.yaml | 3.12 | ubuntu-latest | all-events | success | latest | all-status | 9.917 | 36.000 | 7.100% |
| .github/workflows/tests.yaml | 3.10 | ubuntu-latest | all-events | success | latest | all-status | 9.141 | 36.000 | 7.100% |
| Total |  |  |  |  |  |  | 175.813 | 507.460 | 100.000% |
+6 more runner-minute rows hidden

> These findings cut wall-clock-neutral runner spend without touching your merge gate; each R-numbered finding carries a machine-derived proof it cannot slow a PR.
> **3 min/mo credited after de-overlap** (naive sum 3 min/mo; 1 neutral finding). All figures are runner-minutes; multiply by your runner's per-minute rate to get dollars.

<!-- ci-speedup:tier2-finding id=f4 pattern=OPT36 -->
<a id="r-1"></a>

## 🟢 Runner saving 1: `lock.yaml` - 3 min/mo

**The largest merge-safe runner-minute saving measured on this repo.**

| Workflow | Consecutive same-head_sha schedule runs | Mean compute/run | Credited runner-min/mo |
| --- | --- | --- | --- |
| `.github/workflows/lock.yaml` | 95 redundant run(s) in 5 group(s) | 0.1 job-min over 20 timed run(s) | ~3 |

_Schedule burn is counted only on event=schedule runs whose head_sha repeats consecutively, so the detector proves the workflow ran again without a code change. Basis: the count is from the all-status schedule slice; the per-run price is the mean of 20 successful schedule-event timed run(s). GUARDRAIL: confirm the current cadence is not an operational SLA before increasing the cron interval._

**💸 Bill root-cause - OPT36 · Cron Schedule Too Frequent** - risk **LOW**

- **What ci-speedup measured:** 95 scheduled run(s) in 5 consecutive same-head_sha group(s) re-ran without a code change in the sampled schedule slice (95% of 100 schedule run(s)); ~3 runner-min/mo of schedule-event compute (mean over 20 timed run(s); ×0.30 to the 30d volume (30 runs); 100-run recent slice (not a full 30d census)).
- **Why this can't slow your merge:** machine-derived proof: `non_pr_event` - `schedule` runs do not gate a PR merge (event=schedule subset only; consecutive same-head_sha schedule runs; schedule is not a developer PR/merge event).
- **Source block:** `runner_minute_spine` matched 1 row for `.github/workflows/lock.yaml`; current measured cost spine for those rows is 3.200 raw min/mo, 30.000 billable min/mo.
- **Guardrail:** Confirm the cron cadence is not an operational SLA; prefer widening the interval only for cleanup/triage/build jobs where delayed execution is acceptable.
- **Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt36--cron-schedule-too-frequent

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT36 - Cron Schedule Too Frequent.
Where: lock.yaml.
What ci-speedup saw: 95 scheduled run(s) in 5 consecutive same-head_sha group(s) re-ran without a code change in the sampled schedule slice (95% of 100 schedule run(s)); ~3 runner-min/mo of schedule-event compute (mean over 20 timed run(s); ×0.30 to the 30d volume (30 runs); 100-run recent slice (not a full 30d census)).
Saving: 3 min/mo of runner capacity - a bill/capacity reduction, not a merge-wait cut. Neutrality certificate: `non_pr_event` - `schedule` runs do not gate a PR merge (event=schedule subset only; consecutive same-head_sha schedule runs; schedule is not a developer PR/merge event). GUARDRAIL: confirm the current cadence is not an operational SLA before increasing the cron interval.

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt36--cron-schedule-too-frequent

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

---

<a id="also-noticed"></a>

## 🧹 Also noticed - residual hygiene

> These findings stay outside the wall-clock-neutral runner-minute section because they are modeled, uncertified, advisory-by-shape, missing source-spine backing, or below that section's measured admission gate. Most do **not** sit on the merge-gating critical path above, so fixing them removes little or no developer wall-clock - but they can still cut runner-minutes. **Expand any finding** for its locations, evidence, the catalog fix recipe, and a copy-paste agent prompt; exact per-occurrence lines + evidence also live in the findings JSON.

> ⚠️ _Approximate: computed across all workflows, but 1 capped workflow(s) still use the shallow 10-run job sample for finding/queue values; 1 runner-minute source workflow(s) still use a shallow 10-run cost-spine sample. Figures can shift run-to-run; re-run with `--shallow-runs 20` to confirm exact values._

<details>
<summary><strong>OPT32 - Missing `paths`/`paths-ignore` on Expensive Workflows</strong> · no bill saving · HIGH · 1 across 1 wf</summary>

**Where:** `publish.yaml:2` (build)
**Evidence:** workflow triggers on push but declares no `paths:`/`paths-ignore:` filter (the `on:` block below has no `paths:` key).
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt32--missing-paths-paths-ignore-on-expensive-workflows

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT32 - Missing `paths`/`paths-ignore` on Expensive Workflows.
Where: publish.yaml:2 (build).
What ci-speedup saw: workflow triggers on push but declares no `paths:`/`paths-ignore:` filter (the `on:` block below has no `paths:` key).
Saving: no measured runner-min saving - off the merge-gating critical path, so ~0 developer wall-clock (a cloud-bill cut, not a merge-wait cut).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt32--missing-paths-paths-ignore-on-expensive-workflows

CAVEAT - the required-status 'Pending' landmine: if ANY check this
workflow produces is a required status check, do NOT skip it via
paths:/branches: filters, [skip ci], or by removing/narrowing a trigger
event - a workflow that no longer fires leaves its
required check 'Pending' and the PR can never merge (official guidance:
do not use path/branch filtering on required workflows). The
documented-safe shape is a job-level `if:` - a skipped job reports
Success and satisfies the gate. The no-op twin-workflow trick (same
workflow AND job name, inverse filter) is a community-known workaround,
NOT in current GitHub docs. Treat required-status UNKNOWN as required:
if branch protection/rulesets are not readable, assume every check this
workflow produces may be required.

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

<details>
<summary><strong>OPT33 - No Draft PR Gating on Expensive Jobs</strong> · no bill saving · MEDIUM · 1 across 1 wf</summary>

**Where:** `tests.yaml:13` (tests)
**Evidence:** expensive job `tests` (matrix) runs on every PR that changes the workflow's filtered `paths:` including drafts - no `if: github.event.pull_request.draft == false` gate
**Catalog (background + fix recipe):** https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt33--no-draft-pr-gating-on-expensive-jobs

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the pattern below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.

Pattern: OPT33 - No Draft PR Gating on Expensive Jobs.
Where: tests.yaml:13 (tests).
What ci-speedup saw: expensive job `tests` (matrix) runs on every PR that changes the workflow's filtered `paths:` including drafts - no `if: github.event.pull_request.draft == false` gate
Saving: no measured runner-min saving - off the merge-gating critical path, so ~0 developer wall-clock (a cloud-bill cut, not a merge-wait cut).

Read the catalog entry (background, fix recipe, and guardrail):
  https://github.com/starslingdev/skills/blob/main/skills/ci-speedup/references/optimization-patterns.md#opt33--no-draft-pr-gating-on-expensive-jobs

CAVEAT - the required-status 'Pending' landmine: if ANY check this
workflow produces is a required status check, do NOT skip it via
paths:/branches: filters, [skip ci], or by removing/narrowing a trigger
event - a workflow that no longer fires leaves its
required check 'Pending' and the PR can never merge (official guidance:
do not use path/branch filtering on required workflows). The
documented-safe shape is a job-level `if:` - a skipped job reports
Success and satisfies the gate. The no-op twin-workflow trick (same
workflow AND job name, inverse filter) is a community-known workaround,
NOT in current GitHub docs. Treat required-status UNKNOWN as required:
if branch protection/rulesets are not readable, assume every check this
workflow produces may be required.

Do: confirm the pattern at each location above, recover the intent from git
history, and apply the catalog's fix recipe where it is safe. State the
failure mode and how you have guarded it before shipping.
```

</details>

## 🗄️ Data sources

> **Where this data comes from**
>
> - **Critical path + step P50:** the committed ci-speedup audit of `pallets/flask`, scanned **2026-07-21** - P50 over **45 runs / 126 jobs** across 5 workflows (latest runs at scan time).
> - **Data-collection cost:** **314 gh API call(s)** in ~51s - adaptive sampling - a 10-run shallow pass over every workflow, then 1 of 3 PR-gating pole candidate(s) deepened to 20 runs, plus 1 bill-pole workflow candidate(s) deepened to 20 runs for the runner-minute source block (the gate, drill-set, and floor are full-depth; other finding-level values may still rest on the shallow sample).
> - **Which checks gate (the critical-path ordering):** measured from **20/20 sampled PRs**.
> - ⚠️ **Required checks were unreadable** (no admin / branch protection 404), so 'gate' here means the **slowest check on a typical PR** (observed), not a *confirmed required* check. Slow checks that run on only a minority of PRs are shown as a footnote, not the headline.
> - **Step internals + cross-run checks (the per-pole drill-downs):** the pole jobs' raw logs, fetched **2026-07-21T16:10:17.038841+00:00** (newer than the critical-path audit above). Each drill-down is **one representative run** of that job - the one closest to its typical time (for a bimodal job, a representative of the slow mode the drill explains), linked + labelled per pole - and the **Cross-run check** validates the load-bearing magnitude (median + range) across several runs.

| Source | Coverage | Used for |
| --- | --- | --- |
| ci-speedup static scan (skill commit `3bb6e2e`, scripts tree `f978505`) | All `.github/workflows/*.yml` under the analyzed tree (36e4a82) | Static pattern detection (OPT1-OPT69 catalog) |
| gh runs/jobs API (timestamps) | 45 runs / 126 jobs sampled | Critical-path + per-step P50 |
| job logs | 1 job log(s) sampled | Step internals + cross-run magnitude (deeper levels) |
| workflow YAML | 5 from the analyzed checkout | `on:` triggers, matrix/shard axes, job timeouts (detector inputs) |

**Data freshness.** Analyzer ran at `2026-07-21T16:10:17.038841+00:00`; workflow YAML is read from the analyzed tree at commit `36e4a82`. Timing and activity counts reflect the sampled runs over a rolling 30-day window at scan time. 314 gh API queries were made.

> _The runner-minute / cost-spine figures in this report keep the full sample by design (they size total compute, not the critical path), so they still include the earlier configuration; a duration- or structure-changing edit (e.g. a shard split) blends both layouts._

_The concurrent checks (the Contents critical path) are P50 across sampled PRs. The per-step timeline + the drill are **one representative run** - the one closest to the P50 time - so they are absolute for that run, not P50. The **categorical cause** is stable across runs; where a **Cross-run check** is shown it gives the magnitude's median + range across several runs, so the single run's number isn't taken on faith. Per-step bars are scaled within each drill._

_The drill bars are plain-English labels for what's in the job log (e.g. a `DB migrations` bar is logged as `Total Migration Time:`). To verify any number, follow the pole's **🔗 Audit** link to the gating step, expand it, and search (Ctrl-F) for the verbatim strings the Audit line lists - GitHub anchors to the step, not an exact log line._

---

Generated by [StarSling](https://starsling.dev) 💫
