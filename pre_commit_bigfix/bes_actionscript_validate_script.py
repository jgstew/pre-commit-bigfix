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
    W500  the file is not parseable BES XML; skipped (advisory --
          bes-schema-validate is the authority on file validity)

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

SKIP_MARKER = "pre-commit-skip: bes-actionscript-validate-script"

# per-check-family opt-out markers (matched anywhere in the file text)
IF_MARKER = "actionscript-if-ok"  # E500, E501, E505, E506
PREFETCH_BLOCK_MARKER = "actionscript-prefetch-block-ok"  # E502, E503, E504
BLOCK_NESTING_MARKER = "actionscript-block-nesting-ok"  # E507

CHECK_MARKERS = {
    "E500": IF_MARKER,
    "E501": IF_MARKER,
    "E505": IF_MARKER,
    "E506": IF_MARKER,
    "E502": PREFETCH_BLOCK_MARKER,
    "E503": PREFETCH_BLOCK_MARKER,
    "E504": PREFETCH_BLOCK_MARKER,
    "E507": BLOCK_NESTING_MARKER,
}

KNOWN_CODES = frozenset(
    ["E500", "E501", "E502", "E503", "E504", "E505", "E506", "E507", "W500"]
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


def check_actionscript(body):
    """Check a single ActionScript body for balanced if/prefetch-block pairing.

    Returns a sorted list of (lineno, code, message), lineno 1-based into
    `body`. `_mask_heredocs` blanks out `createfile until` block content
    first, so lines that only look like commands inside one are ignored (its
    own E302 belongs to the sibling schclass hook, not here).
    """
    lines, _createfile_issues = _mask_heredocs(body.split("\n"))
    issues = []
    if_stack = []  # each entry: [lineno, seen_else]
    prefetch_stack = []  # each entry: [lineno, if_depth_at_open]

    for index, raw_line in enumerate(lines):
        lineno = index + 1
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        if _BEGIN_PREFETCH_BLOCK_RE.match(stripped):
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

        if _IF_RE.match(stripped):
            if_stack.append([lineno, False])
            continue

        if _ELSEIF_RE.match(stripped):
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
