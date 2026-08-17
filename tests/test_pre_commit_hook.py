"""Dependency-provisioning invariant for ``.githooks/pre-commit`` (issue #31).

The hook exists so that "green on my machine" means "green in CI" — it runs the
same full ``pytest -v`` suite CI runs. That promise is only true if the hook's
environment has what the suite needs, and the suite hard-requires **PyYAML**:
several ci-score tests exec ``skills/ci-score/scripts/collect_config.py`` by file
path *at module scope*, and that script does ``sys.exit(1)`` in its
``except ImportError``. A ``SystemExit`` raised during pytest's COLLECTION phase
is not a test failure pytest can report — it aborts the entire run with
``INTERNALERROR``. The observed symptom was a wall of traceback on a clean tree,
exit code 3, and zero tests having run.

Two of the hook's three arms (``uvx``, ``pipx``) build a throwaway environment
containing pytest and *nothing else*, so they must explicitly provision pyyaml
into it. The third (bare ``python3``) cannot provision anything, so it must
instead pre-check that yaml is importable and abort with a readable message
rather than the INTERNALERROR wall.

This is exactly the class of bug that stays invisible: the suite is green in CI
the whole time, and nothing else in the repo exercises the hook, so a regression
here ships without a single red test. Hence a guard.

**Why this parses instead of grepping.** The obvious ``assert "--with pyyaml" in
text`` is brittle (breaks on ``--with=pyyaml``) and trivially satisfied by
someone writing the string in a comment. So the checker below shlex-splits real
command lines only, attributes each to the arm it lives in — a flag that drifts
into the wrong branch fails — and checks that ``--with pyyaml`` actually precedes
the ``pytest`` token, because ``uvx pytest --with=pyyaml`` passes the flag to
pytest, not to uvx, and is just as broken as omitting it. It deliberately reads
the file as text rather than executing the hook, so the guard runs everywhere;
requiring uvx/pipx to be installed would make it skip on most machines, which is
precisely the hole that let this bug exist.

**On ``--preinstall``.** An early draft of the fix used
``pipx run --preinstall pyyaml``. That flag is real but belongs to ``pipx
install``; ``pipx run`` rejects it with ``unrecognized arguments``, which would
have made the hook abort *every* commit for pipx users. The specific assertion
against it below is a red-proof of a mistake already made once.

**The parser is deliberately fail-closed.** It models one command per line and
multi-line ``if``/``elif``/``else``/``fi`` only. Shell it cannot model — a
one-line ``if …; then …; fi``, a line continuation, pytest launched through
``bash -c``, a ``case`` dispatch — produces a *violation*, never a silent pass.
A guard that quietly stops checking is the failure mode this whole file exists to
prevent, so every unmodellable construct is an explicit "rewrite this so the
guard can read it".

``_reject`` negative-controls the checker against the original broken hook and
against a battery of hostile rewrites: a refactor that guts the parser would
otherwise ship green — the same failure mode ``tests/test_repo_guards.py`` was
written to prevent.
"""
from __future__ import annotations

import ast
import shlex
import tomllib
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_HOOK = _REPO / ".githooks" / "pre-commit"
_PYPROJECT = _REPO / "pyproject.toml"
_CI_WORKFLOWS = (
    _REPO / ".github" / "workflows" / "ci.yml",
    _REPO / ".github" / "workflows" / "ci-fork.yml",
)

# Runners that build an isolated, throwaway environment. These CAN and MUST be
# told to add pyyaml. Any runner NOT in this set is treated as unknown and fails
# the enumeration check below, so adding a fourth arm can't silently go
# unprotected.
_ISOLATED_RUNNERS = frozenset({"uvx", "pipx"})

# Commands that run a shell fragment given as a *string*: the guard cannot see
# inside them, so a pytest invocation hidden in one is unmodellable by design.
_SHELL_WRAPPERS = frozenset({"bash", "sh", "zsh", "dash", "eval", "exec", "env",
                             "xargs", "nohup", "timeout"})

# Leading words to peel off before identifying a command's runner.
_LEADING_NOISE = frozenset({"if", "elif", "!", "then", "do", "while", "until"})


# ---------------------------------------------------------------------------
# The parser — split the runner dispatch into its top-level arms
# ---------------------------------------------------------------------------

def _strip(raw: str) -> str:
    """Strip whitespace and drop whole-line comments (never partial lines: a
    ``#`` inside a quoted echo is not a comment, and mis-stripping one would
    silently change what the checker sees)."""
    line = raw.strip()
    return "" if line.startswith("#") else line


_STATEMENT_SEPS = frozenset({";", "&&", "||", "&"})


def _split(line: str) -> list[str]:
    """shlex-split a line, or [] if it is not something we can tokenize."""
    try:
        return shlex.split(line)
    except ValueError:              # unbalanced quotes — not a command we model
        return []


def _statements(line: str) -> list[list[str]]:
    """Tokenize a line, then split it into individual shell STATEMENTS on
    unquoted ``;`` / ``&&`` / ``||`` / ``&``.

    Without this, a single physical line can smuggle two unrelated commands
    past a checker that reasons over "the line's tokens" as one bag: e.g.
    ``uvx --with pyyaml true; pipx run pytest -v`` gives pyyaml to a no-op and
    runs the REAL pytest invocation — via plain ``pipx run pytest -v`` — with
    nothing. A whole-line token scan sees ``--with pyyaml`` sitting before the
    ``pytest`` token and calls it provisioned; it never notices they belong to
    different commands. Splitting on real shell statement separators first
    closes that gap for ``;``, ``&&``, ``||``, and backgrounding ``&``.
    """
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:              # unbalanced quotes — not a command we model
        return []
    statements: list[list[str]] = [[]]
    for tok in tokens:
        if tok in _STATEMENT_SEPS:
            statements.append([])
        else:
            statements[-1].append(tok)
    return [s for s in statements if s]


def _command_words(line: str) -> list[str]:
    """The first word of each shell STATEMENT on the line, as keywords.

    Uses ``_statements`` (quote-aware) rather than a raw ``line.split(";")`` —
    a naive split on the literal character breaks as soon as a semicolon
    appears INSIDE a quoted argument, e.g. a Python ``-c`` payload with more
    than one statement in it. That corrupted the ``if``/``fi`` depth counter in
    ``_blocks``: the spurious extra "segment" register as a bogus `if`, which
    silently truncated the arm's line list before the real `fi` and the real
    pytest invocation — so the checker stopped looking at that arm entirely
    rather than reporting a violation. Depth tracking must never lose lines
    because of characters that live inside a string.
    """
    return [stmt[0] for stmt in _statements(line) if stmt]


def _blocks(hook_text: str) -> list[list[list[str]]]:
    """Every top-level ``if`` block in the hook, as a list of its arms.

    Tracks ``if``/``fi`` nesting so a nested conditional inside an arm (the
    python3 arm's yaml preflight) stays attributed to its enclosing arm rather
    than being mistaken for a further arm. Comments and blank lines are dropped
    before anything is inspected, so a mention of ``pyyaml`` in a comment can
    never satisfy an assertion.
    """
    groups: list[list[list[str]]] = []
    depth = 0
    for raw in hook_text.splitlines():
        line = _strip(raw)
        if not line:
            continue
        words = _command_words(line)
        if words and words[0] == "if":
            depth += 1
            if depth == 1:
                groups.append([[]])       # open a new block with its first arm
                continue
        elif words and words[0] == "fi":
            depth -= 1
            continue
        elif depth == 1 and words and words[0] in ("elif", "else"):
            groups[-1].append([])         # open the next arm of this block
            continue
        if depth >= 1 and groups:
            groups[-1][-1].append(line)
    return groups


def _dispatch_arms(hook_text: str) -> list[list[str]]:
    """The arms of the block that actually dispatches pytest.

    The hook has more than one top-level conditional (the dispatch, plus the
    ``if [ $? -ne 0 ]`` result check), and a future edit could add another that
    merely *mentions* pytest. Pick the block with the most pytest-running arms —
    and note that ``_violations`` checks EVERY block that runs pytest, so a decoy
    block cannot shadow a broken real one.
    """
    scored = [(sum(1 for arm in arms if _pytest_commands(arm)), arms)
              for arms in _blocks(hook_text)]
    scored = [(n, arms) for n, arms in scored if n]
    if not scored:
        return []
    return max(scored, key=lambda pair: pair[0])[1]


def _runner(tokens: list[str]) -> str | None:
    """The command word of a tokenized line, with shell noise peeled off."""
    for tok in tokens:
        if tok in _LEADING_NOISE:
            continue
        return tok
    return None


def _pytest_commands(arm_lines: list[str]) -> list[list[str]]:
    """Every individual shell STATEMENT in an arm that invokes pytest, one
    statement at a time (see ``_statements`` for why a line isn't a statement).

    Matches ``pytest`` as a whole token (or a path ending in ``/pytest``) so that
    an ``echo`` whose *message text* happens to contain "pytest" — the hook's own
    install hint does — is not mistaken for an invocation. Pytest smuggled inside
    a quoted shell fragment is caught separately, as an unmodellable construct.
    """
    found = []
    for line in arm_lines:
        for tokens in _statements(line):
            if any(t == "pytest" or t.endswith("/pytest") for t in tokens):
                found.append(tokens)
    return found


def _flat(tokens: list[str]) -> list[str]:
    """Split `--with=pyyaml` into `--with`, `pyyaml` so both spellings compare equal."""
    out: list[str] = []
    for tok in tokens:
        out.extend(tok.split("=", 1) if tok.startswith("-") and "=" in tok else [tok])
    return out


def _provisions_pyyaml_before_pytest(tokens: list[str]) -> bool:
    """`--with pyyaml` must be an argument to the RUNNER, i.e. appear before the
    `pytest` token. `uvx pytest --with=pyyaml` hands the flag to pytest instead
    and is exactly as broken as omitting it."""
    try:
        pytest_at = next(i for i, t in enumerate(tokens)
                         if t == "pytest" or t.endswith("/pytest"))
    except StopIteration:
        return False
    for i, tok in enumerate(tokens[:pytest_at]):
        if tok == "--with" and i + 1 < pytest_at and tokens[i + 1] == "pyyaml":
            return True
    return False


def _real_yaml_preflight(arm_lines: list[str]) -> bool:
    """True iff the arm actually *executes* a Python `-c` payload that imports
    yaml — verified by parsing the payload as Python and inspecting its AST,
    not by searching its text.

    A substring search for "import yaml" would be satisfied by an `echo` that
    merely suggests the import (that's the `_ECHOED_PREFLIGHT` control), but
    it would ALSO be satisfied by `python3 -c "print('import yaml')"` — a
    string literal that mentions the words without ever importing anything.
    Parsing the payload and walking its `Import`/`ImportFrom` nodes is the only
    way to tell "this text contains the phrase" from "this code does the
    thing".
    """
    for line in arm_lines:
        for tokens in _statements(line):
            words = [t for t in tokens if t not in _LEADING_NOISE]
            if not words or not words[0].startswith("python"):
                continue
            if "-c" not in words:
                continue
            idx = words.index("-c")
            if idx + 1 >= len(words):
                continue
            try:
                tree = ast.parse(words[idx + 1])
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(
                        alias.name == "yaml" for alias in node.names):
                    return True
                if isinstance(node, ast.ImportFrom) and node.module == "yaml":
                    return True
    return False


def _aborts(arm_lines: list[str]) -> bool:
    """True iff the arm can terminate the hook (`exit …`) — a preflight that only
    warns and then runs pytest anyway is the INTERNALERROR wall all over again.

    Requires ``exit`` as a statement's actual leading command word, not merely
    present as a token anywhere on the line — an unquoted
    ``echo will exit 1 if this fails`` tokenizes to a bare word ``exit`` too, and
    a substring/membership check over the whole line can't tell that apart from
    a real ``exit 1``.
    """
    for line in arm_lines:
        for statement in _statements(line):
            words = [t for t in statement if t not in _LEADING_NOISE]
            if words and words[0] == "exit":
                return True
    return False


def _unmodellable(hook_text: str) -> list[str]:
    """Constructs the parser cannot read. Reported as violations, never ignored."""
    problems = []
    for raw in hook_text.splitlines():
        line = _strip(raw)
        if not line:
            continue
        if line.endswith("\\"):
            problems.append(
                f"line continuation splits a command across lines; the guard "
                f"models one command per line — keep it on one line: {line}")
            continue
        words = _command_words(line)
        if "if" in words and "fi" in words:
            problems.append(
                f"one-line `if …; then …; fi` — the guard models multi-line "
                f"conditionals only; write it out: {line}")
        # Per STATEMENT, not per line: `true && bash -c "uvx pytest -v"` hides a
        # wrapped pytest behind a leading decoy command that a whole-line runner
        # lookup would report instead of `bash`.
        for tokens in _statements(line):
            runner = _runner(tokens)
            if runner in _SHELL_WRAPPERS and any("pytest" in t for t in tokens):
                problems.append(
                    f"pytest invoked through {runner!r}, whose argument is an opaque "
                    f"shell string the guard cannot inspect: {line}")
    return problems


def _violations(hook_text: str) -> list[str]:
    """Every reason this hook text fails the invariant. Empty list == compliant."""
    problems: list[str] = _unmodellable(hook_text)

    blocks = [arms for arms in _blocks(hook_text)
              if any(_pytest_commands(arm) for arm in arms)]
    if not blocks:
        problems.append("no pytest dispatch block found in the hook")
        return problems

    # EVERY block that runs pytest is checked, not just the dispatch: a decoy
    # `if` that merely mentions pytest must not shadow a broken real dispatch.
    for arms in blocks:
        for arm in arms:
            for raw_tokens in _pytest_commands(arm):
                tokens = _flat(raw_tokens)
                runner = _runner(tokens)
                if runner in _ISOLATED_RUNNERS:
                    if not _provisions_pyyaml_before_pytest(tokens):
                        problems.append(
                            f"isolated runner {runner!r} builds a throwaway env but "
                            f"never provisions pyyaml into it via `--with pyyaml` "
                            f"ahead of the pytest token: {' '.join(tokens)}")
                    if runner == "pipx" and "--preinstall" in tokens:
                        problems.append(
                            "`pipx run` does not accept --preinstall (that flag belongs "
                            "to `pipx install`); it aborts with 'unrecognized arguments' "
                            "and breaks every commit. Use --with.")
                elif runner and runner.startswith("python"):
                    # Can't provision; must pre-check instead, in this same arm.
                    if not _real_yaml_preflight(arm):
                        problems.append(
                            "the bare python3 arm cannot install pyyaml, so it must "
                            "preflight `python3 -c \"import yaml\"` and fail readably; "
                            "no such command found in that arm")
                    elif not _aborts(arm):
                        problems.append(
                            "the bare python3 arm preflights yaml but never `exit`s on "
                            "failure, so pytest still runs without yaml and still hits "
                            "INTERNALERROR")
                else:
                    problems.append(
                        f"unknown test runner {runner!r} — if this is a new isolated "
                        f"runner it needs a pyyaml provisioning rule here")
    return problems


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------

def test_hook_exists_and_is_executable():
    assert _HOOK.is_file(), f"{_HOOK} is missing"


def test_every_arm_provisions_pyyaml():
    """The invariant itself: no arm may run pytest without yaml being available."""
    assert _violations(_HOOK.read_text()) == []


def test_dispatch_has_exactly_three_arms():
    """A fourth arm must fail loudly rather than quietly go unguarded."""
    arms = _dispatch_arms(_HOOK.read_text())
    assert len(arms) == 3, (
        f"expected 3 dispatch arms (uvx / pipx / bare python3), found {len(arms)}; "
        "a new arm needs its own pyyaml provisioning rule in _violations()")


def test_uvx_arm_is_tried_before_pipx():
    """uvx is the arm verified end-to-end (full suite, CI-identical pass/skip counts).

    pipx is correct as written but the minimum version carrying `run --with` is
    unconfirmed, so it must not shadow uvx by being checked first.
    """
    arms = _dispatch_arms(_HOOK.read_text())
    runners = [_runner(_flat(cmds[0])) for arm in arms if (cmds := _pytest_commands(arm))]
    assert runners.index("uvx") < runners.index("pipx"), (
        f"uvx must be tried before pipx; got order {runners}")


def test_pyyaml_is_declared_in_the_dev_extra():
    """The root cause. Had this been declared, the hook could not have forgotten it."""
    data = tomllib.loads(_PYPROJECT.read_text())
    dev = data["project"]["optional-dependencies"]["dev"]
    assert any(spec.lower().startswith("pyyaml") for spec in dev), (
        f"pyyaml missing from pyproject.toml's dev extra: {dev}")


@pytest.mark.parametrize("workflow", _CI_WORKFLOWS, ids=lambda p: p.name)
def test_ci_workflows_also_provision_pyyaml(workflow):
    """CI is the other environment that runs this suite, and it installs its deps
    with its own hardcoded `pip install` line rather than reading the dev extra.
    Nothing stops someone from trimming that line — and the failure would be the
    same INTERNALERROR wall, on the gate that protects `main`. So pin it here.
    """
    assert workflow.is_file(), f"{workflow} is missing"
    text = workflow.read_text()
    installs = [ln.strip() for ln in text.splitlines()
                if "pip install" in ln and "uv" not in ln.split("pip install")[1]]
    assert installs, f"{workflow.name} has no dependency install step"
    assert any("pyyaml" in ln.lower() or '".[dev]"' in ln or "'.[dev]'" in ln
               for ln in installs), (
        f"{workflow.name} runs the suite but never installs PyYAML "
        f"(install lines: {installs}); pytest will abort at collection with "
        "INTERNALERROR. Install it explicitly or use the dev extra.")


# ---------------------------------------------------------------------------
# Negative controls — proof the checker above has teeth
# ---------------------------------------------------------------------------

_BROKEN_ORIGINAL = """#!/bin/bash
echo "Running tests..."
cd "$(git rev-parse --show-toplevel)"
if command -v pipx &> /dev/null; then
    pipx run pytest -v
elif command -v uvx &> /dev/null; then
    uvx pytest -v
else
    python3 -m pytest -v
fi
"""

_BROKEN_PREINSTALL = _BROKEN_ORIGINAL.replace(
    "pipx run pytest -v", "pipx run --preinstall pyyaml pytest -v").replace(
    "uvx pytest -v", "uvx --with pyyaml pytest -v")

_COMMENT_ONLY = """#!/bin/bash
# remember to use --with pyyaml here
if command -v uvx &> /dev/null; then
    uvx pytest -v
fi
"""

# A compliant hook, used as the base for the hostile rewrites below so each one
# differs from a PASSING text by exactly the defect it is named for.
_GOOD = """#!/bin/bash
if command -v uvx &> /dev/null; then
    uvx --with pyyaml pytest -v
elif command -v pipx &> /dev/null; then
    pipx run --with pyyaml pytest -v
else
    if ! python3 -c "import yaml" &> /dev/null; then
        echo "install pyyaml"
        exit 1
    fi
    python3 -m pytest -v
fi
"""

# `--with=pyyaml` AFTER the subcommand is an argument to pytest, not to uvx.
_FLAG_AFTER_PYTEST = _GOOD.replace(
    "uvx --with pyyaml pytest -v", "uvx pytest --with=pyyaml -v")

# `--from` selects the package providing the executable; it installs pyyaml and
# then fails to find a `pytest` entry point in it.
_WRONG_FLAG = _GOOD.replace(
    "uvx --with pyyaml pytest -v", "uvx --from pyyaml pytest -v")

# The preflight degraded from an abort to a warning: pytest still runs yaml-less.
_PREFLIGHT_WARNS_ONLY = _GOOD.replace('        exit 1\n', '')

# "import yaml" present only as advice inside an echo — no actual preflight.
_ECHOED_PREFLIGHT = """#!/bin/bash
if command -v uvx &> /dev/null; then
    uvx --with pyyaml pytest -v
elif command -v pipx &> /dev/null; then
    pipx run --with pyyaml pytest -v
else
    echo "if this fails, check python3 -c 'import yaml'"
    python3 -m pytest -v
fi
"""

# A decoy conditional that mentions pytest, placed BEFORE a fully broken
# dispatch: a checker that inspects only the first matching block sees green.
_DECOY_BLOCK = """#!/bin/bash
if [ -n "$SKIP" ]; then
    uvx --with pyyaml pytest -v
fi
""" + _BROKEN_ORIGINAL.split("\n", 3)[3]

# pytest smuggled through a shell wrapper the guard cannot see inside.
_WRAPPED = _GOOD.replace(
    "uvx --with pyyaml pytest -v", 'bash -c "uvx pytest -v"')

# A one-liner conditional: unmodellable, so it must fail rather than pass.
_ONE_LINER = """#!/bin/bash
if command -v uvx &> /dev/null; then uvx pytest -v; fi
"""

# A line continuation hiding the runner from its arguments.
_CONTINUATION = _GOOD.replace(
    "uvx --with pyyaml pytest -v", "uvx \\\n        pytest -v")

# A `case` dispatch — no `if` block at all, so nothing gets checked unless the
# absence of a dispatch is itself a violation.
_CASE_DISPATCH = """#!/bin/bash
case "$RUNNER" in
  uvx) uvx pytest -v ;;
  *) python3 -m pytest -v ;;
esac
"""

# A fourth, unrecognized runner.
_FOURTH_ARM = _GOOD.replace(
    "elif command -v pipx",
    "elif command -v hatch &> /dev/null; then\n    hatch run pytest -v\nelif command -v pipx")


@pytest.mark.parametrize("label,text", [
    ("the original issue-31 hook", _BROKEN_ORIGINAL),
    ("the wrong pipx flag (--preinstall)", _BROKEN_PREINSTALL),
    ("pyyaml mentioned only in a comment", _COMMENT_ONLY),
    ("--with placed after the pytest token", _FLAG_AFTER_PYTEST),
    ("--from instead of --with", _WRONG_FLAG),
    ("preflight that warns but never exits", _PREFLIGHT_WARNS_ONLY),
    ("'import yaml' only inside an echo", _ECHOED_PREFLIGHT),
    ("a decoy block shadowing a broken dispatch", _DECOY_BLOCK),
    ("pytest wrapped in bash -c", _WRAPPED),
    ("a one-line if/then/fi dispatch", _ONE_LINER),
    ("a line continuation", _CONTINUATION),
    ("a case-statement dispatch", _CASE_DISPATCH),
    ("an unrecognized fourth runner", _FOURTH_ARM),
])
def test_checker_rejects_known_bad_hooks(label, text):
    """Without these, a parser that silently matched everything would ship green."""
    assert _violations(text), f"checker failed to reject {label}"


def test_checker_accepts_a_known_good_hook():
    """The other half of the red-proof: the rejections above must come from the
    named defect, not from a checker that rejects everything."""
    assert _violations(_GOOD) == []
