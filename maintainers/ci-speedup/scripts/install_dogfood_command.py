#!/usr/bin/env python3
"""(Re)install the /ci-speedup-dogfood slash command from its canonical body.

The committed canonical body lives at
`maintainers/ci-speedup/workflows/ci-speedup-dogfood.command.md`; the *installed*
command Claude Code actually runs lives at the gitignored
`.claude/commands/ci-speedup-dogfood.md`. Those two diverging silently is exactly
what broke a real run: the workflow JS was relocated, the canonical body was
updated, but the manually-copied installed copy kept pointing at the old path.

This makes the copy a single deterministic, idempotent command instead of a
hand operation: it strips the canonical body's leading `<!-- install -->` comment
(so the YAML frontmatter leads, as a slash command requires) and writes the result
to `.claude/commands/`. `--check` reports drift without writing (exit 1 if the
installed copy is missing or stale) so a maintainer can detect divergence locally —
CI cannot, since `.claude/` is gitignored and never in the repo.

    python3 maintainers/ci-speedup/scripts/install_dogfood_command.py          # (re)install
    python3 maintainers/ci-speedup/scripts/install_dogfood_command.py --check  # detect drift
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CANONICAL = (
    _REPO_ROOT / "maintainers" / "ci-speedup" / "workflows" / "ci-speedup-dogfood.command.md"
)
_INSTALLED = _REPO_ROOT / ".claude" / "commands" / "ci-speedup-dogfood.md"

# A single leading HTML comment block (the install note) plus the blank line after it.
_LEADING_COMMENT_RE = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)


def render_installed_body(canonical_text: str) -> str:
    """Transform the canonical command body into its installed form.

    Strips the leading install comment so the `---` frontmatter leads. Idempotent:
    a body with no leading comment (already-installed form) is returned unchanged
    apart from leading-blank-line normalization, so re-running never corrupts it.
    """
    body = _LEADING_COMMENT_RE.sub("", canonical_text, count=1).lstrip("\n")
    if not body.startswith("---"):
        raise ValueError(
            "canonical command body must have YAML frontmatter ('---') after its "
            "leading install comment; got:\n" + body[:80]
        )
    return body


def _render_from_disk() -> str:
    if not _CANONICAL.exists():
        raise FileNotFoundError(f"missing canonical command body: {_CANONICAL}")
    return render_installed_body(_CANONICAL.read_text())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="(Re)install the /ci-speedup-dogfood slash command.")
    ap.add_argument(
        "--check",
        action="store_true",
        help="report whether the installed copy is in sync; do not write. Exit 1 on drift.",
    )
    args = ap.parse_args(argv)
    rendered = _render_from_disk()

    if args.check:
        if not _INSTALLED.exists():
            print(f"DRIFT: not installed — {_INSTALLED} is missing. Run without --check to install.")
            return 1
        if _INSTALLED.read_text() != rendered:
            print(f"DRIFT: {_INSTALLED} differs from the canonical body. Run without --check to refresh.")
            return 1
        print(f"in sync: {_INSTALLED} matches the canonical body.")
        return 0

    _INSTALLED.parent.mkdir(parents=True, exist_ok=True)
    existed = _INSTALLED.exists()
    _INSTALLED.write_text(rendered)
    print(f"{'refreshed' if existed else 'installed'}: {_INSTALLED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
