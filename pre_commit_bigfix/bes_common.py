"""Helpers shared by the BES hooks in this package.

Each of these was once copied into several hooks and kept identical by hand.
They live here so a fix to one is a fix to all: reading a file as LF text while
remembering its line endings, writing it back the same way, finding the BES
files under a folder when no paths are given, and printing the
`path:line: [CODE] message` report the hooks share.

SchemaGuard also lives here. It is what keeps an auto-fix from turning a
schema-valid file into one that fails BES.xsd validation.
"""

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


def _bundled_schemas(validate_bes_xml):
    """Return the schema files validate_bes_xml ships with, not cwd ones.

    Upstream's SCHEMA_FILES also holds any *.xsd in the current folder, which
    would let a repo-local Foo.xsd make <Foo> checkable, or a repo-local
    BES.xsd stand in for the real one.
    """
    bundled = os.path.join(
        os.path.dirname(os.path.realpath(validate_bes_xml.__file__)), "schemas"
    )
    return [
        path
        for path in validate_bes_xml.SCHEMA_FILES
        if os.path.dirname(os.path.realpath(path)) == bundled
    ]


def schema_errors(raw, path=None):
    """Validate BES XML bytes against the schema bes-schema-validate would pick.

    `path`, if given, is the file's name; validate_bes_xml uses it only for
    its extension (.ojo -> BESOJO.xsd, .BESDomain -> BESDomain.xsd). Returns a
    list of "Line N: message" strings, empty when valid. Returns None when no
    bundled schema applies, meaning validity is unknown. validate_bes_xml
    (and so lxml) is imported only here: importing it scans and compiles every
    schema, which only a fix that writes needs, and the stdlib-only
    bes-conventions-check must not need it at all.
    """
    import validate_bes_xml  # pylint: disable=import-outside-toplevel

    schemas = _bundled_schemas(validate_bes_xml)
    if not schemas:  # an empty list would make upstream fall back to the cwd
        return None
    result = validate_bes_xml.validate_bes(
        xml=raw, filename=path, schema_pathnames=schemas
    )
    if result:
        return []
    # upstream reports "no schema applies" as schema=None with line-less
    # errors; a syntax error also has schema=None, but carries line numbers.
    # Swap for `result.status == "no_schema"` once jgstew/validate_bes_xml#17
    # ships (and raise the validate_bes_xml floor to match).
    if result.schema is None and all(line is None for line, _msg in result.errors):
        return None
    return [f"Line {line}: {message}" for line, message in result.errors]


def schema_regression(original, new, path=None):
    """Return the schema errors an edit introduced, or [] if it introduced none.

    `original` and `new` are a file's bytes before and after an auto-fix. Only
    a valid-to-invalid change counts: a file that already failed validation
    is bes-schema-validate's to report, and blocking every fix to it would
    help nobody. An unknown schema (see schema_errors) also counts as none.
    """
    if new == original:
        return []
    errors = schema_errors(new, path)
    if not errors:
        return []
    return errors if schema_errors(original, path) == [] else []


class SchemaGuard:
    """Accept a file's auto-fix passes one at a time, keeping it BES.xsd-valid.

    Start it with the file's text, then hand each fix pass's result to
    apply(). A pass that would turn a schema-valid file invalid is held back:
    its fixes are dropped and one issue is recorded under `code` naming them.
    The passes before and after it still apply, so one bad fix does not cost
    the others. A file that already fails validation is never held back,
    since bes-schema-validate reports it regardless. Line endings do not
    affect validity, so the text is checked in whatever form it is given.

    Afterwards `src` is the accepted text, `fixed` the accepted fixes, and
    `refused` the issues to report.
    """

    def __init__(self, src, code, path=None, validate=True):
        self.src = src
        self.fixed = []
        self.refused = []
        self._code = code
        self._path = path
        self._validate = validate
        self._valid = None  # is the accepted text schema-valid? (checked lazily)

    def _errors(self, new_src):
        """Schema errors `new_src` would introduce over the accepted text."""
        if self._valid is None:
            self._valid = schema_errors(self.src.encode("utf-8"), self._path) == []
        if not self._valid:
            return []
        return schema_errors(new_src.encode("utf-8"), self._path) or []

    def apply(self, new_src, fixes):
        """Take one pass's rewritten text and its fixes; return True if kept."""
        if self._validate and new_src != self.src:
            errors = self._errors(new_src)
            if errors:
                codes = ", ".join(sorted({code for _line, code, _msg in fixes}))
                self.refused.append(
                    (
                        1,
                        self._code,
                        (
                            f"auto-fix ({codes or 'unreported'}) not written: it "
                            "would make the file fail BES.xsd validation "
                            f"({errors[0]}); fix by hand, or --disable "
                            f"{self._code} to write it anyway"
                        ),
                    )
                )
                return False
        self.src = new_src
        self.fixed += fixes
        return True
