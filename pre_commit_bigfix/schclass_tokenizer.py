#!/usr/bin/env python3
"""Tokenizer engine driven by a .schclass Schema (see schclass.py).

Walks input text exactly the way the console's SyntaxEdit control does:

    - `start:Tag` literals enter a state (comment, string, {...} relevance);
      inside it, `skip:Tag` escapes are consumed without ending the state
      (this is how `\\"` stays inside a string and a backslash-newline carries
      a state across lines), `end:Tag` literals end it (consumed), `@eol`
      ends it at the line break, and `end:separators` end it WITHOUT
      consuming the separator.
    - `token:tag` keyword literals match longest-first across every class
      visible in the current container (so `add nohash prefetch item` beats
      `add prefetch item` beats `prefetch`), bounded by the class's
      `token:start:separators` / `token:end:separators` (default: whitespace
      and line boundaries), and gated by `previous:tag` context (`@eol` =
      line start, `@specs` = a non-alphanumeric character).
    - `children` classes may begin inside a state (a url inside {...}); the
      containing state's token is emitted in segments around the child.
    - Text no class claims is emitted as `default` tokens, one per contiguous
      non-whitespace run. Default text is NEVER an engine error: a display
      grammar is total, and judging default text is the consumer's job (the
      ActionScript linter treats default text at line start as an unknown
      command verb).

Errors are emitted only for states that reach end of input with no legitimate
exit (no end tag seen and no `@eol` fallback) -- an unterminated state. States
that may end at `@eol` close with end_kind 'eol'/'eof' instead, and consumers
decide whether that matters (an eol-terminated {...} substitution is a lint
error; an eol-terminated // comment is normal).

Options (both off by default to stay console-faithful):
    case_insensitive  match tags/keywords regardless of case (the BigFix
                      agent accepts `RUN`; the console colorizer does not)
    relaxed_bol       weaken `@eol` in previous:tag from "column 0" to "only
                      whitespace precedes on this line" (real ActionScript
                      allows indented commands)
"""

import bisect
import dataclasses

from pre_commit_bigfix.schclass import AT_EOL, AT_SPECS

_DEFAULT_TOKEN_SEPARATORS = (" ", "\t")


@dataclasses.dataclass
class Token:
    """One lexed span of the input."""

    class_name: str  # lexClass name, or 'default'
    text: str  # exact source slice
    line: int  # 1-based start position
    col: int
    end_line: int
    end_col: int  # 1-based, exclusive
    end_kind: str  # 'tag' | 'separator' | 'eol' | 'eof' | 'token' | 'child'
    keyword: str = None  # canonical token:tag literal for keyword tokens


@dataclasses.dataclass
class TokenizeError:
    """A state entered but never legitimately exited."""

    line: int
    col: int
    class_name: str
    kind: str  # 'unterminated'
    message: str


@dataclasses.dataclass
class _Candidate:
    """A literal that can begin a token or state within some container."""

    literal: str  # canonical literal from the schema
    match: str  # what to compare against the text (lowered if insensitive)
    kind: str  # 'start' (enters a state) | 'token' (keyword)
    cls: object  # the owning LexClass


class Tokenizer:
    """Tokenizes text according to a loaded Schema."""

    def __init__(self, schema, case_insensitive=False, relaxed_bol=False):
        self.schema = schema
        self.case_insensitive = case_insensitive
        self.relaxed_bol = relaxed_bol
        root = schema.root()
        self._root_name = root.name if root is not None else None
        # candidate lists per container: the root sees every class parented to
        # it; a state with `children` sees the named child classes.
        self._candidates = {}
        if root is not None:
            self._candidates[root.name] = self._build_candidates(
                cls for cls in schema.classes.values() if root.name in cls.parents
            )
        for cls in schema.classes.values():
            if cls.children:
                self._candidates[cls.name] = self._build_candidates(
                    schema.classes[name]
                    for name in cls.children
                    if name in schema.classes
                )

    def _fold(self, literal):
        return literal.lower() if self.case_insensitive else literal

    def _build_candidates(self, classes):
        """Return per-first-char candidate index, longest literal first."""
        flat = []
        for cls in classes:
            for literal in cls.start_tags:
                flat.append(_Candidate(literal, self._fold(literal), "start", cls))
            for literal in cls.token_tags:
                flat.append(_Candidate(literal, self._fold(literal), "token", cls))
        flat.sort(key=lambda cand: -len(cand.literal))  # stable: schema order ties
        index = {}
        for cand in flat:
            if cand.match:
                index.setdefault(cand.match[0], []).append(cand)
        return index

    def tokenize(self, text):
        """Tokenize `text`; return (tokens, errors)."""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        low = text.lower() if self.case_insensitive else text
        length = len(text)
        line_starts = [0]
        for offset, char in enumerate(text):
            if char == "\n":
                line_starts.append(offset + 1)

        tokens = []
        errors = []
        stack = []  # [{cls, start, seg_start}] innermost state last
        state = {"pos": 0, "default_start": None}

        def line_col(offset):
            idx = bisect.bisect_right(line_starts, offset) - 1
            return idx + 1, offset - line_starts[idx] + 1

        def emit(class_name, start, end, end_kind, keyword=None):
            line, col = line_col(start)
            end_line, end_col = line_col(end)
            tokens.append(
                Token(
                    class_name,
                    text[start:end],
                    line,
                    col,
                    end_line,
                    end_col,
                    end_kind,
                    keyword,
                )
            )

        def flush_default(end):
            if state["default_start"] is not None and end > state["default_start"]:
                emit("default", state["default_start"], end, "separator")
            state["default_start"] = None

        def match_literal(literals, pos):
            """Longest matching literal from an iterable, or None."""
            best = None
            for literal in literals:
                if low.startswith(self._fold(literal), pos):
                    if best is None or len(literal) > len(best):
                        best = literal
            return best

        def at_bol(pos):
            line_start = line_starts[bisect.bisect_right(line_starts, pos) - 1]
            if self.relaxed_bol:
                return all(char in " \t" for char in text[line_start:pos])
            return pos == line_start

        def previous_ok(cls, pos):
            if not cls.previous_tags:
                return True
            for tag in cls.previous_tags:
                if tag == AT_EOL:
                    if at_bol(pos):
                        return True
                elif tag == AT_SPECS:
                    prev = text[pos - 1] if pos > 0 else ""
                    if prev and not (prev.isalnum() or prev == "_"):
                        return True
                elif pos >= len(tag) and text[pos - len(tag) : pos] == tag:
                    return True
            return False

        def token_boundaries(cls):
            start_seps, start_eol = cls.token_start_separators, cls.token_start_eol
            if not start_seps and not start_eol:
                start_seps, start_eol = _DEFAULT_TOKEN_SEPARATORS, True
            end_seps, end_eol = cls.token_end_separators, cls.token_end_eol
            if not end_seps and not end_eol:
                end_seps, end_eol = _DEFAULT_TOKEN_SEPARATORS, True
            return start_seps, start_eol, end_seps, end_eol

        def candidate_at(container_name, pos):
            index = self._candidates.get(container_name, {})
            for cand in index.get(low[pos], ()):
                if not low.startswith(cand.match, pos):
                    continue
                if not previous_ok(cand.cls, pos):
                    continue
                if cand.kind == "token":
                    start_seps, start_eol, end_seps, end_eol = token_boundaries(
                        cand.cls
                    )
                    if pos > 0:
                        prev = text[pos - 1]
                        if prev == "\n":
                            if not start_eol:
                                continue
                        elif prev not in start_seps:
                            continue
                    end = pos + len(cand.match)
                    if end < length:
                        nxt = text[end]
                        if nxt == "\n":
                            if not end_eol:
                                continue
                        elif nxt not in end_seps:
                            continue
                return cand
            return None

        def take_candidate(cand, pos):
            """Emit a keyword token or push a new state; return the new pos."""
            if cand.kind == "token":
                end = pos + len(cand.match)
                emit(cand.cls.name, pos, end, "token", keyword=cand.literal)
                return end
            stack.append({"cls": cand.cls, "start": pos, "seg_start": pos})
            return pos + len(cand.match)

        def pop_state(end, end_kind):
            """Emit the innermost state's pending segment and pop it."""
            top = stack.pop()
            if end > top["seg_start"]:
                emit(top["cls"].name, top["seg_start"], end, end_kind)
            if stack:
                stack[-1]["seg_start"] = end

        pos = 0
        while pos < length:
            if stack:
                cls = stack[-1]["cls"]
                skip = match_literal(cls.skip_tags, pos)
                if skip is not None:
                    pos += len(skip)
                    continue
                end_tag = match_literal(cls.end_tags, pos)
                if end_tag is not None:
                    pos += len(end_tag)
                    pop_state(pos, "tag")
                    continue
                if text[pos] == "\n":
                    if cls.end_at_eol or cls.end_separators_eol:
                        pop_state(pos, "eol")  # newline left to the container
                    else:
                        pos += 1  # multi-line state: newline is state content
                    continue
                separator = match_literal(cls.end_separators, pos)
                if separator is not None:
                    pop_state(pos, "separator")  # separator NOT consumed
                    continue
                if cls.children:
                    cand = candidate_at(cls.name, pos)
                    if cand is not None:
                        if pos > stack[-1]["seg_start"]:
                            emit(cls.name, stack[-1]["seg_start"], pos, "child")
                        stack[-1]["seg_start"] = pos
                        new_pos = take_candidate(cand, pos)
                        if stack[-1]["cls"] is cls:  # keyword child: resume after
                            stack[-1]["seg_start"] = new_pos
                        pos = new_pos
                        continue
                pos += 1
                continue

            char = text[pos]
            if char == "\n" or char in " \t":
                flush_default(pos)
                pos += 1
                continue
            cand = candidate_at(self._root_name, pos)
            if cand is not None:
                flush_default(pos)
                pos = take_candidate(cand, pos)
                continue
            if state["default_start"] is None:
                state["default_start"] = pos
            pos += 1

        flush_default(length)
        while stack:
            cls = stack[-1]["cls"]
            start = stack[-1]["start"]
            pop_state(length, "eof")
            if not (cls.end_at_eol or cls.end_separators_eol):
                line, col = line_col(start)
                errors.append(
                    TokenizeError(
                        line,
                        col,
                        cls.name,
                        "unterminated",
                        (
                            f"{cls.name} opened at {line}:{col} is never "
                            "terminated before end of input"
                        ),
                    )
                )
        return tokens, errors
