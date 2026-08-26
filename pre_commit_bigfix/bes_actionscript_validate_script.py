#!/usr/bin/env python3
"""Pre-commit hook: validate ActionScript block balance in BES files.

Checks every <ActionScript> body of a BES file (and, for non-.bes/.ojo paths,
the whole file read as one raw ActionScript body) for balanced `if`/`endif`
and `begin prefetch block`/`end prefetch block` pairing. This is the sibling
hook named in bes_actionscript_lint_schclass.py's SCOPE note: checks that need
knowledge the lexical grammar does not carry -- pairing, ordering, and block
interleaving -- live here instead. It is meant to grow more per-script checks
over time; the balance walk is the first.

An unbalanced block is a real defect, not a style nit: the BigFix agent fails
the action at runtime on a dangling `if`, and a missing `endif` silently
changes which statements are conditional.

Checks:
    E500  an `if` is never closed by a matching `endif`
    E501  an `endif` with no open `if`
    E502  a `begin prefetch block` is never closed by `end prefetch block`
    E503  an `end prefetch block` with no open `begin prefetch block`
    E504  a `begin prefetch block` nested inside another one (prefetch blocks
          do not nest)
    E505  an `else` or `elseif` outside any open `if`
    E506  an `elseif` after `else`, or a second `else` for the same `if`
    E507  an `if` opened inside a prefetch block is still open when that
          block's `end prefetch block` is reached -- blocks interleave, they
          do not nest, so this cannot close cleanly
    E508  a `{` relevance substitution has no closing `}` before the end of
          its line (a substitution cannot span lines); `}}` inside the
          substitution is a literal `}` and does not close it
    E509  a `}` with no `{` relevance substitution open on that line.
          `appendfile <content>` lines are exempt from both E508 and E509 --
          everything after the verb is one line of raw file content written
          out verbatim (`appendfile }` appends a literal `}`), not
          ActionScript. A regex interval quantifier's braces (`{40}`,
          `{1,3}`, `{2,}` -- common in a `regex "..."` literal used to pull
          a sha1/sha256/size/url back out of a matched line) are skipped
          whole and never count as an open or a close
    E510  an `add prefetch item` / `add nohash prefetch item` outside an open
          `begin prefetch block` (the agent rejects these outside a block)
    E511  a `collect prefetch items` outside an open prefetch block
    E512  two prefetch/download producers declare the same download name in
          the exact same conditional context (both unconditional, or both
          reached through identical if/elseif/else branch choices) -- the
          second silently overwrites the first. Declarations reached via
          different `if`s (even ones that look platform-exclusive, like a
          separate `if` per OS) are NOT compared: this checker cannot verify
          their conditions are mutually exclusive, and BigFix content
          routinely relies on exactly that pattern for cross-platform
          prefetch blocks. Also NOT flagged: two declarations whose sha1/
          sha256/size all match -- mirror URLs for the identical file,
          where either one satisfies the download
    E513  a command references `__Download\\<name>` but nothing prefetches or
          downloads a file of that name (a typo catcher; skipped entirely
          when any producer's names are unknowable -- see below. `delete` and
          `folder delete` lines are cleanup, not consumption, and never
          count. A reference containing a glob wildcard, e.g.
          `__Download\\mysql*rpm`, is never flagged -- the shell matches it
          at runtime, not this checker)
    E514  an `if` or `elseif` whose condition is not a `{...}` relevance
          substitution (`if true`, bare `if`; the agent requires one)
    E515  a `begin prefetch block` that is not at the top of the script --
          only blank lines, `//` comments, `action parameter query` lines,
          and `parameter` assignments may precede it. Plain `prefetch`
          statements are NOT placement-checked; they are legal anywhere
    E516  two `parameter "name" = ...` assignments to the same name that can
          co-execute (see E512's co-executable rule -- assignments in
          different `if`/`elseif`/`else` branches are not compared): action
          parameters are write-once, and the second assignment silently
          overwrites the first
    E517  a `parameter "name"` substitution is referenced before the line
          that assigns it -- the assignment exists later in the same body,
          so this is an ordering bug, not a parameter supplied from outside
          the script (which this hook cannot see and does not flag)
    E518  a `continue if` or `pause while` condition is not a `{...}`
          relevance substitution -- the same E514 rule extended to these two
          other condition-bearing verbs. One exception: a literal
          `continue if false` (any case) is accepted as a documented idiom
          for forcing a branch to fail unconditionally. `continue if true`
          is still flagged (it always continues, so it does nothing), and
          `pause while` has no literal exception at all (`true` hangs
          forever, `false` never pauses)
    E519  a command references `__createfile` or `__appendfile` but the body
          never has a matching `createfile until` / `appendfile` line
          earlier; `delete`/`folder delete` lines are cleanup, not
          consumption, and never count (E513's rule, reapplied)
    E520  a `setting` line is not the documented
          `setting "name"="value" on "{...}" for client|user|action` or
          `setting delete "name" on "{...}" for client|user|action` shape
          -- a missing effective-date clause fails at runtime
    E521  a `regset`/`regset64`/`regdelete`/`regdelete64` key is not a
          quoted, bracketed `"[HKEY_...]..."` keyname
    E522  an `override wait` / `override run` block is not terminated by its
          matching verb -- it hits end of body, is terminated by the *other*
          override verb's command, or is immediately reopened by another
          `override` before any command runs. A `{...}` relevance
          substitution line counts as an open option line, not a closing
          command, since it can itself evaluate to one. `bes-actionscript-
          lint-schclass` validates the option lines inside a block (E303);
          this is the pairing check that block's state machine cannot
          express
    E523  an `action uses wow64 redirection` argument that is not `true`,
          `false`, or a `{...}` relevance substitution
    W500  the file is not parseable BES XML; skipped (advisory --
          bes-schema-validate is the authority on file validity)
    W501  unreachable command: a line after an unconditional `exit`,
          `restart`, or `shutdown` (one outside any `if`) can never run;
          only the first unreachable line is reported
    W502  an `action parameter query` after the first execution command --
          these are console-time prompts and belong at the top
    W503  a `__Download`, `__createfile`, or `__appendfile` reference is not
          exactly that case (e.g. `__download\\x.exe`) -- Windows tolerates
          this, but a Linux/macOS agent's case-sensitive filesystem does not.
          Auto-fixable: see AUTO-FIXES below
    W504  the deprecated `dos` verb; use `waithidden cmd.exe /c ...` instead
    W505  a `wait`/`run` of cmd.exe passes a command line but no `/c` (or
          `/k`); without one cmd.exe opens a shell and never runs the command
    W506  a `move`/`copy` of `__createfile`/`__appendfile` onto a destination
          that is not deleted earlier in the body. Both verbs fail when the
          destination already exists, so the action works once and fails on
          every later run; a destination inside the action's own download
          folder is exempt, being action-scoped rather than persistent

E513 is conservative: it is skipped for a whole body whenever any producer's
names cannot be known statically -- an `extract`/`unarchive`/`archive now`/
`utility` command, a `download` with no `as <name>` whose URL is not a literal
with a basename, or any producer name/URL containing a `{` substitution.

E517 is likewise conservative: a `parameter "name"` reference is only checked
against assignments made elsewhere in the *same* body. A name never assigned
in-script is not flagged at all -- real content routinely supplies parameters
from the action's Description page (secure parameters, REST credentials) that
this hook cannot see, and flagging every such reference would be pure noise.

E-codes are real issues and fail the hook. W-codes are advisory and do NOT
fail the hook unless --strict is given.

AUTO-FIXES. There is exactly one, and it is the only check here that is safe
to auto-fix: every other issue is a missing/misplaced piece of block
structure (an `endif`, an `end prefetch block`, ...) a hook has no way to
know the right place for, and guessing could silently change what the action
does.

--auto-fix (W503), on by default (yes when files are given, as pre-commit
does; no when auto-discovering). Every wrong-case `__download`,
`__createfile`, or `__appendfile` reference is rewritten in place to its
canonical spelling -- this is purely a case correction of a reference this
hook already resolved to a known scratch-file token, so there is nothing to
guess. An auto-fixed file fails the hook so the change is reviewed and
re-staged.

Only <ActionScript> elements with MIMEType application/x-Fixlet-Windows-Shell
(matched case-insensitively; a mixed-case MIMEType is still valid BigFix
content) or no MIMEType (which defaults to it) are checked; other bodies are
other languages and are skipped silently. Bodies are extracted with lxml, so
entities are decoded and adjacent CDATA sections merged, with lxml's
sourceline mapping issues back to file line numbers.

Lines inside a `createfile until <MARKER>` block are raw file content, not
ActionScript, and are not scanned -- an `if` or `endif` appearing in such a
block's content does not count. That block's own well-formedness (does it
reach its marker) is bes-actionscript-lint-schclass's E302, not this hook's;
it is not re-reported here.

Usage:
    bes_actionscript_validate_script.py [--strict] [--disable E501]
                                        [--auto-fix=yes|no] [file ...]

With no file arguments, all *.bes files in the current folder and below are
checked. Non-.bes/.ojo paths given explicitly are checked as raw ActionScript
text.

A file can opt out of all checks with a comment anywhere in it:
    <!-- pre-commit-skip: bes-actionscript-validate-script -->
or out of a single check family with the matching marker anywhere in the file:
    actionscript-if-ok             (E500, E501, E505, E506, E514, E518)
    actionscript-prefetch-block-ok (E502, E503, E504)
    actionscript-block-nesting-ok  (E507)
    actionscript-substitution-ok   (E508, E509)
    actionscript-prefetch-placement-ok (E510, E511, E515)
    actionscript-download-ok       (E512, E513)
    actionscript-parameter-ok      (E516, E517)
    actionscript-scratch-ok        (E519, W503)
    actionscript-scratch-dest-ok   (W506)
    actionscript-command-shape-ok  (E520, E521, E523, W504)
    actionscript-cmd-ok            (W505)
    actionscript-override-ok       (E522 -- shared with bes-actionscript-lint-schclass's E303)
    actionscript-unreachable-ok    (W501)
    actionscript-parameter-query-ok (W502)

(E514 and E518 belong to the `actionscript-if-ok` family above: they are
if/continue-if/pause-while condition-shape checks.)

Files that look like mustache templates (containing a `{{ placeholder }}`)
are skipped silently: they are not real content until rendered. Only an
identifier-like placeholder counts -- `{{` is also the ActionScript escape
for a literal `{`, so a heredoc payload containing it is real content.

Exit codes:
    0  no E-code issues and nothing auto-fixed (and, without --strict,
       regardless of warnings)
    1  an E-code issue was found, a file was auto-fixed, or a warning was
       found while --strict is set
"""

import argparse
import os
import re
import sys

from lxml import etree

if __package__ in (None, ""):  # run directly as a script, not as a module
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# `_mask_heredocs` is shared with the sibling ActionScript hook on purpose:
# both need to know that the lines inside a `createfile until` block are file
# content rather than commands, and one implementation of that rule is enough.
from pre_commit_bigfix.bes_actionscript_lint_schclass import _mask_heredocs

# prefetch line-shape prefixes (matched against lowercased lines). These
# mirror the same-named constants in bes_actionscript_validate_prefetch.py --
# NOT imported from there, because that module imports the bigfix_prefetch
# package, which this hook's isolated pre-commit environment does not carry.
# tests/test_bes_actionscript_validate_script.py asserts they stay in lockstep.
NOHASH_PREFETCH = "add nohash prefetch item"
BLOCK_PREFETCH = "add prefetch item"
STATEMENT_PREFETCH = "prefetch "

SKIP_MARKER = "pre-commit-skip: bes-actionscript-validate-script"

# per-check-family opt-out markers (matched anywhere in the file text)
IF_MARKER = "actionscript-if-ok"  # E500, E501, E505, E506
PREFETCH_BLOCK_MARKER = "actionscript-prefetch-block-ok"  # E502, E503, E504
BLOCK_NESTING_MARKER = "actionscript-block-nesting-ok"  # E507
# shared with the sibling schclass hook's E301 on purpose: one marker turns
# off substitution complaints in both hooks, which is what a file that really
# does contain odd braces wants.
SUBSTITUTION_MARKER = "actionscript-substitution-ok"  # E508, E509
PREFETCH_PLACEMENT_MARKER = "actionscript-prefetch-placement-ok"  # E510, E511, E515
DOWNLOAD_MARKER = "actionscript-download-ok"  # E512, E513
PARAMETER_MARKER = "actionscript-parameter-ok"  # E516, E517
SCRATCH_MARKER = "actionscript-scratch-ok"  # E519, W503
COMMAND_SHAPE_MARKER = "actionscript-command-shape-ok"  # E520, E521, E523, W504
CMD_MARKER = "actionscript-cmd-ok"  # W505
SCRATCH_DEST_MARKER = "actionscript-scratch-dest-ok"  # W506
# shared with the sibling schclass hook's E303 on purpose: one marker turns
# off override-block complaints in both hooks.
OVERRIDE_BLOCK_MARKER = "actionscript-override-ok"  # E522
UNREACHABLE_MARKER = "actionscript-unreachable-ok"  # W501
PARAMETER_QUERY_MARKER = "actionscript-parameter-query-ok"  # W502

CHECK_MARKERS = {
    "E500": IF_MARKER,
    "E501": IF_MARKER,
    "E505": IF_MARKER,
    "E506": IF_MARKER,
    "E502": PREFETCH_BLOCK_MARKER,
    "E503": PREFETCH_BLOCK_MARKER,
    "E504": PREFETCH_BLOCK_MARKER,
    "E507": BLOCK_NESTING_MARKER,
    "E508": SUBSTITUTION_MARKER,
    "E509": SUBSTITUTION_MARKER,
    "E510": PREFETCH_PLACEMENT_MARKER,
    "E511": PREFETCH_PLACEMENT_MARKER,
    "E512": DOWNLOAD_MARKER,
    "E513": DOWNLOAD_MARKER,
    "E514": IF_MARKER,
    "E515": PREFETCH_PLACEMENT_MARKER,
    "E516": PARAMETER_MARKER,
    "E517": PARAMETER_MARKER,
    "E518": IF_MARKER,
    "E519": SCRATCH_MARKER,
    "E520": COMMAND_SHAPE_MARKER,
    "E521": COMMAND_SHAPE_MARKER,
    "E522": OVERRIDE_BLOCK_MARKER,
    "E523": COMMAND_SHAPE_MARKER,
    "W501": UNREACHABLE_MARKER,
    "W502": PARAMETER_QUERY_MARKER,
    "W503": SCRATCH_MARKER,
    "W504": COMMAND_SHAPE_MARKER,
    "W505": CMD_MARKER,
    "W506": SCRATCH_DEST_MARKER,
}

KNOWN_CODES = frozenset(
    [
        "E500",
        "E501",
        "E502",
        "E503",
        "E504",
        "E505",
        "E506",
        "E507",
        "E508",
        "E509",
        "E510",
        "E511",
        "E512",
        "E513",
        "E514",
        "E515",
        "E516",
        "E517",
        "E518",
        "E519",
        "E520",
        "E521",
        "E522",
        "E523",
        "W500",
        "W501",
        "W502",
        "W503",
        "W504",
        "W505",
        "W506",
    ]
)

BES_EXTENSIONS = (".bes", ".ojo")
ACTIONSCRIPT_MIMETYPE = "application/x-fixlet-windows-shell"  # compared lowercased

# a mustache template ({{ placeholder }}) is not real content until rendered.
# Only an identifier-like placeholder counts: `{{` is also the ActionScript
# escape for a literal `{`, so heredoc payloads (YARA, JSON, C#) contain `{{`
# around arbitrary content and must not be mistaken for a template.
# Kept identical in all four hooks -- see the lockstep test in
# tests/test_bes_actionscript_validate_script.py.
MUSTACHE_RE = re.compile(r"\{\{\s*[#/^!&>]?\s*[\w.-]+\s*\}\}")

# the first token of a line, case-insensitively, anchored to line start so a
# relevance substitution or argument merely containing one of these words does
# not match (e.g. `continue if {...}` is not an `if` opener)
_IF_RE = re.compile(r"^if\b", re.IGNORECASE)
_ELSEIF_RE = re.compile(r"^elseif\b", re.IGNORECASE)
_ELSE_RE = re.compile(r"^else\s*$", re.IGNORECASE)
_ENDIF_RE = re.compile(r"^endif\s*$", re.IGNORECASE)
_BEGIN_PREFETCH_BLOCK_RE = re.compile(r"^begin\s+prefetch\s+block\s*$", re.IGNORECASE)
_END_PREFETCH_BLOCK_RE = re.compile(r"^end\s+prefetch\s+block\s*$", re.IGNORECASE)
_ADD_PREFETCH_ITEM_RE = re.compile(
    r"^add\s+(?:nohash\s+)?prefetch\s+item\b", re.IGNORECASE
)
_COLLECT_PREFETCH_ITEMS_RE = re.compile(
    r"^collect\s+prefetch\s+items\s*$", re.IGNORECASE
)
_PREFETCH_STATEMENT_RE = re.compile(r"^prefetch\s+(\S+)", re.IGNORECASE)
_DOWNLOAD_AS_RE = re.compile(r"^download(?:\s+now)?\s+as\s+(\S+)", re.IGNORECASE)
_DOWNLOAD_RE = re.compile(r"^download(?:\s+now)?\s+(\S+)\s*$", re.IGNORECASE)
_NAME_KV_RE = re.compile(r"\bname\s*=\s*(\S+)", re.IGNORECASE)
# `__Download\<name>` (or forward slash) on a command line; the name stops at
# whitespace, a quote, or another path separator
_DOWNLOAD_REF_RE = re.compile(r'__Download[\\/]([^\s"\'\\/]+)', re.IGNORECASE)
# a shell glob wildcard (`*` or `?`) in a __Download\ consumer reference --
# e.g. `__Download\mysql*rpm` to match a versioned filename the script
# author cannot spell out literally. The shell expands it at runtime, not
# this checker, so such a name can never be matched against a producer's
# literal name and is left unchecked, the same as a `{...}` substitution.
_GLOB_WILDCARD_RE = re.compile(r"[*?]")
# producers whose output names cannot be known statically; their presence
# turns E513 off for the whole body
_UNKNOWABLE_PRODUCER_RE = re.compile(
    r"^(?:extract|unarchive|archive\s+now|utility)\b", re.IGNORECASE
)
# a bare `download` verb, any shape -- the fallback when neither download
# shape above matched (e.g. a URL with a space inside a substitution)
_DOWNLOAD_VERB_RE = re.compile(r"^download\b", re.IGNORECASE)
# sha1/sha256/size attributes on a producer line, in either the `prefetch`
# statement's colon form (`sha1:...`) or `add prefetch item`'s key=value form
# (`sha1=...`) -- used to tell whether two same-named declarations are
# actually mirror URLs for the identical file (see `_fingerprint`)
_HASH_ATTR_RE = re.compile(r"\b(sha1|sha256|size)\s*[:=]\s*(\S+)", re.IGNORECASE)
# a regex interval quantifier, e.g. `{40}`, `{1,3}`, `{2,}` -- relevance
# substitutions routinely embed a `regex "..."` literal (to pull a sha1/
# sha256/size/url back out of a line with `parenthesized part N of first
# match`), and a quantifier's braces are plain regex syntax, not a nested
# relevance substitution or its close; see `_check_substitution_braces`
_REGEX_QUANTIFIER_RE = re.compile(r"\{\d+(?:,\d*)?\}")
# `delete` / `folder delete` lines clean up the working directory; a
# `__Download\<name>` they mention is not a consumption of that file
_DELETE_RE = re.compile(r"^(?:folder\s+)?delete\b", re.IGNORECASE)
# the two delete forms with their argument captured, for the W506 destination scan
_FILE_DELETE_RE = re.compile(r"^delete\s+(.+?)\s*$", re.IGNORECASE)
_FOLDER_DELETE_RE = re.compile(r"^folder\s+delete\s+(.+?)\s*$", re.IGNORECASE)
# a move/copy whose source is a scratch file, with the destination captured
_SCRATCH_MOVE_RE = re.compile(
    r'^(move|copy)\s+"?(__createfile|__appendfile)"?\s+(.+?)\s*$', re.IGNORECASE
)
# the action's own download folder is action-scoped, not a persistent location
_DOWNLOAD_DEST_RE = re.compile(r"__download|download path", re.IGNORECASE)
# `copy`/`move` lines can themselves populate `__Download`, either from a
# literal `__createfile`/`__appendfile` source (the sole __Download ref is
# the destination) or by renaming one download to another (>= 2 refs; the
# last is the destination, earlier ones are ordinary consumer references)
_MOVE_COPY_RE = re.compile(r"^(?:copy|move)\b", re.IGNORECASE)
_CREATEFILE_SOURCE_RE = re.compile(r"__(?:create|append)file\b", re.IGNORECASE)
# shell redirection into `__Download\<name>` creates that file
_REDIRECT_TARGET_RE = re.compile(
    r'>>?\s*"?__Download[\\/]([^\s"\'\\/]+)', re.IGNORECASE
)
_TERMINATOR_RE = re.compile(r"^(?:exit|restart|shutdown)\b", re.IGNORECASE)
_ACTION_PARAMETER_QUERY_RE = re.compile(r"^action\s+parameter\s+query\b", re.IGNORECASE)
_PARAMETER_RE = re.compile(r"^parameter\b", re.IGNORECASE)
# a `parameter "name" = ...` assignment; the value is everything after `=`
_PARAMETER_ASSIGN_RE = re.compile(r'^parameter\s+"([^"]+)"\s*=', re.IGNORECASE)
# a `parameter "name"` reference anywhere on a line, assignments included --
# callers distinguish an assignment's own name from a reference to another
_PARAMETER_REF_RE = re.compile(r'\bparameter\s+"([^"]+)"', re.IGNORECASE)
_CONTINUE_IF_RE = re.compile(r"^continue\s+if\b(.*)$", re.IGNORECASE)
_PAUSE_WHILE_RE = re.compile(r"^pause\s+while\b(.*)$", re.IGNORECASE)
# `continue if false` (any case) is a documented idiom -- an unconditional
# literal used to force a failure on a branch (e.g. the `else` of an
# `if`/`else`/`endif`), not a mistyped relevance substitution. `continue if
# true` is NOT included: it always continues, so the check does nothing.
# `pause while` gets no such exception: `pause while true` hangs forever and
# `pause while false` never pauses, so neither is a sane literal there.
_LITERAL_FALSE_RE = re.compile(r"^false\s*$", re.IGNORECASE)
_CREATEFILE_UNTIL_RE = re.compile(r"^createfile\s+until\b", re.IGNORECASE)
_APPENDFILE_VERB_RE = re.compile(r"^appendfile\b", re.IGNORECASE)
# `__createfile`/`__appendfile` references, any case; callers compare the
# matched text against the canonical spelling to catch a wrong-case use
_CREATEFILE_REF_RE = re.compile(r"__createfile\b", re.IGNORECASE)
_APPENDFILE_REF_RE = re.compile(r"__appendfile\b", re.IGNORECASE)
# `__Download`/`__createfile`/`__appendfile` in any case, for the W503
# wrong-case scan; grouped so one search finds all three spellings at once
_SCRATCH_REF_RE = re.compile(r"__(download|createfile|appendfile)\b", re.IGNORECASE)
_SCRATCH_CANONICAL = {
    "download": "__Download",
    "createfile": "__createfile",
    "appendfile": "__appendfile",
}
_SETTING_RE = re.compile(r"^setting\s+(.*)$", re.IGNORECASE | re.DOTALL)
_SETTING_SHAPE_RE = re.compile(
    r'^setting\s+(?:delete\s+".+"|".+"\s*=\s*".*")'
    r'\s+on\s+"\{.*\}"\s+for\s+(client\b|user\b|action\b)',
    re.IGNORECASE | re.DOTALL,
)
_REGSET_RE = re.compile(
    r"^(regset64|regset|regdelete64|regdelete)\s+(.*)$", re.IGNORECASE
)
_REGSET_KEY_RE = re.compile(r'^"\[', re.IGNORECASE)
_DOS_VERB_RE = re.compile(r"^dos\b", re.IGNORECASE)
_WOW64_RE = re.compile(r"^action\s+uses\s+wow64\s+redirection\b(.*)$", re.IGNORECASE)
# the agent accepts a boolean literal (any case) or a `{...}` substitution
_WOW64_ARG_RE = re.compile(r"^(?:true|false|\{.*\})$", re.IGNORECASE | re.DOTALL)
# a launching verb plus everything after it; the executable token is split off
# by _leading_token because it may be quoted (and may contain substitutions)
_LAUNCH_VERB_RE = re.compile(
    r"^(wait|waithidden|run|runhidden)\s+(\S.*)$", re.IGNORECASE
)
# cmd.exe interprets its payload only after /c or /k; anywhere in the arguments
_CMD_SWITCH_RE = re.compile(r"(?:^|\s)/[ck]\b", re.IGNORECASE)
_OVERRIDE_VERB_RE = re.compile(r"^override\s+(wait|run)\s*$", re.IGNORECASE)
_OVERRIDE_OPTION_LINE_RE = re.compile(r"^\w+\s*=")

# lines that do not count as "execution has started" for W502: declarations,
# prompts, structure, and prefetching
_NON_EXECUTION_RES = (
    _BEGIN_PREFETCH_BLOCK_RE,
    _END_PREFETCH_BLOCK_RE,
    _ADD_PREFETCH_ITEM_RE,
    _COLLECT_PREFETCH_ITEMS_RE,
    _PREFETCH_STATEMENT_RE,
    _PARAMETER_RE,
    _ACTION_PARAMETER_QUERY_RE,
    _IF_RE,
    _ELSEIF_RE,
    _ELSE_RE,
    _ENDIF_RE,
)


def _check_substitution_braces(lineno, line):
    """Check one line's `{...}` relevance substitutions for balance.

    A substitution must open and close on the same line: the agent evaluates
    it per line, so a `{` left open at end of line is not a substitution that
    continues, it is a broken one (E508). A `}` reached with none open is the
    mirror image (E509).

    `{{` is an escape, not an opener: it passes a literal `{` through to the
    command, so it neither opens a substitution nor makes the `}` that
    follows a substitution close -- that `}` pairs with the escape instead.
    `}}` is likewise a literal `}`, and the same escape holds *inside* an
    open substitution too: `{ ... "@{'k'='v'}}" ... }` (a PowerShell hashtable
    literal quoted inside the substitution) does not close on the first `}`
    of that `}}` -- the pair is a literal `}` in the string, and the
    substitution stays open for its real closing `}`. Escapes outside a
    substitution are counted so an escaped brace absorbs a later lone `}`
    rather than being reported as stray, which keeps this quiet on the
    escaping styles seen in real content.
    """
    issues = []
    open_col = None  # column of the `{` that opened the current substitution
    pending_escapes = 0  # `{{`/`}}` literals a lone `}` may pair with
    index = 0
    while index < len(line):
        match = _REGEX_QUANTIFIER_RE.match(line, index)
        if match:
            # `{40}` etc -- a regex quantifier's braces, not a nested
            # substitution or its close; skip over the whole span untouched
            index = match.end()
            continue
        char = line[index]
        if open_col is None:
            if line.startswith("{{", index) or line.startswith("}}", index):
                pending_escapes += 1
                index += 2
                continue
            if char == "{":
                open_col = index + 1
            elif char == "}":
                if pending_escapes:
                    pending_escapes -= 1
                else:
                    issues.append(
                        (
                            lineno,
                            "E509",
                            (
                                f"unbalanced }} at column {index + 1} -- no `{{` "
                                "relevance substitution is open on this line "
                                f"(`{{{{` passes a literal brace through); add "
                                f"`{SUBSTITUTION_MARKER}` if intentional"
                            ),
                        )
                    )
        elif char == "}":
            if line.startswith("}}", index):
                index += 2  # escaped literal }; the substitution stays open
                continue
            open_col = None
        index += 1

    if open_col is not None:
        issues.append(
            (
                lineno,
                "E508",
                (
                    f"unbalanced {{ at column {open_col} -- the relevance "
                    "substitution has no closing } before the end of the "
                    "line, and a substitution cannot span lines (`{{` passes "
                    f"a literal brace through); add `{SUBSTITUTION_MARKER}` "
                    "if intentional"
                ),
            )
        )
    return issues


def _url_basename(url):
    """Return the last path segment of a literal URL, or None if unknowable."""
    if "{" in url:
        return None
    base = url.rstrip("/").rsplit("/", 1)[-1]
    if not base or "://" in base or base == url.rstrip("/"):
        # no path at all (bare host), or nothing after the last slash
        return None
    return base


def _fingerprint(line):
    """Return a hashable `{attr: value}` snapshot of a producer line's
    sha1/sha256/size attributes, lowercased and order-independent, or None.

    if the line declares none of them.

    Two producer declarations of the same download name with matching
    fingerprints are the same file offered from multiple mirror URLs --
    a common BigFix pattern -- not a real duplicate; see `_co_executable`'s
    caller in `_check_download_names`. A line with no hash attributes at
    all (a `download as`, `move`/`copy`, or redirect producer) fingerprints
    to None, which never matches another None -- those stay flagged as
    before, since there is nothing here to confirm they are the same file.
    """
    attrs = tuple(
        sorted((k.lower(), v.lower()) for k, v in _HASH_ATTR_RE.findall(line))
    )
    return attrs or None


def _co_executable(path_a, path_b):
    """Return True only when two declarations are known to run together.

    Each path is a `{if_id: branch_index}` snapshot of which `if`/`elseif`/
    `else` branch was open, for every still-open `if`, at the moment a name
    was declared. Real BigFix content routinely guards platform-specific
    prefetch items with a *separate* `if` per platform (Windows, then a
    second unrelated `if` for mac, then another for Linux) rather than one
    `if`/`elseif` chain -- and this checker has no way to know those
    conditions are mutually exclusive. So this only calls two declarations
    co-executable -- a real E512 duplicate -- when their paths are exactly
    equal: both unconditional (empty path), or both reached through the
    identical sequence of branch choices. Anything reached via a different
    `if` (even one that looks platform-exclusive) is treated as potentially
    mutually exclusive and left unflagged, on the same false-alarm-is-worse
    principle E513's gating uses.
    """
    return path_a == path_b


def _check_download_names(lines):
    """Check prefetch/download producer names against `__Download\\` consumers.

    Returns E512 issues for a duplicate producer name that can co-execute
    with an earlier declaration of the same name (the second declaration
    would silently overwrite the first at runtime) -- declarations of the
    same name in mutually exclusive `if`/`elseif`/`else` branches (see
    `_co_executable`) are not flagged, since only one of them ever runs.
    Also returns E513 issues for a `__Download\\<name>` consumer no producer
    creates. E513 is conservative: the moment any producer's names are
    unknowable (an extract/unarchive/archive now/utility command, a
    `download` with no `as <name>` and no literal URL basename, or a
    name/URL containing a `{` substitution), the whole consumer check is
    skipped -- a missed typo is better than a false alarm. E512 still runs on
    the literal names that were collected. A single consumer reference
    containing a shell glob wildcard (`*` or `?`, e.g.
    `__Download\\mysql*rpm` for a versioned filename the script author
    cannot spell out literally) is skipped on its own, without disabling
    the check for the rest of the body -- the shell expands it at runtime,
    not this checker, so it can never be matched against a producer's
    literal name.

    `copy`/`move` and shell-redirection (`>`, `>>`) lines can themselves
    create a file under `__Download`, not just consume one -- see
    `_MOVE_COPY_RE`/`_REDIRECT_TARGET_RE` below -- so they are also treated
    as producers where the destination name is determinable.

    `copy`/`move` and shell-redirection (`>`, `>>`) lines can themselves
    create a file under `__Download`, not just consume one -- see
    `_MOVE_COPY_RE`/`_REDIRECT_TARGET_RE` below -- so they are also treated
    as producers where the destination name is determinable.
    """
    issues = []
    producers = {}  # lowercased name -> [(lineno, if-branch path, fingerprint), ...]
    knowable = True
    if_stack = []  # each entry: [if_id, branch_index]
    next_if_id = 0

    def current_path():
        return {if_id: branch for if_id, branch in if_stack}

    def produce(lineno, name, fingerprint=None):
        nonlocal knowable
        if name is None or "{" in name:
            knowable = False
            return
        name = name.strip("\"'").lower()
        if not name:
            knowable = False
            return
        path = current_path()
        declarations = producers.setdefault(name, [])
        for existing_lineno, existing_path, existing_fingerprint in declarations:
            if not _co_executable(path, existing_path):
                continue
            if fingerprint is not None and fingerprint == existing_fingerprint:
                # same name, same sha1/sha256/size -- mirror URLs for the
                # identical file, not a real duplicate; whichever download
                # succeeds satisfies both
                continue
            issues.append(
                (
                    lineno,
                    "E512",
                    (
                        f'duplicate download name "{name}" (first '
                        f"declared on line {existing_lineno}, and both "
                        "can run in the same execution); the second "
                        "declaration silently overwrites the first; add "
                        f"`{DOWNLOAD_MARKER}` if intentional"
                    ),
                )
            )
            break
        declarations.append((lineno, path, fingerprint))

    for index, raw_line in enumerate(lines):
        lineno = index + 1
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        # if/elseif/else/endif bookkeeping only -- pairing itself is E500/
        # E501/E505/E506's job elsewhere; an unbalanced endif here is
        # ignored rather than double-reported
        if _IF_RE.match(stripped):
            next_if_id += 1
            if_stack.append([next_if_id, 0])
            continue
        if _ELSEIF_RE.match(stripped) or _ELSE_RE.match(stripped):
            if if_stack:
                if_stack[-1][1] += 1
            continue
        if _ENDIF_RE.match(stripped):
            if if_stack:
                if_stack.pop()
            continue

        lowered = stripped.lower()
        if _UNKNOWABLE_PRODUCER_RE.match(stripped):
            knowable = False
            continue
        if lowered.startswith((BLOCK_PREFETCH, NOHASH_PREFETCH)):
            match = _NAME_KV_RE.search(stripped)
            produce(lineno, match.group(1) if match else None, _fingerprint(stripped))
            continue
        if lowered.startswith(STATEMENT_PREFETCH):
            match = _PREFETCH_STATEMENT_RE.match(stripped)
            produce(lineno, match.group(1) if match else None, _fingerprint(stripped))
            continue
        match = _DOWNLOAD_AS_RE.match(stripped)
        if match:
            produce(lineno, match.group(1))
            continue
        match = _DOWNLOAD_RE.match(stripped)
        if match:
            produce(lineno, _url_basename(match.group(1)))
            continue
        if _DOWNLOAD_VERB_RE.match(stripped):
            # a download of some other shape (a URL with a space inside a
            # `{...}` substitution does not match either regex above); its
            # target name is unknowable
            knowable = False
            continue

        if _MOVE_COPY_RE.match(stripped):
            refs = _DOWNLOAD_REF_RE.findall(stripped)
            has_createfile_source = bool(_CREATEFILE_SOURCE_RE.search(stripped))
            if has_createfile_source and refs:
                # source is __createfile/__appendfile, not a __Download ref;
                # the one __Download ref on the line is the destination
                produce(lineno, refs[-1])
            elif has_createfile_source and "{" in stripped:
                # `move __createfile "{download path "X"}"` -- a substituted
                # destination with no literal __Download ref to read back
                knowable = False
            elif not has_createfile_source and len(refs) >= 2:
                # renaming one download to another; the last ref is the new
                # name, earlier refs are ordinary consumer references
                produce(lineno, refs[-1])
            # a single __Download ref with no __createfile source is left
            # alone here -- it is an ordinary consumer reference (e.g.
            # `move __Download\typo.exe elsewhere`), checked as one below
            continue

        match = _REDIRECT_TARGET_RE.search(stripped)
        if match:
            produce(lineno, match.group(1))
            # fall through: the line may still hold other __Download refs
            # (a command being redirected, say) to check as consumers below

    if knowable:
        for index, raw_line in enumerate(lines):
            lineno = index + 1
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            if _DELETE_RE.match(stripped):
                # deleting `__Download\<name>` is cleanup, not consumption --
                # ensuring the working directory is clean before proceeding
                # is normal even when nothing downloads that name
                continue
            for name in _DOWNLOAD_REF_RE.findall(stripped):
                if "{" in name:  # a substituted name is unknowable; skip it
                    continue
                if _GLOB_WILDCARD_RE.search(name):
                    # a wildcard reference (e.g. `__Download\mysql*rpm` for
                    # a versioned filename) matches by shell glob at
                    # runtime, not by literal name; skip it
                    continue
                if name.lower() not in producers:
                    issues.append(
                        (
                            lineno,
                            "E513",
                            (
                                f"`__Download\\{name}` is referenced but nothing "
                                "prefetches or downloads a file of that name; "
                                f"add `{DOWNLOAD_MARKER}` if intentional"
                            ),
                        )
                    )
    return issues


def _check_parameters(lines):
    """Check `parameter "name" = ...` assignments and references.

    Returns E516 issues for a second assignment to a name that can
    co-execute with an earlier one (the same `_co_executable` if-branch-path
    rule E512 uses -- assignments in mutually exclusive `if`/`elseif`/`else`
    branches are not compared), since action parameters are write-once and
    the second assignment would silently overwrite the first at runtime.

    Also returns E517 issues for a `parameter "name"` reference on a line
    before that name's (first) assignment elsewhere in the body -- an
    ordering bug, since the substitution evaluates to empty at that point.
    A name never assigned anywhere in the body is not flagged: it may be
    supplied from outside the script (a secure parameter, say), which this
    hook cannot see.
    """
    issues = []
    if_stack = []  # each entry: [if_id, branch_index], mirrors _check_download_names
    next_if_id = 0
    declarations = {}  # lowercased name -> [(lineno, if-branch path), ...]
    first_assign_lineno = {}  # lowercased name -> earliest assignment lineno
    deferred_refs = []  # (lineno, name, raw_name) references seen so far

    def current_path():
        return {if_id: branch for if_id, branch in if_stack}

    # first pass: record every assignment (for E516 and to know where each
    # name is first assigned), in source order
    for index, raw_line in enumerate(lines):
        lineno = index + 1
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        if _IF_RE.match(stripped):
            next_if_id += 1
            if_stack.append([next_if_id, 0])
            continue
        if _ELSEIF_RE.match(stripped) or _ELSE_RE.match(stripped):
            if if_stack:
                if_stack[-1][1] += 1
            continue
        if _ENDIF_RE.match(stripped):
            if if_stack:
                if_stack.pop()
            continue

        match = _PARAMETER_ASSIGN_RE.match(stripped)
        if match:
            name = match.group(1)
            key = name.lower()
            if key not in first_assign_lineno:
                first_assign_lineno[key] = lineno
            path = current_path()
            existing = declarations.setdefault(key, [])
            for existing_lineno, existing_path in existing:
                if _co_executable(path, existing_path):
                    issues.append(
                        (
                            lineno,
                            "E516",
                            (
                                f'duplicate assignment to parameter "{name}" '
                                f"(first assigned on line {existing_lineno}, "
                                "and both can run in the same execution); "
                                "action parameters are write-once and the "
                                "second assignment silently overwrites the "
                                f"first; add `{PARAMETER_MARKER}` if "
                                "intentional"
                            ),
                        )
                    )
                    break
            existing.append((lineno, path))

    # second pass: every `parameter "name"` reference, including inside an
    # assignment's own value (self-reference is a real ordering bug too, and
    # the assignment's own name= part is excluded by scanning after it)
    for index, raw_line in enumerate(lines):
        lineno = index + 1
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        assign_match = _PARAMETER_ASSIGN_RE.match(stripped)
        scan_from = assign_match.end() if assign_match else 0
        for match in _PARAMETER_REF_RE.finditer(stripped, scan_from):
            deferred_refs.append((lineno, match.group(1)))

    for lineno, name in deferred_refs:
        key = name.lower()
        assign_lineno = first_assign_lineno.get(key)
        if assign_lineno is not None and lineno < assign_lineno:
            issues.append(
                (
                    lineno,
                    "E517",
                    (
                        f'`parameter "{name}"` is referenced here but not '
                        f"assigned until line {assign_lineno}; the "
                        "substitution evaluates to empty at this point; add "
                        f"`{PARAMETER_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def _normalize_path(text):
    """Normalize a path argument for comparison: unquote, unify separators.

    Comparison is textual -- two spellings of the same path that differ by
    quoting, separator or a trailing slash are treated as equal, but a
    `{...}` substitution is compared verbatim (its value is unknowable here,
    so only an identical substitution counts as the same path).
    """
    return text.strip().strip('"').replace("\\", "/").rstrip("/")


def _clears_destination(line, destination):
    """True if `line` deletes `destination` or a folder containing it."""
    stripped = line.strip()
    match = _FOLDER_DELETE_RE.match(stripped)
    if match:
        folder = _normalize_path(match.group(1))
        # a substituted prefix is unknowable, so compare the trailing literal
        # segment: `folder delete "{client folder...}/__Local/Upgrade"` covers
        # `__Local/Upgrade/besclientupgrade`
        tail = folder.split("}")[-1].strip("/")
        return bool(tail) and "/" + tail + "/" in "/" + destination
    match = _FILE_DELETE_RE.match(stripped)
    return bool(match) and _normalize_path(match.group(1)) == destination


def _check_scratch_destinations(lines):
    """Check that a scratch file is moved/copied onto a cleared destination.

    Returns W506 for a `move`/`copy` of `__createfile`/`__appendfile` whose
    destination is not deleted earlier in the body. Both verbs fail when the
    destination already exists, so such an action works once and then fails
    on every later run; the documented pattern is `delete <dest>` first.

    A destination inside the action's own download folder is exempt: that
    folder is action-scoped rather than a persistent location.
    """
    issues = []
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        match = _SCRATCH_MOVE_RE.match(stripped)
        if not match:
            continue
        verb, destination = match.group(1).lower(), _normalize_path(match.group(3))
        if not destination or _DOWNLOAD_DEST_RE.search(destination):
            continue
        if any(_clears_destination(line, destination) for line in lines[:index]):
            continue
        shown = match.group(3).strip().strip('"')
        issues.append(
            (
                index + 1,
                "W506",
                (
                    f'`{verb}` onto "{shown}" without deleting it first; '
                    f"`{verb}` fails when the destination already exists, so this "
                    f"action cannot run twice; add `{SCRATCH_DEST_MARKER}` if "
                    "intentional"
                ),
            )
        )
    return issues


def _check_scratch_references(lines):
    """Check `__createfile`/`__appendfile` production and reference case.

    Returns E519 issues for a command referencing `__createfile` (resp.
    `__appendfile`) when the body has no `createfile until` (resp.
    `appendfile`) line anywhere -- the E513 rule reapplied to these two
    scratch-file verbs, with the same `delete`/`folder delete` exemption
    (clearing scratch output is normal housekeeping, not consumption).

    Also returns W503 issues for any `__download`, `__createfile`, or
    `__appendfile` reference whose case does not match the canonical
    spelling -- Windows tolerates this, a case-sensitive Linux/macOS
    filesystem does not.
    """
    issues = []
    has_createfile = any(
        _CREATEFILE_UNTIL_RE.match(line.strip())
        for line in lines
        if line.strip() and not line.strip().startswith("//")
    )
    has_appendfile = any(
        _APPENDFILE_VERB_RE.match(line.strip())
        for line in lines
        if line.strip() and not line.strip().startswith("//")
    )

    for index, raw_line in enumerate(lines):
        lineno = index + 1
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        for match in _SCRATCH_REF_RE.finditer(raw_line):
            matched_text = match.group(0)
            canonical = _SCRATCH_CANONICAL[match.group(1).lower()]
            if matched_text != canonical:
                issues.append(
                    (
                        lineno,
                        "W503",
                        (
                            f'"{matched_text}" is not exactly "{canonical}"; '
                            "Windows tolerates the case mismatch but a "
                            "case-sensitive Linux/macOS filesystem does not; "
                            f"add `{SCRATCH_MARKER}` if intentional"
                        ),
                    )
                )

        if _DELETE_RE.match(stripped):
            continue  # cleanup, not consumption -- same exemption as E513

        if not has_createfile and _CREATEFILE_REF_RE.search(stripped):
            issues.append(
                (
                    lineno,
                    "E519",
                    (
                        "`__createfile` is referenced but the body has no "
                        f"`createfile until` line; add `{SCRATCH_MARKER}` if intentional"
                    ),
                )
            )
        if not has_appendfile and _APPENDFILE_REF_RE.search(stripped):
            issues.append(
                (
                    lineno,
                    "E519",
                    (
                        "`__appendfile` is referenced but the body has no "
                        "`appendfile` line; add "
                        f"`{SCRATCH_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def _scratch_case_targets(raw, src, is_bes):
    """Yield (file_lineno, wrong_text, canonical) for every W503 fix target.

    Mirrors what `_check_scratch_references` itself flags: `body.split("\n")`
    is run through `_mask_heredocs` first, so a wrong-case reference sitting
    inside `createfile until` block content (raw file text, not ActionScript)
    is not a target here either. `file_lineno` is 1-based into the whole
    file, matching `_validate_bes_xml`'s sourceline offset for a .bes file.
    """
    if is_bes:
        try:
            bodies = list(_iter_actionscript_bodies(raw))
        except etree.XMLSyntaxError:
            return  # already reported as W500; nothing safe to rewrite
    else:
        bodies = [(1, src)]

    for sourceline, body in bodies:
        masked_lines, _createfile_issues = _mask_heredocs(body.split("\n"))
        for index, masked_line in enumerate(masked_lines):
            stripped = masked_line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            for match in _SCRATCH_REF_RE.finditer(masked_line):
                matched_text = match.group(0)
                canonical = _SCRATCH_CANONICAL[match.group(1).lower()]
                if matched_text != canonical:
                    yield sourceline + index, matched_text, canonical


def _replace_on_line(lines, lineno, text, replacement):
    """Substitute one `text` on 1-based `lineno` of `lines`; say whether it landed.

    The reference is replaced inside the file line rather than the line being
    rebuilt, so indentation and anything else sharing the line survive. A
    target whose text is no longer found on its line (already fixed by an
    earlier, overlapping match, say) is left alone rather than guessed at.
    """
    if not 1 <= lineno <= len(lines):
        return False
    raw_line = lines[lineno - 1]
    if text not in raw_line:
        return False
    lines[lineno - 1] = raw_line.replace(text, replacement, 1)
    return True


def fix_scratch_case(src, targets):
    """Rewrite each wrong-case scratch reference to its canonical spelling.

    `targets` is `_scratch_case_targets`'s (file_lineno, wrong_text,
    canonical) triples. Returns (new_src, fixed), `fixed` a list of
    (lineno, "W503", message).
    """
    lines = src.split("\n")
    fixed = []
    for lineno, text, canonical in targets:
        if _replace_on_line(lines, lineno, text, canonical):
            fixed.append(
                (
                    lineno,
                    "W503",
                    f'"{text}" replaced with "{canonical}"',
                )
            )
    return "\n".join(lines), fixed


def _leading_token(text):
    """Split `text` into its first whitespace-delimited token and the rest.

    A double-quoted token is kept whole (quotes stripped) so a quoted
    executable path containing spaces -- or a `{...}` substitution that may
    expand to one -- stays a single token.
    """
    text = text.lstrip()
    if text.startswith('"'):
        end = text.find('"', 1)
        if end != -1:
            return text[1:end], text[end + 1 :].strip()
    token, _sep, rest = text.partition(" ")
    return token, rest.strip()


def _is_cmd_shell(executable):
    """True if `executable` names the Windows command interpreter.

    Compares the trailing path component so both `cmd.exe` and a full path
    like `{windows folder}\\system32\\cmd.exe` are recognized, while an
    unrelated program whose name merely ends in "cmd" is not.
    """
    basename = re.split(r"[\\/]", executable)[-1].strip().lower()
    return basename in ("cmd", "cmd.exe")


def _check_command_shapes(lines):
    """Check per-line command shapes independent of block structure.

    Returns E520 for a `setting` line that is not the documented
    `setting "name"="value" on "{...}" for client|user|action` or
    `setting delete "name" on "{...}" for client|user|action` shape (a
    missing effective-date `on` clause fails at runtime); E521 for a
    `regset`/`regset64`/`regdelete`/`regdelete64` key that is not a quoted,
    bracketed `"[HKEY_...]..."` keyname; W504 for the deprecated `dos`
    verb (`waithidden cmd.exe /c ...` is the documented replacement); and
    W505 for a `wait`/`run` of cmd.exe that passes a command line without the
    `/c` (or `/k`) switch cmd.exe needs to execute it.
    """
    issues = []
    for index, raw_line in enumerate(lines):
        lineno = index + 1
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        if _SETTING_RE.match(stripped) and not _SETTING_SHAPE_RE.match(stripped):
            issues.append(
                (
                    lineno,
                    "E520",
                    (
                        "`setting` line does not match the documented "
                        '`setting "name"="value" on "{...}" for '
                        "client|user|action` shape; add "
                        f"`{COMMAND_SHAPE_MARKER}` if intentional"
                    ),
                )
            )

        match = _REGSET_RE.match(stripped)
        if match:
            verb, rest = match.group(1), match.group(2).strip()
            if not _REGSET_KEY_RE.match(rest):
                issues.append(
                    (
                        lineno,
                        "E521",
                        (
                            f'"{verb}" key is not a quoted, bracketed '
                            '"[HKEY_...]..." keyname; add '
                            f"`{COMMAND_SHAPE_MARKER}` if intentional"
                        ),
                    )
                )

        match = _WOW64_RE.match(stripped)
        if match and not _WOW64_ARG_RE.match(match.group(1).strip()):
            issues.append(
                (
                    lineno,
                    "E523",
                    (
                        "`action uses wow64 redirection` takes `true`, `false`, or a "
                        "`{...}` relevance substitution; add "
                        f"`{COMMAND_SHAPE_MARKER}` if intentional"
                    ),
                )
            )

        match = _LAUNCH_VERB_RE.match(stripped)
        if match:
            executable, arguments = _leading_token(match.group(2))
            if (
                _is_cmd_shell(executable)
                and arguments
                and not _CMD_SWITCH_RE.search(arguments)
            ):
                issues.append(
                    (
                        lineno,
                        "W505",
                        (
                            "cmd.exe is passed a command line but no `/c` (or "
                            "`/k`); without one it opens a shell and never runs "
                            f"the command; add `{CMD_MARKER}` if intentional"
                        ),
                    )
                )

        if _DOS_VERB_RE.match(stripped):
            issues.append(
                (
                    lineno,
                    "W504",
                    (
                        "`dos` is deprecated; use `waithidden cmd.exe /c "
                        "...` instead; add "
                        f"`{COMMAND_SHAPE_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def _check_condition_shapes(lines):
    """Check `continue if` / `pause while` condition shape.

    Returns E518 for a `continue if` or `pause while` whose condition is not
    a `{...}` relevance substitution -- the same rule E514 applies to `if`/
    `elseif`, extended to these two other condition-bearing verbs. The one
    exception: a literal `continue if false` (any case) is accepted as a
    documented idiom for forcing a branch to fail unconditionally, e.g. in
    the `else` of an `if`/`else`/`endif`. `continue if true` is still
    flagged -- it always continues, so the check does nothing -- and
    `pause while` gets no literal exception at all: `pause while true`
    hangs forever and `pause while false` never pauses, so neither literal
    is ever the right thing to write.
    """
    issues = []
    for index, raw_line in enumerate(lines):
        lineno = index + 1
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        for regex, verb, allow_literal_false in (
            (_CONTINUE_IF_RE, "continue if", True),
            (_PAUSE_WHILE_RE, "pause while", False),
        ):
            match = regex.match(stripped)
            if not match:
                continue
            condition = match.group(1).lstrip()
            if condition.startswith("{"):
                continue
            if allow_literal_false and _LITERAL_FALSE_RE.match(condition):
                continue
            issues.append(
                (
                    lineno,
                    "E518",
                    (
                        f"`{verb}` condition is not a `{{...}}` "
                        "relevance substitution; the agent requires "
                        f"one; add `{IF_MARKER}` if intentional"
                    ),
                )
            )
    return issues


def _check_override_blocks(lines):
    """Check `override wait` / `override run` block termination.

    `bes_actionscript_lint_schclass.py` validates the keyword=value option
    lines inside a block (E303) but its state machine never notices a block
    that is left open: hitting end of body, being reopened by another
    `override` before any command runs, or being closed by the *wrong*
    verb's command (an `override wait` block whose next real command is
    `run ...` instead of `wait ...`, or vice versa). This is that pairing
    check.

    A line that starts with `{` (after stripping leading whitespace) is
    also treated as an open option line, not a closing command: a `{...}`
    relevance substitution can itself evaluate to a keyword=value option
    (e.g. choosing `hidden=true` vs `completion=none` by OS), so it keeps
    the block open exactly like a literal option line would.
    """
    issues = []
    open_verb = None
    open_lineno = None
    for index, raw_line in enumerate(lines):
        lineno = index + 1
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        match = _OVERRIDE_VERB_RE.match(stripped)
        if match:
            if open_verb is not None:
                issues.append(
                    (
                        open_lineno,
                        "E522",
                        (
                            f"`override {open_verb}` is reopened by another "
                            f"`override` on line {lineno} before any "
                            f"command runs; add `{OVERRIDE_BLOCK_MARKER}` if "
                            "intentional"
                        ),
                    )
                )
            open_verb = match.group(1).lower()
            open_lineno = lineno
            continue

        if open_verb is None:
            continue
        if _OVERRIDE_OPTION_LINE_RE.match(stripped) or stripped.startswith("{"):
            # a keyword=value option line, or a `{...}` relevance
            # substitution that evaluates to one at runtime (e.g. picking
            # `hidden=true` vs `completion=none` by OS) -- the block is
            # still open either way
            continue

        # the first non-option line closes the block -- its own verb must
        # match the one `override` opened
        verb = re.match(r"[A-Za-z_]+", stripped)
        command_verb = verb.group(0).lower() if verb else ""
        if command_verb != open_verb:
            issues.append(
                (
                    open_lineno,
                    "E522",
                    (
                        f"`override {open_verb}` is terminated by `{command_verb}` "
                        f"on line {lineno}, not `{open_verb}`; add "
                        f"`{OVERRIDE_BLOCK_MARKER}` if intentional"
                    ),
                )
            )
        open_verb = None

    if open_verb is not None:
        issues.append(
            (
                open_lineno,
                "E522",
                (
                    f"`override {open_verb}` is never terminated by a "
                    f"matching `{open_verb}` command; add "
                    f"`{OVERRIDE_BLOCK_MARKER}` if intentional"
                ),
            )
        )
    return issues


def check_actionscript(body):
    """Check a single ActionScript body for balanced blocks and substitutions.

    Walks `if`/`endif` and `begin`/`end prefetch block` pairing across lines,
    and `{...}` relevance-substitution braces within each line.

    Returns a sorted list of (lineno, code, message), lineno 1-based into
    `body`. `_mask_heredocs` blanks out `createfile until` block content
    first, so lines that only look like commands inside one are ignored (its
    own E302 belongs to the sibling schclass hook, not here).
    """
    lines, _createfile_issues = _mask_heredocs(body.split("\n"))
    issues = _check_download_names(lines)  # E512 / E513
    issues.extend(_check_parameters(lines))  # E516 / E517
    issues.extend(_check_scratch_references(lines))  # E519 / W503
    issues.extend(_check_scratch_destinations(lines))  # W506
    issues.extend(_check_command_shapes(lines))  # E520 / E521 / W504
    issues.extend(_check_condition_shapes(lines))  # E518
    issues.extend(_check_override_blocks(lines))  # E522
    if_stack = []  # each entry: [lineno, seen_else]
    prefetch_stack = []  # each entry: [lineno, if_depth_at_open]
    preamble_over = False  # True once anything a prefetch block may not follow
    first_execution_lineno = None  # first line that starts real execution
    terminated_lineno = None  # unconditional exit/restart/shutdown, if any
    unreachable_reported = False  # W501 fires once, on the first dead line

    for index, raw_line in enumerate(lines):
        lineno = index + 1
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        # brace balance is per line and independent of the block walk below,
        # so it runs before any of the `continue`s that dispatch on the verb.
        # The raw line is passed, not `stripped`, so reported columns line up
        # with the file. An `appendfile <content>` line is skipped entirely:
        # everything after the verb is one line of raw file content written
        # out verbatim, the same as `createfile until` heredoc content, not
        # ActionScript -- `appendfile }` is a literal `}` appended to the
        # file, not a stray relevance-substitution close.
        if not _APPENDFILE_VERB_RE.match(stripped):
            issues.extend(_check_substitution_braces(lineno, raw_line))

        # unreachable code (W501): anything after an unconditional
        # exit/restart/shutdown never runs; report the first such line only
        if terminated_lineno is not None and not unreachable_reported:
            unreachable_reported = True
            issues.append(
                (
                    lineno,
                    "W501",
                    (
                        "unreachable: the unconditional "
                        f"exit/restart/shutdown on line {terminated_lineno} "
                        "means this line can never run; add "
                        f"`{UNREACHABLE_MARKER}` if intentional"
                    ),
                )
            )

        if _ACTION_PARAMETER_QUERY_RE.match(stripped):
            if first_execution_lineno is not None:
                issues.append(
                    (
                        lineno,
                        "W502",
                        (
                            "`action parameter query` after execution began "
                            f"on line {first_execution_lineno}; these are "
                            "console-time prompts and belong at the top; add "
                            f"`{PARAMETER_QUERY_MARKER}` if intentional"
                        ),
                    )
                )
            continue  # a prompt is preamble: opens/closes/starts nothing below

        # placement bookkeeping for E515 and W502. `parameter` assignments
        # and `action parameter query` (handled above) are preamble; anything
        # else -- a prefetch block included -- ends the preamble.
        is_preamble_line = bool(_PARAMETER_RE.match(stripped))
        if _TERMINATOR_RE.match(stripped) and not if_stack:
            terminated_lineno = lineno
        if first_execution_lineno is None and not any(
            regex.match(stripped) for regex in _NON_EXECUTION_RES
        ):
            first_execution_lineno = lineno
        # any non-preamble line ends the preamble -- except the
        # `begin prefetch block` line itself, whose own branch below must see
        # the preamble state as it was BEFORE the block (and then ends it)
        if not is_preamble_line and not _BEGIN_PREFETCH_BLOCK_RE.match(stripped):
            preamble_over = True

        if _BEGIN_PREFETCH_BLOCK_RE.match(stripped):
            # a nested block is E504 below; E515 on top of it would be noise
            if preamble_over and not prefetch_stack:
                issues.append(
                    (
                        lineno,
                        "E515",
                        (
                            "`begin prefetch block` is not at the top of the "
                            "script -- only blank lines, // comments, `action "
                            "parameter query`, and `parameter` assignments "
                            "may precede it; add "
                            f"`{PREFETCH_PLACEMENT_MARKER}` if intentional"
                        ),
                    )
                )
            preamble_over = True
            if prefetch_stack:
                issues.append(
                    (
                        lineno,
                        "E504",
                        (
                            "`begin prefetch block` nested inside another "
                            "prefetch block; prefetch blocks do not nest; "
                            f"add `{PREFETCH_BLOCK_MARKER}` if intentional"
                        ),
                    )
                )
            # pushed regardless of nesting, so a nested pair's own
            # `end prefetch block` still matches up and does not also
            # misreport as a stray E503
            prefetch_stack.append([lineno, len(if_stack)])
            continue

        if _END_PREFETCH_BLOCK_RE.match(stripped):
            if not prefetch_stack:
                issues.append(
                    (
                        lineno,
                        "E503",
                        (
                            "`end prefetch block` with no open `begin prefetch "
                            f"block`; add `{PREFETCH_BLOCK_MARKER}` if "
                            "intentional"
                        ),
                    )
                )
            else:
                open_lineno, if_depth_at_open = prefetch_stack.pop()
                if len(if_stack) > if_depth_at_open:
                    issues.append(
                        (
                            lineno,
                            "E507",
                            (
                                "`if` opened inside a prefetch block is still "
                                "open at `end prefetch block`; blocks "
                                "interleave rather than nest; add "
                                f"`{BLOCK_NESTING_MARKER}` if intentional"
                            ),
                        )
                    )
            continue

        if _ADD_PREFETCH_ITEM_RE.match(stripped):
            if not prefetch_stack:
                issues.append(
                    (
                        lineno,
                        "E510",
                        (
                            "`add prefetch item` outside an open `begin "
                            "prefetch block`; the agent rejects it there; add "
                            f"`{PREFETCH_PLACEMENT_MARKER}` if intentional"
                        ),
                    )
                )
            continue

        if _COLLECT_PREFETCH_ITEMS_RE.match(stripped):
            if not prefetch_stack:
                issues.append(
                    (
                        lineno,
                        "E511",
                        (
                            "`collect prefetch items` outside an open `begin "
                            "prefetch block`; the agent rejects it there; add "
                            f"`{PREFETCH_PLACEMENT_MARKER}` if intentional"
                        ),
                    )
                )
            continue

        if _IF_RE.match(stripped):
            condition = stripped[_IF_RE.match(stripped).end() :].lstrip()
            if not condition.startswith("{"):
                issues.append(
                    (
                        lineno,
                        "E514",
                        (
                            "`if` condition is not a `{...}` relevance "
                            "substitution; the agent requires one; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            if_stack.append([lineno, False])
            continue

        if _ELSEIF_RE.match(stripped):
            condition = stripped[_ELSEIF_RE.match(stripped).end() :].lstrip()
            if not condition.startswith("{"):
                issues.append(
                    (
                        lineno,
                        "E514",
                        (
                            "`elseif` condition is not a `{...}` relevance "
                            "substitution; the agent requires one; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            if not if_stack:
                issues.append(
                    (
                        lineno,
                        "E505",
                        (
                            f"`elseif` outside any open `if`; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            elif if_stack[-1][1]:
                issues.append(
                    (
                        lineno,
                        "E506",
                        (
                            "`elseif` after `else` for the same `if`; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            continue

        if _ELSE_RE.match(stripped):
            if not if_stack:
                issues.append(
                    (
                        lineno,
                        "E505",
                        (
                            f"`else` outside any open `if`; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            elif if_stack[-1][1]:
                issues.append(
                    (
                        lineno,
                        "E506",
                        (
                            "second `else` for the same `if`; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            else:
                if_stack[-1][1] = True
            continue

        if _ENDIF_RE.match(stripped):
            if not if_stack:
                issues.append(
                    (
                        lineno,
                        "E501",
                        (
                            f"`endif` with no open `if`; add "
                            f"`{IF_MARKER}` if intentional"
                        ),
                    )
                )
            else:
                if_stack.pop()
            continue

    for open_lineno, _seen_else in if_stack:
        issues.append(
            (
                open_lineno,
                "E500",
                (
                    f"`if` is never closed by `endif`; add "
                    f"`{IF_MARKER}` if intentional"
                ),
            )
        )
    for open_lineno, _if_depth_at_open in prefetch_stack:
        issues.append(
            (
                open_lineno,
                "E502",
                (
                    "`begin prefetch block` is never closed by `end prefetch "
                    f"block`; add `{PREFETCH_BLOCK_MARKER}` if intentional"
                ),
            )
        )
    return sorted(issues)


def _iter_actionscript_bodies(raw):
    """Yield (sourceline, body) for every BigFix ActionScript in a BES document.

    Raises etree.XMLSyntaxError if the document does not parse; the callers
    turn that into W500. MIMEType is compared case-insensitively: it is valid
    BigFix content either way.
    """
    root = etree.fromstring(raw)
    for element in root.iter("ActionScript"):
        mimetype = element.get("MIMEType")
        if mimetype is not None and mimetype.strip().lower() != ACTIONSCRIPT_MIMETYPE:
            continue
        yield element.sourceline, element.text or ""


def _validate_bes_xml(raw):
    """Check block balance in every ActionScript of a BES document."""
    try:
        bodies = list(_iter_actionscript_bodies(raw))
    except etree.XMLSyntaxError as err:
        return [(1, "W500", f"not parseable BES XML ({err}); skipping")]
    issues = []
    for sourceline, body in bodies:
        for lineno, code, message in check_actionscript(body):
            issues.append((sourceline + lineno - 1, code, message))
    return issues


def is_bes_file(path):
    """Return True if `path` has a BES XML extension."""
    return path.endswith(BES_EXTENSIONS)


def _encode(src, was_crlf):
    """Turn checked text back into file bytes, restoring CRLF if that is the file."""
    return (src.replace("\n", "\r\n") if was_crlf else src).encode("utf-8")


def check_file(path, disabled=frozenset(), auto_fix=False):
    """Check a single file; return (issues, fixed).

    With `auto_fix`, every wrong-case `__download`/`__createfile`/
    `__appendfile` reference (W503) is rewritten in place to its canonical
    spelling, unless "W503" is in `disabled` or the file opts out with the
    `actionscript-scratch-ok` marker. The file's line endings are preserved
    (CRLF in, CRLF out). No other check here has an auto-fix.
    """
    if not os.path.isfile(path):
        return [(1, "W500", "file not found; skipping")], []

    with open(path, "rb") as handle:
        original = handle.read()
    was_crlf = b"\r\n" in original
    src = (
        original.decode("utf-8", errors="replace")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    if SKIP_MARKER in src:
        return [], []
    if MUSTACHE_RE.search(src):
        return [], []

    is_bes = is_bes_file(path)
    raw = original
    fixed = []
    if auto_fix and "W503" not in disabled and SCRATCH_MARKER not in src:
        src, fixed = fix_scratch_case(src, _scratch_case_targets(raw, src, is_bes))
        raw = _encode(src, was_crlf)
        if raw != original:
            with open(path, "wb") as handle:
                handle.write(raw)

    if is_bes:
        issues = _validate_bes_xml(raw)
    else:
        issues = check_actionscript(src)

    opt_outs = {marker for code, marker in CHECK_MARKERS.items() if marker in src}
    issues = [
        (lineno, code, message)
        for lineno, code, message in issues
        if code not in disabled and CHECK_MARKERS.get(code) not in opt_outs
    ]
    return sorted(issues), fixed


def check_files(paths, disabled=frozenset(), auto_fix=False):
    """Check several files; return a list of (path, issues, fixed) tuples.

    This is the programmatic entry point: it does no printing.
    """
    results = []
    for path in paths:
        issues, fixed = check_file(path, disabled=disabled, auto_fix=auto_fix)
        results.append((path, issues, fixed))
    return results


def discover_bes_files(root="."):
    """Return all .bes files under `root`, pruning hidden and noise directories."""
    skip_dirs = {"__pycache__", "node_modules"}
    root = os.path.normpath(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d not in skip_dirs
        ]
        for name in filenames:
            if name.endswith(".bes"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def _report(results):
    """Print every fix and issue in `results`; return (issues, warnings, fixes)."""
    issue_count = 0
    warning_count = 0
    fix_count = 0
    for path, issues, fixed in results:
        for lineno, check_id, message in fixed:
            fix_count += 1
            print(f"{path}:{lineno}: [{check_id}] auto-fixed: {message}")
        for lineno, check_id, message in issues:
            if check_id.startswith("W"):
                warning_count += 1
                print(f"{path}:{lineno}: [{check_id}] warning: {message}")
            else:
                issue_count += 1
                print(f"{path}:{lineno}: [{check_id}] {message}")
    return issue_count, warning_count, fix_count


def main(argv=None):
    """Execution starts here.

    argv defaults to None so this works both as a console_scripts entry point
    (pre-commit calls it with no arguments; argparse then reads sys.argv) and
    when called directly as `main(sys.argv[1:])`.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as failures (non-zero exit); default: advisory",
    )
    parser.add_argument(
        "--disable",
        default="",
        metavar="CODES",
        help="comma-separated check IDs to skip entirely, e.g. --disable E501",
    )
    parser.add_argument(
        "--auto-fix",
        choices=["yes", "no"],
        default=None,
        help=(
            "rewrite wrong-case __download/__createfile/__appendfile "
            "references (W503) in place to their canonical spelling "
            "(default: yes when files are given, no when auto-discovering)"
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        help=(
            "files to check (.bes/.ojo are read as BES XML, anything else as "
            "raw ActionScript); if omitted, all *.bes files in the current "
            "folder and below are checked"
        ),
    )
    args = parser.parse_args(argv)

    disabled = {
        code.strip().upper() for code in args.disable.split(",") if code.strip()
    }
    unknown = disabled - KNOWN_CODES
    if unknown:
        print(
            f"warning: ignoring unknown --disable code(s): {', '.join(sorted(unknown))}"
        )

    # auto-fix defaults to yes for explicit files, no when auto-discovering; an
    # explicit --auto-fix always wins. This is the sibling hooks' rule, and
    # pre-commit always passes files, so under pre-commit the default is yes.
    if args.auto_fix is not None:
        auto_fix = args.auto_fix == "yes"
    else:
        auto_fix = bool(args.files)
    paths = args.files if args.files else discover_bes_files(".")

    issue_count, warning_count, fix_count = _report(
        check_files(paths, disabled=disabled, auto_fix=auto_fix)
    )

    if fix_count:
        print(f"\nauto-fixed {fix_count} issue(s); review and re-stage the changes.")
    if warning_count:
        print(f"{warning_count} warning(s).")
    if issue_count:
        print(f"{issue_count} issue(s).")
    # E-codes and any fix always fail; warnings fail only under --strict
    return 1 if (issue_count or fix_count or (warning_count and args.strict)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
