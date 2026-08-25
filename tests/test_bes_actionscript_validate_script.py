#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_actionscript_validate_script.py.

These exercise the if/endif and begin/end prefetch block balance walk
(E500-E507), the lxml-based extraction of every <ActionScript> from BES XML
(sourceline-accurate linenos, case-insensitive MIMEType gating), raw non-.bes
file checking, createfile-heredoc masking, the skip/opt-out markers,
--disable, W500 on unparsable XML, the mustache-template skip, and main()'s
exit codes.
"""

from pre_commit_bigfix import bes_actionscript_validate_script as validator

WINDOWS_SHELL = "application/x-Fixlet-Windows-Shell"


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
    assert fixed == []  # this hook has no auto-fixes at all
    return issues


def codes(issues):
    """Return just the check codes of an issue list."""
    return [code for _lineno, code, _message in issues]


# --- balanced scripts report nothing -----------------------------------------


def test_balanced_if_else_elseif_endif_reports_nothing():
    body = (
        'if {name of operating system = "x"}\n'
        "wait cmd /c echo a\n"
        'elseif {name of operating system = "y"}\n'
        "wait cmd /c echo b\n"
        "else\n"
        "wait cmd /c echo c\n"
        "endif"
    )
    assert validator.check_actionscript(body) == []


def test_balanced_prefetch_block_reports_nothing():
    body = (
        "begin prefetch block\n"
        "add prefetch item name=x sha1=1 size=1 url=http://x/y\n"
        "end prefetch block"
    )
    assert validator.check_actionscript(body) == []


def test_nested_balanced_if_reports_nothing():
    body = "if {true}\n" "if {true}\n" "wait cmd /c echo a\n" "endif\n" "endif"
    assert validator.check_actionscript(body) == []


def test_comment_and_blank_lines_are_ignored():
    body = "// if {true}\n\n   \nwait cmd /c echo a"
    assert validator.check_actionscript(body) == []


# --- E500: unclosed if -------------------------------------------------------


def test_unclosed_if_is_e500():
    body = 'if {name of operating system = "x"}\nwait cmd /c echo a'
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E500"]
    assert issues[0][0] == 1
    assert validator.IF_MARKER in issues[0][2]


# --- E501: endif with no open if ---------------------------------------------


def test_stray_endif_is_e501():
    body = "wait cmd /c echo a\nendif"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E501"]
    assert issues[0][0] == 2


# --- E502: unclosed prefetch block --------------------------------------------


def test_unclosed_prefetch_block_is_e502():
    body = "begin prefetch block\nadd prefetch item name=x sha1=1 size=1 url=http://x/y"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E502"]
    assert issues[0][0] == 1


# --- E503: stray end prefetch block -------------------------------------------


def test_stray_end_prefetch_block_is_e503():
    body = "wait cmd /c echo a\nend prefetch block"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E503"]
    assert issues[0][0] == 2


# --- E504: nested prefetch blocks ---------------------------------------------


def test_nested_prefetch_block_is_e504():
    body = (
        "begin prefetch block\n"
        "begin prefetch block\n"
        "end prefetch block\n"
        "end prefetch block"
    )
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E504"]
    assert issues[0][0] == 2


# --- E505: else/elseif outside any if -----------------------------------------


def test_else_outside_if_is_e505():
    body = "wait cmd /c echo a\nelse\nwait cmd /c echo b"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E505"]
    assert issues[0][0] == 2


def test_elseif_outside_if_is_e505():
    body = "wait cmd /c echo a\nelseif {true}\nwait cmd /c echo b"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E505"]
    assert issues[0][0] == 2


# --- E506: elseif after else, or a second else --------------------------------


def test_elseif_after_else_is_e506():
    body = (
        "if {true}\n"
        "wait cmd /c echo a\n"
        "else\n"
        "wait cmd /c echo b\n"
        "elseif {true}\n"
        "wait cmd /c echo c\n"
        "endif"
    )
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E506"]
    assert issues[0][0] == 5


def test_second_else_is_e506():
    body = (
        "if {true}\n"
        "wait cmd /c echo a\n"
        "else\n"
        "wait cmd /c echo b\n"
        "else\n"
        "wait cmd /c echo c\n"
        "endif"
    )
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E506"]
    assert issues[0][0] == 5


# --- E507: if left open across a prefetch block boundary ----------------------


def test_if_open_at_end_prefetch_block_is_e507():
    body = (
        "begin prefetch block\n"
        "if {true}\n"
        "add prefetch item name=x sha1=1 size=1 url=http://x/y\n"
        "end prefetch block\n"
        "endif"
    )
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E507"]
    assert issues[0][0] == 4


# --- createfile heredocs are masked, not scanned ------------------------------


def test_if_inside_createfile_block_is_ignored():
    body = (
        "createfile until END_OF_FILE\n"
        "if this is file content, not actionscript\n"
        "END_OF_FILE\n"
        "wait cmd /c echo a"
    )
    assert validator.check_actionscript(body) == []


def test_e302_is_not_reported_here():
    """A never-closed createfile block is the schclass hook's E302, not ours."""
    body = "createfile until END_OF_FILE\nif not really actionscript"
    assert validator.check_actionscript(body) == []


# --- BES XML extraction -------------------------------------------------------


def test_linenos_map_back_to_the_file(tmp_path):
    issues = issues_for(tmp_path, bes("wait cmd /c echo a\nendif"))
    assert codes(issues) == ["E501"]
    assert issues[0][0] == 8  # the second line of the generated ActionScript body


def test_second_task_lineno_maps_correctly(tmp_path):
    content = bes(
        [
            ("wait cmd /c echo ok", WINDOWS_SHELL),
            ("wait cmd /c echo a\nendif", WINDOWS_SHELL),
        ]
    )
    issues = issues_for(tmp_path, content)
    assert codes(issues) == ["E501"]
    assert issues[0][0] == 11


def test_non_actionscript_mimetypes_are_skipped(tmp_path):
    bad = "wait cmd /c echo a\nendif"
    content = bes([(bad, "application/x-sh"), (bad, "text/x-uri")])
    assert issues_for(tmp_path, content) == []


def test_missing_mimetype_is_actionscript(tmp_path):
    content = bes([("wait cmd /c echo a\nendif", None)])
    assert codes(issues_for(tmp_path, content)) == ["E501"]


def test_mimetype_is_matched_case_insensitively(tmp_path):
    content = bes([("wait cmd /c echo a\nendif", WINDOWS_SHELL.upper())])
    assert codes(issues_for(tmp_path, content)) == ["E501"]


def test_unparsable_xml_is_w500(tmp_path):
    issues = issues_for(tmp_path, "<BES><Task></BES>")
    assert codes(issues) == ["W500"]


def test_missing_file_is_w500(tmp_path):
    issues, fixed = validator.check_file(str(tmp_path / "nope.bes"))
    assert codes(issues) == ["W500"]
    assert fixed == []


def test_raw_actionscript_file_is_checked(tmp_path):
    path = write(tmp_path, "script.txt", "wait cmd /c echo a\nendif")
    issues, fixed = validator.check_file(path)
    assert codes(issues) == ["E501"]
    assert fixed == []


# --- opt-outs ------------------------------------------------------------------


def test_skip_marker_disables_the_whole_file(tmp_path):
    content = bes("wait cmd /c echo a\nendif", marker=validator.SKIP_MARKER)
    assert issues_for(tmp_path, content) == []


def test_if_marker_opts_out_of_if_checks(tmp_path):
    content = bes("wait cmd /c echo a\nendif", marker=validator.IF_MARKER)
    assert issues_for(tmp_path, content) == []


def test_prefetch_block_marker_opts_out_of_block_checks(tmp_path):
    content = bes(
        "begin prefetch block\nend prefetch block\nend prefetch block",
        marker=validator.PREFETCH_BLOCK_MARKER,
    )
    assert issues_for(tmp_path, content) == []


def test_disable_skips_a_code(tmp_path):
    content = bes("wait cmd /c echo a\nendif")
    assert issues_for(tmp_path, content, disabled={"E501"}) == []


def test_mustache_templates_are_skipped(tmp_path):
    content = bes("if {{ name }}\nwait cmd /c echo a")
    assert issues_for(tmp_path, content) == []


# --- main() ----------------------------------------------------------------


def test_main_passes_a_valid_file(tmp_path, capsys):
    path = write(tmp_path, "ok.bes", bes("wait cmd /c echo a"))
    assert validator.main([path]) == 0
    assert capsys.readouterr().out == ""


def test_main_fails_on_an_error(tmp_path, capsys):
    path = write(tmp_path, "bad.bes", bes("wait cmd /c echo a\nendif"))
    assert validator.main([path]) == 1
    assert "[E501]" in capsys.readouterr().out


def test_main_warning_only_fails_under_strict(tmp_path, capsys):
    path = write(tmp_path, "warn.bes", "<BES><Task></BES>")
    assert validator.main([path]) == 0
    assert "[W500]" in capsys.readouterr().out
    assert validator.main(["--strict", path]) == 1


def test_main_reports_unknown_disable_codes(tmp_path, capsys):
    path = write(tmp_path, "ok.bes", bes("wait cmd /c echo a"))
    assert validator.main(["--disable", "E999", path]) == 0
    assert "unknown --disable code" in capsys.readouterr().out


def test_main_discovers_bes_files(tmp_path, monkeypatch):
    write(tmp_path, "bad.bes", bes("wait cmd /c echo a\nendif"))
    monkeypatch.chdir(tmp_path)
    assert validator.main([]) == 1
