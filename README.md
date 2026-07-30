# pre-commit-bigfix

pre commit hooks for BigFix content

Moved from [pre-commit-jgstew](https://github.com/jgstew/pre-commit-jgstew).

## Usage

Add this to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/jgstew/pre-commit-bigfix
    rev: v0.1.0
    hooks:
      - id: check-bes-conventions
```

## Hooks

### check-bes-conventions

Picky, opinionated content checks + auto-fixes for BigFix BES files that the
BES.xsd schema (`validate-bes`) cannot express: ActionScript MIMEType, value
formats for SourceReleaseDate / x-fixlet-modification-time / DownloadSize /
action-ui-metadata / CPE-2.3 / CVENames, prefetch-line shape and https URLs,
CDATA usage, blank-line and trailing-whitespace spacing, empty ActionScript,
dynamic download statements, a UTF-8 XML declaration, Title placeholders and
whitespace, non-trivial non-empty Relevance, unique MIMEField names,
description placeholders, and Task/Fixlet release-date / modification-time
presence.

Auto-fixes the fixable ones in place and exits 1 when anything was fixed so
the change is reviewed and re-staged. E-codes fail the hook; pass `--strict`
to also fail on warnings. Unparsable files are skipped (`validate-bes` owns
validity).

See the docstring in
[bigfix_bes_check_conventions.py](pre_commit_bigfix/bigfix_bes_check_conventions.py)
for the full list of check codes, opt-out markers, and options.

## Development

```bash
pip install -e .[test]
python -m pytest
pre-commit run --all-files
```
