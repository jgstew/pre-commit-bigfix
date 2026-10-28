# pre-commit-bigfix

pre commit hooks for BigFix content

Moved from [pre-commit-jgstew](https://github.com/jgstew/pre-commit-jgstew).

## Usage

Add this to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/jgstew/pre-commit-bigfix
    rev: v2.0.0
    hooks:
      - id: bes-schema-validate
      - id: bes-conventions-check
      - id: bes-actionscript-lint-schclass
      - id: bes-actionscript-validate-prefetch
      - id: bes-actionscript-validate-script
      - id: bes-relevance-lint
      - id: bes-relevance-convert-group
      - id: bes-content-score-risk
      # only in a Git External Custom Site (repository site) repo:
      - id: bes-siterepo-validate-layout
```

The hooks were renamed to a consistent `bes-<aspect>-<action>` scheme in
v0.3.0. The deprecated aliases for the previous ids (`validate-bes`,
`check-bes-conventions`) have since been removed, along with the console
scripts of the same names: a config using them now fails with pre-commit's
"hook id not found" error. Use `bes-schema-validate` and
`bes-conventions-check` instead.

## Run without pre-commit

The `pre-commit-bigfix` command runs every hook over a folder, without
pre-commit or a git commit:

```bash
uvx --from git+https://github.com/jgstew/pre-commit-bigfix pre-commit-bigfix
```

Once the package is on PyPI, this is just `uvx pre-commit-bigfix`. Give one or
more files or folders to check (default: the current folder). Each hook gets
the files its `files` pattern matches, with its default `args`, and a summary
line per hook is printed at the end. The exit code is 1 if any hook fails, and
2 for a path that does not exist or a bad option.

- It is **read-only**. Under pre-commit several hooks fix files in place; here
  each is run with `--auto-fix=no` (or `--check` for
  `bes-relevance-convert-group` and `bes-siterepo-validate-layout`), so
  fixable problems are reported, not fixed. Run a hook directly, or use
  pre-commit, to apply fixes.
- Hidden folders (a name starting with `.`, or the hidden flag on macOS and
  Windows) are not searched; pass `--include-hidden` to search them.
  `__pycache__` and `node_modules` are never searched. A folder named on the
  command line is always searched.
- Symlinked files found while searching are skipped, as pre-commit skips
  them. A file named on the command line that no hook checks is reported.
- `bes-siterepo-validate-layout` runs once in each git repo that holds a given
  path, and is skipped when none does. It is also skipped, and not counted
  as a failure, in a repo that shows no sign of being a site: git tracks no
  `site.xml` or `siteConfig.xml` file and no `Fixlets`, `NonClientFiles` or
  `OtherFiles` folder at its top (names compared ignoring case).
- A hook with more than 20 results is summarized instead of listed: a count
  per code, and the files with the most results. The summary table at the end
  shows each hook's result count. If anything was summarized and no log file
  is being written, the last line says to run again with `--log-file`.
- `--log-file [FILE]` writes every hook's full output to FILE (default
  `pre-commit-bigfix-results.log`), replacing it if it exists. This is the
  only file the command writes, and it will not replace a given path or a
  file some hook checks. Give paths to check before `--log-file`, or use
  `--log-file=FILE`, so a path is not taken as FILE.
- `--skip HOOK` (repeatable) leaves a hook out.

## Hooks

### bes-schema-validate

Validates that BigFix XML files are well-formed and satisfy their schema, via
the [validate_bes_xml](https://pypi.org/project/validate-bes-xml/) package
(`>= 2.4.1`). It checks these files:

| Files | Root tag | Schema |
|---|---|---|
| `*.bes` | `<BES>` | `BES.xsd` |
| `*.ojo` | any | `BESOJO.xsd` |
| `siteConfig.xml` (Git External Custom Site) | `<SiteConfig>` | `SiteConfig.xsd` |
| `site.xml` (Git External Custom Site) | `<Site>` | `Site.xsd` |
| `digest.xml` (Git External Custom Site) | `<Digest>` | `Digest.xsd` |
| `Signatures/*.xml` (BigFix Inventory signatures) | `<SoftwareIdentityCatalog>` | `SoftwareIdentityCatalog.xsd` |

The file names only decide which files the hook sees. Apart from `.ojo`
files, which always use `BESOJO.xsd`, the schema is picked by the root tag:
the bundled schema with the same name, ignoring case. So a `digest.xml` whose
root is `<SiteConfig>` is checked against `SiteConfig.xsd`, and a `.bes` file
whose root is `<BESAPI>` against `BESAPI.xsd`.

The hook's `files` pattern is:

```text
\.(bes|ojo)$|(^|/)(siteConfig|site|digest)\.xml$|(^|/)Signatures/[^/]+\.xml$
```

The `.xml` names are matched case-sensitively, as BigFix documents them, and
only signature files directly inside a `Signatures/` folder are matched. Keep
signatures elsewhere? Set `files:` in your own config.

Only the schemas bundled with validate_bes_xml are used. A `*.xsd` in the
repo (a copy of `site.xsd` from RepositorySiteExample, say) is ignored, so a
`.bes` file whose root tag has no bundled schema fails here as it would
anywhere else.

A `.xml` file that is not a BigFix file, such as a sitemap or a Maven site
descriptor named `site.xml`, has no bundled schema for its root tag and is
skipped. An Eclipse update-site `site.xml` is the exception: its root is a
plain `<site>`, which matches `Site.xsd` (schema names match without regard
to case), so it is validated and fails. If your repo holds Eclipse update
sites, exclude them:

```yaml
      - id: bes-schema-validate
        exclude: ^eclipse/.*site\.xml$
```

Files that pass print nothing. Each error is printed as `path:line: message`,
or `path: message` when there is no line number, and the exit code is the
number of files that failed:

```text
Sites/Foo/siteConfig.xml:4: Element 'BesFileDir': This element is not expected. Expected is one of ( NonClientFilesDir, OtherFilesDir ).
Sites/Foo/Fixlets/A/digest.xml:4: Element 'DigestRelevanceEvaluationPeriod': [facet 'enumeration'] The value 'PT10M' is not an element of the set {...}.
unknown.bes: no schema to validate this file against
```

Renamed from `validate-bes`, whose deprecated alias has been removed.

### bes-conventions-check

Picky, opinionated content checks + auto-fixes for BigFix BES files that the
BES.xsd schema (`bes-schema-validate`) cannot express: ActionScript MIMEType,
value formats for SourceReleaseDate / x-fixlet-modification-time / DownloadSize /
action-ui-metadata / CPE-2.3 / CVENames / x-relevance-evaluation-period,
prefetch-line shape (URL schemes overridable with `--prefetch-url-schemes`)
and https URLs, CDATA usage, blank-line and
trailing-whitespace spacing, empty ActionScript, dynamic download statements,
a UTF-8 XML declaration, Title placeholders / whitespace / TODO markers,
non-trivial non-empty Relevance with no stray whitespace, unique MIMEField
names, unique Analysis Property names/IDs, unique Action IDs, action link text
free of empty-substitution gaps, SuccessCriteria body/Option consistency, a
SourceSeverity vocabulary (default Low/Moderate/Important/High/Critical,
overridable with `--severity-values`; `Unspecified` is auto-fixed to empty), description placeholders / empty
descriptions, a Description `<script>` block free of `//` line comments
(lost when the file is converted to FXF, since Description newlines are
collapsed), and Task/Fixlet release-date / modification-time presence and order
(a SourceReleaseDate later than the modification time warns `W219`), and a
`DownloadSize` that does not match the prefetches' total (`W220`, only when
that total is knowable), and a Relevance that waits for a client setting value
the action never sets (`W221`).

Auto-fixes the fixable ones in place and exits 1 when anything was fixed so
the change is reviewed and re-staged. Only rewrites whose right answer is
knowable from the file are made: besides the whitespace, CDATA, date-insert
and XML-declaration fixes, a missing ActionScript MIMEType gets the
Windows-Shell default (`E200`), an unambiguous year-first SourceReleaseDate
or a loosely-formatted timestamp is respelled (`E201`/`E202`/`E216` - a wrong
day-of-week is dropped, not recomputed), a `cve-` prefix is uppercased
(`E209`, several `<CVENames>` are not merged), an evaluation period is
zero-padded (`E219`), a case-only SourceSeverity mismatch is respelled
(`W216`), and a DownloadSize that disagrees with a knowable prefetch total is
set to it (`W220`). E-codes fail the hook; pass `--strict`
to also fail on warnings, or `--errors-only` to leave W-codes out of the report
entirely (the checks and their auto-fixes still run, unlike `--disable`).
`--check-filename` (off by default) additionally checks that a file's
basename matches its first content object's Title. Unparsable files are
skipped (`bes-schema-validate` owns validity).

Renamed from `check-bes-conventions`, whose deprecated alias has been
removed. The file-level opt-out marker moved with it, from `pre-commit-skip:
bes-conventions` to `pre-commit-skip: bes-conventions-check`.

See the docstring in
[bes_conventions_check.py](https://github.com/jgstew/pre-commit-bigfix/blob/main/pre_commit_bigfix/bes_conventions_check.py)
for the full list of check codes, opt-out markers, and options.

Auto-fixes are checked against BES.xsd in three groups: all the per-block
fixes together, the trailing-whitespace strip, and the XML declaration. A
group that would turn a schema-valid file into an invalid one is not written
and is reported as `E222`; the other groups still are (`--disable E222` writes
it anyway). Because the per-block fixes are one group, one bad block fix holds
back every block fix in the file.

### bes-actionscript-lint-schclass

Lints every `<ActionScript>` body in BES files against the BigFix console's
own lexical grammar: the vendored
[ExpandedActionScript.schclass](https://github.com/jgstew/pre-commit-bigfix/blob/main/pre_commit_bigfix/schclass_data/ExpandedActionScript.schclass)
(the lex schema the console's editor uses, 323 command verbs) merged with a
[small override file](https://github.com/jgstew/pre-commit-bigfix/blob/main/pre_commit_bigfix/schclass_data/bigfix_overrides.schclass)
of validation corrections the display grammar needs.

The rule: the first token of every line must be a known command verb, a `//`
comment, a `{...}` relevance substitution, a continuation, or the line must be
blank (E300; the message quotes the whole offending line and, when the
grammar narrows it to a handful of known commands, offers a `did you mean` --
e.g. `action log commands` suggests `action log command`). A `{...}`
substitution must close before line end (E301), and a
`createfile until <MARKER>` block must reach its bare marker line (E302; the
block's raw content is excluded from linting). An `override run` / `override
wait` line opens a block whose following `keyword=value` lines are options
rather than commands, checked against the
[documented keywords and values](https://developer.bigfix.com/action-script/reference/execution/override.html)
(E303) -- a value in `{...}` is a relevance substitution and is accepted
unchecked. Verbs match case-insensitively but a non-lowercase verb warns
(W302), an override option keyword or value that is not lowercase warns (W303),
and an unbalanced `"` warns (W301). ActionScript has no escape character, so
`"C:\Bes\"` is a closed string; only a `regset`/`regset64` value, which uses
`.reg`-file syntax, treats `\"` as an escaped quote, and `appendfile` content
is raw file text that is not checked.
Only `application/x-Fixlet-Windows-Shell` (or missing-MIMEType) bodies are
BigFix ActionScript and are linted; `x-sh`, `x-AppleScript`,
`x-Fixlet-Windows-PowerShell`, and `text/x-uri` bodies are other languages and
are skipped. E-codes fail the hook; pass `--strict` to also fail on warnings.
Unparsable files are skipped (`bes-schema-validate` owns validity). Non-`.bes`
paths passed explicitly are linted as raw ActionScript text, so you can widen the
hook's `files` pattern to cover standalone ActionScript files.

The underlying schclass loader ([schclass.py](https://github.com/jgstew/pre-commit-bigfix/blob/main/pre_commit_bigfix/schclass.py))
and tokenizer engine
([schclass_tokenizer.py](https://github.com/jgstew/pre-commit-bigfix/blob/main/pre_commit_bigfix/schclass_tokenizer.py)) are
generic: point them at any `.schclass` file and they lex that language.

This hook's scope is deliberately limited to what the schclass grammar can
decide - the lexical validity of each line. ActionScript checks that need
knowledge the grammar does not carry (per-verb argument shapes, `if`/`endif`
and prefetch-block pairing, the `]]></ActionScript>` closing-tag whitespace
trap, http->https escalation, and any content-changing auto-fixes) belong in
a separate ActionScript hook, so this one stays a thin consumer of the grammar
files and needs no code changes when BigFix ships new command verbs. Its one
auto-fix changes only case: `--auto-fix` (on by default when files are given,
as pre-commit does) lowercases a `W302` verb or `W303` override option in
place, and an auto-fixed file fails the hook so it is reviewed and re-staged;
`args: ["--auto-fix", "no"]` reports them without rewriting.

See the docstring in
[bes_actionscript_lint_schclass.py](https://github.com/jgstew/pre-commit-bigfix/blob/main/pre_commit_bigfix/bes_actionscript_lint_schclass.py)
for the full list of check codes, opt-out markers, and options.

The case fixes are checked against BES.xsd together. If they would turn a
schema-valid file into an invalid one, none of them are written and `E304` is
reported (`--disable E304` writes them anyway).

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
length, or a line that could not be parsed at all.

A missing sha256 is `E401`. `bigfix_prefetch` calls sha256 optional unless
asked, but in 2026 it is treated as mandatory here. It gets its own code
rather than being folded into `E400` so that a repo which still wants it
optional can turn just that off:

```yaml
      - id: bes-actionscript-validate-prefetch
        args: ["--disable", "E401"]
```

A prefetch block item with no sha1 warns (`W402`); a prefetch *statement* with
no sha1 warns (`W405`) instead of failing the line - current BigFix clients
accept a statement with sha256 alone, so this is unusual but valid. A
declared name whose extension differs from the extension of the URL's file
warns (`W406`) - e.g. `<sha1>.msi` fetched from `ccsetup531.exe` - since the
extension decides how the file is run or unpacked. An extension is a trailing
`.` plus 1-4 characters including a letter; names or URLs without one, and
server-side script URLs such as `download.php`, are not compared, and a URL
that is the declared name with one more extension appended (`7z.dll.txt`, a
way past web filtering) counts as a match. Text the prefetch syntax does not
define is `E403` - a stray token (an AutoPkg template's
`vs_SSMS.exe; filename*=UTF-8''vs_SSMS.exe`), a misspelt field (`sha2:`), an
unencoded space splitting the URL - since the reference parser silently
ignores it; a space-separated trailing `// comment` is fine. The two shapes
with one meaning each are auto-fixed offline: `sha2:` before a 64-hex value
becomes `sha256:`, and a space directly after the URL becomes `%20`; any
other stray text is left for a human. An
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

The same flag switches an `http://` prefetch URL to `https://` (the fix for
`bes-conventions-check`'s `W207`), but only once the https copy is proven to be
the same file: a HEAD request must report a `Content-Length` equal to the
line's size - checked *before* anything is downloaded - and must not redirect
off https; then the download's size and every hash on the line must match.
Only the scheme changes. Anything else is `W407` and the line stays on http;
`--disable W407` turns this part off.

```yaml
      - id: bes-actionscript-validate-prefetch
        args: ["--auto-fix-network", "yes"]
```

Because this reaches out to whatever URLs the content names, it is opt-in and
never the default - think about it before turning it on for a repo whose
prefetches point at hosts you do not control.

A prefetch that downloads the retired `unzip-5.52.exe` from the BigFix redist
folder is `E402` - `unzip-6.0.exe` is the current one - and it is auto-fixed
offline. Auto-fix is on by default; the line is rewritten in place to

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

`E402`, the two `E403` shapes above, and (with `--auto-fix-network`) `E401`
and the `W207` https switch are the only auto-fixes, and no others are
planned - `E400`'s correct size and hashes are properties of the
real file, and a hook has no way to know which file was meant. E-codes and any
auto-fix fail the hook; pass `--strict` to also fail on warnings. Unparsable
files are skipped (`bes-schema-validate` owns validity).

See the docstring in
[bes_actionscript_validate_prefetch.py](https://github.com/jgstew/pre-commit-bigfix/blob/main/pre_commit_bigfix/bes_actionscript_validate_prefetch.py)
for the full list of check codes, opt-out markers, and options.

Auto-fixes are checked against BES.xsd one pass at a time, in the order
`E403`, `E402`, `E401`, `W407`. A pass that would turn a schema-valid file
into an invalid one is not written and is reported as `E404`; the other passes
still are (`--disable E404` writes it anyway).

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

Within a single line, a `{...}` relevance substitution that is never closed
before end of line is `E508`, and a `}` reached with no substitution open is
`E509`: a substitution is evaluated per line and cannot span lines. `E508`
also applies to `createfile until` content, which the agent substitutes too,
so a literal `{` in an embedded script must be written `{{` (a lone `}` there
is literal and is not `E509`). `{{` (and
`}}`) is an escape that passes a literal brace through to the command, so it
neither opens nor closes a substitution, and a later lone `}` pairs with that
escape instead of being reported as stray. The `}}` escape holds *inside* an
open substitution too - a quoted literal like `{ ... "@{'k'='v'}}" ... }`
(a PowerShell hashtable nested inside a substitution) does not close on the
first `}` of that `}}`.

An `add prefetch item` or `collect prefetch items` outside an open prefetch
block is `E510`/`E511` - the agent rejects them there. Two prefetch/download
producers declaring the same download name in the same conditional context is
`E512` (the second silently overwrites the first); declarations reached
through different `if`/`elseif`/`else` branch choices are not compared, since
cross-platform content routinely declares the same `name=` once per OS in a
separate `if` per platform, and a `__Download\<name>` reference that nothing
prefetches or downloads warns `W507` - a typo catcher that is skipped entirely
whenever any producer's names are unknowable (an `extract`/`unarchive`/
`archive now`/`utility` command, a `download` with no `as <name>` and no
literal URL basename, or a `{...}` substitution in a name or URL); a
`delete` or `folder delete` of a `__Download\<name>` is cleanup, not
consumption, and never counts as a reference. A script can create files under
`__Download` too, so `copy`/`move` destinations (including from
`__createfile`) and shell redirection targets (`... > __Download\<name>`)
count as producers. An
`if`/`elseif` whose condition is not a `{...}` relevance substitution is
`E514`, and `else if` written as two words (not a chained branch; use
`elseif`) is `E524`. A `begin prefetch block` that is not at the top of the script is
`E515`: only blank lines, `//` comments, `action parameter query` lines, and
`parameter` assignments may precede it - plain `prefetch` statements are legal
anywhere in a script and are not placement-checked.

Two `parameter "name" = ...` assignments to the same name that can co-execute
(the same conditional-context rule as `E512`) is `E516` - action parameters
are write-once, and the second assignment silently overwrites the first. A
`parameter "name"` reference before that name's assignment elsewhere in the
body is `E517`; a name never assigned in-script (a secure parameter supplied
from the Description page, say) is not `E517`, since this hook cannot see it -
but if the name occurs nowhere else in the whole file (not assigned, queried,
or mentioned by a Description form) it warns `W508`: that is almost always
copy-paste from a sibling fixlet, and the substitution fails at runtime. The
platform-supplied `action issue date` is exempt. A `continue if` or `pause while` condition that is not a `{...}`
relevance substitution is `E518` - the same rule `E514` applies to `if`/
`elseif`, extended to these two other condition-bearing verbs.

A command referencing `__createfile` or `__appendfile` when the body has no
matching `createfile until` / `appendfile` line anywhere is `E519` - the
`W507` rule reapplied to these two scratch-file verbs, with the same
`delete`/`folder delete` cleanup exemption. Any `__Download`, `__createfile`,
or `__appendfile` reference whose case does not match exactly warns `W503`:
Windows tolerates the mismatch, a case-sensitive Linux/macOS filesystem does
not. It is auto-fixed (see below).

A `setting` line that is not the documented
`setting "name"="value" on "{...}" for client|user|action` shape is `E520` -
a missing effective-date clause fails at runtime. A
`regset`/`regset64`/`regdelete`/`regdelete64` key that is not a quoted,
bracketed `"[HKEY_...]..."` keyname is `E521`. An
`action uses wow64 redirection` argument that is not `true`, `false`, or a
`{...}` substitution is `E523`.

A `wait`/`run` of cmd.exe that passes a command line but no `/c` warns
`W505`: without the switch cmd.exe opens an interactive shell and never runs
the command, so the action reports success having done nothing. `/k` is
likewise flagged: it does run the command, but leaves the shell open
afterward, so the action hangs instead of completing.

A `move`/`copy` of any source (a `__createfile`/`__appendfile` scratch file,
a download, ...) onto a destination that is not cleared earlier in the body
warns `W506` - cleared meaning a `delete` of it (including one that looks the
same file up by relevance), a shell `rm`/`del` naming it, or a `move` of it
elsewhere. Both verbs fail when the
destination already exists, so such an action works the first time and fails
on every later run; the documented pattern is to `delete` the destination
first. A destination inside the action's own download folder is exempt, being
action-scoped rather than a persistent location, and a `folder delete` of an
ancestor counts as clearing it.

An `override wait` / `override run` block not terminated by its own matching
verb - it hits end of body, is terminated by the *other* verb's command, or
is reopened by another `override` before any command runs - is `E522`.
`bes-actionscript-lint-schclass` validates the `keyword=value` option lines
inside a block (its `E303`); this is the pairing check that block's state
machine cannot express.

A command after an unconditional `exit`, `restart`, or `shutdown` (one outside
any `if`) can never run and warns `W501` (first unreachable line only); an
`action parameter query` after the first execution command warns `W502` -
these are console-time prompts and belong at the top.

A `parameter "<name>" = <value>` whose value is not double-quoted is `E527`:
the agent substitutes `{...}` first and then parses the line, so an unquoted
value - even a singular `{"a"}` - is invalid `parameter` syntax and the line
fails at runtime. A trailing `// comment` on a `parameter` line is `E528`:
only fixed-syntax lines (`if`/`elseif`/`else`/`endif`, the prefetch block,
`override`) accept one, so the line fails even with a quoted value.

`--auto-fix` (`W503`, `W506`, `E525`, `E528`, `E527`, `E524`, `W505`, `E521`), on by default when files are given (as
pre-commit does) and off when auto-discovering, rewrites every wrong-case
`__download`/`__createfile`/`__appendfile` reference to its canonical
spelling, inserts a `delete <destination>` before each `W506` move/copy, and
quotes each unquoted `folder create`/`folder delete` path (`E525` - quoted even
when today's value has no spaces, since a user profile or parameter can),
moves a `parameter` line's trailing comment onto its own line above (`E528`),
quotes an unquoted `parameter` value (`E527` - `&quot;` in an entity-escaped
body; a value holding a `"` outside `{...}` or `%22` is reported, not fixed),
joins `else if` into `elseif` (`E524`, unless a stray `endif` shows a real
nested `if`), turns a waiting cmd.exe's `/k` into `/c` or inserts a missing
`/c` after its leading switches (`W505`), and quotes a bracketed-but-unquoted
registry key (`E521`), in place; an auto-fixed file fails the hook so the
change is reviewed and re-staged. No other check here has an auto-fix: a hook
has no way to know where a missing `endif` or `end prefetch block` was meant
to go, and guessing could silently change what the action does.

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
`E506`, `E514`, `E518`, `E524`), `actionscript-prefetch-block-ok` (`E502`, `E503`,
`E504`), `actionscript-block-nesting-ok` (`E507`), `actionscript-substitution-ok`
(`E508`, `E509` - the same marker `bes-actionscript-lint-schclass` uses for
its `E301`, so one marker covers both hooks),
`actionscript-prefetch-placement-ok` (`E510`, `E511`, `E515`),
`actionscript-download-ok` (`E512`, `W507`), `actionscript-parameter-ok`
(`E516`, `E517`, `E527`, `E528`, `W508`), `actionscript-scratch-ok` (`E519`, `W503`),
`actionscript-scratch-dest-ok` (`W506`),
`actionscript-command-shape-ok` (`E520`, `E521`, `E523`, `E525`),
`actionscript-cmd-ok` (`W505`),
`actionscript-override-ok` (`E522` - shared with
`bes-actionscript-lint-schclass`'s `E303`), `actionscript-unreachable-ok`
(`W501`), or `actionscript-parameter-query-ok` (`W502`). E-codes fail the
hook; pass
`--strict` to also fail on warnings.

See the docstring in
[bes_actionscript_validate_script.py](https://github.com/jgstew/pre-commit-bigfix/blob/main/pre_commit_bigfix/bes_actionscript_validate_script.py)
for the full list of check codes, opt-out markers, and options.

Auto-fixes are checked against BES.xsd one pass at a time: `W503`, `W506`,
`E525`, `E528`, `E527`, then the `E524`/`W505`/`E521` line rewrites as one pass. A pass that
would turn a schema-valid file into an invalid one is not written and is
reported as `E526`; the other passes still are (`--disable E526` writes it
anyway).

### bes-relevance-lint

Every other hook here treats relevance as opaque - `{...}` is a lexer state
mechanically identical to a string literal, and the most any check proves about
a condition is that it starts with a brace. This hook is where that stops. It
hands each statement to
[bigfix-relevance-analyzer](https://github.com/jgstew/bigfix-relevance-analyzer),
which parses it, binds `it`, resolves every inspector against the client dumps,
type-checks the result, and scores what it costs to evaluate.

Every site the analyzer's extractor recognizes is checked - `<Relevance>`
bodies, `<SuccessCriteria Option="CustomRelevance">` bodies, Analysis
`<Property>` bodies, and the `{...}` substitutions inside `<ActionScript>` - so
a defect in a substitution is reported at the line it lives on, not at the top
of the file.

| code | meaning |
| --- | --- |
| `E600` | the statement could not be parsed |
| `E601` | the statement contains text that could not be lexed |
| `E602` | `it` is used where there is no context to bind it to |
| `E603` | the type checker reported a problem beyond an unbound `it` |
| `E604` | the complexity score is above the ceiling (raise with `--max-score`) |
| `E605` | the evaluation cost is above the ceiling (raise with `--max-evaluation-cost`) |
| `E606` | a directory tree was deeper than `--max-depth`, so it was not fully scanned (auto-discovery only; pre-commit always passes filenames) |
| `E607` | a path given to the linter does not exist, could not be read, or is not a file type the analyzer recognizes (the hook's `files:` pattern keeps those away under pre-commit) |
| `E608` | the value does not fit the kind of site it came from: a `<Relevance>` that is not a boolean, or an `if`/`elseif`/`continue if` condition that is not a boolean or string |
| `E609` | inspectors exclusive to client relevance and to session relevance in one statement, which no engine can answer |
| `E610` | an ActionScript command word used as a relevance name, usually an ActionScript line pasted or doubled into relevance |
| `E611` | a plural operand where the engine requires a single value, which it refuses before evaluating anything; a `unique value of` (or singular-aggregate) rewrite is printed as a suggested fix where safe |
| `E612` | an ActionScript `{` with anything after it on its line and no `}` to close it there, which fails the action |
| `E613` | a `<?Relevance` with no closing `?>`, so its relevance was not linted |
| `E614` | a BES file that is not well-formed XML, so nothing in it was linted (**off by default**; `--enable E614`) |
| `W600` | a name no inspector dump defines |
| `W601` | a property written singular over an object that may be plural |
| `W602` | a singular spelling mid-chain (under a `whose` filter, or where a plural is built from it), where the plural reads safer |
| `W603` | two version-looking strings compared as strings, not as versions |
| `W604` | a version comparison that truncates to the shorter operand's components |
| `W605` | an ordinary ActionScript substitution's value is an opaque object with no text form |
| `W606` | an ordinary ActionScript substitution's value may be more than one value; the client joins them with no separator |
| `W607` | a relevance-tagged markdown code fence that is never closed, so its relevance was not linted (manual runs on markdown only) |

`W600` is a warning rather than an error because a repo running a newer client
than the analyzer's dump snapshot legitimately uses names it has never heard
of. `W601` is **disabled by default** in the hook declaration: across 1,108
`.bes` files of real content it fires 6,127 times, which drowns everything
else. Switch it back on with `--enable W601`.

Unparsable XML is skipped rather than reported (`E614` is off by default) -
`bes-schema-validate` owns file validity. That does mean a truncated file passes this hook: a clean run
says the relevance that could be extracted is sound, not that the file parses.

A file opts out of every check here with
`<!-- pre-commit-skip: bes-relevance-lint -->` anywhere in it. There is no
per-rule marker: `--disable` takes a code repo-wide, and a single file that
legitimately needs relevance this complex is what `--max-score` is for. Files
are never rewritten, but where the analyzer can work out a safe rewrite of a
whole statement (today, the singular spellings behind `W602`) the fixed
statement is printed once under its first finding as `suggested fix: ...`.
E-codes fail the hook; pass `--strict` to also fail on warnings.

This hook needs **Python 3.11 or newer** - the analyzer requires it, while the
rest of this package still runs on 3.8. No specific interpreter is pinned, since
`language_version` names an exact executable and pinning `python3.11` would
break machines that only have something newer; set it yourself
(`language_version: python3.12`) if pre-commit's default is too old. The
dependency carries a matching environment marker, so the other hooks stay
installable on 3.8-3.10; run this one there anyway and it prints why it cannot
run and skips (exit 0) - no config on a 3.8-3.10 interpreter can make it pass,
so failing there would only be an unfixable red build. On 3.11+ a missing
analyzer is a broken install, and the hook still fails.

See the docstring in
[bes_relevance_lint.py](https://github.com/jgstew/pre-commit-bigfix/blob/main/pre_commit_bigfix/bes_relevance_lint.py) for the full
list of check codes and options.

### bes-relevance-convert-group

The BigFix console can save applicability as a computer-group style
`<GroupRelevance>`: a list of search components, each already carrying its own
`<Relevance>`, joined by intersection or union. BES.xsd allows either that or a
run of `<Relevance>` elements in the same place, and plain relevance is what
reads and diffs well, so this hook rewrites each `/BES/*/GroupRelevance` in
place:

| `JoinByIntersection` | components | becomes |
| --- | --- | --- |
| `true` | any | one `<Relevance>` per component (sibling Relevance must all hold) |
| `false` | one | `<Relevance>s1</Relevance>` |
| `false` | two or more | `<Relevance>(s1) OR (s2) OR ...</Relevance>` |

Each component's relevance is copied verbatim - CDATA stays CDATA, escaped
stays escaped - except an OR-join of several, which is decoded, joined, and
written once: as CDATA when any input was CDATA or the text holds `<`, `>` or
`&`, and entity-escaped if it contains `]]>`. The splice leaves everything
outside the replaced block byte-identical, line endings included. A long union
can become one large statement; `bes-relevance-lint` may then report `E604`.

| code | meaning |
| --- | --- |
| `E700` | a GroupRelevance was converted (under `--check`: needs converting) |
| `E701` | a GroupRelevance holds a `SearchComponentGroupReference`; group membership is not converted yet, so it is left unchanged |
| `E702` | `JoinByIntersection` is not a boolean, or is missing with two or more components (BES.xsd documents no default; a single component converts either way); left unchanged |
| `E703` | a GroupRelevance has no components, or one with an empty Relevance; left unchanged |
| `E704` | the converted file would turn a schema-valid file invalid, so nothing is written |
| `W700` | skipped: file missing or not parseable XML, or a GroupRelevance that could not be located |

The hook converts by default and exits 1 when it changed anything, so the
rewrite shows up for review; `--check` only reports. With no files given it
checks every `*.bes` below the current folder and never rewrites. A file opts
out with `<!-- pre-commit-skip: bes-relevance-convert-group -->`.

### bes-content-score-risk

Scores how risky a BES file's content is and lists the reasons, so content
that needs a careful human review is flagged before it is trusted. It is a
triage signal, not a verdict, and it never changes a file. Each finding adds
points; a file at or over `--fail-score` (default 50, the HIGH band) fails
with `E900`.

| code | points | signal |
| --- | --- | --- |
| `W901` | 20 | script in a Description: `<script>`, `javascript:`, an `on*=` handler |
| `W902` | 25 | session relevance in a Description: `<?relevance ...?>`, `EvaluateRelevance(` |
| `W903` | 15 | both in one Description |
| `W910` | 25 | ActionScript `download` / `download now`: not hashed. A later `continue if {sha1 of ...}` does not excuse it; use a prefetch |
| `W911` | 25 | `add nohash prefetch item` |
| `W912` | 10 | a download or prefetch URL over plain `http://` or to a raw IP |
| `W913` | 15 | a download command in script content (`curl`, `wget`, `Invoke-WebRequest`, `DownloadString`, `bitsadmin`, ...) |
| `W920` | 2 | base64 that really is an image of its `data:image/` type |
| `W921` | 20 | base64 (80+ characters) anywhere else |
| `W922` | 25 | a decoded payload is an executable or a script |
| `W923` | 20 | a decode-and-run command: `certutil -decode`, `base64 -d`, `FromBase64String`, `powershell -EncodedCommand` |
| `W924` | 15 | other obfuscation: `\x`, `\u`, `%XX` or hex runs decoding to ASCII; `eval(`, `unescape(`, `atob(`, `Function(`, `fromCharCode(` |
| `W925` | 15 | a decoded payload is gzip, zlib or zip compressed |
| `W926` | 30 | base64 labelled `data:image/` whose bytes are not that image |
| `W927` | 10 + inner | a decoded payload holds findings of its own; names the decode path (`base64->gzip->text`) |
| `W900` | | a MEDIUM score (25-49) |
| `W908` | | not parseable XML; skipped |
| `E900` | | the score is at or over `--fail-score` |

Every encoded blob is decoded and scanned again: base64 as UTF-8 and as
UTF-16LE (PowerShell `-EncodedCommand`), compressed data decompressed, up to
3 layers and 4 MB per file. `--weight CODE=N` changes a signal's points,
`--disable CODES` skips signals, and `--fail-score N` moves the threshold.
The default weights are a starting point, to be tuned against real content.

### bes-siterepo-validate-layout

For a BigFix [Git External Custom Site](https://help.hcl-software.com/bigfix/11.0/platform/Platform/Config/c_repository_site_git.html)
("repository site", BigFix 11.0.7+) repo. The root server gathers the site
from git, and one bad file can fail the whole sync, so this hook checks the
site as a whole: it runs once per commit (`pass_filenames: false`,
`always_run: true`) on the files `git ls-files` lists, so untracked and
ignored files do not count.

The site root is the repo root, or each `--site-root DIR` (repeatable, for a
repo of several sites like CommunityContent's `Sites/<name>/`). Its
`siteConfig.xml`, if tracked, names the folders (`BesFileDir`,
`NonClientFilesDir`, `OtherFilesDir`); the defaults are `Fixlets`,
`NonClientFiles` and `OtherFiles`.

A root server can run Windows or RHEL, and one repo site may serve both, so
names and paths must be valid on both: the stricter limit always applies.
Folder names, the `.bes` extension and `digest.xml` match ignoring case, as
on Windows, so nothing goes unchecked; one that matches only that way is a
warning (`W808`), since RHEL is case-sensitive.

| code | meaning |
| --- | --- |
| `E800` | a `.bes` file in the `.bes` folder whose name does not start with a numeric ID and a space or hyphen; `42- Name.bes` and `42 Name.bes` both work |
| `E801` | two or more `.bes` files in one site share an ID, compared as integers, so `0042` and `42` collide; each names the others |
| `E802` | a `.bes` file's server path is too long and the rename cannot fix it: even `<ID> X.bes` is too long (the folders are), it has no ID, or `E805` is disabled. Renaming a folder changes its `.fxf` or digest, so that is left to you |
| `E803` | fix: zero padding in the ID (`0042- X.bes` -> `42- X.bes`); done even when the ID is a duplicate (`E801`), since the ID does not change |
| `E804` | fix: non-ASCII characters in the name, folded to ASCII |
| `E805` | fix: the server path is too long, or the name is over 255 bytes, so the file is renamed `<ID> <Title>.bes` |
| `E806` | a rename was skipped: the new name is taken (ignoring case), the file has unstaged changes pre-commit set aside, the commit uses a temporary index (`git commit -a`, `git commit <paths>`), or the rename failed |
| `E807` | another tracked file's server path is too long, inside the site roots or not (the server clones the whole repo). It is not renamed, since actions may refer to it by name |
| `E808` | a file or folder name over 255 bytes in UTF-8 (Linux `NAME_MAX`) that the rename cannot fix; each folder once |
| `W800` | a `.bes` file outside the `.bes` folder; the server does not gather it |
| `W801` | a `.bes` file directly in the `.bes` folder, or deeper than `<BesFileDir>/<fxf>/<digest>/` (how the server handles either is undocumented) |
| `W802` | a file in the `.bes` folder other than `.bes` or `digest.xml`; an `.xsd` too, since `bes-schema-validate` already has the schemas |
| `W803` | a folder `siteConfig.xml` renames has no files (a default name spelled out, as the template does, is not checked: those folders are optional) |
| `W804` | the site has no content: no `.bes` files and no files in the NonClient or Other folders. A site of server files only passes |
| `W806` | an ID outside 1..2147483647 (the range is undocumented) |
| `W807` | `siteConfig.xml` is not readable XML; the default folders are used (`bes-schema-validate` reports why) |
| `W808` | a folder, `.bes` extension or `digest.xml` that matches the expected name only when case is ignored (`fixlets/` for `Fixlets`, `.BES`); a RHEL server may not find it |

**Path and name limits.** The server clones the whole repo to
`<server-root>\RepositorySiteGather\Sites\<repo>_<branch>_<8 hex>\Source\`,
and each file's path relative to the repo root (not the site root) is added
to that. The result must be at most 259 characters (`MAX_PATH` is 260 with
the terminating NUL); paths over it fail on 11.0.7 even with Windows long
paths enabled. For example, `bigfix-site-reporting-jgstew` on the `main`
branch is cloned to
`C:\Program Files (x86)\BigFix Enterprise\BES Server\RepositorySiteGather\Sites\bigfix-site-reporting-jgstew_main_27eb797e\Source\`,
129 characters, leaving 130 for the path in the repo. `<repo>` is the git
repo's name, not the site's name in BigFix. The length is counted in UTF-16
units, as Windows counts it. Only this Windows layout is confirmed (the
clone path on a RHEL server is not), so it is the path that is measured. On
Linux each file and folder name must also be at most 255 bytes in UTF-8
(`NAME_MAX`); Linux's 4096-byte `PATH_MAX` cannot be reached once the
Windows limit holds. In a repo of several sites, paths are still measured
from the repo root: CommunityContent's `Sites/<name>/Fixlets/...` paths
count in full. The options:

| option | default |
| --- | --- |
| `--server-root` | `C:\Program Files (x86)\BigFix Enterprise\BES Server` |
| `--repo-name` | the last part of the `origin` remote URL without `.git`, or the repo folder's name |
| `--branch` | `main` |
| `--max-path` | `259` |

**Renames.** By default each `.bes` file in the `.bes` folder is renamed at
most once, combining the fixes it needs: zero padding stripped from the ID
(`E803`), non-ASCII folded to ASCII (`E804`: the euro sign becomes `EUR`, a
curly apostrophe `'`, accents are dropped, and `_` stands in when there is no
equivalent), and, if the path or name is still too long, `<ID> <Title>.bes`
cut to fit both limits (`E805`). The title comes from the file's `<Title>`,
or from its current name if the title has no letter or digit; it is made
ASCII and safe on Windows, cut short, and any trailing space, dot or hyphen
is dropped. A name that already fits is left alone, even when it differs
from the title. The ID never changes and no file moves between folders.

Tracked files are renamed with `git mv`, so the renames are staged and the
next commit carries them whole; a plain rename would leave an unstaged
deletion that `git commit -a` could commit without the new file. Nothing is
renamed (`E806`) where the rename would be lost:

- `git commit -a` and `git commit <paths>` run the hook on a temporary index
  that git throws away when the hook fails. `git add` the changes and run a
  plain `git commit` (or `pre-commit run`) to get the renames.
- A file with unstaged changes that pre-commit set aside for the run: it
  could not put them back on a renamed file. The hook finds pre-commit's
  stash file by the pid of its parent, grandparent or great-grandparent (a
  Windows `.exe` launcher sits in between); this is verified on macOS only.
  `pre-commit try-repo` keeps its stash in a temporary cache that the hook
  cannot see, so there such a file is renamed and pre-commit then fails to
  restore the changes (they stay in its patch file).
Any rename makes the hook exit 1, so review the renames and commit again.
`--check` is a dry run that reports what would be renamed.

Files with no ID are reported (`E800`), not given one. An opt-in
`--assign-ids` is deferred: choosing IDs is a policy decision, best backed
by a counter file as CommunityContent does, since taking the highest ID plus
one could reuse a deleted item's ID.

Not checked here: more than one object in a `.bes` file, or Baselines
(repository sites are thought to handle both); schemas, GroupRelevance and
`//` comments (`bes-schema-validate`, `bes-relevance-convert-group`,
`bes-conventions-check`); setting up a blank repo. For names that differ
only by case, and names Windows forbids, add these companions from
[pre-commit-hooks](https://github.com/pre-commit/pre-commit-hooks)
(`>= 5.0.0`):

```yaml
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: check-case-conflict
      - id: check-illegal-windows-names
```

A repo with several sites:

```yaml
      - id: bes-siterepo-validate-layout
        args: [--site-root, "Sites/Site A", --site-root, "Sites/Site B"]
```

## Development

```bash
pip install -e .[test]
python -m pytest
pre-commit run --all-files
```
