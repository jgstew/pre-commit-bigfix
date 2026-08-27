#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_actionscript_validate_script.py.

These exercise the if/endif and begin/end prefetch block balance walk
(E500-E507), the per-line {...} relevance-substitution brace balance
(E508, E509), prefetch placement (E510, E511, E515), download-name
consistency (E512, E513), if-condition shape (E514), duplicate/out-of-order
parameter assignment (E516, E517), continue-if/pause-while condition shape
(E518), __createfile/__appendfile production (E519), unreachable code
(W501), action-parameter-query placement (W502), wrong-case scratch-file
references (W503), setting/regset line shape (E520, E521), the deprecated
`dos` verb (W504), override wait/run block termination (E522), the
lxml-based extraction of every <ActionScript> from BES XML
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
    """Return the issue list for `content` written to a file.

    `auto_fix` defaults to False in `check_file`, so nothing is rewritten
    here unless a test opts in via `**kwargs`.
    """
    path = write(tmp_path, name, content)
    issues, fixed = validator.check_file(path, disabled=disabled, **kwargs)
    assert fixed == []
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


def test_appendfile_literal_close_brace_is_not_e509():
    """`appendfile }` appends a literal `}` to the file -- it is one line of
    raw file content, not a stray relevance-substitution close.
    """
    body = (
        "appendfile \t\t/bin/rm -fr $TMPDIR\n"
        "appendfile }\n"
        'appendfile CLIENTDIRS="/var/opt/BESClient"'
    )
    assert validator.check_actionscript(body) == []


def test_appendfile_literal_open_brace_is_not_e508():
    body = "appendfile {\nappendfile }"
    assert validator.check_actionscript(body) == []


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


def test_double_close_brace_inside_a_substitution_is_an_escape():
    """A PowerShell hashtable literal quoted inside a substitution: the
    `}}` closing it is a literal `}`, not the substitution's real close.
    """
    body = (
        'parameter "ArgHeader" = "{ if (windows of operating system) then '
        '"@{\'k\'=\'v\'}}" else "Metadata:true" }"'
    )
    assert validator.check_actionscript(body) == []


def test_double_close_brace_inside_a_substitution_still_leaves_it_open():
    """The escape absorbs one `}}`; a still-missing real close is E508."""
    issues = validator.check_actionscript("wait echo {a}}b")
    assert codes(issues) == ["E508"]


def test_real_close_follows_an_escaped_close_inside_a_substitution():
    issues = validator.check_actionscript("wait echo {a}}b}")
    assert issues == []


def test_regex_quantifier_braces_inside_a_substitution_are_not_e509():
    """`{40}` etc is a regex interval quantifier, not a substitution close --
    it must not prematurely close the substitution and orphan the real one.
    """
    body = (
        "wait cmd /c echo {(if (true) then (parenthesized part 3 of first "
        'match (case insensitive regex "sha1(=|:)(\\S{40})( |\\b)") of it) '
        'else "")}'
    )
    assert validator.check_actionscript(body) == []


def test_regex_quantifier_with_range_is_not_e509():
    body = 'wait cmd /c echo {(regex "\\d{1,3}") of it}'
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


def test_mustache_pattern_matches_every_hook():
    """All four hooks must agree on what counts as an unrendered template."""
    from pre_commit_bigfix import bes_actionscript_lint_schclass as schclass
    from pre_commit_bigfix import bes_actionscript_validate_prefetch as prefetch
    from pre_commit_bigfix import bes_conventions_check as conventions

    patterns = {
        validator.MUSTACHE_RE.pattern,
        schclass.MUSTACHE_RE.pattern,
        prefetch.MUSTACHE_RE.pattern,
        conventions.MUSTACHE_RE.pattern,
    }
    assert len(patterns) == 1

    # placeholders are templates; a literal-brace escape around content is not
    assert validator.MUSTACHE_RE.search("<Title>{{vendor}} {{model}}</Title>")
    assert validator.MUSTACHE_RE.search("delete {{ name }}.lnk")
    assert not validator.MUSTACHE_RE.search('{{\n  "key": "value"\n}}')
    assert not validator.MUSTACHE_RE.search("condition:\n{{\n  $re1 = /x/\n}}")


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


def test_duplicate_prefetch_name_with_matching_hash_is_not_e512():
    """Two mirror URLs for the identical file (same sha1/sha256/size) are
    not a real duplicate -- either satisfies the download.
    """
    body = (
        "prefetch a.exe sha1:x size:1 http://mirror-one/a.exe sha256:z\n"
        "prefetch a.exe sha1:x size:1 http://mirror-two/a.exe sha256:z\n"
        "wait __Download\\a.exe"
    )
    assert validator.check_actionscript(body) == []


def test_duplicate_prefetch_name_with_mismatched_hash_is_still_e512():
    """Matching name but a differing hash is a real duplicate, not mirrors."""
    body = (
        "prefetch a.exe sha1:x size:1 http://mirror-one/a.exe sha256:z\n"
        "prefetch a.exe sha1:x size:1 http://mirror-two/a.exe sha256:different\n"
        "wait __Download\\a.exe"
    )
    assert codes(validator.check_actionscript(body)) == ["E512"]


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


def test_same_name_in_separate_sibling_ifs_is_not_e512():
    """Real content guards each platform with its own `if`, not elseif."""
    body = (
        "if {windows of operating system}\n"
        "prefetch a.tar.gz sha1:x size:1 http://x/win.tar.gz\n"
        "endif\n"
        "if {mac of operating system}\n"
        "prefetch a.tar.gz sha1:y size:1 http://x/mac.tar.gz\n"
        "endif\n"
        "wait __Download\\a.tar.gz"
    )
    assert validator.check_actionscript(body) == []


def test_same_name_in_elseif_siblings_of_one_if_is_not_e512():
    body = (
        "if {windows of operating system}\n"
        "prefetch a.tar.gz sha1:x size:1 http://x/win.tar.gz\n"
        "elseif {mac of operating system}\n"
        "prefetch a.tar.gz sha1:y size:1 http://x/mac.tar.gz\n"
        "endif\n"
        "wait __Download\\a.tar.gz"
    )
    assert validator.check_actionscript(body) == []


def test_same_name_twice_in_the_same_branch_is_still_e512():
    """Same exact conditional path -- both run together -- a real bug."""
    body = (
        "if {true}\n"
        "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
        "prefetch a.exe sha1:y size:1 http://x/b.exe\n"
        "endif"
    )
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E512"]


def test_unconditional_duplicate_inside_and_outside_an_if_is_not_e512():
    """Conservative: a top-level dup masked by conditional nesting is missed
    on purpose -- unproven co-execution is preferred over a false alarm.
    """
    body = (
        "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
        "if {true}\n"
        "prefetch a.exe sha1:y size:1 http://x/b.exe\n"
        "endif"
    )
    assert validator.check_actionscript(body) == []


# --- E513: __Download reference with no producer -------------------------------


def test_download_reference_with_no_producer_is_e513():
    body = "prefetch a.exe sha1:x size:1 http://x/a.exe\nwait __Download\\b.exe"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E513"]
    assert issues[0][0] == 2
    assert validator.DOWNLOAD_MARKER in issues[0][2]


def test_download_reference_matches_case_insensitively():
    body = "prefetch A.exe sha1:x size:1 http://x/a.exe\nwait __Download/a.EXE"
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


def test_delete_of_a_download_is_cleanup_not_consumption():
    """`delete __Download\\x` before downloading x is normal hygiene."""
    body = (
        "delete __Download\\document\n"
        "folder delete __Download\\stage\n"
        "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
        "wait __Download\\a.exe"
    )
    assert validator.check_actionscript(body) == []


def test_unshaped_download_line_suppresses_e513():
    """A substituted URL contains a space, matching neither download shape."""
    body = (
        'parameter "u" = "http://169.254.169.254/latest/document"\n'
        'download now {parameter "u"}\n'
        "copy __Download/document /tmp/out.json"
    )
    assert validator.check_actionscript(body) == []


def test_substituted_consumer_name_is_not_judged():
    body = (
        "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
        'wait __Download\\{parameter "n"}\n'
        "wait __Download\\a.exe"
    )
    assert validator.check_actionscript(body) == []


def test_glob_wildcard_consumer_name_is_not_judged():
    """`mysql*rpm` matches a versioned filename by shell glob at runtime,
    not by a literal producer name -- no `prefetch`/`download` needed.
    """
    body = "waithidden rpm -Uvh __Download\\mysql*rpm __Download\\mysql*deb"
    assert validator.check_actionscript(body) == []


def test_glob_wildcard_consumer_does_not_disable_other_e513_checks():
    """The wildcard skip is per-reference, not a whole-body knowability
    escape hatch: an unrelated real typo two lines later still fires.
    """
    body = (
        "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
        "wait __Download\\mysql*rpm\n"
        "wait __Download\\b.exe"
    )
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E513"]
    assert "b.exe" in issues[0][2]


# --- E513: copy/move and shell-redirection producers ---------------------------


def test_copy_from_createfile_registers_the_destination():
    body = (
        "createfile until EOF\ncontent\nEOF\n"
        "copy __createfile __Download\\ResponseFile.txt\n"
        "wait __Download\\ResponseFile.txt"
    )
    assert validator.check_actionscript(body) == []


def test_move_from_createfile_registers_the_destination():
    body = (
        "createfile until EOF\ncontent\nEOF\n"
        "move __createfile __Download\\WUA_Search.vbs\n"
        "wait __Download\\WUA_Search.vbs"
    )
    assert validator.check_actionscript(body) == []


def test_move_from_createfile_with_substituted_destination_suppresses_e513():
    """`{download path "X"}` -- no literal __Download ref to read back."""
    body = (
        "createfile until EOF\ncontent\nEOF\n"
        'move __createfile "{ download path "WUA_Search.vbs" }"\n'
        "wait __Download\\anything.exe"
    )
    assert validator.check_actionscript(body) == []


def test_move_renaming_one_download_to_another_registers_the_new_name():
    body = (
        "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
        "move __Download\\a.exe __Download\\b.exe\n"
        "wait __Download\\b.exe"
    )
    assert validator.check_actionscript(body) == []


def test_move_of_an_undeclared_download_with_no_createfile_is_still_e513():
    """A single __Download ref with no __createfile source is a plain typo."""
    body = "move __Download\\typo.exe elsewhere"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E513"]


def test_redirection_into_download_registers_the_target():
    body = (
        "createfile until EOF\ncontent\nEOF\n"
        "move __createfile __Download\\WUA_Search.vbs\n"
        "waithidden cmd /c cscript __Download\\WUA_Search.vbs "
        "> __Download\\results_WindowsUpdates.ini\n"
        "move __Download\\results_WindowsUpdates.ini "
        '"C:\\out.ini"'
    )
    assert validator.check_actionscript(body) == []


def test_double_redirect_append_into_download_registers_the_target():
    body = "wait cmd /c echo hi >> __Download\\log.txt\n" "wait __Download\\log.txt"
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


# --- E516: duplicate parameter assignment ---------------------------------------


def test_duplicate_unconditional_parameter_assignment_is_e516():
    body = 'parameter "a" = "1"\nparameter "a" = "2"'
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E516"]
    assert issues[0][0] == 2
    assert validator.PARAMETER_MARKER in issues[0][2]


def test_parameter_assignment_in_separate_if_branches_is_fine():
    """Cross-platform content assigns the same parameter in separate ifs."""
    body = (
        "if {windows of operating system}\n"
        'parameter "path" = "C:\\x"\n'
        "endif\n"
        "if {mac of operating system}\n"
        'parameter "path" = "/tmp/x"\n'
        "endif"
    )
    assert validator.check_actionscript(body) == []


def test_parameter_assignment_in_same_if_elseif_branches_is_fine():
    body = (
        "if {true}\n" 'parameter "a" = "1"\n' "else\n" 'parameter "a" = "2"\n' "endif"
    )
    assert validator.check_actionscript(body) == []


def test_parameter_reassignment_in_same_branch_is_e516():
    body = "if {true}\n" 'parameter "a" = "1"\n' 'parameter "a" = "2"\n' "endif"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E516"]
    assert issues[0][0] == 3


def test_single_assignment_reports_nothing():
    body = 'parameter "a" = "1"\nwait cmd /c echo {parameter "a"}'
    assert validator.check_actionscript(body) == []


# --- E517: parameter referenced before its assignment ---------------------------


def test_parameter_referenced_before_assignment_is_e517():
    body = 'wait cmd /c echo {parameter "a"}\nparameter "a" = "1"'
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E517"]
    assert issues[0][0] == 1
    assert validator.PARAMETER_MARKER in issues[0][2]


def test_parameter_referenced_after_assignment_is_fine():
    body = 'parameter "a" = "1"\nwait cmd /c echo {parameter "a"}'
    assert validator.check_actionscript(body) == []


def test_parameter_never_assigned_in_script_is_not_flagged():
    """A secure parameter supplied from the Description page is invisible here."""
    body = 'wait cmd /c echo {parameter "secret" of action}'
    assert validator.check_actionscript(body) == []


# --- E518: continue if / pause while condition must be a substitution -----------


def test_continue_if_without_substitution_is_e518():
    body = "continue if somejunk"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E518"]
    assert validator.IF_MARKER in issues[0][2]


def test_continue_if_with_substitution_is_fine():
    body = 'continue if {exists file "x"}'
    assert validator.check_actionscript(body) == []


def test_continue_if_literal_false_is_fine():
    # a documented idiom for forcing a branch to fail unconditionally, e.g.
    # in the `else` of an `if`/`else`/`endif`
    body = "continue if false"
    assert validator.check_actionscript(body) == []


def test_continue_if_literal_false_any_case_is_fine():
    body = "continue if FALSE"
    assert validator.check_actionscript(body) == []


def test_continue_if_literal_true_is_still_e518():
    # unlike `false`, `true` always continues -- the check does nothing, so
    # it is not the documented idiom and is still flagged
    body = "continue if true"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E518"]


def test_pause_while_without_substitution_is_e518():
    body = "pause while somejunk"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E518"]


def test_pause_while_with_substitution_is_fine():
    body = 'pause while {exists process "x"}'
    assert validator.check_actionscript(body) == []


def test_pause_while_literal_true_is_e518():
    # `pause while true` never becomes false -- it hangs forever, so unlike
    # `continue if false` it is not treated as an intentional idiom
    body = "pause while true"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E518"]


def test_pause_while_literal_false_is_e518():
    # `pause while false` is already false, so the pause never happens --
    # also not treated as an intentional idiom
    body = "pause while false"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E518"]


# --- E519: __createfile / __appendfile referenced with no producer --------------


def test_createfile_reference_with_no_producer_is_e519():
    body = "move __createfile __Download\\x.txt"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E519"]
    assert validator.SCRATCH_MARKER in issues[0][2]


def test_createfile_reference_with_a_producer_is_fine():
    body = "createfile until EOF\ncontent\nEOF\nmove __createfile __Download\\x.txt"
    assert validator.check_actionscript(body) == []


def test_appendfile_reference_with_no_producer_is_e519():
    body = "wait cmd /c type __appendfile"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E519"]


def test_appendfile_reference_with_a_producer_is_fine():
    body = "appendfile line one\nwait cmd /c type __appendfile"
    assert validator.check_actionscript(body) == []


def test_deleting_createfile_with_no_producer_is_not_flagged():
    """Cleanup, not consumption -- the same exemption E513 uses."""
    body = "delete __createfile"
    assert validator.check_actionscript(body) == []


# --- W503: wrong-case __Download / __createfile / __appendfile reference --------


def test_lowercase_download_reference_is_w503():
    body = "prefetch a.exe sha1:x size:1 http://x/a.exe\nwait __download\\a.exe"
    issues = validator.check_actionscript(body)
    assert "W503" in codes(issues)
    assert (
        validator.SCRATCH_MARKER
        in [msg for _, code, msg in issues if code == "W503"][0]
    )


def test_lowercase_createfile_reference_is_w503():
    body = "createfile until EOF\ncontent\nEOF\nmove __CreateFile __Download\\x.txt"
    issues = validator.check_actionscript(body)
    assert "W503" in codes(issues)


def test_correct_case_scratch_references_are_fine():
    body = (
        "createfile until EOF\ncontent\nEOF\n"
        "move __createfile __Download\\x.txt\n"
        "wait __Download\\x.txt"
    )
    assert validator.check_actionscript(body) == []


# --- W503 auto-fix: rewrite wrong-case scratch references -----------------------


def test_fix_scratch_case_rewrites_wrong_case_reference():
    src = "prefetch a.exe sha1:x size:1 http://x/a.exe\nwait __download\\a.exe"
    new_src, fixed = validator.fix_scratch_case(src, [(2, "__download", "__Download")])
    assert (
        new_src == "prefetch a.exe sha1:x size:1 http://x/a.exe\nwait __Download\\a.exe"
    )
    assert [(lineno, code) for lineno, code, _msg in fixed] == [(2, "W503")]


def test_fix_scratch_case_skips_a_target_no_longer_on_its_line():
    """A stale/incorrect target is left alone rather than guessed at."""
    src = "wait cmd /c echo a"
    new_src, fixed = validator.fix_scratch_case(src, [(1, "__download", "__Download")])
    assert new_src == src
    assert fixed == []


def test_check_file_auto_fix_rewrites_raw_actionscript_file(tmp_path):
    path = write(
        tmp_path,
        "script.txt",
        "prefetch a.exe sha1:x size:1 http://x/a.exe\nwait __download\\a.exe",
    )
    issues, fixed = validator.check_file(path, auto_fix=True)
    assert issues == []  # the reference is canonical after the fix
    assert codes(fixed) == ["W503"]

    with open(path, "rb") as handle:
        rewritten = handle.read().decode("utf-8")
    assert "__Download\\a.exe" in rewritten
    assert "__download\\a.exe" not in rewritten


def test_check_file_auto_fix_rewrites_bes_cdata_in_place(tmp_path):
    content = bes("prefetch a.exe sha1:x size:1 http://x/a.exe\nwait __download\\a.exe")
    path = write(tmp_path, "x.bes", content)
    issues, fixed = validator.check_file(path, auto_fix=True)
    assert issues == []
    assert codes(fixed) == ["W503"]

    with open(path, "rb") as handle:
        rewritten = handle.read().decode("utf-8")
    assert "__Download\\a.exe" in rewritten
    assert "__download\\a.exe" not in rewritten
    # everything outside the ActionScript body is untouched
    assert "<Title>Example</Title>" in rewritten


def test_check_file_auto_fix_preserves_crlf(tmp_path):
    """`write()` always saves with CRLF endings; the fix must round-trip them."""
    path = write(
        tmp_path,
        "script.txt",
        "prefetch a.exe sha1:x size:1 http://x/a.exe\nwait __download\\a.exe",
    )
    _issues, fixed = validator.check_file(path, auto_fix=True)
    assert codes(fixed) == ["W503"]
    with open(path, "rb") as handle:
        rewritten = handle.read()
    assert (
        rewritten
        == b"prefetch a.exe sha1:x size:1 http://x/a.exe\r\nwait __Download\\a.exe"
    )


def test_check_file_auto_fix_off_by_default(tmp_path):
    path = write(tmp_path, "script.txt", "delete __download\\a.exe")
    issues, fixed = validator.check_file(path)
    assert fixed == []
    assert "W503" in codes(issues)


def test_check_file_auto_fix_respects_disabled(tmp_path):
    path = write(tmp_path, "script.txt", "delete __download\\a.exe")
    issues, fixed = validator.check_file(path, auto_fix=True, disabled={"W503"})
    assert fixed == []
    assert codes(issues) == []  # disabled, not fixed


def test_check_file_auto_fix_respects_scratch_marker(tmp_path):
    content = "// actionscript-scratch-ok\ndelete __download\\a.exe"
    path = write(tmp_path, "script.txt", content)
    issues, fixed = validator.check_file(path, auto_fix=True)
    assert fixed == []
    assert codes(issues) == []  # opted out, not fixed


def test_main_auto_fixes_by_default_when_files_are_given(tmp_path, capsys):
    path = write(tmp_path, "script.txt", "delete __download\\a.exe")
    assert validator.main([path]) == 1  # an auto-fix still fails the hook
    out = capsys.readouterr().out
    assert "[W503] auto-fixed" in out
    assert "auto-fixed 1 issue(s)" in out
    with open(path, "rb") as handle:
        assert b"__Download\\a.exe" in handle.read()


def test_main_auto_fix_no_leaves_the_file_alone(tmp_path, capsys):
    path = write(tmp_path, "script.txt", "delete __download\\a.exe")
    assert validator.main(["--auto-fix", "no", path]) == 0  # W503 is advisory
    out = capsys.readouterr().out
    assert "[W503] warning" in out
    with open(path, "rb") as handle:
        assert b"__download\\a.exe" in handle.read()


def test_main_does_not_auto_fix_when_discovering(tmp_path, monkeypatch):
    write(tmp_path, "script.bes", bes("delete __download\\a.exe"))
    monkeypatch.chdir(tmp_path)
    assert validator.main([]) == 0  # W503 is advisory and nothing was fixed
    with open(tmp_path / "script.bes", "rb") as handle:
        assert b"__download\\a.exe" in handle.read()


# --- E520: malformed setting line -------------------------------------------------


def test_setting_missing_on_clause_is_e520():
    body = 'setting "x"="1"'
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E520"]
    assert validator.COMMAND_SHAPE_MARKER in issues[0][2]


def test_well_formed_setting_line_is_fine():
    body = 'setting "x"="1" on "{parameter "action issue date" of action}" for client'
    assert validator.check_actionscript(body) == []


def test_well_formed_setting_delete_line_is_fine():
    body = (
        'setting delete "_WebUIAppEnv_CACHE_TTL" on '
        '"{parameter "action issue date"}" for client'
    )
    assert validator.check_actionscript(body) == []


def test_setting_delete_missing_on_clause_is_e520():
    body = 'setting delete "_WebUIAppEnv_CACHE_TTL"'
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E520"]


# --- E521: regset/regdelete key not bracketed -------------------------------------


def test_regset_unbracketed_key_is_e521():
    body = 'regset HKEY_LOCAL_MACHINE\\SOFTWARE\\x "v"="1"'
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E521"]
    assert validator.COMMAND_SHAPE_MARKER in issues[0][2]


def test_regset_bracketed_key_is_fine():
    body = 'regset "[HKEY_LOCAL_MACHINE\\SOFTWARE\\x]" "v"="1"'
    assert validator.check_actionscript(body) == []


def test_regset64_bracketed_key_is_fine():
    body = 'regset64 "[HKEY_LOCAL_MACHINE\\SOFTWARE\\x]" "v"="1"'
    assert validator.check_actionscript(body) == []


def test_regdelete_unbracketed_key_is_e521():
    body = "regdelete HKEY_LOCAL_MACHINE\\SOFTWARE\\x"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E521"]


# --- W504: deprecated dos verb -----------------------------------------------------


def test_dos_verb_is_w504():
    body = "dos cd C:\\x && npm install"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["W504"]
    assert validator.COMMAND_SHAPE_MARKER in issues[0][2]


def test_waithidden_cmd_is_not_w504():
    body = "waithidden cmd.exe /c echo hi"
    assert validator.check_actionscript(body) == []


# --- E523: action uses wow64 redirection argument shape ----------------------------


def test_wow64_redirection_with_a_substitution_is_fine():
    body = "action uses wow64 redirection {not x64 of operating system}"
    assert validator.check_actionscript(body) == []


def test_wow64_redirection_true_is_fine():
    assert validator.check_actionscript("action uses wow64 redirection true") == []


def test_wow64_redirection_mixed_case_false_is_fine():
    """The agent accepts any case, as it does for verbs."""
    assert validator.check_actionscript("action uses wow64 redirection False") == []


def test_wow64_redirection_with_a_bare_word_is_e523():
    body = "action uses wow64 redirection yes"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E523"]
    assert validator.COMMAND_SHAPE_MARKER in issues[0][2]


def test_wow64_redirection_with_no_argument_is_e523():
    assert codes(validator.check_actionscript("action uses wow64 redirection")) == [
        "E523"
    ]


def test_command_shape_marker_silences_e523(tmp_path):
    content = bes(
        "action uses wow64 redirection yes", marker=validator.COMMAND_SHAPE_MARKER
    )
    assert issues_for(tmp_path, content) == []


def test_disable_e523_silences_it(tmp_path):
    content = bes("action uses wow64 redirection yes")
    assert issues_for(tmp_path, content, disabled={"E523"}) == []


# --- W505: cmd.exe without /c, or with /k -----------------------------------------


def test_wait_cmd_without_a_switch_is_w505():
    body = "wait cmd.exe vs_setup.exe --nocache --wait"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["W505"]
    assert validator.CMD_MARKER in issues[0][2]


def test_waithidden_cmd_without_a_switch_is_w505():
    body = "waithidden cmd C:\\setup.exe /S"
    assert codes(validator.check_actionscript(body)) == ["W505"]


def test_run_cmd_without_a_switch_is_w505():
    body = "run cmd.exe install.bat"
    assert codes(validator.check_actionscript(body)) == ["W505"]


def test_quoted_cmd_path_without_a_switch_is_w505():
    body = 'wait "{windows folder}\\system32\\cmd.exe" install.bat'
    assert codes(validator.check_actionscript(body)) == ["W505"]


def test_cmd_with_slash_c_is_fine():
    assert validator.check_actionscript("wait cmd.exe /c echo hi") == []


def test_cmd_with_uppercase_slash_k_is_w505():
    issues = validator.check_actionscript("waithidden cmd /K echo hi")
    assert codes(issues) == ["W505"]
    assert "/c" in issues[0][2]


def test_cmd_with_lowercase_slash_k_is_w505():
    assert codes(validator.check_actionscript("wait cmd /k setup.exe")) == ["W505"]


def test_cmd_with_both_switches_is_fine():
    """/c wins even when /k is also present -- the shell still exits."""
    assert validator.check_actionscript("wait cmd /k /c echo hi") == []


def test_bare_cmd_with_no_arguments_is_fine():
    """No payload to run, so nothing is silently skipped -- not this check's
    business.
    """
    assert validator.check_actionscript("wait cmd.exe") == []


def test_a_non_cmd_executable_is_not_w505():
    assert validator.check_actionscript("wait powershell.exe -File x.ps1") == []


def test_an_executable_merely_ending_in_cmd_is_not_w505():
    assert validator.check_actionscript("wait install-cmd.exe --quiet") == []


def test_cmd_inside_a_heredoc_is_not_w505():
    body = "createfile until _EOF_\nwait cmd.exe setup.exe\n_EOF_\nwait cmd.exe /c x"
    assert validator.check_actionscript(body) == []


def test_cmd_marker_silences_w505(tmp_path):
    content = bes("wait cmd.exe setup.exe", marker=validator.CMD_MARKER)
    assert issues_for(tmp_path, content) == []


def test_disable_w505_silences_it(tmp_path):
    content = bes("wait cmd.exe setup.exe")
    assert issues_for(tmp_path, content, disabled={"W505"}) == []


def test_cmd_marker_silences_slash_k(tmp_path):
    content = bes("wait cmd /k setup.exe", marker=validator.CMD_MARKER)
    assert issues_for(tmp_path, content) == []


# --- W506: move/copy of a scratch file onto an undeleted destination ---------------


def test_move_scratch_onto_undeleted_destination_is_w506():
    body = "createfile until _EOF_\nx\n_EOF_\nmove __createfile setup.reg"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["W506"]
    assert validator.SCRATCH_DEST_MARKER in issues[0][2]


def test_copy_scratch_onto_undeleted_destination_is_w506():
    body = 'createfile until _EOF_\nx\n_EOF_\ncopy __createfile "c:\\tools\\Bginfo.bat"'
    assert codes(validator.check_actionscript(body)) == ["W506"]


def test_delete_before_move_is_fine():
    body = "createfile until _EOF_\nx\n_EOF_\ndelete setup.reg\nmove __createfile setup.reg"
    assert validator.check_actionscript(body) == []


def test_quoted_delete_matches_an_unquoted_destination():
    body = (
        "createfile until _EOF_\nx\n_EOF_\n"
        'delete "c:\\tools\\setup.reg"\nmove __createfile c:\\tools\\setup.reg'
    )
    assert validator.check_actionscript(body) == []


def test_folder_delete_of_the_parent_clears_the_destination():
    """`folder delete` of an ancestor removes anything beneath it."""
    body = (
        "folder delete __Local/Upgrade\n"
        "appendfile #!/bin/sh\n"
        "move __appendfile __Local/Upgrade/besclientupgrade"
    )
    assert validator.check_actionscript(body) == []


def test_a_download_folder_destination_is_not_w506():
    """The action's own download folder is action-scoped, not a persistent path."""
    body = (
        "createfile until _EOF_\nx\n_EOF_\nmove __createfile __Download\\Baseline.bes"
    )
    assert validator.check_actionscript(body) == []


def test_move_of_a_non_scratch_source_is_not_w506():
    body = "move __Download/x.deb /var/tmp/x.deb"
    assert codes(validator.check_actionscript(body)) == ["E513"]


def test_scratch_dest_marker_silences_w506(tmp_path):
    content = bes(
        "createfile until _EOF_\nx\n_EOF_\nmove __createfile setup.reg",
        marker=validator.SCRATCH_DEST_MARKER,
    )
    assert issues_for(tmp_path, content) == []


def test_disable_w506_silences_it(tmp_path):
    content = bes("createfile until _EOF_\nx\n_EOF_\nmove __createfile setup.reg")
    assert issues_for(tmp_path, content, disabled={"W506"}) == []


# --- E522: override wait/run block termination -------------------------------------


def test_override_wait_terminated_by_wait_is_fine():
    body = "override wait\nhidden=true\nwait cmd /c echo a"
    assert validator.check_actionscript(body) == []


def test_override_run_terminated_by_run_is_fine():
    body = "override run\nhidden=true\nrun cmd /c echo a"
    assert validator.check_actionscript(body) == []


def test_override_substitution_option_line_is_fine():
    """A `{...}` relevance substitution can itself evaluate to a
    keyword=value option (e.g. picking `hidden=true` vs `completion=none`.

    by OS); it keeps the block open like a literal option line does.
    """
    body = (
        "override run\n"
        '{if (windows of operating system) then "hidden=true" '
        'else "completion=none" }\n'
        'run echo "test"'
    )
    assert validator.check_actionscript(body) == []


def test_override_substitution_option_line_with_leading_whitespace_is_fine():
    body = (
        "override wait\n"
        '  {if (windows of operating system) then "hidden=true" '
        'else "completion=none" }\n'
        "wait cmd /c echo a"
    )
    assert validator.check_actionscript(body) == []


def test_override_wait_terminated_by_run_is_e522():
    body = "override wait\nhidden=true\nrun cmd /c echo a"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E522"]
    assert issues[0][0] == 1
    assert validator.OVERRIDE_BLOCK_MARKER in issues[0][2]


def test_override_wait_terminated_by_waithidden_is_e522():
    """`waithidden` is a different verb from `wait`; the override does not apply."""
    body = "override wait\nhidden=true\nwaithidden cmd /c echo a"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E522"]


def test_override_never_terminated_is_e522():
    body = "override wait\nhidden=true"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E522"]
    assert issues[0][0] == 1


def test_override_reopened_before_a_command_is_e522():
    body = "override wait\nhidden=true\noverride run\nrun cmd /c echo a"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E522"]
    assert issues[0][0] == 1


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


def test_parameter_marker_silences_e516(tmp_path):
    content = bes(
        'parameter "a" = "1"\nparameter "a" = "2"',
        marker=validator.PARAMETER_MARKER,
    )
    assert issues_for(tmp_path, content) == []


def test_scratch_marker_silences_e519(tmp_path):
    content = bes(
        "move __createfile __Download\\x.txt",
        marker=validator.SCRATCH_MARKER,
    )
    assert issues_for(tmp_path, content) == []


def test_command_shape_marker_silences_e520(tmp_path):
    content = bes('setting "x"="1"', marker=validator.COMMAND_SHAPE_MARKER)
    assert issues_for(tmp_path, content) == []


def test_override_block_marker_silences_e522(tmp_path):
    content = bes(
        "override wait\nhidden=true\nrun cmd /c echo a",
        marker=validator.OVERRIDE_BLOCK_MARKER,
    )
    assert issues_for(tmp_path, content) == []


def test_disable_w504_silences_it(tmp_path):
    issues = issues_for(tmp_path, bes("dos echo hi"), disabled={"W504"})
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


def test_literal_double_braces_in_a_heredoc_are_not_a_mustache_template(tmp_path):
    # `{{` is also the ActionScript escape for a literal `{`, so heredoc payloads
    # (YARA rules, JSON, C#) contain it without being templates -- such a file is
    # real content and must still be checked
    content = bes(
        'createfile until _EOF_\n{{\n  "key": "value"\n}}\n_EOF_\nendif',
    )
    assert codes(issues_for(tmp_path, content)) == ["E501"]


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
