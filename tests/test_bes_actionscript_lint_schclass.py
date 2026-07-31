#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_actionscript_lint_schclass.py.

These exercise the ActionScript line linting (E300-E302, W301-W302), the
lxml-based extraction of every <ActionScript> from BES XML (entity decoding,
merged CDATA sections, sourceline-accurate linenos, MIMEType gating), raw
non-.bes file linting, the skip/opt-out markers, --disable, W300 on
unparsable XML, the mustache-template skip, and main()'s exit codes.
"""

from pre_commit_bigfix import bes_actionscript_lint_schclass as linter

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


def issues_for(tmp_path, content, name="x.bes", disabled=frozenset()):
    """Return the issue list for `content` written to a file."""
    path = write(tmp_path, name, content)
    issues, fixed = linter.check_file(path, disabled=disabled)
    assert fixed == []
    return issues


def codes(tmp_path, content, name="x.bes", disabled=frozenset()):
    """Return the sorted set of check codes flagged for `content`."""
    return sorted({item[1] for item in issues_for(tmp_path, content, name, disabled)})


# --- the pure lint core -----------------------------------------------------


GOOD_BODY = """
// a comment line
parameter "src" = "http://example.com/f.exe"
prefetch f.exe sha1:da39a3ee5e6b4b0d3255bfef95601890afd80709 size:1 http://example.com/f.exe
begin prefetch block
    add prefetch item name=f.exe sha1=da39a3ee5e6b4b0d3255bfef95601890afd80709 size=1 url=http://example.com/f.exe
    add nohash prefetch item url=https://example.com/g.exe
    collect prefetch items
end prefetch block
if {name of operating system as lowercase starts with "win"}
    waithidden __Download\\f.exe /S
elseif {exists folder "/tmp"}
    wait /bin/sh -c "echo hi"
else
    run notepad.exe
endif
action parameter query "restart" with description "Restart now?"
delete __createfile
createfile until _EOF_
this heredoc is { not " actionscript // at all
badverb inside heredoc is fine
_EOF_
move __createfile "C:\\out.cmd"
setting "x"="1" on "{parameter "action issue date" of action}" for client
setting delete "x" on "{now}" for client
download http://example.com/legacy.exe
download as f.exe https://example.com/f.exe
download now as g.exe http://example.com/g.exe
surrender device id
action uses wow64 redirection {not x64 of operating system}
{if exists true whose (if true then (exists folder "/x") else false) else nothing}run x{endif}
continue if {exists folder "/tmp"}
"""


def test_good_body_is_clean():
    assert linter.lint_actionscript(GOOD_BODY) == []


def test_blank_and_comment_only_body_is_clean():
    assert linter.lint_actionscript("\n\n// just a comment\n\n") == []


def test_unknown_verb_e300():
    issues = linter.lint_actionscript("run x\nbadverb y\n")
    assert [(lineno, code) for lineno, code, _msg in issues] == [(2, "E300")]
    assert "badverb" in issues[0][2]


def test_e300_line_starting_with_string():
    issues = linter.lint_actionscript('"quoted" is not a verb\n')
    assert issues[0][1] == "E300"


def test_uppercase_verb_w302_not_e300():
    issues = linter.lint_actionscript("RUN x\n")
    assert [(lineno, code) for lineno, code, _msg in issues] == [(1, "W302")]
    assert "run" in issues[0][2]


def test_lowercase_mixed_verbs_no_w302():
    assert linter.lint_actionscript("run x\nwaithidden y\n") == []


def test_override_block_options_are_clean():
    body = (
        "override wait\n"
        "hidden=true\n"
        "completion=job\n"
        "runas=currentuser\n"
        "timeout_seconds=300\n"
        "disposition=terminate\n"
        'wait cmd /C echo "hello"\n'
        "override run\n"
        "priority=low\n"
        "detached=true\n"
        "run cmd /C echo "
        '"hello"\n'
    )
    assert linter.lint_actionscript(body) == []


def test_override_option_wrong_case_w302_not_e300():
    issues = linter.lint_actionscript("override wait\nRunAs=currentuser\nwait x\n")
    assert [(lineno, code) for lineno, code, _msg in issues] == [(2, "W302")]
    assert "runas" in issues[0][2]


def test_override_option_without_equals_is_still_e300():
    # a bare option word is not a command; only `option=value` is recognized
    issues = linter.lint_actionscript("override wait\nhidden\nwait x\n")
    assert [(lineno, code) for lineno, code, _msg in issues] == [(2, "E300")]


def test_unknown_override_option_is_e300():
    issues = linter.lint_actionscript("override wait\nbogus_option=true\nwait x\n")
    assert [(lineno, code) for lineno, code, _msg in issues] == [(2, "E300")]


def test_uppercase_word_mid_line_is_not_w302():
    # only the line-opening verb is case-checked; arguments are free text
    assert linter.lint_actionscript("wait setup.exe /VERYSILENT RESTART=0\n") == []


def test_unterminated_substitution_e301():
    issues = linter.lint_actionscript("run {pathname of client folder\n")
    assert [(lineno, code) for lineno, code, _msg in issues] == [(1, "E301")]


def test_closed_substitution_ok():
    assert linter.lint_actionscript("run {pathname of client folder}\\x.exe\n") == []


def test_substitution_continued_with_backslash_newline_ok():
    body = 'run {pathname of client folder \\\n & "x"}\n'
    assert linter.lint_actionscript(body) == []
    # ...and the continuation line itself is not an E300


def test_substitution_at_line_start_ok():
    assert linter.lint_actionscript('{parameter "x" of action}\n') == []


def test_unterminated_string_w301():
    issues = linter.lint_actionscript('run "abc\n')
    assert [(lineno, code) for lineno, code, _msg in issues] == [(1, "W301")]


def test_heredoc_masks_content():
    body = 'createfile until EOF\n{garbage " // not actionscript\nEOF\nrun x\n'
    assert linter.lint_actionscript(body) == []


def test_heredoc_unterminated_e302():
    body = "createfile until EOF\nsome content\n"
    issues = linter.lint_actionscript(body)
    assert [(lineno, code) for lineno, code, _msg in issues] == [(1, "E302")]


def test_heredoc_indented_marker_does_not_terminate():
    body = "createfile until EOF\n  EOF\nEOF\nbadverb x\n"
    issues = linter.lint_actionscript(body)
    # line 2 is masked (indented marker does not close), line 3 closes,
    # line 4 resumes linting and is a bad verb
    assert [(lineno, code) for lineno, code, _msg in issues] == [(4, "E300")]


def test_lint_resumes_after_heredoc_with_correct_lineno():
    body = "createfile until _END_\nraw stuff\n_END_\nbadverb y\nrun x\n"
    issues = linter.lint_actionscript(body)
    assert [(lineno, code) for lineno, code, _msg in issues] == [(4, "E300")]


def test_indented_verbs_ok():
    assert linter.lint_actionscript("if {true}\n\trun x\n endif\n") == []


# --- extraction from BES XML -------------------------------------------------


def test_good_bes_file_is_clean(tmp_path):
    assert codes(tmp_path, bes("\nrun x\nwait y\n")) == []


def test_bad_verb_in_bes_has_file_lineno(tmp_path):
    content = bes("\nrun x\nbadverb y\n")
    issues = issues_for(tmp_path, content)
    assert [(code, "badverb" in msg) for _l, code, msg in issues] == [("E300", True)]
    # the ActionScript open tag is on file line 7; body local line 3 -> file 9
    lineno = issues[0][0]
    lines = content.split("\n")
    assert lines[lineno - 1] == "badverb y"


def test_all_actionscripts_are_linted(tmp_path):
    content = bes(
        [
            ("\nbadverb one\n", WINDOWS_SHELL),
            ("\nbadverb two\n", WINDOWS_SHELL),
        ]
    )
    issues = issues_for(tmp_path, content)
    assert [code for _l, code, _m in issues] == ["E300", "E300"]
    lines = content.split("\n")
    assert lines[issues[0][0] - 1] == "badverb one"
    assert lines[issues[1][0] - 1] == "badverb two"


def test_non_actionscript_mimetypes_are_skipped(tmp_path):
    shell = "#!/bin/sh\necho hi\nls -la\n"
    for mimetype in (
        "application/x-sh",
        "application/x-AppleScript",
        "application/x-Fixlet-Windows-PowerShell",
        "text/x-uri",
    ):
        assert codes(tmp_path, bes([(shell, mimetype)])) == []


def test_missing_mimetype_is_linted(tmp_path):
    assert codes(tmp_path, bes([("\nbadverb x\n", None)])) == ["E300"]


def test_entity_escaped_body_is_decoded_before_linting(tmp_path):
    # not CDATA: entities must decode to the real ActionScript text
    content = bes("placeholder").replace(
        "<![CDATA[placeholder]]>",
        "\nif {name of operating system as lowercase starts with &quot;win&quot;}"
        "\nrun x\nendif\n",
    )
    assert codes(tmp_path, content) == []


def test_multiple_cdata_sections_merge(tmp_path):
    content = bes("placeholder").replace(
        "<![CDATA[placeholder]]>",
        "<![CDATA[\nrun x]]><![CDATA[\nwait y\n]]>",
    )
    assert codes(tmp_path, content) == []


def test_unparsable_xml_w300(tmp_path):
    issues = issues_for(tmp_path, "<BES><Task>not closed\n")
    assert [code for _l, code, _m in issues] == ["W300"]


def test_mustache_template_skipped(tmp_path):
    content = bes("\nbadverb {{template_var}}\n")
    assert codes(tmp_path, content) == []


# --- raw (non-.bes) files ----------------------------------------------------


def test_raw_actionscript_file(tmp_path):
    issues = issues_for(tmp_path, "run x\nbadverb y\n", name="script.actionscript")
    assert [(lineno, code) for lineno, code, _m in issues] == [(2, "E300")]


def test_raw_actionscript_clean(tmp_path):
    assert codes(tmp_path, "run x\n// done\n", name="script.actionscript") == []


# --- markers / disable -------------------------------------------------------


def test_file_skip_marker(tmp_path):
    content = bes("\nbadverb x\n", marker=linter.SKIP_MARKER)
    assert codes(tmp_path, content) == []


def test_verb_marker_suppresses_e300(tmp_path):
    content = bes("\nbadverb x\n", marker="actionscript-verb-ok")
    assert codes(tmp_path, content) == []


def test_case_marker_suppresses_w302(tmp_path):
    content = bes("\nRUN x\n", marker="actionscript-case-ok")
    assert codes(tmp_path, content) == []


def test_disable_e300(tmp_path):
    content = bes("\nbadverb x\n")
    assert codes(tmp_path, content, disabled={"E300"}) == []


def test_markers_do_not_hide_other_codes(tmp_path):
    content = bes("\nbadverb x\nrun {oops\n", marker="actionscript-verb-ok")
    assert codes(tmp_path, content) == ["E301"]


# --- main() ------------------------------------------------------------------


def test_main_exit_1_on_e300(tmp_path, capsys):
    path = write(tmp_path, "x.bes", bes("\nbadverb x\n"))
    assert linter.main([path]) == 1
    assert "E300" in capsys.readouterr().out


def test_main_exit_0_on_clean(tmp_path):
    path = write(tmp_path, "x.bes", bes("\nrun x\n"))
    assert linter.main([path]) == 0


def test_main_warning_only_exit_0(tmp_path, capsys):
    path = write(tmp_path, "x.bes", bes("\nRUN x\n"))
    assert linter.main([path]) == 0
    assert "W302" in capsys.readouterr().out


def test_main_warning_strict_exit_1(tmp_path):
    path = write(tmp_path, "x.bes", bes("\nRUN x\n"))
    assert linter.main(["--strict", path]) == 1


def test_main_disable_flag(tmp_path):
    path = write(tmp_path, "x.bes", bes("\nbadverb x\n"))
    assert linter.main(["--disable", "E300", path]) == 0


def test_main_unknown_disable_warns(tmp_path, capsys):
    path = write(tmp_path, "x.bes", bes("\nrun x\n"))
    assert linter.main(["--disable", "E999", path]) == 0
    assert "E999" in capsys.readouterr().out


def test_repo_example_files_lint_clean():
    issues, fixed = linter.check_file("tests/examples/example-test.bes")
    assert fixed == []
    assert [code for _l, code, _m in issues if code.startswith("E")] == []
