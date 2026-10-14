"""Tests for pre_commit_bigfix/bes_schema_validate.py.

Requires the `validate_bes_xml` package (installed via requirements.txt in CI);
skipped where it is not available.
"""

from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parent / "examples"

pytest.importorskip("validate_bes_xml")

from pre_commit_bigfix import bes_schema_validate as hook


def test_valid_bes_passes():
    assert hook.main([str(EXAMPLES / "example-test.bes")]) == 0


def test_no_files_is_zero():
    assert hook.main([]) == 0


def test_malformed_bes_fails(tmp_path):
    bad = tmp_path / "bad.bes"
    bad.write_text("<BES><Task><Unclosed></Task></BES>", encoding="utf-8")
    assert hook.main([str(bad)]) == 1


def test_mixed_valid_and_invalid_counts_only_bad(tmp_path):
    bad = tmp_path / "bad.bes"
    bad.write_text("<BES><Task><Unclosed></Task></BES>", encoding="utf-8")
    good = str(EXAMPLES / "example-test.bes")
    assert hook.main([good, str(bad)]) == 1


# --- Git External Custom Site and BigFix Inventory signature files ----------

GOOD_SITE_FILES = [
    EXAMPLES / "site" / "siteConfig.xml",
    EXAMPLES / "site" / "site.xml",
    EXAMPLES / "site" / "Fixlets" / "digest.xml",
    EXAMPLES / "Signatures" / "example.xml",
]

# (file, line of the one schema error it has)
BAD_SITE_FILES = [
    (EXAMPLES / "site-bad" / "siteConfig.xml", 4),  # a second <BesFileDir>
    (EXAMPLES / "site-bad" / "site.xml", 4),  # a second <Relevance>
    (EXAMPLES / "site-bad" / "Fixlets" / "digest.xml", 4),  # PT10M
    (EXAMPLES / "site-bad" / "Signatures" / "example.xml", 7),  # size="12a"
]


@pytest.mark.parametrize("path", GOOD_SITE_FILES, ids=lambda p: p.name)
def test_valid_site_file_passes_silently(path, capsys):
    assert hook.main([str(path)]) == 0
    assert capsys.readouterr().out == ""


def test_valid_bes_passes_silently(capsys):
    assert hook.main([str(EXAMPLES / "example-test.bes")]) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("path", "line"), BAD_SITE_FILES, ids=lambda p: getattr(p, "name", str(p))
)
def test_invalid_site_file_fails_with_path_and_line(path, line, capsys):
    assert hook.main([str(path)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    assert out[0].startswith(f"{path}:{line}: Element ")


def test_site_xml_syntax_error_fails_on_line_1(tmp_path, capsys):
    bad = tmp_path / "site.xml"
    bad.write_text("<Site><Relevance>true</Site", encoding="utf-8")
    assert hook.main([str(bad)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out and all(line.startswith(f"{bad}:1: ") for line in out)


@pytest.mark.parametrize(
    "content",
    [
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>',
        '<site xmlns="http://maven.apache.org/SITE/2.0.0"/>',
    ],
    ids=["sitemap", "maven"],
)
def test_non_bigfix_site_xml_is_skipped(tmp_path, content, capsys):
    other = tmp_path / "site.xml"
    other.write_text(content, encoding="utf-8")
    assert hook.main([str(other)]) == 0
    # a skip never shows validate_bes_xml's inferred schema name, which is
    # cut short for namespaced roots ("0.9}urlset.xsd")
    assert "xsd" not in capsys.readouterr().out


def test_eclipse_update_site_xml_fails(tmp_path):
    """A lowercase <site> with no namespace matches Site.xsd, by decision."""
    eclipse = tmp_path / "site.xml"
    eclipse.write_text(
        '<site><feature url="features/x_1.0.jar" id="x" version="1.0"/></site>',
        encoding="utf-8",
    )
    assert hook.main([str(eclipse)]) == 1


def test_bes_with_unknown_root_fails_without_line(tmp_path, capsys):
    unknown = tmp_path / "unknown.bes"
    unknown.write_text("<Foo/>", encoding="utf-8")
    assert hook.main([str(unknown)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    assert out[0].startswith(f"{unknown}: no schema")


def test_cwd_schema_is_ignored(tmp_path, monkeypatch):
    """A Foo.xsd beside the files must not make <Foo/> checkable."""
    import validate_bes_xml  # pylint: disable=import-outside-toplevel

    foo_xsd = tmp_path / "Foo.xsd"
    foo_xsd.write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="Foo"/></xs:schema>',
        encoding="utf-8",
    )
    foo = tmp_path / "foo.bes"
    foo.write_text("<Foo/>", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # SCHEMA_FILES is built at import, so add the cwd schema the way an
    # import from this folder would have: the package re-exports it, and the
    # inner module's copy is the one validate_bes() falls back to
    with_cwd = {*validate_bes_xml.SCHEMA_FILES, str(foo_xsd)}
    monkeypatch.setattr(validate_bes_xml, "SCHEMA_FILES", with_cwd)
    monkeypatch.setattr(validate_bes_xml.validate_bes_xml, "SCHEMA_FILES", with_cwd)
    assert validate_bes_xml.validate_xml(str(foo), verbose=False)  # upstream would
    assert hook.main([str(foo)]) == 1


def test_mixed_run_counts_only_invalid_files(tmp_path):
    sitemap = tmp_path / "site.xml"
    sitemap.write_text(
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>',
        encoding="utf-8",
    )
    files = [str(p) for p in GOOD_SITE_FILES]
    files += [str(p) for p, _ in BAD_SITE_FILES]
    files += [str(sitemap), str(EXAMPLES / "example-test.bes")]
    assert hook.main(files) == len(BAD_SITE_FILES)
