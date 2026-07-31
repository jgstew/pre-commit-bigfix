# pre-commit-bigfix

pre commit hooks for BigFix content

Moved from [pre-commit-jgstew](https://github.com/jgstew/pre-commit-jgstew).

## Usage

Add this to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/jgstew/pre-commit-bigfix
    rev: v0.3.1
    hooks:
      - id: bes-schema-validate
      - id: bes-conventions-check
      - id: bes-actionscript-lint-schclass
      - id: bes-actionscript-validate-prefetch
```

The hooks were renamed to a consistent `bes-<aspect>-<action>` scheme in
v0.3.0. The previous ids (`validate-bes`, `check-bes-conventions`) still work
as deprecated aliases, so existing configs need no changes.

## Hooks

### bes-schema-validate

Validates that BigFix BES XML files (`.bes`, `.ojo`) are well-formed XML that
satisfies the BES.xsd schema, via the
[validate_bes_xml](https://pypi.org/project/validate-bes-xml/) package.

Renamed from `validate-bes`, which is kept as a deprecated alias so existing
configs keep working: both ids run the same entry point, so there is no
behavior difference and no rush to migrate. New configs should use
`bes-schema-validate`.

### bes-conventions-check

Picky, opinionated content checks + auto-fixes for BigFix BES files that the
BES.xsd schema (`bes-schema-validate`) cannot express: ActionScript MIMEType,
value formats for SourceReleaseDate / x-fixlet-modification-time / DownloadSize /
action-ui-metadata / CPE-2.3 / CVENames, prefetch-line shape and https URLs,
CDATA usage, blank-line and trailing-whitespace spacing, empty ActionScript,
dynamic download statements, a UTF-8 XML declaration, Title placeholders and
whitespace, non-trivial non-empty Relevance, unique MIMEField names,
description placeholders, and Task/Fixlet release-date / modification-time
presence.

Auto-fixes the fixable ones in place and exits 1 when anything was fixed so
the change is reviewed and re-staged. E-codes fail the hook; pass `--strict`
to also fail on warnings, or `--errors-only` to leave W-codes out of the report
entirely (the checks and their auto-fixes still run, unlike `--disable`).
Unparsable files are skipped (`bes-schema-validate` owns validity).

Renamed from `check-bes-conventions`, which is kept as a deprecated alias so
existing configs keep working; both ids run the same entry point. Note that
the file-level opt-out marker moved with it, from `pre-commit-skip:
bes-conventions` to `pre-commit-skip: bes-conventions-check`.

See the docstring in
[bes_conventions_check.py](pre_commit_bigfix/bes_conventions_check.py)
for the full list of check codes, opt-out markers, and options.

### bes-actionscript-lint-schclass

Lints every `<ActionScript>` body in BES files against the BigFix console's
own lexical grammar: the vendored
[ExpandedActionScript.schclass](pre_commit_bigfix/schclass_data/ExpandedActionScript.schclass)
(the lex schema the console's editor uses, 323 command verbs) merged with a
[small override file](pre_commit_bigfix/schclass_data/bigfix_overrides.schclass)
of validation corrections the display grammar needs.

The rule: the first token of every line must be a known command verb, a `//`
comment, a `{...}` relevance substitution, a continuation, or the line must be
blank (E300). A `{...}` substitution must close before line end (E301), and a
`createfile until <MARKER>` block must reach its bare marker line (E302; the
block's raw content is excluded from linting). An `override run` / `override
wait` line opens a block whose following `keyword=value` lines are options
rather than commands, checked against the
[documented keywords and values](https://developer.bigfix.com/action-script/reference/execution/override.html)
(E303) -- a value in `{...}` is a relevance substitution and is accepted
unchecked. Verbs match case-insensitively but a non-lowercase verb warns
(W302), an override option keyword or value that is not lowercase warns (W303),
and an unbalanced `"` warns (W301).
Only `application/x-Fixlet-Windows-Shell` (or missing-MIMEType) bodies are
BigFix ActionScript and are linted; `x-sh`, `x-AppleScript`,
`x-Fixlet-Windows-PowerShell`, and `text/x-uri` bodies are other languages and
are skipped. E-codes fail the hook; pass `--strict` to also fail on warnings.
Unparsable files are skipped (`bes-schema-validate` owns validity). Non-`.bes`
paths passed explicitly are linted as raw ActionScript text, so you can widen the
hook's `files` pattern to cover standalone ActionScript files.

The underlying schclass loader ([schclass.py](pre_commit_bigfix/schclass.py))
and tokenizer engine
([schclass_tokenizer.py](pre_commit_bigfix/schclass_tokenizer.py)) are
generic: point them at any `.schclass` file and they lex that language.

This hook's scope is deliberately limited to what the schclass grammar can
decide - the lexical validity of each line. ActionScript checks that need
knowledge the grammar does not carry (per-verb argument shapes, `if`/`endif`
and prefetch-block pairing, the `]]></ActionScript>` closing-tag whitespace
trap, http->https escalation, and any auto-fixes) belong in a separate
ActionScript hook, so this one stays a thin consumer of the grammar files and
needs no code changes when BigFix ships new command verbs.

See the docstring in
[bes_actionscript_lint_schclass.py](pre_commit_bigfix/bes_actionscript_lint_schclass.py)
for the full list of check codes, opt-out markers, and options.

### bes-actionscript-validate-prefetch

Validates every prefetch line in every `<ActionScript>` body with
`validate_prefetch()` from the
[bigfix_prefetch](https://pypi.org/project/bigfix-prefetch/) package, which is
the reference implementation of what a valid prefetch is. Both spellings are
covered:

```text
prefetch <name> sha1:<40> size:<n> <url> sha256:<64>
add prefetch item name=<name> sha1=<40> size=<n> url=<url> sha256=<64>
```

A line that fails validation is `E400`, carrying the reason `bigfix_prefetch`
reported: a missing size or a size that is not > 0, a hash of the wrong
length, a sha1 missing from a prefetch statement (where it is mandatory), or a
line that could not be parsed at all.

A missing sha256 is `E401`. `bigfix_prefetch` calls sha256 optional unless
asked, but in 2026 it is treated as mandatory here. It gets its own code
rather than being folded into `E400` so that a repo which still wants it
optional can turn just that off:

```yaml
      - id: bes-actionscript-validate-prefetch
        args: ["--disable", "E401"]
```

A prefetch block item with no sha1 warns (`W402`), and an
`add nohash prefetch item` line is reported rather than validated (`W403`),
since it is hashless by definition and its download cannot be verified.

A file whose prefetches knowingly do not meet these rules opts out of every
check in this hook with `prefetch-ok` anywhere in it (e.g.
`<!-- prefetch-ok -->`) - the same marker that opts out of the prefetch-shape
warning `W206` in `bes-conventions-check`, since it is the same judgement.
The usual `<!-- pre-commit-skip: bes-actionscript-validate-prefetch -->` skips
the file too.

The scope is internal validity only. This hook is offline: it never downloads
a URL and never checks that the hashes match the real file. Dynamic
prefetches (a line holding a `{...}` relevance substitution), `//` comments,
and the raw content of a `createfile until` block are skipped - none of them
carry a fixed size and hash to check. The line's overall shape and its
http-vs-https scheme are `W206`/`W207` in `bes-conventions-check`, and its
lexical validity is `E300` in `bes-actionscript-lint-schclass`: three
altitudes on the same line, all intentional.

There are no auto-fixes, and none are planned - the correct size and hashes
are properties of the real file, which only a download can learn. E-codes fail
the hook; pass `--strict` to also fail on warnings. Unparsable files are
skipped (`bes-schema-validate` owns validity).

See the docstring in
[bes_actionscript_validate_prefetch.py](pre_commit_bigfix/bes_actionscript_validate_prefetch.py)
for the full list of check codes, opt-out markers, and options.

## Development

```bash
pip install -e .[test]
python -m pytest
pre-commit run --all-files
```
