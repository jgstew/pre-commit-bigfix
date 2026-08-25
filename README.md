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
      - id: bes-actionscript-validate-script
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

`--auto-fix-network` (off by default) adds the missing sha256 of an `E401` for
you, which means downloading the file to hash it - there is no other way to
learn a sha256. The download is handed to `add_sha256_prefetch()` from
`bigfix_prefetch` (v1.1.5+), which streams the file, checks it against the size
and sha1 already on the line, and re-emits the prefetch with sha256 added, in
the same spelling and keeping the line's own download name. A download that
does not happen or does not match is `W404`: the line is left alone and its
`E401` stands. Each URL is fetched at most once per run, and each download
gives up after 60 seconds.

```yaml
      - id: bes-actionscript-validate-prefetch
        args: ["--auto-fix-network", "yes"]
```

Because this reaches out to whatever URLs the content names, it is opt-in and
never the default - think about it before turning it on for a repo whose
prefetches point at hosts you do not control.

A prefetch that downloads the retired `unzip-5.52.exe` from the BigFix redist
folder is `E402` - `unzip-6.0.exe` is the current one - and it is the hook's
one auto-fix. Auto-fix is on by default; the line is rewritten in place to

```text
add prefetch item name=unzip.exe sha1=84debf12767785cd9b43811022407de7413beb6f size=204800 url=http://software.bigfix.com/download/redist/unzip-6.0.exe sha256=2122557d350fd1c59fb0ef32125330bde673e9331eb9371b454c2ad2d82091ac
```

or the `prefetch ... sha1:... size:...` statement equivalent, whichever
spelling the line already used - the replacement string is built by
`prefetch_from_dictionary()` from `bigfix_prefetch`, so its shape is the
reference implementation's. The original download's *name* is kept (the rest
of the ActionScript refers to the file by that name), while the url, size,
sha1, and sha256 become the current file's. An `add nohash prefetch item` on
the old URL is reported but not rewritten: swapping in a hashed prefetch would
change what the line does, not just which file it fetches. To report `E402`
without rewriting anything:

```yaml
      - id: bes-actionscript-validate-prefetch
        args: ["--auto-fix", "no"]
```

A file whose prefetches knowingly do not meet these rules opts out of every
check in this hook with `prefetch-ok` anywhere in it (e.g.
`<!-- prefetch-ok -->`) - the same marker that opts out of the prefetch-shape
warning `W206` in `bes-conventions-check`, since it is the same judgement.
The usual `<!-- pre-commit-skip: bes-actionscript-validate-prefetch -->` skips
the file too.

The scope of the *checks* is internal validity only, and they are offline: no
check downloads a URL or verifies that the hashes match the real file. The one
thing that touches the network is `--auto-fix-network`, above, and only when it
is asked for. Dynamic
prefetches (a line holding a `{...}` relevance substitution), `//` comments,
and the raw content of a `createfile until` block are skipped - none of them
carry a fixed size and hash to check. The line's overall shape and its
http-vs-https scheme are `W206`/`W207` in `bes-conventions-check`, and its
lexical validity is `E300` in `bes-actionscript-lint-schclass`: three
altitudes on the same line, all intentional.

`E402` and (with `--auto-fix-network`) `E401` are the only auto-fixes, and no
others are planned - `E400`'s correct size and hashes are properties of the
real file, and a hook has no way to know which file was meant. E-codes and any
auto-fix fail the hook; pass `--strict` to also fail on warnings. Unparsable
files are skipped (`bes-schema-validate` owns validity).

See the docstring in
[bes_actionscript_validate_prefetch.py](pre_commit_bigfix/bes_actionscript_validate_prefetch.py)
for the full list of check codes, opt-out markers, and options.

### bes-actionscript-validate-script

Checks every `<ActionScript>` body of a BES file for balanced `if`/`endif` and
`begin prefetch block`/`end prefetch block` pairing - the sibling hook named
in `bes-actionscript-lint-schclass`'s SCOPE note for checks that need pairing,
ordering, and block-interleaving knowledge the lexical grammar does not
carry, and meant to grow more per-script checks over time. An unbalanced
block is a real defect, not a style nit: the BigFix agent fails the action at
runtime on a dangling `if`, and a missing `endif` silently changes which
statements are conditional.

An unclosed `if` is `E500`; a stray `endif` with no open `if` is `E501`. An
unclosed `begin prefetch block` is `E502`; a stray `end prefetch block` is
`E503`; a `begin prefetch block` nested inside another one is `E504`, since
prefetch blocks do not nest. An `else` or `elseif` outside any open `if` is
`E505`; an `elseif` after `else`, or a second `else` for the same `if`, is
`E506`. An `if` opened inside a prefetch block that is still open at that
block's `end prefetch block` is `E507`, since blocks interleave rather than
nest.

This hook has no auto-fixes: a hook has no way to know where a missing
`endif` or `end prefetch block` was meant to go, and guessing could silently
change what the action does.

Only `application/x-Fixlet-Windows-Shell` (matched case-insensitively - it is
valid BigFix content either way) or missing-MIMEType bodies are checked;
bodies are extracted with lxml, so entities are decoded, CDATA sections
merged, and line numbers map back to the file. Lines inside a
`createfile until` block are file content, not ActionScript, and are not
scanned; that block's own well-formedness is `bes-actionscript-lint-schclass`'s
`E302`, not reported here. Unparsable files are `W500` (`bes-schema-validate`
owns validity).

A file opts out of every check here with
`<!-- pre-commit-skip: bes-actionscript-validate-script -->` anywhere in it,
or out of one family with `actionscript-if-ok` (`E500`, `E501`, `E505`,
`E506`), `actionscript-prefetch-block-ok` (`E502`, `E503`, `E504`), or
`actionscript-block-nesting-ok` (`E507`). E-codes fail the hook; pass
`--strict` to also fail on warnings.

See the docstring in
[bes_actionscript_validate_script.py](pre_commit_bigfix/bes_actionscript_validate_script.py)
for the full list of check codes, opt-out markers, and options.

## Development

```bash
pip install -e .[test]
python -m pytest
pre-commit run --all-files
```
