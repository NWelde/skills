"""Pin the /ci-speedup-dogfood installer's transform so a refresh can't corrupt the command.

`install_dogfood_command.render_installed_body` turns the committed canonical body into the
form written to the gitignored `.claude/commands/`. These tests exercise that transform purely
(no `.claude/` needed, so CI runs them): the frontmatter must lead, the install comment must be
gone, the launch `scriptPath` must survive intact, and re-running must be idempotent. Together
with `test_dogfood_command_integrity.py` (which pins the canonical `scriptPath` itself), this
makes install a deterministic, tested step instead of the hand-copy that previously drifted.
"""

import re

import install_dogfood_command as inst

_SCRIPT_PATH_RE = re.compile(r"""scriptPath:\s*['"]([^'"]+)['"]""")


def _canonical_text() -> str:
    return inst._CANONICAL.read_text()


def test_installed_body_leads_with_frontmatter_and_drops_install_comment():
    rendered = inst.render_installed_body(_canonical_text())
    # A slash command requires its YAML frontmatter first — the canonical body's leading
    # `<!-- install note -->` must be stripped, or Claude Code won't parse the command.
    assert rendered.startswith("---"), "installed body must lead with `---` frontmatter"
    assert "<!--" not in rendered.split("\n", 1)[0], "leading install comment must be stripped"


def test_installed_body_preserves_the_launch_script_path():
    canonical_paths = _SCRIPT_PATH_RE.findall(_canonical_text())
    rendered_paths = _SCRIPT_PATH_RE.findall(inst.render_installed_body(_canonical_text()))
    # The whole point of the guard: the installed copy launches the SAME workflow path as the
    # committed canonical body — the transform must not alter or drop it.
    assert rendered_paths == canonical_paths, (
        f"scriptPath changed across install transform: canonical {canonical_paths} "
        f"-> rendered {rendered_paths}"
    )
    assert rendered_paths, "canonical body must declare at least one scriptPath"


def test_render_is_idempotent():
    once = inst.render_installed_body(_canonical_text())
    # Re-rendering the already-installed form (no leading comment) must be a no-op, so a
    # maintainer re-running the installer never progressively mangles the file.
    assert inst.render_installed_body(once) == once


def test_render_rejects_a_body_with_no_frontmatter():
    # If the canonical body ever loses its frontmatter, fail loudly rather than install a
    # command Claude Code can't parse.
    try:
        inst.render_installed_body("<!-- just a comment -->\n\nno frontmatter here\n")
    except ValueError:
        return
    raise AssertionError("render_installed_body must raise when frontmatter is missing")
