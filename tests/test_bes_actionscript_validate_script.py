#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_actionscript_validate_script.py.

These exercise the if/endif and begin/end prefetch block balance walk
(E500-E507), the per-line {...} relevance-substitution brace balance
(E508, E509), prefetch placement (E510, E511, E515), download-name
consistency (E512, E513), if-condition shape (E514), unreachable code
(W501), action-parameter-query placement (W502), the lxml-based extraction of every <ActionScript> from BES XML
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


# --- E508 / E509: {...} relevance substitution brace balance ------------------


def test_balanced_substitution_reports_nothing():
    body = "wait cmd /c echo {name of operating system} {now}"
    assert validator.check_actionscript(body) == []


def test_unclosed_substitution_is_e508():
    body = "wait cmd /c echo ok\nwait cmd /c echo {name of operating system"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E508"]
    assert issues[0][0] == 2
    assert validator.SUBSTITUTION_MARKER in issues[0][2]


def test_substitution_may_not_span_lines():
    """The closing } on the next line does not close the previous line's {."""
    body = "wait cmd /c echo {name of\noperating system}"
    assert codes(validator.check_actionscript(body)) == ["E508", "E509"]


def test_stray_close_brace_is_e509():
    body = "wait cmd /c echo }"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E509"]
    assert issues[0][0] == 1
    assert validator.SUBSTITUTION_MARKER in issues[0][2]


def test_double_open_brace_is_an_escape_not_a_substitution():
    """`{{` passes a literal { through, so it opens nothing."""
    assert validator.check_actionscript("wait cmd /c echo {{") == []


def test_close_brace_after_an_escape_pairs_with_it():
    """The } after a {{ closes out the escaped literal, not a substitution."""
    assert validator.check_actionscript("wait cmd /c echo {{literal}") == []
    assert validator.check_actionscript("wait cmd /c echo {{literal}}") == []


def test_escape_then_real_substitution_still_balances():
    body = "wait cmd /c echo {{ {name of operating system} }}"
    assert validator.check_actionscript(body) == []


def test_substitution_column_is_reported_from_the_raw_line():
    issues = validator.check_actionscript("    wait cmd /c echo {x")
    assert "column 22" in issues[0][2]


def test_braces_in_a_comment_line_are_ignored():
    assert validator.check_actionscript("// see {name of operating system") == []


def test_braces_inside_createfile_block_are_ignored():
    body = (
        "createfile until END_OF_FILE\n"
        "some } file { content\n"
        "END_OF_FILE\n"
        "wait cmd /c echo a"
    )
    assert validator.check_actionscript(body) == []


def test_substitution_opt_out_marker_silences_e508(tmp_path):
    content = bes("wait cmd /c echo {x", marker=validator.SUBSTITUTION_MARKER)
    assert issues_for(tmp_path, content) == []


def test_disable_e509_silences_it(tmp_path):
    issues = issues_for(tmp_path, bes("wait cmd /c echo }"), disabled={"E509"})
    assert issues == []


# --- prefetch line-shape constants stay in lockstep with the prefetch hook ----


def test_prefetch_prefix_constants_match_the_prefetch_hook():
    """Duplicated (not imported) to avoid the bigfix_prefetch dependency."""
    from pre_commit_bigfix import bes_actionscript_validate_prefetch as prefetch

    assert validator.NOHASH_PREFETCH == prefetch.NOHASH_PREFETCH
    assert validator.BLOCK_PREFETCH == prefetch.BLOCK_PREFETCH
    assert validator.STATEMENT_PREFETCH == prefetch.STATEMENT_PREFETCH


# --- E510 / E511: prefetch-block-only commands outside a block ----------------


def test_add_prefetch_item_outside_block_is_e510():
    body = "add prefetch item name=x sha1=1 size=1 url=http://x/y"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E510"]
    assert validator.PREFETCH_PLACEMENT_MARKER in issues[0][2]


def test_add_nohash_prefetch_item_outside_block_is_e510():
    body = "add nohash prefetch item name=x url=http://x/y"
    assert codes(validator.check_actionscript(body)) == ["E510"]


def test_collect_prefetch_items_outside_block_is_e511():
    issues = validator.check_actionscript("collect prefetch items")
    assert codes(issues) == ["E511"]
    assert validator.PREFETCH_PLACEMENT_MARKER in issues[0][2]


def test_block_commands_inside_a_block_report_nothing():
    body = (
        "begin prefetch block\n"
        "add prefetch item name=a.exe sha1=1 size=1 url=http://x/a.exe\n"
        "collect prefetch items\n"
        "end prefetch block\n"
        "wait __Download\\a.exe"
    )
    assert validator.check_actionscript(body) == []


# --- E512: duplicate download names --------------------------------------------


def test_duplicate_prefetch_name_is_e512():
    body = (
        "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
        "prefetch a.exe sha1:y size:1 http://x/b.exe\n"
        "wait __Download\\a.exe"
    )
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E512"]
    assert issues[0][0] == 2
    assert validator.DOWNLOAD_MARKER in issues[0][2]


def test_duplicate_name_across_producer_kinds_is_e512():
    """A block item and a `download as` with the same name still collide."""
    body = (
        "begin prefetch block\n"
        "add prefetch item name=a.exe sha1=1 size=1 url=http://x/a.exe\n"
        "end prefetch block\n"
        "download now as a.exe http://x/other.exe\n"
        "wait __Download\\a.exe"
    )
    assert codes(validator.check_actionscript(body)) == ["E512"]


def test_duplicate_names_compare_case_insensitively():
    body = (
        "prefetch A.EXE sha1:x size:1 http://x/a.exe\n"
        "prefetch a.exe sha1:y size:1 http://x/b.exe\n"
        "wait __Download\\a.exe"
    )
    assert codes(validator.check_actionscript(body)) == ["E512"]


# --- E513: __Download reference with no producer -------------------------------


def test_download_reference_with_no_producer_is_e513():
    body = "prefetch a.exe sha1:x size:1 http://x/a.exe\nwait __Download\\b.exe"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E513"]
    assert issues[0][0] == 2
    assert validator.DOWNLOAD_MARKER in issues[0][2]


def test_download_reference_matches_case_insensitively():
    body = "prefetch A.exe sha1:x size:1 http://x/a.exe\nwait __download/a.EXE"
    assert validator.check_actionscript(body) == []


def test_literal_download_url_basename_counts_as_a_producer():
    body = "download http://x/y.exe\nwait __Download\\y.exe"
    assert validator.check_actionscript(body) == []


def test_download_as_counts_as_a_producer():
    body = "download now as z.exe http://x/y.exe\nwait __Download\\z.exe"
    assert validator.check_actionscript(body) == []


def test_extract_present_suppresses_e513():
    """An archive's contents are unknowable, so no consumer can be judged."""
    body = (
        "prefetch a.zip sha1:x size:1 http://x/a.zip\n"
        "extract a.zip\n"
        "wait __Download\\inside.exe"
    )
    assert validator.check_actionscript(body) == []


def test_substituted_producer_name_suppresses_e513():
    body = (
        'prefetch {parameter "n"} sha1:x size:1 http://x/a.exe\n'
        "wait __Download\\b.exe"
    )
    assert validator.check_actionscript(body) == []


def test_substituted_consumer_name_is_not_judged():
    body = (
        "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
        'wait __Download\\{parameter "n"}\n'
        "wait __Download\\a.exe"
    )
    assert validator.check_actionscript(body) == []


# --- E514: if/elseif condition must be a substitution ---------------------------


def test_if_without_substitution_condition_is_e514():
    issues = validator.check_actionscript("if true\nendif")
    assert codes(issues) == ["E514"]
    assert issues[0][0] == 1
    assert validator.IF_MARKER in issues[0][2]


def test_bare_if_is_e514():
    assert codes(validator.check_actionscript("if\nendif")) == ["E514"]


def test_elseif_without_substitution_condition_is_e514():
    body = "if {true}\nelseif true\nendif"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E514"]
    assert issues[0][0] == 2


def test_if_with_substitution_and_no_space_is_fine():
    assert validator.check_actionscript("if{true}\nendif") == []


# --- E515: prefetch block must be at the top ------------------------------------


def test_prefetch_block_after_a_command_is_e515():
    body = "wait cmd /c echo a\nbegin prefetch block\nend prefetch block"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E515"]
    assert issues[0][0] == 2
    assert validator.PREFETCH_PLACEMENT_MARKER in issues[0][2]


def test_preamble_lines_before_prefetch_block_are_fine():
    body = (
        "// header comment\n"
        "\n"
        'action parameter query "q" with description "d"\n'
        'parameter "a" = "b"\n'
        "begin prefetch block\n"
        "add prefetch item name=a.exe sha1=1 size=1 url=http://x/a.exe\n"
        "end prefetch block\n"
        "wait __Download\\a.exe"
    )
    assert validator.check_actionscript(body) == []


def test_second_prefetch_block_is_e515_not_e504():
    """Sequential (not nested) second block: not at the top, so E515."""
    body = (
        "begin prefetch block\n"
        "end prefetch block\n"
        "begin prefetch block\n"
        "end prefetch block"
    )
    assert codes(validator.check_actionscript(body)) == ["E515"]


def test_nested_prefetch_block_is_e504_only():
    body = "begin prefetch block\nbegin prefetch block\nend prefetch block"
    assert codes(validator.check_actionscript(body)) == ["E502", "E504"]


# --- W501: unreachable code after exit/restart/shutdown -------------------------


def test_command_after_unconditional_exit_is_w501():
    issues = validator.check_actionscript("exit 0\nwait a\nwait b")
    assert codes(issues) == ["W501"]  # first dead line only
    assert issues[0][0] == 2
    assert validator.UNREACHABLE_MARKER in issues[0][2]


def test_command_after_restart_is_w501():
    assert codes(validator.check_actionscript("restart 60\nwait a")) == ["W501"]


def test_exit_inside_an_if_is_conditional_and_fine():
    body = "if {true}\nexit 0\nendif\nwait a"
    assert validator.check_actionscript(body) == []


def test_comment_after_exit_is_fine():
    assert validator.check_actionscript("exit 0\n// done") == []


# --- W502: action parameter query after execution began -------------------------


def test_parameter_query_after_a_command_is_w502():
    body = 'wait cmd /c echo a\naction parameter query "q" with description "d"'
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["W502"]
    assert issues[0][0] == 2
    assert validator.PARAMETER_QUERY_MARKER in issues[0][2]


def test_parameter_query_at_the_top_is_fine():
    body = 'action parameter query "q" with description "d"\nwait cmd /c echo a'
    assert validator.check_actionscript(body) == []


def test_parameter_query_after_only_declarations_is_fine():
    """Prefetch/parameter/if lines do not count as execution having begun."""
    body = (
        "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
        'parameter "a" = "b"\n'
        'action parameter query "q" with description "d"\n'
        "wait __Download\\a.exe"
    )
    assert validator.check_actionscript(body) == []


# --- new-check opt-outs and --disable -------------------------------------------


def test_prefetch_placement_marker_silences_e510(tmp_path):
    content = bes(
        "add prefetch item name=x sha1=1 size=1 url=http://x/y",
        marker=validator.PREFETCH_PLACEMENT_MARKER,
    )
    assert issues_for(tmp_path, content) == []


def test_download_marker_silences_e513(tmp_path):
    content = bes(
        "prefetch a.exe sha1:x size:1 http://x/a.exe\nwait __Download\\b.exe",
        marker=validator.DOWNLOAD_MARKER,
    )
    assert issues_for(tmp_path, content) == []


def test_if_marker_silences_e514(tmp_path):
    content = bes("if true\nendif", marker=validator.IF_MARKER)
    assert issues_for(tmp_path, content) == []


def test_disable_w501_silences_it(tmp_path):
    issues = issues_for(tmp_path, bes("exit 0\nwait a"), disabled={"W501"})
    assert issues == []


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
