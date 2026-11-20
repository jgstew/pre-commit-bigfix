#!/usr/bin/env python3
"""Pre-commit hook: lint the bodies of BigFix Inventory signature files.

`bes-schema-validate` already checks `Signatures/*.xml` against
SoftwareIdentityCatalog.xsd, but that schema types <ExtendedSignature> as any
content, so nothing looks inside the CDATA body, where the detection logic is.
This hook does, and adds the cross-file rules no XSD can express (repo-wide
uniqueIds, the header comment against the <Software> attributes).

Checks:
    E100  a CDATA body longer than --max-signature-chars (default 3829, the
          most BigFix Inventory imports). Python len() of the text between
          `<![CDATA[` and `]]>`: characters, whitespace included
    E101  a CDATA body that is not well-formed XML when wrapped as
          <r>BODY</r> (single-instance bodies have several top-level elements)
    E102  a Signature uniqueId used twice in one file, or also used by another
          signature file in the repo
    E103  `$(NAME)` or withVariable="NAME" with no Variable/Iterator
          name="NAME" in the same body
    E104  an <Instance> with no element children, which the scanner rejects
    E105  <RpmProductInfo field="version">, which returns version.release
          joined with a dot; use field="displayVersion" and crop at `-`
    E106  the file is not well-formed XML, so nothing in it was linted. Off by
          default -- bes-schema-validate owns file validity -- and switched
          back on with --enable E106
    W100  a body longer than 90% of the limit
    W101  a Software uniqueId duplicated, by the same rules as E102. A warning
          until Software IDs are confirmed to be global like Signature IDs
    W102  ReadFile in a body with no FileInfoCompare field="size" guard
    W103  ReadFile plus a StringCrop endString="&#10;", with no &#13; anywhere
          in the body: on a CRLF file the CR is kept and Compare fails
    W104  a DETAILED_VER variable with no
          <Condition withVariable="DETAILED_VER"><Action do="SKIP" onValue=""/>
    W105  a body that does not export all of INSTALL_PATH, DETAILED_VER and
          IS_INSTALLED. Off by default (older and basic-style signatures
          legitimately do not); --enable W105
    W106  an RpmProductList filter that does not end in `*`
    W107  an MsiProductList filter that is not `*`, does not start with `*`,
          and is not a {GUID}: filter matches the product code, not the name
    W108  XmlValue, which fails on plists with an external DTD
    W109  a version 1 (time-based) uniqueId that is new: in no signature file
          of the repo at HEAD (so a renamed file's IDs are not new). Use
          uuid.uuid4(). Skipped outside git
    W110  the leading comment's ProductName / Release differ from
          <Software name> / version
    W111  a Signature `modified` earlier than its `created`

E-codes fail the hook; warnings fail only under --strict. Findings are
reported at the <Signature> start tag (W110 at the <Software> tag), since a
body is usually one long line.

E102 and W101 compare every passed file against every signature file in the
repo holding each passed file (`git ls-files` there; outside git, a walk of
the folder holding its Signatures/ folder), matched by
the hook's own `files:` pattern, but report only on the files passed in. So an
old duplicate between two unchanged files surfaces only with --all-files or
when one of them is edited. A file keeping its own IDs across edits is never a
collision: only the same ID in two paths, or twice in one file.

A file that is not a <SoftwareIdentityCatalog> is skipped. A file opts out of
every check here with `pre-commit-skip: bes-signature-lint` anywhere in it.
Nothing is auto-fixed.

Usage:
    bes-signature-lint [--strict] [--disable E103] [--enable W105]
                       [--max-signature-chars N] [FILES...]

Exit status: the number of E-code findings (plus warnings under --strict),
capped at 255; 0 when clean.
"""

import argparse
import datetime
import os
import re
import sys

from lxml import etree

from pre_commit_bigfix import bes_common

__all__ = ["main"]

# the most characters BigFix Inventory imports in one signature body
DEFAULT_MAX_SIGNATURE_CHARS = 3829
# W100 fires above this fraction of the limit
NEAR_LIMIT = 0.9

KNOWN_CODES = frozenset(
    ["E100", "E101", "E102", "E103", "E104", "E105", "E106"]
    + [f"W{n}" for n in range(100, 112)]
)
DEFAULT_DISABLED = frozenset({"E106", "W105"})

SKIP_MARKER = "pre-commit-skip: bes-signature-lint"
# the same pattern as this hook's `files:` in .pre-commit-hooks.yaml
SIGNATURE_FILE_RE = re.compile(r"(^|/)Signatures/[^/]+\.xml$")

# comments and CDATA are blanked (offsets kept) before tags are searched, so a
# `<Signature` inside either is not taken for a tag
_MASK_RE = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>", re.DOTALL)
_SIGNATURE_RE = re.compile(
    r"<Signature\b[^>]*(?<!/)>(.*?)</Signature\s*>|<Signature\b[^>]*/>", re.DOTALL
)
_SOFTWARE_RE = re.compile(r"<Software\b")
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_VAR_USE_RE = re.compile(r"\$\(([^)]*)\)")
_GUID_RE = re.compile(r"^\{[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")
# the raw text of the body is searched for these, since the CDATA keeps
# character references literally
_LF_CROP_RE = re.compile(
    r"<StringCrop\b[^>]*\bendString\s*=\s*([\"'])&#(?:10|x0*a);\1", re.IGNORECASE
)
_CR_RE = re.compile(r"&#(?:13|x0*d);", re.IGNORECASE)
# a version 1 uniqueId anywhere in a file, for W109's lookup at HEAD
_V1_ID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-1[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}"
_EXPORTED = ("INSTALL_PATH", "DETAILED_VER", "IS_INSTALLED")

_SAFE_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False
)


def _split_codes(value):
    return {code.strip().upper() for code in value.split(",") if code.strip()}


def _local(element):
    """The tag of `element` without a namespace, or None for a comment/PI."""
    if not isinstance(element.tag, str):
        return None
    return etree.QName(element).localname


def _elements(root, name):
    return [el for el in root.iter() if _local(el) == name]


def _parse(path):
    """Return the parsed root of `path`, or None when it is not well-formed."""
    try:
        return etree.parse(path, _SAFE_PARSER).getroot()
    except (etree.XMLSyntaxError, OSError):
        return None


def _catalog_ids(root):
    """[(kind, uniqueId, software name)] of every Software and Signature in `root`."""
    ids = []
    for software in _elements(root, "Software"):
        name = software.get("name", "")
        if software.get("uniqueId"):
            ids.append(("Software", software.get("uniqueId"), name))
        for signature in _elements(software, "Signature"):
            if signature.get("uniqueId"):
                ids.append(("Signature", signature.get("uniqueId"), name))
    return ids


def _is_signature_file(path):
    return bool(SIGNATURE_FILE_RE.search(os.path.normpath(path).replace(os.sep, "/")))


def _repo_root(path, cache):
    """The top folder of the git repo holding `path`, or None outside git.

    `cache` maps folders already asked about, so files sharing a folder cost
    one git call.
    """
    folder = os.path.dirname(os.path.abspath(path))
    if folder not in cache:
        out = bes_common.run_git(folder, "rev-parse", "--show-toplevel")
        cache[folder] = os.fsdecode(out).strip() if out else None
    return cache[folder]


def _signature_files_under(root, in_git):
    """Every signature file git tracks under `root` (or, outside git, that a
    walk of it finds), as paths relative to the current folder.
    """
    if in_git:
        out = bes_common.run_git(root, "ls-files", "-z")
        names = os.fsdecode(out or b"").split("\0")
        paths = [os.path.join(root, name) for name in names if name]
    else:
        paths = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            paths.extend(os.path.join(dirpath, name) for name in filenames)
    return sorted(os.path.relpath(path) for path in paths if _is_signature_file(path))


def _same_file_key(path):
    """A key equal for two spellings of one file (relative, absolute, case)."""
    return os.path.normcase(os.path.realpath(path))


def _index_roots(paths, root_cache):
    """{(folder, in_git)} to index for `paths`: each file's git repo, or
    outside git the folder that holds its Signatures/ folder.
    """
    roots = set()
    for path in paths:
        top = _repo_root(path, root_cache)
        if top is not None:
            roots.add((top, True))
        else:
            signatures = os.path.dirname(os.path.abspath(path))
            roots.add((os.path.dirname(signatures), False))
    return roots


def _build_index(passed_roots, root_cache):
    """{(kind, id): [(path, software name)]} over the passed files' repos.

    A passed file is read from disk with its unstaged changes, like the rest;
    `passed_roots` saves parsing those twice.
    """
    others = []
    for folder, in_git in sorted(_index_roots(passed_roots, root_cache)):
        others.extend(_signature_files_under(folder, in_git))
    index = {}
    seen = set()
    for path in list(passed_roots) + others:
        if _same_file_key(path) in seen:
            continue
        seen.add(_same_file_key(path))
        root = passed_roots.get(path)
        if root is None:
            root = _parse(path)
        if root is None or _local(root) != "SoftwareIdentityCatalog":
            continue
        for kind, unique_id, name in _catalog_ids(root):
            index.setdefault((kind, unique_id), []).append((path, name))
    return index


def _head_v1_ids(top):
    """Every version 1 uniqueId in any signature file at HEAD in repo `top`.

    One git grep over the whole tree, so a renamed or moved file's IDs are
    still found, and the cost does not grow with the files passed in. Empty
    when there is no commit yet.
    """
    out = bes_common.run_git(
        top,
        "grep",
        "-h",
        "-o",
        "-I",
        "-E",
        _V1_ID_RE,
        "HEAD",
        "--",
        ":(glob)**/Signatures/*.xml",
    )
    return set(os.fsdecode(out or b"").split())


def _is_v1(unique_id):
    """Whether a schema-valid uniqueId is a version 1 (time-based) UUID."""
    return len(unique_id) == 36 and unique_id[14] == "1"


def _parse_datetime(value):
    try:
        return datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _header_value(header, key):
    match = re.search(r"^\s*" + key + r':\s*"([^"]*)"', header, re.MULTILINE)
    return match.group(1) if match else None


def _lint_body(body, max_chars):
    """[(code, message)] for one CDATA body."""
    found = []
    if len(body) > max_chars:
        found.append(
            ("E100", f"body is {len(body)} characters, over the {max_chars} limit")
        )
    elif len(body) > int(max_chars * NEAR_LIMIT):
        found.append(
            (
                "W100",
                (
                    f"body is {len(body)} characters, within 10% of the "
                    f"{max_chars} limit"
                ),
            )
        )
    try:
        root = etree.fromstring("<r>" + body + "</r>", _SAFE_PARSER)
    except etree.XMLSyntaxError as exc:
        found.append(("E101", f"body is not well-formed XML: {exc}"))
        return found

    defined = {
        el.get("name")
        for el in root.iter()
        if _local(el) in ("Variable", "Iterator") and el.get("name")
    }
    used = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for attr, value in el.attrib.items():
            used.extend(_VAR_USE_RE.findall(value))
            if attr == "withVariable":
                used.append(value)
    for name in dict.fromkeys(used):
        if name not in defined:
            found.append(
                (
                    "E103",
                    f"variable {name!r} is used but no Variable/Iterator defines it",
                )
            )

    for instance in _elements(root, "Instance"):
        if not any(isinstance(child.tag, str) for child in instance):
            found.append(("E104", "<Instance> has no children; the scanner rejects it"))
    for info in _elements(root, "RpmProductInfo"):
        if info.get("field") == "version":
            found.append(
                (
                    "E105",
                    (
                        'RpmProductInfo field="version" returns version.release '
                        'joined with a dot; use field="displayVersion" and crop at "-"'
                    ),
                )
            )

    if _elements(root, "ReadFile"):
        if not any(
            el.get("field") == "size" for el in _elements(root, "FileInfoCompare")
        ):
            found.append(
                ("W102", 'ReadFile with no FileInfoCompare field="size" guard')
            )
        if _LF_CROP_RE.search(body) and not _CR_RE.search(body):
            found.append(
                (
                    "W103",
                    (
                        'ReadFile cropped at endString="&#10;" with no &#13; crop; '
                        "a CRLF file keeps the CR and Compare fails"
                    ),
                )
            )

    if any(el.get("name") == "DETAILED_VER" for el in _elements(root, "Variable")):
        skips_empty = any(
            cond.get("withVariable") == "DETAILED_VER"
            and any(
                _local(action) == "Action"
                and action.get("do") == "SKIP"
                and action.get("onValue") == ""
                for action in cond
            )
            for cond in _elements(root, "Condition")
        )
        if not skips_empty:
            found.append(
                (
                    "W104",
                    (
                        'DETAILED_VER with no <Condition withVariable="DETAILED_VER">'
                        '<Action do="SKIP" onValue=""/>'
                    ),
                )
            )

    exported = {
        el.get("name")
        for el in root.iter()
        if _local(el) in ("Variable", "Iterator") and el.get("export") == "true"
    }
    missing = [name for name in _EXPORTED if name not in exported]
    if missing:
        found.append(("W105", "does not export " + ", ".join(missing)))

    for rpm in _elements(root, "RpmProductList"):
        value = rpm.get("filter")
        if value is not None and not value.endswith("*"):
            found.append(
                (
                    "W106",
                    (
                        f"RpmProductList filter={value!r} has no trailing *; it "
                        "matches the whole name-version-release.arch"
                    ),
                )
            )
    for msi in _elements(root, "MsiProductList"):
        value = msi.get("filter")
        if value is not None and not (value.startswith("*") or _GUID_RE.match(value)):
            found.append(
                (
                    "W107",
                    (
                        f"MsiProductList filter={value!r} matches the product code, "
                        'not the name; use "*" or a {GUID}'
                    ),
                )
            )
    if _elements(root, "XmlValue"):
        found.append(
            (
                "W108",
                "XmlValue fails on plists with an external DTD; use ReadFile + StringCrop",
            )
        )
    return found


def _v1_message(kind, unique_id):
    return (
        f"new {kind} uniqueId {unique_id} is a version 1 (time-based) UUID; "
        "prefer uuid.uuid4()"
    )


def _describe(others):
    return ", ".join(f'{path} (Software "{name}")' for path, name in others)


def lint_file(path, src, root, index, max_chars, head_ids):
    """[(lineno, code, message)] for one parsed signature file."""
    issues = []
    masked = _MASK_RE.sub(lambda m: " " * len(m.group(0)), src)
    tags = list(_SIGNATURE_RE.finditer(masked))
    signatures = _elements(root, "Signature")
    software_tags = list(_SOFTWARE_RE.finditer(masked))
    software_elements = _elements(root, "Software")
    if len(tags) != len(signatures) or len(software_tags) != len(software_elements):
        # the text search and the parser disagree; fall back to the parser's
        # lines rather than pair the wrong tags
        sig_lines = [el.sourceline for el in signatures]
        sw_lines = [el.sourceline for el in software_elements]
        sig_spans = [None] * len(signatures)
    else:
        sig_lines = [bes_common.lineno(src, m.start()) for m in tags]
        sw_lines = [bes_common.lineno(src, m.start()) for m in software_tags]
        sig_spans = [m.span() for m in tags]
    sw_line_of = {id(el): line for el, line in zip(software_elements, sw_lines)}

    def collisions(kind, unique_id):
        uses = index.get((kind, unique_id), [])
        here = _same_file_key(path)
        others = [use for use in uses if _same_file_key(use[0]) != here]
        twice_here = sum(1 for use in uses if _same_file_key(use[0]) == here) > 1
        return others, twice_here

    for software, line in zip(software_elements, sw_lines):
        unique_id = software.get("uniqueId")
        if unique_id:
            others, twice = collisions("Software", unique_id)
            if twice:
                issues.append(
                    (
                        line,
                        "W101",
                        f"Software uniqueId {unique_id} is used more than once in this file",
                    )
                )
            if others:
                issues.append(
                    (
                        line,
                        "W101",
                        f"Software uniqueId {unique_id} also used by {_describe(others)}",
                    )
                )
            if head_ids is not None and _is_v1(unique_id) and unique_id not in head_ids:
                issues.append((line, "W109", _v1_message("Software", unique_id)))

    # the header is the first comment before the root element
    header = None
    node = root.getprevious()
    while node is not None:
        if isinstance(node, etree._Comment):
            header = node.text or ""
        node = node.getprevious()
    if header is not None and software_elements:
        software = software_elements[0]
        line = sw_line_of[id(software)]
        for key, attr in (("ProductName", "name"), ("Release", "version")):
            value = _header_value(header, key)
            if value is not None and value != software.get(attr, ""):
                issues.append(
                    (
                        line,
                        "W110",
                        (
                            f'header {key}: "{value}" differs from <Software '
                            f'{attr}="{software.get(attr, "")}">'
                        ),
                    )
                )

    for number, (signature, line, span) in enumerate(
        zip(signatures, sig_lines, sig_spans), 1
    ):
        unique_id = signature.get("uniqueId", "")
        label = f"signature #{number} ({unique_id})"
        if unique_id:
            others, twice = collisions("Signature", unique_id)
            if twice:
                issues.append(
                    (
                        line,
                        "E102",
                        f"uniqueId {unique_id} is used more than once in this file",
                    )
                )
            if others:
                issues.append(
                    (
                        line,
                        "E102",
                        f"uniqueId {unique_id} also used by {_describe(others)}",
                    )
                )
        if head_ids is not None and _is_v1(unique_id) and unique_id not in head_ids:
            issues.append((line, "W109", _v1_message("Signature", unique_id)))
        created = _parse_datetime(signature.get("created"))
        modified = _parse_datetime(signature.get("modified"))
        if created and modified:
            try:
                earlier = modified < created
            except TypeError:  # one has a time zone and the other not
                earlier = False
            if earlier:
                issues.append(
                    (line, "W111", f"{label} modified is earlier than created")
                )

        if span is not None:
            bodies = _CDATA_RE.findall(src[span[0] : span[1]])
        else:
            bodies = [el.text or "" for el in _elements(signature, "ExtendedSignature")]
        for body in bodies:
            for code, message in _lint_body(body, max_chars):
                issues.append((line, code, f"{label}: {message}"))
    return issues


def main(argv=None):
    """Lint the signature files named in `argv`; return the capped error count."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--strict", action="store_true", help="fail on warnings as well as errors"
    )
    parser.add_argument(
        "--disable",
        default="",
        metavar="CODES",
        help="comma-separated check IDs to skip entirely, e.g. --disable E103",
    )
    parser.add_argument(
        "--enable",
        default="",
        metavar="CODES",
        help=(
            "comma-separated check IDs to switch back on, undoing one this "
            "hook disables by default, e.g. --enable W105"
        ),
    )
    parser.add_argument(
        "--max-signature-chars",
        type=int,
        default=DEFAULT_MAX_SIGNATURE_CHARS,
        metavar="N",
        help=(
            "the longest CDATA body allowed (E100); W100 fires above 90%% of "
            f"it (default {DEFAULT_MAX_SIGNATURE_CHARS}, BigFix Inventory's "
            "import limit)"
        ),
    )
    parser.add_argument("files", nargs="*", help="signature files to check")
    args = parser.parse_args(argv)

    disabled = _split_codes(args.disable)
    enabled = _split_codes(args.enable)
    unknown = (disabled | enabled) - KNOWN_CODES
    if unknown:
        print(
            "warning: ignoring unknown --disable/--enable code(s): {}".format(
                ", ".join(sorted(unknown))
            )
        )
    disabled -= unknown
    enabled -= unknown
    disabled |= DEFAULT_DISABLED - enabled

    # one entry per file however it was spelled, keeping the first spelling
    files = {}
    for path in args.files:
        files.setdefault(_same_file_key(path), os.path.normpath(path))
    parsed = {}
    results = []
    for path in files.values():
        try:
            _raw, src, _crlf = bes_common.read_source(path)
        except OSError as exc:
            print(f"{path}: skipped, could not be read: {exc}")
            continue
        if SKIP_MARKER in src:
            continue
        root = _parse(path)
        if root is None:
            if "E106" in disabled:
                print(
                    f"{path}: skipped, not well-formed XML (bes-schema-validate reports it)"
                )
            else:
                results.append(
                    (path, [(1, "E106", "not well-formed XML; nothing was linted")], [])
                )
            continue
        if _local(root) != "SoftwareIdentityCatalog":
            continue
        parsed[path] = (src, root)

    root_cache = {}
    # only E102 and W101 read the index; skip reading the repo without them
    if {"E102", "W101"} <= disabled:
        index = {}
    else:
        index = _build_index(
            {path: root for path, (_src, root) in parsed.items()}, root_cache
        )
    head_ids_by_repo = {}
    for path, (src, root) in parsed.items():
        # W109's IDs at HEAD, read once per repo; None outside git
        top = None if "W109" in disabled else _repo_root(path, root_cache)
        if top is not None and top not in head_ids_by_repo:
            head_ids_by_repo[top] = _head_v1_ids(top)
        head_ids = head_ids_by_repo.get(top)
        issues = lint_file(path, src, root, index, args.max_signature_chars, head_ids)
        issues = [issue for issue in issues if issue[1] not in disabled]
        results.append((path, issues, []))

    error_count, warning_count, _fixes = bes_common.report(results)
    if warning_count:
        print(f"{warning_count} warning(s).")
    if error_count:
        print(f"{error_count} issue(s).")
    failures = error_count + (warning_count if args.strict else 0)
    return min(failures, 255)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
