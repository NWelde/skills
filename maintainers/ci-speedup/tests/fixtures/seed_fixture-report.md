# demo - why is the merge slow?

> **Bottom line.** A typical PR waits **4m 15s** for all checks to finish; the per-pole drill-downs below trace where that time goes.

## 📋 Contents

1. [`build`](#pole-1) - 4m 15s

> **Where this data comes from**
>
> - Critical path scanned **2026-05-29**.

<a id="pole-1"></a>

## Long pole 1: `ci.yml` ▸ build - 4m 15s

```text
Where the job's ~4m 15s goes - every step, slowest first.
```

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the root cause below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.
```

<a id="pole-2"></a>

## Long pole 2: `sdk-pr.yml` ▸ Run integration tests - 17m 20s

```text
Where the job's ~17m 20s goes - every step, slowest first.
```

#### 🤖 Prompt for your coding agent

```text
ci-speedup measured the root cause below but does NOT prescribe the fix -
investigate it in the repo and apply a safe change.
```

## 🗄️ Data sources

| Source | Coverage | Used for |
| --- | --- | --- |
| ci-speedup static scan (skill commit `0000000`) | all workflows | Static pattern detection |
