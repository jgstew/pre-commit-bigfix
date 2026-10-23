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
It is also skipped in a repo that shows no sign of being a site: git tracks
no site.xml or siteConfig.xml file and no Fixlets, NonClientFiles or
OtherFiles folder at its top (names compared ignoring case).

A hook that reports more than 20 results (`path:line: message` or
`path: message` lines) has them summarized, counted by code and by file,
instead of listed. --log-file writes the full output of every hook to FILE
(default pre-commit-bigfix-results.log), replacing it if it exists; that is
the only file this command writes. It will not replace a PATH or a file some
hook checks. Give PATHs before --log-file, or use --log-file=FILE, so a PATH
is not taken as FILE.

A hook with no matching files is skipped rather than run with no file names:
run that way, most hooks would search the current folder themselves.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import os
import re
import stat
import subprocess
import sys
import traceback
from collections import Counter
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

# a hook with more results than this has them summarized, not listed
SUMMARY_OVER = 20
# files and folders listed in the summary, most results first
SUMMARY_TOP_FILES = 5
DEFAULT_LOG_FILE = "pre-commit-bigfix-results.log"

# one result line: `path:line: message`, maybe `[CODE] ` first; a Windows
# drive letter (C:\...) does not end the path, as `:\d+: ` must follow it
RESULT_RE = re.compile(r"^(?P<path>.+?):\d+: (?:\[(?P<code>[A-Z]+\d+)\] )?")

# a site repo's top folder holds one of these, compared lowercase. The folder
# names are bes_siterepo_validate_layout.DEFAULT_DIRS, copied so the layout
# module is only imported when it runs.
SITE_FILES = frozenset({"site.xml", "siteconfig.xml"})
SITE_DIRS = frozenset({"fixlets", "nonclientfiles", "otherfiles"})


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


def looks_like_site(root):
    """True if git repo `root` tracks a site file or site folder at its top.

    See SITE_FILES and SITE_DIRS. Only tracked files count, as the layout hook
    sees only what `git ls-files` lists.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=False
        )
    except OSError:  # git not installed
        return False
    if result.returncode:
        return False
    for path in os.fsdecode(result.stdout).split("\0"):
        top, slash, _rest = path.partition("/")
        if top.lower() in (SITE_DIRS if slash else SITE_FILES):
            return True
    return False


def _path_prefix(line, paths):
    """The one of `paths` that `line` starts with, followed by `: `; or None."""
    end = line.find(": ")
    while end != -1:  # a path may hold ": " itself
        if line[:end] in paths:
            return line[:end]
        end = line.find(": ", end + 1)
    return None


def split_output(text, paths=()):
    """Split a hook's output into its results and its other lines.

    Returns ([(path, code or None), ...], [other line, ...]). A result is a
    `path:line: message` line, or `path: message` for one of the files the
    hook was given (`paths`), as bes-schema-validate prints when it has no
    line. The indented lines after a result (a suggested fix) belong to it;
    any other line (a count such as `7 warning(s).`, a crash) is kept as is.
    """
    results, other = [], []
    in_result = False
    paths = frozenset(paths)
    for line in text.splitlines():
        match = RESULT_RE.match(line)
        path = None if match else _path_prefix(line, paths)
        if match or path:
            results.append((match["path"], match["code"]) if match else (path, None))
            in_result = True
        elif in_result and line[:1].isspace():
            continue
        else:
            other.append(line)
            in_result = False
    return results, other


def summarize(results, other, log_path):
    """The text printed in place of a hook's output when it has many results."""
    files = Counter(path for path, _code in results)
    lines = [
        (
            f"{len(results)} results in {len(files)} file(s), more than"
            f" {SUMMARY_OVER}, so they are summarized. By code:"
        )
    ]
    codes = Counter(code or "(no code)" for _path, code in results)
    width = max(len(code) for code in codes)
    lines += [f"  {code:<{width}}  {n}" for code, n in codes.most_common()]
    lines.append("Most results:")
    lines += [f"  {n:>5}  {path}" for path, n in files.most_common(SUMMARY_TOP_FILES)]
    lines += other
    if log_path:
        lines.append(f"All of them are in {log_path}.")
    else:
        lines.append(
            "Run again with --log-file to write all of them to"
            f" {DEFAULT_LOG_FILE} (or --log-file=FILE)."
        )
    return "\n".join(lines) + "\n"


class _Tee:
    """A text stream that writes to each of `streams`.

    Not an io.TextIOBase: its __del__ would flush the streams, by then
    perhaps closed (the log).
    """

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


class Report:
    """Where the output goes: stdout, and the --log-file if one is given.

    The log gets every hook's full output; stdout gets it too, unless the
    hook has more than SUMMARY_OVER results, when it gets summarize() instead.
    """

    def __init__(self, log=None, log_path=None):
        self.log = log
        self.log_path = log_path

    def show(self, text):
        """Write `text` to stdout only."""
        sys.stdout.write(text)
        sys.stdout.flush()

    def write(self, text):
        """Write `text` to stdout and the log."""
        self.show(text)
        if self.log:
            self.log.write(text)

    def _capture(self, hook, argv, folder):
        """Run `hook` in `folder` (None: here) with stdout caught; return (code,
        text).
        """
        caught = io.StringIO()
        # stderr (warnings, a crash's traceback) is not summarized: it is
        # shown as it comes, and copied to the log
        err = (
            contextlib.redirect_stderr(_Tee(sys.stderr, self.log))
            if self.log
            else contextlib.nullcontext()
        )
        here = os.getcwd()
        try:
            with contextlib.redirect_stdout(caught), err:
                if folder:  # a whole-repo hook finds its repo from the current folder
                    os.chdir(folder)
                try:
                    code = _call(hook, argv)
                finally:
                    os.chdir(here)
        except BaseException:  # Ctrl-C: _call already catches the rest
            self.write(caught.getvalue())  # what the hook printed before it
            raise
        return code, caught.getvalue()

    def run(self, hook, argv, folders=(None,), paths=()):
        """Run `hook` once in each of `folders`; return (worst code, result count).

        `paths` are the files the hook is given, for split_output(). Each run
        goes to the log as it ends. Stdout gets each run under its own
        `=== hook (folder)` line, or, when all of them together have more than
        SUMMARY_OVER results, one summary of them.
        """
        headers = [
            f"=== {hook.id}" + (f" ({folder})" if folder else "") + "\n"
            for folder in folders
        ]
        if len(folders) == 1:
            self.show(headers[0])  # before it runs, to show which hook is busy
        worst, results, other, texts = 0, [], [], []
        for header, folder in zip(headers, folders):
            if self.log:
                self.log.write(header)
            code, text = self._capture(hook, argv, folder)
            if self.log:
                self.log.write(text)
            worst = max(worst, code)
            found, rest = split_output(text, paths)
            results += found
            other += rest
            texts.append(text)
        if len(results) > SUMMARY_OVER:
            if len(folders) > 1:
                self.show(f"=== {hook.id} ({', '.join(folders)})\n")
            self.show(summarize(results, other, self.log_path))
        else:
            for header, text in zip(headers, texts):
                self.show(text if len(folders) == 1 else header + text)
        return worst, len(results)


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


def run_hook(hook, files, roots, report=None):
    """Run one hook read-only; return (status, code, result count).

    A file hook gets the `files` its pattern matches; a whole-repo hook runs in
    each of the git repos `roots` that looks_like_site(). status is "passed",
    "failed" or "skipped: <why>".
    """
    report = report or Report()
    if hook.files is None:
        if not roots:
            return "skipped: not a git repo", 0, 0
        sites = [root for root in roots if looks_like_site(root)]
        if not sites:
            return "skipped: not a site repo", 0, 0
        code, count = report.run(hook, [*hook.args, *hook.read_only], sites)
    else:
        pattern = re.compile(hook.files)
        matched = [path for path in files if pattern.search(_match_path(path))]
        if not matched:
            return "skipped: no files", 0, 0
        # `--` so a file named like an option (-h.bes) is still a file name
        argv = [*hook.args, *hook.read_only, "--", *matched]
        code, count = report.run(hook, argv, paths=matched)
    return ("failed" if code else "passed"), code, count


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
    parser.add_argument(
        "--log-file",
        nargs="?",
        const=DEFAULT_LOG_FILE,
        metavar="FILE",
        help="write every hook's full output to FILE, replacing it"
        f" (default FILE: {DEFAULT_LOG_FILE})",
    )
    return parser


def main(argv=None):
    """Execution starts here; returns 1 if any hook failed, 2 for a bad PATH."""
    args = build_parser().parse_args(argv)
    # a file name the console cannot show (an ASCII or cp1252 console, or not
    # UTF-8) is escaped rather than crash the run; the layout hook does this
    # itself, but its stdout is a StringIO here
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")

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

    if not args.log_file:
        return _run_all(args, files, roots, Report())
    if _would_replace_input(args.log_file, args.paths):
        print(
            f"pre-commit-bigfix: --log-file {args.log_file} is a file to check,"
            " not a log; give PATHs before --log-file, or --log-file=FILE",
            file=sys.stderr,
        )
        return 2
    try:
        # "w": a log from an earlier run is replaced, not added to. Not a
        # `with` here, so that only open()'s own error is caught
        log = open(  # noqa: SIM115 - closed by the `with log:` below
            args.log_file, "w", encoding="utf-8", errors="backslashreplace"
        )
    except OSError as exc:
        print(
            f"pre-commit-bigfix: cannot write {args.log_file}: {exc}",
            file=sys.stderr,
        )
        return 2
    with log:
        code = _run_all(args, files, roots, Report(log, args.log_file))
    print(f"Full results written to {args.log_file}")
    return code


def _would_replace_input(log_file, paths):
    """True if `log_file` is a file some hook checks, or one of `paths`.

    --log-file FILE takes the next argument when FILE is left out, so
    `--log-file x.bes` would otherwise empty x.bes before it is checked.
    """
    if ANY_HOOK_RE.search(_match_path(log_file)):
        return True
    if not os.path.exists(log_file):
        return False
    for path in paths:
        try:
            if os.path.samefile(path, log_file):
                return True
        except OSError:
            continue
    return False


def _run_all(args, files, roots, report):
    """Run every hook not skipped, then write the summary table; return the exit
    code.
    """
    results = []
    for hook in HOOKS:
        if hook.id in args.skip:
            results.append((hook.id, "skipped: --skip", 0, 0))
            continue
        results.append((hook.id, *run_hook(hook, files, roots, report)))

    width = max(len(hook.id) for hook in HOOKS) + 3
    report.write("\n")
    for hook_id, status, _code, count in results:
        found = f" ({count} result{'' if count == 1 else 's'})" if count else ""
        report.write(f"{hook_id} {'.' * (width - len(hook_id))} {status}{found}\n")
    return 1 if any(code for _id, _status, code, _count in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
