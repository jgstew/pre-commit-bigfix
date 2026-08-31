#!/usr/bin/env python3
"""Pre-commit hook: lint the relevance inside BES files.

Every other hook in this repo treats relevance as opaque -- `{...}` is a lexer
state mechanically identical to a string literal, and the most any check proves
about a condition is that it starts with a brace. This hook is where that stops:
it hands each relevance statement to `bigfix-relevance-analyzer`, which parses
it, binds `it`, resolves every inspector against the dumps, type-checks the
result, and scores what it costs to evaluate.

Every relevance site the analyzer's extractor recognizes is checked -- <Relevance>
bodies, <SuccessCriteria Option="CustomRelevance"> bodies, Analysis <Property>
bodies, and the `{...}` substitutions inside <ActionScript> -- so a defect in a
substitution is reported at the line it lives on, not at the top of the file.

Checks:
    E600  the statement could not be parsed
    E601  the statement contains text that could not be lexed
    E602  `it` is used where there is no context to bind it to
    E603  the type checker reported a problem beyond an unbound `it`
    E604  the complexity score is above the ceiling (raise with --max-score)
    E605  the evaluation cost is above the ceiling (raise with
          --max-evaluation-cost)
    E606  a directory tree was deeper than the walk's limit, so it was not
          fully scanned. Only reachable when auto-discovering -- pre-commit
          always passes filenames
    W600  a name no inspector dump defines. A warning rather than an error
          because a repo running a newer client than the analyzer's snapshot
          legitimately uses names it has never heard of
    W601  a property written singular over an object that may be plural.
          Disabled by default in .pre-commit-hooks.yaml: it fires ~6 times per
          file across real content, which drowns everything else. Enable it
          deliberately with --enable W601

E-codes fail the hook; warnings fail only under --strict.

Unparsable XML is skipped, not reported -- bes-schema-validate owns file
validity, and this hook must not duplicate its findings. That does mean a
truncated file passes here: a clean run says the relevance the extractor could
see is sound, not that the file parses.

A file opts out of every check here with `pre-commit-skip: bes-relevance-lint`
anywhere in it, the same marker the sibling hooks honor. There is no per-rule
marker: --disable takes the code repo-wide, and a single file that legitimately
needs relevance this complex is what --max-score is for.

There is no auto-fix. Nothing this hook reports has a mechanical rewrite --
every one of them needs a human to decide what the relevance was meant to say.

Usage:
    bes-relevance-lint [--strict] [--disable E604] [--enable W601] [FILES...]

Exit status:
    0  no E-code findings (and, without --strict, no warnings either), or the
       interpreter is older than 3.11, where the analyzer cannot be installed
       and the hook skips with a notice rather than failing a build that has
       no way to go green
    1  an E-code fired, a warning fired under --strict, or the analyzer is
       missing on a 3.11+ interpreter, where it should have been installed
"""

import argparse
import sys

try:
    from bigfix_relevance_analyzer import (
        LintConfig,
        Severity,
        lint_directory,
        lint_paths,
    )

    IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - exercised only on an old Python
    LintConfig = lint_directory = lint_paths = Severity = None
    IMPORT_ERROR = exc

__all__ = ["main"]

# Every rule the analyzer can report, mapped to this repo's code vocabulary.
# Two spellings exist because a repo configures hooks by E-code (--disable E604,
# same as every sibling hook) while the analyzer names its rules in prose; the
# analyzer's own name is printed in the message tail so either one greps to the
# same line.
#
# tests/test_bes_relevance_lint.py fails if a key of the analyzer's RULES is
# missing here -- that is what turns "the library added a rule" from a silent
# dropped finding into a red build.
CODES = {
    "parse-error": "E600",
    "error-token": "E601",
    "unbound-it": "E602",
    "type-error": "E603",
    "complexity": "E604",
    "evaluation-cost": "E605",
    "max-depth-exceeded": "E606",
    "file-error": "E607",
    "unknown-inspector": "W600",
    "non-unique-risk": "W601",
    "plural-preferred": "W602",
}

KNOWN_CODES = frozenset(CODES.values())

# The reverse direction, for --disable/--enable: a repo names an E-code, the
# analyzer's LintConfig wants its own.
ANALYZER_CODES = {code: name for name, code in CODES.items()}


MIN_ANALYZER_PYTHON = (3, 11)


def _analyzer_unavailable():
    """Explain the missing analyzer and return the exit status to use.

    The two cases are not the same failure. Below 3.11 the dependency cannot
    be installed at all -- setup.cfg holds it back with an environment marker
    on purpose, because this package still supports 3.8 -- so nothing the repo
    writes in its config makes the hook run, and failing would leave it a
    permanently red build with no fix available. There the hook skips: it
    prints why and exits 0. On 3.11+ the analyzer is a hard dependency, so a
    missing one is a broken install and stays a failure.
    """
    running = f"{sys.version_info[0]}.{sys.version_info[1]}"
    if sys.version_info < MIN_ANALYZER_PYTHON:
        print(
            "bes-relevance-lint: skipped. It requires bigfix-relevance-analyzer, "
            f"which needs Python 3.11 or newer; this interpreter is {running}. "
            "To actually run this hook, point pre-commit at a 3.11+ interpreter "
            "with `default_language_version` in your .pre-commit-config.yaml. "
            f"({IMPORT_ERROR})"
        )
        return 0
    print(
        "bes-relevance-lint requires bigfix-relevance-analyzer, which is not "
        f"importable on this Python {running} interpreter even though it is new "
        "enough for it. Reinstall this package's dependencies (pip install "
        "--upgrade pre-commit-bigfix), or drop this hook from your config. "
        f"({IMPORT_ERROR})"
    )
    return 1


def _split_codes(raw):
    """Parse a comma-separated --disable/--enable value into a set of E-codes."""
    return {code.strip().upper() for code in raw.split(",") if code.strip()}


def _severities(disabled, enabled):
    """Per-code overrides for LintConfig, in the analyzer's own vocabulary."""
    severities = {}
    for code in disabled:
        severities[ANALYZER_CODES[code]] = Severity.IGNORE
    for code in enabled:
        # Restore the analyzer's own default rather than forcing a severity:
        # --enable exists to undo a default --disable from the hook
        # declaration, not to promote a warning into an error. --strict is
        # what does that, for every warning at once.
        severities.pop(ANALYZER_CODES[code], None)
    return severities


SKIP_MARKER = "pre-commit-skip: bes-relevance-lint"


def _opted_out(path):
    """Whether this file carries the marker that skips this hook entirely.

    Read as bytes and matched against bytes: this runs before the analyzer
    touches the file, so it must not care whether the file decodes cleanly.
    An unreadable file is not opted out -- it simply yields no findings once
    the extractor reaches it.
    """
    try:
        with open(path, "rb") as handle:
            return SKIP_MARKER.encode("utf-8") in handle.read()
    except OSError:
        return False


def _report(findings):
    """Print each finding in this repo's format.

    Returns (errors, warnings).
    """
    errors = warnings = 0
    for finding in findings:
        code = CODES[finding.code]
        where = f"{finding.path}:{finding.line}"
        label = "warning: " if finding.severity is Severity.WARNING else ""
        print(f"{where}: [{code}] {label}{finding.message} ({finding.code})")
        if finding.severity is Severity.WARNING:
            warnings += 1
        else:
            errors += 1
    return errors, warnings


def main(argv=None):
    """Execution starts here.

    argv defaults to None so this works both as a console_scripts entry point
    (pre-commit calls it with no arguments; argparse then reads sys.argv) and
    when called directly as `main(sys.argv[1:])`.
    """
    if IMPORT_ERROR is not None:
        return _analyzer_unavailable()

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
        help="comma-separated check IDs to skip entirely, e.g. --disable E604",
    )
    parser.add_argument(
        "--enable",
        default="",
        metavar="CODES",
        help=(
            "comma-separated check IDs to switch back on, undoing a --disable "
            "this hook declares by default, e.g. --enable W601"
        ),
    )
    parser.add_argument(
        "--max-score",
        type=float,
        default=None,
        help=(
            "raise E604's complexity ceiling above the analyzer's default; "
            "content that legitimately needs to be this complex should raise "
            "this rather than disable the check"
        ),
    )
    parser.add_argument(
        "--max-evaluation-cost",
        type=float,
        default=None,
        help="raise E605's evaluation-cost ceiling above the analyzer's default",
    )
    parser.add_argument(
        "--dialect",
        choices=["client", "session"],
        default=None,
        help="force the dialect instead of trusting what extraction says",
    )
    parser.add_argument(
        "--platform",
        default=None,
        help="narrow client inspector lookups to one platform, e.g. windows",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=6,
        help=(
            "how many directory levels to walk when auto-discovering "
            "(no effect when files are given, which is always the case under "
            "pre-commit)"
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        help=(
            "files to check; anything the analyzer's extractor does not "
            "recognize yields nothing. If omitted, the current folder and "
            "below is walked"
        ),
    )
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

    config_kwargs = {"severities": _severities(disabled, enabled)}
    # The analyzer's ceilings are on by default and these only raise them, so a
    # None here means "keep the built-in default", not "no limit".
    if args.max_score is not None:
        config_kwargs["max_score"] = args.max_score
    if args.max_evaluation_cost is not None:
        config_kwargs["max_evaluation_cost"] = args.max_evaluation_cost
    if args.platform is not None:
        config_kwargs["platform"] = args.platform
    if args.dialect is not None:
        from bigfix_relevance_analyzer.dialect import Dialect

        config_kwargs["dialect"] = Dialect(args.dialect)

    config = LintConfig(**config_kwargs)

    if args.files:
        findings = lint_paths(
            [path for path in args.files if not _opted_out(path)], config
        )
    else:
        # Filter after the walk rather than before it: the analyzer owns
        # discovery, and re-walking here to drop opted-out files first would
        # mean two definitions of what counts as a file to check.
        findings = [
            finding
            for finding in lint_directory(".", config, max_depth=args.max_depth)
            if not _opted_out(finding.path)
        ]

    error_count, warning_count = _report(findings)

    if warning_count:
        print(f"{warning_count} warning(s).")
    if error_count:
        print(f"{error_count} issue(s).")
    # E-codes always fail; warnings fail only under --strict
    return 1 if (error_count or (warning_count and args.strict)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
