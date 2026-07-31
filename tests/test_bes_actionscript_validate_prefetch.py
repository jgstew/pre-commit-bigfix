#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_actionscript_validate_prefetch.py.

These exercise the prefetch line finding (both spellings, comments, dynamic
{...} lines, createfile blocks), the mapping of bigfix_prefetch's verdict and
warnings onto E400/E401/W402, the W403 nohash report, the mandatory-sha256
rule, the lxml-based extraction of every <ActionScript> from BES XML
(sourceline-accurate linenos, MIMEType gating), raw non-.bes file checking,
the skip/opt-out markers, --disable, W400 on unparsable XML, the
mustache-template skip, and main()'s exit codes.
"""

import pytest

from pre_commit_bigfix import bes_actionscript_validate_prefetch as validator

WINDOWS_SHELL = "application/x-Fixlet-Windows-Shell"

SHA1 = "e1652b058195db3f5f754b7ab430652ae04a50b8"
SHA256 = "8d9b5190aace52a1db1ac73a65ee9999c329157c8e88f61a772433323d6b7a4a"
URL = "https://software.bigfix.com/download/redist/unzip-5.52.exe"

GOOD_STATEMENT = f"prefetch unzip.exe sha1:{SHA1} size:167936 {URL} sha256:{SHA256}"
GOOD_BLOCK_ITEM = (
    f"add prefetch item name=unzip.exe sha1={SHA1} size=167936 "
    f"url={URL} sha256={SHA256}"
)


def bes(actions, marker=None):
    """Build a single-Task BES document.

    `actions` is a list of (body, mimetype) pairs (mimetype None omits the
    attribute); a single string means one Windows-Shell CDATA action.
    `marker` inserts an XML comment right after <BES>.
    """
    if isinstance(actions, str):
        actions = [(actions, WINDOWS_SHELL)]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            '<BES xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:noNamespaceSchemaLocation="BES.xsd">'
        ),
    ]
    if marker:
        lines.append(f"\t<!-- {marker} -->")
    lines.append("\t<Task>")
    lines.append("\t\t<Title>Example</Title>")
    lines.append('\t\t<Relevance>exists folder "/tmp"</Relevance>')
    for i, (body, mimetype) in enumerate(actions, start=1):
        tag = "DefaultAction" if i == 1 else "Action"
        mime = f' MIMEType="{mimetype}"' if mimetype else ""
        lines.append(f'\t\t<{tag} ID="Action{i}">')
        lines.append(f"\t\t\t<ActionScript{mime}><![CDATA[{body}]]></ActionScript>")
        lines.append(f"\t\t</{tag}>")
    lines.append("\t</Task>")
    lines.append("</BES>")
    return "\n".join(lines) + "\n"


def write(tmp_path, name, content):
    """Write `content` to tmp_path/name with CRLF endings; return the path str."""
    path = tmp_path / name
    crlf = content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    path.write_bytes(crlf.encode("utf-8"))
    return str(path)


def issues_for(tmp_path, content, name="x.bes", disabled=frozenset(), **kwargs):
    """Return the issue list for `content` written to a file."""
    path = write(tmp_path, name, content)
    issues, fixed = validator.check_file(path, disabled=disabled, **kwargs)
    assert fixed == []  # this hook has no auto-fixes
    return issues


def codes(issues):
    """Return just the check codes of an issue list."""
    return [code for _lineno, code, _message in issues]


# --- line finding ------------------------------------------------------------


def test_finds_both_prefetch_spellings():
    body = (
        f"{GOOD_STATEMENT}\nbegin prefetch block\n{GOOD_BLOCK_ITEM}\nend prefetch block"
    )
    found = list(validator.find_prefetch_lines(body))
    assert [lineno for lineno, _line, _nohash in found] == [1, 3]
    assert all(not nohash for _lineno, _line, nohash in found)


def test_indented_and_uppercase_lines_are_found():
    body = f"\tADD PREFETCH ITEM name=x sha1={SHA1} size=5 url={URL} sha256={SHA256}"
    assert len(list(validator.find_prefetch_lines(body))) == 1


def test_comment_and_blank_lines_are_not_prefetches():
    body = f"// {GOOD_STATEMENT}\n\n   \n"
    assert list(validator.find_prefetch_lines(body)) == []


def test_dynamic_prefetch_is_skipped():
    body = "prefetch {name of it} sha1:{sha1 of it} size:{size of it} https://x/y"
    assert list(validator.find_prefetch_lines(body)) == []
    assert validator.validate_actionscript(body) == []


def test_createfile_block_content_is_not_scanned():
    body = (
        "createfile until END_OF_FILE\n"
        "prefetch not-really.exe size:0 http://example.com/x\n"
        f"END_OF_FILE\n{GOOD_STATEMENT}"
    )
    found = list(validator.find_prefetch_lines(body))
    assert [lineno for lineno, _line, _nohash in found] == [4]


def test_nohash_is_reported_not_validated():
    body = f"add nohash prefetch item name=x size=5 url={URL}"
    issues = validator.validate_actionscript(body)
    assert codes(issues) == ["W403"]


# --- validation verdicts -----------------------------------------------------


def test_valid_prefetches_report_nothing():
    assert validator.validate_actionscript(GOOD_STATEMENT) == []
    assert validator.validate_actionscript(GOOD_BLOCK_ITEM) == []


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        (GOOD_STATEMENT.replace("size:167936", "size:0"), "size is invalid"),
        (GOOD_STATEMENT.replace(f"sha1:{SHA1}", "sha1:e1652b05"), "sha1 not the"),
        (
            GOOD_STATEMENT.replace(f"sha256:{SHA256}", "sha256:8d9b5190"),
            "sha256 not the",
        ),
        ("prefetch garbage-with-no-fields", "size is missing"),
    ],
)
def test_invalid_prefetch_is_e400_with_the_reason(body, fragment):
    issues = validator.validate_actionscript(body)
    assert codes(issues) == ["E400"]
    assert fragment in issues[0][2]
    assert validator.PREFETCH_MARKER in issues[0][2]


def test_missing_sha256_is_an_error():
    """Upstream calls sha256 optional; this hook treats it as mandatory."""
    body = GOOD_STATEMENT.replace(f" sha256:{SHA256}", "")
    issues = validator.validate_actionscript(body)
    assert codes(issues) == ["E401"]
    assert "no sha256" in issues[0][2]


def test_missing_sha256_can_be_disabled(tmp_path):
    body = GOOD_STATEMENT.replace(f" sha256:{SHA256}", "")
    assert issues_for(tmp_path, bes(body), disabled={"E401"}) == []


def test_block_item_without_sha1_warns():
    body = GOOD_BLOCK_ITEM.replace(f" sha1={SHA1}", "")
    assert codes(validator.validate_actionscript(body)) == ["W402"]


def test_statement_without_sha1_is_an_error():
    """Sha1 is mandatory in a prefetch statement, unlike in a block item."""
    body = GOOD_STATEMENT.replace(f"sha1:{SHA1} ", "")
    assert codes(validator.validate_actionscript(body)) == ["E400"]


def test_missing_hash_is_reported_once():
    """The parse and validate layers both warn about a missing sha256."""
    body = GOOD_BLOCK_ITEM.replace(f" sha256={SHA256}", "")
    assert codes(validator.validate_actionscript(body)) == ["E401"]


def test_block_item_with_neither_hash_reports_both_hashes():
    """A missing sha1 makes upstream fail the line on the missing sha256.

    That failure is this hook's E401, not a second E400 saying the same
    thing, and the unusual missing sha1 is still its own W402.
    """
    body = GOOD_BLOCK_ITEM.replace(f" sha1={SHA1}", "").replace(f" sha256={SHA256}", "")
    assert sorted(codes(validator.validate_actionscript(body))) == ["E401", "W402"]


def test_a_hard_failure_and_a_missing_sha256_are_both_reported():
    body = GOOD_STATEMENT.replace("size:167936", "size:0").replace(
        f" sha256:{SHA256}", ""
    )
    issues = validator.validate_actionscript(body)
    assert sorted(codes(issues)) == ["E400", "E401"]
    assert "size is invalid" in {code: message for _l, code, message in issues}["E400"]


def test_line_numbers_are_local_to_the_body():
    body = f"// header\n\n{GOOD_STATEMENT.replace('size:167936', 'size:0')}"
    issues = validator.validate_actionscript(body)
    assert issues[0][0] == 3


# --- BES XML extraction ------------------------------------------------------


def test_linenos_map_back_to_the_file(tmp_path):
    issues = issues_for(tmp_path, bes("prefetch bad size:0 http://example.com/x"))
    assert codes(issues) == ["E400"]
    assert issues[0][0] == 7  # the <ActionScript> line of the generated document


def test_non_actionscript_mimetypes_are_skipped(tmp_path):
    bad = "prefetch bad size:0 http://example.com/x"
    content = bes([(bad, "application/x-sh"), (bad, "text/x-uri")])
    assert issues_for(tmp_path, content) == []


def test_missing_mimetype_is_actionscript(tmp_path):
    content = bes([("prefetch bad size:0 http://example.com/x", None)])
    assert codes(issues_for(tmp_path, content)) == ["E400"]


def test_entities_are_decoded_before_validating(tmp_path):
    """A non-CDATA body with &amp; is validated as the agent would see it."""
    content = bes(GOOD_STATEMENT).replace(
        f"<![CDATA[{GOOD_STATEMENT}]]>",
        GOOD_STATEMENT.replace(URL, f"{URL}?a=1&amp;b=2"),
    )
    assert issues_for(tmp_path, content) == []


def test_unparsable_xml_is_w400(tmp_path):
    issues = issues_for(tmp_path, "<BES><Task></BES>")
    assert codes(issues) == ["W400"]


def test_missing_file_is_w400(tmp_path):
    issues, fixed = validator.check_file(str(tmp_path / "nope.bes"))
    assert codes(issues) == ["W400"]
    assert fixed == []


def test_raw_actionscript_file_is_checked(tmp_path):
    issues = issues_for(
        tmp_path, "prefetch bad size:0 http://example.com/x\n", name="x.txt"
    )
    assert codes(issues) == ["E400"]


# --- opt-outs ----------------------------------------------------------------


def test_skip_marker_disables_the_whole_file(tmp_path):
    content = bes(
        "prefetch bad size:0 http://example.com/x", marker=validator.SKIP_MARKER
    )
    assert issues_for(tmp_path, content) == []


@pytest.mark.parametrize(
    "body",
    [
        "prefetch bad size:0 http://example.com/x",
        GOOD_STATEMENT.replace(f" sha256:{SHA256}", ""),
        GOOD_BLOCK_ITEM.replace(f" sha1={SHA1}", ""),
        f"add nohash prefetch item name=x size=5 url={URL}",
    ],
)
def test_the_prefetch_ok_marker_opts_out_of_every_check(tmp_path, body):
    assert issues_for(tmp_path, bes(body)) != []
    assert issues_for(tmp_path, bes(body, marker=validator.PREFETCH_MARKER)) == []


def test_disable_skips_a_code(tmp_path):
    content = bes("prefetch bad size:0 http://example.com/x")
    assert issues_for(tmp_path, content, disabled={"E400"}) == []


def test_mustache_templates_are_skipped(tmp_path):
    content = bes("prefetch {{ name }} size:0 http://example.com/x")
    assert issues_for(tmp_path, content) == []


# --- main() ------------------------------------------------------------------


def test_main_passes_a_valid_file(tmp_path, capsys):
    path = write(tmp_path, "ok.bes", bes(GOOD_STATEMENT))
    assert validator.main([path]) == 0
    assert capsys.readouterr().out == ""


def test_main_fails_on_an_error(tmp_path, capsys):
    path = write(tmp_path, "bad.bes", bes("prefetch bad size:0 http://example.com/x"))
    assert validator.main([path]) == 1
    assert "[E400]" in capsys.readouterr().out


def test_main_warning_only_fails_under_strict(tmp_path, capsys):
    body = GOOD_BLOCK_ITEM.replace(f" sha1={SHA1}", "")
    path = write(tmp_path, "warn.bes", bes(body))
    assert validator.main([path]) == 0
    assert "[W402]" in capsys.readouterr().out
    assert validator.main(["--strict", path]) == 1


def test_main_reports_unknown_disable_codes(tmp_path, capsys):
    path = write(tmp_path, "ok.bes", bes(GOOD_STATEMENT))
    assert validator.main(["--disable", "E999", path]) == 0
    assert "unknown --disable code" in capsys.readouterr().out


def test_main_discovers_bes_files(tmp_path, monkeypatch):
    write(tmp_path, "bad.bes", bes("prefetch bad size:0 http://example.com/x"))
    monkeypatch.chdir(tmp_path)
    assert validator.main([]) == 1
