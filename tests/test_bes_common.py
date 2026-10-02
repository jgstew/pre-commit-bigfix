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


# --- review fixes: schema choice and import noise (PR #28) --------------------


@pytest.mark.parametrize("name", ["site/x.ojo", "site/X.OJO"])
def test_ojo_files_use_the_besojo_schema(name):
    """Upstream maps .ojo to BESOJO.xsd before inferring; so must the guard."""
    # the example is a Task, which BES.xsd allows and BESOJO.xsd does not
    assert bes_common.schema_errors(VALID, name)
    assert bes_common.schema_errors(VALID, "site/x.bes") == []
    assert bes_common.schema_errors(VALID) == []


def test_besdomain_files_use_the_besdomain_schema():
    assert bes_common.schema_errors(VALID, "site/x.BESDomain")


def test_schema_errors_delegates_to_validate_bes(monkeypatch):
    """The schema choice is upstream's: bes_common passes the name through."""
    calls = []
    real = validate_bes_xml.validate_bes

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(validate_bes_xml, "validate_bes", spy)
    assert bes_common.schema_errors(VALID, "site/x.bes") == []
    assert len(calls) == 1
    assert calls[0]["xml"] == VALID
    assert calls[0]["filename"] == "site/x.bes"


def test_no_bundled_schemas_means_unknown_not_the_cwd_ones(monkeypatch):
    # upstream treats an empty schema list as "use SCHEMA_FILES", cwd included
    monkeypatch.setattr(validate_bes_xml, "SCHEMA_FILES", {"/repo/BES.xsd"})
    assert bes_common.schema_errors(INVALID) is None


def _run_in(folder, code):
    """Run `code` in a fresh interpreter with `folder` as the current folder.

    The repo root goes on PYTHONPATH: leaving it for `folder` drops it from
    sys.path, and the package is not installed in every test environment
    (pre-commit's pytest hook installs only the dependencies).
    """
    import os
    import subprocess
    import sys

    root = str(Path(__file__).resolve().parent.parent)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [root, env.get("PYTHONPATH")]))
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=folder,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result


def test_a_cwd_schema_cannot_validate_an_unknown_root(tmp_path):
    # a repo-local Foo.xsd must not make <Foo> count as checkable BES XML
    (tmp_path / "Foo.xsd").write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="Foo"/></xs:schema>',
        encoding="utf-8",
    )
    _run_in(
        tmp_path,
        "from pre_commit_bigfix import bes_common\n"
        "assert bes_common.schema_errors(b'<Foo/>') is None\n",
    )


def test_bundled_schema_wins_over_a_cwd_copy(tmp_path):
    # a permissive repo-local BES.xsd must not let an invalid file through
    (tmp_path / "BES.xsd").write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="BES"><xs:complexType><xs:sequence>'
        '<xs:any processContents="skip" minOccurs="0" maxOccurs="unbounded"/>'
        "</xs:sequence></xs:complexType></xs:element></xs:schema>",
        encoding="utf-8",
    )
    invalid = tmp_path / "invalid.bes"
    invalid.write_bytes(INVALID)
    _run_in(
        tmp_path,
        "from pre_commit_bigfix import bes_common\n"
        "assert bes_common.schema_errors(open('invalid.bes', 'rb').read())\n",
    )


def test_validating_prints_nothing_even_with_a_bad_xsd_in_cwd(tmp_path):
    """Importing validate_bes_xml warns on stdout; none must reach the report."""
    (tmp_path / "broken.xsd").write_text("<not a schema", encoding="utf-8")
    out = _run_in(
        tmp_path,
        "from pre_commit_bigfix import bes_common\n"
        f"assert bes_common.schema_errors(open({str(EXAMPLE)!r}, 'rb').read()) == []\n",
    )
    assert out.stdout == ""


# --- review fix: a missing validate_bes_xml warns, it does not crash ----------


def test_missing_validate_bes_xml_means_unknown_and_warns_once(monkeypatch, capsys):
    import sys

    monkeypatch.setitem(sys.modules, "validate_bes_xml", None)  # import fails
    monkeypatch.setattr(bes_common, "_schema_check_warned", [])
    assert bes_common.schema_errors(INVALID) is None
    assert bes_common.schema_errors(INVALID) is None
    captured = capsys.readouterr()
    assert captured.out == ""  # the hook report on stdout stays clean
    assert captured.err.count("schema check unavailable") == 1
    assert "validate_bes_xml" in captured.err


def test_conventions_auto_fix_without_validate_bes_xml_still_writes(tmp_path):
    """The stdlib-only hook, run with no validate_bes_xml, fixes unchecked."""
    path = tmp_path / "x.bes"
    path.write_bytes(VALID.replace(b"</Title>", b"</Title>   ", 1))
    result = _run_in(
        tmp_path,
        "import sys; sys.modules['validate_bes_xml'] = None\n"
        "from pre_commit_bigfix import bes_conventions_check as hook\n"
        "_issues, fixed = hook.check_file('x.bes', auto_fix=True)\n"
        "assert 'W210' in [code for _l, code, _m in fixed], fixed\n",
    )
    assert b"</Title>   " not in path.read_bytes()
    assert "schema check unavailable" in result.stderr
    assert "Traceback" not in result.stderr
