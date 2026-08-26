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
size present and > 0, hash lengths right, sha256 present, sha1 present when the
line is a prefetch statement without a sha256. It is deliberately offline:
nothing here downloads the URL or checks that the hashes match the real file.
The line's overall shape and its http-vs-https scheme are W206/W207 in
bes-conventions-check, and its lexical validity is E300 in
bes-actionscript-lint-schclass -- three altitudes on the same line, all
intentional.

Checks:
    E400  a prefetch line is invalid; the reason is the message
          `validate_prefetch()` reported (bad size, wrong hash length, an
          unparsable line, ...)
    E401  a prefetch line has no sha256. Upstream treats sha256 as optional
          unless asked; this hook treats it as mandatory, because in 2026 it
          is what enhanced security requires. It is its own code so a repo
          that still wants it optional can `--disable E401`.
    E402  a prefetch downloads the retired unzip-5.52.exe from the BigFix
          redist folder; unzip-6.0.exe is the current one. Auto-fixable.
    W400  the file is not parseable BES XML; skipped (advisory --
          bes-schema-validate is the authority on file validity)
    W402  a prefetch block item has no sha1; technically valid, but unusual
    W403  an `add nohash prefetch item` line: hashless by definition, so it is
          reported rather than validated -- the download cannot be verified
    W404  --auto-fix-network was asked to add a sha256 and could not: the URL
          would not download, or what came back did not match the size and
          sha1 already on the line. The E401 stands; this says why the fix did
          not land.
    W405  a prefetch statement has no sha1. Current BigFix clients accept a
          statement with sha256 alone, so this is valid but unusual --
          previously this hook (following upstream) treated it as mandatory
          and failed the line as E400 with a misleading "could not be parsed"
          message; it is now its own advisory code, same footing as W402's
          block-item case.

E-codes are real issues and fail the hook. W-codes are advisory and do NOT
fail the hook unless --strict is given.

AUTO-FIXES. There are two, and they are separate flags because one of them
touches the network:

--auto-fix (E402), on by default. The retired unzip-5.52.exe prefetch is
rewritten in place to the current unzip-6.0.exe one, in whichever spelling the
line already used -- the replacement is built by `prefetch_from_dictionary()`
from bigfix_prefetch, so its shape is the reference implementation's, not this
hook's idea of it. Purely offline: the current file's size and hashes are
constants here. The original download's *name* is kept (the rest of the
ActionScript refers to the file by that name, so renaming it here would break
the script); everything else -- url, size, sha1, sha256 -- becomes the current
file's.

--auto-fix-network (E401), OFF by default. A prefetch with no sha256 gets one,
which means downloading the file to hash it: there is no other way to learn a
sha256. The download is handed to `add_sha256_prefetch()` from bigfix_prefetch,
which streams the file, checks it against the size and sha1 already on the
line, and re-emits the prefetch with sha256 added; a download that does not
match, or does not happen, is W404 and the line is left alone. Because this
reaches out to whatever URLs the content names, it is opt-in, never the
default, and each URL is fetched at most once per run.

An auto-fixed file fails the hook so the change is reviewed and re-staged.
Nothing else is fixable: E400's right size and hashes are properties of the
real file, and a hook has no way to know which file was meant.

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
                                          [--auto-fix=yes|no]
                                          [--auto-fix-network=yes|no]
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
    0  no E-code issues and nothing auto-fixed (and, without --strict,
       regardless of warnings)
    1  an E-code issue was found, a file was auto-fixed, or a warning was found
       while --strict is set
"""

import argparse
import contextlib
import io
import os
import re
import socket
import sys
import warnings

from bigfix_prefetch.prefetch import add_sha256_prefetch
from bigfix_prefetch.prefetch_from_dictionary import prefetch_from_dictionary
from bigfix_prefetch.prefetch_parse import parse_prefetch
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

KNOWN_CODES = frozenset(
    ["E400", "E401", "E402", "W400", "W402", "W403", "W404", "W405"]
)

# Seconds any one --auto-fix-network download may stall for. bigfix_prefetch
# calls urlopen() without a timeout, which can hang a commit indefinitely, so
# the socket default is set around the call and put back afterwards.
NETWORK_TIMEOUT = 60

# The retired redist download (E402). Matched on either scheme: what is out of
# date is the file, not the URL's scheme (the http-vs-https judgement is W207
# in bes-conventions-check), and BigFix content has shipped it both ways.
OUTDATED_UNZIP_RE = re.compile(
    r"https?://software\.bigfix\.com/download/redist/unzip-5\.52\.exe",
    re.IGNORECASE,
)

# The current unzip in the same folder, and the E402 auto-fix's replacement
# values. `file_name` is only the fallback: the fix keeps whatever name the
# original prefetch used, since the rest of the ActionScript refers to the
# downloaded file by that name.
CURRENT_UNZIP = {
    "file_name": "unzip.exe",
    "file_sha1": "84debf12767785cd9b43811022407de7413beb6f",
    "file_size": "204800",
    "download_url": "http://software.bigfix.com/download/redist/unzip-6.0.exe",
    "file_sha256": ("2122557d350fd1c59fb0ef32125330bde673e9331eb9371b454c2ad2d82091ac"),
}

BES_EXTENSIONS = (".bes", ".ojo")

# the one MIMEType that IS BigFix ActionScript; a missing MIMEType defaults to
# it, every other value is some other language and holds no prefetch lines.
ACTIONSCRIPT_MIMETYPE = "application/x-Fixlet-Windows-Shell"

# `add nohash prefetch item` is the documented hashless form; it is matched
# before the hashed form so it is reported (W403), not validated.
NOHASH_PREFETCH = "add nohash prefetch item"
BLOCK_PREFETCH = "add prefetch item"
STATEMENT_PREFETCH = "prefetch "

# an unrendered mustache template ({{ placeholder }}) is not real content yet.
# Only an identifier-like placeholder counts: `{{` is also the ActionScript
# escape for a literal `{`, so heredoc payloads (YARA, JSON, C#) contain `{{`
# around arbitrary content and must not be mistaken for a template.
# Kept identical in all four hooks -- see the lockstep test in
# tests/test_bes_actionscript_validate_script.py.
MUSTACHE_RE = re.compile(r"\{\{\s*[#/^!&>]?\s*[\w.-]+\s*\}\}")


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


def is_outdated_unzip(line):
    """Say whether `line` downloads the retired redist unzip-5.52.exe."""
    return bool(OUTDATED_UNZIP_RE.search(line))


def current_unzip_prefetch(line):
    """Return the current unzip prefetch, spelled the way `line` is spelled.

    The replacement string itself comes from `prefetch_from_dictionary()` in
    bigfix_prefetch, so a block item gets the block spelling (`name=`/`sha1=`)
    and a statement gets the statement one (`sha1:`/`size:`) exactly as the
    reference implementation writes them. The original download's name is
    carried over -- the surrounding ActionScript refers to the file by name, so
    renaming it here would break the script -- and the fallback if the line is
    too broken to parse a name out of is the canonical `unzip.exe`.
    """
    lowered = line.strip().lower()
    prefetch_type = "block" if lowered.startswith(BLOCK_PREFETCH) else "statement"
    values = dict(CURRENT_UNZIP)
    with warnings.catch_warnings():
        # parse_prefetch warns about the very things E400/E401/W402 report;
        # they are reported from validate_prefetch_line(), not from here.
        warnings.simplefilter("ignore")
        try:
            parsed = parse_prefetch(line)
        except (AttributeError, TypeError, ValueError):
            parsed = {}
    if parsed.get("file_name"):
        values["file_name"] = parsed["file_name"]
    return prefetch_from_dictionary(values, prefetch_type)


def has_sha256(line):
    """Say whether `line` already carries a sha256 (of any length: E400 owns that)."""
    return "sha256" in line.lower()


# Fed to validate_prefetch() only, to check the rest of a sha1-less statement
# through the reference implementation; never parsed for its value and never
# written to a file. See statement_missing_sha1()/_with_placeholder_sha1().
PLACEHOLDER_SHA1 = "0" * 40


def statement_missing_sha1(line):
    """Say whether `line` is a prefetch *statement* with no sha1.

    A prefetch block item with no sha1 is W402's business (upstream parses it
    fine, sha1 just being optional there); a statement is different -- upstream
    `parse_prefetch()` has no `try` around its `sha1:` regex for a statement,
    so a sha1-less one raises `AttributeError` instead of reporting anything
    useful. This is the pre-check that catches that case before it reaches
    `validate_prefetch()`.
    """
    lowered = line.strip().lower()
    return lowered.startswith(STATEMENT_PREFETCH) and " sha1:" not in lowered


def _with_placeholder_sha1(line):
    """Return `line` with a placeholder sha1 spliced in after the size field.

    Lets a sha1-less statement be checked for every *other* defect (bad size,
    wrong sha256 length, ...) through the real `validate_prefetch()` rather
    than re-implementing its statement regexes here. The placeholder is never
    parsed for its value, never reported in a message (messages are trimmed
    to their first line by `_first_line()`, which drops the raw prefetch
    upstream appends), and never written back to the file.
    """
    return re.sub(r" size:", f" sha1:{PLACEHOLDER_SHA1} size:", line, count=1)


def sha256_added_prefetch(line):
    """Download the prefetch's file and return the same line with sha256 added.

    A thin wrapper over `add_sha256_prefetch()` from bigfix_prefetch (the
    upstream examples/add_sha256_prefetch_string.py is exactly this call): it
    streams the download, checks it against the size and sha1 the line already
    claims, and re-emits the prefetch -- in the same spelling -- with sha256
    added. Anything that goes wrong (no network, a 404, a download that does
    not match the line) raises; the caller turns that into W404.

    Three things are handled here that upstream does not:
      * a socket timeout, so a hanging URL cannot hang a commit;
      * upstream's progress printing and warnings, which are swallowed so they
        cannot land in the middle of this hook's own output;
      * the download's *name*, which upstream takes from the URL's basename --
        the name the line already used is put back, since the rest of the
        ActionScript refers to the downloaded file by that name.
    """
    old_timeout = socket.getdefaulttimeout()
    with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
        warnings.simplefilter("ignore")  # upstream warns about what E401 reports
        socket.setdefaulttimeout(NETWORK_TIMEOUT)
        try:
            updated = add_sha256_prefetch(line)
        finally:
            socket.setdefaulttimeout(old_timeout)
        if not updated or not has_sha256(updated):
            raise ValueError("the regenerated prefetch still has no sha256")
        parsed_old = parse_prefetch(line)
        parsed_new = parse_prefetch(updated)

    parsed_new["prefetch_type"] = parsed_old.get("prefetch_type", "statement")
    if parsed_old.get("file_name"):
        parsed_new["file_name"] = parsed_old["file_name"]
    return prefetch_from_dictionary(parsed_new)


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

    A sha1-less prefetch *statement* is a separate pre-check (W405): upstream
    cannot even parse such a line (see `statement_missing_sha1()`), so it is
    validated with a placeholder sha1 spliced in instead, to catch every
    *other* defect through the real `validate_prefetch()` rather than one
    reimplemented here.
    """
    is_sha1_less_statement = statement_missing_sha1(line)
    line_to_validate = _with_placeholder_sha1(line) if is_sha1_less_statement else line
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")  # the same reason may repeat per line
        try:
            valid = validate_prefetch(line_to_validate)
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
    if is_sha1_less_statement:
        issues.append(
            (
                "W405",
                (
                    "prefetch statement has no sha1; sha256 alone is accepted "
                    "by current BigFix clients, so this is valid but unusual "
                    f"-- add one, or `{PREFETCH_MARKER}` if intentional"
                ),
            )
        )
    elif any(_is_missing(message, "sha1") for message in messages):
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
        if is_outdated_unzip(line):
            fixable = "" if is_nohash else " (auto-fixable)"
            issues.append(
                (
                    lineno,
                    "E402",
                    (
                        "prefetch downloads the retired unzip-5.52.exe; "
                        f"{CURRENT_UNZIP['download_url']} is the current one"
                        f"{fixable}; add `{PREFETCH_MARKER}` if intentional"
                    ),
                )
            )
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


def _iter_actionscript_bodies(raw):
    """Yield (sourceline, body) for every BigFix ActionScript in a BES document.

    Raises etree.XMLSyntaxError if the document does not parse; the callers
    turn that into W400.
    """
    root = etree.fromstring(raw)
    for element in root.iter("ActionScript"):
        mimetype = element.get("MIMEType")
        if mimetype is not None and mimetype != ACTIONSCRIPT_MIMETYPE:
            continue
        yield element.sourceline, element.text or ""


def _validate_bes_xml(raw):
    """Validate prefetches in every ActionScript of a BES document."""
    try:
        bodies = list(_iter_actionscript_bodies(raw))
    except etree.XMLSyntaxError as err:
        return [(1, "W400", f"not parseable BES XML ({err}); skipping")]
    issues = []
    for sourceline, body in bodies:
        for lineno, code, message in validate_actionscript(body):
            issues.append((sourceline + lineno - 1, code, message))
    return issues


def iter_prefetch_targets(raw, src, is_bes):
    """Yield (file_lineno, line) for every fixable prefetch line in a file.

    Line numbers are 1-based into `src`. An `add nohash prefetch item` is left
    out of both fixes: it is hashless on purpose, and giving it hashes would
    change what the line does, not just which file it fetches.
    """
    if is_bes:
        try:
            bodies = list(_iter_actionscript_bodies(raw))
        except etree.XMLSyntaxError:
            return  # already reported as W400; nothing safe to rewrite
    else:
        bodies = [(1, src)]

    for sourceline, body in bodies:
        for lineno, line, is_nohash in find_prefetch_lines(body):
            if not is_nohash:
                yield sourceline + lineno - 1, line


def find_fix_targets(raw, src, is_bes):
    """Return [(file_lineno, line)] for the E402 lines that can be rewritten."""
    return [
        (lineno, line)
        for lineno, line in iter_prefetch_targets(raw, src, is_bes)
        if is_outdated_unzip(line)
    ]


def find_network_fix_targets(raw, src, is_bes):
    """Return [(file_lineno, line)] for the E401 lines a download could fix."""
    return [
        (lineno, line)
        for lineno, line in iter_prefetch_targets(raw, src, is_bes)
        if not has_sha256(line)
    ]


def _replace_on_line(lines, lineno, text, replacement):
    """Substitute `text` on 1-based `lineno` of `lines`; say whether it landed.

    The prefetch text is replaced inside the file line rather than the line
    being rebuilt, so indentation and anything sharing the line (a `<![CDATA[`
    opener, say) survive. A target whose text is not found on its line -- which
    entity decoding could in principle cause -- is left alone rather than
    guessed at, and its issue still stands.
    """
    if not 1 <= lineno <= len(lines):
        return False
    raw_line = lines[lineno - 1]
    if text not in raw_line:
        return False
    lines[lineno - 1] = raw_line.replace(text, replacement, 1)
    return True


def fix_outdated_unzip(src, targets):
    """Rewrite each target line to the current unzip prefetch; return (src, fixed)."""
    lines = src.split("\n")
    fixed = []
    for lineno, text in targets:
        if _replace_on_line(lines, lineno, text, current_unzip_prefetch(text)):
            fixed.append(
                (
                    lineno,
                    "E402",
                    (
                        "replaced the retired unzip-5.52.exe prefetch with "
                        f"{CURRENT_UNZIP['download_url']}"
                    ),
                )
            )
    return "\n".join(lines), fixed


def fix_missing_sha256(src, targets, cache=None):
    """Add a sha256 to each target line by downloading it; return (src, fixed, failed).

    `failed` is a list of W404s: the line stayed as it was and its E401 still
    stands. `cache` maps a prefetch line to the rewritten one (or to None for a
    line whose download already failed), so a URL repeated across a run is
    fetched once -- pass the same dict to every call to share it.
    """
    if cache is None:
        cache = {}
    lines = src.split("\n")
    fixed = []
    failed = []
    for lineno, text in targets:
        if text not in cache:
            try:
                cache[text] = sha256_added_prefetch(text)
            except Exception as err:  # noqa: BLE001 -- see below
                # urlopen alone raises URLError, HTTPError, socket.timeout, ssl
                # errors...; upstream adds AttributeError/TypeError/ValueError
                # for a download that does not match the line. Every one of them
                # means the same thing here -- no sha256 was learned -- and none
                # of them may take the whole run down.
                cache[text] = None
                failed.append((lineno, "W404", f"{type(err).__name__}: {err}"))
                continue
        replacement = cache[text]
        if replacement is None:
            failed.append((lineno, "W404", "the download already failed above"))
        elif _replace_on_line(lines, lineno, text, replacement):
            fixed.append((lineno, "E401", "downloaded the file and added its sha256"))
    failed = [
        (
            lineno,
            code,
            (
                f"could not add a sha256 by download ({reason}); the line was "
                "left as it is and its E401 stands"
            ),
        )
        for lineno, code, reason in failed
    ]
    return "\n".join(lines), fixed, failed


def _encode(src, was_crlf):
    """Turn checked text back into file bytes, restoring CRLF if that is the file."""
    return (src.replace("\n", "\r\n") if was_crlf else src).encode("utf-8")


def check_file(  # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
    path,
    disabled=frozenset(),
    strict=False,
    auto_fix=False,
    auto_fix_network=False,
    network_cache=None,
):
    """Check one file; return (issues, fixed), each a list of (lineno, code, msg).

    With `auto_fix`, the retired unzip-5.52.exe prefetches (E402) are rewritten
    in place to the current unzip-6.0.exe one. With `auto_fix_network` -- which
    downloads files, and so is never the default -- a prefetch with no sha256
    (E401) gets one, or a W404 saying why it could not; `network_cache` is a
    dict shared across files so a repeated URL is fetched once. Both report
    under `fixed`, and the file's line endings are preserved (CRLF in, CRLF
    out). `strict` is accepted for parity with the sibling hooks and does not
    change what is reported (the caller decides whether warnings fail).
    """
    del strict  # reported issues are the same either way
    if not os.path.isfile(path):
        return [(1, "W400", "file not found; skipping")], []

    with open(path, "rb") as handle:
        original = handle.read()
    was_crlf = b"\r\n" in original
    src = (
        original.decode("utf-8", errors="replace")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    if SKIP_MARKER in src:
        return [], []
    if MUSTACHE_RE.search(src):
        return [], []

    is_bes = path.endswith(BES_EXTENSIONS)
    opted_out = PREFETCH_MARKER in src

    raw = original
    fixed = []
    failed = []
    if not opted_out and auto_fix and "E402" not in disabled:
        src, got = fix_outdated_unzip(src, find_fix_targets(raw, src, is_bes))
        fixed += got
        raw = _encode(src, was_crlf)
    if not opted_out and auto_fix_network and "E401" not in disabled:
        # re-found on the current text: an E402 fix above may already have
        # brought a sha256 with it, leaving nothing here to download.
        src, got, failed = fix_missing_sha256(
            src, find_network_fix_targets(raw, src, is_bes), network_cache
        )
        fixed += got
        raw = _encode(src, was_crlf)
    if raw != original:
        with open(path, "wb") as handle:
            handle.write(raw)

    if is_bes:
        issues = _validate_bes_xml(raw)
    else:
        issues = validate_actionscript(src)
    issues += failed

    issues = [
        (lineno, code, message)
        for lineno, code, message in issues
        if code not in disabled and not opted_out
    ]
    return sorted(issues), fixed


def check_files(
    paths, disabled=frozenset(), strict=False, auto_fix=False, auto_fix_network=False
):
    """Check several files; return a list of (path, issues, fixed) tuples.

    This is the programmatic entry point: it does no printing. The download
    cache is made here, so a URL repeated across the files is fetched once.
    """
    network_cache = {}
    return [
        (
            path,
            *check_file(
                path,
                disabled=disabled,
                strict=strict,
                auto_fix=auto_fix,
                auto_fix_network=auto_fix_network,
                network_cache=network_cache,
            ),
        )
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


def _report(results):
    """Print every fix and issue in `results`; return (issues, warnings, fixes)."""
    issue_count = 0
    warning_count = 0
    fix_count = 0
    for path, issues, fixed in results:
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
    return issue_count, warning_count, fix_count


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
        "--auto-fix",
        choices=["yes", "no"],
        default=None,
        help=(
            "rewrite the retired unzip-5.52.exe prefetches (E402) in place "
            "(default: yes when files are given, no when auto-discovering)"
        ),
    )
    parser.add_argument(
        "--auto-fix-network",
        choices=["yes", "no"],
        default="no",
        help=(
            "add a sha256 to the prefetches that have none (E401) by "
            "DOWNLOADING each file to hash it; off by default, since it "
            "fetches whatever URLs the content names"
        ),
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

    # auto-fix defaults to yes for explicit files, no when auto-discovering; an
    # explicit --auto-fix always wins. This is the sibling hooks' rule, and
    # pre-commit always passes files, so under pre-commit the default is yes.
    if args.auto_fix is not None:
        auto_fix = args.auto_fix == "yes"
    else:
        auto_fix = bool(args.files)
    paths = args.files if args.files else discover_bes_files(".")

    issue_count, warning_count, fix_count = _report(
        check_files(
            paths,
            disabled=disabled,
            strict=args.strict,
            auto_fix=auto_fix,
            auto_fix_network=args.auto_fix_network == "yes",
        )
    )

    if fix_count:
        print(f"\nauto-fixed {fix_count} issue(s); review and re-stage the changes.")
    if warning_count:
        print(f"{warning_count} prefetch warning(s).")
    if issue_count:
        print(f"{issue_count} prefetch issue(s).")
    # E-codes and any fix always fail; warnings fail only under --strict
    return 1 if (issue_count or fix_count or (warning_count and args.strict)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
