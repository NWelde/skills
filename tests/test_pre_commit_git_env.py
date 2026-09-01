"""Git-addressing-environment invariant for ``.githooks/pre-commit`` (issue #14).

``git commit`` exports its repo-addressing environment — ``GIT_DIR`` and
``GIT_INDEX_FILE`` — to every hook it launches, and every child of that hook
inherits them. From a LINKED WORKTREE they are ABSOLUTE paths into the main
repo's ``.git``, and they OUTRANK both a subprocess's ``cwd`` and ``git -C``. The
pre-commit hook runs the full pytest suite, so a fixture test doing ``git init``
/ ``git add`` / ``git commit`` inside its ``tmp_path`` executes against the real
repository's metadata instead. The 2026-07-30 incident is what that looks like in
practice: HEAD reset, the index truncated to a single entry, fixture ``init`` /
``base`` commits landing on real refs, and ``core.bare true`` written into the
developer checkout. (From the main worktree git exports ``GIT_INDEX_FILE`` as the
relative ``.git/index``, which resolves harmlessly inside each test's own cwd —
which is why only worktree users were ever bitten.)

The repo-root ``conftest.py`` already scrubs these at pytest import time (PR #18,
red-proved by ``tests/test_repo_guards.py``). That is the last line of defense,
not the first, and it defends exactly one thing: a pytest process that actually
loaded that conftest. The hook is the layer where the variables ENTER the
process tree, so it is the layer that should drop them — one ``unset`` there
covers pytest, anything pytest shells out to, and anything else the hook ever
grows, including a runner arm that reaches the suite without the root conftest.

**Why the boundary is the first git OR pytest statement, not just pytest.** Not
because the hook's own ``git rev-parse --show-toplevel`` is at risk — measured,
it answers with the cwd's worktree whether or not ``GIT_DIR`` is inherited, since
git does not export ``GIT_WORK_TREE``. The reason is that "unset before anything
touches git" is a property that stays true as the hook grows, while "unset before
pytest" has to be re-argued every time a line is added above it. Requiring the
scrub at the top leaves no window to reason about, and costs a line.

**What "unconditionally unset" has to mean.** An earlier version of this guard
checked only that the *word* ``unset`` led a statement somewhere above the
boundary, at what it believed was ``if``-depth 0. Its depth counter never
incremented — it peeled ``if`` off as a leading keyword before looking for it —
so *every* construct below read as top level, and each of these passed while
leaking the whole environment:

* ``if [ -n "$SCRUB" ]; then unset GIT_…; fi`` — one arm only
* ``while false; do unset GIT_…; done`` / the same in a ``for`` or ``case``
* ``scrub() { unset GIT_…; }`` that is never called
* ``[ -n "$NOPE" ] && unset GIT_…`` / ``true || unset GIT_…``
* ``unset GIT_… &`` and ``unset GIT_… | cat`` — subshells; the parent keeps them
* ``unset GIT_…`` followed by ``export GIT_DIR=…``
* a here-doc whose body merely contains the text

So the scan now models real block structure with a stack (``if``/``fi``,
``while``/``until``/``for``/``select``/``do``…``done``, ``case``/``esac``,
``( )`` subshells, ``{ }`` groups and function bodies), tracks the depth of the
statement's *command word* rather than the line, records the separators around
each statement so a conditional or backgrounded ``unset`` is not mistaken for an
unconditional one, skips here-doc bodies, and revokes any variable that is
re-assigned or re-exported before the boundary. Every bullet above is a negative
control.

**Why the required variable set is read out of ``conftest.py``.** Two places in
this repo now know which variables are dangerous, and a list duplicated by hand
drifts: someone hardens the conftest against ``GIT_COMMON_DIR``, the hook never
learns about it, and the outer layer silently protects less than the inner one.
Parsing the conftest's scrub tuple and requiring the hook to cover it makes that
drift a red test instead of a quiet asymmetry.

**Why the controls do not use that parsed set.** They are built from ``_CANON``,
a literal list in this file, and a separate test asserts ``_CANON`` equals what
``conftest.py`` scrubs. Deriving the controls from the parsed set instead makes
them self-referential: weaken the conftest and the "known bad" fixtures weaken in
lockstep, so the whole file stays green while the invariant it guards shrinks.

**Why this parses rather than greps.** ``assert "unset GIT_DIR" in text`` is
satisfied by the word appearing in a comment, by an ``unset`` that runs inside
one dispatch arm and not the others, and by one placed after pytest has already
run. Each of those is exactly as broken as no unset at all, and each is a
negative control below. The parser is fail-closed in the same way as
``tests/test_pre_commit_hook.py``: shell it cannot model is reported as a
violation, never skipped.
"""
from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path
from typing import NamedTuple

import pytest

_REPO = Path(__file__).resolve().parents[1]
_HOOK = _REPO / ".githooks" / "pre-commit"
_CONFTEST = _REPO / "conftest.py"

# The canonical dangerous set, written out literally so the negative controls
# below do not depend on the very parse they are meant to red-prove.
# ``test_conftest_scrub_matches_the_canonical_set`` pins it to conftest.py.
_CANON = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CONFIG_PARAMETERS",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_NAMESPACE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_WORK_TREE",
)

# Any statement that talks to git or runs the suite. Matched per STATEMENT on
# comment-stripped lines, and deliberately over-eager: an extra hit only moves
# the boundary EARLIER, which makes the requirement stricter, never laxer.
_BOUNDARY = re.compile(r"\b(git|pytest)\b")

# Separators, by what they mean for the statement that FOLLOWS (or precedes) them.
_SEQ_SEPS = frozenset({";", ";;", ";&", ";;&"})
_COND_SEPS = frozenset({"&&", "||"})          # the next statement may not run
_ASYNC_SEPS = frozenset({"&", "|", "|&"})     # subshell: env changes don't stick
_SEPS = _SEQ_SEPS | _COND_SEPS | _ASYNC_SEPS

# Words peeled off before identifying a statement's command word. These affect
# identification ONLY — block depth is tracked separately by _walk, so listing
# `if` here can no longer blind the depth counter (the original bug).
_LEADING_NOISE = frozenset({"if", "elif", "else", "then", "do", "while", "until",
                            "for", "select", "case", "!", "time", "(", "{", "[["})

# Blocks whose bodies are NOT unconditional top-level code.
_BLOCK_OPEN = {"if": "if", "while": "loop", "until": "loop", "for": "loop",
               "select": "loop", "case": "case", "(": "subshell", "{": "group"}
_BLOCK_CLOSE = {"fi": "if", "done": "loop", "esac": "case",
                ")": "subshell", "}": "group"}

# A `{ … }` group is the one block that neither isolates the environment (unlike
# a `( … )` subshell) nor gates execution (unlike `if`/`for`/`case`): it always
# runs, in the current shell. So it does not count toward the depth that decides
# "unconditional" — but a FUNCTION body, which happens to be spelled with the
# same braces, does, because defining it is not calling it.
_ENV_TRANSPARENT = frozenset({"group"})

# Commands whose effect on the environment the guard cannot see. Before the
# boundary these are reported, never ignored: `source`/`eval` can re-introduce
# exactly the variables the unset just dropped, and `trap` defers its body past
# every statement this guard is ordering things against.
_OPAQUE = frozenset({"source", ".", "eval", "exec", "trap", "bash", "sh", "zsh",
                     "dash", "env", "xargs", "nohup", "timeout"})

_HEREDOC = re.compile(r"<<-?(?!<)\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?")
_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _depth(stack: list[str]) -> int:
    """How many blocks on the stack can stop a statement from running (or can
    keep its ``unset`` from reaching the hook's own environment)."""
    return sum(1 for kind in stack if kind not in _ENV_TRANSPARENT)


class _Stmt(NamedTuple):
    """One shell statement, with everything needed to judge whether it runs
    unconditionally in the hook's top-level flow."""
    tokens: list[str]
    depth: int          # block depth AT the command word, not at the line
    prev_sep: str | None
    next_sep: str | None


def _strip(raw: str) -> str:
    """Whitespace-stripped line, or "" if the whole line is a comment. Never a
    partial strip: a ``#`` inside a quoted echo is not a comment, and cutting
    there would change what the checker sees."""
    line = raw.strip()
    return "" if line.startswith("#") else line


def _tokenize(line: str) -> list[str] | None:
    """The line's tokens, or None if it is not something we can tokenize."""
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:              # unbalanced quotes — not a command we model
        return None


def _words(tokens: list[str]) -> list[str]:
    """A statement's tokens with leading shell keywords/structure peeled off."""
    out = list(tokens)
    while out and out[0] in _LEADING_NOISE:
        out.pop(0)
    return out


def _unset_vars(stmt: _Stmt) -> set[str]:
    """The variables an ``unset`` statement clears — {} if it isn't one.

    ``unset`` must be the statement's leading command word, not merely a token
    somewhere on the line: an unquoted ``echo you should unset GIT_DIR first``
    tokenizes to a bare ``unset`` too, and a membership test cannot tell that
    apart from the real thing.
    """
    words = _words(stmt.tokens)
    if not words or words[0] != "unset":
        return set()
    # `unset -v FOO` / `unset -f FOO` — skip flags, keep names. A name that is
    # not a literal (`unset $VARS`) is kept verbatim and simply won't match a
    # required name, so indirection fails the invariant rather than passing it.
    return {w for w in words[1:] if not w.startswith("-")}


def _assigned_vars(stmt: _Stmt) -> set[str]:
    """Names this statement puts BACK into the environment.

    Covers ``FOO=bar``, ``export FOO=bar``, ``export FOO``, and
    ``declare/typeset -x FOO=bar``. Deliberately blind to depth and to
    conditionality: a re-assignment that only *might* run is still a reason to
    stop calling the earlier unset effective.
    """
    words = _words(stmt.tokens)
    if not words:
        return set()
    names: set[str] = set()
    scan = words
    if words[0] in ("export", "declare", "typeset", "local", "readonly"):
        scan = words[1:]
    elif words[0] == "unset":
        return set()
    for tok in scan:
        if tok.startswith("-"):
            continue
        m = _ASSIGN.match(tok)
        if m:
            names.add(m.group(1))
        elif words[0] in ("export", "declare", "typeset", "readonly") and \
                re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tok):
            names.add(tok)
    return names


def _walk(tokens: list[str], stack: list[str],
          problems: list[str], lineno: int) -> list[_Stmt]:
    """Split one line's tokens into statements, maintaining the block ``stack``.

    ``stack`` is carried ACROSS lines by the caller, which is the whole point:
    ``while false; do`` on one line and ``unset GIT_DIR`` on the next must be
    seen as body, not as top level. Each statement records the depth at its own
    command word, so ``( unset GIT_DIR )`` — where the subshell opens inside the
    statement — is depth 1, not depth 0.
    """
    stmts: list[_Stmt] = []
    cur: list[str] = []
    cur_depth: int | None = None
    prev_sep: str | None = None

    def close(sep: str | None) -> None:
        nonlocal cur, cur_depth, prev_sep
        if cur:
            stmts.append(_Stmt(cur, cur_depth if cur_depth is not None else _depth(stack),
                               prev_sep, sep))
        cur, cur_depth = [], None
        prev_sep = sep

    for tok in tokens:
        if tok in _SEPS:
            close(tok)
            continue
        if tok in _BLOCK_OPEN:
            kind = _BLOCK_OPEN[tok]
            if tok == "{" and "()" in cur:
                kind = "function"      # `name() {` — a definition, not a call
            cur.append(tok)
            stack.append(kind)
            continue
        if tok in _BLOCK_CLOSE:
            kind = _BLOCK_CLOSE[tok]
            if tok == "}" and stack and stack[-1] == "function":
                kind = "function"
            # Inside a `case`, a bare `)` terminates an arm PATTERN — it is not
            # a subshell close. Without this the arm would drive depth negative
            # and every later statement would read as top level.
            if kind == "subshell" and stack and stack[-1] == "case":
                cur.append(tok)
                continue
            if not stack or stack[-1] != kind:
                problems.append(
                    f"line {lineno}: `{tok}` closes a `{kind}` block that was "
                    f"never opened (stack={stack or 'empty'}); the guard cannot "
                    f"tell top-level code from block bodies in this hook")
                stack.clear()
            else:
                stack.pop()
            cur.append(tok)
            continue
        if tok == "()":                  # `name() {` — the function's arg list
            cur.append(tok)
            continue
        if cur_depth is None and tok not in _LEADING_NOISE:
            cur_depth = _depth(stack)
        cur.append(tok)
    close(None)
    return stmts


def _scan(hook_text: str) -> tuple[set[str], int | None, list[str]]:
    """Walk the hook once, stopping at the first git/pytest statement.

    Returns (variables unconditionally cleared ahead of the boundary, the
    boundary line index, unmodellable constructs). "Unconditionally" means: at
    block depth 0, not gated behind ``&&``/``||``, not run in a subshell via
    ``&`` or a pipeline, and not re-assigned again before the boundary.

    The walk STOPS at the boundary rather than reading on. An earlier version
    kept scanning, so an ``unset`` sitting after the first git call still landed
    in the returned set and the ordering half of the invariant never fired.
    """
    unset_before: set[str] = set()
    boundary: int | None = None
    problems: list[str] = []
    stack: list[str] = []
    heredoc: str | None = None

    for i, raw in enumerate(hook_text.splitlines()):
        if heredoc is not None:
            # Here-doc body: inert text, never executed code. The delimiter may
            # be indented when the operator was `<<-`.
            if raw.strip() == heredoc:
                heredoc = None
            continue

        line = _strip(raw)
        if not line:
            continue
        if line.endswith("\\"):
            problems.append(
                f"line {i}: a line continuation splits a command across lines; "
                f"the guard models one command per line — keep it on one line: {line}")
            continue

        tokens = _tokenize(line)
        if tokens is None:
            problems.append(
                f"line {i}: unbalanced quoting the guard cannot tokenize: {line}")
            continue

        if "if" in tokens and "fi" in tokens:
            problems.append(
                f"line {i}: one-line `if …; then …; fi` — the guard models "
                f"multi-line conditionals only; write it out: {line}")

        for stmt in _walk(tokens, stack, problems, i):
            # Revocation first: `export GIT_DIR=…/.git` both puts the variable
            # back AND trips the boundary regex on its own path, so judging the
            # boundary first would drop the revocation on the floor.
            unset_before -= _assigned_vars(stmt)

            text = " ".join(stmt.tokens)
            if _BOUNDARY.search(text):
                boundary = i
                if stmt.depth > 0:
                    problems.append(
                        f"line {i}: the first git/pytest statement runs inside a "
                        f"block, not in top-level flow; the guard cannot order "
                        f"the scrub against it: {text}")
                break

            words = _words(stmt.tokens)
            if words and words[0] in _OPAQUE:
                problems.append(
                    f"line {i}: `{words[0]}` runs code the guard cannot inspect "
                    f"before the scrub boundary; it may re-introduce the very "
                    f"variables the unset dropped: {text}")

            unconditional = (
                stmt.depth == 0
                and stmt.prev_sep not in _COND_SEPS
                and stmt.prev_sep not in _ASYNC_SEPS
                and stmt.next_sep not in _ASYNC_SEPS
            )
            if unconditional:
                unset_before |= _unset_vars(stmt)

        if boundary is not None:
            break

        # A here-doc opened on this line swallows the following lines. Detected
        # on the raw text: `<<` reaches the tokenizer as a bare operator, so the
        # delimiter would otherwise read as an ordinary argument and its body as
        # executable code.
        m = _HEREDOC.search(line)
        if m:
            heredoc = m.group(1)

    if boundary is None:
        if stack:
            problems.append(
                f"unclosed shell block(s) {stack} at end of hook; the guard cannot "
                f"tell top-level code from block bodies")
        if heredoc is not None:
            problems.append(
                f"here-doc opened with delimiter {heredoc!r} is never closed")
    return unset_before, boundary, problems


def _required_vars() -> set[str]:
    """The variables ``conftest.py``'s Guard 1 scrubs, read out of its AST.

    Located structurally — a MODULE-LEVEL ``for`` over a literal sequence of
    ``GIT_*`` strings whose body actually removes the loop variable from
    ``os.environ`` — rather than by name or line number, so the guard survives
    the loop being renamed or moved but fails loudly if it is deleted, gutted,
    or shadowed by a decoy.

    Module-level is enforced by walking ``tree.body`` rather than ``ast.walk``:
    a matching loop buried in a helper function is not Guard 1 and must not be
    mistaken for it. The body check matters just as much — a loop whose
    ``os.environ.pop`` has been replaced by ``pass`` still *names* every
    variable while scrubbing none of them.
    """
    tree = ast.parse(_CONFTEST.read_text(encoding="utf-8"))

    def scrubs(node: ast.For) -> bool:
        """True iff the body removes the loop variable from os.environ."""
        target = node.target.id if isinstance(node.target, ast.Name) else None
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                fn = sub.func
                if (isinstance(fn, ast.Attribute) and fn.attr == "pop"
                        and isinstance(fn.value, ast.Attribute)
                        and fn.value.attr == "environ"
                        and sub.args
                        and isinstance(sub.args[0], ast.Name)
                        and sub.args[0].id == target):
                    return True
            if isinstance(sub, ast.Delete):
                for tgt in sub.targets:
                    if (isinstance(tgt, ast.Subscript)
                            and isinstance(tgt.value, ast.Attribute)
                            and tgt.value.attr == "environ"):
                        return True
        return False

    matches: list[set[str]] = []
    for node in tree.body:                       # MODULE LEVEL ONLY
        if not isinstance(node, ast.For):
            continue
        if not isinstance(node.iter, (ast.Tuple, ast.List)):
            continue
        elts = node.iter.elts
        names = [e.value for e in elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if len(names) != len(elts) or not names:
            continue
        if not all(n.startswith("GIT_") for n in names):
            continue
        if not scrubs(node):
            raise AssertionError(
                f"conftest.py has a module-level loop over {sorted(names)} but its "
                "body no longer removes the variable from os.environ — Guard 1 "
                "names the dangerous variables while scrubbing none of them.")
        matches.append(set(names))

    if len(matches) > 1:
        raise AssertionError(
            f"conftest.py has {len(matches)} module-level GIT_* scrub loops "
            f"({[sorted(m) for m in matches]}); this guard cannot tell which one "
            "is Guard 1. Collapse them into one.")
    if not matches:
        raise AssertionError(
            "conftest.py no longer contains a module-level loop over a literal list "
            "of GIT_* names that pops each from os.environ — Guard 1 (the "
            "import-time scrub) appears to be gone. That guard is the last line of "
            "defense for the 2026-07-30 incident; restore it before relaxing this "
            "test."
        )
    return matches[0]


def _violations(hook_text: str, required: set[str]) -> list[str]:
    """Every reason this hook text fails the invariant. Empty list == compliant."""
    unset_before, boundary, problems = _scan(hook_text)

    if boundary is None:
        problems.append(
            "the hook never invokes git or pytest — if the dispatch moved, this "
            "guard can no longer see the thing it is ordering the unset against")
        return problems

    missing = sorted(required - unset_before)
    if missing:
        problems.append(
            f"the hook does not unconditionally unset {missing} before its first "
            f"git/pytest statement (line {boundary}). git exports these to hooks "
            "as absolute paths and they outrank both `cwd` and `git -C`, so every "
            "fixture test's git subprocess — and the hook's own "
            "`rev-parse --show-toplevel` — is aimed at the real repository.")
    return problems


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------

def test_hook_scrubs_git_addressing_env_before_anything_uses_git():
    assert _violations(_HOOK.read_text(encoding="utf-8"), _required_vars()) == []


def test_hook_covers_every_variable_conftest_scrubs():
    """Drift guard: the outer layer must never protect less than the inner one."""
    required = _required_vars()
    unset_before, _, _ = _scan(_HOOK.read_text(encoding="utf-8"))
    assert required <= unset_before, (
        f"conftest.py scrubs {sorted(required)} but the hook only unsets "
        f"{sorted(unset_before)}; the two lists have drifted apart. Add the "
        f"missing names to the hook's `unset`.")


def test_conftest_scrub_matches_the_canonical_set():
    """Pins the literal ``_CANON`` used to build every negative control below to
    what ``conftest.py`` actually scrubs.

    Without this the controls are self-referential: shrink Guard 1's tuple and
    the "known bad" fixtures shrink with it, so a hook that stopped protecting
    six of seven variables would still be rejected only for the one that
    remained — and the file would stay green while the invariant collapsed.
    """
    assert _required_vars() == set(_CANON), (
        "conftest.py's scrub set and this file's _CANON have diverged; update "
        "_CANON deliberately (and check the hook's `unset` too) rather than "
        "letting the negative controls track the change silently.")


# ---------------------------------------------------------------------------
# Negative controls — proof the checker above has teeth
# ---------------------------------------------------------------------------

_ALL = " ".join(sorted(_CANON))

_GOOD = f"""#!/bin/bash
echo "Running tests..."
unset {_ALL}
cd "$(git rev-parse --show-toplevel)" || exit 1
if command -v uvx &> /dev/null; then
    uvx --with pyyaml pytest -v
else
    python3 -m pytest -v
fi
"""

# The hook as it stood before issue #14: no scrub at all.
_NO_UNSET = _GOOD.replace(f"unset {_ALL}\n", "")

# The scrub exists but runs after the damage is possible — the hook's own
# rev-parse already resolved against the inherited GIT_DIR.
_UNSET_AFTER_BOUNDARY = f"""#!/bin/bash
cd "$(git rev-parse --show-toplevel)" || exit 1
unset {_ALL}
python3 -m pytest -v
"""

# Only one dispatch arm is protected; the others still inherit. Note this sits
# BEFORE the first git call — the earlier version of this control had its unset
# after the boundary, so it was rejected for the wrong reason and the depth
# logic went untested.
_UNSET_IN_ONE_ARM = f"""#!/bin/bash
echo "Running tests..."
if [ -n "$SCRUB" ]; then
    unset {_ALL}
fi
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# The same defect written as a one-liner.
_UNSET_IN_ONE_LINE_IF = f"""#!/bin/bash
if [ -n "$SCRUB" ]; then unset {_ALL}; fi
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# `while` body — the loop's condition is false, so the unset never executes.
_UNSET_IN_WHILE = f"""#!/bin/bash
while [ -n "$RETRY" ]; do
    unset {_ALL}
done
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# `for` body over a possibly-empty list.
_UNSET_IN_FOR = f"""#!/bin/bash
for _ in $MAYBE_EMPTY; do
    unset {_ALL}
done
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# `case` arm — only fires for one value of $MODE.
_UNSET_IN_CASE = f"""#!/bin/bash
case "$MODE" in
  strict) unset {_ALL} ;;
  *) echo "lenient" ;;
esac
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# A function that defines the scrub and is never called.
_UNSET_IN_UNCALLED_FUNCTION = f"""#!/bin/bash
scrub() {{
    unset {_ALL}
}}
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# `&&` gates the unset on a condition that may be false.
_UNSET_BEHIND_AND = f"""#!/bin/bash
[ -n "$SCRUB" ] && unset {_ALL}
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# `||` — runs only when the left side fails.
_UNSET_BEHIND_OR = f"""#!/bin/bash
[ -z "$SCRUB" ] || unset {_ALL}
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# Backgrounded: a subshell unsets its OWN copy; the hook keeps every variable.
_UNSET_BACKGROUNDED = f"""#!/bin/bash
unset {_ALL} &
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# In a pipeline — same subshell problem.
_UNSET_IN_PIPELINE = f"""#!/bin/bash
unset {_ALL} | cat
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# An explicit ( ) subshell.
_UNSET_IN_SUBSHELL = f"""#!/bin/bash
( unset {_ALL} )
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# The scrub happens, then GIT_DIR is put straight back.
_REEXPORTED_AFTER_UNSET = f"""#!/bin/bash
unset {_ALL}
export GIT_DIR="$HOME/repo/.git"
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# A bare assignment (no `export`) still repopulates the name for anything the
# hook sources or re-exports later.
_REASSIGNED_AFTER_UNSET = f"""#!/bin/bash
unset {_ALL}
GIT_INDEX_FILE=/tmp/idx
export GIT_INDEX_FILE
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# The names appear only inside a here-doc body — inert text, never executed.
_UNSET_IN_HEREDOC = f"""#!/bin/bash
cat <<'NOTE'
unset {_ALL}
NOTE
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# The scrub is delegated to a sourced file the guard cannot read.
_SOURCED_SCRUB = """#!/bin/bash
source ./scripts/scrub-env.sh
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# `trap` defers the unset to hook exit — long after pytest has run.
_TRAPPED_UNSET = f"""#!/bin/bash
trap "unset {_ALL}" EXIT
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# The names appear only as advice, never as an executed unset.
_COMMENT_ONLY = f"""#!/bin/bash
# remember to unset {_ALL} here
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# An unquoted echo tokenizes a bare `unset` and the variable names too.
_ECHOED_UNSET = f"""#!/bin/bash
echo you should unset {_ALL} first
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# Partial coverage: GIT_INDEX_FILE alone is enough to redirect `git add` at the
# real index even with GIT_DIR gone.
_PARTIAL = _GOOD.replace(f"unset {_ALL}", "unset GIT_DIR")

# Indirection through a variable — the guard cannot resolve $VARS, and must not
# credit the hook for names it cannot see.
_INDIRECT_NAMES = f"""#!/bin/bash
VARS="{_ALL}"
unset $VARS
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""

# A line continuation the parser cannot model — must fail, not silently pass.
_CONTINUATION = _GOOD.replace(f"unset {_ALL}", "unset \\\n    GIT_DIR")

# `echo unset …` and the real command share a line; only the echo is an unset.
_SMUGGLED_ON_ONE_LINE = _GOOD.replace(
    f"unset {_ALL}", f"echo unset {_ALL} && true")

# The whole hook body lives inside a function; nothing runs at top level, and a
# stray `fi`-style desync must not make the guard read block bodies as top level.
_UNBALANCED_BLOCK = f"""#!/bin/bash
fi
unset {_ALL}
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""


@pytest.mark.parametrize("label,text", [
    ("a hook with no unset at all (the issue-14 state)", _NO_UNSET),
    ("an unset placed after the first git call", _UNSET_AFTER_BOUNDARY),
    ("an unset inside a single dispatch arm, above the boundary", _UNSET_IN_ONE_ARM),
    ("the same arm-only unset written as a one-liner", _UNSET_IN_ONE_LINE_IF),
    ("an unset inside a while-loop body", _UNSET_IN_WHILE),
    ("an unset inside a for-loop body", _UNSET_IN_FOR),
    ("an unset inside a case arm", _UNSET_IN_CASE),
    ("an unset inside a function that is never called", _UNSET_IN_UNCALLED_FUNCTION),
    ("an unset gated behind &&", _UNSET_BEHIND_AND),
    ("an unset gated behind ||", _UNSET_BEHIND_OR),
    ("a backgrounded unset (subshell)", _UNSET_BACKGROUNDED),
    ("an unset inside a pipeline (subshell)", _UNSET_IN_PIPELINE),
    ("an unset inside an explicit ( ) subshell", _UNSET_IN_SUBSHELL),
    ("GIT_DIR re-exported after the unset", _REEXPORTED_AFTER_UNSET),
    ("GIT_INDEX_FILE re-assigned after the unset", _REASSIGNED_AFTER_UNSET),
    ("the unset present only inside a here-doc body", _UNSET_IN_HEREDOC),
    ("the scrub delegated to a sourced file", _SOURCED_SCRUB),
    ("the unset deferred to an EXIT trap", _TRAPPED_UNSET),
    ("the variables named only in a comment", _COMMENT_ONLY),
    ("a bare `unset` token smuggled in via echo", _ECHOED_UNSET),
    ("GIT_DIR unset but GIT_INDEX_FILE left behind", _PARTIAL),
    ("variable names reached only through $VARS indirection", _INDIRECT_NAMES),
    ("a line continuation", _CONTINUATION),
    ("`echo unset …` sharing a line with a real command", _SMUGGLED_ON_ONE_LINE),
    ("an unbalanced block that desyncs depth tracking", _UNBALANCED_BLOCK),
])
def test_checker_rejects_known_bad_hooks(label, text):
    assert _violations(text, set(_CANON)), f"checker failed to reject {label}"


def test_a_called_function_is_still_not_credited():
    """Fail-closed by design, and worth stating so the next maintainer is not
    surprised: a scrub moved into a function is rejected even when the function
    IS called, because the guard cannot prove the call is reached
    unconditionally (or reached at all — `scrub` may be shadowed, or the call may
    sit in a branch). The remedy is to put the `unset` at top level, which is
    what the hook does. This mirrors `tests/test_pre_commit_hook.py`, which
    refuses to reason about anything it cannot read literally."""
    called = f"""#!/bin/bash
scrub() {{
    unset {_ALL}
}}
scrub
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""
    assert _violations(called, set(_CANON))


def test_checker_accepts_a_known_good_hook():
    """The other half of the red-proof: the rejections above come from the named
    defect, not from a checker that rejects everything."""
    assert _violations(_GOOD, set(_CANON)) == []


@pytest.mark.parametrize("label,text", [
    # Real hooks that happen to contain the constructs the parser models. These
    # must NOT be rejected, or the guard becomes noise a maintainer routes
    # around instead of a signal.
    ("a completed if/fi block above the scrub", f"""#!/bin/bash
if [ -n "$VERBOSE" ]; then
    echo "verbose"
fi
unset {_ALL}
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""),
    ("a function defined above the scrub", f"""#!/bin/bash
note() {{
    echo "$1"
}}
note "starting"
unset {_ALL}
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""),
    ("a case block above the scrub", f"""#!/bin/bash
case "$MODE" in
  quiet) echo "" ;;
  *) echo "Running tests..." ;;
esac
unset {_ALL}
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""),
    ("the scrub sharing a line with a following command", f"""#!/bin/bash
unset {_ALL}; echo "scrubbed"
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""),
    ("the scrub wrapped in a { } group (runs in the current shell)", f"""#!/bin/bash
{{ unset {_ALL}; }}
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""),
    ("a here-doc above the scrub", f"""#!/bin/bash
cat <<'BANNER'
pre-commit
BANNER
unset {_ALL}
cd "$(git rev-parse --show-toplevel)" || exit 1
python3 -m pytest -v
"""),
])
def test_checker_accepts_valid_variations(label, text):
    """False alarms are their own failure mode: a guard that rejects correct
    hooks gets deleted, and then it guards nothing."""
    assert _violations(text, set(_CANON)) == [], f"checker wrongly rejected {label}"


# ---------------------------------------------------------------------------
# Red-proof for _required_vars itself
# ---------------------------------------------------------------------------

def _with_conftest(monkeypatch, tmp_path: Path, text: str):
    path = tmp_path / "conftest.py"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setitem(globals(), "_CONFTEST", path)
    return path


_REAL_CONFTEST = _CONFTEST.read_text(encoding="utf-8")

# A verbatim copy of Guard 1, used as the needle for the mutations below. Kept as
# a literal rather than sliced out of the file so that a Guard 1 rewrite has to be
# noticed and re-read by a human. `_mutate` asserts the needle still matches
# before every substitution: without that, a drifted literal makes `.replace()` a
# silent no-op, the "mutated" conftest stays valid, and each red-proof below
# passes while proving nothing.
_GUARD1 = ('for _var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",\n'
           '             "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",\n'
           '             "GIT_NAMESPACE", "GIT_CONFIG_PARAMETERS"):\n'
           '    os.environ.pop(_var, None)\n')


def _mutate(replacement: str) -> str:
    """`_REAL_CONFTEST` with Guard 1 swapped for `replacement`, or a loud failure
    if `_GUARD1` no longer matches the file."""
    assert _GUARD1 in _REAL_CONFTEST, (
        "Guard 1's exact text in conftest.py no longer matches this file's "
        "_GUARD1 literal; update _GUARD1 so the red-proofs below keep biting")
    return _REAL_CONFTEST.replace(_GUARD1, replacement, 1)


def test_required_vars_reads_the_real_conftest():
    assert _required_vars() == set(_CANON)


def test_required_vars_raises_when_guard1_is_deleted(monkeypatch, tmp_path):
    _with_conftest(monkeypatch, tmp_path, _mutate(""))
    with pytest.raises(AssertionError, match="Guard 1"):
        _required_vars()


def test_required_vars_raises_when_the_loop_body_is_gutted(monkeypatch, tmp_path):
    """The names can survive while the scrub does not: a loop whose
    ``os.environ.pop`` became ``pass`` still enumerates all seven variables."""
    _with_conftest(monkeypatch, tmp_path,
                   _REAL_CONFTEST.replace("    os.environ.pop(_var, None)", "    pass"))
    with pytest.raises(AssertionError, match="scrubbing none"):
        _required_vars()


def test_required_vars_ignores_a_loop_inside_a_function(monkeypatch, tmp_path):
    """Guard 1 is module-level code that runs at import. A structurally identical
    loop inside a helper runs only when called and is NOT Guard 1."""
    _with_conftest(monkeypatch, tmp_path, _mutate(
        'def _scrub():\n'
        '    for _var in ("GIT_DIR",):\n'
        '        os.environ.pop(_var, None)\n'))
    with pytest.raises(AssertionError, match="Guard 1"):
        _required_vars()


def test_required_vars_rejects_an_ambiguous_second_loop(monkeypatch, tmp_path):
    """A decoy module-level loop over a SUBSET would otherwise shrink the
    required set silently, and the hook would pass while Guard 1 shrank."""
    _with_conftest(monkeypatch, tmp_path, _mutate(
        'for _v in ("GIT_DIR",):\n    os.environ.pop(_v, None)\n\n' + _GUARD1))
    with pytest.raises(AssertionError, match="scrub loops"):
        _required_vars()
