#!/usr/bin/env python3
"""Pre-commit hook: validate ActionScript block balance in BES files.

Checks every <ActionScript> body of a BES file (and, for non-.bes/.ojo paths,
the whole file read as one raw ActionScript body) for balanced `if`/`endif`
and `begin prefetch block`/`end prefetch block` pairing. This is the sibling
hook named in bes_actionscript_lint_schclass.py's SCOPE note: checks that need
knowledge the lexical grammar does not carry -- pairing, ordering, and block
interleaving -- live here instead. It is meant to grow more per-script checks
over time; the balance walk is the first.

An unbalanced block is a real defect, not a style nit: the BigFix agent fails
the action at runtime on a dangling `if`, and a missing `endif` silently
changes which statements are conditional.

Checks:
    E500  an `if` is never closed by a matching `endif`
    E501  an `endif` with no open `if`
    E502  a `begin prefetch block` is never closed by `end prefetch block`
    E503  an `end prefetch block` with no open `begin prefetch block`
    E504  a `begin prefetch block` nested inside another one (prefetch blocks
          do not nest)
    E505  an `else` or `elseif` outside any open `if`
    E506  an `elseif` after `else`, or a second `else` for the same `if`
    E507  an `if` opened inside a prefetch block is still open when that
          block's `end prefetch block` is reached -- blocks interleave, they
          do not nest, so this cannot close cleanly
    E508  a `{` relevance substitution has no closing `}` before the end of
          its line (a substitution cannot span lines); `}}` inside the
          substitution is a literal `}` and does not close it
    E509  a `}` with no `{` relevance substitution open on that line
    E510  an `add prefetch item` / `add nohash prefetch item` outside an open
          `begin prefetch block` (the agent rejects these outside a block)
    E511  a `collect prefetch items` outside an open prefetch block
    E512  two prefetch/download producers declare the same download name in
          the exact same conditional context (both unconditional, or both
          reached through identical if/elseif/else branch choices) -- the
          second silently overwrites the first. Declarations reached via
          different `if`s (even ones that look platform-exclusive, like a
          separate `if` per OS) are NOT compared: this checker cannot verify
          their conditions are mutually exclusive, and BigFix content
          routinely relies on exactly that pattern for cross-platform
          prefetch blocks
    E513  a command references `__Download\\<name>` but nothing prefetches or
          downloads a file of that name (a typo catcher; skipped entirely
          when any producer's names are unknowable -- see below. `delete` and
          `folder delete` lines are cleanup, not consumption, and never count)
    E514  an `if` or `elseif` whose condition is not a `{...}` relevance
          substitution (`if true`, bare `if`; the agent requires one)
    E515  a `begin prefetch block` that is not at the top of the script --
          only blank lines, `//` comments, `action parameter query` lines,
          and `parameter` assignments may precede it. Plain `prefetch`
          statements are NOT placement-checked; they are legal anywhere
    W500  the file is not parseable BES XML; skipped (advisory --
          bes-schema-validate is the authority on file validity)
    W501  unreachable command: a line after an unconditional `exit`,
          `restart`, or `shutdown` (one outside any `if`) can never run;
          only the first unreachable line is reported
    W502  an `action parameter query` after the first execution command --
          these are console-time prompts and belong at the top

E513 is conservative: it is skipped for a whole body whenever any producer's
names cannot be known statically -- an `extract`/`unarchive`/`archive now`/
`utility` command, a `download` with no `as <name>` whose URL is not a literal
with a basename, or any producer name/URL containing a `{` substitution.

E-codes are real issues and fail the hook. W-codes are advisory and do NOT
fail the hook unless --strict is given. This hook has no auto-fixes: a hook
has no way to know where a missing `endif` or `end prefetch block` was
supposed to go, and guessing could silently change what the action does.

Only <ActionScript> elements with MIMEType application/x-Fixlet-Windows-Shell
(matched case-insensitively; a mixed-case MIMEType is still valid BigFix
content) or no MIMEType (which defaults to it) are checked; other bodies are
other languages and are skipped silently. Bodies are extracted with lxml, so
entities are decoded and adjacent CDATA sections merged, with lxml's
sourceline mapping issues back to file line numbers.

Lines inside a `createfile until <MARKER>` block are raw file content, not
ActionScript, and are not scanned -- an `if` or `endif` appearing in such a
block's content does not count. That block's own well-formedness (does it
reach its marker) is bes-actionscript-lint-schclass's E302, not this hook's;
it is not re-reported here.

Usage:
    bes_actionscript_validate_script.py [--strict] [--disable E501] [file ...]

With no file arguments, all *.bes files in the current folder and below are
checked. Non-.bes/.ojo paths given explicitly are checked as raw ActionScript
text.

A file can opt out of all checks with a comment anywhere in it:
    <!-- pre-commit-skip: bes-actionscript-validate-script -->
or out of a single check family with the matching marker anywhere in the file:
    actionscript-if-ok             (E500, E501, E505, E506)
    actionscript-prefetch-block-ok (E502, E503, E504)
    actionscript-block-nesting-ok  (E507)
    actionscript-substitution-ok   (E508, E509)
    actionscript-prefetch-placement-ok (E510, E511, E515)
    actionscript-download-ok       (E512, E513)
    actionscript-unreachable-ok    (W501)
    actionscript-parameter-query-ok (W502)

(E514 belongs to the `actionscript-if-ok` family above: it is an if-shape
check.)

Files that look like mustache templates (containing `{{ ... }}`) are skipped
silently: they are not real content until rendered.

Exit codes:
    0  no E-code issues (and, without --strict, regardless of warnings)
    1  an E-code issue was found, or a warning was found while --strict is set
"""

import argparse
import os
import re
import sys

from lxml import etree

if __package__ in (None, ""):  # run directly as a script, not as a module
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# `_mask_heredocs` is shared with the sibling ActionScript hook on purpose:
# both need to know that the lines inside a `createfile until` block are file
# content rather than commands, and one implementation of that rule is enough.
from pre_commit_bigfix.bes_actionscript_lint_schclass import _mask_heredocs

# prefetch line-shape prefixes (matched against lowercased lines). These
# mirror the same-named constants in bes_actionscript_validate_prefetch.py --
# NOT imported from there, because that module imports the bigfix_prefetch
# package, which this hook's isolated pre-commit environment does not carry.
# tests/test_bes_actionscript_validate_script.py asserts they stay in lockstep.
NOHASH_PREFETCH = "add nohash prefetch item"
BLOCK_PREFETCH = "add prefetch item"
STATEMENT_PREFETCH = "prefetch "

SKIP_MARKER = "pre-commit-skip: bes-actionscript-validate-script"

# per-check-family opt-out markers (matched anywhere in the file text)
IF_MARKER = "actionscript-if-ok"  # E500, E501, E505, E506
PREFETCH_BLOCK_MARKER = "actionscript-prefetch-block-ok"  # E502, E503, E504
BLOCK_NESTING_MARKER = "actionscript-block-nesting-ok"  # E507
# shared with the sibling schclass hook's E301 on purpose: one marker turns
# off substitution complaints in both hooks, which is what a file that really
# does contain odd braces wants.
SUBSTITUTION_MARKER = "actionscript-substitution-ok"  # E508, E509
PREFETCH_PLACEMENT_MARKER = "actionscript-prefetch-placement-ok"  # E510, E511, E515
DOWNLOAD_MARKER = "actionscript-download-ok"  # E512, E513
UNREACHABLE_MARKER = "actionscript-unreachable-ok"  # W501
PARAMETER_QUERY_MARKER = "actionscript-parameter-query-ok"  # W502

CHECK_MARKERS = {
    "E500": IF_MARKER,
    "E501": IF_MARKER,
    "E505": IF_MARKER,
    "E506": IF_MARKER,
    "E502": PREFETCH_BLOCK_MARKER,
    "E503": PREFETCH_BLOCK_MARKER,
    "E504": PREFETCH_BLOCK_MARKER,
    "E507": BLOCK_NESTING_MARKER,
    "E508": SUBSTITUTION_MARKER,
    "E509": SUBSTITUTION_MARKER,
    "E510": PREFETCH_PLACEMENT_MARKER,
    "E511": PREFETCH_PLACEMENT_MARKER,
    "E512": DOWNLOAD_MARKER,
    "E513": DOWNLOAD_MARKER,
    "E514": IF_MARKER,
    "E515": PREFETCH_PLACEMENT_MARKER,
    "W501": UNREACHABLE_MARKER,
    "W502": PARAMETER_QUERY_MARKER,
}

KNOWN_CODES = frozenset(
    [
        "E500",
        "E501",
        "E502",
        "E503",
        "E504",
        "E505",
        "E506",
        "E507",
        "E508",
        "E509",
        "E510",
        "E511",
        "E512",
        "E513",
        "E514",
        "E515",
        "W500",
        "W501",
        "W502",
    ]
)

BES_EXTENSIONS = (".bes", ".ojo")
ACTIONSCRIPT_MIMETYPE = "application/x-fixlet-windows-shell"  # compared lowercased

# a mustache template ({{ ... }}) is not real content until rendered
MUSTACHE_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)

# the first token of a line, case-insensitively, anchored to line start so a
# relevance substitution or argument merely containing one of these words does
# not match (e.g. `continue if {...}` is not an `if` opener)
_IF_RE = re.compile(r"^if\b", re.IGNORECASE)
_ELSEIF_RE = re.compile(r"^elseif\b", re.IGNORECASE)
_ELSE_RE = re.compile(r"^else\s*$", re.IGNORECASE)
_ENDIF_RE = re.compile(r"^endif\s*$", re.IGNORECASE)
_BEGIN_PREFETCH_BLOCK_RE = re.compile(r"^begin\s+prefetch\s+block\s*$", re.IGNORECASE)
_END_PREFETCH_BLOCK_RE = re.compile(r"^end\s+prefetch\s+block\s*$", re.IGNORECASE)
_ADD_PREFETCH_ITEM_RE = re.compile(
    r"^add\s+(?:nohash\s+)?prefetch\s+item\b", re.IGNORECASE
)
_COLLECT_PREFETCH_ITEMS_RE = re.compile(
    r"^collect\s+prefetch\s+items\s*$", re.IGNORECASE
)
_PREFETCH_STATEMENT_RE = re.compile(r"^prefetch\s+(\S+)", re.IGNORECASE)
_DOWNLOAD_AS_RE = re.compile(r"^download(?:\s+now)?\s+as\s+(\S+)", re.IGNORECASE)
_DOWNLOAD_RE = re.compile(r"^download(?:\s+now)?\s+(\S+)\s*$", re.IGNORECASE)
_NAME_KV_RE = re.compile(r"\bname\s*=\s*(\S+)", re.IGNORECASE)
# `__Download\<name>` (or forward slash) on a command line; the name stops at
# whitespace, a quote, or another path separator
_DOWNLOAD_REF_RE = re.compile(r'__Download[\\/]([^\s"\'\\/]+)', re.IGNORECASE)
# producers whose output names cannot be known statically; their presence
# turns E513 off for the whole body
_UNKNOWABLE_PRODUCER_RE = re.compile(
    r"^(?:extract|unarchive|archive\s+now|utility)\b", re.IGNORECASE
)
# a bare `download` verb, any shape -- the fallback when neither download
# shape above matched (e.g. a URL with a space inside a substitution)
_DOWNLOAD_VERB_RE = re.compile(r"^download\b", re.IGNORECASE)
# `delete` / `folder delete` lines clean up the working directory; a
# `__Download\<name>` they mention is not a consumption of that file
_DELETE_RE = re.compile(r"^(?:folder\s+)?delete\b", re.IGNORECASE)
# `copy`/`move` lines can themselves populate `__Download`, either from a
# literal `__createfile`/`__appendfile` source (the sole __Download ref is
# the destination) or by renaming one download to another (>= 2 refs; the
# last is the destination, earlier ones are ordinary consumer references)
_MOVE_COPY_RE = re.compile(r"^(?:copy|move)\b", re.IGNORECASE)
_CREATEFILE_SOURCE_RE = re.compile(r"__(?:create|append)file\b", re.IGNORECASE)
# shell redirection into `__Download\<name>` creates that file
_REDIRECT_TARGET_RE = re.compile(
    r'>>?\s*"?__Download[\\/]([^\s"\'\\/]+)', re.IGNORECASE
)
_TERMINATOR_RE = re.compile(r"^(?:exit|restart|shutdown)\b", re.IGNORECASE)
_ACTION_PARAMETER_QUERY_RE = re.compile(r"^action\s+parameter\s+query\b", re.IGNORECASE)
_PARAMETER_RE = re.compile(r"^parameter\b", re.IGNORECASE)

# lines that do not count as "execution has started" for W502: declarations,
# prompts, structure, and prefetching
_NON_EXECUTION_RES = (
    _BEGIN_PREFETCH_BLOCK_RE,
    _END_PREFETCH_BLOCK_RE,
    _ADD_PREFETCH_ITEM_RE,
    _COLLECT_PREFETCH_ITEMS_RE,
    _PREFETCH_STATEMENT_RE,
    _PARAMETER_RE,
    _ACTION_PARAMETER_QUERY_RE,
    _IF_RE,
    _ELSEIF_RE,
    _ELSE_RE,
    _ENDIF_RE,
)


def _check_substitution_braces(lineno, line):
    """Check one line's `{...}` relevance substitutions for balance.

    A substitution must open and close on the same line: the agent evaluates
    it per line, so a `{` left open at end of line is not a substitution that
    continues, it is a broken one (E508). A `}` reached with none open is the
    mirror image (E509).

    `{{` is an escape, not an opener: it passes a literal `{` through to the
    command, so it neither opens a substitution nor makes the `}` that
    follows a substitution close -- that `}` pairs with the escape instead.
    `}}` is likewise a literal `}`, and the same escape holds *inside* an
    open substitution too: `{ ... "@{'k'='v'}}" ... }` (a PowerShell hashtable
    literal quoted inside the substitution) does not close on the first `}`
    of that `}}` -- the pair is a literal `}` in the string, and the
    substitution stays open for its real closing `}`. Escapes outside a
    substitution are counted so an escaped brace absorbs a later lone `}`
    rather than being reported as stray, which keeps this quiet on the
    escaping styles seen in real content.
    """
    issues = []
    open_col = None  # column of the `{` that opened the current substitution
    pending_escapes = 0  # `{{`/`}}` literals a lone `}` may pair with
    index = 0
    while index < len(line):
        char = line[index]
        if open_col is None:
            if line.startswith("{{", index) or line.startswith("}}", index):
                pending_escapes += 1
                index += 2
                continue
            if char == "{":
                open_col = index + 1
            elif char == "}":
                if pending_escapes:
                    pending_escapes -= 1
                else:
                    issues.append(
                        (
                            lineno,
                            "E509",
                            (
                                f"unbalanced }} at column {index + 1} -- no `{{` "
                                "relevance substitution is open on this line "
                                f"(`{{{{` passes a literal brace through); add "
                                f"`{SUBSTITUTION_MARKER}` if intentional"
                            ),
                        )
                    )
        elif char == "}":
            if line.startswith("}}", index):
                index += 2  # escaped literal }; the substitution stays open
                continue
            open_col = None
        index += 1

    if open_col is not None:
        issues.append(
            (
                lineno,
                "E508",
                (
                    f"unbalanced {{ at column {open_col} -- the relevance "
                    "substitution has no closing } before the end of the "
                    "line, and a substitution cannot span lines (`{{` passes "
                    f"a literal brace through); add `{SUBSTITUTION_MARKER}` "
                    "if intentional"
                ),
            )
        )
    return issues


def _url_basename(url):
    """Return the last path segment of a literal URL, or None if unknowable."""
    if "{" in url:
        return None
    base = url.rstrip("/").rsplit("/", 1)[-1]
    if not base or "://" in base or base == url.rstrip("/"):
        # no path at all (bare host), or nothing after the last slash
        return None
    return base


def _co_executable(path_a, path_b):
    """Return True only when two declarations are known to run together.

    Each path is a `{if_id: branch_index}` snapshot of which `if`/`elseif`/
    `else` branch was open, for every still-open `if`, at the moment a name
    was declared. Real BigFix content routinely guards platform-specific
    prefetch items with a *separate* `if` per platform (Windows, then a
    second unrelated `if` for mac, then another for Linux) rather than one
    `if`/`elseif` chain -- and this checker has no way to know those
    conditions are mutually exclusive. So this only calls two declarations
    co-executable -- a real E512 duplicate -- when their paths are exactly
    equal: both unconditional (empty path), or both reached through the
    identical sequence of branch choices. Anything reached via a different
    `if` (even one that looks platform-exclusive) is treated as potentially
    mutually exclusive and left unflagged, on the same false-alarm-is-worse
    principle E513's gating uses.
    """
    return path_a == path_b


def _check_download_names(lines):
    """Check prefetch/download producer names against `__Download\\` consumers.

    Returns E512 issues for a duplicate producer name that can co-execute
    with an earlier declaration of the same name (the second declaration
    would silently overwrite the first at runtime) -- declarations of the
    same name in mutually exclusive `if`/`elseif`/`else` branches (see
    `_co_executable`) are not flagged, since only one of them ever runs.
    Also returns E513 issues for a `__Download\\<name>` consumer no producer
    creates. E513 is conservative: the moment any producer's names are
    unknowable (an extract/unarchive/archive now/utility command, a
    `download` with no `as <name>` and no literal URL basename, or a
    name/URL containing a `{` substitution), the whole consumer check is
    skipped -- a missed typo is better than a false alarm. E512 still runs on
    the literal names that were collected.

    `copy`/`move` and shell-redirection (`>`, `>>`) lines can themselves
    create a file under `__Download`, not just consume one -- see
    `_MOVE_COPY_RE`/`_REDIRECT_TARGET_RE` below -- so they are also treated
    as producers where the destination name is determinable.
    """
    issues = []
    producers = {}  # lowercased name -> [(lineno, if-branch path), ...]
    knowable = True
    if_stack = []  # each entry: [if_id, branch_index]
    next_if_id = 0

    def current_path():
        return {if_id: branch for if_id, branch in if_stack}

    def produce(lineno, name):
        nonlocal knowable
        if name is None or "{" in name:
            knowable = False
            return
        name = name.strip("\"'").lower()
        if not name:
            knowable = False
            return
        path = current_path()
        declarations = producers.setdefault(name, [])
        for existing_lineno, existing_path in declarations:
            if _co_executable(path, existing_path):
                issues.append(
                    (
                        lineno,
                        "E512",
                        (
                            f'duplicate download name "{name}" (first '
                            f"declared on line {existing_lineno}, and both "
                            "can run in the same execution); the second "
                            "declaration silently overwrites the first; add "
                            f"`{DOWNLOAD_MARKER}` if intentional"
                        ),
                    )
                )
                break
        declarations.append((lineno, path))

    for index, raw_line in enumerate(lines):
        lineno = index + 1
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        # if/elseif/else/endif bookkeeping only -- pairing itself is E500/
        # E501/E505/E506's job elsewhere; an unbalanced endif here is
        # ignored rather than double-reported
        if _IF_RE.match(stripped):
            next_if_id += 1
            if_stack.append([next_if_id, 0])
            continue
        if _ELSEIF_RE.match(stripped) or _ELSE_RE.match(stripped):
            if if_stack:
                if_stack[-1][1] += 1
            continue
        if _ENDIF_RE.match(stripped):
            if if_stack:
                if_stack.pop()
            continue

        lowered = stripped.lower()
        if _UNKNOWABLE_PRODUCER_RE.match(stripped):
            knowable = False
            continue
        if lowered.startswith((BLOCK_PREFETCH, NOHASH_PREFETCH)):
            match = _NAME_KV_RE.search(stripped)
            produce(lineno, match.group(1) if match else None)
            continue
        if lowered.startswith(STATEMENT_PREFETCH):
            match = _PREFETCH_STATEMENT_RE.match(stripped)
            produce(lineno, match.group(1) if match else None)
            continue
        match = _DOWNLOAD_AS_RE.match(stripped)
        if match:
            produce(lineno, match.group(1))
            continue
        match = _DOWNLOAD_RE.match(stripped)
        if match:
            produce(lineno, _url_basename(match.group(1)))
            continue
        if _DOWNLOAD_VERB_RE.match(stripped):
            # a download of some other shape (a URL with a space inside a
            # `{...}` substitution does not match either regex above); its
            # target name is unknowable
            knowable = False
            continue

        if _MOVE_COPY_RE.match(stripped):
            refs = _DOWNLOAD_REF_RE.findall(stripped)
            has_createfile_source = bool(_CREATEFILE_SOURCE_RE.search(stripped))
            if has_createfile_source and refs:
                # source is __createfile/__appendfile, not a __Download ref;
                # the one __Download ref on the line is the destination
                produce(lineno, refs[-1])
            elif has_createfile_source and "{" in stripped:
                # `move __createfile "{download path "X"}"` -- a substituted
                # destination with no literal __Download ref to read back
                knowable = False
            elif not has_createfile_source and len(refs) >= 2:
                # renaming one download to another; the last ref is the new
                # name, earlier refs are ordinary consumer references
                produce(lineno, refs[-1])
            # a single __Download ref with no __createfile source is left
            # alone here -- it is an ordinary consumer reference (e.g.
            # `move __Download\typo.exe elsewhere`), checked as one below
            continue

        match = _REDIRECT_TARGET_RE.search(stripped)
        if match:
            produce(lineno, match.group(1))
            # fall through: the line may still hold other __Download refs
            # (a command being redirected, say) to check as consumers below

    if knowable:
        for index, raw_line in enumerate(lines):
            lineno = index + 1
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            if _DELETE_RE.match(stripped):
                # deleting `__Download\<name>` is cleanup, not consumption --
                # ensuring the working directory is clean before proceeding
                # is normal even when nothing downloads that name
                continue
            for name in _DOWNLOAD_REF_RE.findall(stripped):
                if "{" in name:  # a substituted name is unknowable; skip it
                    continue
                if name.lower() not in producers:
                    issues.append(
                        (
                            lineno,
                            "E513",
                            (
                                f"`__Download\\{name}` is referenced but nothing "
                                "prefetches or downloads a file of that name; "
                                f"add `{DOWNLOAD_MARKER}` if intentional"
                            ),
                        )
                    )
    return issues


def check_actionscript(body):
    """Check a single ActionScript body for balanced blocks and substitutions.

    Walks `if`/`endif` and `begin`/`end prefetch block` pairing across lines,
    and `{...}` relevance-substitution braces within each line.

    Returns a sorted list of (lineno, code, message), lineno 1-based into
    `body`. `_mask_heredocs` blanks out `createfile until` block content
    first, so lines that only look like commands inside one are ignored (its
    own E302 belongs to the sibling schclass hook, not here).
    """
    lines, _createfile_issues = _mask_heredocs(body.split("\n"))
    issues = _check_download_names(lines)  # E512 / E513
    if_stack = []  # each entry: [lineno, seen_else]
    prefetch_stack = []  # each entry: [lineno, if_depth_at_open]
    preamble_over = False  # True once anything a prefetch block may not follow
    first_execution_lineno = None  # first line that starts real execution
    terminated_lineno = None  # unconditional exit/restart/shutdown, if any
    unreachable_reported = False  # W501 fires once, on the first dead line

    for index, raw_line in enumerate(lines):
        lineno = index + 1
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        # brace balance is per line and independent of the block walk below,
        # so it runs before any of the `continue`s that dispatch on the verb.
        # The raw line is passed, not `stripped`, so reported columns line up
        # with the file.
        issues.extend(_check_substitution_braces(lineno, raw_line))

        # unreachable code (W501): anything after an unconditional
        # exit/restart/shutdown never runs; report the first such line only
        if terminated_lineno is not None and not unreachable_reported:
            unreachable_reported = True
            issues.append(
                (
                    lineno,
                    "W501",
                    (
                        "unreachable: the unconditional "
                        f"exit/restart/shutdown on line {terminated_lineno} "
                        "means this line can never run; add "
                        f"`{UNREACHABLE_MARKER}` if intentional"
                    ),
                )
            )

        if _ACTION_PARAMETER_QUERY_RE.match(stripped):
            if first_execution_lineno is not None:
                issues.append(
                    (
                        lineno,
                        "W502",
                        (
                            "`action parameter query` after execution began "
                            f"on line {first_execution_lineno}; these are "
                            "console-time prompts and belong at the top; add "
                            f"`{PARAMETER_QUERY_MARKER}` if intentional"
                        ),
                    )
                )
            continue  # a prompt is preamble: opens/closes/starts nothing below

        # placement bookkeeping for E515 and W502. `parameter` assignments
        # and `action parameter query` (handled above) are preamble; anything
        # else -- a prefetch block included -- ends the preamble.
        is_preamble_line = bool(_PARAMETER_RE.match(stripped))
        if _TERMINATOR_RE.match(stripped) and not if_stack:
            terminated_lineno = lineno
        if first_execution_lineno is None and not any(
            regex.match(stripped) for regex in _NON_EXECUTION_RES
        ):
            first_execution_lineno = lineno
        # any non-preamble line ends the preamble -- except the
        # `begin prefetch block` line itself, whose own branch below must see
        # the preamble state as it was BEFORE the block (and then ends it)
        if not is_preamble_line and not _BEGIN_PREFETCH_BLOCK_RE.match(stripped):
            preamble_over = True

        if _BEGIN_PREFETCH_BLOCK_RE.match(stripped):
            # a nested block is E504 below; E515 on top of it would be noise
            if preamble_over and not prefetch_stack:
                issues.append(
                    (
                        lineno,
                        "E515",
                        (
                            "`begin prefetch block` is not at the top of the "
                            "script -- only blank lines, // comments, `action "
                            "parameter query`, and `parameter` assignments "
                            "may precede it; add "
                            f"`{PREFETCH_PLACEMENT_MARKER}` if intentional"
                        ),
                    )
                )
            preamble_over = True
            if prefetch_stack:
                issues.append(
                    (
                        lineno,
                        "E504",
                        (
                            "`begin prefetch block` nested inside another "
                            "prefetch block; prefetch blocks do not nest; "
                            f"add `{PREFETCH_BLOCK_MARKER}` if intentional"
                        ),
                    )
                )
            # pushed regardless of nesting, so a nested pair's own
            # `end prefetch block` still matches up and does not also
            # misreport as a stray E503
            prefetch_stack.append([lineno, len(if_stack)])
            continue

        if _END_PREFETCH_BLOCK_RE.match(stripped):
            if not prefetch_stack:
                issues.append(
                    (
                        lineno,
                        "E503",
                        (
                            "`end prefetch block` with no open `begin prefetch "
                            f"block`; add `{PREFETCH_BLOCK_MARKER}` if "
                            "intentional"
                        ),
                    )
                )
            else:
                open_lineno, if_depth_at_open = prefetch_stack.pop()
                if len(if_stack) > if_depth_at_open:
                    issues.append(
                        (
                            lineno,
                            "E507",
                            (
                                "`if` opened inside a prefetch block is still "
                                "open at `end prefetch block`; blocks "
                                "interleave rather than nest; add "
                                f"`{BLOCK_NESTING_MARKER}` if intentional"
                            ),
                        )
                    )
            continue

        if _ADD_PREFETCH_ITEM_RE.match(stripped):
            if not prefetch_stack:
                issues.append(
                    (
                        lineno,
                        "E510",
                        (
                            "`add prefetch item` outside an open `begin "
                            "prefetch block`; the agent rejects it there; add "
                            f"`{PREFETCH_PLACEMENT_MARKER}` if intentional"
                        ),
                    )
                )
            continue

        if _COLLECT_PREFETCH_ITEMS_RE.match(stripped):
            if not prefetch_stack:
                issues.append(
                    (
                        lineno,
                        "E511",
                        (
                            "`collect prefetch items` outside an open `begin "
                            "prefetch block`; the agent rejects it there; add "
                            f"`{PREFETCH_PLACEMENT_MARKER}` if intentional"
                        ),
                    )
                )
            continue

        if _IF_RE.match(stripped):
            condition = stripped[_IF_RE.match(stripped).end() :].lstrip()
            if not condition.startswith("{"):
                issues.append(
                    (
                        lineno,
                        "E514",
                        (
                            "`if` condition is not a `{...}` relevance "
                            "substitution; the agent requires one; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            if_stack.append([lineno, False])
            continue

        if _ELSEIF_RE.match(stripped):
            condition = stripped[_ELSEIF_RE.match(stripped).end() :].lstrip()
            if not condition.startswith("{"):
                issues.append(
                    (
                        lineno,
                        "E514",
                        (
                            "`elseif` condition is not a `{...}` relevance "
                            "substitution; the agent requires one; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            if not if_stack:
                issues.append(
                    (
                        lineno,
                        "E505",
                        (
                            f"`elseif` outside any open `if`; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            elif if_stack[-1][1]:
                issues.append(
                    (
                        lineno,
                        "E506",
                        (
                            "`elseif` after `else` for the same `if`; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            continue

        if _ELSE_RE.match(stripped):
            if not if_stack:
                issues.append(
                    (
                        lineno,
                        "E505",
                        (
                            f"`else` outside any open `if`; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            elif if_stack[-1][1]:
                issues.append(
                    (
                        lineno,
                        "E506",
                        (
                            "second `else` for the same `if`; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            else:
                if_stack[-1][1] = True
            continue

        if _ENDIF_RE.match(stripped):
            if not if_stack:
                issues.append(
                    (
                        lineno,
                        "E501",
                        (
                            f"`endif` with no open `if`; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            else:
                if_stack.pop()
            continue

    for open_lineno, _seen_else in if_stack:
        issues.append(
            (
                open_lineno,
                "E500",
                (
                    f"`if` is never closed by `endif`; add "
                    f"`{IF_MARKER}` if intentional"
                ),
            )
        )
    for open_lineno, _if_depth_at_open in prefetch_stack:
        issues.append(
            (
                open_lineno,
                "E502",
                (
                    "`begin prefetch block` is never closed by `end prefetch "
                    f"block`; add `{PREFETCH_BLOCK_MARKER}` if intentional"
                ),
            )
        )
    return sorted(issues)


def _iter_actionscript_bodies(raw):
    """Yield (sourceline, body) for every BigFix ActionScript in a BES document.

    Raises etree.XMLSyntaxError if the document does not parse; the callers
    turn that into W500. MIMEType is compared case-insensitively: it is valid
    BigFix content either way.
    """
    root = etree.fromstring(raw)
    for element in root.iter("ActionScript"):
        mimetype = element.get("MIMEType")
        if mimetype is not None and mimetype.strip().lower() != ACTIONSCRIPT_MIMETYPE:
            continue
        yield element.sourceline, element.text or ""


def _validate_bes_xml(raw):
    """Check block balance in every ActionScript of a BES document."""
    try:
        bodies = list(_iter_actionscript_bodies(raw))
    except etree.XMLSyntaxError as err:
        return [(1, "W500", f"not parseable BES XML ({err}); skipping")]
    issues = []
    for sourceline, body in bodies:
        for lineno, code, message in check_actionscript(body):
            issues.append((sourceline + lineno - 1, code, message))
    return issues


def is_bes_file(path):
    """Return True if `path` has a BES XML extension."""
    return path.endswith(BES_EXTENSIONS)


def check_file(path, disabled=frozenset()):
    """Check a single file; return (issues, fixed).

    `fixed` is always [].

    This hook has no auto-fixes, so the second element of the tuple exists
    only to keep the (issues, fixed) contract the other hooks share.
    """
    if not os.path.isfile(path):
        return [(1, "W500", "file not found; skipping")], []

    with open(path, "rb") as handle:
        raw = handle.read()
    src = (
        raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    )

    if SKIP_MARKER in src:
        return [], []
    if MUSTACHE_RE.search(src):
        return [], []

    if is_bes_file(path):
        issues = _validate_bes_xml(raw)
    else:
        issues = check_actionscript(src)

    opt_outs = {marker for code, marker in CHECK_MARKERS.items() if marker in src}
    issues = [
        (lineno, code, message)
        for lineno, code, message in issues
        if code not in disabled and CHECK_MARKERS.get(code) not in opt_outs
    ]
    return sorted(issues), []


def check_files(paths, disabled=frozenset()):
    """Check several files; return a list of (path, issues, fixed) tuples.

    This is the programmatic entry point: it does no printing.
    """
    results = []
    for path in paths:
        issues, fixed = check_file(path, disabled=disabled)
        results.append((path, issues, fixed))
    return results


def discover_bes_files(root="."):
    """Return all .bes files under `root`, pruning hidden and noise directories."""
    skip_dirs = {"__pycache__", "node_modules"}
    root = os.path.normpath(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d not in skip_dirs
        ]
        for name in filenames:
            if name.endswith(".bes"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def _report(results):
    """Print every issue in `results`; return (issue_count, warning_count)."""
    issue_count = 0
    warning_count = 0
    for path, issues, _fixed in results:
        for lineno, check_id, message in issues:
            if check_id.startswith("W"):
                warning_count += 1
                print(f"{path}:{lineno}: [{check_id}] warning: {message}")
            else:
                issue_count += 1
                print(f"{path}:{lineno}: [{check_id}] {message}")
    return issue_count, warning_count


def main(argv=None):
    """Execution starts here.

    argv defaults to None so this works both as a console_scripts entry point
    (pre-commit calls it with no arguments; argparse then reads sys.argv) and
    when called directly as `main(sys.argv[1:])`.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as failures (non-zero exit); default: advisory",
    )
    parser.add_argument(
        "--disable",
        default="",
        metavar="CODES",
        help="comma-separated check IDs to skip entirely, e.g. --disable E501",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help=(
            "files to check (.bes/.ojo are read as BES XML, anything else as "
            "raw ActionScript); if omitted, all *.bes files in the current "
            "folder and below are checked"
        ),
    )
    args = parser.parse_args(argv)

    disabled = {
        code.strip().upper() for code in args.disable.split(",") if code.strip()
    }
    unknown = disabled - KNOWN_CODES
    if unknown:
        print(
            f"warning: ignoring unknown --disable code(s): {', '.join(sorted(unknown))}"
        )

    paths = args.files if args.files else discover_bes_files(".")
    issue_count, warning_count = _report(check_files(paths, disabled=disabled))

    if warning_count:
        print(f"{warning_count} warning(s).")
    if issue_count:
        print(f"{issue_count} issue(s).")
    return 1 if (issue_count or (warning_count and args.strict)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
