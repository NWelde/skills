# Security

## Reporting a vulnerability

Please report suspected security vulnerabilities through GitHub's **private
vulnerability reporting**: go to the **Security** tab of this repository and
choose **Report a vulnerability**. This opens a private advisory visible only to
the maintainers — please do not open a public issue for a security report.

Include enough detail to reproduce (affected script/version, inputs, and observed
vs expected behavior). We'll acknowledge your report and keep you updated as we
investigate.

## Data-handling model

`ci-speedup` is designed to run **locally, under your own GitHub credentials**,
and to keep your data on your machine.

- **Runs with your own `gh` auth.** The skill reads the audited repository's
  GitHub Actions run/job/log data and workflow YAML through a fixed set of
  **read-only, enumerated `gh` API calls**, using the `gh` CLI you have already
  authenticated. It uses no credentials of its own.
- **Never modifies your repo's contents, and never commits or pushes.** The
  critical path and the findings are derived in-process and stored **locally**:
  a `findings.json` (plus a raw drill-log bundle) written to a scratch path
  outside your checkout. The one file it can create in your working directory is
  the sanitized report (`ci-speedup-findings-report.md`), and only when you pick
  "Save the full report"; it is an untracked, generated file you can gitignore
  or delete. If you ask the skill to implement a fix, you review the change
  before anything is committed.
- **No telemetry — nothing is sent to StarSling.** The skill reports no run data,
  finding, or metric anywhere. Data leaves your machine in exactly two ways, both
  of them yours: the read-only `gh` calls to GitHub, and — only when a drilled
  pole matches no catalog detector — the job-log excerpt your own agent reads to
  write the gap-fill analysis. Nothing else is transmitted.
