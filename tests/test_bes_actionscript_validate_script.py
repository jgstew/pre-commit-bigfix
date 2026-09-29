#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_actionscript_validate_script.py.

These exercise the if/endif and begin/end prefetch block balance walk
(E500-E507), the per-line {...} relevance-substitution brace balance
(E508, E509), prefetch placement (E510, E511, E515), download-name
consistency (E512, W507), if-condition shape (E514), duplicate/out-of-order
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

import pytest
from lxml import etree

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


# --- E524: `else if` instead of `elseif` ---------------------------------------


@pytest.mark.parametrize("spelling", ["else if", "Else If", "ELSE  IF"])
def test_else_if_is_e524(spelling):
    """ActionScript's chained branch is one word, `elseif`; `else if` is not
    recognized as an else or an elseif, so the branch logic is not what the.

    author wrote.
    """
    body = (
        "if {windows of operating system}\nwait cmd /c echo a\n"
        f"{spelling} {{mac of operating system}}\nwait /bin/echo b\nendif"
    )
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["E524"]
    assert issues[0][0] == 3
    assert "elseif" in issues[0][2] and validator.IF_MARKER in issues[0][2]


def test_else_if_is_tracked_as_an_elseif_so_nothing_cascades():
    """Treated as the elseif it was meant to be: a later `else` is still the
    first else, and the block still closes.
    """
    body = (
        "if {a}\nwait x\nelse if {b}\nwait y\nelse\nwait z\nendif\n"
        'parameter "p" = "1"'
    )
    assert codes(validator.check_actionscript(body)) == ["E524"]


def test_else_if_without_a_substitution_also_reports_e514():
    body = "if {a}\nwait x\nelse if true\nwait y\nendif"
    assert codes(validator.check_actionscript(body)) == ["E514", "E524"]


def test_elseif_and_plain_else_are_not_e524():
    body = "if {a}\nwait x\nelseif {b}\nwait y\nelse\nwait z\nendif"
    assert validator.check_actionscript(body) == []


def test_if_marker_silences_e524(tmp_path):
    content = bes(
        "if {a}\nwait x\nelse if {b}\nwait y\nendif", marker=validator.IF_MARKER
    )
    assert issues_for(tmp_path, content) == []


def test_disable_e524_silences_it(tmp_path):
    content = bes("if {a}\nwait x\nelse if {b}\nwait y\nendif")
    assert issues_for(tmp_path, content, disabled={"E524"}) == []


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


def test_stray_close_brace_inside_createfile_block_is_ignored():
    """A `}` with nothing open is literal createfile text (an unclosed `{`
    there is E508 -- see the createfile E508 tests).
    """
    body = (
        "createfile until END_OF_FILE\n"
        "some } file content\n"
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
    # `{{` escaping a literal `{` before an MSI product code (`msiexec
    # /x{{{GUID}}`) is ActionScript, not a template -- found in real content
    guid = "CD95F661-A5C4-44F5-A6AA-ECDD91C240E1"
    assert not validator.MUSTACHE_RE.search(
        f"waithidden msiexec.exe /x{{{{{{{guid}}}}} /qn"
    )
    assert not validator.MUSTACHE_RE.search(f"{{{{{guid.lower()}}}}}")
    # a triple-mustache placeholder is still a template
    assert validator.MUSTACHE_RE.search("<Title>{{{DisplayName}}}</Title>")


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


def test_moves_into_the_same_download_subdirectory_are_not_e512():
    """Several files moved into `__Download\\<dir>\\...` share a directory,
    not a download name -- none overwrites another (issue #21).
    """
    body = (
        "prefetch Setup.exe sha1:a size:1 http://x/Setup.exe\n"
        "prefetch Upd1.msp sha1:b size:1 http://x/Upd1.msp\n"
        "prefetch Upd2.msp sha1:c size:1 http://x/Upd2.msp\n"
        'wait __Download\\Setup.exe /x /d "{(pathname of client folder of '
        'current site)}\\__Download\\AcrobatPro"\n'
        'move __Download\\Upd1.msp "__Download\\AcrobatPro\\Adobe Acrobat XI\\Upd1.msp"\n'
        'move __Download\\Upd2.msp "__Download\\AcrobatPro\\Adobe Acrobat XI\\Upd2.msp"\n'
        'wait msiexec /p "__Download\\AcrobatPro\\Adobe Acrobat XI\\Upd2.msp"'
    )
    assert validator.check_actionscript(body) == []


def test_move_to_a_top_level_download_name_twice_is_still_e512():
    body = (
        "prefetch a.exe sha1:a size:1 http://x/a.exe\n"
        "prefetch b.exe sha1:b size:1 http://x/b.exe\n"
        "move __Download\\a.exe __Download\\c.exe\n"
        "move __Download\\b.exe __Download\\c.exe\n"
        "wait __Download\\c.exe"
    )
    assert codes(validator.check_actionscript(body)) == ["E512"]


# --- W507: __Download reference with no producer -------------------------------


def test_download_reference_with_no_producer_is_w507():
    body = "prefetch a.exe sha1:x size:1 http://x/a.exe\nwait __Download\\b.exe"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["W507"]
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


def test_extract_present_suppresses_w507():
    """An archive's contents are unknowable, so no consumer can be judged."""
    body = (
        "prefetch a.zip sha1:x size:1 http://x/a.zip\n"
        "extract a.zip\n"
        "wait __Download\\inside.exe"
    )
    assert validator.check_actionscript(body) == []


def test_substituted_producer_name_suppresses_w507():
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


def test_unshaped_download_line_suppresses_w507():
    """A substituted URL contains a space, matching neither download shape."""
    body = (
        'parameter "u" = "http://169.254.169.254/latest/document"\n'
        'download now {parameter "u"}\n'
        "delete /tmp/out.json\n"
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


def test_glob_wildcard_consumer_does_not_disable_other_w507_checks():
    """The wildcard skip is per-reference, not a whole-body knowability
    escape hatch: an unrelated real typo two lines later still fires.
    """
    body = (
        "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
        "wait __Download\\mysql*rpm\n"
        "wait __Download\\b.exe"
    )
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["W507"]
    assert "b.exe" in issues[0][2]


# --- W507: copy/move and shell-redirection producers ---------------------------


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


def test_move_from_createfile_with_substituted_destination_suppresses_w507():
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


def test_move_of_an_undeclared_download_with_no_createfile_is_still_w507():
    """A single __Download ref with no __createfile source is a plain typo."""
    body = "delete elsewhere\nmove __Download\\typo.exe elsewhere"
    issues = validator.check_actionscript(body)
    assert codes(issues) == ["W507"]


def test_redirection_into_download_registers_the_target():
    body = (
        "createfile until EOF\ncontent\nEOF\n"
        "move __createfile __Download\\WUA_Search.vbs\n"
        "waithidden cmd /c cscript __Download\\WUA_Search.vbs "
        "> __Download\\results_WindowsUpdates.ini\n"
        'delete "C:\\out.ini"\n'
        "move __Download\\results_WindowsUpdates.ini "
        '"C:\\out.ini"'
    )
    assert validator.check_actionscript(body) == []


def test_double_redirect_append_into_download_registers_the_target():
    body = "wait cmd /c echo hi >> __Download\\log.txt\n" "wait __Download\\log.txt"
    assert validator.check_actionscript(body) == []


def test_folder_create_under_download_is_not_a_reference():
    """`folder create "__Download\\7z"` makes a folder -- it is a producer,
    not a reference to a download nothing provides.
    """
    assert validator.check_actionscript('folder create "__Download\\7z"') == []


def test_folder_create_registers_the_folder_for_later_references():
    body = 'folder create "__Download\\7z"\nwait "__Download\\7z\\x.exe"'
    assert validator.check_actionscript(body) == []


def test_reference_into_an_uncreated_download_subfolder_is_still_w507():
    body = 'folder create "__Download\\7z"\nwait "__Download\\8z\\x.exe"'
    assert codes(validator.check_actionscript(body)) == ["W507"]


def test_global_download_folder_is_not_the_action_download_folder():
    """`__Global\\__Download\\actionsite\\...` is the client's shared
    download cache, not this action's `__Download` folder.
    """
    body = (
        'parameter "backup" = "{(data folder of client as string) & '
        '"\\__Global\\__Download\\actionsite\\_listbackup.txt"}"\n'
        "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
        "wait __Download\\a.exe"
    )
    assert validator.check_actionscript(body) == []


def test_substituted_download_folder_reference_is_still_checked():
    """`& "\\__Download\\x"` inside a substitution is a real reference."""
    body = (
        "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
        'wait __Download\\a.exe /b="{(client folder of current site as string) '
        '& "\\__Download\\E5450A19.exe"}"'
    )
    assert codes(validator.check_actionscript(body)) == ["W507"]


@pytest.mark.parametrize(
    "extract_line",
    [
        # sysinternals-style zip unpacked with a prefetched unzip.exe
        'waithidden __Download\\unzip.exe -o "{pathname of file "a.zip" of '
        'folder "__Download" of client folder of current site}" -d '
        '"{pathname of folder "__Download" of client folder of current site}"',
        # 7-Zip, with the executable itself found by a relevance substitution
        'waithidden "{ (pathname of file "7z.exe" of folder "7z" of folder '
        '"__Download" of client folder of current site) }" e -y -o"{pathname '
        'of folder "__Download" of client folder of current site}" "x.exe"',
        "waithidden __Download\\7za.exe x __Download\\a.7z -o__Download",
        # Windows' own cabinet expander, pulling files out of a .diagcab
        'waithidden expand -i "__Download\\O14-CTRRemove.diagcab" '
        '-f:OffScrub*.vbs "__Download"',
    ],
)
def test_archive_extractor_run_makes_download_names_unknowable(extract_line):
    """An unzip/7-Zip/expand run writes files whose names the script never
    spells out, exactly like an `extract` line -- so W507 is skipped.
    """
    body = (
        "prefetch a.zip sha1:x size:1 http://x/a.zip\n"
        f"{extract_line}\n"
        'wait "__Download\\setup_from_archive.exe"'
    )
    assert validator.check_actionscript(body) == []


def test_non_extractor_run_keeps_w507():
    body = "wait __Download\\setup.exe /S\nwait __Download\\other.exe"
    assert codes(validator.check_actionscript(body)) == ["W507", "W507"]


def test_move_into_download_from_elsewhere_registers_the_destination():
    """The one __Download ref is the destination -- the file is being put there."""
    body = (
        'move {parameter "Temp"}\\ScreenShot.png __Download\\ScreenShot.png\n'
        "delete C:\\out.png\n"
        "copy __Download\\ScreenShot.png C:\\out.png"
    )
    assert validator.check_actionscript(body) == []


def test_move_out_of_download_with_one_ref_is_still_a_reference():
    body = (
        'delete "C:\\ProgramData\\user.png"\n'
        'copy "__Download\\user.png" "C:\\ProgramData\\user.png"'
    )
    assert codes(validator.check_actionscript(body)) == ["W507"]


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


def test_action_parameter_query_defines_the_parameter():
    """The query prompts for the value when the action is taken, so it is set
    from the first line on -- a later `parameter` line does not make an.

    earlier reference an ordering bug.
    """
    body = (
        'action parameter query "homePage" with description "Home Page" '
        'with default value "https://example.com"\n'
        'if {parameter "homePage" = ""}\n'
        'parameter "homePage" = "about:blank"\n'
        "endif"
    )
    assert "E517" not in codes(validator.check_actionscript(body))


@pytest.mark.parametrize(
    "guard",
    [
        'if {not exists parameter "DriveLetter"}',
        'if {not (exists parameter "DriveLetter")}',
        'if {exists parameter "DriveLetter" and true}',
    ],
)
def test_exists_parameter_guard_is_not_a_premature_reference(guard):
    """Testing whether a parameter was supplied from outside the script is
    the supported way to give it a default, not a use before assignment.
    """
    body = f'{guard}\n\tparameter "DriveLetter" = "C"\nendif'
    assert validator.check_actionscript(body) == []


def test_value_use_inside_an_exists_guard_line_is_still_e517():
    """Only the `exists parameter` test itself is exempt, not a value read."""
    body = (
        'if {exists parameter "a" and parameter "a" = "x"}\n'
        'parameter "a" = "1"\n'
        "endif"
    )
    assert codes(validator.check_actionscript(body)) == ["E517"]


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
    """Cleanup, not consumption -- the same exemption W507 uses."""
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


def test_move_of_a_non_scratch_source_is_also_w506():
    """A download moved onto a persistent path fails the same way on a rerun."""
    body = "move __Download/x.deb /var/tmp/x.deb"
    assert codes(validator.check_actionscript(body)) == ["W506", "W507"]


def test_scratch_dest_marker_silences_w506(tmp_path):
    content = bes(
        "createfile until _EOF_\nx\n_EOF_\nmove __createfile setup.reg",
        marker=validator.SCRATCH_DEST_MARKER,
    )
    assert issues_for(tmp_path, content) == []


def test_disable_w506_silences_it(tmp_path):
    content = bes("createfile until _EOF_\nx\n_EOF_\nmove __createfile setup.reg")
    assert issues_for(tmp_path, content, disabled={"W506"}) == []


PREFETCH_A = "prefetch a.exe sha1:x size:1 http://x/a.exe\n"


@pytest.mark.parametrize(
    "line",
    [
        'move __Download\\a.exe "C:\\app\\a.exe"',
        'copy __Download\\a.exe "{parameter "Logs"}results.json"',
        "copy __Download/a.exe /etc/app/a.exe",
    ],
)
def test_copy_or_move_of_any_source_onto_an_undeleted_destination_is_w506(line):
    """`copy`/`move` fail when the destination exists whatever the source
    is, so the action works once and fails on every later run.
    """
    issues = validator.check_actionscript(PREFETCH_A + line)
    assert codes(issues) == ["W506"]
    assert issues[0][0] == 2


def test_any_source_with_a_prior_delete_is_fine():
    body = (
        PREFETCH_A + 'delete "C:\\app\\a.exe"\nmove __Download\\a.exe "C:\\app\\a.exe"'
    )
    assert validator.check_actionscript(body) == []


def test_any_source_onto_a_download_folder_destination_is_not_w506():
    body = (
        PREFETCH_A + "move __Download\\a.exe __Download\\b.exe\nwait __Download\\b.exe"
    )
    assert validator.check_actionscript(body) == []


def test_backup_move_destination_needs_its_own_delete():
    """`move <file> <file>.bak` is itself a move onto `<file>.bak`."""
    move = 'move "C:\\app\\x.conf" "C:\\app\\x.conf.bak"'
    assert codes(validator.check_actionscript(move)) == ["W506"]
    body = 'delete "C:\\app\\x.conf.bak"\n' + move
    assert validator.check_actionscript(body) == []


def test_delete_of_the_same_file_looked_up_by_relevance_clears_it():
    """`{pathname of file "x.jar" of folder (parameter "Dir")}` names the
    same file as `{parameter "Dir"}/x.jar` (real bigfix-content shape).
    """
    body = (
        "prefetch x.jar sha1:x size:1 http://x/x.jar\n"
        'delete "{pathname of file "x.jar" of folder (parameter "Dir")}"\n'
        'copy __Download/x.jar "{parameter "Dir"}/x.jar"'
    )
    assert validator.check_actionscript(body) == []


def test_relevance_lookup_of_a_different_file_does_not_clear_it():
    body = (
        "prefetch x.jar sha1:x size:1 http://x/x.jar\n"
        'delete "{pathname of file "other.jar" of folder (parameter "Dir")}"\n'
        'copy __Download/x.jar "{parameter "Dir"}/x.jar"'
    )
    assert codes(validator.check_actionscript(body)) == ["W506"]


@pytest.mark.parametrize(
    "folder_delete",
    [
        'folder delete "{ parameter "RunFolder" }"',  # spaces inside the braces
        'folder delete "{parameter "RunFolder"}"',
        'folder delete "{parameter "RunFolder"}\\"',
    ],
)
def test_folder_delete_of_a_substituted_parent_clears_it(folder_delete):
    body = (
        "prefetch KVRT.exe sha1:x size:1 http://x/KVRT.exe\n"
        f"{folder_delete}\n"
        'copy __Download\\KVRT.exe "{parameter "RunFolder"}\\KVRT.exe"'
    )
    assert validator.check_actionscript(body) == []


def test_folder_delete_of_a_different_substituted_folder_does_not_clear_it():
    body = (
        "prefetch KVRT.exe sha1:x size:1 http://x/KVRT.exe\n"
        'folder delete "{parameter "OtherFolder"}"\n'
        'copy __Download\\KVRT.exe "{parameter "RunFolder"}\\KVRT.exe"'
    )
    assert codes(validator.check_actionscript(body)) == ["W506"]


@pytest.mark.parametrize(
    "shell_delete, destination",
    [
        # real CommunityContent shapes (macOS /tmp is /private/tmp)
        ("wait /bin/sh -c \"rm '/private/tmp/a.pkg' \"", '"/tmp/a.pkg"'),
        ('wait sh -c "rm \'/tmp/{parameter "D"}\'"', '"/tmp/{parameter "D"}"'),
        ("wait /bin/rm -f /opt/app/a.pkg", "/opt/app/a.pkg"),
        ('waithidden cmd /c del /f "C:\\app\\a.pkg"', '"C:\\app\\a.pkg"'),
    ],
)
def test_shell_delete_of_the_destination_clears_it(shell_delete, destination):
    body = (
        "prefetch a.pkg sha1:x size:1 http://x/a.pkg\n"
        f"{shell_delete}\nmove __Download/a.pkg {destination}"
    )
    assert validator.check_actionscript(body) == []


@pytest.mark.parametrize(
    "shell_line",
    [
        "wait sh -c \"rm '/tmp/other.pkg'\"",  # a different file
        'wait sh -c "echo /tmp/a.pkg"',  # names it but does not delete it
        "wait sh -c \"rm '/tmp/a.pkg.old'\"",  # a longer name, not the file
    ],
)
def test_shell_line_that_does_not_delete_the_destination_keeps_w506(shell_line):
    body = (
        "prefetch a.pkg sha1:x size:1 http://x/a.pkg\n"
        f'{shell_line}\nmove __Download/a.pkg "/tmp/a.pkg"'
    )
    assert codes(validator.check_actionscript(body)) == ["W506"]


def test_copy_whose_arguments_cannot_be_split_is_not_w506():
    """Three unquoted words: which is the destination is unknowable."""
    body = PREFETCH_A + "copy __Download\\a.exe C:\\Program Files\\a.exe"
    assert "W506" not in codes(validator.check_actionscript(body))


def test_parameter_of_action_matches_the_bare_parameter():
    """`{parameter "X" of action}` and `{parameter "X"}` name one parameter."""
    body = (
        "createfile until _EOF_\nx\n_EOF_\n"
        'delete "{parameter "Dir" of action}\\Bin\\Baseline.ps1"\n'
        'copy __createfile "{parameter "Dir"}\\Bin\\Baseline.ps1"'
    )
    assert validator.check_actionscript(body) == []


def test_moving_the_destination_away_clears_it():
    """Backing the old file up with `move` leaves the destination empty."""
    body = (
        "appendfile new content\n"
        'delete "{parameter "server"}.bak"\n'
        'move "{parameter "server"}" "{parameter "server"}.bak"\n'
        'move __appendfile "{parameter "server"}"'
    )
    assert validator.check_actionscript(body) == []


def test_copying_the_destination_elsewhere_does_not_clear_it():
    """A `copy` leaves its source in place, so the destination still exists."""
    body = (
        "appendfile new content\n"
        'delete "{parameter "server"}.bak"\n'
        'copy "{parameter "server"}" "{parameter "server"}.bak"\n'
        'move __appendfile "{parameter "server"}"'
    )
    assert codes(validator.check_actionscript(body)) == ["W506"]


def test_moving_a_different_file_away_does_not_clear_it():
    body = (
        "appendfile new content\n"
        'delete "C:\\app\\server.conf.bak"\n'
        'move "C:\\app\\server.conf" "C:\\app\\server.conf.bak"\n'
        'move __appendfile "C:\\app\\web.conf"'
    )
    assert codes(validator.check_actionscript(body)) == ["W506"]


def test_windows_path_delete_matches_case_insensitively():
    """A drive-letter / backslash path is on a case-insensitive filesystem."""
    body = (
        "createfile until _EOF_\nx\n_EOF_\n"
        'delete "C:\\Windows\\Temp\\Applocker.xml"\n'
        'move __createfile "c:\\windows\\temp\\applocker.xml"'
    )
    assert validator.check_actionscript(body) == []


@pytest.mark.parametrize(
    "deleted, destination",
    [
        ("applocker.xml", "Applocker.xml"),  # bare name: platform unknown
        ("/etc/App.conf", "/etc/app.conf"),  # POSIX: case-sensitive
    ],
)
def test_non_windows_path_case_mismatch_is_still_w506(deleted, destination):
    """On a case-sensitive filesystem these are two different files."""
    body = (
        "createfile until _EOF_\nx\n_EOF_\n"
        f"delete {deleted}\nmove __createfile {destination}"
    )
    assert codes(validator.check_actionscript(body)) == ["W506"]


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


def test_download_marker_silences_w507(tmp_path):
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


# --- line numbers quoted inside messages are file lines ------------------------


@pytest.mark.parametrize(
    "code, body, referenced_body_line",
    [
        (
            "E512",
            "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
            "prefetch a.exe sha1:y size:1 http://x/b.exe\n"
            "wait __Download\\a.exe",
            1,
        ),
        ("E516", 'parameter "a" = "1"\nparameter "a" = "2"', 1),
        ("E517", 'wait cmd /c echo {parameter "a"}\nparameter "a" = "1"', 2),
        ("E522", "override wait\nhidden=true\nrun cmd /c echo a", 3),
        ("E522", "override wait\noverride run\nrun cmd /c echo a", 2),
        ("W501", "exit 0\nwait cmd /c echo a", 1),
        ("W502", 'wait cmd /c echo a\naction parameter query "p"', 1),
    ],
)
def test_line_numbers_in_messages_are_file_lines(
    tmp_path, code, body, referenced_body_line
):
    """A message that points at another line must use the same numbering as
    the issue's own line -- the file's -- not a count from the start of the.

    ActionScript body (which begins several lines into the file).
    """
    content = bes(body)
    body_start = (
        content.split("\n").index(
            next(line for line in content.split("\n") if "<ActionScript" in line)
        )
        + 1
    )
    expected = body_start + referenced_body_line - 1
    messages = [msg for _, found, msg in issues_for(tmp_path, content) if found == code]
    assert messages, f"expected {code}"
    assert f"line {expected}" in messages[0], messages[0]


# --- trailing `//` comments on fixed-syntax lines --------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "if {a}\nwait x\nendif // end of the a check",
        "if {a}\nwait x\nendif  //no space after the slashes",
        'if {a}\nwait x\nelse  //if {exists local user "x"}\nwait y\nendif',
        "if {a} // why we check a\nwait x\nendif",
        "if {a}\nwait x\nelseif {b} // b case\nwait y\nendif",
        "begin prefetch block // downloads\n"
        "add prefetch item name=a.exe sha1=x size=1 url=http://x/a.exe\n"
        "end prefetch block // done\nwait __Download\\a.exe",
        "override wait // SYSTEM cannot change display settings\n"
        "hidden=true\nwait cmd /c echo a",
    ],
)
def test_trailing_comment_on_a_fixed_syntax_line_is_ignored(body):
    """A `// comment` at the end of a line is valid ActionScript; on a line
    whose syntax is fixed (if/elseif/else/endif, prefetch block bounds,.

    override) it must not change how the line is parsed.
    """
    assert validator.check_actionscript(body) == []


def test_else_with_trailing_comment_is_still_an_else():
    """Recognized as an else, so a second else for the same if is E506."""
    body = "if {a}\nwait x\nelse // first\nwait y\nelse\nwait z\nendif"
    assert codes(validator.check_actionscript(body)) == ["E506"]


def test_double_slash_arguments_of_a_command_are_not_a_comment():
    """`cscript //Nologo` -- the rest of a launch line goes to the program
    verbatim, so its `>` redirect into __Download still produces the file.
    """
    body = (
        "prefetch a.vbs sha1:x size:1 http://x/a.vbs\n"
        "waithidden cmd /c cscript __Download\\a.vbs //Nologo > __Download\\out.ini\n"
        "copy __Download\\out.ini C:\\out.ini"
    )
    assert "W507" not in codes(validator.check_actionscript(body))


@pytest.mark.parametrize(
    "line, expected",
    [
        ("endif // x", "endif"),
        ("endif", "endif"),
        ('if {exists file "a//b"} // c', 'if {exists file "a//b"}'),
        ('if {"x // y" = "z"}', 'if {"x // y" = "z"}'),  # inside a substitution
        ("else//x", "else//x"),  # `//` must follow whitespace
    ],
)
def test_strip_trailing_comment(line, expected):
    assert validator._strip_trailing_comment(line) == expected


# --- W506 auto-fix: insert `delete <destination>` before the move/copy ----------


def _action_texts(path):
    """Decoded ActionScript text of every action in the BES file at `path`."""
    with open(path, "rb") as handle:
        root = etree.fromstring(handle.read())
    return [element.text for element in root.iter("ActionScript")]


def test_w506_auto_fix_inserts_delete_before_the_copy(tmp_path):
    body = (
        "prefetch a.exe sha1:x size:1 http://x/a.exe\n"
        '    copy __Download\\a.exe "C:\\app\\a.exe"\nwait "C:\\app\\a.exe"'
    )
    path = write(tmp_path, "x.bes", bes(body))
    issues, fixed = validator.check_file(path, auto_fix=True)
    assert "W506" not in codes(issues)
    assert codes(fixed) == ["W506"]
    [text] = _action_texts(path)
    assert (
        '\n    delete "C:\\app\\a.exe"\n    copy __Download\\a.exe "C:\\app\\a.exe"'
        in text
    )


def test_w506_auto_fix_on_the_first_line_of_the_body(tmp_path):
    """The body starts on the <ActionScript> tag line: the delete goes after
    the tag, inside the script, not before it.
    """
    path = write(tmp_path, "x.bes", bes('move __Download\\a.exe "C:\\a.exe"'))
    _issues, fixed = validator.check_file(path, auto_fix=True)
    assert codes(fixed) == ["W506"]
    [text] = _action_texts(path)
    assert text == 'delete "C:\\a.exe"\nmove __Download\\a.exe "C:\\a.exe"'


def test_w506_auto_fix_in_an_entity_escaped_body(tmp_path):
    """Outside CDATA the inserted delete must be escaped the same way."""
    content = bes("x").replace(
        "<![CDATA[x]]>",
        "\nmove __Download\\a.exe &quot;C:\\a &amp; b\\a.exe&quot;\n",
    )
    path = write(tmp_path, "x.bes", content)
    _issues, fixed = validator.check_file(path, auto_fix=True)
    assert codes(fixed) == ["W506"]
    raw = open(path, encoding="utf-8").read()
    assert "delete &quot;C:\\a &amp; b\\a.exe&quot;" in raw
    [text] = _action_texts(path)
    assert '\ndelete "C:\\a & b\\a.exe"\nmove __Download' in text


def test_w506_auto_fix_copies_a_cdata_destination_with_ampersand_verbatim(tmp_path):
    """Inside CDATA a relevance `&` concatenation is literal and legal."""
    move = 'copy __Download\\a.dll "{(pathname of windows folder & "\\a.dll")}"'
    path = write(tmp_path, "x.bes", bes("wait x\n" + move))
    _issues, fixed = validator.check_file(path, auto_fix=True)
    assert codes(fixed) == ["W506"]
    [text] = _action_texts(path)
    assert (
        text == 'wait x\ndelete "{(pathname of windows folder & "\\a.dll")}"\n' + move
    )


def test_w506_auto_fix_handles_several_targets_and_keeps_crlf(tmp_path):
    body = (
        'copy __Download\\a.exe "C:\\a.exe"\n'
        "wait x\n"
        'copy __Download\\b.exe "C:\\b.exe"'
    )
    path = write(tmp_path, "x.bes", bes(body))
    issues, fixed = validator.check_file(path, auto_fix=True)
    assert codes(fixed) == ["W506", "W506"]
    assert "W506" not in codes(issues)
    [text] = _action_texts(path)
    assert text.split("\n") == [
        'delete "C:\\a.exe"',
        'copy __Download\\a.exe "C:\\a.exe"',
        "wait x",
        'delete "C:\\b.exe"',
        'copy __Download\\b.exe "C:\\b.exe"',
    ]
    raw = open(path, "rb").read()
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_w506_auto_fix_is_idempotent(tmp_path):
    path = write(tmp_path, "x.bes", bes('copy __Download\\a.exe "C:\\a.exe"'))
    validator.check_file(path, auto_fix=True)
    once = open(path, "rb").read()
    _issues, fixed = validator.check_file(path, auto_fix=True)
    assert fixed == []
    assert open(path, "rb").read() == once


@pytest.mark.parametrize(
    "kwargs, marker",
    [({"disabled": {"W506"}}, None), ({}, validator.SCRATCH_DEST_MARKER)],
)
def test_w506_auto_fix_respects_disable_and_marker(tmp_path, kwargs, marker):
    content = bes('copy __Download\\a.exe "C:\\a.exe"', marker=marker)
    path = write(tmp_path, "x.bes", content)
    before = open(path, "rb").read()
    _issues, fixed = validator.check_file(path, auto_fix=True, **kwargs)
    assert "W506" not in codes(fixed)
    assert open(path, "rb").read() == before


def test_w506_is_not_fixed_without_auto_fix(tmp_path):
    path = write(tmp_path, "x.bes", bes('copy __Download\\a.exe "C:\\a.exe"'))
    before = open(path, "rb").read()
    issues, fixed = validator.check_file(path)
    assert "W506" in codes(issues) and fixed == []
    assert open(path, "rb").read() == before


# --- E508 inside `createfile until` content --------------------------------------


def test_unclosed_brace_in_createfile_content_is_e508():
    """Createfile content is relevance-substituted line by line, so a literal
    `{` must be written `{{` there too (real bigfix-content shape: the same.

    script escapes `@{{Metadata="true"}` correctly two lines later).
    """
    body = (
        "createfile until END_OF_FILE\n"
        "try {\n"
        '$r = Invoke-RestMethod -Headers @{{Metadata="true"} -Uri "{parameter "u"}"\n'
        "} catch {\n"
        "    exit 1\n"
        "}\n"
        "END_OF_FILE\n"
        "move __createfile __Download\\get.ps1"
    )
    issues = validator.check_actionscript(body)
    assert [(lineno, code) for lineno, code, _ in issues] == [(2, "E508"), (4, "E508")]
    assert "createfile" in issues[0][2] and "{{" in issues[0][2]


@pytest.mark.parametrize(
    "content_line",
    [
        "}",  # a lone `}` is literal text
        'echo {parameter "x"}',  # a closed substitution
        "function f {{ return 1 }",  # escaped
        "if (\"$x\" -match '\\d{3}') {{ exit }",  # regex quantifier + escape
    ],
)
def test_balanced_or_literal_createfile_content_is_fine(content_line):
    body = (
        "createfile until EOF\n"
        f"{content_line}\n"
        "EOF\n"
        "move __createfile __Download\\x.ps1"
    )
    assert "E508" not in codes(validator.check_actionscript(body))


def test_substitution_marker_silences_createfile_e508(tmp_path):
    content = bes(
        "createfile until EOF\ntry {\nEOF\nmove __createfile __Download\\x.ps1",
        marker=validator.SUBSTITUTION_MARKER,
    )
    assert "E508" not in codes(issues_for(tmp_path, content))


# --- W508: a parameter referenced once and never set anywhere in the file -------


def test_parameter_named_nowhere_else_in_the_file_is_w508(tmp_path):
    """Copy-paste from a sibling fixlet that set it (real bigfix-content
    shape): the name occurs exactly once in the whole file.
    """
    body = "wait echo x\nappendfile rm -rf '{parameter \"JREFolder\"}'"
    issues = issues_for(tmp_path, bes(body))
    assert codes(issues) == ["W508"]
    content = bes(body).split("\n")
    assert "JREFolder" in content[issues[0][0] - 1]
    assert validator.PARAMETER_MARKER in issues[0][2]


@pytest.mark.parametrize(
    "extra",
    [
        # a Description page that supplies it (secure/prompted parameters)
        (
            "<Title>Example</Title>",
            "<Title>Example</Title><Description>"
            '&lt;input id="JREFolder"&gt;</Description>',
        ),
        # set by a second action in the same file
        (
            "</DefaultAction>",
            '</DefaultAction><Action ID="Action2"><ActionScript>'
            'parameter "JREFolder" = "/opt"</ActionScript></Action>',
        ),
    ],
)
def test_parameter_named_elsewhere_in_the_file_is_not_w508(tmp_path, extra):
    content = bes('wait echo {parameter "JREFolder"}').replace(*extra)
    assert "W508" not in codes(issues_for(tmp_path, content))


@pytest.mark.parametrize(
    "body",
    [
        'parameter "d" = "/opt"\nwait echo {parameter "d"}',
        'action parameter query "d" with description "Dir"\nwait echo {parameter "d"}',
        # two references: named elsewhere, so the narrow rule stays quiet
        'wait echo {parameter "d"}\nwait echo {parameter "d"}',
    ],
)
def test_assigned_queried_or_repeated_parameter_is_not_w508(tmp_path, body):
    assert "W508" not in codes(issues_for(tmp_path, bes(body)))


def test_builtin_action_issue_date_parameter_is_not_w508(tmp_path):
    """`action issue date` is supplied by the platform itself -- the console
    writes `setting ... on "{parameter "action issue date" of action}"`.
    """
    body = (
        'setting "_BESClient_Log_Days"="30" on '
        '"{parameter "action issue date" of action}" for client'
    )
    assert "W508" not in codes(issues_for(tmp_path, bes(body)))


def test_parameter_marker_silences_w508(tmp_path):
    content = bes(
        'wait echo {parameter "JREFolder"}', marker=validator.PARAMETER_MARKER
    )
    assert issues_for(tmp_path, content) == []
