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
and any content-changing auto-fixes) belong in a sibling ActionScript hook,
not here. The one exception is lowercasing (W302/W303): the grammar already
knows exactly which text is the verb or option, and the rewrite changes only
its case. Keeping the split means this hook stays a thin,
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
          {...} substitution, a continuation, or blank. The message quotes
          the offending line (not just its first token) and, when the
          grammar narrows it to at most three known commands or to one close
          spelling of them, names them as a `did you mean` suggestion --
          e.g. `action log commands` suggests `action log command`
    E301  a {...} relevance substitution has no closing } before line end
    E302  a `createfile until <MARKER>` block never reaches its marker line
    E303  an `override run` / `override wait` option line is wrong: an unknown
          keyword, no value, a value outside the documented set for that
          keyword, a non-integer `timeout_seconds`, or a `keyword=value` option
          line outside any override block
    W300  the file is not parseable BES XML; skipped (advisory --
          bes-schema-validate is the authority on file validity)
    W301  a "..." string has no closing " before line end (often benign in
          ActionScript arguments, so a warning). ActionScript has no escape
          character, so `"C:\\Bes\\"` is closed -- except in a `regset`/
          `regset64` value, written in .reg-file syntax, where `\\"` and `\\\\`
          are escapes. `appendfile` content lines are raw file text and exempt
    W302  a matched command verb is not lowercase (e.g. `RUN`; valid but
          unconventional; fixable -> lowercased)
    W303  an override option keyword or value is not lowercase (e.g. `RunAs`;
          valid but unconventional; fixable -> lowercased, a `{...}` value
          never touched)

E-codes are real issues and fail the hook. W-codes are advisory and do NOT
fail the hook unless --strict is given.

--auto-fix (W302, W303), on by default when files are given (as pre-commit
does) and off when auto-discovering, lowercases each non-lowercase command
verb and override option keyword/value in place; nothing else is rewritten,
since anything more is beyond what a lexical grammar can justify (see SCOPE
above). The file's line endings are kept, and an auto-fixed file fails the
hook so the change is reviewed and re-staged. `--disable W302` or the
`actionscript-case-ok` marker (W303: `actionscript-override-case-ok`) turns
the check and its fix off together.

XML bodies are extracted with lxml, so the linted text is the REAL
ActionScript exactly as the agent sees it: entities decoded, adjacent CDATA
sections merged, with lxml's sourceline mapping issues back to file line
numbers.

Usage:
    bes_actionscript_lint_schclass.py [--strict] [--disable E300,W302]
                                      [--auto-fix=yes|no] [file ...]

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
both intentional. The E300 `did you mean` suggestion is word-based, so a
first word glued to punctuation (`run"x"`) gets none; a plural or bare
`action log`/`action launch` line stays E300 by design -- `action log all`,
`action log command`, and the two `action launch preference` forms are the
only variants the grammar and the BigFix documentation carry
(jgstew/pre-commit-bigfix#15).

Exit codes:
    0  no E-code issues and nothing auto-fixed (and, without --strict,
       regardless of warnings)
    1  an E-code issue was found, a file was auto-fixed, or a warning was found
       while --strict is set
"""

import argparse
import dataclasses
import difflib
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
# an `appendfile <content>` line: the content is raw file text (W301-exempt)
_APPENDFILE_RE = re.compile(r"[ \t]*appendfile\b", re.IGNORECASE)
# a `regset`/`regset64` line: its value is written in .reg-file syntax, where
# `\"` IS an escaped quote and `\\` an escaped backslash (W301 scans it with
# _regset_tokenizer, unlike the rest of ActionScript, which has no escapes)
_REGSET_RE = re.compile(r"[ \t]*regset(?:64)?\b", re.IGNORECASE)

OVERRIDE_OPTION_RE = re.compile(r"[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*=(.*)\Z")

# an unrendered mustache template ({{ placeholder }}) is not real content yet.
# Only an identifier-like placeholder counts: `{{` is also the ActionScript
# escape for a literal `{`, so heredoc payloads (YARA, JSON, C#) contain `{{`
# around arbitrary content and must not be mistaken for a template.
# Kept identical in all four hooks -- see the lockstep test in
# tests/test_bes_actionscript_validate_script.py.
# A GUID-shaped "placeholder" is not one: `msiexec /x{{{GUID}}` escapes a
# literal `{` in front of an MSI product code.
MUSTACHE_RE = re.compile(
    r"\{\{(?!\s*[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\s*\}\})"
    r"\s*[#/^!&>]?\s*[\w.-]+\s*\}\}"
)

# E300's message quotes the offending LINE, not the first token: a `default`
# token is one contiguous non-whitespace run (see flush_default in
# schclass_tokenizer.py), so quoting the token alone turned `action log
# commands` into a useless `"action"` (jgstew/pre-commit-bigfix#15).
LINE_QUOTE_LIMIT = 40

# E300's "did you mean" suggestion. SUGGEST_LIMIT is both the cap and the
# relevance gate: a family the grammar has already narrowed to this many
# commands is named in full (it is a fact about the grammar, not a guess); a
# wider family is filtered by spelling similarity first and usually stays
# silent -- see _verb_suggestions.
SUGGEST_LIMIT = 3
SUGGEST_CUTOFF = 0.85

_TOKENIZER = None
_REGSET_TOKENIZER = None
_VERBS = None


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


def _regset_tokenizer():
    """Return a Tokenizer whose strings honor .reg-file escapes (lazy).

    The default grammar deliberately has no string escapes (ActionScript has
    none, see bigfix_overrides.schclass); a regset value is the exception, so
    `\\\\` and `\\"` are added back for it. Longest match wins, so at `\\\\"`
    the escaped backslash is consumed and the quote then closes the string.
    """
    global _REGSET_TOKENIZER
    if _REGSET_TOKENIZER is None:
        schema = schclass.load_default_actionscript_schema()
        string = schema.classes["string"]
        schema.classes["string"] = dataclasses.replace(
            string, skip_tags=("\\\\", '\\"') + tuple(string.skip_tags)
        )
        _REGSET_TOKENIZER = Tokenizer(schema, case_insensitive=True, relaxed_bol=True)
    return _REGSET_TOKENIZER


def _regset_line_has_open_string(line):
    """True if a regset `line` leaves a "..." string open, per .reg escapes."""
    tokens, _errors = _regset_tokenizer().tokenize(line)
    return any(
        token.class_name == "string" and token.end_kind in ("eol", "eof")
        for token in tokens
    )


def _grammar_verbs(tokenizer):
    """Return a tokenizer's command verbs, sorted (cached for the default).

    Derived from the merged schema the same way _TOKENIZER is, so new BigFix
    verbs arrive with the vendored schclass and there is no list to maintain
    here. A caller-supplied tokenizer (a test path) is not cached.
    """
    global _VERBS
    if tokenizer is not _TOKENIZER:
        return tuple(sorted(tokenizer.schema.all_token_tags()))
    if _VERBS is None:
        _VERBS = tuple(sorted(tokenizer.schema.all_token_tags()))
    return _VERBS


def _default_verbs():
    """Return the default grammar's command verbs, sorted (lazy)."""
    return _grammar_verbs(_default_tokenizer())


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


def _quote(value, limit=LINE_QUOTE_LIMIT):
    """`value` shortened for use in a message, with an elision marker if cut."""
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "..."


def _verb_ratio(words, verb):
    """Similarity of the line's leading words to `verb`, word-count aligned.

    The line is truncated to the candidate's own word count first, so a
    verb's trailing arguments (`action log commands --now`) do not dilute
    the score.
    """
    lowered = verb.lower()
    head = " ".join(words[: len(lowered.split())])
    return difflib.SequenceMatcher(None, head, lowered).ratio()


def _verb_suggestions(line, verbs):
    """Return the known verbs a bad line most likely meant, best first.

    The candidates are the verbs sharing the LONGEST leading-word prefix
    with the line: `action log commands` and a bare `action log` both land
    on {`action log all`, `action log command`}. A line whose first word
    begins no verb at all (`badverb y`, a "quoted" string) gets nothing --
    that gate is what keeps the suggestion from being noise. A family the
    grammar has already narrowed to SUGGEST_LIMIT or fewer is returned
    whole; a wider one is a guess and is filtered to close spellings only.
    A verb the line already spells exactly (at its own word count) is
    dropped -- suggesting back what was already written is not a suggestion.
    """
    words = line.strip().lower().split()
    if not words:
        return []
    family = []
    depth = 0
    for verb in verbs:
        verb_words = verb.lower().split()
        shared = 0
        while (
            shared < len(verb_words)
            and shared < len(words)
            and verb_words[shared] == words[shared]
        ):
            shared += 1
        if shared == 0:
            continue
        if shared > depth:
            family, depth = [verb], shared
        elif shared == depth:
            family.append(verb)
    family = [
        verb for verb in family if " ".join(words[: len(verb.split())]) != verb.lower()
    ]
    if not family:
        return []
    ranked = sorted(family, key=lambda verb: (-_verb_ratio(words, verb), verb))
    if len(family) > SUGGEST_LIMIT:
        ranked = [v for v in ranked if _verb_ratio(words, v) >= SUGGEST_CUTOFF]
    return ranked[:SUGGEST_LIMIT]


def _did_you_mean(suggestions):
    """Render suggested verbs as a message clause, or "" when there are none."""
    quoted = [f"`{verb}`" for verb in suggestions]
    if not quoted:
        return ""
    if len(quoted) == 1:
        body = quoted[0]
    elif len(quoted) == 2:
        body = " or ".join(quoted)
    else:
        body = ", ".join(quoted[:-1]) + ", or " + quoted[-1]
    return f"did you mean {body}?; "


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


_UNBALANCED_STRING_MESSAGE = (
    'unbalanced " -- the string has no closing quote before '
    f"the end of the line; add `{STRING_MARKER}` if intentional"
)


def _mask_brace_escapes(line):
    """Blank out ActionScript's literal-brace escapes, keeping every column.

    `{{` outside a substitution is a literal `{`, and `}}` inside one is a
    literal `}`; the display grammar knows neither, so a `{{` would start a
    substitution that never closes (a false E301). Quoted relevance strings
    inside a substitution are skipped so their braces are left alone.
    """
    chars, depth, quoted, index = list(line), 0, False, 0
    while index < len(line):
        char = line[index]
        if depth and char == '"':
            quoted = not quoted
        elif (
            not quoted
            and not depth
            and line.startswith("{{", index)
            or not quoted
            and depth
            and line.startswith("}}", index)
        ):
            chars[index] = chars[index + 1] = " "
            index += 2
            continue
        elif not quoted and char == "{":
            depth += 1
        elif not quoted and char == "}" and depth:
            depth -= 1
        index += 1
    return "".join(chars)


def _override_case_rewrite(line, keyword, raw_value):
    """Return (old, new) lowercasing an override option line, or None.

    The keyword is lowercased when it is a known option; the value only when
    it is one of that option's documented values (W303's own rule) -- never
    a `{...}` substitution, an integer, or free text like a user name.
    """
    canonical = keyword.lower()
    if canonical not in OVERRIDE_OPTIONS:
        return None
    old = line.strip()
    new = canonical + old[len(keyword) :] if old.startswith(keyword) else old
    value = _override_value(raw_value)
    allowed = OVERRIDE_OPTIONS[canonical]
    if (
        value
        and "{" not in value
        and canonical not in OVERRIDE_INTEGER_OPTIONS
        and allowed is not None
        and value.lower() in allowed
        and value != value.lower()
    ):
        at = new.find(value, new.find("=") + 1)
        if at != -1:
            new = new[:at] + value.lower() + new[at + len(value) :]
    return (old, new) if new != old else None


def lint_actionscript(body, tokenizer=None, fixes=None):
    """Lint one ActionScript body; return sorted [(lineno, code, message)].

    Line numbers are local to the body, 1-based. `tokenizer` defaults to the
    shared tokenizer over the vendored ActionScript grammar. When `fixes` is
    a list, a (lineno, code, old, new) rewrite is appended to it for every
    W302/W303 case-only finding -- the only auto-fixes this hook makes.
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
    tokens, _errors = tokenizer.tokenize(
        "\n".join(_mask_brace_escapes(line) for line in masked_lines)
    )
    # everything after `appendfile` is one line of raw file content (a batch
    # file, a VBScript, JSON...), so its quotes are not ActionScript strings
    appendfile_lines = {
        lineno
        for lineno, line in enumerate(masked_lines, start=1)
        if _APPENDFILE_RE.match(line)
    }
    regset_lines = {
        lineno
        for lineno, line in enumerate(masked_lines, start=1)
        if _REGSET_RE.match(line) and lineno not in masked
    }

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
                if fixes is not None:
                    fixes.append((lineno, "W302", token.text, token.keyword))
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
                found = _check_override_option(lineno, keyword, raw_value)
                issues.extend(found)
                rewrite = _override_case_rewrite(line, keyword, raw_value)
                if (
                    fixes is not None
                    and rewrite
                    and any(code == "W303" for _l, code, _m in found)
                ):
                    fixes.append((lineno, "W303") + rewrite)
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
        suggestion = _did_you_mean(_verb_suggestions(line, _grammar_verbs(tokenizer)))
        issues.append(
            (
                lineno,
                "E300",
                (
                    "line does not start with a known ActionScript command, "
                    f'// comment, or {{...}} substitution: "{_quote(line)}"; '
                    f"{suggestion}add `{VERB_MARKER}` if intentional"
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
        if (
            token.class_name == "string"
            and token.end_kind in ("eol", "eof")
            and token.line not in appendfile_lines
            and token.line not in regset_lines
        ):
            issues.append((token.line, "W301", _UNBALANCED_STRING_MESSAGE))
    for lineno in sorted(regset_lines):
        if _regset_line_has_open_string(masked_lines[lineno - 1]):
            issues.append((lineno, "W301", _UNBALANCED_STRING_MESSAGE))
    return sorted(issues)


def _lint_bes_xml(raw, src, fixes=None):
    """Lint every ActionScript in a BES document; return file-lineno issues.

    `fixes`, when a list, collects lint_actionscript's rewrites with their
    line numbers mapped to the file the same way.
    """
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
        body_fixes = [] if fixes is not None else None
        for lineno, code, message in lint_actionscript(body, fixes=body_fixes):
            issues.append((element.sourceline + lineno - 1, code, message))
        for lineno, code, old, new in body_fixes or []:
            fixes.append((element.sourceline + lineno - 1, code, old, new))
    return issues


# the opening tag (and CDATA start) a body's first line may share its line with
_ACTIONSCRIPT_OPEN_RE = re.compile(r"<ActionScript\b[^>]*>(?:<!\[CDATA\[)?")

_FIX_MESSAGES = {
    "W302": "lowercased the command verb",
    "W303": "lowercased the override option",
}


def _apply_fixes(src, fixes, codes):
    """Apply (file_lineno, code, old, new) case rewrites to `src`, in place.

    Each `old` is replaced once on its line -- as written, or with `"`
    escaped as `&quot;` in an entity-escaped body; a rewrite whose text is
    not found there is skipped rather than guessed at. Only `codes` are
    applied. Returns (new_src, fixed).
    """
    lines = src.split("\n")
    fixed = []
    for lineno, code, old, new in fixes:
        if code not in codes or not 1 <= lineno <= len(lines):
            continue
        line = lines[lineno - 1]
        # a body's first line may share the file line with its opening tag;
        # search only the ActionScript text after it
        opening = _ACTIONSCRIPT_OPEN_RE.search(line)
        start = opening.end() if opening else 0
        if old not in line[start:] and "&quot;" in line:
            old, new = old.replace('"', "&quot;"), new.replace('"', "&quot;")
        at = line.find(old, start)
        if at == -1:
            continue
        lines[lineno - 1] = line[:at] + new + line[at + len(old) :]
        fixed.append((lineno, code, _FIX_MESSAGES[code]))
    return "\n".join(lines), fixed


def check_file(path, disabled=frozenset(), strict=False, auto_fix=False):
    """Check one file; return (issues, fixed) like the sibling checkers.

    With `auto_fix`, each non-lowercase command verb (W302) and override
    option keyword/value (W303) is lowercased in place, unless the code is in
    `disabled` or the file carries that check's opt-out marker; the file's
    line endings are preserved. Nothing else is ever rewritten. `strict` is
    accepted for parity with the siblings and does not change what is
    reported (the caller decides whether warnings fail).
    """
    del strict  # reported issues are the same either way
    if not os.path.isfile(path):
        return [(1, "W300", "file not found; skipping")], []

    with open(path, "rb") as handle:
        raw = handle.read()
    was_crlf = b"\r\n" in raw
    src = (
        raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    )

    if SKIP_MARKER in src:
        return [], []
    if MUSTACHE_RE.search(src):
        return [], []

    is_bes = path.endswith(BES_EXTENSIONS)
    fix_codes = {
        code
        for code in ("W302", "W303")
        if auto_fix and code not in disabled and CHECK_MARKERS[code] not in src
    }
    fixed = []
    if fix_codes:
        fixes = []
        if is_bes:
            _lint_bes_xml(raw, src, fixes)
        else:
            lint_actionscript(src, fixes=fixes)
        src, fixed = _apply_fixes(src, fixes, fix_codes)
        if fixed:
            raw = (src.replace("\n", "\r\n") if was_crlf else src).encode("utf-8")
            with open(path, "wb") as handle:
                handle.write(raw)

    if is_bes:
        issues = _lint_bes_xml(raw, src)
    else:
        issues = lint_actionscript(src)

    issues = [
        (lineno, code, message)
        for lineno, code, message in issues
        if code not in disabled and CHECK_MARKERS.get(code, "\0") not in src
    ]
    return sorted(issues), fixed


def check_files(paths, disabled=frozenset(), strict=False, auto_fix=False):
    """Check several files; return a list of (path, issues, fixed) tuples.

    This is the programmatic entry point: it does no printing.
    """
    return [
        (path, *check_file(path, disabled=disabled, strict=strict, auto_fix=auto_fix))
        for path in paths
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
        "--auto-fix",
        choices=["yes", "no"],
        default=None,
        help=(
            "lowercase non-lowercase command verbs (W302) and override option "
            "keywords/values (W303), in place (default: yes when files are "
            "given, no when auto-discovering)"
        ),
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

    # auto-fix defaults to yes for explicit files, no when auto-discovering; an
    # explicit --auto-fix always wins -- the sibling hooks' rule, and pre-commit
    # always passes files, so under pre-commit the default is yes.
    if args.auto_fix is not None:
        auto_fix = args.auto_fix == "yes"
    else:
        auto_fix = bool(args.files)
    paths = args.files if args.files else discover_bes_files(".")

    issue_count = 0
    warning_count = 0
    fix_count = 0
    for path, issues, fixed in check_files(
        paths, disabled=disabled, strict=args.strict, auto_fix=auto_fix
    ):
        for lineno, check_id, message in fixed:
            fix_count += 1
            print(f"{path}:{lineno}: [{check_id}] auto-fixed: {message}")
        for lineno, check_id, message in issues:
            if check_id.startswith("W"):
                warning_count += 1
                print(f"{path}:{lineno}: [{check_id}] warning: {message}")
            else:
                issue_count += 1
                print(f"{path}:{lineno}: [{check_id}] {message}")

    if fix_count:
        print(f"\nauto-fixed {fix_count} issue(s); review and re-stage the changes.")
    if warning_count:
        print(f"{warning_count} ActionScript warning(s).")
    if issue_count:
        print(f"{issue_count} ActionScript issue(s).")
    # E-codes and any fix always fail; warnings fail only under --strict
    return 1 if (issue_count or fix_count or (warning_count and args.strict)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
