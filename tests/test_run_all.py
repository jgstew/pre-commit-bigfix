#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/run_all.py, the `pre-commit-bigfix` command.

The runner runs every hook in .pre-commit-hooks.yaml over a folder, so that
`uvx pre-commit-bigfix` checks content without pre-commit. These tests tie its
hook table to .pre-commit-hooks.yaml, check how it finds files (hidden folders
skipped unless --include-hidden), and, above all, that it is read-only: a file
every auto-fixing hook would rewrite, and a .bes name the layout hook would
rename, come through a run unchanged.
"""

import configparser
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from pre_commit_bigfix import run_all

yaml = pytest.importorskip("yaml")  # ships with pre-commit; skip if absent

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = Path(__file__).parent / "examples"
GOOD = EXAMPLES / "example-test.bes"
GROUP = EXAMPLES / "Example-Group-Relevance-Fixlet.bes"

SHA1 = "e1652b058195db3f5f754b7ab430652ae04a50b8"
SHA256 = "8d9b5190aace52a1db1ac73a65ee9999c329157c8e88f61a772433323d6b7a4a"
URL = "https://software.bigfix.com/download/redist/7za920.exe"

# example-test.bes with something each file-rewriting hook auto-fixes:
# trailing whitespace (bes-conventions-check), `sha2:` (-validate-prefetch),
# an uppercase verb (-lint-schclass), a wrong-case `__download`
# (-validate-script)
FIXABLE_SCRIPT = (
    f"prefetch 7za920.exe sha1:{SHA1} size:167936 {URL} sha2:{SHA256}\n"
    "WAIT __download\\7za920.exe\n"
)


# not BES.xsd-valid: bes-schema-validate fails it
INVALID_BES = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<BES xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xsi:noNamespaceSchemaLocation="BES.xsd">\n'
    "\t<NotAnElement/>\n"
    "</BES>\n"
)


def write_invalid(path):
    path.write_text(INVALID_BES, encoding="utf-8")


def fixable_bes():
    text = GOOD.read_text(encoding="utf-8")
    text = text.replace("<Title>Nothing - Example</Title>", "<Title>Fixable</Title>   ")
    return text.replace("dos echo Nothing\n", FIXABLE_SCRIPT)


def hooks_yaml():
    """Return the hooks in .pre-commit-hooks.yaml as {id: hook dict}."""
    hooks = yaml.safe_load((REPO / ".pre-commit-hooks.yaml").read_text("utf-8"))
    return {hook["id"]: hook for hook in hooks}


def snapshot(root):
    """Return {relative path: bytes} for every file under `root`."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(Path(root).rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


# --- the hook table matches .pre-commit-hooks.yaml -------------------------------


def test_runner_covers_every_hook():
    assert [hook.id for hook in run_all.HOOKS] == list(hooks_yaml())


@pytest.mark.parametrize("hook", run_all.HOOKS, ids=lambda hook: hook.id)
def test_runner_hook_matches_its_declaration(hook):
    declared = hooks_yaml()[hook.id]
    assert hook.files == declared.get("files")
    assert list(hook.args) == declared.get("args", [])
    # the same program pre-commit runs
    module = f"pre_commit_bigfix.{hook.module}:main"
    assert console_scripts()[declared["entry"].split()[0]] == module
    # the layout hook reads `git ls-files` itself; every other hook is given files
    assert (hook.files is None) is (declared.get("pass_filenames") is False)


def console_scripts():
    parser = configparser.ConfigParser()
    parser.read(REPO / "setup.cfg", encoding="utf-8")
    raw = parser["options.entry_points"]["console_scripts"]
    return {
        name.strip(): target.strip()
        for name, _, target in (
            line.partition("=") for line in raw.splitlines() if "=" in line
        )
    }


def test_console_script_is_declared():
    assert console_scripts()["pre-commit-bigfix"] == "pre_commit_bigfix.run_all:main"


# --- read-only ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hook_id", "argv"),
    [
        ("bes-conventions-check", ["--auto-fix=yes"]),
        ("bes-actionscript-lint-schclass", ["--auto-fix=yes"]),
        ("bes-actionscript-validate-prefetch", ["--auto-fix=yes"]),
        ("bes-actionscript-validate-script", ["--auto-fix=yes"]),
    ],
)
def test_fixture_is_fixable_by(hook_id, argv, tmp_path, monkeypatch):
    """Precondition for the read-only test: each of these hooks would rewrite it."""
    path = tmp_path / "fixable.bes"
    path.write_text(fixable_bes(), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.chdir(tmp_path)
    hook = next(hook for hook in run_all.HOOKS if hook.id == hook_id)
    hook.load().main([*argv, str(path)])
    assert path.read_bytes() != before


def test_group_fixture_is_converted_without_check(tmp_path, monkeypatch):
    """Precondition: without --check, bes-relevance-convert-group rewrites it."""
    path = tmp_path / GROUP.name
    shutil.copy(GROUP, path)
    before = path.read_bytes()
    monkeypatch.chdir(tmp_path)
    hook = next(
        hook for hook in run_all.HOOKS if hook.id == "bes-relevance-convert-group"
    )
    hook.load().main([str(path)])
    assert path.read_bytes() != before


# a hook option that writes files, and what turns it off
WRITING_OPTIONS = (
    (r"--auto-fix(?![-\w])", "--auto-fix=no"),
    (r"--auto-fix-network(?![-\w])", "--auto-fix-network=no"),
    (r"--check(?![-\w])", "--check"),
)


@pytest.mark.parametrize("hook", run_all.HOOKS, ids=lambda hook: hook.id)
def test_every_writing_option_is_turned_off(hook, capsys):
    """A hook that offers a way not to write gets it, so a new hook can't slip by."""
    with pytest.raises(SystemExit):
        hook.load().main(["--help"])
    help_text = capsys.readouterr().out
    assert "usage:" in help_text
    for option, off in WRITING_OPTIONS:
        if re.search(option, help_text):
            assert off in hook.read_only, f"{hook.id} offers {off} but is not given it"


def test_runner_writes_nothing(tmp_path, monkeypatch, capsys):
    (tmp_path / "fixable.bes").write_text(fixable_bes(), encoding="utf-8")
    shutil.copy(GROUP, tmp_path / GROUP.name)  # bes-relevance-convert-group
    before = snapshot(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert run_all.main([]) == 1
    assert snapshot(tmp_path) == before
    assert "[W302]" in capsys.readouterr().out


def test_runner_renames_nothing(tmp_path, monkeypatch, capsys):
    """Bes-siterepo-validate-layout runs with --check: reported, not renamed."""
    repo = tmp_path / "site"
    (repo / "Fixlets/A").mkdir(parents=True)
    shutil.copy(GOOD, repo / "Fixlets/A/0042- Nothing - Example.bes")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    monkeypatch.chdir(repo)
    assert run_all.main([]) == 1
    assert "[E803]" in capsys.readouterr().out
    assert sorted(p.name for p in (repo / "Fixlets/A").iterdir()) == [
        "0042- Nothing - Example.bes"
    ]
    assert git(repo, "diff", "--cached", "--name-status", "-M") == (
        "A\tFixlets/A/0042- Nothing - Example.bes\n"
    )


# --- results and exit code ---------------------------------------------------------


def test_clean_folder_passes(tmp_path, monkeypatch, capsys):
    shutil.copy(GOOD, tmp_path / GOOD.name)
    monkeypatch.chdir(tmp_path)
    assert run_all.main([]) == 0
    out = capsys.readouterr().out
    # every file hook ran; outside a git repo the layout hook is skipped
    for hook in run_all.HOOKS:
        assert hook.id in out
    assert "not a git repo" in out


def test_bad_file_fails_and_names_the_failing_hook(tmp_path, monkeypatch, capsys):
    write_invalid(tmp_path / "invalid.bes")
    monkeypatch.chdir(tmp_path)
    assert run_all.main([]) == 1
    out = capsys.readouterr().out
    assert "invalid.bes" in out
    assert re.search(r"bes-schema-validate\b.*fail", out, re.IGNORECASE)


def test_empty_folder_passes_and_hooks_do_not_auto_discover(
    tmp_path, monkeypatch, capsys
):
    """A hook with no matching files is skipped, never run with no arguments.

    Run with no file names, most hooks search the current folder themselves,
    which would check the files the runner deliberately left out.
    """
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    write_invalid(hidden / "invalid.bes")
    monkeypatch.chdir(tmp_path)
    assert run_all.main([]) == 0
    out = capsys.readouterr().out
    assert "invalid.bes" not in out
    assert "no files" in out


def test_explicit_paths(tmp_path, monkeypatch, capsys):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    shutil.copy(GOOD, tmp_path / "a" / GOOD.name)
    write_invalid(tmp_path / "b" / "invalid.bes")
    monkeypatch.chdir(tmp_path)
    assert run_all.main(["a"]) == 0
    assert run_all.main([os.path.join("b", "invalid.bes")]) == 1
    capsys.readouterr()


def test_missing_path_is_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert run_all.main(["nope"]) == 2
    assert "nope" in capsys.readouterr().err


def test_skip(tmp_path, monkeypatch, capsys):
    write_invalid(tmp_path / "invalid.bes")
    monkeypatch.chdir(tmp_path)
    run_all.main(["--skip", "bes-schema-validate"])
    out = capsys.readouterr().out
    assert not re.search(r"^=+ bes-schema-validate\b", out, re.MULTILINE)


def test_a_crashing_hook_fails_but_the_others_still_run(tmp_path, monkeypatch, capsys):
    class Broken:
        @staticmethod
        def main(argv):
            raise RuntimeError("boom")

    first = run_all.HOOKS[0]
    monkeypatch.setattr(
        run_all,
        "HOOKS",
        (first._replace(module="no_such_module"), *run_all.HOOKS[1:]),
    )
    monkeypatch.setattr(
        type(first),
        "load",
        lambda hook: (
            Broken
            if hook.module == "no_such_module"
            else run_all.importlib.import_module(f"pre_commit_bigfix.{hook.module}")
        ),
    )
    shutil.copy(GOOD, tmp_path / GOOD.name)
    monkeypatch.chdir(tmp_path)
    assert run_all.main([]) == 1
    captured = capsys.readouterr()
    assert "boom" in captured.err
    assert f"{first.id}: crashed" in captured.out
    assert "=== bes-conventions-check" in captured.out


def test_skip_unknown_hook_is_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        run_all.main(["--skip", "no-such-hook"])
    assert exc.value.code == 2


def test_a_file_name_starting_with_a_dash_is_not_an_option(
    tmp_path, monkeypatch, capsys
):
    """`-h.bes` must be checked, not read as -h (help, exit 0: a false pass)."""
    write_invalid(tmp_path / "-h.bes")
    monkeypatch.chdir(tmp_path)
    assert run_all.main([]) == 1
    out = capsys.readouterr().out
    assert "usage:" not in out
    assert "-h.bes" in out


def test_files_are_matched_like_pre_commit_from_inside_a_folder(
    tmp_path, monkeypatch, capsys
):
    """`(^|/)Signatures/...` must match when run from inside Signatures/."""
    sigs = tmp_path / "Signatures"
    sigs.mkdir()
    shutil.copy(EXAMPLES / "site-bad" / "Signatures" / "example.xml", sigs)
    monkeypatch.chdir(sigs)
    assert run_all.main([]) == 1
    assert run_all.main(["example.xml"]) == 1
    capsys.readouterr()


def test_a_named_file_no_hook_checks_is_reported(tmp_path, monkeypatch, capsys):
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert run_all.main(["notes.txt"]) == 0
    assert "notes.txt: not checked by any hook" in capsys.readouterr().err


def test_layout_hook_checks_the_repo_of_the_path(tmp_path, monkeypatch, capsys):
    """Not the repo of the current folder: here, the current folder has none."""
    repo = tmp_path / "site"
    (repo / "Fixlets/A").mkdir(parents=True)
    shutil.copy(GOOD, repo / "Fixlets/A/0042- Nothing - Example.bes")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    monkeypatch.chdir(tmp_path)
    assert run_all.main(["site"]) == 1
    assert "[E803]" in capsys.readouterr().out
    assert (repo / "Fixlets/A/0042- Nothing - Example.bes").exists()
    # and the runner's own current folder is left as it was
    assert Path.cwd() == tmp_path


# --- discovery ---------------------------------------------------------------------


def touch(root, *rels):
    for rel in rels:
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")


def rels(paths, root):
    return sorted(Path(p).relative_to(root).as_posix() for p in paths)


def test_discover_keeps_files_some_hook_checks(tmp_path):
    touch(
        tmp_path,
        "a.bes",
        "b.ojo",
        "r.rel",
        "Site/siteConfig.xml",
        "Signatures/s.xml",
        "pom.xml",
        "readme.md",
    )
    found = run_all.discover([str(tmp_path)])
    assert rels(found, tmp_path) == [
        "Signatures/s.xml",
        "Site/siteConfig.xml",
        "a.bes",
        "b.ojo",
        "r.rel",
    ]


def test_discover_skips_dot_folders_and_tool_folders(tmp_path):
    touch(
        tmp_path,
        "keep.bes",
        ".git/x.bes",
        ".venv/lib/x.bes",
        "sub/.cache/x.bes",
        "node_modules/x.bes",
        "__pycache__/x.bes",
    )
    assert rels(run_all.discover([str(tmp_path)]), tmp_path) == ["keep.bes"]


def test_include_hidden_still_skips_tool_folders(tmp_path):
    touch(tmp_path, "keep.bes", "node_modules/x.bes", "__pycache__/x.bes")
    found = run_all.discover([str(tmp_path)], include_hidden=True)
    assert rels(found, tmp_path) == ["keep.bes"]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")
def test_discover_skips_symlinked_files_like_pre_commit(tmp_path):
    """Pre-commit types a symlink as `symlink`, not `text`, so no hook gets one."""
    touch(tmp_path, "real.bes")
    os.symlink(tmp_path / "real.bes", tmp_path / "link.bes")
    assert rels(run_all.discover([str(tmp_path)]), tmp_path) == ["real.bes"]


def test_discover_lists_a_file_once(tmp_path, monkeypatch):
    touch(tmp_path, "x.bes")
    monkeypatch.chdir(tmp_path)
    assert run_all.discover(["x.bes", "./x.bes", "."]) == ["x.bes"]


def test_include_hidden_walks_dot_folders(tmp_path):
    touch(tmp_path, "keep.bes", ".hidden/x.bes")
    found = run_all.discover([str(tmp_path)], include_hidden=True)
    assert rels(found, tmp_path) == [".hidden/x.bes", "keep.bes"]


@pytest.mark.skipif(
    not (hasattr(os, "chflags") and hasattr(stat, "UF_HIDDEN")),
    reason="needs the BSD/macOS hidden flag",
)
def test_discover_skips_folders_with_the_hidden_flag(tmp_path):
    touch(tmp_path, "keep.bes", "flagged/x.bes")
    os.chflags(tmp_path / "flagged", stat.UF_HIDDEN)
    assert rels(run_all.discover([str(tmp_path)]), tmp_path) == ["keep.bes"]


def test_a_named_hidden_folder_is_walked(tmp_path):
    """Hidden folders are skipped while walking, not when named on purpose."""
    touch(tmp_path, ".hidden/x.bes")
    found = run_all.discover([str(tmp_path / ".hidden")])
    assert rels(found, tmp_path) == [".hidden/x.bes"]


def test_a_named_file_is_kept_even_if_no_hook_matches_it(tmp_path):
    touch(tmp_path, "notes.txt")
    assert run_all.discover([str(tmp_path / "notes.txt")]) == [
        str(tmp_path / "notes.txt")
    ]
