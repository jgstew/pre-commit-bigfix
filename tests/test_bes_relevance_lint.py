#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_relevance_lint.py.

These exercise the mapping from bigfix-relevance-analyzer's rule names to this
repo's E600-E606/W600-W601 vocabulary, one fixture per code, the report format,
--disable/--enable, the --strict boundary, the `pre-commit-skip` marker, the
skips this hook inherits from the extractor (unparsable XML, unrecognized
suffixes), and main()'s exit codes.

The completeness test is the important one: it fails when the analyzer grows a
rule this hook does not map, which would otherwise drop that rule's findings on
the floor without a word.
"""

import sys

import pytest

from pre_commit_bigfix import bes_relevance_lint as linter

pytest.importorskip(
    "bigfix_relevance_analyzer",
    reason="bes-relevance-lint's analyzer needs Python 3.11+",
)

# Long enough to clear the analyzer's complexity ceiling; the shape is
# irrelevant, only that there is a lot of it.
TOO_COMPLEX = " and ".join('exists file "x{}"'.format(i) for i in range(120))

# Repeated whose-filters over a folder tree: cheap to write, expensive to run,
# which is exactly what the evaluation-cost rule is watching for.
TOO_COSTLY = " and ".join(
    'exists (files whose (size of it > {}) of folders of folder "/tmp")'.format(i)
    for i in range(8)
)


def bes(relevance, marker=None):
    """Build a single-Task BES document around one <Relevance> body."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            '<BES xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:noNamespaceSchemaLocation="BES.xsd">'
        ),
    ]
    if marker:
        lines.append("<!-- {} -->".format(marker))
    lines += [
        "<Task>",
        "<Title>Example</Title>",
        "<Relevance>{}</Relevance>".format(relevance),
        "</Task>",
        "</BES>",
    ]
    return "\n".join(lines)


def write(tmp_path, content, name="x.bes"):
    """Write `content` to tmp_path/name; return the path as a string."""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def run(tmp_path, relevance, *args, **kwargs):
    """Lint one relevance body; return (exit status, printed lines)."""
    capsys = kwargs.pop("capsys")
    path = write(tmp_path, bes(relevance, marker=kwargs.pop("marker", None)))
    status = linter.main(list(args) + [path])
    out = capsys.readouterr().out.splitlines()
    return status, out


def codes_in(lines):
    """The hook codes reported, in order."""
    found = []
    for line in lines:
        for code in linter.KNOWN_CODES:
            if "[{}]".format(code) in line:
                found.append(code)
    return found


def test_every_analyzer_rule_is_mapped():
    """A rule the analyzer reports and this hook does not know is a dropped
    finding: _report would raise on the lookup, so this fails loudly here.

    first, with the name of whatever was added.
    """
    from bigfix_relevance_analyzer.lint import RULES

    assert set(RULES) == set(linter.CODES)


def test_codes_are_unique():
    assert len(linter.KNOWN_CODES) == len(linter.CODES)


@pytest.mark.parametrize(
    ("relevance", "code"),
    [
        pytest.param("exists (", "E600", id="parse-error"),
        pytest.param('exists file "unterminated', "E601", id="error-token"),
        pytest.param("it", "E602", id="unbound-it"),
        pytest.param('if true then "a" else 1', "E603", id="type-error"),
        pytest.param(TOO_COMPLEX, "E604", id="complexity"),
        pytest.param(TOO_COSTLY, "E605", id="evaluation-cost"),
        pytest.param("exists bogusinspectorname", "W600", id="unknown-inspector"),
        pytest.param('name of files "x"', "W601", id="non-unique-risk"),
    ],
)
def test_each_code_fires(tmp_path, capsys, relevance, code):
    _, out = run(tmp_path, relevance, capsys=capsys)
    assert code in codes_in(out)


def test_clean_relevance_says_nothing(tmp_path, capsys):
    status, out = run(tmp_path, 'exists file "x"', capsys=capsys)
    assert status == 0
    assert out == []


def test_report_carries_both_spellings(tmp_path, capsys):
    """The E-code is what a repo configures; the analyzer's own name is what
    its docs and --list-rules use.

    Both are on the line so either greps.
    """
    _, out = run(tmp_path, 'if true then "a" else 1', capsys=capsys)
    assert "[E603]" in out[0]
    assert "(type-error)" in out[0]
    assert ".bes:5:" in out[0]  # the <Relevance> line, not the top of the file


def test_warnings_are_labelled_and_advisory(tmp_path, capsys):
    status, out = run(tmp_path, "exists bogusinspectorname", capsys=capsys)
    assert "warning: " in out[0]
    assert status == 0


def test_strict_fails_on_a_warning(tmp_path, capsys):
    status, _ = run(tmp_path, "exists bogusinspectorname", "--strict", capsys=capsys)
    assert status == 1


def test_an_error_fails_without_strict(tmp_path, capsys):
    status, _ = run(tmp_path, "it", capsys=capsys)
    assert status == 1


def test_disable_silences_a_code(tmp_path, capsys):
    status, out = run(tmp_path, "it", "--disable", "E602", capsys=capsys)
    assert codes_in(out) == []
    assert status == 0


def test_enable_undoes_a_declared_disable(tmp_path, capsys):
    """The hook declaration ships `--disable W601`; a repo that wants the rule
    appends `--enable W601` rather than having to restate the whole list.
    """
    _, out = run(
        tmp_path,
        'name of files "x"',
        "--disable",
        "W601",
        "--enable",
        "W601",
        capsys=capsys,
    )
    assert codes_in(out) == ["W601"]


def test_unknown_disable_codes_warn_and_are_ignored(tmp_path, capsys):
    status, out = run(tmp_path, "it", "--disable", "E999,E602", capsys=capsys)
    assert "E999" in out[0]
    assert codes_in(out) == []
    assert status == 0


def test_max_score_raises_the_complexity_ceiling(tmp_path, capsys):
    status, out = run(tmp_path, TOO_COMPLEX, "--max-score", "5000", capsys=capsys)
    assert "E604" not in codes_in(out)
    assert status == 0


def test_unparsable_xml_is_skipped(tmp_path, capsys):
    """Bes-schema-validate owns file validity.

    A clean run here says the
    relevance that could be extracted is sound, not that the file parses.
    """
    path = write(tmp_path, "<BES><Task><Relevance>it</Relevance></Task>")
    status = linter.main([path])
    assert capsys.readouterr().out == ""
    assert status == 0


def test_an_unrecognized_suffix_yields_nothing(tmp_path, capsys):
    path = write(tmp_path, bes("it"), name="x.txt")
    status = linter.main([path])
    assert capsys.readouterr().out == ""
    assert status == 0


def test_a_missing_file_is_not_an_error(tmp_path, capsys):
    status = linter.main([str(tmp_path / "nope.bes")])
    assert capsys.readouterr().out == ""
    assert status == 0


def test_the_skip_marker_opts_a_file_out(tmp_path, capsys):
    status, out = run(
        tmp_path, "it", capsys=capsys, marker="pre-commit-skip: bes-relevance-lint"
    )
    assert out == []
    assert status == 0


def test_a_substitution_is_reported_at_its_own_line(tmp_path, capsys):
    """An ActionScript `{...}` is a relevance site like any other, and its
    line number is the line it lives on.
    """
    document = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            "<BES>",
            "<Task>",
            "<Title>Example</Title>",
            "<ActionScript>",
            "waithidden {it}",
            "</ActionScript>",
            "</Task>",
            "</BES>",
        ]
    )
    path = write(tmp_path, document)
    linter.main([path])
    out = capsys.readouterr().out.splitlines()
    assert codes_in(out) == ["E602"]
    assert ".bes:6:" in out[0]


def test_the_skip_marker_opts_a_file_out_when_discovering(
    tmp_path, monkeypatch, capsys
):
    """The marker holds on the auto-discovery path too.

    pre-commit always passes filenames, but the sibling hooks all auto-discover
    when run with none and honor the marker either way. The unmarked file
    carries the same defect on purpose: it is what proves the walk ran at all,
    so an empty result cannot pass this test by accident.
    """
    write(tmp_path, bes("it", marker=linter.SKIP_MARKER), name="skipme.bes")
    write(tmp_path, bes("it"), name="checkme.bes")
    monkeypatch.chdir(tmp_path)

    status = linter.main([])
    out = capsys.readouterr().out

    assert "checkme.bes" in out
    assert "skipme.bes" not in out
    assert status == 1


def test_the_import_guard_does_not_recommend_a_per_hook_language_version(
    monkeypatch, capsys
):
    """On an old interpreter the hook must say so and give advice that matches
    the hook declaration.

    `language_version` names an *exact* executable, so pinning 3.11 on the hook
    breaks every machine that has only 3.12 or newer -- which is why
    .pre-commit-hooks.yaml declares no `language_version` and the README says
    not to add one. The guard must not send the reader the other way. Every
    mention here has to be the `default_language_version` form.
    """
    monkeypatch.setattr(linter, "IMPORT_ERROR", ImportError("no analyzer here"))
    monkeypatch.setattr(sys, "version_info", (3, 8, 18, "final", 0))

    status = linter.main([])
    out = capsys.readouterr().out

    assert status == 0
    assert "3.11" in out
    assert out.count("language_version") == out.count("default_language_version")


def test_an_interpreter_too_old_for_the_analyzer_skips_instead_of_failing(
    monkeypatch, capsys
):
    """<3.11 is an environment fact, not a defect in the content.

    setup.cfg's environment marker keeps the analyzer off those interpreters
    on purpose, so a repo whose pre-commit runs on 3.8 cannot install it from
    any config it writes. Failing there is an unfixable red build (which is
    exactly what `pre-commit try-repo` on the 3.8 leg of test_build.yaml hit),
    so the hook skips with a notice.
    """
    monkeypatch.setattr(linter, "IMPORT_ERROR", ImportError("no analyzer here"))
    monkeypatch.setattr(sys, "version_info", (3, 8, 18, "final", 0))

    assert linter.main([]) == 0
    assert "skipped" in capsys.readouterr().out


def test_a_missing_analyzer_on_a_new_enough_interpreter_still_fails(
    monkeypatch, capsys
):
    """On 3.11+ the analyzer is a hard dependency.

    Its absence there means a broken install, which the repo *can* fix -- so
    this one stays an error rather than quietly passing every file unchecked.
    """
    monkeypatch.setattr(linter, "IMPORT_ERROR", ImportError("no analyzer here"))
    monkeypatch.setattr(sys, "version_info", (3, 12, 0, "final", 0))

    assert linter.main([]) == 1
    assert "skipped" not in capsys.readouterr().out
