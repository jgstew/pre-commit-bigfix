#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_relevance_convert_group.py.

These exercise the conversion of a console-exported <GroupRelevance> into
plain <Relevance>: JoinByIntersection="true" becomes one <Relevance> per
search component, "false" one `(a) OR (b)` <Relevance> (a lone component
needing no parentheses), with the CDATA / entity-escaping of the result, the
in-place splice that leaves the rest of the file byte-identical, the refusals
(E701 group reference, E702 JoinByIntersection, E703 empty component), the
console examples in tests/examples, CRLF preservation, --check, --disable, the
skip marker, the mustache-template skip, W700, and main()'s exit codes.
"""

import re
import shutil
from pathlib import Path

import pytest
from lxml import etree

from pre_commit_bigfix import bes_relevance_convert_group as hook

EXAMPLES = Path(__file__).parent / "examples"
FIXLET_EXAMPLE = EXAMPLES / "Example-Group-Relevance-Fixlet.bes"
ANALYSIS_EXAMPLE = EXAMPLES / "Example-Group-Relevance-Analysis.bes"
TASK_EXAMPLE = EXAMPLES / "Example-Group-Relevance-Task.bes"
BASELINE_EXAMPLE = EXAMPLES / "Example-Group-Relevance-Baseline.bes"

HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<BES xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xsi:noNamespaceSchemaLocation="BES.xsd">\n'
)


def prop(relevance_inner, comparison="Contains"):
    """One SearchComponentPropertyReference line; `relevance_inner` is raw XML."""
    return (
        f'<SearchComponentPropertyReference PropertyName="P" '
        f'Comparison="{comparison}"><SearchText>x</SearchText>'
        f"<Relevance>{relevance_inner}</Relevance>"
        "</SearchComponentPropertyReference>"
    )


def scr(relevance_inner, comparison="IsTrue"):
    """One SearchComponentRelevance line; `relevance_inner` is raw XML."""
    return (
        f'<SearchComponentRelevance Comparison="{comparison}">'
        f"<Relevance>{relevance_inner}</Relevance></SearchComponentRelevance>"
    )


def group_ref(name="Some Group", comparison="IsMember"):
    """One SearchComponentGroupReference line (it has no Relevance)."""
    return (
        f'<SearchComponentGroupReference GroupName="{name}" '
        f'Comparison="{comparison}"></SearchComponentGroupReference>'
    )


def group(components, join="true"):
    """A GroupRelevance block indented for a content object; join None omits it."""
    attr = "" if join is None else f' JoinByIntersection="{join}"'
    lines = [f"\t\t<GroupRelevance{attr}>"]
    lines += [f"\t\t\t{component}" for component in components]
    lines.append("\t\t</GroupRelevance>")
    return "\n".join(lines) + "\n"


def bes(*objects):
    """A BES document holding `objects`, each a (tag, applicability) pair.

    `applicability` is the indented GroupRelevance (or Relevance) text.
    """
    body = ""
    for tag, applicability in objects:
        body += (
            f"\t<{tag}>\n"
            "\t\t<Title>Example</Title>\n"
            "\t\t<Description>An example.</Description>\n"
            f"{applicability}"
            "\t\t<Domain>BESC</Domain>\n"
            f"\t</{tag}>\n"
        )
    return HEADER + body + "</BES>\n"


def relevances(src):
    """Decoded text of every content-object <Relevance> in `src`."""
    root = etree.fromstring(src.encode("utf-8"))
    return ["".join(node.xpath("text()")) for node in root.xpath("/BES/*/Relevance")]


def convert(src):
    """Run the pure conversion; return (new_src, fixed codes, issue codes)."""
    new_src, fixed, issues = hook.convert_group_relevance(src)
    return new_src, [c for _l, c, _m in fixed], [c for _l, c, _m in issues]


def example_relevance_lines(path):
    """The example's component <Relevance> lines, re-indented to content level.

    The console writes each component's <Relevance> on its own line, so this
    is the expected intersection output derived without parsing any XML.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    return ["\t\t" + line.strip() for line in lines if "<Relevance>" in line]


def replace_group_block(path, replacement_lines):
    """The example's text with its GroupRelevance lines replaced."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if "<GroupRelevance" in line)
    end = next(i for i, line in enumerate(lines) if "</GroupRelevance>" in line)
    new = [line + "\n" for line in replacement_lines]
    return "".join(lines[:start] + new + lines[end + 1 :])


# --- the console examples -------------------------------------------------


def test_fixlet_example_intersection_becomes_one_relevance_per_component():
    src = FIXLET_EXAMPLE.read_text(encoding="utf-8")
    new_src, fixed, issues = convert(src)
    expected_lines = example_relevance_lines(FIXLET_EXAMPLE)
    assert len(expected_lines) == 3
    assert new_src == replace_group_block(FIXLET_EXAMPLE, expected_lines)
    assert fixed == ["E700"]
    assert issues == []


def test_fixlet_example_keeps_cdata_and_escaping_verbatim():
    new_src, _fixed, _issues = convert(FIXLET_EXAMPLE.read_text(encoding="utf-8"))
    assert (
        "<Relevance><![CDATA[not exists (if (exists true whose (if true then exists "
        "drive of system folder else false)) then"
    ) in new_src
    assert "GroupRelevance" not in new_src


def test_analysis_example_union_becomes_one_or_joined_cdata_relevance():
    src = ANALYSIS_EXAMPLE.read_text(encoding="utf-8")
    root = etree.fromstring(src.encode("utf-8"))
    statements = [
        "".join(node.xpath("text()")).strip()
        for node in root.xpath("/BES/*/GroupRelevance/*/Relevance")
    ]
    assert len(statements) == 8

    new_src, fixed, issues = convert(src)
    assert fixed == ["E700"]
    assert issues == []
    assert relevances(new_src) == [" OR ".join(f"({s})" for s in statements)]
    assert (
        "\t\t<Relevance><![CDATA[(exists (if exist values of settings "
        '"_BESGather_Use_Https" of client'
    ) in new_src
    assert ")]]></Relevance>\n\t\t<Source>Internal</Source>" in new_src


def test_task_example_single_union_component_has_no_parentheses():
    src = TASK_EXAMPLE.read_text(encoding="utf-8")
    new_src, fixed, issues = convert(src)
    expected = (
        "\t\t<Relevance>exists (computer id) whose (it as string as lowercase "
        'contains "133454" as lowercase)</Relevance>'
    )
    assert new_src == replace_group_block(TASK_EXAMPLE, [expected])
    assert fixed == ["E700"]
    assert issues == []


def test_baseline_example_of_group_references_is_reported_and_unchanged():
    src = BASELINE_EXAMPLE.read_text(encoding="utf-8")
    new_src, fixed, issues = convert(src)
    assert new_src == src
    assert fixed == []
    assert issues == ["E701"]


@pytest.mark.parametrize("example", [FIXLET_EXAMPLE, ANALYSIS_EXAMPLE, TASK_EXAMPLE])
def test_converted_examples_are_schema_valid(tmp_path, example):
    validate_bes_xml = pytest.importorskip("validate_bes_xml")
    new_src, _fixed, _issues = convert(example.read_text(encoding="utf-8"))
    out = tmp_path / example.name
    out.write_text(new_src, encoding="utf-8")
    assert validate_bes_xml.validate_xml(str(out))


# --- union / intersection rules -------------------------------------------


def test_intersection_with_one_component_gives_one_relevance():
    src = bes(("Task", group([prop("exists file 1")], join="true")))
    new_src, fixed, _issues = convert(src)
    assert relevances(new_src) == ["exists file 1"]
    assert "\t\t<Relevance>exists file 1</Relevance>\n" in new_src
    assert fixed == ["E700"]


def test_union_without_special_characters_is_plain_text():
    src = bes(("Task", group([prop("a"), prop("b"), prop("c")], join="false")))
    new_src, _fixed, _issues = convert(src)
    assert "\t\t<Relevance>(a) OR (b) OR (c)</Relevance>\n" in new_src


@pytest.mark.parametrize(("join", "count"), [("1", 2), ("0", 1), (" true ", 2)])
def test_xs_boolean_spellings_of_join(join, count):
    src = bes(("Task", group([prop("a"), prop("b")], join=join)))
    new_src, fixed, _issues = convert(src)
    assert len(relevances(new_src)) == count
    assert fixed == ["E700"]


def test_search_component_relevance_is_used_as_is_for_true_and_false():
    src = bes(
        (
            "Task",
            group(
                [scr("exists file 1", "IsTrue"), scr("not exists file 2", "IsFalse")],
                join="true",
            ),
        )
    )
    new_src, fixed, _issues = convert(src)
    assert relevances(new_src) == ["exists file 1", "not exists file 2"]
    assert fixed == ["E700"]


def test_baseline_and_fixlet_stream_are_converted():
    src = bes(
        ("Baseline", group([prop("a"), prop("b")], join="false")),
        ("FixletStream", group([prop("c")], join="true")),
    )
    new_src, fixed, _issues = convert(src)
    assert relevances(new_src) == ["(a) OR (b)", "c"]
    assert fixed == ["E700", "E700"]


def test_file_without_group_relevance_is_untouched():
    src = bes(("Task", "\t\t<Relevance>true</Relevance>\n"))
    assert convert(src) == (src, [], [])


def test_rest_of_file_is_byte_identical():
    src = bes(("Task", group([prop("a"), prop("b")], join="true")))
    new_src, _fixed, _issues = convert(src)
    before, _, after = src.partition("\t\t<GroupRelevance")
    assert new_src.startswith(before)
    assert new_src.endswith(after.partition("</GroupRelevance>\n")[2])


def test_replacement_takes_the_group_relevance_indentation():
    src = bes(("Task", group([prop("a"), prop("b")]))).replace("\t\t<Group", "  <Group")
    new_src, _fixed, _issues = convert(src)
    assert "  <Relevance>a</Relevance>\n  <Relevance>b</Relevance>\n" in new_src


# --- CDATA and escaping ---------------------------------------------------


def test_intersection_keeps_each_cdata_wrapper_byte_for_byte():
    inner = "<![CDATA[exists (1) whose (it < 2)]]>"
    src = bes(("Task", group([prop(inner), prop("x &amp; y")], join="true")))
    new_src, _fixed, _issues = convert(src)
    assert f"<Relevance>{inner}</Relevance>" in new_src
    assert "<Relevance>x &amp; y</Relevance>" in new_src


def test_single_union_component_keeps_cdata_byte_for_byte():
    inner = "<![CDATA[exists (1) whose (it < 2)]]>"
    src = bes(("Task", group([prop(inner)], join="false")))
    new_src, _fixed, _issues = convert(src)
    assert f"\t\t<Relevance>{inner}</Relevance>\n" in new_src


def test_union_of_mixed_cdata_and_escaped_is_one_cdata_section():
    src = bes(
        (
            "Task",
            group([prop("<![CDATA[1 < 2]]>"), prop("3 &gt; 2 &amp; true")], "false"),
        )
    )
    new_src, _fixed, _issues = convert(src)
    assert "<Relevance><![CDATA[(1 < 2) OR (3 > 2 & true)]]></Relevance>" in new_src
    assert new_src.count("<![CDATA[") == 1
    assert "&amp;" not in new_src


def test_union_of_cdata_needing_no_escape_stays_cdata():
    src = bes(("Task", group([prop("<![CDATA[a]]>"), prop("<![CDATA[b]]>")], "false")))
    new_src, _fixed, _issues = convert(src)
    assert "<Relevance><![CDATA[(a) OR (b)]]></Relevance>" in new_src


def test_union_trims_whitespace_inside_and_around_cdata():
    src = bes(
        ("Task", group([prop("  <![CDATA[  a  ]]>  "), prop("\n b \n")], "false"))
    )
    new_src, _fixed, _issues = convert(src)
    assert relevances(new_src) == ["(a) OR (b)"]


def test_escaped_input_round_trips_through_cdata_output():
    src = bes(("Task", group([prop("1 &lt; 2"), prop("3 &lt; 4")], "false")))
    new_src, _fixed, _issues = convert(src)
    assert relevances(new_src) == ["(1 < 2) OR (3 < 4)"]
    assert "<![CDATA[(1 < 2) OR (3 < 4)]]>" in new_src


def test_union_text_containing_cdata_terminator_is_entity_escaped():
    # a literal `]]>` is not allowed in element text, so the input spells it ]]&gt;
    src = bes(("Task", group([prop('"]]&gt;" = "x"'), prop("1 &lt; 2")], "false")))
    new_src, _fixed, _issues = convert(src)
    assert "<![CDATA[" not in new_src
    assert relevances(new_src) == ['("]]>" = "x") OR (1 < 2)']


# --- refusals ---------------------------------------------------------------


@pytest.mark.parametrize("join", ["true", "false"])
def test_group_reference_mixed_with_properties_is_reported_and_unchanged(join):
    src = bes(("Task", group([prop("a"), group_ref("G"), prop("b")], join=join)))
    new_src, fixed, issues = convert(src)
    assert new_src == src
    assert fixed == []
    assert issues == ["E701"]


def test_only_the_convertible_object_is_rewritten():
    src = bes(
        ("Task", group([prop("a"), group_ref("G")], join="true")),
        ("Fixlet", group([prop("b")], join="true")),
    )
    new_src, fixed, issues = convert(src)
    assert new_src.count("<GroupRelevance") == 1
    assert "\t\t<Relevance>b</Relevance>\n" in new_src
    assert fixed == ["E700"]
    assert issues == ["E701"]


def test_group_reference_message_names_the_group():
    src = bes(("Task", group([group_ref("CPU is Virtual", "IsNotMember")])))
    _new_src, _fixed, issues = hook.convert_group_relevance(src)
    assert "CPU is Virtual" in issues[0][2]


@pytest.mark.parametrize("join", [None, "", "yes", "TRUE"])
def test_missing_or_invalid_join_is_reported_and_unchanged(join):
    src = bes(("Task", group([prop("a"), prop("b")], join=join)))
    new_src, fixed, issues = convert(src)
    assert new_src == src
    assert fixed == []
    assert issues == ["E702"]


@pytest.mark.parametrize("inner", ["", "   ", "<![CDATA[ ]]>"])
def test_empty_component_relevance_is_reported_and_unchanged(inner):
    src = bes(("Task", group([prop("a"), prop(inner)], join="false")))
    new_src, fixed, issues = convert(src)
    assert new_src == src
    assert fixed == []
    assert issues == ["E703"]


def test_group_relevance_with_no_components_is_reported():
    src = bes(("Task", '\t\t<GroupRelevance JoinByIntersection="true" />\n'))
    new_src, fixed, issues = convert(src)
    assert new_src == src
    assert fixed == []
    assert issues == ["E703"]


def test_reported_lineno_is_the_group_relevance_line():
    src = bes(("Task", group([group_ref()])))
    _new_src, _fixed, issues = hook.convert_group_relevance(src)
    expected = src.splitlines().index('\t\t<GroupRelevance JoinByIntersection="true">')
    assert issues[0][0] == expected + 1


# --- locating the text to splice --------------------------------------------


def test_group_relevance_in_a_comment_does_not_shift_the_splice():
    commented = (
        "\t<!-- <GroupRelevance><Relevance>no</Relevance></GroupRelevance> -->\n"
    )
    src = bes(("Task", group([prop("a"), prop("b")], join="true")))
    src = src.replace("<BES ", commented.join(["", ""]) + "<BES ", 0)
    src = src.replace("\t<Task>\n", commented + "\t<Task>\n", 1)
    new_src, fixed, _issues = convert(src)
    assert commented in new_src
    assert "\t\t<Relevance>a</Relevance>\n\t\t<Relevance>b</Relevance>\n" in new_src
    assert fixed == ["E700"]


def test_group_relevance_text_inside_cdata_does_not_shift_the_splice():
    tricky = '<![CDATA["</GroupRelevance><GroupRelevance>" contains "x"]]>'
    src = bes(("Task", group([prop(tricky), prop("b")], join="true")))
    new_src, fixed, _issues = convert(src)
    assert f"\t\t<Relevance>{tricky}</Relevance>\n\t\t<Relevance>b</Relevance>\n" in (
        new_src
    )
    assert fixed == ["E700"]


def test_group_relevance_outside_a_content_object_is_left_alone():
    src = bes(("Task", group([prop("a")]))).replace(
        "</BES>",
        "\t<Other>\n\t\t<Inner>\n"
        + group([prop("z")])
        + "\t\t</Inner>\n\t</Other>\n</BES>",
    )
    new_src, fixed, issues = convert(src)
    assert new_src == src
    assert fixed == []
    assert issues == ["W700"]


# --- files and the command line ---------------------------------------------


def write(tmp_path, name, content, newline="\n"):
    path = tmp_path / name
    path.write_bytes(content.replace("\n", newline).encode("utf-8"))
    return path


CONVERTIBLE = bes(("Task", group([prop("a"), prop("b")], join="false")))


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_check_file_preserves_line_endings(tmp_path, newline):
    path = write(tmp_path, "x.bes", CONVERTIBLE, newline)
    issues, fixed = hook.check_file(str(path))
    raw = path.read_bytes()
    assert b"<Relevance>(a) OR (b)</Relevance>" in raw
    if newline == "\r\n":
        assert raw.count(b"\n") == raw.count(b"\r\n")
    else:
        assert b"\r" not in raw
    assert [c for _l, c, _m in fixed] == ["E700"]
    assert issues == []


def test_check_mode_reports_and_does_not_write(tmp_path):
    path = write(tmp_path, "x.bes", CONVERTIBLE)
    issues, fixed = hook.check_file(str(path), check=True)
    assert path.read_text(encoding="utf-8") == CONVERTIBLE
    assert [c for _l, c, _m in issues] == ["E700"]
    assert fixed == []


def test_main_converts_then_is_clean(tmp_path, capsys):
    path = write(tmp_path, "x.bes", CONVERTIBLE)
    assert hook.main([str(path)]) == 1
    assert "[E700] auto-fixed:" in capsys.readouterr().out
    assert hook.main([str(path)]) == 0
    assert capsys.readouterr().out == ""


def test_main_check_exits_one_without_writing(tmp_path, capsys):
    path = write(tmp_path, "x.bes", CONVERTIBLE)
    assert hook.main(["--check", str(path)]) == 1
    assert "[E700]" in capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == CONVERTIBLE


def test_main_fails_on_unconvertible(tmp_path):
    path = write(tmp_path, "x.bes", bes(("Task", group([group_ref()]))))
    assert hook.main([str(path)]) == 1


def test_disable_e700_neither_converts_nor_reports(tmp_path):
    path = write(tmp_path, "x.bes", CONVERTIBLE)
    assert hook.main(["--disable", "E700", str(path)]) == 0
    assert path.read_text(encoding="utf-8") == CONVERTIBLE


def test_disable_e701_silences_group_reference(tmp_path):
    path = write(tmp_path, "x.bes", bes(("Task", group([group_ref()]))))
    assert hook.main(["--disable", "e701", str(path)]) == 0


def test_skip_marker_skips_the_file(tmp_path):
    content = CONVERTIBLE.replace("<BES ", f"<!-- {hook.SKIP_MARKER} -->\n<BES ", 1)
    path = write(tmp_path, "x.bes", content)
    assert hook.check_file(str(path)) == ([], [])
    assert path.read_text(encoding="utf-8") == content


def test_mustache_template_is_skipped(tmp_path):
    content = CONVERTIBLE.replace("<Title>Example</Title>", "<Title>{{name}}</Title>")
    path = write(tmp_path, "x.bes", content)
    assert hook.check_file(str(path)) == ([], [])


def test_unparsable_xml_is_an_advisory_w700(tmp_path):
    path = write(tmp_path, "x.bes", "<BES><Task><GroupRelevance></Task></BES>")
    issues, fixed = hook.check_file(str(path))
    assert [c for _l, c, _m in issues] == ["W700"]
    assert fixed == []
    assert hook.main([str(path)]) == 0
    assert hook.main(["--strict", str(path)]) == 1


def test_missing_file_is_w700(tmp_path):
    issues, _fixed = hook.check_file(str(tmp_path / "nope.bes"))
    assert [c for _l, c, _m in issues] == ["W700"]


def test_main_without_files_discovers_and_only_checks(tmp_path, monkeypatch):
    path = write(tmp_path, "x.bes", CONVERTIBLE)
    write(tmp_path, "ignored.txt", CONVERTIBLE)
    monkeypatch.chdir(tmp_path)
    assert hook.main([]) == 1
    assert path.read_text(encoding="utf-8") == CONVERTIBLE  # discovery never writes


def test_examples_end_to_end(tmp_path, capsys):
    for example in (FIXLET_EXAMPLE, ANALYSIS_EXAMPLE, TASK_EXAMPLE):
        shutil.copy(example, tmp_path / example.name)
    paths = [str(p) for p in sorted(tmp_path.iterdir())]
    assert hook.main(paths) == 1
    out = capsys.readouterr().out
    assert len(re.findall(r"\[E700\] auto-fixed", out)) == 3
    assert hook.main(paths) == 0


def test_conversion_that_would_break_the_schema_is_not_written(tmp_path, monkeypatch):
    pytest.importorskip("validate_bes_xml")
    path = write(tmp_path, "x.bes", TASK_EXAMPLE.read_text(encoding="utf-8"))
    original = path.read_bytes()
    real = hook.convert_group_relevance

    def breaking(src):
        new_src, converted, issues = real(src)
        # a second <Title> is well-formed but schema-invalid
        return (
            new_src.replace("</Title>", "</Title><Title>x</Title>", 1),
            converted,
            issues,
        )

    monkeypatch.setattr(hook, "convert_group_relevance", breaking)
    issues, fixed = hook.check_file(str(path))
    assert [c for _l, c, _m in issues] == ["E704"]
    assert fixed == []
    assert path.read_bytes() == original


def test_every_code_is_documented_everywhere():
    """Each code is in the docstring, the hook description and the README table."""
    root = Path(__file__).resolve().parent.parent
    hooks = (root / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    description = hooks.partition("- id: bes-relevance-convert-group")[2]
    readme = (root / "README.md").read_text(encoding="utf-8")
    for code in sorted(hook.KNOWN_CODES):
        assert code in hook.__doc__, f"{code} missing from the module docstring"
        assert code in description, f"{code} missing from .pre-commit-hooks.yaml"
        assert f"| `{code}` |" in readme, f"{code} missing from the README table"


# --- review fix: missing JoinByIntersection (PR #28) --------------------------


def test_missing_join_with_one_component_is_converted():
    """AND and OR of a single statement are the same, so no default is needed."""
    src = bes(("Task", group([prop("a")], join=None)))
    new_src, fixed, issues = convert(src)
    assert relevances(new_src) == ["a"]
    assert fixed == ["E700"]
    assert issues == []


def test_missing_join_message_says_what_to_add():
    src = bes(("Task", group([prop("a"), prop("b")], join=None)))
    _new_src, _fixed, issues = hook.convert_group_relevance(src)
    assert 'JoinByIntersection="true"' in issues[0][2]
    assert 'JoinByIntersection="false"' in issues[0][2]


def test_invalid_join_with_one_component_is_still_refused():
    src = bes(("Task", group([prop("a")], join="yes")))
    assert convert(src)[2] == ["E702"]
