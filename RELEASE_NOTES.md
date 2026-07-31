# Release Notes

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
