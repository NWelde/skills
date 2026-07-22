<!-- Canonical body for the /ci-speedup-dogfood slash command. `.claude/` is gitignored, so
     install/refresh the local copy with the deterministic installer (it strips this comment
     so the frontmatter leads) rather than copying by hand — a hand-copy is what drifted before:
       python3 maintainers/ci-speedup/scripts/install_dogfood_command.py          # (re)install
       python3 maintainers/ci-speedup/scripts/install_dogfood_command.py --check  # detect drift -->
---
description: Dogfood ci-speedup — run the real skill on each org's top repo, open PRs for any skill bugs
---

Run the ci-speedup dogfood loop on these orgs: **$ARGUMENTS** (GitHub org slugs, space/comma separated). If empty, ask me for the list. A `--force` token (also `--fresh` / `-f`) re-runs every org from scratch; without it, an org with a complete prior run resumes (so a partial-throttle re-run only re-does the orgs that failed).

**Speed modes (opt-in tokens):** `--audit-only` (alias `--no-fix`) stops after Run + audit — it reports the bugs + grader seeds found but SKIPS the slow Fix + integrate tail (per-bug `effort:high` worktree agents + the consolidated PR). Use it for a fast detection / smoke run. `--fast` implies `--audit-only` AND samples a smaller window (`run.py --target 5` instead of 10) for a quicker, lower-fidelity skill pass. Drop the token to get the full find → fix → PR loop.

**COST PREFLIGHT (mandatory — state the number BEFORE launching):** tell the operator the expected token cost and get their go-ahead first. Measured anchors: a 6-org `--force --audit-only` sweep cost **~990k output tokens** (round 2, 2026-07-16) — budget **~165k per org** for detection; the full fix tail adds roughly **100–250k per drafted bug** (fix agent + 2-reviewer panel) plus one integrator agent. The 2026-07-16 incident burned **3.5M tokens** because nothing stated a number or enforced a ceiling — both are now mandatory. Kill criteria while it runs: kill the run if spend crosses the stated estimate by ~50%, if a single agent is visibly stuck (no progress across two checks), or if the operator says stop; the workflow's own ceiling (below) is the mechanical backstop, not a substitute for watching.

**Hard caps (on by default):** `--token-budget=<N>` — a mechanical output-token ceiling (default **2,000,000**) that bounds **THIS RUN's own spend**, checked between every chunk/stage. The workflow snapshots the harness's session-cumulative token pool once at launch and gates on the delta since, so the ceiling governs only what this run adds — the session's lifetime pool (which never resets across turns) is irrelevant, and a fresh run always starts regardless of what earlier turns spent. When crossed, nothing new is scheduled, completed work is returned, and every skipped unit is marked loudly (errored org rows / `needs_human` fix rows with any already-drafted patch preserved) — re-run to resume, or raise the flag deliberately for a bigger sweep. The result's `token_budget` reports both `run_spent_output_tokens` (the governed delta) and `session_spent_output_tokens` (the raw pool, for context). `--max-fixes=<N>` — at most N fix agents per run (default **4**); excess bugs are held as explicit `max_fixes_capped` rows for the next run. Both accept only the single-token `=`-form (`--token-budget=1500000`); an unknown or two-token flag form throws instead of being scouted as an org. Every subagent is pinned `model: 'opus'` (session-model inheritance is a footgun — a cheaper session model would silently degrade the audit).

Launch the committed workflow, forwarding the parsed orgs via an inline `workflow()` wrapper (a direct `scriptPath` launch doesn't reliably thread top-level `args`):

```js
export const meta = { name: 'ci-speedup-dogfood-launch', description: 'forward orgs to the dogfood workflow' }
const orgs = "$ARGUMENTS".split(/[\s,]+/).filter(Boolean)   // split on spaces/commas (any --force token is forwarded as-is; the workflow parses it)
return await workflow({ scriptPath: 'maintainers/ci-speedup/workflows/ci-speedup-dogfood.js' }, orgs)
```

It runs the **real** ci-speedup skill on each org's top public repo (full SKILL.md flow, including the phase-4a gap-fill), audits each run for bugs in the skill (an LLM audit **plus** a deterministic structured-grader seed pass via `scripts/grader_seeds.py`), drafts a fix patch per distinct bug, and integrates all clean patches into **one consolidated PR** (one review surface; duplicate/conflicting fixes are reconciled at integration, one commit per fix; never merges). When it returns, report the audited repos, the bugs found, the **consolidated PR** (`consolidated_pr`), how many fixes were `integrated`, any `not_integrated` (with reasons), and (if any) the `resumed` orgs skipped from a prior run.

In an **`--audit-only` / `--fast`** run the result instead carries `mode`, the audited repos, and `bugs` (LLM-audit bugs + grader seeds), with **no Fix/PR fields** — report the bugs found + the `note` that fixes were skipped (re-run without the token to draft fixes).
