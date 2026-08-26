#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_actionscript_validate_prefetch.py.

These exercise the prefetch line finding (both spellings, comments, dynamic
{...} lines, createfile blocks), the mapping of bigfix_prefetch's verdict and
warnings onto E400/E401/W402, the W403 nohash report, the mandatory-sha256
rule, the lxml-based extraction of every <ActionScript> from BES XML
(sourceline-accurate linenos, MIMEType gating), raw non-.bes file checking,
the skip/opt-out markers, --disable, W400 on unparsable XML, the
mustache-template skip, the E402 retired-unzip check and its auto-fix, and
main()'s exit codes.
"""

import pytest

from pre_commit_bigfix import bes_actionscript_validate_prefetch as validator

WINDOWS_SHELL = "application/x-Fixlet-Windows-Shell"

SHA1 = "e1652b058195db3f5f754b7ab430652ae04a50b8"
SHA256 = "8d9b5190aace52a1db1ac73a65ee9999c329157c8e88f61a772433323d6b7a4a"
URL = "https://software.bigfix.com/download/redist/7za920.exe"

GOOD_STATEMENT = f"prefetch 7za920.exe sha1:{SHA1} size:167936 {URL} sha256:{SHA256}"
GOOD_BLOCK_ITEM = (
    f"add prefetch item name=7za920.exe sha1={SHA1} size=167936 "
    f"url={URL} sha256={SHA256}"
)

OLD_URL = "http://software.bigfix.com/download/redist/unzip-5.52.exe"
OLD_STATEMENT = f"prefetch unzip.exe sha1:{SHA1} size:167936 {OLD_URL} sha256:{SHA256}"
OLD_BLOCK_ITEM = (
    f"add prefetch item name=unzip.exe sha1={SHA1} size=167936 "
    f"url={OLD_URL} sha256={SHA256}"
)
# the one the auto-fix is expected to write, verbatim
NEW_BLOCK_ITEM = (
    "add prefetch item name=unzip.exe "
    "sha1=84debf12767785cd9b43811022407de7413beb6f size=204800 "
    "url=http://software.bigfix.com/download/redist/unzip-6.0.exe "
    "sha256=2122557d350fd1c59fb0ef32125330bde673e9331eb9371b454c2ad2d82091ac"
)
NEW_STATEMENT = (
    "prefetch unzip.exe sha1:84debf12767785cd9b43811022407de7413beb6f "
    "size:204800 http://software.bigfix.com/download/redist/unzip-6.0.exe "
    "sha256:2122557d350fd1c59fb0ef32125330bde673e9331eb9371b454c2ad2d82091ac"
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
    if not kwargs.get("auto_fix"):
        assert fixed == []  # E402 is the only fixable code, and only on request
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
        (f"prefetch garbage-with-no-fields sha1:{SHA1}", "size is missing"),
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


def test_statement_without_sha1_warns():
    """Current BigFix clients accept a statement with sha256 alone.

    Upstream can't even parse a sha1-less statement (its `sha1:` regex has no
    `try`), so this hook splices in a placeholder to check everything else and
    reports the missing sha1 itself, as an advisory W405 rather than E400.
    """
    body = GOOD_STATEMENT.replace(f"sha1:{SHA1} ", "")
    assert codes(validator.validate_actionscript(body)) == ["W405"]


def test_statement_without_either_hash_reports_both():
    """A sha1-less, sha256-less statement gets both codes, block-item style."""
    body = GOOD_STATEMENT.replace(f"sha1:{SHA1} ", "").replace(f" sha256:{SHA256}", "")
    assert sorted(codes(validator.validate_actionscript(body))) == ["E401", "W405"]


def test_statement_without_sha1_and_bad_size_still_reports_e400():
    """The placeholder sha1 splice must not swallow a real defect like size:0."""
    body = GOOD_STATEMENT.replace(f"sha1:{SHA1} ", "").replace("size:167936", "size:0")
    assert sorted(codes(validator.validate_actionscript(body))) == ["E400", "W405"]


def test_disable_w405(tmp_path):
    body = GOOD_STATEMENT.replace(f"sha1:{SHA1} ", "")
    assert issues_for(tmp_path, bes(body), disabled={"W405"}) == []


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
    issues = issues_for(
        tmp_path,
        bes(f"prefetch bad sha1:{SHA1} size:0 http://example.com/x sha256:{SHA256}"),
    )
    assert codes(issues) == ["E400"]
    assert issues[0][0] == 7  # the <ActionScript> line of the generated document


def test_non_actionscript_mimetypes_are_skipped(tmp_path):
    bad = "prefetch bad size:0 http://example.com/x"
    content = bes([(bad, "application/x-sh"), (bad, "text/x-uri")])
    assert issues_for(tmp_path, content) == []


def test_missing_mimetype_is_actionscript(tmp_path):
    content = bes(
        [
            (
                f"prefetch bad sha1:{SHA1} size:0 http://example.com/x sha256:{SHA256}",
                None,
            )
        ]
    )
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
        tmp_path,
        f"prefetch bad sha1:{SHA1} size:0 http://example.com/x sha256:{SHA256}" + "\n",
        name="x.txt",
    )
    assert codes(issues) == ["E400"]


# --- E402: the retired unzip-5.52.exe ----------------------------------------


@pytest.mark.parametrize("body", [OLD_STATEMENT, OLD_BLOCK_ITEM])
def test_outdated_unzip_is_e402(body):
    issues = validator.validate_actionscript(body)
    assert codes(issues) == ["E402"]
    assert "unzip-6.0.exe" in issues[0][2]


def test_outdated_unzip_matches_either_scheme():
    body = OLD_STATEMENT.replace("http://", "https://")
    assert codes(validator.validate_actionscript(body)) == ["E402"]


def test_current_unzip_is_not_e402():
    assert validator.validate_actionscript(NEW_STATEMENT) == []
    assert validator.validate_actionscript(NEW_BLOCK_ITEM) == []


def test_outdated_nohash_unzip_is_reported_but_not_fixable(tmp_path):
    body = f"add nohash prefetch item name=unzip.exe size=167936 url={OLD_URL}"
    assert sorted(codes(validator.validate_actionscript(body))) == ["E402", "W403"]
    path = write(tmp_path, "x.bes", bes(body))
    before = open(path, "rb").read()
    issues, fixed = validator.check_file(path, auto_fix=True)
    assert fixed == []
    assert "E402" in codes(issues)
    assert open(path, "rb").read() == before


def test_e402_can_be_disabled(tmp_path):
    assert issues_for(tmp_path, bes(OLD_STATEMENT), disabled={"E402"}) == []


# --- the E402 auto-fix -------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [(OLD_STATEMENT, NEW_STATEMENT), (OLD_BLOCK_ITEM, NEW_BLOCK_ITEM)],
)
def test_auto_fix_rewrites_to_the_current_unzip(tmp_path, body, expected):
    path = write(tmp_path, "x.bes", bes(body))
    issues, fixed = validator.check_file(path, auto_fix=True)
    assert codes(fixed) == ["E402"]
    assert issues == []  # the rewritten line is clean
    written = open(path, "rb").read().decode("utf-8")
    assert expected in written
    assert "unzip-5.52.exe" not in written


def test_auto_fix_keeps_crlf_and_the_rest_of_the_line(tmp_path):
    """The prefetch text is replaced in place, not the whole file line."""
    content = bes(OLD_BLOCK_ITEM)
    path = write(tmp_path, "x.bes", content)
    validator.check_file(path, auto_fix=True)
    raw = open(path, "rb").read()
    assert b"\n" in raw and b"\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n")
    assert f"<![CDATA[{NEW_BLOCK_ITEM}]]></ActionScript>".encode() in raw


def test_auto_fix_keeps_the_original_download_name(tmp_path):
    """The rest of the ActionScript refers to the file by name; don't rename it."""
    body = OLD_STATEMENT.replace("prefetch unzip.exe", "prefetch unz552.exe")
    path = write(tmp_path, "x.bes", bes(body))
    validator.check_file(path, auto_fix=True)
    written = open(path, "rb").read().decode("utf-8")
    assert "prefetch unz552.exe " in written
    assert "unzip-6.0.exe" in written


def test_auto_fix_leaves_other_files_alone(tmp_path):
    """A file with no retired unzip prefetch is not rewritten at all."""
    path = write(tmp_path, "ok.bes", bes(GOOD_STATEMENT))
    before = open(path, "rb").read()
    assert validator.check_file(path, auto_fix=True) == ([], [])
    assert open(path, "rb").read() == before


def test_auto_fix_works_on_raw_actionscript_files(tmp_path):
    path = write(tmp_path, "x.txt", f"// header\n{OLD_STATEMENT}\n")
    issues, fixed = validator.check_file(path, auto_fix=True)
    assert [lineno for lineno, _code, _message in fixed] == [2]
    assert NEW_STATEMENT in open(path, "rb").read().decode("utf-8")


def test_auto_fix_respects_the_opt_out_marker(tmp_path):
    content = bes(OLD_STATEMENT, marker=validator.PREFETCH_MARKER)
    path = write(tmp_path, "x.bes", content)
    before = open(path, "rb").read()
    assert validator.check_file(path, auto_fix=True) == ([], [])
    assert open(path, "rb").read() == before


def test_auto_fix_respects_disable(tmp_path):
    path = write(tmp_path, "x.bes", bes(OLD_STATEMENT))
    before = open(path, "rb").read()
    assert validator.check_file(path, disabled={"E402"}, auto_fix=True) == ([], [])
    assert open(path, "rb").read() == before


def test_main_auto_fixes_by_default_and_fails(tmp_path, capsys):
    path = write(tmp_path, "x.bes", bes(OLD_STATEMENT))
    assert validator.main([path]) == 1
    assert "auto-fixed" in capsys.readouterr().out
    assert NEW_STATEMENT in open(path, "rb").read().decode("utf-8")
    # the fix is idempotent, and the fixed file then passes
    assert validator.main([path]) == 0


def test_main_auto_fix_no_reports_without_rewriting(tmp_path, capsys):
    path = write(tmp_path, "x.bes", bes(OLD_STATEMENT))
    before = open(path, "rb").read()
    assert validator.main(["--auto-fix", "no", path]) == 1
    assert "[E402]" in capsys.readouterr().out
    assert open(path, "rb").read() == before


def test_main_does_not_auto_fix_when_discovering(tmp_path, monkeypatch):
    path = write(tmp_path, "x.bes", bes(OLD_STATEMENT))
    before = open(path, "rb").read()
    monkeypatch.chdir(tmp_path)
    assert validator.main([]) == 1
    assert open(path, "rb").read() == before


# --- the --auto-fix-network sha256 fix ---------------------------------------
#
# Nothing here touches the network: `sha256_added_prefetch` is the one function
# that downloads, and it is stubbed. The one test of its own logic stubs
# bigfix_prefetch's `add_sha256_prefetch` instead, one layer further down.

NO_SHA256_STATEMENT = GOOD_STATEMENT.replace(f" sha256:{SHA256}", "")
NO_SHA256_BLOCK_ITEM = GOOD_BLOCK_ITEM.replace(f" sha256={SHA256}", "")


@pytest.fixture(name="downloaded")
def downloaded_fixture(monkeypatch):
    """Stub the download, and record the lines it was asked about."""
    asked = []

    def fake(line):
        asked.append(line)
        joiner = "=" if line.lower().startswith("add prefetch item") else ":"
        return f"{line} sha256{joiner}{SHA256}"

    monkeypatch.setattr(validator, "sha256_added_prefetch", fake)
    return asked


@pytest.mark.parametrize(
    "body", [NO_SHA256_STATEMENT, NO_SHA256_BLOCK_ITEM], ids=["statement", "block"]
)
def test_network_fix_adds_the_sha256(tmp_path, downloaded, body):
    path = write(tmp_path, "x.bes", bes(body))
    issues, fixed = validator.check_file(path, auto_fix_network=True)
    assert codes(fixed) == ["E401"]
    assert issues == []  # the E401 is gone, because the line now has a sha256
    assert downloaded == [body]
    assert SHA256 in open(path, "rb").read().decode("utf-8")


def test_network_fix_is_off_by_default(tmp_path, downloaded):
    path = write(tmp_path, "x.bes", bes(NO_SHA256_STATEMENT))
    before = open(path, "rb").read()
    issues, fixed = validator.check_file(path, auto_fix=True)
    assert codes(issues) == ["E401"]
    assert fixed == []
    assert downloaded == []
    assert open(path, "rb").read() == before


def test_network_fix_leaves_prefetches_that_have_a_sha256_alone(tmp_path, downloaded):
    path = write(tmp_path, "ok.bes", bes(GOOD_STATEMENT))
    assert validator.check_file(path, auto_fix_network=True) == ([], [])
    assert downloaded == []


def test_network_fix_skips_nohash_lines(tmp_path, downloaded):
    body = f"add nohash prefetch item name=x size=5 url={URL}"
    path = write(tmp_path, "x.bes", bes(body))
    _issues, fixed = validator.check_file(path, auto_fix_network=True)
    assert fixed == []
    assert downloaded == []  # hashless on purpose; hashing it would change it


def test_a_failed_download_is_w404_and_changes_nothing(tmp_path, monkeypatch):
    def boom(_line):
        raise OSError("Name or service not known")

    monkeypatch.setattr(validator, "sha256_added_prefetch", boom)
    path = write(tmp_path, "x.bes", bes(NO_SHA256_STATEMENT))
    before = open(path, "rb").read()
    issues, fixed = validator.check_file(path, auto_fix_network=True)
    assert fixed == []
    assert sorted(codes(issues)) == ["E401", "W404"]
    assert (
        "Name or service not known"
        in dict((code, message) for _lineno, code, message in issues)["W404"]
    )
    assert open(path, "rb").read() == before


def test_a_repeated_url_is_downloaded_once(tmp_path, downloaded):
    """The cache is shared across files, so a common download is fetched once."""
    paths = [
        write(tmp_path, "a.bes", bes(NO_SHA256_STATEMENT)),
        write(tmp_path, "b.bes", bes(NO_SHA256_STATEMENT)),
    ]
    results = validator.check_files(paths, auto_fix_network=True)
    assert [codes(fixed) for _path, _issues, fixed in results] == [["E401"], ["E401"]]
    assert downloaded == [NO_SHA256_STATEMENT]


def test_the_offline_fix_runs_first_and_can_make_the_download_moot(
    tmp_path, downloaded
):
    """The E402 replacement already carries a sha256, so nothing is fetched."""
    body = OLD_STATEMENT.replace(f" sha256:{SHA256}", "")
    path = write(tmp_path, "x.bes", bes(body))
    _issues, fixed = validator.check_file(path, auto_fix=True, auto_fix_network=True)
    assert codes(fixed) == ["E402"]
    assert downloaded == []
    assert NEW_STATEMENT in open(path, "rb").read().decode("utf-8")


def test_network_fix_respects_disable_and_the_opt_out_marker(tmp_path, downloaded):
    path = write(tmp_path, "x.bes", bes(NO_SHA256_STATEMENT))
    assert validator.check_file(path, disabled={"E401"}, auto_fix_network=True) == (
        [],
        [],
    )
    marked = write(
        tmp_path, "y.bes", bes(NO_SHA256_STATEMENT, marker=validator.PREFETCH_MARKER)
    )
    assert validator.check_file(marked, auto_fix_network=True) == ([], [])
    assert downloaded == []


def test_network_fix_on_a_sha1_less_statement_is_w404_and_changes_nothing(tmp_path):
    """A sha1-less statement can't be verified against anything, so it stays.

    No download stub here: upstream's own `parse_prefetch()` raises before any
    network call is made (its `sha1:` regex has no `try`), so this exercises
    the real `sha256_added_prefetch()` and confirms the failure surfaces as
    W404 rather than crashing the run, and the line is left as it is.
    """
    body = GOOD_STATEMENT.replace(f"sha1:{SHA1} ", "").replace(f" sha256:{SHA256}", "")
    path = write(tmp_path, "x.bes", bes(body))
    before = open(path, "rb").read()
    issues, fixed = validator.check_file(path, auto_fix_network=True)
    assert fixed == []
    assert sorted(codes(issues)) == ["E401", "W404", "W405"]
    assert open(path, "rb").read() == before


def test_sha256_added_prefetch_keeps_the_original_name(monkeypatch):
    """Upstream names the file after the URL basename; the line's name wins."""
    line = (
        f"prefetch unzip.exe sha1:{SHA1} size:167936 "
        "http://software.bigfix.com/download/redist/unzip-6.0.exe"
    )

    def fake_add_sha256(prefetch_to_update, save_file=False):
        assert prefetch_to_update == line and not save_file
        print("upstream progress chatter that must not reach the hook's output")
        return (
            f"prefetch unzip-6.0.exe sha1:{SHA1} size:167936 "
            "http://software.bigfix.com/download/redist/unzip-6.0.exe "
            f"sha256:{SHA256}"
        )

    monkeypatch.setattr(validator, "add_sha256_prefetch", fake_add_sha256)
    assert validator.sha256_added_prefetch(line) == (
        f"prefetch unzip.exe sha1:{SHA1} size:167936 "
        "http://software.bigfix.com/download/redist/unzip-6.0.exe "
        f"sha256:{SHA256}"
    )


def test_sha256_added_prefetch_keeps_the_block_spelling(monkeypatch):
    line = NO_SHA256_BLOCK_ITEM
    monkeypatch.setattr(
        validator,
        "add_sha256_prefetch",
        lambda prefetch_to_update, save_file=False: f"{line} sha256={SHA256}",
    )
    assert validator.sha256_added_prefetch(line) == f"{line} sha256={SHA256}"


def test_sha256_added_prefetch_raises_when_no_sha256_came_back(monkeypatch):
    monkeypatch.setattr(
        validator,
        "add_sha256_prefetch",
        lambda prefetch_to_update, save_file=False: None,
    )
    with pytest.raises(ValueError):
        validator.sha256_added_prefetch(NO_SHA256_STATEMENT)


def test_main_network_fix_is_opt_in(tmp_path, capsys, downloaded):
    path = write(tmp_path, "x.bes", bes(NO_SHA256_STATEMENT))
    assert validator.main([path]) == 1
    assert "[E401]" in capsys.readouterr().out
    assert downloaded == []

    assert validator.main(["--auto-fix-network", "yes", path]) == 1
    assert "auto-fixed" in capsys.readouterr().out
    assert downloaded == [NO_SHA256_STATEMENT]
    assert validator.main([path]) == 0


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
    content = bes(
        f"prefetch bad sha1:{SHA1} size:0 http://example.com/x sha256:{SHA256}"
    )
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


def test_main_on_a_sha1_less_statement_warns_but_passes(tmp_path, capsys):
    """The shape that prompted W405: a real-world sha256-only statement."""
    body = (
        "prefetch win-x64-tcping.exe size:2075136 "
        "https://github.com/Tcp-Ping/Tcping/releases/download/v0.1.1/"
        f"win-x64-tcping.exe sha256:{SHA256}"
    )
    path = write(tmp_path, "warn.bes", bes(body))
    assert validator.main([path]) == 0
    assert "[W405]" in capsys.readouterr().out
    assert validator.main(["--strict", path]) == 1


def test_main_reports_unknown_disable_codes(tmp_path, capsys):
    path = write(tmp_path, "ok.bes", bes(GOOD_STATEMENT))
    assert validator.main(["--disable", "E999", path]) == 0
    assert "unknown --disable code" in capsys.readouterr().out


def test_main_discovers_bes_files(tmp_path, monkeypatch):
    write(tmp_path, "bad.bes", bes("prefetch bad size:0 http://example.com/x"))
    monkeypatch.chdir(tmp_path)
    assert validator.main([]) == 1
