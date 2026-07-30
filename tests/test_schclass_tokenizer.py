#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/schclass_tokenizer.py (the tokenizer engine).

The engine walks the lexClass states of a loaded Schema: entered states
(comment/string/relevance) with their skip/end rules, keyword token matching
(longest-first, boundary-separated, optionally context-constrained by
previous:tag), URL child classes, and 'default' tokens for text no class
claims. Default text is never an engine error -- a display grammar is total;
error emission is reserved for states that can never legitimately exit
(no end tag reached, no @eol fallback) before end of input.

Most tests run against the real merged ActionScript grammar; a synthetic
schema exercises the unterminated-state error path the ActionScript grammar
cannot reach (all its states may end at @eol).
"""

import pytest

from pre_commit_bigfix import schclass
from pre_commit_bigfix.schclass_tokenizer import Tokenizer

SCHEMA = schclass.load_default_actionscript_schema()


def tokenize(text, **kwargs):
    return Tokenizer(SCHEMA, **kwargs).tokenize(text)


def kinds(tokens):
    return [token.class_name for token in tokens]


# --- comments ---------------------------------------------------------------


def test_comment_runs_to_eol():
    tokens, errors = tokenize("// hello world\nrun x\n")
    assert errors == []
    assert tokens[0].class_name == "comment"
    assert tokens[0].text == "// hello world"
    assert tokens[0].end_kind == "eol"


def test_comment_then_keyword_lines():
    tokens, errors = tokenize("// hello\nrun x\n")
    assert errors == []
    assert kinds(tokens) == ["comment", "keywords", "default"]
    assert tokens[1].keyword == "run"
    assert tokens[1].line == 2


def test_comment_backslash_continues_to_next_line():
    tokens, errors = tokenize("// part one \\\npart two\nrun x\n")
    assert errors == []
    assert tokens[0].class_name == "comment"
    assert tokens[0].line == 1
    assert tokens[0].end_line == 2
    assert "part two" in tokens[0].text
    assert tokens[1].keyword == "run"
    assert tokens[1].line == 3


# --- strings ----------------------------------------------------------------


def test_string_basic():
    tokens, errors = tokenize('run "hello"\n')
    assert errors == []
    assert kinds(tokens) == ["keywords", "string"]
    assert tokens[1].text == '"hello"'
    assert tokens[1].end_kind == "tag"


def test_string_escaped_quote_stays_inside():
    tokens, errors = tokenize('run "a\\"b"\n')
    assert errors == []
    string = tokens[1]
    assert string.class_name == "string"
    assert string.text == '"a\\"b"'
    assert string.end_kind == "tag"


def test_string_unterminated_ends_at_eol():
    tokens, errors = tokenize('run "abc\nwait x\n')
    assert errors == []  # @eol is a legitimate exit for the display grammar
    string = tokens[1]
    assert string.class_name == "string"
    assert string.end_kind == "eol"
    assert tokens[2].keyword == "wait"


def test_string_backslash_newline_continues():
    tokens, errors = tokenize('run "abc\\\ndef"\n')
    assert errors == []
    string = tokens[1]
    assert string.class_name == "string"
    assert string.end_kind == "tag"
    assert string.line == 1
    assert string.end_line == 2


def test_string_cut_by_eof_ends_eof_without_error():
    tokens, errors = tokenize('run "abc')
    assert errors == []
    assert tokens[1].class_name == "string"
    assert tokens[1].end_kind == "eof"


# --- relevance substitutions -------------------------------------------------


def test_relevance_basic():
    tokens, errors = tokenize('if {exists file "c:\\x"}\n')
    assert errors == []
    assert tokens[0].keyword == "if"
    relevance = [t for t in tokens if t.class_name == "relevance"]
    assert relevance and relevance[-1].end_kind == "tag"


def test_relevance_unterminated_ends_at_eol():
    tokens, errors = tokenize("run {pathname of client folder\n")
    assert errors == []
    relevance = [t for t in tokens if t.class_name == "relevance"]
    assert relevance[-1].end_kind == "eol"


def test_relevance_url_child_segments():
    tokens, errors = tokenize("wait {a http://x.com b}\n")
    assert errors == []
    classes = kinds(tokens)
    assert "url" in classes
    url = tokens[classes.index("url")]
    assert url.text == "http://x.com"
    # the relevance state resumes after the child and still closes on '}'
    assert [t.end_kind for t in tokens if t.class_name == "relevance"][-1] == "tag"


def test_relevance_url_child_does_not_swallow_closing_brace():
    # the override adds '}' to the url end separators for exactly this shape
    tokens, errors = tokenize("wait {download of http://x.com/f}\n")
    assert errors == []
    relevance = [t for t in tokens if t.class_name == "relevance"]
    assert relevance[-1].end_kind == "tag"


# --- keywords ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("add nohash prefetch item name=x\n", "add nohash prefetch item"),
        ("add prefetch item name=x\n", "add prefetch item"),
        ("prefetch f.exe sha1:x size:1 http://x\n", "prefetch"),
        ("download now as f.exe\n", "download now as"),
        ("download as f.exe\n", "download as"),
        ("download http://x\n", "download"),
        ('setting delete "x" on "y"\n', "setting delete"),
        ('setting "x"="1" on "y"\n', "setting"),
        ("elseif {true}\n", "elseif"),
        ('action parameter query "x" with description "y"\n', "action parameter query"),
        ("surrender device id\n", "surrender device id"),
    ],
)
def test_keyword_longest_match_first(line, expected):
    tokens, errors = tokenize(line)
    assert errors == []
    assert tokens[0].keyword == expected


def test_keyword_boundary_runhidden_not_run():
    tokens, _ = tokenize("runhidden foo.exe\n")
    assert tokens[0].keyword == "runhidden"


def test_running_is_default_text():
    tokens, _ = tokenize("running foo\n")
    assert tokens[0].class_name == "default"
    assert tokens[0].text == "running"
    assert tokens[0].keyword is None


def test_keyword_not_matched_after_equals():
    tokens, _ = tokenize("name=run x\n")
    assert tokens[0].class_name == "default"
    assert tokens[0].text == "name=run"


def test_if_immediately_followed_by_brace():
    tokens, errors = tokenize("if{exists x}\n")
    assert errors == []
    assert tokens[0].keyword == "if"
    assert tokens[1].class_name == "relevance"


def test_url_matches_after_keyword_and_space():
    tokens, errors = tokenize("download http://example.com/f.exe\n")
    assert errors == []
    assert tokens[0].keyword == "download"
    assert tokens[1].class_name == "url"
    assert tokens[1].text == "http://example.com/f.exe"


def test_https_url_matches_via_override():
    tokens, errors = tokenize("download https://example.com/f.exe\n")
    assert errors == []
    assert tokens[1].class_name == "url_https"


# --- previous:tag (@eol) strict vs relaxed -----------------------------------


def test_previous_tag_eol_strict_rejects_indented_download():
    tokens, _ = tokenize("  download http://x\n")
    assert tokens[0].class_name == "default"
    assert tokens[0].text == "download"


def test_relaxed_bol_accepts_indented_download():
    tokens, _ = tokenize("  download http://x\n", relaxed_bol=True)
    assert tokens[0].keyword == "download"
    assert tokens[0].col == 3


def test_relaxed_bol_rejects_download_after_text():
    tokens, _ = tokenize("echo download x\n", relaxed_bol=True)
    assert tokens[0].class_name == "default"
    assert tokens[1].class_name == "default"
    assert tokens[1].text == "download"


def test_indented_plain_keyword_matches_even_strict():
    # the `keywords` class has no previous:tag, and ' ' is a start separator
    tokens, _ = tokenize("    wait foo.exe\n")
    assert tokens[0].keyword == "wait"


# --- case sensitivity ---------------------------------------------------------


def test_case_sensitive_by_default():
    tokens, _ = tokenize("RUN foo\n")
    assert tokens[0].class_name == "default"


def test_case_insensitive_flag_matches_upper():
    tokens, _ = tokenize("RUN foo\n", case_insensitive=True)
    assert tokens[0].class_name == "keywords"
    assert tokens[0].keyword == "run"  # canonical tag
    assert tokens[0].text == "RUN"  # source text preserved


# --- positions ----------------------------------------------------------------


def test_token_positions_are_one_based():
    tokens, _ = tokenize("run x\nwait y\n")
    run, x, wait, y = tokens
    assert (run.line, run.col, run.end_line, run.end_col) == (1, 1, 1, 4)
    assert (x.line, x.col) == (1, 5)
    assert (wait.line, wait.col) == (2, 1)
    assert (y.line, y.col) == (2, 6)


def test_crlf_input_positions():
    tokens, errors = tokenize("run x\r\nwait y\r\n")
    assert errors == []
    assert [t.keyword for t in tokens if t.keyword] == ["run", "wait"]
    assert tokens[2].line == 2


# --- unterminated-state errors (synthetic grammar) ----------------------------


BLOCK_SCHEMA = schclass.parse_schclass_text(
    "lexClass:\n"
    "\tname = global\n"
    "\tparent:file = <*.Test>\n"
    "lexClass:\n"
    "\tname = blockcomment\n"
    "\tparent = global\n"
    "\tstart:Tag = '/*'\n"
    "\tend:Tag = '*/'\n"
)


def test_block_state_spans_lines_and_closes():
    tokens, errors = Tokenizer(BLOCK_SCHEMA).tokenize("a /* one\ntwo */ b\n")
    assert errors == []
    block = [t for t in tokens if t.class_name == "blockcomment"]
    assert len(block) == 1
    assert block[0].text == "/* one\ntwo */"
    assert block[0].end_kind == "tag"


def test_block_state_unterminated_at_eof_is_error():
    tokens, errors = Tokenizer(BLOCK_SCHEMA).tokenize("a /* never closed\nmore\n")
    assert len(errors) == 1
    assert errors[0].class_name == "blockcomment"
    assert errors[0].kind == "unterminated"
    assert (errors[0].line, errors[0].col) == (1, 3)
    block = [t for t in tokens if t.class_name == "blockcomment"]
    assert block[0].end_kind == "eof"


# --- default tokens ------------------------------------------------------------


def test_default_tokens_split_per_word():
    tokens, errors = tokenize("frobnicate the widget\n")
    assert errors == []
    assert [t.text for t in tokens] == ["frobnicate", "the", "widget"]
    assert {t.class_name for t in tokens} == {"default"}


def test_empty_and_whitespace_only_input():
    assert tokenize("") == ([], [])
    tokens, errors = tokenize(" \t \n\n  \n")
    assert (tokens, errors) == ([], [])
