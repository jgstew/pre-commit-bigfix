#!/usr/bin/env python3
"""Tests for the bes-signature-lint hook.

tests/examples/Signatures/lint-clean.xml is an invented signature every check
passes; each test below writes a variant of it with one defect into a temporary
folder, so the committed examples stay schema-valid for bes-schema-validate.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pre_commit_bigfix import bes_signature_lint

EXAMPLES = Path(__file__).resolve().parent / "examples"
CLEAN = EXAMPLES / "Signatures" / "lint-clean.xml"
CLEAN_TEXT = CLEAN.read_text(encoding="utf-8")
CLEAN_BODY = re.search(r"<!\[CDATA\[(.*?)\]\]>", CLEAN_TEXT, re.S).group(1)

SOFTWARE_ID = "3f2b8c1e-4d5a-4b6c-9e7f-0a1b2c3d4e5f"
SIGNATURE_ID = "7a6b5c4d-3e2f-4a1b-8c9d-0e1f2a3b4c5d"
# version 1 (time-based): the 15th character is "1"
V1_ID = "bfbd5b10-99f3-11e7-8040-0050560082fd"


def signature(
    body=CLEAN_BODY,
    unique_id=SIGNATURE_ID,
    created="2026-11-19T00:00:00Z",
    modified="2026-11-20T00:00:00Z",
):
    return (
        f'    <Signature uniqueId="{unique_id}" modified="{modified}" '
        f'created="{created}">\n'
        f"      <ExtendedSignature>\n"
        f"        <![CDATA[{body}]]>\n"
        f"      </ExtendedSignature>\n"
        f"    </Signature>\n"
    )


def catalog(
    *signatures,
    software_id=SOFTWARE_ID,
    name="Example Widget",
    version="1.AFFECTED",
    header='ProductName: "Example Widget"\nRelease: "1.AFFECTED"\n',
):
    head = f"<!--\n{header}-->\n" if header is not None else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        + head
        + "<SoftwareIdentityCatalog>\n"
        + f'  <Software name="{name}" vendor="Example Vendor" '
        + f'uniqueId="{software_id}" version="{version}">\n'
        + "".join(signatures or (signature(),))
        + "  </Software>\n</SoftwareIdentityCatalog>\n"
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A temporary folder, outside git, holding a Signatures/ folder."""
    (tmp_path / "Signatures").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write(repo, text, name="s.xml"):
    path = repo / "Signatures" / name
    path.write_text(text, encoding="utf-8")
    return f"Signatures/{name}"


def run(capsys, *args):
    rc = bes_signature_lint.main(list(args))
    out = capsys.readouterr().out
    return rc, out, sorted(set(re.findall(r"\[([EW]\d{3})\]", out)))


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_clean_example_passes_strict(capsys):
    rc, out, codes = run(capsys, "--strict", "--enable", "W105,E106", str(CLEAN))
    assert (rc, codes) == (0, []), out


def test_body_length_limit(repo, capsys):
    pad = 3829 - len("<r/>")
    at_limit = write(repo, catalog(signature(body="<r/>" + " " * pad)))
    rc, out, codes = run(capsys, "--disable", "W100,W105", at_limit)
    assert "E100" not in codes, out
    over = write(repo, catalog(signature(body="<r/>" + " " * (pad + 1))))
    rc, out, codes = run(capsys, over)
    assert "E100" in codes and "3830 characters" in out
    assert rc == 1


def test_near_limit_and_custom_limit(repo, capsys):
    path = write(repo, catalog())
    length = len(CLEAN_BODY)
    _rc, out, codes = run(capsys, "--max-signature-chars", str(length + 5), path)
    assert codes == ["W100"], out
    rc, _out, codes = run(capsys, "--max-signature-chars", str(length - 1), path)
    assert codes == ["E100"] and rc == 1


def test_single_instance_multi_root_body_is_well_formed(repo, capsys):
    body = (
        '<Variable export="true" name="IS_INSTALLED"><ValueOf value="true"/>'
        '</Variable><Condition withVariable="IS_INSTALLED">'
        '<Action do="SKIP" onValue="false"/></Condition>'
    )
    rc, out, codes = run(capsys, write(repo, catalog(signature(body=body))))
    assert (rc, codes) == (0, []), out


def test_malformed_body(repo, capsys):
    rc, out, codes = run(capsys, write(repo, catalog(signature(body="<Instance>"))))
    assert codes == ["E101"] and rc == 1, out


def test_duplicate_id_in_one_file(repo, capsys):
    path = write(repo, catalog(signature(), signature()))
    rc, out, codes = run(capsys, path)
    assert codes == ["E102"]
    assert out.count("[E102]") == 2 and rc == 2


def test_duplicate_id_against_unchanged_file(repo, capsys):
    other = "1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5"
    write(repo, catalog(software_id=other, name="Other"), "old.xml")
    changed = write(repo, catalog(), "new.xml")
    rc, out, codes = run(capsys, changed)
    assert codes == ["E102"], out
    assert 'Signatures/old.xml (Software "Other")' in out
    assert out.startswith("Signatures/new.xml:")
    assert "old.xml:" not in out.split("also used by")[0]


def test_duplicate_software_id_is_a_warning(repo, capsys):
    other = "1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5"
    write(repo, catalog(signature(unique_id=other)), "old.xml")
    rc, out, codes = run(capsys, write(repo, catalog(), "new.xml"))
    assert (rc, codes) == (0, ["W101"]), out
    assert bes_signature_lint.main(["--strict", "Signatures/new.xml"]) == 1


def test_same_file_keeping_its_ids_is_not_a_collision(repo, capsys):
    path = write(repo, catalog())
    rc, out, codes = run(capsys, path, path)
    assert (rc, codes) == (0, []), out


@pytest.mark.parametrize(
    "old, new, code",
    [
        ('"$(text)"', '"$(txet)"', "E103"),
        ("<Instance>", "<Instance></Instance><Instance>", "E104"),
        (
            "<FindFilePathEx",
            '<RpmProductInfo code="x" field="version"/><FindFilePathEx',
            "E105",
        ),
    ],
)
def test_body_errors(repo, capsys, old, new, code):
    body = CLEAN_BODY.replace(old, new, 1)
    assert body != CLEAN_BODY
    rc, out, codes = run(capsys, write(repo, catalog(signature(body=body))))
    assert codes == [code] and rc == 1, out


def test_undefined_with_variable(repo, capsys):
    body = CLEAN_BODY.replace('withVariable="size"', 'withVariable="sz"')
    _rc, out, codes = run(capsys, write(repo, catalog(signature(body=body))))
    assert codes == ["E103"] and "'sz'" in out


@pytest.mark.parametrize(
    "old, new, code",
    [
        ('field="size"', 'field="modified"', "W102"),
        ('endString="&#13;"', 'endString=""', "W103"),
        (
            '<Condition withVariable="DETAILED_VER"><Action do="SKIP" onValue=""/>'
            "</Condition>",
            "",
            "W104",
        ),
        (
            "<FindFilePathEx",
            '<RpmProductList filter="widget" type="any"/><FindFilePathEx',
            "W106",
        ),
        (
            "<FindFilePathEx",
            '<MsiProductList filter="Widget"/><FindFilePathEx',
            "W107",
        ),
        (
            "<FindFilePathEx",
            '<XmlValue file="a" xpath="b"/><FindFilePathEx',
            "W108",
        ),
    ],
)
def test_body_warnings(repo, capsys, old, new, code):
    body = CLEAN_BODY.replace(old, new, 1)
    assert body != CLEAN_BODY
    rc, out, codes = run(capsys, write(repo, catalog(signature(body=body))))
    assert (rc, codes) == (0, [code]), out
    assert bes_signature_lint.main(["--strict", "Signatures/s.xml"]) == 1


@pytest.mark.parametrize(
    "filters",
    [
        '<RpmProductList filter="*widget-*" type="any"/>',
        '<MsiProductList filter="*"/>'
        + '<MsiProductList filter="*Widget"/>'
        + '<MsiProductList filter="{8077DB9D-1A2B-4C3D-9E8F-0A1B2C3D4E5F}"/>',
    ],
)
def test_good_filters_are_quiet(repo, capsys, filters):
    body = CLEAN_BODY.replace("<FindFilePathEx", filters + "<FindFilePathEx", 1)
    rc, out, codes = run(capsys, write(repo, catalog(signature(body=body))))
    assert (rc, codes) == (0, []), out


def test_exports_off_by_default(repo, capsys):
    body = CLEAN_BODY.replace(
        'export="true" name="IS_INSTALLED"', 'export="false" name="IS_INSTALLED"'
    )
    path = write(repo, catalog(signature(body=body)))
    assert run(capsys, path)[2] == []
    _rc, out, codes = run(capsys, "--enable", "W105", path)
    assert codes == ["W105"] and "IS_INSTALLED" in out


def test_header_mismatch(repo, capsys):
    text = catalog(header='ProductName: "Widget all"\nRelease: "0.AFFECTED"\n')
    rc, out, codes = run(capsys, write(repo, text))
    assert codes == ["W110"] and out.count("[W110]") == 2, out
    # reported at the <Software> tag
    assert out.startswith("Signatures/s.xml:7:")
    assert run(capsys, write(repo, catalog(header=None)))[2] == []
    assert run(capsys, write(repo, catalog(header='Author: "x"\n')))[2] == []


def test_modified_before_created(repo, capsys):
    text = catalog(
        signature(created="2026-11-20T00:00:00Z", modified="2026-11-19T00:00:00Z")
    )
    rc, out, codes = run(capsys, write(repo, text))
    assert (rc, codes) == (0, ["W111"]), out
    # reported at the <Signature> start tag
    assert out.startswith("Signatures/s.xml:8:")


def test_new_v1_ids_only_in_git(repo, capsys):
    path = write(repo, catalog(signature(unique_id=V1_ID)))
    # outside git: every other check still runs, W109 is skipped
    write(
        repo,
        catalog(
            signature(unique_id=V1_ID),
            software_id="1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5",
        ),
        "o.xml",
    )
    assert run(capsys, path)[2] == ["E102"]
    (repo / "Signatures" / "o.xml").unlink()
    assert run(capsys, path)[2] == []
    git(repo, "init", "-q")
    _rc, out, codes = run(capsys, path)
    assert codes == ["W109"] and V1_ID in out  # untracked
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "x")
    assert run(capsys, path)[2] == []  # at HEAD
    other_v1 = "a96093c0-1187-11ee-a859-025041000001"
    write(repo, catalog(signature(unique_id=V1_ID), signature(unique_id=other_v1)))
    _rc, out, codes = run(capsys, path)
    assert codes == ["W109"] and other_v1 in out and V1_ID not in out


def test_repo_index_uses_git_ls_files(repo, capsys):
    git(repo, "init", "-q")
    write(repo, catalog(software_id="1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5"), "old.xml")
    changed = write(repo, catalog(), "new.xml")
    git(repo, "add", "Signatures/old.xml")
    assert run(capsys, changed)[2] == ["E102"]


def test_unparsable_file_skipped_unless_enabled(repo, capsys):
    path = write(repo, "<SoftwareIdentityCatalog>")
    rc, out, codes = run(capsys, path)
    assert (rc, codes) == (0, []) and "skipped" in out
    rc, _out, codes = run(capsys, "--enable", "E106", path)
    assert (rc, codes) == (1, ["E106"])


def test_skip_marker_and_other_roots(repo, capsys):
    body = CLEAN_BODY.replace("<Instance>", "<Instance/><Instance>", 1)
    text = catalog(signature(body=body)).replace(
        "<SoftwareIdentityCatalog>",
        "<!-- pre-commit-skip: bes-signature-lint -->\n<SoftwareIdentityCatalog>",
    )
    assert run(capsys, write(repo, text))[0] == 0
    assert run(capsys, write(repo, "<Other/>", "o.xml"))[0] == 0


def test_disable(repo, capsys):
    path = write(repo, catalog(signature(body="<Instance/>")))
    assert run(capsys, path)[2] == ["E104"]
    assert run(capsys, "--disable", "E104", path)[0] == 0


def test_exit_code_capped(repo, capsys):
    path = write(repo, catalog(*[signature() for _ in range(300)]))
    rc, _out, _codes = run(capsys, path)
    assert rc == 255


def test_examples_folder_copy_is_clean(repo, capsys):
    shutil.copy(CLEAN, repo / "Signatures" / "c.xml")
    assert run(capsys, "--strict", "Signatures/c.xml")[0] == 0


# --- PR #65 review ---------------------------------------------------------


def test_index_is_per_repo_not_cwd(tmp_path, monkeypatch, capsys):
    # two clones of one repo under a parent folder that is not a git repo:
    # running from the parent must not report each clone against the other
    for clone in ("one", "two"):
        (tmp_path / clone / "Signatures").mkdir(parents=True)
        (tmp_path / clone / "Signatures" / "s.xml").write_text(catalog())
    git(tmp_path / "one", "init", "-q")
    monkeypatch.chdir(tmp_path)
    rc, out, codes = run(capsys, "one/Signatures/s.xml")
    assert (rc, codes) == (0, []), out


def test_index_reads_the_files_repo_from_outside_it(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    (repo / "Signatures").mkdir(parents=True)
    (repo / "Signatures" / "old.xml").write_text(
        catalog(software_id="1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5")
    )
    (repo / "Signatures" / "new.xml").write_text(catalog())
    git(repo, "init", "-q")
    git(repo, "add", "Signatures/old.xml")
    monkeypatch.chdir(tmp_path)
    _rc, out, codes = run(capsys, "repo/Signatures/new.xml")
    assert codes == ["E102"], out
    assert "repo/Signatures/old.xml" in out


def test_w109_follows_a_rename(repo, capsys):
    write(repo, catalog(signature(unique_id=V1_ID)), "old.xml")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "x")
    git(repo, "mv", "Signatures/old.xml", "Signatures/new.xml")
    rc, out, codes = run(capsys, "--strict", "Signatures/new.xml")
    assert (rc, codes) == (0, []), out


def test_self_closing_signature_before_a_normal_one(repo, capsys):
    # the body is exactly at the limit; counting the whitespace around the
    # CDATA would push it over
    body = "<r/>" + " " * (3829 - len("<r/>"))
    empty = '    <Signature uniqueId="1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5"/>\n'
    path = write(repo, catalog(empty, signature(body=body)))
    _rc, out, codes = run(capsys, "--disable", "W100", "--enable", "E100", path)
    assert "E100" not in codes, out


@pytest.mark.parametrize(
    "crop, cr, flagged",
    [
        ('endString="&#10;"', 'endString="&#xD;"', False),
        ('endString="&#10;"', 'endString="&#x0d;"', False),
        ("endString='&#10;'", 'endString=""', True),
        ('endString="&#xA;"', 'endString=""', True),
        ('endString = "&#x0a;"', 'endString=""', True),
    ],
)
def test_w103_entity_spellings(repo, capsys, crop, cr, flagged):
    body = CLEAN_BODY.replace('endString="&#10;"', crop, 1).replace(
        'endString="&#13;"', cr, 1
    )
    _rc, out, codes = run(capsys, write(repo, catalog(signature(body=body))))
    assert codes == (["W103"] if flagged else []), out


def test_index_skipped_when_its_checks_are_off(repo, capsys, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("index built")

    monkeypatch.setattr(bes_signature_lint, "_build_index", boom)
    path = write(repo, catalog())
    assert run(capsys, "--disable", "E102,W101", path)[0] == 0


def test_git_calls_do_not_grow_with_files(repo, capsys, monkeypatch):
    git(repo, "init", "-q")
    paths = [
        write(
            repo,
            catalog(
                signature(unique_id=f"7a6b5c4d-3e2f-4a1b-8c9d-0e1f2a3b4c{n:02d}"),
                software_id=f"3f2b8c1e-4d5a-4b6c-9e7f-0a1b2c3d4e{n:02d}",
            ),
            f"s{n}.xml",
        )
        for n in range(10)
    ]
    calls = []
    real_run = subprocess.run

    def counting(cmd, *args, **kwargs):
        if cmd and cmd[0] == "git":
            calls.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", counting)
    assert run(capsys, *paths)[0] == 0
    assert len(calls) <= 4, calls


def test_git_helper_is_shared(tmp_path):
    from pre_commit_bigfix import bes_common, bes_siterepo_validate_layout

    assert bes_common.run_git(tmp_path, "rev-parse", "--show-toplevel") is None
    git(tmp_path, "init", "-q")
    assert bes_common.run_git(tmp_path, "rev-parse", "--is-inside-work-tree") == (
        b"true\n"
    )
    assert bes_siterepo_validate_layout._git is bes_common.run_git


def test_same_file_two_spellings_linted_once(repo, capsys):
    path = write(repo, catalog(signature(body="<Instance/>")))
    rc, out, _codes = run(capsys, path, str(repo / path))
    assert rc == 1 and out.count("[E104]") == 1, out


# --- uniqueId case (PR #65 review) ----------------------------------------

UPPER_V1_ID = "CCCCCCCC-BBBB-1CCC-8DDD-EEEEEEEEEEEE"


def test_w109_finds_an_uppercase_id_at_head(repo, capsys):
    path = write(repo, catalog(signature(unique_id=UPPER_V1_ID)), "upper.xml")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "x")
    _rc, out, codes = run(capsys, "--disable", "W112", path)
    assert "W109" not in codes, out


def test_w109_head_lookup_ignores_case(repo, capsys):
    # committed lowercase, now written uppercase: the same ID, not a new one
    write(repo, catalog(signature(unique_id=UPPER_V1_ID.lower())))
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "x")
    path = write(repo, catalog(signature(unique_id=UPPER_V1_ID)))
    _rc, out, codes = run(capsys, "--disable", "W112", path)
    assert "W109" not in codes, out


def test_e102_ignores_case_in_one_file(repo, capsys):
    path = write(repo, catalog(signature(), signature(unique_id=SIGNATURE_ID.upper())))
    _rc, out, codes = run(capsys, "--disable", "W112", path)
    assert codes == ["E102"] and out.count("[E102]") == 2, out


def test_e102_ignores_case_across_files(repo, capsys):
    other = "1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5"
    write(
        repo,
        catalog(signature(unique_id=SIGNATURE_ID.upper()), software_id=other),
        "old.xml",
    )
    _rc, out, codes = run(
        capsys, "--disable", "W112", write(repo, catalog(), "new.xml")
    )
    assert codes == ["E102"] and "old.xml" in out, out


def test_w101_ignores_case_across_files(repo, capsys):
    other = "1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5"
    write(
        repo,
        catalog(signature(unique_id=other), software_id=SOFTWARE_ID.upper()),
        "old.xml",
    )
    _rc, out, codes = run(
        capsys, "--disable", "W112", write(repo, catalog(), "new.xml")
    )
    assert codes == ["W101"], out


def test_w101_ignores_case_in_one_file(repo, capsys):
    other = "1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5"
    text = catalog().replace(
        "  </Software>\n",
        "  </Software>\n"
        f'  <Software name="Example Widget" vendor="Example Vendor" '
        f'uniqueId="{SOFTWARE_ID.upper()}" version="1.AFFECTED">\n'
        + signature(unique_id=other)
        + "  </Software>\n",
    )
    _rc, out, codes = run(capsys, "--disable", "W112", write(repo, text))
    assert codes == ["W101"] and out.count("[W101]") == 2, out


def test_w112_uppercase_ids(repo, capsys):
    text = catalog(
        signature(unique_id=SIGNATURE_ID.upper()), software_id=SOFTWARE_ID.upper()
    )
    rc, out, codes = run(capsys, write(repo, text))
    assert (rc, codes) == (0, ["W112"]), out
    lines = sorted(re.findall(r"s\.xml:(\d+): \[W112\]", out))
    # the <Software> tag (line 7) and the <Signature> tag (line 8)
    assert lines == ["7", "8"], out
    # one failure per W112 under --strict
    assert bes_signature_lint.main(["--strict", "Signatures/s.xml"]) == 2
    assert run(capsys, "--disable", "W112", "Signatures/s.xml")[0] == 0


def test_w112_quiet_on_lowercase(repo, capsys):
    assert run(capsys, "--strict", write(repo, catalog()))[0] == 0
