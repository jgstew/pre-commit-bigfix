#!/usr/bin/env python3
"""Run every pre-commit-bigfix hook over a folder, without pre-commit.

    uvx pre-commit-bigfix [PATH ...]

This is the `pre-commit-bigfix` command. It finds the files under each PATH
(default: the current folder), gives each hook the ones its `files` pattern in
.pre-commit-hooks.yaml matches, with that hook's default `args`, and prints a
pass/fail line per hook. The exit code is 1 when any hook fails, and 2 for
a PATH that does not exist or a bad option.

It is read-only. Run by pre-commit, several hooks fix files in place by
default; here each one is told not to (--auto-fix=no, or --check for the
hooks that convert or rename), so fixable problems are reported instead.
To apply the fixes, run the hook itself, or use pre-commit.

Hidden folders (a name starting with `.`, or the hidden flag on macOS and
Windows) are not searched unless --include-hidden is given, and __pycache__
and node_modules never are; a PATH that names a folder is searched anyway.
Symlinked files found while searching are skipped, as pre-commit skips them.
A named file that no hook checks is reported on stderr.

bes-siterepo-validate-layout checks a whole repo from `git ls-files`, so it
runs once in each git repo that holds a PATH, and is skipped when none does.

A hook with no matching files is skipped rather than run with no file names:
run that way, most hooks would search the current folder themselves.
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import stat
import subprocess
import sys
import traceback
from typing import NamedTuple

from . import bes_common


class Hook(NamedTuple):
    """One hook from .pre-commit-hooks.yaml, as the runner calls it."""

    id: str
    module: str  # in this package; its main(argv) is the console script
    files: str | None  # the hook's `files` regex; None: it lists its own
    args: tuple[str, ...] = ()  # the hook's default `args`
    read_only: tuple[str, ...] = ()  # what keeps it from writing

    def load(self):
        """Import the hook's module (only when it runs, as some are heavy)."""
        return importlib.import_module(f"{__package__}.{self.module}")


# Same order, ids, `files` and `args` as .pre-commit-hooks.yaml (minus aliases);
# tests/test_run_all.py keeps the two in step.
HOOKS = (
    Hook(
        "bes-schema-validate",
        "bes_schema_validate",
        r"\.(bes|ojo)$|(^|/)(siteConfig|site|digest)\.xml$"
        r"|(^|/)Signatures/[^/]+\.xml$",
    ),
    Hook(
        "bes-conventions-check",
        "bes_conventions_check",
        r"\.bes$",
        read_only=("--auto-fix=no",),
    ),
    Hook(
        "bes-actionscript-lint-schclass",
        "bes_actionscript_lint_schclass",
        r"\.bes$",
        read_only=("--auto-fix=no",),
    ),
    Hook(
        "bes-actionscript-validate-prefetch",
        "bes_actionscript_validate_prefetch",
        r"\.bes$",
        # --auto-fix-network is already off by default; say so anyway
        read_only=("--auto-fix=no", "--auto-fix-network=no"),
    ),
    Hook(
        "bes-actionscript-validate-script",
        "bes_actionscript_validate_script",
        r"\.bes$",
        read_only=("--auto-fix=no",),
    ),
    Hook(
        "bes-relevance-lint",
        "bes_relevance_lint",
        r"\.(bes|bes\.xml|ojo|besrpt|beswrpt|webreport|bsr|rel)$",
        args=("--disable", "W601"),
    ),
    Hook(
        "bes-relevance-convert-group",
        "bes_relevance_convert_group",
        r"\.bes$",
        read_only=("--check",),
    ),
    Hook(
        "bes-siterepo-validate-layout",
        "bes_siterepo_validate_layout",
        None,
        read_only=("--check",),
    ),
)

# any file some hook checks; anything else is not worth listing
ANY_HOOK_RE = re.compile("|".join(f"(?:{h.files})" for h in HOOKS if h.files))


def _is_hidden(path, name):
    """True for a dot folder, or one with the macOS or Windows hidden flag."""
    if name.startswith("."):
        return True
    try:
        st = os.lstat(path)
    except OSError:
        return False
    # st_flags exists on BSD/macOS and st_file_attributes on Windows; each
    # constant is missing (so 0) on the other platforms
    if getattr(st, "st_flags", 0) & getattr(stat, "UF_HIDDEN", 0):
        return True
    return bool(
        getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0)
    )


def _match_path(path):
    """The string a hook's `files` regex is searched in.

    pre-commit searches the repo-relative path, so `(^|/)Signatures/x.xml`
    sees the folder. The path as given may not hold it (`x.xml`, run from
    inside Signatures/), so the absolute path is used instead.
    """
    return os.path.abspath(path).replace(os.sep, "/")


def discover(paths, include_hidden=False):
    """Return the files under `paths` that some hook checks, sorted, each once.

    A file named in `paths` is kept even if no hook checks it. Folders are
    walked, skipping symlinked files (pre-commit does not pass them to these
    hooks), bes_common.DISCOVERY_SKIP_DIRS and, unless `include_hidden`, hidden
    folders; a folder named in `paths` is walked even if it is hidden.
    """
    found = set()
    for top in paths:
        if not os.path.isdir(top):
            found.add(os.path.normpath(top))
            continue
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in bes_common.DISCOVERY_SKIP_DIRS
                and (include_hidden or not _is_hidden(os.path.join(dirpath, d), d))
            ]
            for name in filenames:
                path = os.path.normpath(os.path.join(dirpath, name))
                if not os.path.islink(path) and ANY_HOOK_RE.search(_match_path(path)):
                    found.add(path)
    return sorted(found)


def repo_roots(paths):
    """Return the top folders of the git repos holding `paths`, each once."""
    roots = []
    for path in paths:
        folder = path if os.path.isdir(path) else os.path.dirname(path) or "."
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=folder,
                capture_output=True,
                check=False,
            )
        except OSError:  # git not installed
            return []
        root = os.fsdecode(result.stdout).strip()
        if result.returncode == 0 and root and root not in roots:
            roots.append(root)
    return roots


def _call(hook, argv):
    """Run `hook`'s main(argv); return its exit code, a crash counting as 1."""
    try:
        code = hook.load().main(argv)
    except SystemExit as exc:  # argparse errors, or a hook that exits
        code = exc.code
    except Exception:  # noqa: BLE001 - one broken hook must not hide the rest
        traceback.print_exc()
        print(f"{hook.id}: crashed")
        return 1
    if code is None:
        return 0
    return code if isinstance(code, int) else 1


def _run_in_repos(hook, roots):
    """Run a whole-repo hook once in each of `roots`; return its worst exit code."""
    worst = 0
    here = os.getcwd()
    for root in roots:
        print(f"=== {hook.id} ({root})", flush=True)
        # the hook finds its repo from the current folder
        os.chdir(root)
        try:
            worst = max(worst, _call(hook, [*hook.args, *hook.read_only]))
        finally:
            os.chdir(here)
    return worst


def run_hook(hook, files, roots):
    """Run one hook read-only; return (status, code).

    A file hook gets the `files` its pattern matches; a whole-repo hook runs in
    each of the git repos `roots`. status is "passed", "failed" or
    "skipped: <why>".
    """
    if hook.files is None:
        if not roots:
            return "skipped: not a git repo", 0
        code = _run_in_repos(hook, roots)
    else:
        pattern = re.compile(hook.files)
        matched = [path for path in files if pattern.search(_match_path(path))]
        if not matched:
            return "skipped: no files", 0
        print(f"=== {hook.id}", flush=True)
        # `--` so a file named like an option (-h.bes) is still a file name
        code = _call(hook, [*hook.args, *hook.read_only, "--", *matched])
    sys.stdout.flush()
    return ("failed" if code else "passed"), code


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pre-commit-bigfix",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        metavar="PATH",
        help="files or folders to check (default: the current folder)",
    )
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        choices=[hook.id for hook in HOOKS],
        metavar="HOOK",
        help="a hook id not to run; repeatable",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="also search hidden folders (see above)",
    )
    return parser


def main(argv=None):
    """Execution starts here; returns 1 if any hook failed, 2 for a bad PATH."""
    args = build_parser().parse_args(argv)

    missing = [path for path in args.paths if not os.path.exists(path)]
    if missing:
        for path in missing:
            print(f"pre-commit-bigfix: no such file or folder: {path}", file=sys.stderr)
        return 2

    files = discover(args.paths, include_hidden=args.include_hidden)
    for path in args.paths:
        if os.path.isfile(path) and not ANY_HOOK_RE.search(_match_path(path)):
            print(f"{path}: not checked by any hook", file=sys.stderr)
    roots = repo_roots(args.paths)

    results = []
    for hook in HOOKS:
        if hook.id in args.skip:
            results.append((hook.id, "skipped: --skip", 0))
            continue
        status, code = run_hook(hook, files, roots)
        results.append((hook.id, status, code))

    width = max(len(hook.id) for hook in HOOKS) + 3
    print()
    for hook_id, status, _code in results:
        print(f"{hook_id} {'.' * (width - len(hook_id))} {status}")
    return 1 if any(code for _id, _status, code in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
