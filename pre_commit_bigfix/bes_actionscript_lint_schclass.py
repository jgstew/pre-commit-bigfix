#!/usr/bin/env python3
"""Pre-commit hook: lint BigFix ActionScript against the console's schclass grammar.

Lints every <ActionScript> body in a BES file (and, for non-.bes/.ojo paths,
the whole file as one raw ActionScript body) against the BigFix console's own
lexical grammar: the vendored schclass_data/ExpandedActionScript.schclass (the
lex schema the console's SyntaxEdit editor uses, 323 command verbs) merged
with schclass_data/bigfix_overrides.schclass (validation corrections the
display grammar needs: an https: URL class, the `surrender device id` verb the
console generator drops, `}` as a URL end separator, and the keyword=value
option lines of `override wait` / `override run` blocks).

SCOPE: this hook is deliberately limited to what the schclass grammar can
decide -- lexical validity of each line -- plus the two BLOCK constructs the
grammar cannot express but which decide whether a line is a command at all:
`createfile until` heredocs (E302) and `override run` / `override wait` option
blocks (E303). ActionScript checks that need knowledge neither carries
(per-verb argument shapes, if/endif and prefetch-block pairing, the
`]]></ActionScript>` closing-tag whitespace trap, http-vs-https escalation,
and any auto-fixes) belong in a sibling ActionScript hook, not here. Keeping the split means this hook stays a thin,
mechanical consumer of the grammar files and needs no edits when BigFix ships
new command verbs -- only the vendored schclass does.

The rule (per jgstew/pre-commit-bigfix#3): the first token of every line must
be a known command verb, a `//` comment, a `{...}` relevance substitution, a
continuation of a state carried across the line break with a backslash, or the
line must be blank. Verbs match case-insensitively (the agent accepts `RUN`),
but a non-lowercase verb is warned about. Lines inside a
`createfile until <MARKER>` block are raw file content and are not linted;
the block must reach its bare marker line. An `override run` / `override wait`
line opens a block whose following `keyword=value` lines are options, not
commands, and are checked against the documented keywords and values instead.

Only <ActionScript> elements with MIMEType application/x-Fixlet-Windows-Shell
(or no MIMEType, which defaults to it) are BigFix ActionScript; x-sh,
x-AppleScript, x-Fixlet-Windows-PowerShell, and text/x-uri bodies are other
languages and are skipped silently (an unknown MIMEType is E200's problem in
bes-conventions-check).

Checks:
    E300  a line's first token is not a known command verb, a // comment, a
          {...} substitution, a continuation, or blank
    E301  a {...} relevance substitution has no closing } before line end
    E302  a `createfile until <MARKER>` block never reaches its marker line
    E303  an `override run` / `override wait` option line is wrong: an unknown
          keyword, no value, a value outside the documented set for that
          keyword, a non-integer `timeout_seconds`, or a `keyword=value` option
          line outside any override block
    W300  the file is not parseable BES XML; skipped (advisory --
          bes-schema-validate is the authority on file validity)
    W301  a "..." string has no closing " before line end (often benign in
          ActionScript arguments, so a warning)
    W302  a matched command verb is not lowercase (e.g. `RUN`; valid but
          unconventional)
    W303  an override option keyword or value is not lowercase (e.g. `RunAs`;
          valid but unconventional)

E-codes are real issues and fail the hook. W-codes are advisory and do NOT
fail the hook unless --strict is given. This hook has no auto-fixes and is not
expected to grow any: rewriting content is beyond what a lexical grammar can
justify (see SCOPE above).

XML bodies are extracted with lxml, so the linted text is the REAL
ActionScript exactly as the agent sees it: entities decoded, adjacent CDATA
sections merged, with lxml's sourceline mapping issues back to file line
numbers.

Usage:
    bes_actionscript_lint_schclass.py [--strict] [--disable E300,W302] [file ...]

With no file arguments, all *.bes files in the current folder and below are
checked. Non-.bes/.ojo paths given explicitly are linted as raw ActionScript
text.

A file can opt out of all checks with a comment anywhere in it:
    <!-- pre-commit-skip: bes-actionscript-lint-schclass -->
or out of a single check family with the matching marker anywhere in the file:
    actionscript-verb-ok           (E300)
    actionscript-substitution-ok   (E301)
    actionscript-createfile-ok     (E302)
    actionscript-override-ok       (E303)
    actionscript-string-ok         (W301)
    actionscript-case-ok           (W302)
    actionscript-override-case-ok  (W303)

Files that look like mustache templates (containing `{{ ... }}`) are skipped
silently: they are not real content until rendered.

Known limitations: multi-word verbs need single spaces (`add  prefetch item`
does not match -- the console colorizer behaves the same way); a line of a
multi-line string that happens to start with `createfile until` is mistaken
for a heredoc opener. A dynamic `download` line is lexically VALID here while
still advisory-warned (W211) in bes-conventions-check -- different altitudes,
both intentional.

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

from pre_commit_bigfix import schclass
from pre_commit_bigfix.schclass_tokenizer import Tokenizer

SKIP_MARKER = "pre-commit-skip: bes-actionscript-lint-schclass"

# per-check opt-out markers (matched anywhere in the file text)
VERB_MARKER = "actionscript-verb-ok"  # E300
SUBSTITUTION_MARKER = "actionscript-substitution-ok"  # E301
CREATEFILE_MARKER = "actionscript-createfile-ok"  # E302
OVERRIDE_MARKER = "actionscript-override-ok"  # E303
STRING_MARKER = "actionscript-string-ok"  # W301
CASE_MARKER = "actionscript-case-ok"  # W302
OVERRIDE_CASE_MARKER = "actionscript-override-case-ok"  # W303

CHECK_MARKERS = {
    "E300": VERB_MARKER,
    "E301": SUBSTITUTION_MARKER,
    "E302": CREATEFILE_MARKER,
    "E303": OVERRIDE_MARKER,
    "W301": STRING_MARKER,
    "W302": CASE_MARKER,
    "W303": OVERRIDE_CASE_MARKER,
}

KNOWN_CODES = frozenset(
    ["E300", "E301", "E302", "E303", "W300", "W301", "W302", "W303"]
)

BES_EXTENSIONS = (".bes", ".ojo")

# the one MIMEType that IS BigFix ActionScript; a missing MIMEType defaults to
# it, every other value is some other language and is not linted here.
ACTIONSCRIPT_MIMETYPE = "application/x-Fixlet-Windows-Shell"

HEREDOC_VERB = "createfile until"

# --- `override run` / `override wait` option blocks --------------------------
# An override block is the verb line, then one `keyword=value` option line per
# option, then the real command line, which closes the block:
#     override wait
#     hidden=true
#     wait notepad.exe
# None of this is expressible in the schclass grammar (the option keywords are
# only commands INSIDE a block, and their values may be relevance
# substitutions), so it lives here as line state -- see SCOPE above.
#
# Keyword and value sets are from
# https://developer.bigfix.com/action-script/reference/execution/override.html
# and may not be exhaustive; the reference is the place to check when a new
# option appears. `None` means the reference gives no closed value set, so only
# the keyword is checked. Keywords are documented case-insensitive, and values
# "can be enclosed in {curly brackets} for Relevance substitution", so a value
# holding a `{` is accepted unchecked -- its real value is not known until the
# agent runs.
OVERRIDE_VERBS = frozenset(["override run", "override wait"])

OVERRIDE_OPTIONS = {
    "completion": frozenset(["none", "process", "job"]),
    "priority": frozenset(["normal", "low"]),
    "hidden": frozenset(["true", "false"]),
    "detached": frozenset(["true", "false"]),
    "runas": frozenset(["agent", "currentuser", "localuser"]),
    "user": None,  # a user name or a relevance expression
    "password": frozenset(["required", "empty", "impersonate", "system"]),
    "asadmin": frozenset(["true", "interactive"]),
    "targetuser": None,  # a user name
    "timeout_seconds": None,  # checked as an integer, not against a value set
    "disposition": frozenset(["terminate", "abandon"]),
}

# 0 is the documented default (meaning "no timeout"), so it must be writable
OVERRIDE_INTEGER_OPTIONS = frozenset(["timeout_seconds"])
INTEGER_RE = re.compile(r"[0-9]+\Z")

OVERRIDE_OPTION_RE = re.compile(r"[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*=(.*)\Z")

# an unrendered mustache template ({{ placeholder }}) is not real content yet.
# Only an identifier-like placeholder counts: `{{` is also the ActionScript
# escape for a literal `{`, so heredoc payloads (YARA, JSON, C#) contain `{{`
# around arbitrary content and must not be mistaken for a template.
# Kept identical in all four hooks -- see the lockstep test in
# tests/test_bes_actionscript_validate_script.py.
MUSTACHE_RE = re.compile(r"\{\{\s*[#/^!&>]?\s*[\w.-]+\s*\}\}")

_TOKENIZER = None


def _default_tokenizer():
    """Return the shared Tokenizer over the merged default grammar (lazy)."""
    global _TOKENIZER
    if _TOKENIZER is None:
        _TOKENIZER = Tokenizer(
            schclass.load_default_actionscript_schema(),
            case_insensitive=True,
            relaxed_bol=True,
        )
    return _TOKENIZER


def _mask_heredocs(lines):
    """Blank out `createfile until` block content; return (masked, issues).

    A `createfile until <MARKER>` line starts a block whose following lines
    (up to and including the exact bare marker line) are raw file content, not
    ActionScript -- the lexical grammar cannot express this, so they are
    replaced with empty lines (keeping line numbers aligned) before
    tokenizing. An indented marker line does NOT close the block. A block
    that never reaches its marker is an E302 and masks to the end.
    """
    masked = list(lines)
    issues = []
    index = 0
    while index < len(masked):
        stripped = masked[index].strip()
        lowered = stripped.lower()
        marker = None
        if lowered.startswith(HEREDOC_VERB):
            rest = stripped[len(HEREDOC_VERB) :]
            if rest[:1] in (" ", "\t"):
                marker = rest.strip()
        if not marker:
            index += 1
            continue
        end = index + 1
        while end < len(masked) and masked[end] != marker:
            masked[end] = ""
            end += 1
        if end >= len(masked):
            issues.append(
                (
                    index + 1,
                    "E302",
                    (
                        f'createfile until marker "{marker}" is never found before '
                        f"the end of the ActionScript; add `{CREATEFILE_MARKER}` "
                        "if intentional"
                    ),
                )
            )
            break
        masked[end] = ""  # the marker line itself is the terminator, not a verb
        index = end + 1
    return masked, issues


def _override_value(raw):
    """Return an option line's value, less a trailing //comment and quotes."""
    value = raw.strip()
    if "{" not in value:  # a substitution may legitimately contain '//'
        value = value.split("//")[0].strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1].strip()
    return value


def _check_override_option(lineno, keyword, raw_value):
    """Check one override `keyword=value` line; return [(lineno, code, msg)]."""
    canonical = keyword.lower()
    if canonical not in OVERRIDE_OPTIONS:
        return [
            (
                lineno,
                "E303",
                (
                    f'"{keyword}" is not a known override option; expected one '
                    f"of {', '.join(sorted(OVERRIDE_OPTIONS))}; add "
                    f"`{OVERRIDE_MARKER}` if intentional"
                ),
            )
        ]

    issues = []
    if keyword != canonical:
        issues.append(
            (
                lineno,
                "W303",
                (
                    f'override option "{keyword}" is not lowercase; use '
                    f'"{canonical}"; add `{OVERRIDE_CASE_MARKER}` if intentional'
                ),
            )
        )

    value = _override_value(raw_value)
    if not value:
        issues.append(
            (
                lineno,
                "E303",
                (
                    f'override option "{canonical}" has no value; add '
                    f"`{OVERRIDE_MARKER}` if intentional"
                ),
            )
        )
        return issues
    if "{" in value:
        return issues  # a relevance substitution: the value is a runtime matter

    if canonical in OVERRIDE_INTEGER_OPTIONS:
        if not INTEGER_RE.match(value):
            issues.append(
                (
                    lineno,
                    "E303",
                    (
                        f'override option "{canonical}" must be a non-negative '
                        f'integer or a {{...}} substitution, not "{value}"; add '
                        f"`{OVERRIDE_MARKER}` if intentional"
                    ),
                )
            )
        return issues

    allowed = OVERRIDE_OPTIONS[canonical]
    if allowed is None:
        return issues  # no documented value set; the keyword was the check
    if value.lower() not in allowed:
        issues.append(
            (
                lineno,
                "E303",
                (
                    f'"{value}" is not a valid value for override option '
                    f'"{canonical}"; expected one of {", ".join(sorted(allowed))}'
                    f"; add `{OVERRIDE_MARKER}` if intentional"
                ),
            )
        )
    elif value != value.lower():
        issues.append(
            (
                lineno,
                "W303",
                (
                    f'override option value "{value}" is not lowercase; use '
                    f'"{value.lower()}"; add `{OVERRIDE_CASE_MARKER}` if '
                    "intentional"
                ),
            )
        )
    return issues


def lint_actionscript(body, tokenizer=None):
    """Lint one ActionScript body; return sorted [(lineno, code, message)].

    Line numbers are local to the body, 1-based. `tokenizer` defaults to the
    shared tokenizer over the vendored ActionScript grammar.
    """
    tokenizer = tokenizer or _default_tokenizer()
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = body.split("\n")
    masked_lines, issues = _mask_heredocs(lines)
    masked = {
        lineno
        for lineno, (raw, now) in enumerate(zip(lines, masked_lines), start=1)
        if raw != now
    }
    tokens, _errors = tokenizer.tokenize("\n".join(masked_lines))

    first_on_line = {}
    continuation = set()
    for token in tokens:
        first_on_line.setdefault(token.line, token)
        continuation.update(range(token.line + 1, token.end_line + 1))

    in_override = False
    for lineno, line in enumerate(masked_lines, start=1):
        if lineno in masked or not line.strip() or lineno in continuation:
            continue
        token = first_on_line.get(lineno)
        if token is None:
            continue
        if token.class_name in ("comment", "relevance"):
            continue  # neither opens nor closes an override block
        if token.keyword is not None:
            if token.text != token.keyword:
                issues.append(
                    (
                        lineno,
                        "W302",
                        (
                            f'command verb "{token.text}" is not lowercase; use '
                            f'"{token.keyword}"; add `{CASE_MARKER}` if intentional'
                        ),
                    )
                )
            # a real command line closes an override block; the override verbs
            # themselves open one. Checked before the option shape below so a
            # command can never be mistaken for an option (no option keyword is
            # also a command verb).
            in_override = token.keyword in OVERRIDE_VERBS
            continue
        option = OVERRIDE_OPTION_RE.match(line)
        if option is not None:
            keyword, raw_value = option.group(1), option.group(2)
            if in_override:
                issues.extend(_check_override_option(lineno, keyword, raw_value))
                continue
            if keyword.lower() in OVERRIDE_OPTIONS:
                issues.append(
                    (
                        lineno,
                        "E303",
                        (
                            f'override option "{keyword}" appears outside an '
                            "`override run` / `override wait` block; add "
                            f"`{OVERRIDE_MARKER}` if intentional"
                        ),
                    )
                )
                continue
        issues.append(
            (
                lineno,
                "E300",
                (
                    "line does not start with a known ActionScript command, "
                    f'// comment, or {{...}} substitution: "{token.text[:40]}"; '
                    f"add `{VERB_MARKER}` if intentional"
                ),
            )
        )

    for token in tokens:
        if token.line in masked:
            continue
        if token.class_name == "relevance" and token.end_kind in ("eol", "eof"):
            issues.append(
                (
                    token.line,
                    "E301",
                    (
                        "{...} substitution has no closing } before the end of "
                        f"the line; add `{SUBSTITUTION_MARKER}` if intentional"
                    ),
                )
            )
        if token.class_name == "string" and token.end_kind in ("eol", "eof"):
            issues.append(
                (
                    token.line,
                    "W301",
                    (
                        'unbalanced " -- the string has no closing quote before '
                        f"the end of the line; add `{STRING_MARKER}` if intentional"
                    ),
                )
            )
    return sorted(issues)


def _lint_bes_xml(raw, src):
    """Lint every ActionScript in a BES document; return file-lineno issues."""
    try:
        root = etree.fromstring(raw)
    except etree.XMLSyntaxError as err:
        return [(1, "W300", f"not parseable BES XML ({err}); skipping")]
    issues = []
    for element in root.iter("ActionScript"):
        mimetype = element.get("MIMEType")
        if mimetype is not None and mimetype != ACTIONSCRIPT_MIMETYPE:
            continue
        body = element.text or ""
        for lineno, code, message in lint_actionscript(body):
            issues.append((element.sourceline + lineno - 1, code, message))
    return issues


def check_file(path, disabled=frozenset(), strict=False):
    """Check one file; return (issues, fixed) like the sibling checkers.

    `fixed` is always [] (this hook has no auto-fixes yet); the tuple shape
    stays parallel with bes_conventions_check.check_file. `strict` is
    accepted for the same parity and does not change what is reported (the
    caller decides whether warnings fail).
    """
    del strict  # reported issues are the same either way
    if not os.path.isfile(path):
        return [(1, "W300", "file not found; skipping")], []

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
        issues = _lint_bes_xml(raw, src)
    else:
        issues = lint_actionscript(src)

    issues = [
        (lineno, code, message)
        for lineno, code, message in issues
        if code not in disabled and CHECK_MARKERS.get(code, "\0") not in src
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
        help="comma-separated check IDs to skip entirely, e.g. --disable W302",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help=(
            "files to check (.bes/.ojo are linted as BES XML, anything else "
            "as raw ActionScript); if omitted, all *.bes files in the current "
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
        print(f"{warning_count} ActionScript warning(s).")
    if issue_count:
        print(f"{issue_count} ActionScript issue(s).")
    return 1 if (issue_count or (warning_count and args.strict)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
