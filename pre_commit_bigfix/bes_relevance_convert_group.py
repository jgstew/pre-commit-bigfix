#!/usr/bin/env python3
"""Convert a BES file's console-exported <GroupRelevance> into plain <Relevance>.

The BigFix console can save a Fixlet/Task/Baseline/Analysis/FixletStream's
applicability as a computer-group style <GroupRelevance>: a list of search
components, each carrying its own already-built <Relevance>, joined by
intersection (all must hold) or union (any may hold). BES.xsd allows either
that or a run of <Relevance> elements in the same place, and plain relevance is
what reads and diffs well in source control, so this hook rewrites

    <GroupRelevance JoinByIntersection="true">   one <Relevance> per component
                                                 (sibling Relevance must all hold)
    <GroupRelevance JoinByIntersection="false">  one <Relevance>(a) OR (b)</Relevance>,
                                                 or just <Relevance>a</Relevance>
                                                 when there is one component

A GroupRelevance is found with the XPath /BES/*/GroupRelevance, and parsed with
lxml; the rewrite itself is a text splice, so everything outside the replaced
block -- formatting, comments, CDATA, line endings -- is left byte-identical.
Each component's <Relevance> is copied verbatim (CDATA stays CDATA, escaped
stays escaped) except when union-joining several, where the decoded texts are
joined and written once: as CDATA when any input was CDATA or the text holds
`<`, `>` or `&`, entity-escaped when it contains `]]>`, and plain otherwise.

Checks (E-codes fail the hook; W-codes are advisory unless --strict):

    E700  a GroupRelevance was converted (or, under --check, needs converting)
    E701  a GroupRelevance holds a SearchComponentGroupReference (or another
          component with no Relevance); converting group membership is not
          supported yet, so that whole GroupRelevance is left unchanged
    E702  JoinByIntersection is not an xs:boolean, or is missing while there
          are several components (with one, AND and OR are the same, so it
          converts); left unchanged
    E703  a GroupRelevance has no components, or one with an empty Relevance;
          left unchanged
    E704  the converted file would no longer pass BES.xsd schema validation;
          nothing is written
    W700  skipped: file not found, not parseable XML, or a GroupRelevance that
          could not be located for the splice

The hook converts in place by default and exits 1 when it changed anything,
so pre-commit shows the rewrite for review. --check is a dry run: it only
reports. When no files are given, every *.bes under the current folder is
checked (never rewritten). A file carrying the text

    pre-commit-skip: bes-relevance-convert-group

anywhere is skipped, as is an unrendered mustache template.
"""

import argparse
import os
import re
import sys

from lxml import etree

if __package__ in (None, ""):  # run directly as a script, not as a module
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pre_commit_bigfix import bes_common
from pre_commit_bigfix.bes_common import MUSTACHE_RE, encode, lineno, read_source

SKIP_MARKER = "pre-commit-skip: bes-relevance-convert-group"
BES_EXTENSIONS = (".bes",)
KNOWN_CODES = frozenset({"E700", "E701", "E702", "E703", "E704", "W700"})

# where BES.xsd allows a GroupRelevance: directly in a content object
GROUP_RELEVANCE_XPATH = "/BES/*/GroupRelevance"
# search components whose <Relevance> child is the component's whole test
RELEVANCE_COMPONENTS = frozenset(
    {"SearchComponentRelevance", "SearchComponentPropertyReference"}
)

# comments and CDATA are blanked out (same length) before the regexes below
# run, so tag-like text inside them cannot be mistaken for markup
OPAQUE_RE = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>", re.DOTALL)
GROUP_RELEVANCE_RE = re.compile(
    r"<GroupRelevance\b[^>]*?(?:/>|>.*?</GroupRelevance>)", re.DOTALL
)
RELEVANCE_RE = re.compile(r"<Relevance\b[^>]*>(.*?)</Relevance>", re.DOTALL)
CDATA_START = "<![CDATA["
XS_BOOLEAN = {"true": True, "1": True, "false": False, "0": False}


def _mask_opaque(src):
    """Return `src` with comment and CDATA text blanked, offsets unchanged."""
    return OPAQUE_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), src)


def _text(element):
    """The element's own text as the evaluator sees it (CDATA unwrapped)."""
    return "".join(element.xpath("text()"))


def _escape(text):
    """Entity-escape `text` for an XML element body."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _component_relevance(component):
    """Return the relevance a search component stands for, or None.

    None means the component has no relevance of its own to copy: a
    SearchComponentGroupReference names a computer group, and turning
    membership into relevance needs a template this hook does not have yet.
    """
    if component.tag not in RELEVANCE_COMPONENTS:
        return None
    relevance = component.find("Relevance")
    return "" if relevance is None else _text(relevance)


def _components(group):
    """The search-component elements of `group` (comments left out)."""
    return [child for child in group if isinstance(child.tag, str)]


def _intersection(group):
    """Return True/False for how `group` joins its components, or None.

    None means it cannot be told. BES.xsd makes JoinByIntersection optional
    and documents no default, so a missing attribute is only safe with a
    single component, where AND and OR mean the same thing.
    """
    join = group.get("JoinByIntersection")
    if join is None:
        return True if len(_components(group)) == 1 else None
    return XS_BOOLEAN.get(join.strip())


def _refusal(group):
    """Return (code, message) if `group` cannot be converted, else None."""
    components = _components(group)
    for component in components:
        if _component_relevance(component) is None:
            if component.tag == "SearchComponentGroupReference":
                what = (
                    f'a SearchComponentGroupReference (GroupName "'
                    f'{component.get("GroupName", "")}")'
                )
            else:
                what = f"a <{component.tag}> component"
            return (
                "E701",
                (
                    f"GroupRelevance holds {what}; converting group membership is "
                    "not supported yet, so it was left unchanged"
                ),
            )
    # before the join check: with nothing to join, how they join is moot
    if not components:
        return "E703", "GroupRelevance has no search components; left unchanged"
    if _intersection(group) is None:
        found = group.get("JoinByIntersection")
        detail = (
            f"missing and it has {len(components)} components"
            if found is None
            else f'"{found}"'
        )
        return (
            "E702",
            (
                f"GroupRelevance JoinByIntersection is {detail}, so how they join "
                'is unknown; add JoinByIntersection="true" (all must hold) or '
                'JoinByIntersection="false" (any may hold). Left unchanged'
            ),
        )
    for number, component in enumerate(components, start=1):
        if not _component_relevance(component).strip():
            return (
                "E703",
                (
                    f"GroupRelevance component {number} (<{component.tag}>) has an "
                    "empty Relevance; left unchanged"
                ),
            )
    return None


def _union_body(statements, any_cdata):
    """The body of one <Relevance> OR-joining the decoded `statements`."""
    joined = " OR ".join(f"({statement.strip()})" for statement in statements)
    if "]]>" in joined:
        return _escape(joined)  # cannot sit inside a single CDATA section
    if any_cdata or any(char in joined for char in "<>&"):
        return f"{CDATA_START}{joined}]]>"
    return joined


def _replacement(src, span, raw_inners, statements, intersection):
    """Return the text that replaces the GroupRelevance at `span`."""
    if intersection or len(statements) == 1:
        bodies = raw_inners
    else:
        any_cdata = any(raw.strip().startswith(CDATA_START) for raw in raw_inners)
        bodies = [_union_body(statements, any_cdata)]
    line_start = src.rfind("\n", 0, span[0]) + 1
    indent = src[line_start : span[0]]
    separator = "\n" + indent if not indent.strip() else ""
    return separator.join(f"<Relevance>{body}</Relevance>" for body in bodies)


def _describe(statements, intersection, join):
    """E700's account of what a GroupRelevance became; `join` is the attribute."""
    count = len(statements)
    if intersection:
        result = f"{count} <Relevance> element(s)"
    elif count == 1:
        result = "one <Relevance>"
    else:
        result = "one OR-joined <Relevance>"
    join = "missing" if join is None else join.strip()
    return (
        f"GroupRelevance (JoinByIntersection {join}, {count} component(s)) -> {result}"
    )


def convert_group_relevance(src):
    """Convert every convertible GroupRelevance in BES text `src`.

    Returns (new_src, converted, issues): `converted` lists an E700 per
    GroupRelevance rewritten, `issues` the E701-E703 refusals and any W700.
    Each entry is (lineno, code, message). Pure: no file is touched.
    """
    try:
        root = etree.fromstring(src.encode("utf-8"))
    except etree.XMLSyntaxError as err:
        return src, [], [(1, "W700", f"not parseable BES XML ({err}); skipping")]

    groups = root.xpath(GROUP_RELEVANCE_XPATH)
    # no tag anywhere: nothing to convert and no misplaced one to warn about
    if "<GroupRelevance" not in src:
        return src, [], []

    masked = _mask_opaque(src)
    spans = [match.span() for match in GROUP_RELEVANCE_RE.finditer(masked)]
    if len(spans) != len(groups):
        return (
            src,
            [],
            [
                (
                    1,
                    "W700",
                    (
                        f"found {len(spans)} <GroupRelevance> tag(s) but "
                        f"{len(groups)} at {GROUP_RELEVANCE_XPATH}; skipping"
                    ),
                )
            ],
        )

    converted, issues, edits = [], [], []
    for group, span in zip(groups, spans):
        line = lineno(src, span[0])
        refusal = _refusal(group)
        if refusal:
            issues.append((line, *refusal))
            continue
        statements = [_component_relevance(c) for c in _components(group)]
        raw_inners = [
            src[m.start(1) + span[0] : m.end(1) + span[0]]
            for m in RELEVANCE_RE.finditer(masked[span[0] : span[1]])
        ]
        if len(raw_inners) != len(statements):
            issues.append(
                (
                    line,
                    "W700",
                    "could not locate each component's <Relevance>; skipping",
                )
            )
            continue
        intersection = _intersection(group)
        edits.append(
            (span, _replacement(src, span, raw_inners, statements, intersection))
        )
        converted.append(
            (
                line,
                "E700",
                _describe(statements, intersection, group.get("JoinByIntersection")),
            )
        )

    for (start, end), text in reversed(edits):
        src = src[:start] + text + src[end:]
    return src, converted, issues


def check_file(path, disabled=frozenset(), check=False):
    """Check (and unless `check`, convert) one file; return (issues, fixed).

    Each is a list of (lineno, code, message). Under `check`, a convertible
    GroupRelevance is an E700 issue and nothing is written; otherwise it is
    rewritten in place (line endings preserved) and reported under `fixed`,
    unless the result would break BES.xsd validity (E704). Codes in
    `disabled` are dropped; disabling E700 also stops the conversion.
    """
    if not os.path.isfile(path):
        return [(1, "W700", "file not found; skipping")], []

    _raw, src, was_crlf = read_source(path)
    if SKIP_MARKER in src or MUSTACHE_RE.search(src):
        return [], []

    new_src, converted, issues = convert_group_relevance(src)
    fixed = []
    if "E700" in disabled:
        converted = []
    elif check:
        issues += [
            (line, code, f"{message}; run without --check to convert")
            for line, code, message in converted
        ]
    elif converted:
        guard = bes_common.SchemaGuard(
            src, "E704", path, validate="E704" not in disabled
        )
        if guard.apply(new_src, converted):
            with open(path, "wb") as handle:
                handle.write(encode(new_src, was_crlf))
            fixed = converted
        issues += guard.refused

    issues = [issue for issue in issues if issue[1] not in disabled]
    return sorted(issues), fixed


def check_files(paths, disabled=frozenset(), check=False):
    """Check several files; return a list of (path, issues, fixed) tuples.

    This is the programmatic entry point: it does no printing.
    """
    return [(path, *check_file(path, disabled=disabled, check=check)) for path in paths]


def main(argv=None):
    """Execution starts here.

    argv defaults to None so this works both as a console_scripts entry point
    (pre-commit calls it with no arguments; argparse then reads sys.argv) and
    when called directly as `main(sys.argv[1:])`.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="dry run: report what would be converted, write nothing",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings (W700) as failures; default: advisory",
    )
    parser.add_argument(
        "--disable",
        default="",
        metavar="CODES",
        help="comma-separated check IDs to skip entirely, e.g. --disable E701",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help=(
            "BES files to convert; if omitted, all *.bes files in the current "
            "folder and below are checked (never rewritten)"
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

    # like the sibling hooks, auto-discovery never rewrites a whole tree
    check = args.check or not args.files
    paths = (
        args.files if args.files else bes_common.discover_bes_files(".", BES_EXTENSIONS)
    )

    issue_count, warning_count, fix_count = bes_common.report(
        check_files(paths, disabled=disabled, check=check)
    )

    if fix_count:
        print(
            f"\nconverted {fix_count} GroupRelevance(s); review and re-stage the changes."
        )
    if warning_count:
        print(f"{warning_count} GroupRelevance warning(s).")
    if issue_count:
        print(f"{issue_count} GroupRelevance issue(s).")
    # E-codes and any conversion always fail; warnings fail only under --strict
    return 1 if (issue_count or fix_count or (warning_count and args.strict)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
