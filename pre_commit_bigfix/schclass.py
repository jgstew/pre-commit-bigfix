#!/usr/bin/env python3
"""Generic loader for .schclass lexer-schema files.

The .schclass format is the lex-schema format of the Codejock Xtreme
ToolkitPro SyntaxEdit control, which the BigFix console embeds for its
ActionScript editor. A schema is a series of `lexClass:` blocks, each an
indented list of `key = value` lines describing one lexical class: how the
class is entered (`start:Tag` literals or `token:tag` keyword lists), how it
ends (`end:Tag` literals / `end:separators`), escape sequences consumed
without ending it (`skip:Tag`), context constraints on where it may begin
(`previous:tag`), token boundary separators, and parent/child containment.

This module only LOADS schemas; pre_commit_bigfix/schclass_tokenizer.py walks
them. Nothing here is ActionScript-specific except the convenience default
loader at the bottom.

Loading supports merging several files so a small override schema can
supplement a vendored base grammar (same-named classes union their token
lists; explicitly-set fields replace; new classes append). This matters
because .schclass files are display grammars, not validation grammars, and
need small corrections for lint use (see schclass_data/bigfix_overrides.schclass).

Format notes pinned by tests (and by the real console-generated file):
    - keys are case-insensitive (`start:tag` and `start:Tag` both occur)
    - values are comma-separated items: quoted strings (with backslash
      escapes: \\ \' \" \n \r \t), @specials (@eol, @specs), or bare tokens
    - repeated `token:tag` lines accumulate, even across blank lines and
      interleaved with other keys
    - `children = 0` means "no children"
    - // comment lines are ignored
    - files may be CRLF or LF
"""

import dataclasses
import os

# @-special sentinels used in previous:tag lists (plain strings; a literal
# "@eol" token text cannot occur, so identity-by-value is safe)
AT_EOL = "@eol"
AT_SPECS = "@specs"

_ESCAPES = {"\\": "\\", "'": "'", '"': '"', "n": "\n", "r": "\r", "t": "\t"}

_DATA_DIR = os.path.join(os.path.dirname(__file__), "schclass_data")
# resolved relative to __file__ (not importlib.resources): fine for pip /
# pre-commit installs; would not survive zip-import, which none of our
# consumers use.
DEFAULT_SCHCLASS_FILES = (
    os.path.join(_DATA_DIR, "ExpandedActionScript.schclass"),
    os.path.join(_DATA_DIR, "bigfix_overrides.schclass"),
)


@dataclasses.dataclass
class LexClass:
    """One `lexClass:` block: a single lexical class of the grammar."""

    name: str = ""
    parents: tuple = ()  # from `parent` / `parent:dyn`
    parent_dyn: bool = False
    parent_file: str = None  # e.g. `<*.ActionScript>` on the root class
    children: tuple = ()  # `children = 0` -> ()
    start_tags: tuple = ()  # literals that enter this class as a state
    end_tags: tuple = ()  # literals that exit the state (consumed)
    end_at_eol: bool = False  # @eol appeared in end:Tag
    skip_tags: tuple = ()  # escape sequences consumed without ending
    end_separators: tuple = ()  # exit the state WITHOUT consuming
    end_separators_eol: bool = False
    previous_tags: tuple = ()  # context constraint; may hold AT_EOL/AT_SPECS
    token_tags: tuple = ()  # keyword literals (accumulated)
    token_start_separators: tuple = ()
    token_start_eol: bool = False
    token_end_separators: tuple = ()
    token_end_eol: bool = False
    attrs: dict = dataclasses.field(default_factory=dict)  # DisplayName, txt:*


@dataclasses.dataclass
class Schema:
    """An ordered collection of LexClasses parsed from .schclass text."""

    classes: dict = dataclasses.field(default_factory=dict)

    def root(self):
        """Return the file-level root class (`parent:file`), or best guess."""
        for cls in self.classes.values():
            if cls.parent_file is not None:
                return cls
        for cls in self.classes.values():
            if not cls.parents:
                return cls
        return next(iter(self.classes.values()), None)

    def all_token_tags(self):
        """Return {token literal: class name} across every class.

        The first class declaring a literal wins (schema order).
        """
        tags = {}
        for cls in self.classes.values():
            for token in cls.token_tags:
                tags.setdefault(token, cls.name)
        return tags


def _split_items(value):
    """Split a raw value into (kind, text) items; kind is 'str' or 'bare'.

    Items are comma-separated at the top level; commas INSIDE quotes (the
    separator lists include a literal ',') must not split. Quoted items decode
    backslash escapes; bare items are kept verbatim (`@eol`, `global`,
    `0x0000FF`, `<*.ActionScript>`).
    """
    items = []
    i, n = 0, len(value)
    while i < n:
        ch = value[i]
        if ch in " \t,":
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            i += 1
            buf = []
            while i < n:
                char = value[i]
                if char == "\\" and i + 1 < n:
                    buf.append(_ESCAPES.get(value[i + 1], value[i + 1]))
                    i += 2
                    continue
                if char == quote:
                    i += 1
                    break
                buf.append(char)
                i += 1
            items.append(("str", "".join(buf)))
        else:
            j = i
            while j < n and value[j] != ",":
                j += 1
            items.append(("bare", value[i:j].strip()))
            i = j
    return items


def _literals(items):
    """Return the quoted-string literals from a parsed item list."""
    return tuple(text for kind, text in items if kind == "str")


def _has_bare(items, token):
    """True if `items` holds the bare token `token` (case-insensitive)."""
    return any(kind == "bare" and text.lower() == token for kind, text in items)


def _apply_key(cls, key, items, raw_value):
    """Fold one `key = value` line into the LexClass being built."""
    if key == "name":
        cls.name = raw_value
    elif key == "parent":
        cls.parents += tuple(text for _kind, text in items)
    elif key == "parent:dyn":
        cls.parents += tuple(text for _kind, text in items)
        cls.parent_dyn = True
    elif key == "parent:file":
        cls.parent_file = raw_value
    elif key == "children":
        if not _has_bare(items, "0"):
            cls.children += tuple(text for _kind, text in items)
    elif key == "start:tag":
        cls.start_tags += _literals(items)
    elif key == "end:tag":
        cls.end_tags += _literals(items)
        cls.end_at_eol = cls.end_at_eol or _has_bare(items, AT_EOL)
    elif key == "skip:tag":
        cls.skip_tags += _literals(items)
    elif key == "end:separators":
        cls.end_separators += _literals(items)
        cls.end_separators_eol = cls.end_separators_eol or _has_bare(items, AT_EOL)
    elif key == "previous:tag":
        for kind, text in items:
            if kind == "bare" and text.lower() in (AT_EOL, AT_SPECS):
                cls.previous_tags += (text.lower(),)
            elif kind == "str":
                cls.previous_tags += (text,)
    elif key == "token:tag":
        cls.token_tags += _literals(items)
    elif key == "token:start:separators":
        cls.token_start_separators += _literals(items)
        cls.token_start_eol = cls.token_start_eol or _has_bare(items, AT_EOL)
    elif key == "token:end:separators":
        cls.token_end_separators += _literals(items)
        cls.token_end_eol = cls.token_end_eol or _has_bare(items, AT_EOL)
    else:
        # presentation / unknown keys (DisplayName, txt:*, ParseOnScreen...)
        decoded = [text for _kind, text in items]
        cls.attrs[key] = ", ".join(decoded) if decoded else raw_value


def parse_schclass_text(text):
    """Parse .schclass text into a Schema."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    schema = Schema()
    current = None
    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if stripped.lower().startswith("lexclass:"):
            if current is not None and current.name:
                schema.classes[current.name] = current
            current = LexClass()
            continue
        if current is None or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip().lower()
        value = value.strip()
        _apply_key(current, key, _split_items(value), value)
    if current is not None and current.name:
        schema.classes[current.name] = current
    return schema


# (list field, paired eol/dyn flag) -- a merge replaces the pair together when
# the override sets either half, so `end:Tag = '"'` (no @eol) clears the flag.
_PAIRED_FIELDS = (
    ("parents", "parent_dyn"),
    ("start_tags", None),
    ("end_tags", "end_at_eol"),
    ("skip_tags", None),
    ("end_separators", "end_separators_eol"),
    ("previous_tags", None),
    ("token_start_separators", "token_start_eol"),
    ("token_end_separators", "token_end_eol"),
    ("children", None),
)


def merge_schemas(base, override):
    """Merge `override` onto `base`; return a new Schema.

    Same-named classes: token_tags are unioned (base order, then new ones);
    any field group the override explicitly sets replaces the base's; fields
    the override leaves unset are preserved. New classes append after the
    base's, keeping schema order deterministic.
    """
    merged = Schema()
    for name, cls in base.classes.items():
        merged.classes[name] = dataclasses.replace(cls, attrs=dict(cls.attrs))
    for name, ocls in override.classes.items():
        if name not in merged.classes:
            merged.classes[name] = dataclasses.replace(ocls, attrs=dict(ocls.attrs))
            continue
        bcls = merged.classes[name]
        bcls.token_tags += tuple(
            token for token in ocls.token_tags if token not in bcls.token_tags
        )
        for list_field, flag_field in _PAIRED_FIELDS:
            flag_set = flag_field is not None and getattr(ocls, flag_field)
            if getattr(ocls, list_field) or flag_set:
                setattr(bcls, list_field, getattr(ocls, list_field))
                if flag_field is not None:
                    setattr(bcls, flag_field, getattr(ocls, flag_field))
        if ocls.parent_file is not None:
            bcls.parent_file = ocls.parent_file
        bcls.attrs.update(ocls.attrs)
    return merged


def load_schclass_files(paths):
    """Parse each .schclass file and merge them left to right into one Schema."""
    schema = None
    for path in paths:
        with open(path, "rb") as handle:
            text = handle.read().decode("utf-8", errors="replace")
        parsed = parse_schclass_text(text)
        schema = parsed if schema is None else merge_schemas(schema, parsed)
    return schema if schema is not None else Schema()


def load_default_actionscript_schema():
    """Load the vendored BigFix ActionScript grammar plus its overrides."""
    return load_schclass_files(DEFAULT_SCHCLASS_FILES)
