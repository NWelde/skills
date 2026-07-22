"""Pin the /ci-speedup-dogfood slash command's entry point to a workflow that exists.

The command is installed by copying the canonical body
(`maintainers/ci-speedup/workflows/ci-speedup-dogfood.command.md`) into the gitignored
`.claude/commands/` dir. That body launches the loop via
`workflow({ scriptPath: '<path>' }, orgs)`. When the workflow JS was relocated
(`skills/ci-speedup/workflows/` -> `maintainers/ci-speedup/workflows/`, #71), nothing caught
that a stale `scriptPath` would point at a now-missing file — so an invocation failed to
launch with no test going red. This pins every `scriptPath` the committed canonical body
declares to a file that actually exists and is a real JS workflow module, so the next
relocation that forgets to update the command fails CI instead of a user's run.

Paths are resolved repo-root-relative, matching how the `workflow({ scriptPath })` wrapper is
actually launched. The gitignored installed copy under `.claude/` can still drift from this
canonical body — that's outside the repo and uncheckable in CI; re-copy after changes.
"""

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMMAND_MD = (
    _REPO_ROOT / "maintainers" / "ci-speedup" / "workflows" / "ci-speedup-dogfood.command.md"
)

# `scriptPath: 'maintainers/ci-speedup/workflows/ci-speedup-dogfood.js'` — single or double
# quoted. Matches the `scriptPath:` ASSIGNMENT only, not the prose mention "`scriptPath` launch".
_SCRIPT_PATH_RE = re.compile(r"""scriptPath:\s*['"]([^'"]+)['"]""")


def _extract_script_paths() -> list[str]:
    assert _COMMAND_MD.exists(), f"missing canonical command body: {_COMMAND_MD}"
    paths = _SCRIPT_PATH_RE.findall(_COMMAND_MD.read_text())
    # >= 1, not == 1: the only thing that must never happen is ZERO matches (a launch line
    # reshaped past what the regex recognizes -> the guard would pass vacuously). A second
    # legitimate scriptPath must be validated, not rejected, so the count isn't frozen — every
    # declared path is checked individually by the tests below.
    assert paths, (
        f"found no `scriptPath:` assignment in {_COMMAND_MD.name} — the launch line changed "
        f"shape and this guard can no longer see it (it would otherwise pass vacuously)."
    )
    return paths


def test_command_script_paths_resolve_to_existing_workflows():
    for script_path in _extract_script_paths():
        target = _REPO_ROOT / script_path
        assert target.exists(), (
            f"the /ci-speedup-dogfood command's scriptPath '{script_path}' does not exist at "
            f"{target} — the workflow moved without updating the command body (the exact "
            f"staleness that broke a real run). Update the scriptPath in {_COMMAND_MD.name}."
        )
        # The workflow() launcher loads a JS module, so the target must be one. This also
        # excludes the markdown command body itself — it carries its own `export const meta`
        # launch wrapper and would otherwise satisfy the module check below.
        assert target.suffix == ".js", (
            f"scriptPath '{script_path}' is not a .js module — the workflow() launcher loads JS."
        )
        # Sanity-check it's a populated workflow module, not an empty or half-written file.
        # (`export const meta` is the workflow contract's required header, not a unique
        # fingerprint of THIS workflow — paired with the .js check above it rules out stubs.)
        assert "export const meta" in target.read_text(), (
            f"scriptPath '{script_path}' is a .js file but not a workflow module "
            f"(no `export const meta`) — looks empty or half-written."
        )


def test_command_does_not_point_at_the_old_relocated_path():
    # Backstop to the existence check above, with a sharper message: today a path under the
    # pre-relocation home also fails `.exists()` (the dir is gone), but this fires explicitly
    # if someone recreates that dir or otherwise reintroduces the old path.
    for script_path in _extract_script_paths():
        assert not script_path.startswith("skills/ci-speedup/workflows/"), (
            f"scriptPath '{script_path}' points at the pre-relocation path under skills/; the "
            f"loop infra now lives under maintainers/ci-speedup/workflows/ (kept out of installs)."
        )
