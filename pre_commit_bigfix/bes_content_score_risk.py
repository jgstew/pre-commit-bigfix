#!/usr/bin/env python3
"""Score how risky a BES file's content is, to flag it for careful review.

This is a triage signal, not a verdict: each finding below adds points to the
file's risk score, and a file whose score reaches --fail-score (default 50,
the HIGH band) fails the hook so a person looks at it before it is trusted.
Content is never changed. Bands: LOW under 25, MEDIUM 25-49, HIGH 50 and up.

Signals (default points in brackets; --weight CODE=N changes one):

    W901  [20] script in a Description: <script>, javascript:, an on*= handler
    W902  [25] session relevance in a Description: <?relevance ...?> or an
          EvaluateRelevance( call
    W903  [15] both of the above in one Description
    W910  [25] an ActionScript `download` / `download now` -- not hashed; a
          later `continue if {sha1 of ...}` does not excuse it, use a prefetch
    W911  [25] `add nohash prefetch item`
    W912  [10] a download or prefetch URL over plain http:// or to a raw IP
    W913  [15] a download command in script content (curl, wget,
          Invoke-WebRequest, DownloadString, bitsadmin, ...)
    W920   [2] base64 of a real image of its declared data:image/ type
    W921  [20] base64 (80+ characters) anywhere else
    W922  [25] a decoded payload is an executable or a script
    W923  [20] a decode-and-run command: certutil -decode, base64 -d,
          FromBase64String, powershell -EncodedCommand
    W924  [15] other obfuscation: long \\x / \\u / %XX / hex runs that decode
          to ASCII, or eval( unescape( atob( Function( fromCharCode(
    W925  [15] a decoded payload is gzip, zlib or zip compressed
    W926  [30] base64 labelled data:image/ whose bytes are not that image
    W927  [10] a decoded payload itself holds findings: scores their points
          plus 10 per layer, and names the decode path (base64->gzip->text)
    W900       a MEDIUM score (summary line)
    W908       not parseable XML; skipped (bes-schema-validate owns validity)
    E900       the score is at or over --fail-score

Every encoded blob is decoded and inspected: base64 is tried as UTF-8 and as
UTF-16LE (PowerShell -EncodedCommand), compressed data is decompressed, and
decoded text is scanned again with the same signals, at most MAX_DEPTH layers
deep and MAX_DECODED bytes in all, so a decompression bomb cannot run away.
"""

import argparse
import base64
import binascii
import io
import re
import sys
import zipfile
import zlib
from typing import NamedTuple

from lxml import etree

from pre_commit_bigfix import bes_common
from pre_commit_bigfix.bes_actionscript_lint_schclass import _mask_heredocs

ACTIONSCRIPT_MIMETYPE = "application/x-Fixlet-Windows-Shell"

WEIGHTS = {
    "W901": 20,
    "W902": 25,
    "W903": 15,
    "W910": 25,
    "W911": 25,
    "W912": 10,
    "W913": 15,
    "W920": 2,
    "W921": 20,
    "W922": 25,
    "W923": 20,
    "W924": 15,
    "W925": 15,
    "W926": 30,
    "W927": 10,
}

MEDIUM = 25
HIGH = 50
MAX_DEPTH = 3
MAX_DECODED = 4 * 1024 * 1024  # bytes decoded per file, all layers together
MAX_INFLATE = 1024 * 1024  # bytes one decompression may produce

SCRIPT_RE = re.compile(r"<script\b|\bjavascript:|<[^>]*\son[a-z]+\s*=", re.IGNORECASE)
SESSION_RE = re.compile(r"<\?relevance\b|\bEvaluateRelevance\s*\(", re.IGNORECASE)
# case-sensitive: `function(` is in every script; `Function(` builds code
OBFUSCATION_API_RE = re.compile(
    r"\b(?:eval|unescape|atob|Function)\s*\(|\bfromCharCode\s*\("
)
DOWNLOAD_CMD_RE = re.compile(
    r"\b(?:curl|wget|iwr|bitsadmin)\b|Invoke-WebRequest|Invoke-RestMethod"
    r"|Start-BitsTransfer|DownloadString|DownloadFile|Net\.WebClient"
    r"|certutil\b[^\n]*-urlcache",
    re.IGNORECASE,
)
DECODE_CMD_RE = re.compile(
    r"certutil(?:\.exe)?\s+-decode|\bbase64\s+(?:-d|-D|--decode)\b"
    r"|FromBase64String|\bpowershell(?:\.exe)?\b[^\n]*\s-(?:e|ec|enc|encodedcommand)\s",
    re.IGNORECASE,
)
URL_RE = re.compile(r"\b(?:https?|ftp)://([^\s/\"'<>:]+)", re.IGNORECASE)
RAW_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
DOWNLOAD_LINE_RE = re.compile(r"^download(?:\s|$)", re.IGNORECASE)
NOHASH_RE = re.compile(r"^add\s+nohash\s+prefetch\s+item\b", re.IGNORECASE)
PREFETCH_RE = re.compile(r"^(?:prefetch|add\s+prefetch\s+item)\b", re.IGNORECASE)

# base64 wrapped across lines counts as one run; it must reach MIN_BASE64
BASE64_RE = re.compile(r"[A-Za-z0-9+/]{16,}(?:\s*[A-Za-z0-9+/]{16,})*={0,2}")
MIN_BASE64 = 80
IMAGE_PREFIX_RE = re.compile(r"data:image/([\w.+-]+);base64,\s*$", re.IGNORECASE)
HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")
# (regex, label, decoder) for the other encodings W924 finds
ENCODED_RUNS = (
    (
        re.compile(r"(?:\\x[0-9A-Fa-f]{2}){16,}"),
        "\\x escapes",
        lambda s: bytes.fromhex(s.replace("\\x", "")),
    ),
    (
        re.compile(r"(?:\\u[0-9A-Fa-f]{4}){8,}"),
        "\\u escapes",
        lambda s: "".join(chr(int(h, 16)) for h in s.split("\\u")[1:]).encode("utf-8"),
    ),
    (
        re.compile(r"(?:%[0-9A-Fa-f]{2}){8,}"),
        "%XX encoding",
        lambda s: bytes.fromhex(s.replace("%", "")),
    ),
    (
        re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}){40,}(?![0-9A-Fa-f])"),
        "hex",
        bytes.fromhex,
    ),
)

# what the bytes of each data:image/ type start with (svg is checked as text)
IMAGE_MAGIC = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "gif": (b"GIF87a", b"GIF89a"),
    "jpeg": (b"\xff\xd8\xff",),
    "jpg": (b"\xff\xd8\xff",),
    "x-icon": (b"\x00\x00\x01\x00",),
    "vnd.microsoft.icon": (b"\x00\x00\x01\x00",),
    "bmp": (b"BM",),
    "webp": (b"RIFF",),
}
EXECUTABLE_MAGIC = (
    b"MZ",
    b"\x7fELF",
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
)
SCRIPT_MARKER_RE = re.compile(
    r"^#!|<script\b|\bpowershell\b|\bcmd(?:\.exe)?\s+/c\b|/bin/(?:ba)?sh\b"
    r"|\b(?:wscript|cscript|mshta|rundll32|regsvr32)\b",
    re.IGNORECASE | re.MULTILINE,
)


class Finding(NamedTuple):
    line: int
    code: str
    points: int
    message: str


def band(score):
    """LOW, MEDIUM or HIGH for a risk score."""
    if score >= HIGH:
        return "HIGH"
    if score >= MEDIUM:
        return "MEDIUM"
    return "LOW"


class _Scanner:
    """Collects findings for one file, with its weights and decode budget."""

    def __init__(self, weights, disabled):
        self.weights = {**WEIGHTS, **(weights or {})}
        self.disabled = set(disabled or ())
        self.budget = MAX_DECODED

    def finding(self, line, code, message, points=None):
        """A Finding, or None for a disabled code."""
        if code in self.disabled:
            return None
        if points is None:
            points = self.weights[code]
        return Finding(line, code, points, message)

    # --- the parts of a BES file ------------------------------------------------

    def description(self, element):
        """W901-W903 and W924's API calls for one Description element."""
        # itertext gives CDATA and entity-escaped HTML decoded; a <?relevance?>
        # outside CDATA is a processing instruction, which itertext skips
        view = "".join(element.itertext()) + "".join(
            f"<?{pi.target} {pi.text or ''}?>"
            for pi in element.iter(etree.ProcessingInstruction)
        )
        line = element.sourceline or 1
        found = []
        script = SCRIPT_RE.search(view)
        session = SESSION_RE.search(view)
        if script:
            found.append(
                self.finding(line, "W901", f"script in a Description: {script[0]!r}")
            )
        if session:
            found.append(
                self.finding(
                    line,
                    "W902",
                    "session relevance in a Description runs as the console "
                    f"operator: {session[0]!r}",
                )
            )
        if script and session:
            found.append(
                self.finding(
                    line, "W903", "a Description script built from session relevance"
                )
            )
        api = OBFUSCATION_API_RE.search(view)
        if api:
            found.append(
                self.finding(
                    line, "W924", f"obfuscation call in a Description: {api[0]!r}"
                )
            )
        return found

    def actionscript(self, element):
        """W910-W913 and W923 for one ActionScript element."""
        body = (element.text or "").replace("\r\n", "\n").replace("\r", "\n")
        start = element.sourceline or 1
        lines = body.split("\n")
        found = []
        mimetype = element.get("MIMEType")
        if mimetype is None or mimetype == ACTIONSCRIPT_MIMETYPE:
            # commands only: createfile content is data, scanned below
            masked, _issues = _mask_heredocs(lines)
            for offset, text in enumerate(masked):
                found.extend(self._command(start + offset, text.strip()))
        for offset, text in enumerate(lines):
            stripped = text.strip()
            if not stripped or stripped.startswith("//"):
                continue
            found.extend(self._script_line(start + offset, stripped))
        return found

    def _command(self, line, text):
        """W910-W912 for one ActionScript command line."""
        if DOWNLOAD_LINE_RE.match(text):
            yield self.finding(
                line,
                "W910",
                "download with no hash check; use a prefetch with sha256 and size",
            )
        elif NOHASH_RE.match(text):
            yield self.finding(line, "W911", "nohash prefetch item: not hash-checked")
        elif not PREFETCH_RE.match(text):
            return
        for url in URL_RE.finditer(text):
            insecure = url[0].lower().startswith(("http:", "ftp:"))
            if insecure or RAW_IP_RE.match(url[1]):
                yield self.finding(
                    line,
                    "W912",
                    f"download URL over plain http or to a raw IP: {url[0]}",
                )

    def _script_line(self, line, text):
        """W913 and W923 for a line of script or file content."""
        download = DOWNLOAD_CMD_RE.search(text)
        if download:
            yield self.finding(line, "W913", f"download command: {download[0]!r}")
        decode = DECODE_CMD_RE.search(text)
        if decode:
            yield self.finding(line, "W923", f"decode-and-run command: {decode[0]!r}")

    # --- encoded content anywhere ---------------------------------------------------

    def encoded(self, src, line_of, depth):
        """W920-W927 for every encoded run in `src`; line_of(pos) -> line."""
        found = []
        for match in BASE64_RE.finditer(src):
            found.extend(self._base64(src, match, line_of(match.start()), depth))
        for regex, label, decoder in ENCODED_RUNS:
            for match in regex.finditer(src):
                if label == "hex" and re.search(
                    r"sha\w*\W{0,3}$",
                    src[max(0, match.start() - 12) : match.start()],
                    re.IGNORECASE,
                ):
                    continue  # a hash value, not a payload
                try:
                    data = decoder(match[0])
                except (ValueError, OverflowError):
                    continue
                if not data.isascii():
                    continue  # non-English text, not hidden ASCII
                line = line_of(match.start())
                found.append(
                    self.finding(line, "W924", f"{len(match[0])} characters of {label}")
                )
                found.extend(self._payload(data, [label], line, depth))
        return found

    def _base64(self, src, match, line, depth):
        run = re.sub(r"\s+", "", match[0])
        if len(run) < MIN_BASE64 or HEX_RE.match(run.rstrip("=")):
            return []
        # real base64 of 60+ bytes all but surely has a digit or + in it;
        # a long path or word run (letters and slashes) does not
        if not re.search(r"[0-9+]", run) or run.count("/") > len(run) // 10 + 2:
            return []
        # a URL path (a VirusTotal report's /file/<sha256>/analysis) is not a
        # payload: skip a run in the same token as a `scheme://`
        token = re.split(
            r"[\s\"'<>()]", src[max(0, match.start() - 2048) : match.start()]
        )
        if "://" in token[-1]:
            return []
        try:
            data = base64.b64decode(run + "=" * (-len(run) % 4), validate=True)
        except (binascii.Error, ValueError):
            return []
        image = IMAGE_PREFIX_RE.search(src[max(0, match.start() - 80) : match.start()])
        if image:
            kind = image[1].lower()
            if kind == "svg+xml":
                text = _as_text(data)
                if text is not None and "<svg" in text.lower():
                    return [
                        self.finding(line, "W920", "base64 SVG image"),
                        *self._text(text, ["base64", "svg"], line, depth),
                    ]
            elif data.startswith(IMAGE_MAGIC.get(kind, (b"\x00\x00no",))):
                return [self.finding(line, "W920", f"base64 {kind} image")]
            return [
                self.finding(
                    line,
                    "W926",
                    f"base64 labelled image/{kind} is not a {kind} image",
                ),
                *self._payload(data, ["base64"], line, depth),
            ]
        return [
            self.finding(line, "W921", f"{len(run)} characters of base64"),
            *self._payload(data, ["base64"], line, depth),
        ]

    def _payload(self, data, path, line, depth):
        """Inspect decoded bytes: W922, W925, and W927 for what they hold."""
        self.budget -= len(data)
        if self.budget < 0 or depth >= MAX_DEPTH:
            return []
        found = []
        if data.startswith(EXECUTABLE_MAGIC):
            found.append(
                self.finding(
                    line, "W922", f"decoded {'->'.join(path)} is an executable"
                )
            )
            return found
        inflated = _inflate(data)
        if inflated is not None:
            kind, data = inflated
            path = [*path, kind]
            self.budget -= len(data)
            found.append(
                self.finding(line, "W925", f"decoded {'->'.join(path)} is compressed")
            )
            if data.startswith(EXECUTABLE_MAGIC):
                found.append(
                    self.finding(
                        line, "W922", f"decoded {'->'.join(path)} is an executable"
                    )
                )
                return found
        text = _as_text(data)
        if text is None:
            return found
        marker = SCRIPT_MARKER_RE.search(text)
        if marker:
            found.append(
                self.finding(
                    line,
                    "W922",
                    f"decoded {'->'.join(path)} is a script: {marker[0]!r}",
                )
            )
        found.extend(self._text(text, path, line, depth))
        return found

    def _text(self, text, path, line, depth):
        """W927: the findings in decoded text, folded into one."""
        inner = [f for f in self._generic(text, depth + 1) if f]
        if not inner:
            return []
        bonus = self.finding(line, "W927", "")
        if bonus is None:
            return []
        summary = ", ".join(f"{f.code} {f.message}" for f in inner[:5])
        if len(inner) > 5:
            summary += f", and {len(inner) - 5} more"
        return [
            bonus._replace(
                points=sum(f.points for f in inner) + bonus.points,
                message=f"decoded {'->'.join([*path, 'text'])} holds: {summary}",
            )
        ]

    def _generic(self, text, depth):
        """Every signal that can apply to decoded text, all on the outer line."""
        found = []
        line = 1  # rewritten by the caller's line through W927
        script = SCRIPT_RE.search(text)
        if script:
            found.append(self.finding(line, "W901", f"script {script[0]!r}"))
        api = OBFUSCATION_API_RE.search(text)
        if api:
            found.append(self.finding(line, "W924", f"obfuscation call {api[0]!r}"))
        for text_line in text.splitlines():
            stripped = text_line.strip()
            if stripped and not stripped.startswith("//"):
                found.extend(self._command(line, stripped))
                found.extend(self._script_line(line, stripped))
        found.extend(self.encoded(text, lambda pos: line, depth))
        return found


def _inflate(data):
    """(kind, decompressed bytes) for gzip, zlib or zip data, else None."""
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
                if not names:
                    return None
                with archive.open(names[0]) as member:
                    return "zip", member.read(MAX_INFLATE)
        except (zipfile.BadZipFile, OSError, RuntimeError, ValueError):
            return None
    for kind, magic, wbits in (
        ("gzip", (b"\x1f\x8b",), 31),
        ("zlib", (b"\x78\x01", b"\x78\x5e", b"\x78\x9c", b"\x78\xda"), 15),
    ):
        if data.startswith(magic):
            try:
                return kind, zlib.decompressobj(wbits).decompress(data, MAX_INFLATE)
            except zlib.error:
                return None
    return None


def _as_text(data):
    """Decoded bytes as text (UTF-16LE when every other byte is NUL), or None."""
    if (
        len(data) >= 4
        and len(data) % 2 == 0
        and data[1::2].count(0) >= len(data) // 2 * 0.9
    ):
        candidates = ("utf-16-le",)
    else:
        candidates = ("utf-8", "latin-1")
    for encoding in candidates:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        printable = sum(1 for c in text if c.isprintable() or c in "\r\n\t")
        if text and printable >= 0.9 * len(text):
            return text
    return None


def score_text(src, weights=None, disabled=()):
    """Return (findings, score) for a BES document's text.

    Raises etree.XMLSyntaxError if it does not parse.
    """
    root = etree.fromstring(src.encode("utf-8"))
    scanner = _Scanner(weights, disabled)
    found = []
    for element in root.iter("Description"):
        found.extend(scanner.description(element))
    for element in root.iter("ActionScript"):
        found.extend(scanner.actionscript(element))
    found.extend(scanner.encoded(src, lambda pos: bes_common.lineno(src, pos), 0))
    found = sorted(f for f in found if f is not None)
    return found, sum(f.points for f in found)


def check_file(path, fail_score, weights=None, disabled=()):
    """Return (issues, score) for one file, issues as (line, code, message)."""
    _raw, src, _crlf = bes_common.read_source(path)
    try:
        found, total = score_text(src, weights, disabled)
    except etree.XMLSyntaxError as err:
        return [(1, "W908", f"not parseable XML ({err}); skipping")], 0
    issues = [(f.line, f.code, f"(+{f.points}) {f.message}") for f in found]
    if total >= fail_score:
        issues.insert(
            0,
            (
                1,
                "E900",
                (
                    f"risk score {total} ({band(total)}) is at or over --fail-score "
                    f"{fail_score}: review this content carefully before trusting it"
                ),
            ),
        )
    elif total >= MEDIUM:
        issues.insert(0, (1, "W900", f"risk score {total} ({band(total)})"))
    return issues, total


def _weight(value):
    """Argparse type for CODE=N."""
    code, sep, points = value.partition("=")
    code = code.strip().upper()
    if not sep or code not in WEIGHTS:
        raise argparse.ArgumentTypeError(
            f"expected CODE=N with a W9xx code, not {value!r}"
        )
    try:
        return code, int(points)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{points!r} is not a whole number") from None


def main(argv=None):
    """Execution starts here; returns 1 when any file reaches --fail-score."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("files", nargs="*", help="BES files (default: all under .)")
    parser.add_argument(
        "--fail-score",
        type=int,
        default=HIGH,
        help=f"fail a file whose risk score reaches this (default {HIGH}, HIGH)",
    )
    parser.add_argument(
        "--weight",
        type=_weight,
        action="append",
        default=[],
        metavar="CODE=N",
        help="change a signal's points, e.g. --weight W921=10 (repeatable)",
    )
    parser.add_argument(
        "--disable",
        default="",
        metavar="CODES",
        help="comma-separated signal codes to skip, e.g. --disable W920",
    )
    args = parser.parse_args(argv)
    weights = dict(args.weight)
    disabled = {c.strip().upper() for c in args.disable.split(",") if c.strip()}
    files = args.files or bes_common.discover_bes_files()
    results = []
    for path in files:
        try:
            issues, _total = check_file(path, args.fail_score, weights, disabled)
        except OSError as err:
            issues = [(1, "W908", f"cannot read ({err}); skipping")]
        results.append((path, issues, []))
    errors, _warnings, _fixes = bes_common.report(results)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
