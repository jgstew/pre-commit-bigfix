#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_common.py, the helpers the hooks share.

Covers read_source/encode line-ending round trips, discover_bes_files' pruning
and extension filter, report()'s output and counts (with errors_only), and the
schema_errors/schema_regression guard that keeps an auto-fix from turning a
schema-valid BES file into an invalid one.
"""

from pathlib import Path

import pytest

from pre_commit_bigfix import bes_common

EXAMPLE = Path(__file__).parent / "examples" / "example-test.bes"


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_read_source_and_encode_round_trip(tmp_path, newline):
    raw = b"a" + newline + b"b" + newline
    path = tmp_path / "x.bes"
    path.write_bytes(raw)
    got_raw, src, was_crlf = bes_common.read_source(str(path))
    assert got_raw == raw
    assert src == "a\nb\n"
    assert was_crlf == (newline == b"\r\n")
    assert bes_common.encode(src, was_crlf) == raw


def test_discover_prunes_hidden_and_noise_dirs(tmp_path):
    for rel in ("a.bes", "sub/b.bes", ".git/c.bes", "node_modules/d.bes", "e.ojo"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    found = bes_common.discover_bes_files(str(tmp_path))
    assert [Path(p).relative_to(tmp_path).as_posix() for p in found] == [
        "a.bes",
        "sub/b.bes",
    ]
    both = bes_common.discover_bes_files(str(tmp_path), (".bes", ".ojo"))
    assert len(both) == 3


def test_report_prints_and_counts(capsys):
    results = [("f.bes", [(2, "E1", "bad"), (3, "W1", "meh")], [(1, "E9", "done")])]
    assert bes_common.report(results) == (1, 1, 1)
    assert capsys.readouterr().out.splitlines() == [
        "f.bes:1: [E9] auto-fixed: done",
        "f.bes:2: [E1] bad",
        "f.bes:3: [W1] warning: meh",
    ]
    assert bes_common.report(results, errors_only=True) == (1, 0, 1)
    assert "[W1]" not in capsys.readouterr().out


# --- schema guard -------------------------------------------------------------

validate_bes_xml = pytest.importorskip("validate_bes_xml")

VALID = EXAMPLE.read_bytes()
# a second <Title> is well-formed XML but not allowed by BES.xsd
INVALID = VALID.replace(b"</Title>", b"</Title><Title>again</Title>", 1)


def test_schema_errors_is_empty_for_a_valid_file():
    assert bes_common.schema_errors(VALID) == []


def test_schema_errors_lists_the_problems_of_an_invalid_file():
    errors = bes_common.schema_errors(INVALID)
    assert errors
    assert all(isinstance(error, str) for error in errors)
    assert "Line " in errors[0]


def test_schema_errors_reports_unparsable_xml():
    assert bes_common.schema_errors(b"<BES><Task></BES>")


def test_schema_errors_is_none_when_no_schema_applies():
    assert bes_common.schema_errors(b"<NotBigFix/>") is None


def test_schema_regression_flags_valid_to_invalid():
    assert bes_common.schema_regression(VALID, INVALID)


def test_schema_regression_allows_valid_to_valid():
    assert bes_common.schema_regression(VALID, VALID) == []


def test_schema_regression_does_not_block_an_already_invalid_file():
    # bes-schema-validate owns invalid input; a fix must only not make it worse
    assert bes_common.schema_regression(INVALID, INVALID) == []


def test_schema_regression_ignores_files_without_a_schema():
    assert bes_common.schema_regression(b"<NotBigFix/>", b"<NotBigFix/>") == []


def test_importing_bes_common_needs_only_the_standard_library():
    """The stdlib-only bes-conventions-check must not get lxml via bes_common."""
    import subprocess
    import sys

    code = (
        "import sys; sys.modules['lxml'] = None; sys.modules['validate_bes_xml'] = None\n"
        "import pre_commit_bigfix.bes_common, pre_commit_bigfix.bes_conventions_check"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
