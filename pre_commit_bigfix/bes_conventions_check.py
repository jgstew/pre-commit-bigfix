#!/usr/bin/env python3
"""Pre-commit hook: check BigFix BES files for opinionated conventions.

This is the BES-content companion to the `bes-schema-validate` hook, which
only checks that a file is well-formed XML that satisfies the BES.xsd schema --
it says nothing about the *content* being conventional or correct. This tool
goes further, with PICKY, OPINIONATED checks (several AUTO-FIXABLE) that the XSD
cannot express.

A BES file is XML rooted at <BES> holding one or more content objects: Task,
Fixlet, Analysis, ComputerGroup, Baseline, SingleAction, ... The checks are
scoped by what actually makes sense for each: value-format checks apply wherever
the field appears; presence checks apply only to Task/Fixlet (the "publishable"
content -- Analysis and ComputerGroup legitimately have no SourceReleaseDate or
modification time).

Checks:
    E200  an <ActionScript> MIMEType is missing or not one of the allowed set
    E201  a <SourceReleaseDate> is present but not in YYYY-MM-DD format
    E202  an x-fixlet-modification-time value is not a valid RFC 5322 date-time
          (e.g. `Tue, 14 Jul 2026 18:32:35 +0000`, or `14 Jul 2026 18:32:35
          +0000` without the optional day-of-week) -- see "Timestamp fields"
          below for exactly what that requires
    E203  a <DownloadSize> is not empty and not 0-or-a-positive-integer (fixable
          -> 0)
    E204  a content object's <Description> still contains the boilerplate
          placeholder "enter a description of the" (case-insensitive), e.g.
          "Enter a description of the Task here." or "...of the Analysis here."
    E205  an x-fixlet-cpe23-item-name value is not a valid CPE 2.3 string
    E206  an action-ui-metadata value is not well-formed
    E207  a Description / Relevance / ActionScript entity-escapes a character
          (< > &) that requires <![CDATA[ ... ]]> instead (fixable -> unescaped
          and CDATA-wrapped)
    E208  the file is not CRLF throughout -- BES files must use CRLF line
          endings (fixable -> the whole file is normalized to CRLF)
    E209  a <CVENames> value is not a valid CVE id (e.g. CVE-2021-44228), or
          more than one <CVENames> element is present in a single content object
    E210  two <MIMEField> entries in one content object share the same <Name>
    E211  a <Title> is a default placeholder ("Custom Fixlet"/"Custom Task"/
          "Custom Baseline"/"Custom Analysis")
    E212  a <Relevance> is the literal `true` (case-insensitive) -- it targets
          every endpoint
    E213  a <Relevance> is empty or whitespace only
    E214  the file has no XML declaration, or its declaration does not specify
          encoding="UTF-8" (fixable -> declaration inserted / encoding set)
    E215  an <ActionScript> has whitespace before its close tag, e.g. an
          indented `]]></ActionScript>` (CDATA body) or a bare indented
          `</ActionScript>` (non-CDATA body) -- that whitespace is inside the
          ActionScript and becomes a bogus whitespace-only last line of the
          action (fixable -> stripped to a flush `]]></ActionScript>` or
          `</ActionScript>`)
    E216  an x-fixlet-first-propagation value is not a valid RFC 5322 date-time
          -- the same rule E202 applies to x-fixlet-modification-time, applied
          to this separate field (see "Timestamp fields" below)
    E217  a <SuccessCriteria Option="CustomRelevance"> body is empty or the
          literal `false` (can never succeed), or a non-CustomRelevance
          <SuccessCriteria> has a non-empty body (silently ignored by BigFix)
    E218  two <Action ID="..."> / <DefaultAction ID="..."> in one content
          object share the same ID
    E219  an x-relevance-evaluation-period value is not a valid HH:MM:SS
          duration (matched case-insensitively; MM and SS must each be 00-59)
    W200  the file is not parseable BES XML; skipped (advisory --
          bes-schema-validate is the authority on file validity)
    W201  a Task/Fixlet has no x-fixlet-modification-time MIMEField (fixable ->
          the moment the linter ran)
    W202  a Task/Fixlet has no <SourceReleaseDate> (fixable -> today)
    W203  a Task/Fixlet has DownloadSize > 0 but no download/prefetch keyword in
          any ActionScript
    W204  an <ActionScript> body is not wrapped in <![CDATA[ ... ]]> (fixable,
          but ONLY under --strict, since wrapping already-escaped content can
          change its meaning)
    W205  an <ActionScript> has more than one blank line before </ActionScript>
          (fixable -> collapsed to one)
    W206  a prefetch / "add prefetch item" line does not match the expected
          shape; a prefetch statement's sha1 is optional when it has a sha256
          (current BigFix clients accept a sha256-only statement)
    W207  a prefetch / "add prefetch item" URL is not https
    W208  an <ActionScript> body is empty (only blank lines and //-comments)
    W209  a <Title> has leading/trailing whitespace/newlines or embedded tabs
          (fixable -> trimmed, tabs replaced with spaces)
    W210  a line has trailing whitespace (fixable -> stripped)
    W211  an <ActionScript> uses a dynamic `download` statement (a line whose
          first non-whitespace token is `download`); prefer a static prefetch
    W212  a <Relevance> is the literal `false` (case-insensitive) -- it never
          applies to any endpoint
    W213  a <Relevance> has leading/trailing whitespace (fixable -> trimmed;
          a CDATA-wrapped Relevance is left untouched, as with Title/W209)
    W214  a <Title> contains a TODO or FIXME marker
    W215  a Task/Fixlet <Description> is empty or missing (distinct from
          E204's boilerplate-placeholder check)
    W216  a non-empty <SourceSeverity> is not one of Low/Moderate/Important/
          Critical/Unspecified (exact case) -- override with --severity-values
    W217  (only with --check-filename) a file's basename does not match its
          first content object's <Title>, sanitized for filename-illegal
          characters (/, backslash, :, *, ?, ", <, >, | -> _)

Timestamp fields (E202, E216): x-fixlet-modification-time and
x-fixlet-first-propagation are both RFC 5322 date-times, e.g.
`Tue, 14 Jul 2026 18:32:35 +0000`:
  - the leading day-of-week + comma is OPTIONAL (RFC 5322 itself makes it so),
    but if present it must be the REAL day of week for the date given --
    `Fri, 06 Aug 2026 12:43:34 +0000` is rejected because 6 Aug 2026 is a
    Thursday, not a Friday
  - the day of month is exactly 2 digits (zero-padded: `06`, not `6`)
  - the month is exactly 3 letters with RFC 5322's exact capitalization
    (`Aug`, not `aug` or `AUG`)
  - the year is exactly 4 digits
  - the time is `HH:MM:SS`, each exactly 2 digits
  - a `+HHMM`/`-HHMM` UTC offset is required and must be a real one (a bare
    zone name like `GMT`/`UTC`/`Z` is not accepted, and neither is an
    out-of-range offset like `+9999` or one at/beyond 24 hours)
SourceReleaseDate (E201) is unrelated to the two above: it is a plain
YYYY-MM-DD date (e.g. `2026-07-14`), no time or timezone component at all.

The allowed <ActionScript> MIMETypes are:
    application/x-Fixlet-Windows-Shell     (the DEFAULT BigFix ActionScript type
                                            for ALL platforms -- despite the name
                                            it is not Windows-specific)
    application/x-sh                       (shell, e.g. macOS / Linux)
    application/x-AppleScript              (macOS AppleScript)
    application/x-Fixlet-Windows-PowerShell  (Windows-specific PowerShell)
    text/x-uri                             (open a URL)

E-codes are real issues and fail the hook. W-codes are advisory and do NOT fail
the hook unless --strict is given; wire the hook with `verbose: true` to surface
them. W200 is how the tool stays out of bes-schema-validate's lane: an
unparsable file is skipped, not failed, here.

--auto-fix rewrites the fixable conventions in place: an invalid/empty
DownloadSize -> 0 (E203); a missing SourceReleaseDate -> today (W202); a missing
x-fixlet-modification-time -> the moment the linter ran (W201); collapsed blank
lines before </ActionScript> (W205); a Title trimmed with tabs replaced by
spaces (W209); a Relevance trimmed of leading/trailing whitespace (W213);
trailing whitespace stripped from every line (W210); whitespace
around an ActionScript CDATA terminator stripped (E215); a missing or
non-UTF-8 XML declaration inserted / normalized (E214); and a
Description/Relevance/ActionScript that entity-escapes < > & is unescaped and
CDATA-wrapped (E207). One fix is gated behind --strict: wrapping an
otherwise-plain ActionScript body in <![CDATA[ ... ]]> (W204). The file-level
fixers (W210 then E214) run after the per-block ones. Finally, CRLF
normalization runs LAST: whenever --auto-fix is on, the whole file is rewritten
with CRLF line endings (E208), so any fix -- and any file that was not already
all-CRLF -- ends up entirely CRLF rather than preserving a mix. --auto-fix
defaults to yes when files are given
explicitly, but to no when auto-discovering, so a bare run is read-only. An
auto-fixed file fails the hook so the change is reviewed and re-staged.

Usage:
    bes_conventions_check.py [--strict] [--errors-only] [--auto-fix=yes|no]
        [--disable E200,W201] [--check-filename]
        [--severity-values Low,Moderate,Important,Critical,Unspecified]
        [file.bes ...]

--check-filename is OFF by default: it enables W217 (a file's basename must
match its first content object's Title, sanitized for filename-illegal
characters). It is opt-in because many repos deliberately version or
otherwise diverge a Title from its filename.

--severity-values overrides the vocabulary W216 accepts for a non-empty
<SourceSeverity> (default: Low, Moderate, Important, Critical, Unspecified,
matched exact-case). Pass a comma-separated list of the values this repo
considers valid, e.g. --severity-values "low,medium,high,critical"; an empty
value in the list is ignored, and an empty <SourceSeverity> is always allowed
regardless of this setting.

With no file arguments, all *.bes files in the current folder and below are
checked. --disable takes a comma-separated list of check IDs to skip entirely.
--errors-only keeps every check (and every auto-fix) running but leaves W-codes
out of the report, so only E-codes and auto-fix lines are printed; unlike
--disable it does not turn off the W-code fixers.

A file can opt out of all checks with an XML comment anywhere in it:
    <!-- pre-commit-skip: bes-conventions-check -->
or out of a single check family with the matching marker (also anywhere in the
file, e.g. in an XML comment):
    mimetype-ok             (E200)
    source-release-date-ok  (E201 and W202)
    modification-time-ok     (E202 and W201)
    first-propagation-ok    (E216)
    download-size-ok        (E203 and W203)
    description-ok          (E204)
    cpe-ok                  (E205)
    action-ui-metadata-ok   (E206)
    cdata-ok                (W204 and E207)
    cdata-close-ok          (E215 -- CDATA terminator or bare ActionScript close)
    action-blank-lines-ok   (W205)
    prefetch-ok             (W206)
    prefetch-https-ok       (W207)
    actionscript-empty-ok   (W208)
    title-ok                (E211, W209, and W214)
    relevance-ok            (E212, E213, W212, and W213)
    xml-declaration-ok      (E214)
    trailing-whitespace-ok  (W210)
    download-ok             (W211)
    cve-names-ok            (E209)
    mimefield-name-ok       (E210)
    success-criteria-ok    (E217)
    action-id-ok            (E218)
    evaluation-period-ok   (E219)
    severity-ok             (W216)
    filename-ok             (W217, only relevant with --check-filename)

description-ok also covers W215 (an empty/missing Task/Fixlet Description) --
it is the same marker as E204 since both describe a Description problem.

Files that look like mustache templates (containing `{{ ... }}`, e.g. the
`*.bes.mustache` sources that ContentFromTemplate renders) are skipped silently:
they are not valid BES XML until rendered, and their own output is what should
be linted.

Exit codes:
    0  no E-code issues and nothing auto-fixed (and, without --strict, regardless
       of warnings)
    1  an E-code issue was found, a file was auto-fixed, or a warning was found
       while --strict is set (--errors-only suppresses the warnings, so they
       cannot fail the run even under --strict)
"""

import argparse
import functools
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from xml.etree import ElementTree

SKIP_MARKER = "pre-commit-skip: bes-conventions-check"

# per-check opt-out markers (matched anywhere in the file text)
MIMETYPE_MARKER = "mimetype-ok"  # E200
SOURCE_RELEASE_DATE_MARKER = "source-release-date-ok"  # E201, W202
MODIFICATION_TIME_MARKER = "modification-time-ok"  # E202, W201
FIRST_PROPAGATION_MARKER = "first-propagation-ok"  # E216
DOWNLOAD_SIZE_MARKER = "download-size-ok"  # E203, W203
DESCRIPTION_MARKER = "description-ok"  # E204
CPE_MARKER = "cpe-ok"  # E205
ACTION_UI_METADATA_MARKER = "action-ui-metadata-ok"  # E206
CDATA_MARKER = "cdata-ok"  # W204
CDATA_CLOSE_MARKER = "cdata-close-ok"  # E215 (CDATA terminator or bare close)
ACTION_BLANK_LINES_MARKER = "action-blank-lines-ok"  # W205
PREFETCH_MARKER = "prefetch-ok"  # W206
PREFETCH_HTTPS_MARKER = "prefetch-https-ok"  # W207
ACTIONSCRIPT_EMPTY_MARKER = "actionscript-empty-ok"  # W208
TITLE_MARKER = "title-ok"  # E211, W209
RELEVANCE_MARKER = "relevance-ok"  # E212, E213
XML_DECL_MARKER = "xml-declaration-ok"  # E214
TRAILING_WS_MARKER = "trailing-whitespace-ok"  # W210
DOWNLOAD_MARKER = "download-ok"  # W211
CVE_NAMES_MARKER = "cve-names-ok"  # E209
MIMEFIELD_DUP_MARKER = "mimefield-name-ok"  # E210
SUCCESS_CRITERIA_MARKER = "success-criteria-ok"  # E217
ACTION_ID_MARKER = "action-id-ok"  # E218
EVALUATION_PERIOD_MARKER = "evaluation-period-ok"  # E219
SEVERITY_MARKER = "severity-ok"  # W216
FILENAME_MARKER = "filename-ok"  # W217 (only with --check-filename)

BES_EXTENSIONS = (".bes",)

# the ActionScript MIMETypes BigFix supports (and this repo allows). The
# "Windows-Shell" one is the platform-agnostic default despite its name; only
# "Windows-PowerShell" is genuinely Windows-only.
ALLOWED_MIMETYPES = frozenset(
    [
        "application/x-Fixlet-Windows-Shell",
        "application/x-sh",
        "application/x-AppleScript",
        "application/x-Fixlet-Windows-PowerShell",
        "text/x-uri",
    ]
)

# content objects that live directly under <BES>
CONTENT_TAGS = frozenset(
    ["Task", "Fixlet", "Analysis", "ComputerGroup", "Baseline", "SingleAction"]
)
# only these are expected to carry a SourceReleaseDate / modification time and a
# download action; the description placeholder check (E204) applies to every
# content object, since Analysis/Baseline/... carry the same boilerplate
DATED_CONTENT_TAGS = frozenset(["Task", "Fixlet"])

MODIFICATION_TIME_NAME = "x-fixlet-modification-time"
FIRST_PROPAGATION_NAME = "x-fixlet-first-propagation"
DESCRIPTION_PLACEHOLDER = "enter a description of the"

# An RFC 5322 date-time, e.g. "Tue, 14 Jul 2026 18:32:35 +0000" -- shared by
# x-fixlet-modification-time (E202) and x-fixlet-first-propagation (E216). The
# day-of-week + comma is an optional group (RFC 5322 makes it so); `rest` is
# everything after it, captured separately so _valid_timestamp() can re-parse
# just that part with strptime without re-deriving the split index.
TIMESTAMP_RE = re.compile(
    r"^(?:(?P<dow>[A-Za-z]{3}), )?"
    r"(?P<rest>\d{2} (?P<mon>[A-Za-z]{3}) \d{4} \d{2}:\d{2}:\d{2} [+-]\d{4})$"
)
# index 0 = Monday, matching datetime.weekday() -- used to cross-check a
# SUPPLIED day-of-week against the one the date actually falls on, not just
# that it is spelled like a real weekday.
WEEKDAY_ABBREVS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEKDAYS = frozenset(WEEKDAY_ABBREVS)
MONTHS = frozenset(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
)

SOURCE_RELEASE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DOWNLOAD_SIZE_RE = re.compile(r"^\d+$")

# a CPE 2.3 formatted string: cpe:2.3: then 11 colon-separated components
# (part vendor product version update edition language sw_edition target_sw
# target_hw other); colons inside a component are backslash-escaped.
CPE23_RE = re.compile(r"^cpe:2\.3:[aho*\-](:([^:\\]|\\.)+){10}$", re.IGNORECASE)

# action-ui-metadata: the JSON object BigFixSetupTemplateDictionary emits. The
# value is real JSON, so whitespace and key order carry no meaning and it is
# parsed rather than pattern-matched; only the keys and their shapes are checked.
ACTION_UI_METADATA_KEYS = frozenset(["version", "size", "icon"])
ACTION_UI_METADATA_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")
# an inline data URI, e.g. data:image/png;base64,iVBORw0KGgo... -- the payload
# (usually a base64-encoded icon) is not inspected beyond being non-empty.
DATA_URI_RE = re.compile(r"^data:[\w.+-]+/[\w.+-]+(?:;[\w.+-]+)*,.+$", re.DOTALL)
# how much of an offending value to quote in a message; an action-ui-metadata
# icon is a base64 blob that would otherwise bury the rest of the report.
VALUE_QUOTE_LIMIT = 120

# a prefetch statement or an "add prefetch item" line (user-supplied shape).
# A statement's sha1 is optional -- but only when it has a sha256, current
# BigFix clients accept a sha256-only statement (bes-actionscript-validate-
# prefetch's W405 is the same judgement); a block item's sha1 is unaffected
# here, that is W402's business in the sibling hook, not a shape issue.
PREFETCH_OK_RE = re.compile(
    r"(^prefetch \S+ (sha1:\S{40} )?size:\d+ https*:\/\/\S+ sha256:\S{64}$"
    r"|^\s+add prefetch item name=\S+ sha1=\S{40} size=\d+ url=https*:\/\/\S+"
    r" sha256=\S{64}$)"
)
DOWNLOAD_KEYWORD_RE = re.compile(r"prefetch|download|add prefetch item", re.IGNORECASE)

# a line whose first non-whitespace token is the `download` action verb (a
# dynamic download); a `download` appearing later on a line, or in a comment,
# is not matched -- only a real statement is.
DOWNLOAD_STMT_RE = re.compile(r"^[ \t]*download\b", re.IGNORECASE)
# the URL inside a prefetch / add-prefetch-item line (used to check the scheme)
PREFETCH_URL_RE = re.compile(r"\b(?:url=|https?://)", re.IGNORECASE)
PREFETCH_URL_SCHEME_RE = re.compile(r"(?:url=)?(https?)://", re.IGNORECASE)

# <Title>, <Relevance>, and <CVENames> element bodies
TITLE_TAG_RE = re.compile(r"<Title>(.*?)</Title>", re.DOTALL)
RELEVANCE_TAG_RE = re.compile(r"<Relevance>(.*?)</Relevance>", re.DOTALL)
CVENAMES_TAG_RE = re.compile(r"<CVENames>(.*?)</CVENames>", re.DOTALL)

# a single CVE identifier, e.g. CVE-2021-44228 (4-digit year, 4+ digit sequence)
CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$")

# the default placeholder titles the BigFix console emits for new content
DEFAULT_TITLES = frozenset(
    ["custom fixlet", "custom task", "custom baseline", "custom analysis"]
)
# a TODO/FIXME marker left in a Title, e.g. "... TODO:testing" or "... FIXME"
TODO_RE = re.compile(r"\bTODO\b|\bFIXME\b", re.IGNORECASE)

# a <SuccessCriteria Option="..."> ... </SuccessCriteria> action element; the
# body is a RelevanceString, meaningful only when Option="CustomRelevance"
SUCCESS_CRITERIA_RE = re.compile(
    r"<SuccessCriteria\b([^>]*)>(.*?)</SuccessCriteria>", re.DOTALL
)
SUCCESS_CRITERIA_OPTION_RE = re.compile(r'Option\s*=\s*"([^"]*)"')

# an <Action ID="..."> or <DefaultAction ID="..."> open tag
ACTION_ID_RE = re.compile(r'<(?:Default)?Action\s+ID\s*=\s*"([^"]*)"')

# an x-relevance-evaluation-period value: an HH:MM:SS duration (the hour
# component is a plain duration, not a clock hour, so it is not capped at 23)
EVALUATION_PERIOD_RE = re.compile(r"^\d{2,}:[0-5]\d:[0-5]\d$")

# <SourceSeverity> body
SOURCE_SEVERITY_RE = re.compile(r"<SourceSeverity>(.*?)</SourceSeverity>", re.DOTALL)
# the canonical, exact-case severity vocabulary; empty is always allowed
CANONICAL_SEVERITIES = frozenset(
    ["Low", "Moderate", "Important", "Critical", "Unspecified"]
)

# characters not allowed in a filename on common filesystems -- used to derive
# the expected filename stem from a content object's Title (W217)
FILENAME_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|]')

# an XML declaration at the very start of the document, and its encoding value
XML_DECL_RE = re.compile("^\\ufeff?\\s*<\\?xml\\b([^>]*)\\?>")
XML_DECL_ENCODING_RE = re.compile(r'encoding\s*=\s*"([^"]*)"', re.IGNORECASE)
XML_DECL_VERSION_RE = re.compile(r'version\s*=\s*"([^"]*)"', re.IGNORECASE)
# trailing spaces/tabs at the end of any line (LF-normalized text)
TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)

# an entity reference for a character that requires CDATA (or escaping): < > &
# -- either the named entity or a decimal/hex numeric reference to it. A literal
# `>` is valid XML text and does NOT require CDATA, so it is deliberately absent.
SPECIAL_ENTITY_RE = re.compile(
    r"&(?:lt|gt|amp|#0*(?:60|62|38)|#x0*(?:3c|3e|26));", re.IGNORECASE
)
# text elements whose content should be CDATA-wrapped when it has special chars
CDATA_ELEMENT_RE = re.compile(
    r"<(Description|Relevance|ActionScript)\b[^>]*>(.*?)</\1>", re.DOTALL
)
# a real child element open tag (distinguishes an action <Description>, whose
# body is <PreLink>/<Link>/<PostLink> markup, from an entity-escaped text body)
CHILD_ELEMENT_RE = re.compile(r"<[A-Za-z]")

ACTIONSCRIPT_OPEN_RE = re.compile(r"<ActionScript\b([^>]*)>")
ACTIONSCRIPT_FULL_RE = re.compile(
    r"<ActionScript\b([^>]*)>(.*?)</ActionScript>", re.DOTALL
)
MIMETYPE_ATTR_RE = re.compile(r'MIMEType\s*=\s*"([^"]*)"')
SRD_RE = re.compile(r"<SourceReleaseDate>(.*?)</SourceReleaseDate>", re.DOTALL)
DOWNLOAD_SIZE_TAG_RE = re.compile(r"<DownloadSize>(.*?)</DownloadSize>", re.DOTALL)
MODTIME_VALUE_RE = re.compile(
    r"<Name>\s*"
    + re.escape(MODIFICATION_TIME_NAME)
    + r"\s*</Name>\s*<Value>(.*?)</Value>",
    re.DOTALL,
)
FIRST_PROP_VALUE_RE = re.compile(
    r"<Name>\s*"
    + re.escape(FIRST_PROPAGATION_NAME)
    + r"\s*</Name>\s*<Value>(.*?)</Value>",
    re.DOTALL,
)
NAMED_MIMEFIELD_RE = re.compile(
    r"<Name>\s*([^<]*?)\s*</Name>\s*<Value>(.*?)</Value>", re.DOTALL
)
CONTENT_OPEN_RE = re.compile(r"<(" + "|".join(sorted(CONTENT_TAGS)) + r")\b")
CONTENT_BLOCK_RE = re.compile(r"(<(Task|Fixlet)\b[^>]*>)(.*?)(</\2>)", re.DOTALL)
# a whole content object (open tag through matching close), used to split a <BES>
# into the independent entities it contains so each is checked/fixed on its own.
CONTENT_OBJECT_SPAN_RE = re.compile(
    r"<(" + "|".join(sorted(CONTENT_TAGS)) + r")\b[^>]*>.*?</\1>", re.DOTALL
)
MUSTACHE_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)
CDATA_RE = re.compile(r"^<!\[CDATA\[(.*)\]\]>$", re.DOTALL)
# 2+ blank lines immediately before a </ActionScript> close (an optional CDATA
# terminator may sit between the blank lines and the close tag)
BLANK_BEFORE_CLOSE_RE = re.compile(
    r"(\n)(?:[ \t]*\n){2,}([ \t]*(?:\]\]>)?[ \t]*</ActionScript>)"
)
# an ActionScript close tag -- either the CDATA terminator `]]>` or, for a
# non-CDATA body, the bare close itself -- with the whitespace that may
# surround it. Whitespace before `]]>` (or before a bare close) is INSIDE the
# ActionScript (so it is action content), and whitespace after `]]>` is
# element text that BigFix appends to the same body -- either way it is a
# spurious whitespace-only last line of the action (E215).
CDATA_CLOSE_RE = re.compile(r"[ \t]*(?:\]\]>)?[ \t]*</ActionScript>")
CDATA_CLOSE_CANONICAL = "]]></ActionScript>"
CDATA_CLOSE_CANONICAL_PLAIN = "</ActionScript>"

# where a new SourceReleaseDate / modification-time MIMEField may be inserted so
# the result still satisfies the BES.xsd element ordering
SRD_ANCHORS = (
    "<SourceSeverity",
    "<CVENames",
    "<SANSID",
    "<MIMEField",
    "<Domain",
    "<DefaultAction",
    "<Action",
)
MODTIME_ANCHORS = ("<Domain", "<DefaultAction", "<Action", "<SingleAction")

KNOWN_CODES = frozenset(
    [
        "E200",  # ActionScript MIMEType missing / not allowed
        "E201",  # SourceReleaseDate not YYYY-MM-DD
        "E202",  # modification-time value not in expected format
        "E203",  # DownloadSize not 0-or-positive-integer
        "E204",  # Description contains the boilerplate placeholder
        "E205",  # x-fixlet-cpe23-item-name not a valid CPE 2.3 string
        "E206",  # action-ui-metadata not well-formed
        "E207",  # entity-escaped special chars where CDATA is required
        "E208",  # file is not entirely CRLF-terminated
        "E209",  # CVENames value invalid or multiple CVENames elements
        "E210",  # duplicate MIMEField Name within one content object
        "E211",  # Title is a default placeholder value
        "E212",  # Relevance is the literal `true`
        "E213",  # Relevance is empty / whitespace only
        "E214",  # XML declaration missing or not encoding="UTF-8"
        "E215",  # whitespace around an ActionScript CDATA terminator
        "E216",  # x-fixlet-first-propagation value not a valid RFC 5322 date-time
        "E217",  # SuccessCriteria body/Option consistency
        "E218",  # duplicate Action ID within one content object
        "E219",  # x-relevance-evaluation-period value not a valid HH:MM:SS duration
        "W200",  # not parseable BES XML; skipped
        "W201",  # Task/Fixlet missing x-fixlet-modification-time
        "W202",  # Task/Fixlet missing SourceReleaseDate
        "W203",  # DownloadSize > 0 but no download keyword in an ActionScript
        "W204",  # ActionScript body not wrapped in CDATA
        "W205",  # more than one blank line before </ActionScript>
        "W206",  # prefetch / add-prefetch-item line malformed
        "W207",  # prefetch / add-prefetch-item URL is not https
        "W208",  # ActionScript body empty (only blank lines and //-comments)
        "W209",  # Title has leading/trailing whitespace or embedded tabs
        "W210",  # a line has trailing whitespace
        "W211",  # ActionScript uses a dynamic `download` statement
        "W212",  # Relevance is the literal `false`
        "W213",  # Relevance has leading/trailing whitespace
        "W214",  # Title contains a TODO/FIXME marker
        "W215",  # Task/Fixlet Description is empty or missing
        "W216",  # SourceSeverity not in the canonical vocabulary
        "W217",  # (--check-filename only) filename does not match Title
    ]
)


def _now():
    """Return the current UTC time (isolated so tests can monkeypatch it)."""
    return datetime.now(timezone.utc)


def _today_str(now=None):
    """Return today's date as YYYY-MM-DD."""
    return (now or _now()).strftime("%Y-%m-%d")


def _modtime_str(now=None):
    """Return the current time as e.g. `Tue, 14 Jul 2026 18:32:35 +0000`."""
    return (now or _now()).strftime("%a, %d %b %Y %H:%M:%S %z")


def _lineno(src, pos):
    """Return the 1-based line number of character offset `pos` in `src`."""
    return src.count("\n", 0, pos) + 1


def _is_all_crlf(raw):
    """True if the raw bytes use CRLF throughout (no lone LF and no lone CR).

    A file with no line breaks at all is trivially CRLF-consistent.
    """
    crlf = raw.count(b"\r\n")
    return raw.count(b"\n") == crlf and raw.count(b"\r") == crlf


def _to_crlf(text):
    """Return `text` with every line ending normalized to CRLF."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


def _strip_cdata(text):
    """Return `text` trimmed, with a wrapping <![CDATA[ ... ]]> removed if present."""
    text = text.strip()
    match = CDATA_RE.match(text)
    return match.group(1).strip() if match else text


def _xml_unescape(text):
    """Decode XML entity references (named and numeric) to their characters.

    `&amp;` is decoded last so `&amp;lt;` becomes the literal text `&lt;`, not `<`.
    """
    text = (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )
    text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    return text.replace("&amp;", "&")


def _valid_source_release_date(value):
    """True if `value` is a real YYYY-MM-DD date."""
    if not SOURCE_RELEASE_DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)  # parsed only to reject impossible dates
    except ValueError:
        return False
    return True


def _valid_timestamp(value):
    """True if `value` is a valid RFC 5322 date-time (E202 / E216).

    `Tue, 14 Jul 2026 18:32:35 +0000` and `14 Jul 2026 18:32:35 +0000` (no
    day-of-week) are both valid; `Fri, 14 Jul 2026 18:32:35 +0000` is not,
    because 14 Jul 2026 is actually a Tuesday. See the module docstring's
    "Timestamp fields" section for the full rule.
    """
    match = TIMESTAMP_RE.match(value)
    if not match:
        return False
    if match.group("mon") not in MONTHS:
        return False
    dow = match.group("dow")
    if dow is not None and dow not in WEEKDAYS:
        return False
    try:
        # Parsed from `rest` (the day-of-week, if any, already matched and
        # verified above) so a correctly-spelled but wrong-for-the-date
        # weekday can't slip past strptime, which does not check that.
        # %z also rejects a bare zone name (no "GMT"/"UTC"/"Z") and an
        # out-of-range offset (magnitude >= 24 hours), which is exactly the
        # "must represent a valid offset" requirement.
        parsed = datetime.strptime(match.group("rest"), "%d %b %Y %H:%M:%S %z")
    except ValueError:
        return False
    return not (dow is not None and WEEKDAY_ABBREVS[parsed.weekday()] != dow)


def _valid_cpe23(value):
    """True if `value` is a CPE 2.3 formatted string."""
    return bool(CPE23_RE.match(value))


def _valid_action_ui_metadata(value):
    """True if `value` is a well-formed action-ui-metadata object.

    It must be a JSON object with a dotted-numeric `version` string and a
    non-negative integer `size` (quoted or bare -- the console emits both),
    plus an optional `icon` data URI. Whitespace and key order are
    insignificant; keys outside that set are not recognised.
    """
    try:
        data = json.loads(value)
    except ValueError:
        return False
    if not isinstance(data, dict) or not ACTION_UI_METADATA_KEYS.issuperset(data):
        return False

    version = data.get("version")
    if not isinstance(version, str) or not ACTION_UI_METADATA_VERSION_RE.match(version):
        return False

    size = data.get("size")
    if isinstance(size, str):
        if not DOWNLOAD_SIZE_RE.match(size):
            return False
    elif not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return False

    icon = data.get("icon")
    return icon is None or (isinstance(icon, str) and bool(DATA_URI_RE.match(icon)))


def _quote(value, limit=VALUE_QUOTE_LIMIT):
    """`value` shortened for use in a message, with an elision marker if cut."""
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "..."


# --------------------------------------------------------------------------
# checks (each returns a list of (lineno, code, message))
# --------------------------------------------------------------------------


def check_action_mimetypes(src):
    """E200: every <ActionScript> must carry a MIMEType from the allowed set."""
    issues = []
    for match in ACTIONSCRIPT_OPEN_RE.finditer(src):
        attrs = match.group(1)
        lineno = _lineno(src, match.start())
        mime_match = MIMETYPE_ATTR_RE.search(attrs)
        if mime_match is None:
            issues.append(
                (
                    lineno,
                    "E200",
                    (
                        "ActionScript has no MIMEType; add one of "
                        f"{sorted(ALLOWED_MIMETYPES)}; add `{MIMETYPE_MARKER}` if intentional"
                    ),
                )
            )
        elif mime_match.group(1) not in ALLOWED_MIMETYPES:
            issues.append(
                (
                    lineno,
                    "E200",
                    (
                        f'ActionScript MIMEType "{mime_match.group(1)}" is not one of '
                        f"{sorted(ALLOWED_MIMETYPES)}; add `{MIMETYPE_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def check_source_release_date_format(src):
    """E201: every <SourceReleaseDate> present must be YYYY-MM-DD (empty allowed)."""
    issues = []
    for match in SRD_RE.finditer(src):
        value = _strip_cdata(match.group(1))
        if value == "":
            continue
        if not _valid_source_release_date(value):
            issues.append(
                (
                    _lineno(src, match.start()),
                    "E201",
                    (
                        f'SourceReleaseDate "{value}" is not in YYYY-MM-DD format; '
                        f"add `{SOURCE_RELEASE_DATE_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def check_modification_time_format(src):
    """E202: every x-fixlet-modification-time value must be a valid RFC 5322 date-
    time.
    """
    issues = []
    for match in MODTIME_VALUE_RE.finditer(src):
        value = _strip_cdata(match.group(1))
        if not _valid_timestamp(value):
            issues.append(
                (
                    _lineno(src, match.start()),
                    "E202",
                    (
                        f'x-fixlet-modification-time "{value}" is not a valid RFC 5322 '
                        "date-time (e.g. `Tue, 14 Jul 2026 18:32:35 +0000`); add "
                        f"`{MODIFICATION_TIME_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def check_first_propagation_format(src):
    """E216: every x-fixlet-first-propagation value must be a valid RFC 5322 date-
    time.
    """
    issues = []
    for match in FIRST_PROP_VALUE_RE.finditer(src):
        value = _strip_cdata(match.group(1))
        if not _valid_timestamp(value):
            issues.append(
                (
                    _lineno(src, match.start()),
                    "E216",
                    (
                        f'x-fixlet-first-propagation "{value}" is not a valid RFC 5322 '
                        "date-time (e.g. `Tue, 14 Jul 2026 18:32:35 +0000`); add "
                        f"`{FIRST_PROPAGATION_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def check_download_size_value(src):
    """E203: every <DownloadSize> present must be 0 or a positive integer."""
    issues = []
    for match in DOWNLOAD_SIZE_TAG_RE.finditer(src):
        value = _strip_cdata(match.group(1))
        if value == "" or not DOWNLOAD_SIZE_RE.match(value):
            issues.append(
                (
                    _lineno(src, match.start()),
                    "E203",
                    (
                        f'DownloadSize "{value}" is not 0 or a positive integer; '
                        f"add `{DOWNLOAD_SIZE_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def check_action_ui_metadata(src):
    """E206: an action-ui-metadata value must be well-formed."""
    issues = []
    for match in NAMED_MIMEFIELD_RE.finditer(src):
        if match.group(1).strip() != "action-ui-metadata":
            continue
        value = _strip_cdata(match.group(2))
        if not _valid_action_ui_metadata(value):
            issues.append(
                (
                    _lineno(src, match.start()),
                    "E206",
                    (
                        f'action-ui-metadata "{_quote(value)}" is not well-formed; add '
                        f"`{ACTION_UI_METADATA_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def check_cpe23(src):
    """E205: an x-fixlet-cpe23-item-name value must be a valid CPE 2.3 string."""
    issues = []
    for match in NAMED_MIMEFIELD_RE.finditer(src):
        if match.group(1).strip().lower() != "x-fixlet-cpe23-item-name":
            continue
        value = _strip_cdata(match.group(2))
        if not _valid_cpe23(value):
            issues.append(
                (
                    _lineno(src, match.start()),
                    "E205",
                    (
                        f'x-fixlet-cpe23-item-name "{value}" is not a valid CPE 2.3 '
                        f"string; add `{CPE_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def check_cdata_required(src):
    """E207: a Description/Relevance/ActionScript that entity-escapes < > &.

    Such content should use <![CDATA[ ... ]]> instead. Elements already wrapped in
    CDATA are fine, and elements whose body is real child markup (an action's
    <Description> of <PreLink>/<Link>/<PostLink>) are not text bodies at all, so
    both are skipped.
    """
    issues = []
    for match in CDATA_ELEMENT_RE.finditer(src):
        tag, inner = match.group(1), match.group(2)
        if "<![CDATA[" in inner or CHILD_ELEMENT_RE.search(inner):
            continue
        if SPECIAL_ENTITY_RE.search(inner):
            issues.append(
                (
                    _lineno(src, match.start()),
                    "E207",
                    (
                        f"{tag} entity-escapes a character (< > &) that requires "
                        f"<![CDATA[ ... ]]>; add `{CDATA_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def check_actionscript_cdata(src):
    """W204: an ActionScript body should be wrapped in <![CDATA[ ... ]]>.

    Bodies that entity-escape special chars are owned by E207, not warned here.
    """
    issues = []
    for match in ACTIONSCRIPT_FULL_RE.finditer(src):
        body = match.group(2)
        if "<![CDATA[" in body or SPECIAL_ENTITY_RE.search(body):
            continue
        issues.append(
            (
                _lineno(src, match.start()),
                "W204",
                (
                    "ActionScript body is not wrapped in <![CDATA[ ... ]]>; add "
                    f"`{CDATA_MARKER}` if intentional (auto-fixable under --strict)"
                ),
            )
        )
    return issues


def check_actionscript_blank_lines(src):
    """W205: no more than one blank line before </ActionScript>."""
    issues = []
    for match in BLANK_BEFORE_CLOSE_RE.finditer(src):
        issues.append(
            (
                _lineno(src, match.start()),
                "W205",
                (
                    "more than one blank line before </ActionScript>; add "
                    f"`{ACTION_BLANK_LINES_MARKER}` if intentional"
                ),
            )
        )
    return issues


def check_cdata_close(src):
    """E215: no whitespace may surround an ActionScript close tag.

    Applies to both the CDATA terminator (`]]></ActionScript>`) and, for a
    non-CDATA body, the bare close (`</ActionScript>`).
    """
    issues = []
    for match in CDATA_CLOSE_RE.finditer(src):
        canonical = (
            CDATA_CLOSE_CANONICAL
            if "]]>" in match.group(0)
            else CDATA_CLOSE_CANONICAL_PLAIN
        )
        if match.group(0) == canonical:
            continue
        issues.append(
            (
                _lineno(src, match.start()),
                "E215",
                (
                    "whitespace before the ActionScript close tag (it becomes "
                    f"a whitespace-only last action line); add `{CDATA_CLOSE_MARKER}` "
                    "if intentional"
                ),
            )
        )
    return issues


def check_prefetch_lines(src):
    """W206: a prefetch / add-prefetch-item line must match the expected shape."""
    issues = []
    for match in ACTIONSCRIPT_FULL_RE.finditer(src):
        body = match.group(2)
        base = _lineno(src, match.start(2))
        for offset, raw in enumerate(body.splitlines()):
            line = raw.rstrip("\r")
            stripped = line.strip()
            is_prefetch = stripped.startswith("prefetch ")
            is_add = "add prefetch item" in stripped
            if not (is_prefetch or is_add):
                continue
            if PREFETCH_OK_RE.fullmatch(line) or PREFETCH_OK_RE.fullmatch(stripped):
                continue
            issues.append(
                (
                    base + offset,
                    "W206",
                    (
                        f'prefetch line "{stripped[:60]}" does not match the expected '
                        f"shape; add `{PREFETCH_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def check_prefetch_https(src):
    """W207: a prefetch / add-prefetch-item URL should use https, not http."""
    issues = []
    for match in ACTIONSCRIPT_FULL_RE.finditer(src):
        body = match.group(2)
        base = _lineno(src, match.start(2))
        for offset, raw in enumerate(body.splitlines()):
            line = raw.rstrip("\r")
            stripped = line.strip()
            is_prefetch = stripped.startswith("prefetch ")
            is_add = "add prefetch item" in stripped
            if not (is_prefetch or is_add):
                continue
            scheme = PREFETCH_URL_SCHEME_RE.search(line)
            if scheme is not None and scheme.group(1).lower() == "http":
                issues.append(
                    (
                        base + offset,
                        "W207",
                        (
                            f'prefetch URL in "{stripped[:60]}" uses http, not https; '
                            f"add `{PREFETCH_HTTPS_MARKER}` if intentional"
                        ),
                    )
                )
    return issues


def _actionscript_is_empty(body):
    """True if an ActionScript body has only blank lines and //-comment lines."""
    content = _strip_cdata(body)
    for raw in content.splitlines():
        line = raw.strip()
        if line and not line.startswith("//"):
            return False
    return True


def check_empty_actionscript(src):
    """W208: an ActionScript body must contain more than blank/// lines."""
    issues = []
    for match in ACTIONSCRIPT_FULL_RE.finditer(src):
        if _actionscript_is_empty(match.group(2)):
            issues.append(
                (
                    _lineno(src, match.start()),
                    "W208",
                    (
                        "ActionScript body is empty (only blank lines and "
                        f"//-comments); add `{ACTIONSCRIPT_EMPTY_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def check_dynamic_download(src):
    """W211: warn on a dynamic `download` statement (prefer a static prefetch)."""
    issues = []
    for match in ACTIONSCRIPT_FULL_RE.finditer(src):
        body = match.group(2)
        base = _lineno(src, match.start(2))
        for offset, raw in enumerate(body.splitlines()):
            line = raw.rstrip("\r")
            if DOWNLOAD_STMT_RE.match(line):
                issues.append(
                    (
                        base + offset,
                        "W211",
                        (
                            f'ActionScript uses a dynamic download statement "'
                            f'{line.strip()[:60]}"; prefer a static prefetch; add '
                            f"`{DOWNLOAD_MARKER}` if intentional"
                        ),
                    )
                )
    return issues


def check_cve_names(src):
    """E209: each <CVENames> value must be a valid CVE id; only one CVENames.

    A single <CVENames> may hold several comma/space-separated CVE ids, but a
    content object must not carry more than one <CVENames> element.
    """
    issues = []
    matches = list(CVENAMES_TAG_RE.finditer(src))
    if len(matches) > 1:
        issues.append(
            (
                _lineno(src, matches[1].start()),
                "E209",
                (
                    "more than one <CVENames> element in a content object; combine "
                    f"into one comma-separated CVENames; add `{CVE_NAMES_MARKER}` "
                    "if intentional"
                ),
            )
        )
    for match in matches:
        value = _strip_cdata(match.group(1))
        for token in re.split(r"[,\s]+", value):
            if token and not CVE_RE.match(token):
                issues.append(
                    (
                        _lineno(src, match.start()),
                        "E209",
                        (
                            f'CVENames value "{token}" is not a valid CVE id (e.g. '
                            f"CVE-2021-44228); add `{CVE_NAMES_MARKER}` if intentional"
                        ),
                    )
                )
    return issues


def check_duplicate_mimefield_names(src):
    """E210: two <MIMEField> entries in one object must not share a <Name>."""
    issues = []
    seen = {}
    for match in NAMED_MIMEFIELD_RE.finditer(src):
        name = match.group(1).strip()
        if name in seen:
            issues.append(
                (
                    _lineno(src, match.start()),
                    "E210",
                    (
                        f'duplicate MIMEField <Name> "{name}" in one content object; '
                        f"add `{MIMEFIELD_DUP_MARKER}` if intentional"
                    ),
                )
            )
        else:
            seen[name] = match.start()
    return issues


def check_success_criteria(src):
    """E217: a <SuccessCriteria> body/Option combination must be consistent.

    A CustomRelevance body must be real relevance (not empty, not the literal
    `false`, which can never succeed); a non-CustomRelevance SuccessCriteria
    (OriginalRelevance, RunToCompletion, or no Option at all) must have an
    empty body, since BigFix silently ignores anything else there.
    """
    issues = []
    for match in SUCCESS_CRITERIA_RE.finditer(src):
        attrs, body = match.group(1), match.group(2)
        lineno = _lineno(src, match.start())
        option_match = SUCCESS_CRITERIA_OPTION_RE.search(attrs)
        option = option_match.group(1) if option_match else None
        value = _strip_cdata(body).strip()
        if option == "CustomRelevance":
            if value == "":
                issues.append(
                    (
                        lineno,
                        "E217",
                        (
                            'SuccessCriteria Option="CustomRelevance" has an empty '
                            f"relevance body; add `{SUCCESS_CRITERIA_MARKER}` if "
                            "intentional"
                        ),
                    )
                )
            elif value.lower() == "false":
                issues.append(
                    (
                        lineno,
                        "E217",
                        (
                            'SuccessCriteria Option="CustomRelevance" body is the '
                            "literal `false`; it can never succeed; add "
                            f"`{SUCCESS_CRITERIA_MARKER}` if intentional"
                        ),
                    )
                )
        elif value != "":
            issues.append(
                (
                    lineno,
                    "E217",
                    (
                        f'SuccessCriteria has a relevance body but Option is "{option}"'
                        ', not "CustomRelevance"; the body is silently ignored; add '
                        f"`{SUCCESS_CRITERIA_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def check_duplicate_action_ids(src):
    """E218: two Action/DefaultAction elements in one object must not share an ID."""
    issues = []
    seen = {}
    for match in ACTION_ID_RE.finditer(src):
        action_id = match.group(1)
        if action_id in seen:
            issues.append(
                (
                    _lineno(src, match.start()),
                    "E218",
                    (
                        f'duplicate Action ID "{action_id}" in one content object; '
                        f"add `{ACTION_ID_MARKER}` if intentional"
                    ),
                )
            )
        else:
            seen[action_id] = match.start()
    return issues


def check_evaluation_period(src):
    """E219: an x-relevance-evaluation-period value must be a valid HH:MM:SS."""
    issues = []
    for match in NAMED_MIMEFIELD_RE.finditer(src):
        if match.group(1).strip().lower() != "x-relevance-evaluation-period":
            continue
        value = _strip_cdata(match.group(2))
        if not EVALUATION_PERIOD_RE.match(value):
            issues.append(
                (
                    _lineno(src, match.start()),
                    "E219",
                    (
                        f'x-relevance-evaluation-period "{value}" is not a valid '
                        f"HH:MM:SS duration; add `{EVALUATION_PERIOD_MARKER}` if "
                        "intentional"
                    ),
                )
            )
    return issues


def check_source_severity(src, allowed=CANONICAL_SEVERITIES):
    """W216: a non-empty <SourceSeverity> must be in the allowed vocabulary.

    `allowed` defaults to CANONICAL_SEVERITIES but can be overridden (see
    --severity-values) to whatever exact-case values a repo wants to permit.
    """
    issues = []
    for match in SOURCE_SEVERITY_RE.finditer(src):
        value = _strip_cdata(match.group(1)).strip()
        if value == "" or value in allowed:
            continue
        issues.append(
            (
                _lineno(src, match.start()),
                "W216",
                (
                    f'SourceSeverity "{value}" is not one of '
                    f"{sorted(allowed)}; add `{SEVERITY_MARKER}` if intentional"
                ),
            )
        )
    return issues


def check_title(src):
    """E211/W209/W214: a <Title> placeholder, stray whitespace, or TODO marker."""
    issues = []
    for match in TITLE_TAG_RE.finditer(src):
        inner = match.group(1)
        lineno = _lineno(src, match.start())
        value = _strip_cdata(inner)
        if value.strip().lower() in DEFAULT_TITLES:
            issues.append(
                (
                    lineno,
                    "E211",
                    (
                        f'Title "{value.strip()}" is a default placeholder; give it a '
                        f"real title; add `{TITLE_MARKER}` if intentional"
                    ),
                )
            )
        if "<![CDATA[" not in inner and (inner != inner.strip() or "\t" in inner):
            issues.append(
                (
                    lineno,
                    "W209",
                    (
                        "Title has leading/trailing whitespace or embedded tabs; add "
                        f"`{TITLE_MARKER}` if intentional"
                    ),
                )
            )
        if TODO_RE.search(value):
            issues.append(
                (
                    lineno,
                    "W214",
                    (
                        f'Title "{value.strip()}" contains a TODO/FIXME marker; add '
                        f"`{TITLE_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def check_relevance(src):
    """E212/E213/W212/W213: Relevance empty/`true`/`false`, or stray whitespace."""
    issues = []
    for match in RELEVANCE_TAG_RE.finditer(src):
        inner = match.group(1)
        value = _strip_cdata(inner).strip()
        lineno = _lineno(src, match.start())
        if value == "":
            issues.append(
                (
                    lineno,
                    "E213",
                    (
                        "Relevance is empty; give it a real relevance clause; add "
                        f"`{RELEVANCE_MARKER}` if intentional"
                    ),
                )
            )
        elif value.lower() == "true":
            issues.append(
                (
                    lineno,
                    "E212",
                    (
                        "Relevance is the literal `true`; it targets every endpoint; "
                        f"add `{RELEVANCE_MARKER}` if intentional"
                    ),
                )
            )
        elif value.lower() == "false":
            issues.append(
                (
                    lineno,
                    "W212",
                    (
                        "Relevance is the literal `false`; it never applies to any "
                        f"endpoint; add `{RELEVANCE_MARKER}` if intentional"
                    ),
                )
            )
        if "<![CDATA[" not in inner and inner != inner.strip():
            issues.append(
                (
                    lineno,
                    "W213",
                    (
                        "Relevance has leading/trailing whitespace; add "
                        f"`{RELEVANCE_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def _content_object_blocks(root, src):
    """Return ordered [(start, end, element)] for the content objects in `src`.

    The regex spans (in document order) are zipped with the ElementTree
    content-tag children (same order) so each block carries its parsed element.
    Each block is an independent entity: it is checked and fixed on its own, and
    a marker only governs the block it sits in (see `_outside_text`).
    """
    spans = [(m.start(), m.end()) for m in CONTENT_OBJECT_SPAN_RE.finditer(src)]
    children = [
        child
        for child in list(root)
        if isinstance(child.tag, str) and child.tag in CONTENT_TAGS
    ]
    return [
        (start, end, children[i] if i < len(children) else None)
        for i, (start, end) in enumerate(spans)
    ]


def _outside_text(src, blocks):
    """Return `src` with every content-object block removed.

    A marker appearing here is outside all objects, so it is file-level and
    governs every object; a marker inside a block governs only that block.
    """
    parts = []
    cursor = 0
    for start, end, _ in blocks:
        parts.append(src[cursor:start])
        cursor = end
    parts.append(src[cursor:])
    return "".join(parts)


def _has_modification_time(element):
    """True if `element` has a MIMEField named x-fixlet-modification-time."""
    for mimefield in element.findall("MIMEField"):
        name = mimefield.find("Name")
        if name is not None and (name.text or "").strip() == MODIFICATION_TIME_NAME:
            return True
    return False


def _action_scripts_text(element):
    """Return the concatenated text of every ActionScript under `element`."""
    return "\n".join((a.text or "") for a in element.iter("ActionScript"))


def _check_element(tag, element, disabled):
    """E204 for any content object plus W201/W202/W203 for a Task/Fixlet.

    Issues are reported at local line 1 -- the block's open tag; the caller
    offsets it to the file line.
    """
    if element is None or tag not in CONTENT_TAGS:
        return []
    issues = []
    title = element.find("Title")
    label = (title.text or "").strip() if title is not None else ""
    where = f' ("{label}")' if label else ""

    if "E204" not in disabled:
        description = element.find("Description")
        text = "".join(description.itertext()) if description is not None else ""
        if DESCRIPTION_PLACEHOLDER in text.lower():
            issues.append(
                (
                    1,
                    "E204",
                    (
                        f"{tag}{where} Description contains the placeholder "
                        f'"{DESCRIPTION_PLACEHOLDER}"; add `{DESCRIPTION_MARKER}` '
                        "if intentional"
                    ),
                )
            )
    if tag not in DATED_CONTENT_TAGS:
        return issues

    if "W215" not in disabled:
        description = element.find("Description")
        text = (
            "".join(description.itertext()).strip() if description is not None else ""
        )
        if text == "":
            issues.append(
                (
                    1,
                    "W215",
                    (
                        f"{tag}{where} has an empty or missing Description; add "
                        f"`{DESCRIPTION_MARKER}` if intentional"
                    ),
                )
            )
    if "W201" not in disabled and not _has_modification_time(element):
        issues.append(
            (
                1,
                "W201",
                (
                    f"{tag}{where} has no x-fixlet-modification-time MIMEField; add "
                    f"`{MODIFICATION_TIME_MARKER}` if intentional"
                ),
            )
        )
    if "W202" not in disabled and element.find("SourceReleaseDate") is None:
        issues.append(
            (
                1,
                "W202",
                (
                    f"{tag}{where} has no SourceReleaseDate; add "
                    f"`{SOURCE_RELEASE_DATE_MARKER}` if intentional"
                ),
            )
        )
    if "W203" not in disabled:
        download = element.find("DownloadSize")
        raw = _strip_cdata(download.text or "") if download is not None else ""
        size = int(raw) if DOWNLOAD_SIZE_RE.match(raw) else 0
        if size > 0 and not DOWNLOAD_KEYWORD_RE.search(_action_scripts_text(element)):
            issues.append(
                (
                    1,
                    "W203",
                    (
                        f"{tag}{where} has DownloadSize > 0 but no download/prefetch "
                        f"keyword in any ActionScript; add `{DOWNLOAD_SIZE_MARKER}` "
                        "if intentional"
                    ),
                )
            )
    return issues


# (codes, opt-out marker, check function) for the checks that scan element text;
# each function scans a single content-object block and returns local linenos.
# `codes` is the tuple of check IDs the function can emit: the check is skipped
# only when its marker is present or ALL of its codes are disabled, and an
# individually-disabled code is dropped from the results afterward.
VALUE_CHECKS = (
    (("E200",), MIMETYPE_MARKER, check_action_mimetypes),
    (("E201",), SOURCE_RELEASE_DATE_MARKER, check_source_release_date_format),
    (("E202",), MODIFICATION_TIME_MARKER, check_modification_time_format),
    (("E216",), FIRST_PROPAGATION_MARKER, check_first_propagation_format),
    (("E203",), DOWNLOAD_SIZE_MARKER, check_download_size_value),
    (("E205",), CPE_MARKER, check_cpe23),
    (("E206",), ACTION_UI_METADATA_MARKER, check_action_ui_metadata),
    (("E207",), CDATA_MARKER, check_cdata_required),
    (("E209",), CVE_NAMES_MARKER, check_cve_names),
    (("E210",), MIMEFIELD_DUP_MARKER, check_duplicate_mimefield_names),
    (("E211", "W209", "W214"), TITLE_MARKER, check_title),
    (("E212", "E213", "W212", "W213"), RELEVANCE_MARKER, check_relevance),
    (("E215",), CDATA_CLOSE_MARKER, check_cdata_close),
    (("E217",), SUCCESS_CRITERIA_MARKER, check_success_criteria),
    (("E218",), ACTION_ID_MARKER, check_duplicate_action_ids),
    (("E219",), EVALUATION_PERIOD_MARKER, check_evaluation_period),
    (("W216",), SEVERITY_MARKER, check_source_severity),
    (("W204",), CDATA_MARKER, check_actionscript_cdata),
    (("W205",), ACTION_BLANK_LINES_MARKER, check_actionscript_blank_lines),
    (("W206",), PREFETCH_MARKER, check_prefetch_lines),
    (("W207",), PREFETCH_HTTPS_MARKER, check_prefetch_https),
    (("W208",), ACTIONSCRIPT_EMPTY_MARKER, check_empty_actionscript),
    (("W211",), DOWNLOAD_MARKER, check_dynamic_download),
)

# (presence code, opt-out marker) -- markers scoped like the value checks
PRESENCE_MARKERS = (
    ("W201", MODIFICATION_TIME_MARKER),
    ("W202", SOURCE_RELEASE_DATE_MARKER),
    ("W203", DOWNLOAD_SIZE_MARKER),
    ("E204", DESCRIPTION_MARKER),
    ("W215", DESCRIPTION_MARKER),
)


def _value_checks(severities=None):
    """Return VALUE_CHECKS, with check_source_severity bound to `severities`.

    `severities` is None (the default -- use CANONICAL_SEVERITIES) unless
    --severity-values overrides it; only check_source_severity takes this
    parameter, so every other entry is passed through unchanged.
    """
    if severities is None:
        return VALUE_CHECKS
    return tuple(
        (
            (codes, marker, functools.partial(check, allowed=severities))
            if check is check_source_severity
            else (codes, marker, check)
        )
        for codes, marker, check in VALUE_CHECKS
    )


def _run_checks(src, root, disabled, severities=None):
    """Run every check on each content object independently; return sorted issues.

    Each block's checks see only that block's text, and a marker governs a block
    only if it sits inside it or outside all objects (file-level). Local line
    numbers from the per-block scans are offset back to the file's line numbers.
    `severities` overrides the W216 vocabulary (see --severity-values).
    """
    blocks = _content_object_blocks(root, src)
    outside = _outside_text(src, blocks)
    value_checks = _value_checks(severities)
    issues = []
    for start, _end, element in blocks:
        block = src[start:_end]
        start_line = _lineno(src, start)
        marker_text = block + outside
        for codes, marker, check in value_checks:
            if marker in marker_text or all(code in disabled for code in codes):
                continue
            for lineno, found_code, message in check(block):
                if found_code in disabled:
                    continue
                issues.append((start_line + lineno - 1, found_code, message))
        presence_disabled = set(disabled)
        for code, marker in PRESENCE_MARKERS:
            if marker in marker_text:
                presence_disabled.add(code)
        tag = element.tag if element is not None else None
        for lineno, found_code, message in _check_element(
            tag, element, presence_disabled
        ):
            issues.append((start_line + lineno - 1, found_code, message))
    return sorted(issues)


def _fix_block(block, marker_text, disabled, strict, now):
    """Apply the auto-fixers to one content-object block; return (new, fixed).

    Marker gating is the same per-block scoping used by the checks.
    """
    fixed = []
    if "E203" not in disabled and DOWNLOAD_SIZE_MARKER not in marker_text:
        block, got = fix_download_size(block)
        fixed += got
    if "W209" not in disabled and TITLE_MARKER not in marker_text:
        block, got = fix_title(block)
        fixed += got
    if "W213" not in disabled and RELEVANCE_MARKER not in marker_text:
        block, got = fix_relevance_whitespace(block)
        fixed += got
    if "W205" not in disabled and ACTION_BLANK_LINES_MARKER not in marker_text:
        block, got = fix_blank_lines(block)
        fixed += got
    if "E207" not in disabled and CDATA_MARKER not in marker_text:
        block, got = fix_cdata_required(block)
        fixed += got
    # runs after the W205 collapse, which preserves the terminator's indentation
    if "E215" not in disabled and CDATA_CLOSE_MARKER not in marker_text:
        block, got = fix_cdata_close(block)
        fixed += got
    if strict and "W204" not in disabled and CDATA_MARKER not in marker_text:
        block, got = fix_actionscript_cdata(block)
        fixed += got
    fix_srd = "W202" not in disabled and SOURCE_RELEASE_DATE_MARKER not in marker_text
    fix_modtime = "W201" not in disabled and MODIFICATION_TIME_MARKER not in marker_text
    if fix_srd or fix_modtime:
        block, got = fix_missing_dates(
            block, now, fix_srd=fix_srd, fix_modtime=fix_modtime
        )
        fixed += got
    return block, fixed


def _autofix(src, root, disabled, strict, now):
    """Rewrite each content object independently; return (new_src, fixed).

    Text outside the content objects is left untouched. Fixed line numbers are
    offset back to the file's line numbers.
    """
    blocks = _content_object_blocks(root, src)
    outside = _outside_text(src, blocks)
    result = []
    fixed = []
    cursor = 0
    for start, end, _element in blocks:
        result.append(src[cursor:start])
        block = src[start:end]
        start_line = _lineno(src, start)
        new_block, block_fixed = _fix_block(
            block, block + outside, disabled, strict, now
        )
        fixed += [
            (start_line + lineno - 1, code, message)
            for lineno, code, message in block_fixed
        ]
        result.append(new_block)
        cursor = end
    result.append(src[cursor:])
    return "".join(result), fixed


# --------------------------------------------------------------------------
# auto-fixers (each mutates `src` text and returns (new_src, fixed_list))
# --------------------------------------------------------------------------


def fix_download_size(src):
    """E203: rewrite an empty/invalid <DownloadSize> to 0."""
    fixed = []

    def repl(match):
        value = _strip_cdata(match.group(1))
        if value == "" or not DOWNLOAD_SIZE_RE.match(value):
            fixed.append(
                (
                    _lineno(src, match.start()),
                    "E203",
                    f'DownloadSize "{value}" set to 0',
                )
            )
            return "<DownloadSize>0</DownloadSize>"
        return match.group(0)

    return DOWNLOAD_SIZE_TAG_RE.sub(repl, src), fixed


def fix_title(src):
    """W209: trim a <Title> and replace embedded tabs with spaces.

    A CDATA-wrapped title is left untouched (its content is opaque here).
    """
    fixed = []

    def repl(match):
        inner = match.group(1)
        if "<![CDATA[" in inner:
            return match.group(0)
        new_inner = inner.replace("\t", " ").strip()
        if new_inner == inner:
            return match.group(0)
        fixed.append(
            (
                _lineno(src, match.start()),
                "W209",
                "trimmed Title and replaced tabs with spaces",
            )
        )
        return f"<Title>{new_inner}</Title>"

    return TITLE_TAG_RE.sub(repl, src), fixed


def fix_relevance_whitespace(src):
    """W213: trim leading/trailing whitespace from a <Relevance> body.

    A CDATA-wrapped Relevance is left untouched (its content is opaque here),
    mirroring fix_title's treatment of a CDATA-wrapped Title.
    """
    fixed = []

    def repl(match):
        inner = match.group(1)
        if "<![CDATA[" in inner:
            return match.group(0)
        new_inner = inner.strip()
        if new_inner == inner:
            return match.group(0)
        fixed.append(
            (
                _lineno(src, match.start()),
                "W213",
                "trimmed Relevance whitespace",
            )
        )
        return f"<Relevance>{new_inner}</Relevance>"

    return RELEVANCE_TAG_RE.sub(repl, src), fixed


def fix_blank_lines(src):
    """W205: collapse 2+ blank lines before </ActionScript> to one."""
    fixed = []

    def repl(match):
        fixed.append(
            (
                _lineno(src, match.start()),
                "W205",
                "collapsed blank lines before </ActionScript>",
            )
        )
        return match.group(1) + "\n" + match.group(2)

    return BLANK_BEFORE_CLOSE_RE.sub(repl, src), fixed


def fix_cdata_close(src):
    """E215: strip the whitespace before an ActionScript close tag.

    Applies to both the CDATA terminator (`]]></ActionScript>`) and, for a
    non-CDATA body, the bare close (`</ActionScript>`).
    """
    fixed = []

    def repl(match):
        canonical = (
            CDATA_CLOSE_CANONICAL
            if "]]>" in match.group(0)
            else CDATA_CLOSE_CANONICAL_PLAIN
        )
        if match.group(0) == canonical:
            return match.group(0)
        fixed.append(
            (
                _lineno(src, match.start()),
                "E215",
                "stripped whitespace before the ActionScript close tag",
            )
        )
        return canonical

    return CDATA_CLOSE_RE.sub(repl, src), fixed


def fix_cdata_required(src):
    """E207: unescape a Description/Relevance/ActionScript body and CDATA-wrap it.

    Skips a body whose unescaped text would contain `]]>`, which cannot sit
    inside a single CDATA section -- that one is left to error.
    """
    fixed = []

    def repl(match):
        tag, inner = match.group(1), match.group(2)
        if "<![CDATA[" in inner or CHILD_ELEMENT_RE.search(inner):
            return match.group(0)
        if not SPECIAL_ENTITY_RE.search(inner):
            return match.group(0)
        decoded = _xml_unescape(inner)
        if "]]>" in decoded:
            return match.group(0)
        fixed.append(
            (
                _lineno(src, match.start()),
                "E207",
                f"wrapped {tag} body in <![CDATA[ ... ]]>",
            )
        )
        open_tag = match.group(0)[: match.start(2) - match.start()]
        return f"{open_tag}<![CDATA[{decoded}]]></{tag}>"

    return CDATA_ELEMENT_RE.sub(repl, src), fixed


def fix_actionscript_cdata(src):
    """W204: wrap an un-wrapped ActionScript body in <![CDATA[ ... ]]>.

    Skips a body that already contains a `]]>` sequence, which cannot be placed
    inside a CDATA section without splitting -- that one is left to warn.
    """
    fixed = []

    def repl(match):
        attrs, body = match.group(1), match.group(2)
        if "<![CDATA[" in body or "]]>" in body:
            return match.group(0)
        fixed.append(
            (
                _lineno(src, match.start()),
                "W204",
                "wrapped ActionScript body in <![CDATA[ ... ]]>",
            )
        )
        return f"<ActionScript{attrs}><![CDATA[{body}]]></ActionScript>"

    return ACTIONSCRIPT_FULL_RE.sub(repl, src), fixed


def _detect_indent(inner):
    """Return the indentation of the first element inside a content block."""
    match = re.search(r"\n([ \t]+)<\w", inner)
    return match.group(1) if match else "\t\t"


def _insert_ordered(inner, new_text, anchors):
    """Insert `new_text` (a full indented line) before the first anchor found."""
    for anchor in anchors:
        pos = inner.find(anchor)
        if pos != -1:
            line_start = inner.rfind("\n", 0, pos) + 1
            return inner[:line_start] + new_text + inner[line_start:]
    stripped = inner.rstrip()
    trailing = inner[len(stripped) :]
    return stripped + "\n" + new_text + (trailing or "\n")


def fix_missing_dates(src, now=None, fix_srd=True, fix_modtime=True):
    """W201/W202: insert a missing SourceReleaseDate / modification time.

    Values use the moment the linter ran. Insertion positions keep the BES.xsd
    element ordering (SourceReleaseDate in the metadata block; the modification
    time MIMEField before <Domain>). `fix_srd` / `fix_modtime` gate each insert
    independently so a single per-field opt-out marker only suppresses its own.
    """
    fixed = []
    date_now = _today_str(now)
    modtime = _modtime_str(now)

    def repl(match):
        open_tag, _tag, inner, close = match.groups()
        indent = _detect_indent(inner)
        lineno = _lineno(src, match.start())
        if fix_srd and "<SourceReleaseDate" not in inner:
            inner = _insert_ordered(
                inner,
                f"{indent}<SourceReleaseDate>{date_now}</SourceReleaseDate>\n",
                SRD_ANCHORS,
            )
            fixed.append((lineno, "W202", f"inserted SourceReleaseDate {date_now}"))
        if fix_modtime and MODIFICATION_TIME_NAME not in inner:
            block = (
                f"{indent}<MIMEField>\n"
                f"{indent}\t<Name>{MODIFICATION_TIME_NAME}</Name>\n"
                f"{indent}\t<Value>{modtime}</Value>\n"
                f"{indent}</MIMEField>\n"
            )
            inner = _insert_ordered(inner, block, MODTIME_ANCHORS)
            fixed.append((lineno, "W201", "inserted x-fixlet-modification-time"))
        return open_tag + inner + close

    return CONTENT_BLOCK_RE.sub(repl, src), fixed


# --------------------------------------------------------------------------
# file-level checks / fixers (E214 XML declaration, W210 trailing whitespace)
# --------------------------------------------------------------------------


def _xml_declaration_encoding(src):
    """Return (has_decl, encoding_or_None) for the leading XML declaration."""
    match = XML_DECL_RE.match(src)
    if match is None:
        return False, None
    enc = XML_DECL_ENCODING_RE.search(match.group(1))
    return True, (enc.group(1) if enc else None)


def check_xml_declaration(src):
    """E214: the file must open with an <?xml ... encoding="UTF-8"?> declaration."""
    has_decl, encoding = _xml_declaration_encoding(src)
    if not has_decl:
        message = "file has no XML declaration"
    elif encoding is None:
        message = 'XML declaration has no encoding (expected encoding="UTF-8")'
    elif encoding.lower() != "utf-8":
        message = f'XML declaration encoding "{encoding}" is not UTF-8'
    else:
        return []
    return [(1, "E214", f"{message}; add `{XML_DECL_MARKER}` if intentional")]


def check_trailing_whitespace(src):
    """W210: no line may have trailing spaces or tabs."""
    issues = []
    for lineno, line in enumerate(src.split("\n"), start=1):
        if line != line.rstrip(" \t"):
            issues.append(
                (
                    lineno,
                    "W210",
                    (
                        "line has trailing whitespace; add "
                        f"`{TRAILING_WS_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def fix_xml_declaration(src):
    """E214: insert a UTF-8 XML declaration, or set encoding="UTF-8" on it."""
    has_decl, encoding = _xml_declaration_encoding(src)
    if has_decl and encoding is not None and encoding.lower() == "utf-8":
        return src, []
    if not has_decl:
        # preserve a leading BOM if one is present
        bom = "\ufeff" if src.startswith("\ufeff") else ""
        body = src[len(bom) :]
        new_src = f'{bom}<?xml version="1.0" encoding="UTF-8"?>\n{body}'
        return new_src, [(1, "E214", "inserted XML declaration")]
    match = XML_DECL_RE.match(src)
    version = XML_DECL_VERSION_RE.search(match.group(1))
    version_value = version.group(1) if version else "1.0"
    new_decl = f'<?xml version="{version_value}" encoding="UTF-8"?>'
    new_src = src[: match.start()] + new_decl + src[match.end() :]
    return new_src, [(1, "E214", 'set XML declaration encoding to "UTF-8"')]


def fix_trailing_whitespace(src):
    """W210: strip trailing spaces/tabs from every line."""
    new_src = TRAILING_WS_RE.sub("", src)
    if new_src == src:
        return src, []
    fixed = [
        (lineno, "W210", "stripped trailing whitespace")
        for lineno, line in enumerate(src.split("\n"), start=1)
        if line != line.rstrip(" \t")
    ]
    return new_src, fixed


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------


def check_filename_matches_title(path, src):
    """W217: the file's basename must match its first content object's Title.

    The Title is sanitized for filename-illegal characters the same way an
    author would when saving the file (/ \\ : * ? " < > | -> _) before it is
    compared against the basename (extension stripped). Only checked when
    --check-filename is passed.
    """
    match = TITLE_TAG_RE.search(src)
    if match is None:
        return []
    title = _strip_cdata(match.group(1)).strip()
    if title == "":
        return []
    expected = FILENAME_ILLEGAL_RE.sub("_", title)
    basename = os.path.basename(path)
    stem, _ext = os.path.splitext(basename)
    if stem == expected:
        return []
    return [
        (
            1,
            "W217",
            (
                f'filename "{basename}" does not match Title "{title}" (expected '
                f'stem "{expected}"); add `{FILENAME_MARKER}` if intentional'
            ),
        )
    ]


def check_file(
    path,
    disabled=frozenset(),
    strict=False,
    auto_fix=False,
    now=None,
    check_filename=False,
    severities=None,
):
    """Check one BES file; return (issues, fixed).

    Each of `issues` and `fixed` is a list of (lineno, code, message). A file is
    skipped (returns [], []) when it carries the file-level skip marker or looks
    like a mustache template. A file that will not parse as XML yields a single
    advisory W200 (bes-schema-validate owns file validity) and no other checks.

    When `auto_fix` is set, the fixable conventions are rewritten in place and
    reported under `fixed`; the CDATA wrap (W204) is applied only when `strict`
    is also set, and CRLF normalization (E208) is applied last so the written
    file is entirely CRLF. Read-only, a file that is not all-CRLF is an E208
    error. The file is read as raw bytes and normalized to LF in memory so the
    checks are line-ending agnostic. `check_filename` enables W217 (off by
    default, matching --check-filename). `severities`, if given, overrides
    W216's allowed SourceSeverity vocabulary (see --severity-values).
    """
    if not os.path.isfile(path):
        return [(1, "W200", "file not found; skipping")], []

    with open(path, "rb") as handle:
        raw = handle.read()
    # normalize to LF in memory so the checks/fixers are line-ending agnostic;
    # `raw` is kept to inspect (and, on auto-fix, rewrite) the real endings.
    src = (
        raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    )

    if SKIP_MARKER in src:
        return [], []
    if MUSTACHE_RE.search(src):
        return [], []

    try:
        root = ElementTree.fromstring(src)
    except ElementTree.ParseError as err:
        return [(1, "W200", f"not parseable BES XML ({err}); skipping")], []

    check_e208 = "E208" not in disabled
    crlf_ok = _is_all_crlf(raw)

    fixed = []
    if auto_fix:
        new_src, fixed = _autofix(src, root, disabled, strict, now)
        # file-level fixers run on the whole document (after the per-block ones):
        # strip trailing whitespace, then ensure the XML declaration.
        if "W210" not in disabled and TRAILING_WS_MARKER not in src:
            new_src, got = fix_trailing_whitespace(new_src)
            fixed += got
        if "E214" not in disabled and XML_DECL_MARKER not in src:
            new_src, got = fix_xml_declaration(new_src)
            fixed += got
        # CRLF normalization runs LAST: BES files must be entirely CRLF, so any
        # auto-fix leaves the whole file CRLF (rather than preserving endings).
        # If the CRLF rule is disabled, write whatever endings resulted (LF).
        if check_e208:
            final_bytes = _to_crlf(new_src).encode("utf-8")
            if not crlf_ok:
                fixed.append((1, "E208", "normalized line endings to CRLF"))
        else:
            final_bytes = new_src.encode("utf-8")
        if final_bytes != raw:
            with open(path, "wb") as handle:
                handle.write(final_bytes)
        src = new_src
        try:
            root = ElementTree.fromstring(src)
        except ElementTree.ParseError as err:
            return [(1, "W200", f"not parseable BES XML after fixes ({err})")], fixed

    issues = _run_checks(src, root, disabled, severities=severities)
    # file-level checks on the final src (after any fixes); in auto-fix mode
    # these come back clean unless the specific fix was disabled.
    if "E214" not in disabled and XML_DECL_MARKER not in src:
        issues += check_xml_declaration(src)
    if "W210" not in disabled and TRAILING_WS_MARKER not in src:
        issues += check_trailing_whitespace(src)
    if check_filename and "W217" not in disabled and FILENAME_MARKER not in src:
        issues += check_filename_matches_title(path, src)
    if not auto_fix and check_e208 and not crlf_ok:
        lone_lf = raw.count(b"\n") - raw.count(b"\r\n")
        lone_cr = raw.count(b"\r") - raw.count(b"\r\n")
        issues.append(
            (
                1,
                "E208",
                (
                    f"BES file must use CRLF line endings throughout (found {lone_lf} "
                    f"lone LF, {lone_cr} lone CR); enable --auto-fix to normalize"
                ),
            )
        )
    return sorted(issues), fixed


def is_bes_file(path):
    """True if `path` has a recognized BES extension."""
    return path.endswith(BES_EXTENSIONS)


def check_files(
    paths,
    disabled=frozenset(),
    strict=False,
    auto_fix=False,
    check_filename=False,
    severities=None,
):
    """Check several BES files; return a list of (path, issues, fixed) tuples.

    Non-BES paths are skipped. Disabled codes are filtered from the results.
    This is the programmatic entry point: it does no printing.
    """
    results = []
    for path in paths:
        if not is_bes_file(path):
            continue
        issues, fixed = check_file(
            path,
            disabled=disabled,
            strict=strict,
            auto_fix=auto_fix,
            check_filename=check_filename,
            severities=severities,
        )
        issues = [item for item in issues if item[1] not in disabled]
        fixed = [item for item in fixed if item[1] not in disabled]
        results.append((path, issues, fixed))
    return results


def discover_bes_files(root="."):
    """Return all BES files under `root`, pruning hidden and noise directories."""
    skip_dirs = {"__pycache__", "node_modules"}
    root = os.path.normpath(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d not in skip_dirs
        ]
        for name in filenames:
            if is_bes_file(name):
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
        help=(
            "treat warnings as failures (non-zero exit) and enable the CDATA "
            "auto-fix (W204); default: advisory"
        ),
    )
    parser.add_argument(
        "--errors-only",
        action="store_true",
        help=(
            "report only E-codes: warnings are left out of the output and cannot "
            "fail the run (even with --strict), but every check and W-code "
            "auto-fix still runs -- unlike --disable"
        ),
    )
    parser.add_argument(
        "--auto-fix",
        choices=["yes", "no"],
        default=None,
        help=(
            "rewrite fixable conventions in place (default: yes when files are "
            "given, no when auto-discovering)"
        ),
    )
    parser.add_argument(
        "--disable",
        default="",
        metavar="CODES",
        help="comma-separated check IDs to skip entirely, e.g. --disable W204",
    )
    parser.add_argument(
        "--check-filename",
        action="store_true",
        help=(
            "enable W217: a file's basename must match its first content "
            "object's Title, sanitized for filename-illegal characters "
            "(off by default)"
        ),
    )
    parser.add_argument(
        "--severity-values",
        default=None,
        metavar="VALUES",
        help=(
            "comma-separated SourceSeverity values W216 accepts (exact case), "
            "overriding the default vocabulary: "
            f"{','.join(sorted(CANONICAL_SEVERITIES))}"
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        help=(
            "BES files to check; if omitted, all *.bes files in the current "
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

    severities = None
    if args.severity_values is not None:
        severities = frozenset(
            value.strip() for value in args.severity_values.split(",") if value.strip()
        )

    # auto-fix defaults to yes for explicit files, no when auto-discovering; an
    # explicit --auto-fix always wins.
    discovering = not args.files
    if args.auto_fix is not None:
        auto_fix = args.auto_fix == "yes"
    else:
        auto_fix = not discovering
    paths = args.files if args.files else discover_bes_files(".")

    issue_count = 0
    warning_count = 0
    fix_count = 0
    for path, issues, fixed in check_files(
        paths,
        disabled=disabled,
        strict=args.strict,
        auto_fix=auto_fix,
        check_filename=args.check_filename,
        severities=severities,
    ):
        for lineno, check_id, message in fixed:
            fix_count += 1
            print(f"{path}:{lineno}: [{check_id}] auto-fixed: {message}")
        for lineno, check_id, message in issues:
            if check_id.startswith("W"):
                # --errors-only drops warnings from the report only; the checks
                # and their fixers already ran (see --disable for skipping them)
                if args.errors_only:
                    continue
                warning_count += 1
                print(f"{path}:{lineno}: [{check_id}] warning: {message}")
            else:
                issue_count += 1
                print(f"{path}:{lineno}: [{check_id}] {message}")

    if fix_count:
        print(f"\nauto-fixed {fix_count} issue(s); review and re-stage the changes.")
    if warning_count:
        print(f"{warning_count} BES-convention warning(s).")
    if issue_count:
        print(f"{issue_count} BES-convention issue(s).")
    # E-codes and any fix always fail; warnings fail only under --strict
    return 1 if (issue_count or fix_count or (warning_count and args.strict)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
