#!/usr/bin/env python3
"""Pre-commit hook: validate BigFix prefetch lines in ActionScript.

Finds every prefetch line in every <ActionScript> body of a BES file (and, for
non-.bes/.ojo paths, in the whole file read as one raw ActionScript body) and
hands it to `validate_prefetch()` from the
[bigfix_prefetch](https://pypi.org/project/bigfix-prefetch/) package, which is
the reference implementation of what a valid prefetch is. Both spellings are
covered:

    prefetch <name> sha1:<40> size:<n> <url> sha256:<64>
    add prefetch item name=<name> sha1=<40> size=<n> url=<url> sha256=<64>

SCOPE: this hook only answers "is this prefetch line internally valid" --
size present and > 0, hash lengths right, sha1 mandatory in a prefetch
statement, sha256 present. It is deliberately offline: nothing here downloads
the URL or checks that the hashes match the real file. The line's overall
shape and its http-vs-https scheme are W206/W207 in bes-conventions-check, and
its lexical validity is E300 in bes-actionscript-lint-schclass -- three
altitudes on the same line, all intentional.

Checks:
    E400  a prefetch line is invalid; the reason is the message
          `validate_prefetch()` reported (bad size, wrong hash length, a
          missing mandatory sha1, an unparsable line, ...)
    E401  a prefetch line has no sha256. Upstream treats sha256 as optional
          unless asked; this hook treats it as mandatory, because in 2026 it
          is what enhanced security requires. It is its own code so a repo
          that still wants it optional can `--disable E401`.
    W400  the file is not parseable BES XML; skipped (advisory --
          bes-schema-validate is the authority on file validity)
    W402  a prefetch block item has no sha1; technically valid, but unusual
    W403  an `add nohash prefetch item` line: hashless by definition, so it is
          reported rather than validated -- the download cannot be verified

E-codes are real issues and fail the hook. W-codes are advisory and do NOT
fail the hook unless --strict is given. This hook has no auto-fixes: the right
size and hashes are properties of the real file, which only a download can
learn.

Lines whose values are not knowable until the agent runs are skipped: a line
containing a `{...}` relevance substitution (a dynamic prefetch) has no fixed
size or hash to check, and `//` comment lines are not commands. The raw
content of a `createfile until <MARKER>` block is file text, not ActionScript,
so a prefetch-looking line inside one is skipped too.

Only <ActionScript> elements with MIMEType application/x-Fixlet-Windows-Shell
(or no MIMEType, which defaults to it) are BigFix ActionScript; other bodies
are other languages and are skipped silently. Bodies are extracted with lxml,
so entities are decoded and adjacent CDATA sections merged, with lxml's
sourceline mapping issues back to file line numbers.

Usage:
    bes_actionscript_validate_prefetch.py [--strict] [--disable E401]
                                          [file ...]

With no file arguments, all *.bes files in the current folder and below are
checked.

A file whose prefetches knowingly do not meet these rules opts out of every
check here with `prefetch-ok` anywhere in it, e.g.

    <!-- prefetch-ok -->

which is the same marker that opts out of the prefetch-shape warning (W206) in
bes-conventions-check: one judgement, one marker. The longer

    <!-- pre-commit-skip: bes-actionscript-validate-prefetch -->

also skips the file, and matches the other hooks' spelling. To turn a check
off across a whole repo instead of file by file, disable its code in the hook
args -- `--disable E401` is the way back to sha256-optional.

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
import warnings

from bigfix_prefetch.prefetch_validate import validate_prefetch
from lxml import etree

if __package__ in (None, ""):  # run directly as a script, not as a module
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# `_mask_heredocs` is shared with the sibling ActionScript hook on purpose:
# both need to know that the lines inside a `createfile until` block are file
# content rather than commands, and one implementation of that rule is enough.
from pre_commit_bigfix.bes_actionscript_lint_schclass import _mask_heredocs

SKIP_MARKER = "pre-commit-skip: bes-actionscript-validate-prefetch"

# The one opt-out marker (matched anywhere in the file text): a file whose
# prefetches are knowingly not up to standard opts out of the whole hook, not
# one code at a time. A repo that wants a check off everywhere disables the
# code instead, with --disable. NOTE: this is the same marker that opts out of
# W206 in bes-conventions-check, so a file carrying it opts out of both -- the
# two are the same judgement ("these prefetch lines are intentional"), and one
# marker is what was asked for.
PREFETCH_MARKER = "prefetch-ok"

KNOWN_CODES = frozenset(["E400", "E401", "W400", "W402", "W403"])

BES_EXTENSIONS = (".bes", ".ojo")

# the one MIMEType that IS BigFix ActionScript; a missing MIMEType defaults to
# it, every other value is some other language and holds no prefetch lines.
ACTIONSCRIPT_MIMETYPE = "application/x-Fixlet-Windows-Shell"

# `add nohash prefetch item` is the documented hashless form; it is matched
# before the hashed form so it is reported (W403), not validated.
NOHASH_PREFETCH = "add nohash prefetch item"
BLOCK_PREFETCH = "add prefetch item"
STATEMENT_PREFETCH = "prefetch "

MUSTACHE_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)


def find_prefetch_lines(body):
    """Yield (lineno, line, is_nohash) for each prefetch line in `body`.

    Line numbers are local to the body, 1-based. Comment lines, lines holding
    a `{...}` relevance substitution, and the raw content of a
    `createfile until` block are not yielded -- see the module docstring.
    """
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    masked, _issues = _mask_heredocs(body.split("\n"))
    for lineno, line in enumerate(masked, start=1):
        stripped = line.strip()
        lowered = stripped.lower()
        if not stripped or lowered.startswith("//"):
            continue
        is_nohash = lowered.startswith(NOHASH_PREFETCH)
        if not is_nohash and not lowered.startswith(
            (BLOCK_PREFETCH, STATEMENT_PREFETCH)
        ):
            continue
        if "{" in stripped:
            continue  # a dynamic prefetch: no fixed size or hash to check
        yield lineno, stripped, is_nohash


def _first_line(message):
    """Return a warning message as one line (validate_prefetch appends the raw)."""
    return str(message).strip().splitlines()[0].strip()


def _is_missing(message, hash_name):
    """Say whether `message` is the "<hash_name> is missing" reason."""
    lowered = message.lower()
    return hash_name in lowered and "missing" in lowered


def validate_prefetch_line(line):
    """Validate one prefetch line; return [(code, message)].

    Wraps `validate_prefetch()` from bigfix_prefetch: its verdict is the
    return value and its reasons are `warnings`, so the warnings are captured
    and turned into this hook's codes. A missing sha256 is pulled out of the
    verdict into its own E401 -- upstream treats it as optional-unless-asked,
    this hook treats it as mandatory, and giving it a code of its own is what
    lets `--disable E401` put it back to optional for a repo that wants that.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")  # the same reason may repeat per line
        try:
            valid = validate_prefetch(line)
        except (AttributeError, TypeError, ValueError) as err:
            # validate_prefetch handles the unparsable-line case itself (its
            # regexes returning None); this is the belt-and-braces path for a
            # shape it does not, so one odd line cannot abort a whole run.
            return [("E400", f"prefetch line could not be validated ({err})")]
    messages = [_first_line(entry.message) for entry in caught]

    issues = []
    # a missing sha1 escalates sha256 to mandatory upstream, so the "sha256 is
    # missing" reason can arrive as either a warning or the failure reason.
    if any(_is_missing(message, "sha256") for message in messages):
        issues.append(
            (
                "E401",
                (
                    "prefetch has no sha256; it is technically optional, but "
                    "treated as mandatory here -- add one, or "
                    f"`{PREFETCH_MARKER}` if intentional"
                ),
            )
        )
    if any(_is_missing(message, "sha1") for message in messages):
        issues.append(
            (
                "W402",
                (
                    "prefetch has no sha1, which is unusual though valid in a "
                    f"prefetch block; add `{PREFETCH_MARKER}` if intentional"
                ),
            )
        )

    if not valid:
        reasons = [m for m in messages if m.lower().startswith("error")] or messages
        # the missing sha256 is already reported as E401 above; anything left
        # is a separate defect and is what E400 is for.
        reasons = [m for m in reasons if not _is_missing(m, "sha256")]
        if reasons:
            reported = "; ".join(dict.fromkeys(reasons))
            issues.append(
                (
                    "E400",
                    (
                        f"invalid prefetch: {reported}; add `{PREFETCH_MARKER}` "
                        "if intentional"
                    ),
                )
            )
        elif not issues:  # failed for a reason nothing reported; do not swallow it
            issues.append(
                (
                    "E400",
                    (
                        "invalid prefetch: reason not reported; add "
                        f"`{PREFETCH_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def validate_actionscript(body):
    """Validate every prefetch line in one ActionScript body.

    Returns sorted [(lineno, code, message)] with line numbers local to the
    body, 1-based.
    """
    issues = []
    for lineno, line, is_nohash in find_prefetch_lines(body):
        if is_nohash:
            issues.append(
                (
                    lineno,
                    "W403",
                    (
                        "`add nohash prefetch item` downloads without a hash, so "
                        "the file cannot be verified and is not validated here; "
                        f"prefer a hashed prefetch, or add `{PREFETCH_MARKER}` if "
                        "intentional"
                    ),
                )
            )
            continue
        for code, message in validate_prefetch_line(line):
            issues.append((lineno, code, message))
    return sorted(issues)


def _validate_bes_xml(raw):
    """Validate prefetches in every ActionScript of a BES document."""
    try:
        root = etree.fromstring(raw)
    except etree.XMLSyntaxError as err:
        return [(1, "W400", f"not parseable BES XML ({err}); skipping")]
    issues = []
    for element in root.iter("ActionScript"):
        mimetype = element.get("MIMEType")
        if mimetype is not None and mimetype != ACTIONSCRIPT_MIMETYPE:
            continue
        body = element.text or ""
        for lineno, code, message in validate_actionscript(body):
            issues.append((element.sourceline + lineno - 1, code, message))
    return issues


def check_file(path, disabled=frozenset(), strict=False):
    """Check one file; return (issues, fixed) like the sibling checkers.

    `fixed` is always [] (this hook has no auto-fixes -- the correct size and
    hashes are properties of the real file); the tuple shape stays parallel
    with the sibling hooks. `strict` is accepted for the same parity and does
    not change what is reported (the caller decides whether warnings fail).
    """
    del strict  # reported issues are the same either way
    if not os.path.isfile(path):
        return [(1, "W400", "file not found; skipping")], []

    with open(path, "rb") as handle:
        raw = handle.read()
    src = (
        raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    )

    if SKIP_MARKER in src:
        return [], []
    if MUSTACHE_RE.search(src):
        return [], []

    if path.endswith(BES_EXTENSIONS):
        issues = _validate_bes_xml(raw)
    else:
        issues = validate_actionscript(src)

    issues = [
        (lineno, code, message)
        for lineno, code, message in issues
        if code not in disabled and PREFETCH_MARKER not in src
    ]
    return sorted(issues), []


def check_files(paths, disabled=frozenset(), strict=False):
    """Check several files; return a list of (path, issues, fixed) tuples.

    This is the programmatic entry point: it does no printing.
    """
    return [
        (path, *check_file(path, disabled=disabled, strict=strict)) for path in paths
    ]


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
        help=(
            "comma-separated check IDs to skip entirely, e.g. --disable E401 "
            "for a repo that still treats sha256 as optional"
        ),
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

    issue_count = 0
    warning_count = 0
    for path, issues, _fixed in check_files(
        paths, disabled=disabled, strict=args.strict
    ):
        for lineno, check_id, message in issues:
            if check_id.startswith("W"):
                warning_count += 1
                print(f"{path}:{lineno}: [{check_id}] warning: {message}")
            else:
                issue_count += 1
                print(f"{path}:{lineno}: [{check_id}] {message}")

    if warning_count:
        print(f"{warning_count} prefetch warning(s).")
    if issue_count:
        print(f"{issue_count} prefetch issue(s).")
    return 1 if (issue_count or (warning_count and args.strict)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
