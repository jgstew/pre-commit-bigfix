# Release Notes

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
