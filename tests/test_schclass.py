#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/schclass.py (the generic .schclass loader).

The .schclass format is the lex-schema format of the Codejock SyntaxEdit
control embedded in the BigFix console. These tests pin the parsing rules to
the constructs that actually appear in the vendored ExpandedActionScript
grammar (plus // comment lines, used by the override file), the merge
semantics that let a small override file supplement the base grammar, and the
shape of the default merged ActionScript schema.
"""

import os

import pre_commit_bigfix
from pre_commit_bigfix import schclass

DATA_DIR = os.path.join(os.path.dirname(pre_commit_bigfix.__file__), "schclass_data")
VENDORED = os.path.join(DATA_DIR, "ExpandedActionScript.schclass")
OVERRIDES = os.path.join(DATA_DIR, "bigfix_overrides.schclass")


# --- basic block / key parsing ---------------------------------------------


def test_parse_single_class_name_parent():
    schema = schclass.parse_schclass_text(
        "lexClass:\n"
        "\tname\t= global\n"
        "\n"
        "lexClass:\n"
        "\tname\t= comment\n"
        "\tparent\t= global\n"
    )
    assert list(schema.classes) == ["global", "comment"]
    assert schema.classes["comment"].parents == ("global",)
    assert schema.classes["comment"].parent_dyn is False


def test_parse_parent_dyn():
    schema = schclass.parse_schclass_text(
        "lexClass:\n\tname = string\n\tparent:dyn = global\n"
    )
    assert schema.classes["string"].parents == ("global",)
    assert schema.classes["string"].parent_dyn is True


def test_parse_root_class_parent_file():
    schema = schclass.parse_schclass_text(
        "lexClass: \n"  # trailing space after the colon, as in the real file
        "\tname\t\t\t= global\n"
        "\tparent:file\t\t= <*.ActionScript>\n"
    )
    cls = schema.classes["global"]
    assert cls.parent_file == "<*.ActionScript>"
    assert schema.root() is cls


def test_escape_decoding():
    schema = schclass.parse_schclass_text(
        "lexClass:\n"
        "\tname = string\n"
        "\tskip:Tag = '\\\\\"', '\\\\\\r\\n', '\\\\\\n'\n"
    )
    # the three items decode to: backslash+quote, backslash+CR+LF, backslash+LF
    assert schema.classes["string"].skip_tags == ('\\"', "\\\r\n", "\\\n")


def test_end_tag_eol_flag():
    schema = schclass.parse_schclass_text(
        "lexClass:\n\tname = string\n\tend:Tag = '\"', @eol\n"
    )
    cls = schema.classes["string"]
    assert cls.end_tags == ('"',)
    assert cls.end_at_eol is True


def test_end_separators_eol_only():
    schema = schclass.parse_schclass_text(
        "lexClass:\n\tname = comment\n\tend:separators = @eol\n"
    )
    cls = schema.classes["comment"]
    assert cls.end_separators == ()
    assert cls.end_separators_eol is True


def test_separator_lists_with_eol():
    # keywords-style separators: ',' is a start separator but not an end one,
    # and quoted commas must not confuse the comma-splitting of the list
    schema = schclass.parse_schclass_text(
        "lexClass:\n"
        "\tname = keywords\n"
        "\ttoken:start:separators\t= ' ', '\\t', ':', ',', '{', '}', @eol\n"
        "\ttoken:end:separators\t= ' ', '\\t', ':', '{', '}', @eol\n"
    )
    cls = schema.classes["keywords"]
    assert cls.token_start_separators == (" ", "\t", ":", ",", "{", "}")
    assert cls.token_start_eol is True
    assert cls.token_end_separators == (" ", "\t", ":", "{", "}")
    assert cls.token_end_eol is True
    assert "," not in cls.token_end_separators


def test_key_case_insensitive():
    # the real file mixes `start:tag` (comment) and `start:Tag` (string)
    schema = schclass.parse_schclass_text(
        "lexClass:\n\tname = a\n\tstart:tag = '//'\n"
        "lexClass:\n\tname = b\n\tstart:Tag = '\"'\n"
    )
    assert schema.classes["a"].start_tags == ("//",)
    assert schema.classes["b"].start_tags == ('"',)


def test_token_tag_accumulates_across_blank_lines_and_other_keys():
    # the real keywords class interleaves token:tag entries with blank lines
    # and places more token:tag lines AFTER the separator/color keys
    schema = schclass.parse_schclass_text(
        "lexClass:\n"
        "\tname = keywords\n"
        "\ttoken:tag = 'run'\n"
        "\n"
        "\ttoken:tag = 'wait'\n"
        "\ttoken:start:separators = ' ', @eol\n"
        "\ttxt:colorFG = 0x0000FF\n"
        "\ttoken:tag = 'activate lpar'\n"
    )
    assert schema.classes["keywords"].token_tags == ("run", "wait", "activate lpar")


def test_previous_tag_sentinels():
    schema = schclass.parse_schclass_text(
        "lexClass:\n\tname = url\n\tprevious:tag = @specs, ' ', '\\t', @eol\n"
    )
    assert schema.classes["url"].previous_tags == (
        schclass.AT_SPECS,
        " ",
        "\t",
        schclass.AT_EOL,
    )


def test_children_zero_means_none():
    schema = schclass.parse_schclass_text(
        "lexClass:\n\tname = keywords\n\tchildren = 0\n"
        "lexClass:\n\tname = relevance\n\tchildren = url\n"
    )
    assert schema.classes["keywords"].children == ()
    assert schema.classes["relevance"].children == ("url",)


def test_unknown_keys_kept_in_attrs():
    schema = schclass.parse_schclass_text(
        "lexClass:\n"
        "\tname = comment\n"
        "\ttxt:colorFG\t= 0x00A000\n"
        "\tDisplayName\t\t= 'Comment (Single-Line)'\n"
        "\tParseOnScreen = 0\n"
    )
    attrs = schema.classes["comment"].attrs
    assert attrs["txt:colorfg"] == "0x00A000"
    assert attrs["displayname"] == "Comment (Single-Line)"
    assert attrs["parseonscreen"] == "0"


def test_comment_lines_ignored():
    # the override file carries a // comment header; the loader must skip it
    schema = schclass.parse_schclass_text(
        "// a header comment\n" "// another line\n" "lexClass:\n" "\tname = global\n"
    )
    assert list(schema.classes) == ["global"]


def test_crlf_and_lf_equivalent():
    lf_text = "lexClass:\n\tname = a\n\ttoken:tag = 'run'\n"
    crlf_text = lf_text.replace("\n", "\r\n")
    assert schclass.parse_schclass_text(lf_text) == schclass.parse_schclass_text(
        crlf_text
    )


# --- the real vendored grammar ---------------------------------------------


def test_parse_vendored_file():
    schema = schclass.load_schclass_files([VENDORED])
    assert list(schema.classes) == [
        "global",
        "comment",
        "string",
        "relevance",
        "url",
        "download_now_as",
        "download_as",
        "download",
        "setting_delete",
        "setting",
        "keywords",
    ]
    assert schema.root().name == "global"
    assert schema.root().parent_file == "<*.ActionScript>"

    comment = schema.classes["comment"]
    assert comment.start_tags == ("//",)
    assert comment.end_separators_eol is True
    assert "\\\r\n" in comment.skip_tags

    string = schema.classes["string"]
    assert string.start_tags == ('"',)
    assert string.end_tags == ('"',)
    assert string.end_at_eol is True
    assert '\\"' in string.skip_tags

    relevance = schema.classes["relevance"]
    assert relevance.start_tags == ("{",)
    assert relevance.end_tags == ("}",)
    assert relevance.end_at_eol is True
    assert relevance.children == ("url",)

    url = schema.classes["url"]
    assert url.start_tags == ("http:",)
    assert url.previous_tags == (schclass.AT_SPECS, " ", "\t", schclass.AT_EOL)

    download = schema.classes["download"]
    assert download.previous_tags == (schclass.AT_EOL,)
    assert download.token_tags == ("download",)

    keywords = schema.classes["keywords"]
    assert len(keywords.token_tags) == 318
    assert "add nohash prefetch item" in keywords.token_tags
    assert "wipe traveler data" in keywords.token_tags  # after the color key
    assert keywords.token_start_eol is True
    assert "," in keywords.token_start_separators
    assert "," not in keywords.token_end_separators

    # 318 keywords + the 5 single-token classes = 323 verbs total
    assert len(schema.all_token_tags()) == 323


# --- merge semantics --------------------------------------------------------


def test_merge_appends_keywords():
    base = schclass.parse_schclass_text(
        "lexClass:\n\tname = keywords\n\ttoken:tag = 'run'\n\ttoken:tag = 'wait'\n"
        "\ttoken:start:separators = ' ', @eol\n"
    )
    override = schclass.parse_schclass_text(
        "lexClass:\n\tname = keywords\n\ttoken:tag = 'surrender device id'\n"
    )
    merged = schclass.merge_schemas(base, override)
    cls = merged.classes["keywords"]
    assert cls.token_tags == ("run", "wait", "surrender device id")
    # fields the override leaves unset are preserved from the base
    assert cls.token_start_separators == (" ",)
    assert cls.token_start_eol is True


def test_merge_dedupes_keywords():
    base = schclass.parse_schclass_text(
        "lexClass:\n\tname = keywords\n\ttoken:tag = 'run'\n"
    )
    override = schclass.parse_schclass_text(
        "lexClass:\n\tname = keywords\n\ttoken:tag = 'run'\n\ttoken:tag = 'wait'\n"
    )
    merged = schclass.merge_schemas(base, override)
    assert merged.classes["keywords"].token_tags == ("run", "wait")


def test_merge_adds_new_class():
    base = schclass.parse_schclass_text("lexClass:\n\tname = global\n")
    override = schclass.parse_schclass_text(
        "lexClass:\n\tname = url_https\n\tparent:dyn = global\n"
        "\tstart:Tag = 'https:'\n"
    )
    merged = schclass.merge_schemas(base, override)
    assert list(merged.classes) == ["global", "url_https"]
    assert merged.classes["url_https"].start_tags == ("https:",)


def test_merge_override_replaces_set_fields():
    base = schclass.parse_schclass_text(
        "lexClass:\n\tname = url\n\tstart:Tag = 'http:'\n" "\tprevious:tag = @eol\n"
    )
    override = schclass.parse_schclass_text(
        "lexClass:\n\tname = url\n\tstart:Tag = 'http:', 'https:'\n"
    )
    merged = schclass.merge_schemas(base, override)
    cls = merged.classes["url"]
    assert cls.start_tags == ("http:", "https:")
    assert cls.previous_tags == (schclass.AT_EOL,)  # untouched


def test_load_schclass_files_folds_left_to_right(tmp_path):
    one = tmp_path / "one.schclass"
    two = tmp_path / "two.schclass"
    one.write_text("lexClass:\n\tname = keywords\n\ttoken:tag = 'run'\n")
    two.write_text("lexClass:\n\tname = keywords\n\ttoken:tag = 'wait'\n")
    merged = schclass.load_schclass_files([str(one), str(two)])
    assert merged.classes["keywords"].token_tags == ("run", "wait")


# --- the default merged ActionScript schema ---------------------------------


def test_load_default_schema_has_https_and_surrender():
    schema = schclass.load_default_actionscript_schema()
    assert "surrender device id" in schema.classes["keywords"].token_tags
    assert schema.classes["url_https"].start_tags == ("https:",)
    # base verbs still present after the merge
    assert "add nohash prefetch item" in schema.classes["keywords"].token_tags
    assert schema.all_token_tags()["download now as"] == "download_now_as"
    assert len(schema.all_token_tags()) == 324


def test_override_file_exists_and_parses():
    schema = schclass.load_schclass_files([OVERRIDES])
    assert "surrender device id" in schema.classes["keywords"].token_tags
