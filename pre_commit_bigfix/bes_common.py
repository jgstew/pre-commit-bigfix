"""Helpers shared by the BES hooks in this package.

Each of these was once copied into several hooks and kept identical by hand.
They live here so a fix to one is a fix to all: reading a file as LF text while
remembering its line endings, writing it back the same way, finding the BES
files under a folder when no paths are given, and printing the
`path:line: [CODE] message` report the hooks share, and checking that an
auto-fix has not made a schema-valid file fail BES.xsd validation.
"""

import io
import os
import re

# an unrendered mustache template ({{ placeholder }}) is not real content yet.
# Only an identifier-like placeholder counts: `{{` is also the ActionScript
# escape for a literal `{`, so heredoc payloads (YARA, JSON, C#) contain `{{`
# around arbitrary content and must not be mistaken for a template.
# A GUID-shaped "placeholder" is not one: `msiexec /x{{{GUID}}` escapes a
# literal `{` in front of an MSI product code.
MUSTACHE_RE = re.compile(
    r"\{\{(?!\s*[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\s*\}\})"
    r"\s*[#/^!&>]?\s*[\w.-]+\s*\}\}"
)

# directories never searched by discover_bes_files (hidden ones are skipped too)
DISCOVERY_SKIP_DIRS = frozenset({"__pycache__", "node_modules"})


def read_source(path):
    """Read `path`; return (raw bytes, text with LF line endings, was_crlf).

    The text is decoded as UTF-8 (undecodable bytes replaced) and every CRLF or
    lone CR is turned into LF, so checks need not care about line endings.
    `was_crlf` records whether the file had any CRLF, for encode() to restore.
    """
    with open(path, "rb") as handle:
        raw = handle.read()
    src = (
        raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    )
    return raw, src, b"\r\n" in raw


def encode(src, was_crlf):
    """Turn checked text back into file bytes, restoring CRLF if that is the file."""
    return (src.replace("\n", "\r\n") if was_crlf else src).encode("utf-8")


def lineno(src, pos):
    """Return the 1-based line number of character offset `pos` in `src`."""
    return src.count("\n", 0, pos) + 1


def discover_bes_files(root=".", extensions=(".bes",)):
    """Return the files under `root` ending in `extensions`, sorted.

    Hidden directories and DISCOVERY_SKIP_DIRS are pruned from the walk.
    """
    root = os.path.normpath(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".") and d not in DISCOVERY_SKIP_DIRS
        ]
        for name in filenames:
            if name.endswith(extensions):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def report(results, errors_only=False):
    """Print every fix and issue in `results`; return (issues, warnings, fixes).

    `results` is a list of (path, issues, fixed) tuples, each of `issues` and
    `fixed` a list of (lineno, code, message). A code starting with W is a
    warning; any other is an error. With `errors_only`, warnings are neither
    printed nor counted.
    """
    issue_count = 0
    warning_count = 0
    fix_count = 0
    for path, issues, fixed in results:
        for line, check_id, message in fixed:
            fix_count += 1
            print(f"{path}:{line}: [{check_id}] auto-fixed: {message}")
        for line, check_id, message in issues:
            if check_id.startswith("W"):
                if errors_only:
                    continue
                warning_count += 1
                print(f"{path}:{line}: [{check_id}] warning: {message}")
            else:
                issue_count += 1
                print(f"{path}:{line}: [{check_id}] {message}")
    return issue_count, warning_count, fix_count


# compiled schemas, keyed by inferred schema name (a plain dict rather than
# functools.cache, which needs Python 3.9+)
_SCHEMAS = {}


def _schema(name):
    """Return the compiled XMLSchema validate_bes_xml uses for `name`, or None.

    validate_bes_xml is imported here rather than at module level: importing it
    finds and parses every bundled .xsd, which only a fix that writes needs.
    """
    # pylint: disable=import-outside-toplevel
    import validate_bes_xml
    from lxml import etree

    if name not in _SCHEMAS:
        paths = [path for path in sorted(validate_bes_xml.SCHEMA_FILES) if name in path]
        _SCHEMAS[name] = etree.XMLSchema(etree.parse(paths[0])) if paths else None
    return _SCHEMAS[name]


def schema_errors(raw):
    """Validate BES XML bytes against BES.xsd the way bes-schema-validate does.

    Returns a list of "Line N: message" strings (empty when valid), or None
    when no bundled schema applies to the document, so validity is unknown.
    The schema is picked as validate_bes_xml.validate_xml picks it: the root's
    `*.xsd` attribute, else the root tag's name. lxml and validate_bes_xml are
    imported only here, so a hook that never writes (and the stdlib-only
    bes-conventions-check) need not have them.
    """
    # pylint: disable=import-outside-toplevel
    import validate_bes_xml
    from lxml import etree

    try:
        document = etree.parse(io.BytesIO(raw))
    except etree.XMLSyntaxError as err:
        return [f"Line {err.lineno}: {err.msg}"]
    schema = _schema(validate_bes_xml.infer_xml_schema(document))
    if schema is None:
        return None
    if schema.validate(document):
        return []
    return [f"Line {error.line}: {error.message}" for error in schema.error_log]


def schema_regression(original, new):
    """Return the schema errors an edit introduced, or [] if it introduced none.

    `original` and `new` are a file's bytes before and after an auto-fix. Only
    a valid-to-invalid change counts: a file that already failed validation
    is bes-schema-validate's to report, and blocking every fix to it would
    help nobody. An unknown schema (see schema_errors) also counts as none.
    """
    if new == original:
        return []
    errors = schema_errors(new)
    if not errors:
        return []
    return errors if schema_errors(original) == [] else []
