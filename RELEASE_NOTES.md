# Release Notes

## v0.8.0

Adds eight semantic checks to `bes-actionscript-validate-script`: prefetch
placement, download-name consistency, if-condition shape, unreachable code,
and `action parameter query` placement.

### Added

- **`E510` / `E511`**: an `add prefetch item` / `add nohash prefetch item`
  (`E510`) or `collect prefetch items` (`E511`) outside an open
  `begin prefetch block` - the agent rejects these outside a block.
- **`E512`**: two prefetch/download producers (statement `prefetch <name>`,
  block `add prefetch item name=<name>`, or `download [now] as <name>`, plus
  a literal `download <url>` basename) declare the same download name,
  compared case-insensitively - the second silently overwrites the first.
- **`E513`**: a command references `__Download\<name>` but nothing prefetches
  or downloads a file of that name - a typo catcher. Conservatively gated:
  skipped for the whole body whenever any producer's names are unknowable
  (an `extract`/`unarchive`/`archive now`/`utility` command, a `download`
  with no `as <name>` and no literal URL basename, or a `{...}` substitution
  in a name or URL), and a substituted consumer name is never judged.
- **`E514`**: an `if` or `elseif` whose condition is not a `{...}` relevance
  substitution (`if true`, bare `if`) - the agent requires one. Joins the
  `actionscript-if-ok` opt-out family.
- **`E515`**: a `begin prefetch block` that is not at the top of the script -
  only blank lines, `//` comments, `action parameter query` lines, and
  `parameter` assignments may precede it. Plain `prefetch` statements are
  legal anywhere in a script and are deliberately not placement-checked.
- **`W501`**: unreachable command - a line after an unconditional `exit`,
  `restart`, or `shutdown` (one outside any `if`) can never run; only the
  first unreachable line is reported.
- **`W502`**: an `action parameter query` after the first execution command -
  these are console-time prompts and belong at the top.
- New opt-out markers, following the per-family pattern:
  `actionscript-prefetch-placement-ok` (`E510`, `E511`, `E515`),
  `actionscript-download-ok` (`E512`, `E513`), `actionscript-unreachable-ok`
  (`W501`), and `actionscript-parameter-query-ok` (`W502`).

No auto-fixes, same rationale as `E500`-`E509`: the hook cannot know intent.

## v0.7.1

Adds per-line `{...}` relevance-substitution brace balance to
`bes-actionscript-validate-script`.

### Added

- **`E508` in `bes-actionscript-validate-script`**: a `{` relevance
  substitution that is never closed by a `}` before the end of its line. A
  substitution is evaluated per line and cannot span lines, so a `{` left open
  at end of line is a broken substitution, not a continued one.
- **`E509` in `bes-actionscript-validate-script`**: a `}` reached with no `{`
  substitution open on that line.
- `{{` (and `}}`) is treated as an escape that passes a literal brace through
  to the command rather than opening or closing a substitution, and a later
  lone `}` pairs with that escape instead of being reported as stray - so
  escaped braces stay quiet.
- Both codes opt out with `actionscript-substitution-ok`, the same marker
  `bes-actionscript-lint-schclass` uses for its `E301`, so one marker covers
  both hooks.

## v0.7.0

Adds a new hook, `bes-actionscript-validate-script`: checks `if`/`endif` and
`begin prefetch block`/`end prefetch block` pairing in every `<ActionScript>`
body of a BES file - the sibling hook `bes-actionscript-lint-schclass`'s SCOPE
note already named for checks that need pairing, ordering, and
block-interleaving knowledge the lexical grammar does not carry.

### Added

- **`bes-actionscript-validate-script`**, a new hook. Only
  `application/x-Fixlet-Windows-Shell` (matched case-insensitively) or
  missing-MIMEType bodies are checked; bodies are extracted with lxml, so
  entities are decoded, CDATA sections merged, and line numbers map back to
  the file. This hook has no auto-fixes: a hook has no way to know where a
  missing `endif` or `end prefetch block` was meant to go, and guessing could
  silently change what the action does.
  - **`E500`**: an `if` is never closed by a matching `endif`.
  - **`E501`**: an `endif` with no open `if`.
  - **`E502`**: a `begin prefetch block` is never closed by `end prefetch block`.
  - **`E503`**: an `end prefetch block` with no open `begin prefetch block`.
  - **`E504`**: a `begin prefetch block` nested inside another one - prefetch blocks do not nest.
  - **`E505`**: an `else` or `elseif` outside any open `if`.
  - **`E506`**: an `elseif` after `else`, or a second `else` for the same `if`.
  - **`E507`**: an `if` opened inside a prefetch block is still open at that block's `end prefetch block` - blocks interleave rather than nest.
  - **`W500`**: the file is not parseable BES XML; skipped (`bes-schema-validate` owns validity).
  - Lines inside a `createfile until` block are file content, not
    ActionScript, and are not scanned - that block's own well-formedness is
    `bes-actionscript-lint-schclass`'s `E302`, not reported here.
  - Opt-outs: `<!-- pre-commit-skip: bes-actionscript-validate-script -->` for
    the whole file, or `actionscript-if-ok` (`E500`, `E501`, `E505`, `E506`),
    `actionscript-prefetch-block-ok` (`E502`, `E503`, `E504`), and
    `actionscript-block-nesting-ok` (`E507`) per check family.

## v0.6.2

Adds `x-fixlet-first-propagation` to the timestamp fields `bes-conventions-check` validates, and tightens the existing `x-fixlet-modification-time` check to actually verify a supplied day-of-week against the date.

### Added

- **`E216` in `bes-conventions-check`**: every `x-fixlet-first-propagation` MIMEField value must be a valid RFC 5322 date-time (e.g. `Tue, 14 Jul 2026 18:32:35 +0000`) - the same rule `E202` already applied to `x-fixlet-modification-time`, now applied to this separate field. A file that knowingly carries a nonconforming value opts out with the `first-propagation-ok` marker, the same pattern as every other value check in the hook.

### Changed

- **`E202` in `bes-conventions-check`**: the leading day-of-week is now optional, matching RFC 5322 itself (`14 Jul 2026 18:32:35 +0000` is accepted, with no day-of-week at all) - but when one is supplied, it must be the *actual* day of week for the date given. `Fri, 06 Aug 2026 12:43:34 +0000` is now rejected, because 6 Aug 2026 is a Thursday, not a Friday; previously the day-of-week was mandatory and only checked for being spelled like a real weekday, not for matching the date. The weekday cross-check is timezone-naive relative to the value's own offset (it compares against the date as written, not a UTC-converted one) and does not depend on the host's locale.
- `SourceReleaseDate` (`E201`) is unaffected by either change above; it remains a plain `YYYY-MM-DD` date with no time or timezone component.

## v0.6.1

Teaches `bes-actionscript-validate-prefetch` to fix prefetches, not just report them: the retired `unzip-5.52.exe` download is replaced offline, and `--auto-fix-network` fills in a missing sha256 by downloading the file.

### Added

- **`E402` in `bes-actionscript-validate-prefetch`**: the prefetch downloads the retired `unzip-5.52.exe` from the BigFix redist folder (matched on either scheme); `http://software.bigfix.com/download/redist/unzip-6.0.exe` is the current one.
  - This is the hook's offline auto-fix, and it is **on by default** (`args: ["--auto-fix", "no"]` turns it off): the line is rewritten in place to the current unzip prefetch, built by `prefetch_from_dictionary()` from `bigfix_prefetch` in whichever spelling the line already used, so a `prefetch ... sha1:...` statement stays a statement and an `add prefetch item ...` stays a block item.
  - The original download's **name** is kept and only the url, size, sha1, and sha256 are replaced: the rest of the ActionScript refers to the downloaded file by name, so renaming it would break the script.
  - An `add nohash prefetch item` on the old URL is reported but not rewritten - giving it hashes would change what the line does, not just which file it fetches.
- **`--auto-fix-network`, off by default**: adds the missing sha256 of an `E401`, which means downloading the file to hash it - there is no other way to learn a sha256. The download is handed to `add_sha256_prefetch()` from `bigfix_prefetch`, which streams the file, checks it against the size and sha1 already on the line, and re-emits the prefetch with sha256 added - in the same spelling, and again keeping the line's own download name (upstream would rename it after the URL's basename).
  - It is a flag of its own rather than part of `--auto-fix`, and never on by default, because it reaches out to whatever URLs the content names.
  - Each URL is fetched at most once per run, and each download gives up after 60 seconds (upstream sets no timeout, and a hanging URL should not hang a commit).
- **`W404`**: `--auto-fix-network` was asked to add a sha256 and could not - the URL would not download, or what came back did not match the size and sha1 already on the line. The line is left exactly as it was and its `E401` stands, so an upstream file that has changed is never quietly re-hashed into looking valid.

### Changed

- An auto-fixed file fails the hook, so the rewrite is reviewed and re-staged - the same behavior as `bes-conventions-check`. Both fixes honor `--disable` and the `prefetch-ok` / `pre-commit-skip` opt-out markers, and preserve the file's CRLF line endings.
- The `bigfix_prefetch` dependency now has a `>= 1.1.5` floor: that is where `prefetch.add_sha256_prefetch()` arrived.
- The hook is no longer offline in every mode. Its **checks** still are - none of them downloads a URL or verifies hashes against the real file - but `--auto-fix-network` does, when asked for.

## v0.6.0

Adds a new hook, `bes-actionscript-validate-prefetch`.

### Added

- **`bes-actionscript-validate-prefetch`**: validates every prefetch line in every `<ActionScript>` body with `validate_prefetch()` from the [bigfix_prefetch](https://pypi.org/project/bigfix-prefetch/) package, which is now an install dependency. Both the `prefetch <name> sha1:<40> size:<n> <url> sha256:<64>` statement and the `add prefetch item name=... sha1=... size=... url=...` block item are covered.
  - `E400`: the line failed validation, with the reason `bigfix_prefetch` reported - a missing size or a size that is not > 0, a hash of the wrong length, a sha1 missing from a prefetch statement, or an unparsable line.
  - `E401`: the line has no sha256. `bigfix_prefetch` treats sha256 as optional unless asked; this hook treats it as mandatory, which is the 2026 expectation. It is a code of its own rather than part of `E400` so a repo that still wants sha256 optional can pass `args: ["--disable", "E401"]`.
  - `W402`: a prefetch block item has no sha1 - technically valid, but unusual.
  - `W403`: an `add nohash prefetch item` line, which is hashless by definition, so it is reported rather than validated.
  - `W400`: the file is not parseable BES XML and was skipped (`bes-schema-validate` owns validity).
  - A file whose prefetches knowingly do not meet these rules opts out of every check in the hook with `prefetch-ok` anywhere in it - the same marker that opts out of `W206` in `bes-conventions-check`, since it is the same judgement. `<!-- pre-commit-skip: bes-actionscript-validate-prefetch -->` also skips the file.
  - Scope is internal validity only: the hook is offline and never downloads a URL or verifies the hashes against the real file. Dynamic prefetches (a line holding a `{...}` substitution), `//` comments, and the raw content of a `createfile until` block are skipped. There are no auto-fixes.
  - This is a third altitude on the same lines, alongside the existing shape/scheme warnings (`W206`/`W207` in `bes-conventions-check`) and the lexical check (`E300` in `bes-actionscript-lint-schclass`).

## v0.5.1

Broadens the `E204` description-placeholder check in `bes-conventions-check` to every content object.

There is no v0.5.0 release; the version went from v0.4.2 straight to v0.5.1.

### Changed

- `E204` in **`bes-conventions-check`** now applies to every content object, not just `Task`/`Fixlet`. `Analysis`, `ComputerGroup`, `Baseline`, and `SingleAction` carry the same boilerplate placeholder, so `Enter a description of the Analysis here.` is now flagged. The match is on the substring `enter a description of the` and remains case-insensitive; `description-ok` still opts out.

## v0.4.2

Adds `E215` to `bes-conventions-check`: whitespace around an `<ActionScript>` CDATA terminator.

### Added

- `E215` in **`bes-conventions-check`** (fixable): an `<ActionScript>` whose CDATA terminator has whitespace around it, e.g. an indented `\t\t\t]]></ActionScript>`. Whitespace before `]]>` sits *inside* the CDATA and whitespace after it is element text appended to the same body, so either way the action gains a spurious whitespace-only last line. The fix strips it to a flush `]]></ActionScript>`. Opt out with `cdata-close-ok`.
  - Previously nothing covered this: `W210` only strips whitespace at end-of-line (here the tabs are followed by `]]></ActionScript>`), `W205` only fires on 2+ blank lines before the close tag, and `W204`/`E207` still see a correctly CDATA-wrapped body.
  - The fixer runs after the `W205` blank-line collapse, which preserves the terminator's indentation, so a block with both issues is fully fixed in one pass.

## v0.4.1

Fixes false `E206` errors on well-formed `action-ui-metadata` values in `bes-conventions-check`, and adds `--errors-only` for a warnings-free report that still runs every fixer.

There is no v0.4.0 release; the version went from v0.3.3 straight to v0.4.1.

### Fixed

- **`bes-conventions-check`** no longer reports false `E206` errors on well-formed `action-ui-metadata` values. The value is now parsed as JSON instead of matched against two fixed patterns, so whitespace (`{"version": "1.0", "size": 10}`) and key order no longer matter, a quoted `size` (`"size": "104632873"`) is accepted alongside a bare one, and an `icon` data URI is accepted in any of those spellings. It must still be a JSON object with a dotted-numeric `version` string, a non-negative integer `size`, and at most an optional `icon` data URI.
- The `E206` message now truncates the offending value at 120 characters, so a base64 `icon` blob no longer buries the rest of the report.

### Added

- `--errors-only` in **`bes-conventions-check`**: warnings are left out of the report and cannot fail the run (even with `--strict`), while every check and every W-code auto-fix still runs. Use this instead of `--disable W2xx,...` when you want a quiet, errors-only report but still want the fixers (`W201`, `W202`, `W205`, `W209`, `W210`) to keep working - `--disable` skips a check *and* its fixer.

## v0.3.3

Fixes false `E300` errors on `override` blocks in `bes-actionscript-lint-schclass`, and validates override options against the documented keywords and values.

There is no v0.3.2 release; the version went from v0.3.1 straight to v0.3.3.

### Fixed

- **`bes-actionscript-lint-schclass`** no longer reports `E300` for the `keyword=value` option lines of an `override run` / `override wait` block. Those lines are options, not commands, and were being judged as unknown command verbs, so any content using `override` failed the hook. This is the main reason to upgrade from v0.3.1.

### Added

- `E303` / `W303` in **`bes-actionscript-lint-schclass`**: an `override run` / `override wait` line now opens a block whose following `keyword=value` lines are validated against the [documented keywords and values](https://developer.bigfix.com/action-script/reference/execution/override.html) - `completion`, `priority`, `hidden`, `detached`, `runas`, `user`, `password`, `asadmin`, `targetuser`, `timeout_seconds`, `disposition`.
  - `E303` - an unknown keyword, a missing value, a value outside the documented set for that keyword, a non-integer `timeout_seconds`, or a `keyword=value` option line outside any override block
  - `W303` - the keyword or value matched case-insensitively but is not lowercase (e.g. `RunAs=`), mirroring `W302` for command verbs
  - A value holding `{...}` is a relevance substitution and is accepted unchecked, since its real value is not known until the agent runs
  - Opt out per check with `actionscript-override-ok` / `actionscript-override-case-ok`
- More `E201` test coverage in `bes-conventions-check`: dates with the right shape but an impossible day (`2026-02-30`, `2023-02-29`, `2026-04-31`), which only the date parse can reject, plus real dates including a leap day.

### Changed

- `<SourceReleaseDate>` validation (`E201`) parses with `date.fromisoformat` instead of `datetime.strptime`, because a calendar date has no timezone to be naive about. No behavior change: for every string the `YYYY-MM-DD` format check admits, both accept and reject exactly the same values.
- Both `check_file` readers use a context manager rather than a bare `open(...).read()`, so the file handle is closed deterministically.
- `bes-schema-validate` calls `sys.exit()` instead of the `exit()` builtin, which is only installed by `site` and can be missing under `python -S`.
- Ruff bumped v0.15.21 -> v0.16.1. Its expanded default rule set surfaced the three items above, plus internal cleanups with no behavior change (a collapsed nested conditional in the tokenizer's `match_literal`, an unused unpacked variable, and a local renamed so it no longer shadows an import). `EXE001` (shebang present but file not executable) is ignored on purpose in `pyproject.toml`, since the hook modules and tests carry `#!/usr/bin/env python3` to stay directly runnable but are imported modules / console-script entry points, not executables.
- Added the `typos` pre-commit hook. Bumped `pre-commit-jgstew` v2.1.1 -> v2.3.0, `codespell` v2.4.2 -> v2.4.3, `zizmor` v1.27.0 -> v1.28.0.

### Removed

- The `misspell` GitHub Actions workflow, superseded by the `typos` pre-commit hook.

**Full Changelog**: https://github.com/jgstew/pre-commit-bigfix/compare/v0.3.1...v0.3.3

---

## v0.3.1

Hook ids renamed to the `<type>-<subtype>-<action>-<mechanism>` convention, plus a new ActionScript linter.

### Added

- **`bes-actionscript-lint-schclass`** - lints every `<ActionScript>` body against the BigFix console's own lexical grammar (vendored `ExpandedActionScript.schclass` plus a small validation override):
  - `E300` - the first token of a line must be a known command verb, a `//` comment, a `{...}` substitution, a continuation, or the line must be blank
  - `E301` - a `{...}` substitution must close before end of line
  - `E302` - a `createfile until <MARKER>` block must reach its marker line (the block's raw content is excluded from linting)
  - `W301` - unbalanced `"`; `W302` - verb matched case-insensitively but is not lowercase

  Only `application/x-Fixlet-Windows-Shell` (or missing `MIMEType`) bodies are treated as ActionScript. Bodies are extracted with lxml, so entities are decoded, CDATA sections merged, and line numbers map back to the source file. Unparsable files are skipped - `bes-schema-validate` owns validity. Pass `--strict` to fail on warnings too.
- Tests asserting that each renamed hook and its deprecated alias stay in lockstep.

### Changed

- `validate-bes` -> **`bes-schema-validate`**, and it now validates against the `BES.xsd` schema explicitly.
- `check-bes-conventions` -> **`bes-conventions-check`**.
- Dependabot bumps: `actions/setup-python` 6.3.0 -> 7.0.0, `lewagon/wait-on-check-action` 0.2 -> 1.8.1.

### Deprecated

- The old ids `validate-bes` and `check-bes-conventions` are kept as aliases pointing at the same entry points, so existing `.pre-commit-config.yaml` files keep working with no behavior change. Prefer the new ids in new configs.

**Full Changelog**: https://github.com/jgstew/pre-commit-bigfix/compare/v0.2.0...v0.3.1

---

## v0.2.0

### Added

- **`validate-bes`** hook - validates BigFix `.bes` / `.ojo` XML files, with README documentation.

**Full Changelog**: https://github.com/jgstew/pre-commit-bigfix/compare/v0.1.1...v0.2.0

---

## v0.1.1

First published release: the repo set up as an installable pre-commit hook package.

### Added

- `pre_commit_bigfix` package with the **`check-bes-conventions`** hook (moved over from `pre-commit-jgstew`) - opinionated content checks and in-place auto-fixes for BES files that the `BES.xsd` schema cannot express: ActionScript `MIMEType`, date/size/metadata value formats, prefetch-line shape and https URLs, CDATA usage, spacing, dynamic downloads, the XML declaration, Title and Relevance content, unique `MIMEField` names, and Task/Fixlet date and download-action presence.
- Full test suite plus an example BES fixture.
- Packaging: `setup.cfg` entry point, `pyproject.toml`, `setup.py` stub.
- GitHub Actions: pre-commit, test_build, tag_and_release, misspell, yamllint; plus dependabot and zizmor config.
- Lint configs and `.pre-commit-config.yaml`.

### Fixed

- `.gitattributes` excludes `.bes` files from text processing; ActionScript content in `example-test.bes` wrapped in CDATA.
- Version bumped to 0.1.1 for module compatibility.

**Full Changelog**: https://github.com/jgstew/pre-commit-bigfix/commits/v0.1.1
