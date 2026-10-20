#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_siterepo_validate_layout.py.

The hook checks a Git External Custom Site ("repository site") repo as a
whole: its file list comes from `git ls-files`, so most tests build a small
git repo in tmp_path. Covered here: the server path prefix (pinned to the
path confirmed on a real server), the repo-name default, the file list,
siteConfig.xml folder names, the naming and duplicate-ID errors, the layout
warnings, path length, the rename auto-fix, --check, and main()'s exit codes.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from pre_commit_bigfix import bes_siterepo_validate_layout as hook


@pytest.fixture(autouse=True)
def no_outer_git_hook_env(monkeypatch):
    """Drop git's hook variables, in case the suite runs inside a git hook.

    git sets GIT_INDEX_FILE (and may set GIT_DIR) for hooks; inherited, they
    would point the tests' git commands at the outer repo's index.
    """
    for name in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_PREFIX"):
        monkeypatch.delenv(name, raising=False)


# confirmed on James's BigFix server for jgstew/bigfix-site-reporting-jgstew
CONFIRMED_SOURCE = (
    "C:\\Program Files (x86)\\BigFix Enterprise\\BES Server\\RepositorySiteGather"
    "\\Sites\\bigfix-site-reporting-jgstew_main_27eb797e\\Source\\"
)

BES_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<BES xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xsi:noNamespaceSchemaLocation="BES.xsd">\n'
    "\t<Task>\n\t\t<Title>{title}</Title>\n"
    "\t\t<Description>d</Description>\n\t\t<Relevance>true</Relevance>\n"
    "\t</Task>\n</BES>\n"
)


def bes(title="Example Task"):
    """A minimal Task whose <Title> is `title` (raw XML text)."""
    return BES_TEMPLATE.format(title=title)


def git(repo, *args):
    """Run git in `repo` and return its stdout."""
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def make_repo(root, files, name="site-repo", add=True):
    """Create a git repo under `root` named `name` holding `files`.

    `files` maps repo-relative paths to text (a .bes with None gets bes()).
    With `add`, every file is staged, which is all `git ls-files` needs.
    """
    repo = Path(root) / name
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            text = bes(Path(rel).stem)
        path.write_text(text, encoding="utf-8")
    if add and files:
        git(repo, "add", "-A")
    return repo


def run(repo, *args, files=None, **kwargs):
    """Run check_repo() on `repo` with its tracked files; return {path: codes}."""
    if files is None:
        files = hook.git_ls_files(repo)
    results = hook.check_repo(str(repo), files, *args, **kwargs)
    return {
        path: sorted(code for _line, code, _msg in issues + fixed)
        for path, issues, fixed in results
        if issues or fixed
    }


def messages(repo, *args, files=None, **kwargs):
    """Run check_repo() on `repo`; return every (path, code, message) reported."""
    if files is None:
        files = hook.git_ls_files(repo)
    found = []
    for path, issues, fixed in hook.check_repo(str(repo), files, *args, **kwargs):
        found += [(path, code, msg) for _line, code, msg in issues + fixed]
    return found


# --- server path prefix -----------------------------------------------------


def test_server_prefix_matches_the_path_confirmed_on_a_server():
    prefix = hook.server_prefix(
        hook.DEFAULT_SERVER_ROOT,
        "bigfix-site-reporting-jgstew",
        "main",
        commit_hash="27eb797e",
    )
    assert prefix == CONFIRMED_SOURCE
    assert len(prefix) == 129


def test_server_prefix_placeholder_hash_is_eight_characters():
    prefix = hook.server_prefix(
        hook.DEFAULT_SERVER_ROOT, "bigfix-site-reporting-jgstew", "main"
    )
    assert len(prefix) == 129
    assert prefix.startswith(hook.DEFAULT_SERVER_ROOT + "\\RepositorySiteGather\\")


def test_server_prefix_other_server_root_and_trailing_separator():
    prefix = hook.server_prefix(
        "E:\\Program Files\\BigFix Enterprise\\BES Server\\", "AACBigFix", "HX90"
    )
    assert prefix.startswith(
        "E:\\Program Files\\BigFix Enterprise\\BES Server\\RepositorySiteGather"
        "\\Sites\\AACBigFix_HX90_"
    )
    assert "\\\\" not in prefix
    assert prefix.endswith("\\Source\\")


def test_server_path_length_uses_backslashes_and_whole_relative_path():
    prefix = hook.server_prefix(
        hook.DEFAULT_SERVER_ROOT, "bigfix-site-reporting-jgstew", "main"
    )
    # 129 + 130 = 259, the limit; one more is over
    rel = "Fixlets/" + "a" * 118 + ".bes"
    assert len(rel) == 130
    assert hook.server_path_length(prefix, rel) == 259


def test_server_path_length_counts_utf16_units():
    # Windows MAX_PATH counts UTF-16 code units: an astral character is two
    assert hook.server_path_length("", "a\U0001f600.bes") == 7


# --- repo name ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "name"),
    [
        ("https://github.com/jgstew/bigfix-site-reporting-jgstew.git", None),
        ("https://github.com/jgstew/bigfix-site-reporting-jgstew", None),
        ("https://github.com/jgstew/bigfix-site-reporting-jgstew/", None),
        ("git@github.com:jgstew/bigfix-site-reporting-jgstew.git", None),
        ("ssh://git@host:2222/jgstew/bigfix-site-reporting-jgstew.git", None),
        ("git@github.com:acapasso/AACBigFix.git", "AACBigFix"),
        ("git@host:AACBigFix.git", "AACBigFix"),
    ],
)
def test_repo_name_from_url(url, name):
    assert hook.repo_name_from_url(url) == (name or "bigfix-site-reporting-jgstew")


def test_default_repo_name_uses_origin(tmp_path):
    repo = make_repo(tmp_path, {}, name="local-folder")
    git(repo, "remote", "add", "origin", "git@github.com:owner/remote-name.git")
    assert hook.default_repo_name(str(repo)) == "remote-name"


def test_default_repo_name_falls_back_to_folder(tmp_path):
    repo = make_repo(tmp_path, {}, name="local-folder")
    assert hook.default_repo_name(str(repo)) == "local-folder"


# --- file list ----------------------------------------------------------------


def test_git_ls_files_lists_tracked_files_only(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "Fixlets/1- A.bes": None,
            "Fixlets/2- Euro \u20ac.bes": None,
            "Sites/With Space/x.txt": "x",
            ".gitignore": "ignored.bes\n",
        },
    )
    (repo / "Fixlets" / "3- untracked.bes").write_text(bes(), encoding="utf-8")
    (repo / "ignored.bes").write_text(bes(), encoding="utf-8")
    assert hook.git_ls_files(str(repo)) == [
        ".gitignore",
        "Fixlets/1- A.bes",
        "Fixlets/2- Euro \u20ac.bes",
        "Sites/With Space/x.txt",
    ]


# --- siteConfig.xml -----------------------------------------------------------


def test_site_config_defaults_without_file(tmp_path):
    repo = make_repo(tmp_path, {"Fixlets/1- A.bes": None})
    config = hook.read_site_config(str(repo), "", hook.git_ls_files(repo))
    assert config.bes_dir == "Fixlets"
    assert config.nonclient_dir == "NonClientFiles"
    assert config.other_dir == "OtherFiles"
    assert config.named == ()
    assert config.issue is None


def test_site_config_renamed_folders(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "siteConfig.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>\n<SiteConfig>\n'
                "  <BesFileDir>Content</BesFileDir>\n"
                "  <NonClientFilesDir> ServerFiles </NonClientFilesDir>\n"
                "  <OtherFilesDir>ClientFiles/</OtherFilesDir>\n</SiteConfig>\n"
            )
        },
    )
    config = hook.read_site_config(str(repo), "", hook.git_ls_files(repo))
    assert (config.bes_dir, config.nonclient_dir, config.other_dir) == (
        "Content",
        "ServerFiles",
        "ClientFiles",
    )
    assert set(config.named) == {"Content", "ServerFiles", "ClientFiles"}


def test_site_config_partial_keeps_other_defaults(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "Sites/A/siteConfig.xml": (
                "<SiteConfig><NonClientFilesDir>Srv</NonClientFilesDir></SiteConfig>"
            )
        },
    )
    config = hook.read_site_config(str(repo), "Sites/A", hook.git_ls_files(repo))
    assert (config.bes_dir, config.nonclient_dir, config.other_dir) == (
        "Fixlets",
        "Srv",
        "OtherFiles",
    )
    assert config.named == ("Srv",)


def test_site_config_malformed_warns_and_uses_defaults(tmp_path):
    repo = make_repo(tmp_path, {"siteConfig.xml": "<SiteConfig><BesFileDir>X"})
    config = hook.read_site_config(str(repo), "", hook.git_ls_files(repo))
    assert config.bes_dir == "Fixlets"
    assert config.issue[1] == "W807"


def test_site_config_untracked_is_ignored(tmp_path):
    repo = make_repo(tmp_path, {"Fixlets/1- A.bes": None})
    (repo / "siteConfig.xml").write_text(
        "<SiteConfig><BesFileDir>Content</BesFileDir></SiteConfig>", encoding="utf-8"
    )
    config = hook.read_site_config(str(repo), "", hook.git_ls_files(repo))
    assert config.bes_dir == "Fixlets"


# --- main ---------------------------------------------------------------------


def test_main_clean_site_passes(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, {"Fixlets/A/1- A.bes": None, "Fixlets/A/2 B.bes": None})
    monkeypatch.chdir(repo)
    assert hook.main([]) == 0
    assert capsys.readouterr().out == ""


def test_main_outside_git_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert hook.main([]) == 1
    assert "git" in capsys.readouterr().out.lower()


def test_main_uses_injected_file_list(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, {"Fixlets/A/1- A.bes": None})
    monkeypatch.chdir(repo)
    seen = []

    def lister(root):
        seen.append(root)
        return ["Fixlets/A/1- A.bes"]

    assert hook.main([], list_files=lister) == 0
    assert os.path.realpath(seen[0]) == os.path.realpath(repo)


# --- E800 numeric ID prefix ---------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "42- Name.bes",  # the documented form
        "42 Name.bes",  # reported to work, James's ruling
        "42-Name.bes",  # every CommunityContent file
        "7200101 Paint.net-Update.bes",  # BigFix-ExtendedContent
        "42 - Name.bes",
    ],
)
def test_e800_accepts_id_then_space_or_hyphen(tmp_path, name):
    # Bad.bes is the control: it shows the check ran and only it was flagged
    repo = make_repo(tmp_path, {f"Fixlets/A/{name}": None, "Fixlets/A/Bad.bes": None})
    assert run(repo, check=True) == {"Fixlets/A/Bad.bes": ["E800"]}


@pytest.mark.parametrize("name", ["Name.bes", "42_Name.bes", "42.bes", "x42- Name.bes"])
def test_e800_flags_names_without_an_id_prefix(tmp_path, name):
    repo = make_repo(tmp_path, {f"Fixlets/A/{name}": None})
    found = messages(repo, check=True)
    assert [code for _path, code, _msg in found] == ["E800"]
    path, _code, message = found[0]
    assert path == f"Fixlets/A/{name}"
    assert "42- Name.bes" in message  # says what the name should look like


def test_e800_only_inside_the_bes_folder(tmp_path):
    repo = make_repo(tmp_path, {"Fixlets/A/Name.bes": None, "tests/Name.bes": None})
    found = run(repo, check=True)
    assert "E800" in found["Fixlets/A/Name.bes"]
    assert "E800" not in found.get("tests/Name.bes", [])


def test_e800_uses_the_bes_folder_from_site_config(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "siteConfig.xml": "<SiteConfig><BesFileDir>Content</BesFileDir></SiteConfig>",
            "Content/A/Name.bes": None,
            "Fixlets/A/Other.bes": None,
        },
    )
    found = run(repo, check=True)
    assert "E800" in found["Content/A/Name.bes"]
    assert "E800" not in found.get("Fixlets/A/Other.bes", [])


def test_e800_bes_folder_matches_case_insensitively(tmp_path):
    # the server runs on Windows, where fixlets\ and Fixlets\ are one folder
    repo = make_repo(tmp_path, {"fixlets/A/Name.bes": None})
    assert "E800" in run(repo, check=True)["fixlets/A/Name.bes"]


# --- E801 duplicate IDs -------------------------------------------------------


def test_e801_compares_ids_as_integers(tmp_path):
    repo = make_repo(
        tmp_path, {"Fixlets/A/0042- X.bes": None, "Fixlets/B/42- Y.bes": None}
    )
    found = [m for m in messages(repo, check=True) if m[1] == "E801"]
    assert sorted(path for path, _code, _msg in found) == [
        "Fixlets/A/0042- X.bes",
        "Fixlets/B/42- Y.bes",
    ]
    by_path = {path: msg for path, _code, msg in found}
    assert "Fixlets/B/42- Y.bes" in by_path["Fixlets/A/0042- X.bes"]
    assert "Fixlets/A/0042- X.bes" in by_path["Fixlets/B/42- Y.bes"]
    assert "42" in by_path["Fixlets/A/0042- X.bes"]


def test_e801_names_every_other_file(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "Fixlets/A/7- a.bes": None,
            "Fixlets/A/7 b.bes": None,
            "Fixlets/A/7-c.bes": None,
        },
    )
    found = {p: m for p, c, m in messages(repo, check=True) if c == "E801"}
    assert len(found) == 3
    assert "Fixlets/A/7 b.bes" in found["Fixlets/A/7- a.bes"]
    assert "Fixlets/A/7-c.bes" in found["Fixlets/A/7- a.bes"]


def test_e801_distinct_ids_pass(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "Fixlets/A/1- a.bes": None,
            "Fixlets/A/10- a.bes": None,
            "Fixlets/A/5- x.bes": None,  # the control pair
            "Fixlets/A/5 y.bes": None,
        },
    )
    assert run(repo, check=True) == {
        "Fixlets/A/5 y.bes": ["E801"],
        "Fixlets/A/5- x.bes": ["E801"],
    }


def test_e801_is_per_site(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "Sites/A/Fixlets/X/1- a.bes": None,
            "Sites/B/Fixlets/X/1- b.bes": None,
            "Sites/B/Fixlets/Y/01- c.bes": None,
        },
    )
    found = run(repo, ["Sites/A", "Sites/B"], check=True)
    assert "E801" not in found.get("Sites/A/Fixlets/X/1- a.bes", [])
    assert "E801" in found["Sites/B/Fixlets/X/1- b.bes"]
    assert "E801" in found["Sites/B/Fixlets/Y/01- c.bes"]


def test_e801_ignores_bes_files_outside_the_bes_folder(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "Fixlets/A/1- a.bes": None,
            "Fixlets/B/1 b.bes": None,
            "Archive/1- old.bes": None,
        },
    )
    flagged = sorted(p for p, c, m in messages(repo, check=True) if c == "E801")
    assert flagged == ["Fixlets/A/1- a.bes", "Fixlets/B/1 b.bes"]
    e801 = [m for m in messages(repo, check=True) if m[1] == "E801"]
    assert "Archive" not in str(e801)


# --- W806 ID range ------------------------------------------------------------


@pytest.mark.parametrize(
    ("prefix", "flagged"),
    [
        ("0", True),
        ("000", True),
        ("1", False),
        ("2147483647", False),
        ("2147483648", True),
        ("99999999999999999999", True),
    ],
)
def test_w806_id_out_of_range(tmp_path, prefix, flagged):
    # Fixlets/B/0- control.bes is always flagged: it shows the check ran
    repo = make_repo(
        tmp_path,
        {f"Fixlets/A/{prefix}- a.bes": None, "Fixlets/B/0- control.bes": None},
    )
    found = run(repo, check=True)
    assert "W806" in found["Fixlets/B/0- control.bes"]
    assert ("W806" in found.get(f"Fixlets/A/{prefix}- a.bes", [])) is flagged


def test_w806_is_a_warning_main_passes(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, {"Fixlets/A/2147483648- a.bes": None})
    monkeypatch.chdir(repo)
    assert hook.main(["--check"]) == 0
    assert hook.main(["--check", "--strict"]) == 1


def test_main_fails_on_e800(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, {"Fixlets/A/Name.bes": None})
    monkeypatch.chdir(repo)
    assert hook.main(["--check"]) == 1
    assert "Fixlets/A/Name.bes:1: [E800]" in capsys.readouterr().out


def test_disable_drops_a_code(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, {"Fixlets/A/Name.bes": None})
    monkeypatch.chdir(repo)
    assert hook.main(["--check", "--disable", "E800"]) == 0
    assert run(repo, check=True, disabled={"E800"}) == {}


# --- layout warnings ----------------------------------------------------------

REPORTING_SITE_CONFIG = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<SiteConfig>\n'
    "  <BesFileDir>Fixlets</BesFileDir>\n"
    "  <NonClientFilesDir>ServerFiles</NonClientFilesDir>\n"
    "  <OtherFilesDir>ClientFiles</OtherFilesDir>\n</SiteConfig>\n"
)


def test_w800_bes_outside_the_bes_folder(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "Fixlets/A/1- ok.bes": None,
            "tests/2- t.bes": None,
            "OtherFiles/3- o.bes": None,
            "4- root.bes": None,
        },
    )
    assert run(repo, check=True) == {
        "4- root.bes": ["W800"],
        "OtherFiles/3- o.bes": ["W800"],
        "tests/2- t.bes": ["W800"],
    }
    message = [m for p, c, m in messages(repo, check=True) if p == "4- root.bes"][0]
    assert "Fixlets" in message


def test_w800_ignores_files_outside_every_site_root(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "Sites/A/Fixlets/X/1- ok.bes": None,
            "Sites/A/2- stray.bes": None,
            "tools/3- tool.bes": None,
        },
    )
    assert run(repo, ["Sites/A"], check=True) == {"Sites/A/2- stray.bes": ["W800"]}


def test_w801_bes_depth(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "Fixlets/1- top.bes": None,
            "Fixlets/A/2- fxf.bes": None,
            "Fixlets/A/B/3- digest.bes": None,
            "Fixlets/A/B/C/4- deep.bes": None,
        },
    )
    assert run(repo, check=True) == {
        "Fixlets/1- top.bes": ["W801"],
        "Fixlets/A/B/C/4- deep.bes": ["W801"],
    }


def test_w802_other_files_in_the_bes_folder(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "Fixlets/digest.xml": "<Digest/>",
            "Fixlets/A/digest.xml": "<Digest/>",
            "Fixlets/A/1- ok.bes": None,
            "Fixlets/digest.xsd": "<xs/>",
            "Fixlets/A/readme.txt": "x",
            "Fixlets/A/x.ojo": "x",
            "Fixlets/.gitkeep": "",
        },
    )
    assert run(repo, check=True) == {
        "Fixlets/.gitkeep": ["W802"],
        "Fixlets/A/readme.txt": ["W802"],
        "Fixlets/A/x.ojo": ["W802"],
        "Fixlets/digest.xsd": ["W802"],
    }
    xsd = [m for p, c, m in messages(repo, check=True) if p.endswith(".xsd")][0]
    assert "bes-schema-validate" in xsd


def test_w803_named_folder_missing(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "siteConfig.xml": REPORTING_SITE_CONFIG,
            "Fixlets/A/1- a.bes": None,
            "ServerFiles/x.ojo": "x",
        },
    )
    found = messages(repo, check=True)
    assert [(p, c) for p, c, m in found] == [("siteConfig.xml", "W803")]
    assert "ClientFiles" in found[0][2]


def test_w803_not_for_default_folders(tmp_path):
    # without siteConfig.xml nothing names NonClientFiles/OtherFiles, so their
    # absence is fine; the second site is the control
    repo = make_repo(
        tmp_path,
        {
            "Sites/A/Fixlets/X/1- a.bes": None,
            "Sites/B/siteConfig.xml": REPORTING_SITE_CONFIG,
            "Sites/B/Fixlets/X/1- a.bes": None,
        },
    )
    found = run(repo, ["Sites/A", "Sites/B"], check=True)
    # Sites/B names ServerFiles/ and ClientFiles/, and has neither
    assert found == {"Sites/B/siteConfig.xml": ["W803", "W803"]}


def test_w804_site_without_content(tmp_path):
    repo = make_repo(tmp_path, {"README.md": "x", "Fixlets/digest.xml": "<D/>"})
    assert run(repo, check=True) == {".": ["W804"]}


def test_w804_bes_outside_the_folder_is_not_content(tmp_path):
    repo = make_repo(tmp_path, {"Archive/1- a.bes": None})
    assert run(repo, check=True) == {".": ["W804"], "Archive/1- a.bes": ["W800"]}


def test_w804_server_files_only_site_passes(tmp_path):
    # the bigfix-site-reporting-jgstew shape; Sites/B (README only) is the control
    repo = make_repo(
        tmp_path,
        {
            "Sites/A/siteConfig.xml": REPORTING_SITE_CONFIG,
            "Sites/A/Fixlets/digest.xml": "<D/>",
            "Sites/A/ServerFiles/r.ojo": "x",
            "Sites/A/ClientFiles/c.txt": "x",
            "Sites/B/README.md": "x",
        },
    )
    assert run(repo, ["Sites/A", "Sites/B"], check=True) == {"Sites/B": ["W804"]}


def test_reporting_site_shape_only_warns_on_the_xsd(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            ".gitignore": "x\n",
            "README.md": "x",
            "LICENSE": "x",
            "site.xml": "<Site/>",
            "siteConfig.xml": REPORTING_SITE_CONFIG,
            "Fixlets/digest.xsd": "<xs/>",
            "ClientFiles/client-file.txt": "x",
            "ServerFiles/relevance-debugger-console.ojo": "x",
            "ServerFiles/relevance-debugger-webreport.beswrpt": "x",
        },
        name="bigfix-site-reporting-jgstew",
    )
    assert run(repo, check=True) == {"Fixlets/digest.xsd": ["W802"]}


def test_w803_not_for_default_names_spelled_out(tmp_path):
    # CommunityContent and the RepositorySiteExample template name all three
    # default folders in siteConfig.xml, and most sites have no
    # NonClientFiles/ or OtherFiles/: those are optional, so that is fine.
    # A renamed folder that is missing (Srv/) is still flagged.
    repo = make_repo(
        tmp_path,
        {
            "siteConfig.xml": (
                "<SiteConfig><BesFileDir>Fixlets</BesFileDir>"
                "<NonClientFilesDir>NonClientFiles</NonClientFilesDir>"
                "<OtherFilesDir>OtherFiles</OtherFilesDir></SiteConfig>"
            ),
            "Fixlets/X/1- a.bes": None,
            "Sites/B/siteConfig.xml": (
                "<SiteConfig><NonClientFilesDir>Srv</NonClientFilesDir>"
                "<OtherFilesDir>OtherFiles</OtherFilesDir></SiteConfig>"
            ),
            "Sites/B/Fixlets/X/1- a.bes": None,
        },
    )
    found = messages(repo, ["", "Sites/B"], check=True)
    assert [(p, c) for p, c, m in found] == [("Sites/B/siteConfig.xml", "W803")]
    assert "Srv/" in found[0][2]


# --- path length --------------------------------------------------------------

# a 10-character prefix keeps the arithmetic readable: limit 50 leaves 40
SHORT_PREFIX = "C:\\Source\\"


def test_e807_long_non_bes_path(tmp_path):
    long_name = "OtherFiles/" + "x" * 25 + ".txt"  # 40 characters
    repo = make_repo(
        tmp_path,
        {
            "Fixlets/A/1- a.bes": None,
            long_name: "x",
            "OtherFiles/" + "y" * 26 + ".txt": "x",  # 41
        },
    )
    found = messages(repo, check=True, prefix=SHORT_PREFIX, max_path=50)
    assert [(p, c) for p, c, m in found] == [
        ("OtherFiles/" + "y" * 26 + ".txt", "E807")
    ]
    message = found[0][2]
    assert "51" in message and "50" in message
    assert "rename" in message.lower()  # says why it is not renamed


def test_e807_counts_the_prefix(tmp_path):
    # no .bes file, which would be over the limit too
    repo = make_repo(tmp_path, {"OtherFiles/x.txt": "x"})
    # 16 characters of path; 50 - 16 = 34 left for the prefix
    assert run(repo, check=True, prefix="P" * 34, max_path=50) == {}
    assert run(repo, check=True, prefix="P" * 35, max_path=50) == {
        "OtherFiles/x.txt": ["E807"]
    }


def test_e807_bes_outside_the_bes_folder(tmp_path):
    repo = make_repo(
        tmp_path, {"Fixlets/A/1- a.bes": None, "Archive/" + "z" * 40 + ".bes": None}
    )
    found = run(repo, check=True, prefix=SHORT_PREFIX, max_path=50)
    assert found == {"Archive/" + "z" * 40 + ".bes": ["E807", "W800"]}


def test_e807_files_outside_every_site_root(tmp_path):
    # the server clones the whole repo, so every tracked file counts
    repo = make_repo(
        tmp_path,
        {"Sites/A/Fixlets/X/1- a.bes": None, "tools/" + "t" * 40 + ".py": "x"},
    )
    found = run(repo, ["Sites/A"], check=True, prefix=SHORT_PREFIX, max_path=50)
    assert found == {"tools/" + "t" * 40 + ".py": ["E807"]}


def test_path_measured_from_the_repo_root_not_the_site_root(tmp_path):
    # Sites/A/OtherFiles/abc.txt is 26 characters; OtherFiles/abc.txt only 18
    repo = make_repo(
        tmp_path,
        {"Sites/A/Fixlets/X/1- a.bes": None, "Sites/A/OtherFiles/abc.txt": "x"},
    )
    assert run(repo, ["Sites/A"], check=True, prefix="", max_path=26) == {}
    found = run(repo, ["Sites/A"], check=True, prefix="", max_path=25)
    assert found["Sites/A/OtherFiles/abc.txt"] == ["E807"]


def test_e802_folders_alone_too_long(tmp_path):
    folder = "Fixlets/" + "f" * 30  # 38 characters
    repo = make_repo(
        tmp_path,
        {
            f"{folder}/123- a.bes": None,  # shortest name 123 a.bes: 48 + 10 = 58
            "Fixlets/A/7- " + "n" * 40 + ".bes": None,  # fixable, so not E802
        },
    )
    found = messages(repo, check=True, prefix=SHORT_PREFIX, max_path=57)
    by_path = {p: (c, m) for p, c, m in found}
    assert by_path[f"{folder}/123- a.bes"][0] == "E802"
    assert "folder" in by_path[f"{folder}/123- a.bes"][1]
    assert "E802" not in str(by_path.get("Fixlets/A/7- " + "n" * 40 + ".bes"))
    # one more character of limit and `123 a.bes` fits
    found = run(repo, check=True, prefix=SHORT_PREFIX, max_path=58)
    assert "E802" not in found.get(f"{folder}/123- a.bes", [])


def test_e802_bes_without_an_id(tmp_path):
    # no ID to build a short name from, so it cannot be fixed either
    repo = make_repo(tmp_path, {"Fixlets/A/" + "n" * 50 + ".bes": None})
    found = run(repo, check=True, prefix=SHORT_PREFIX, max_path=50)
    assert found == {"Fixlets/A/" + "n" * 50 + ".bes": ["E800", "E802"]}


def test_confirmed_server_prefix_leaves_130(tmp_path, monkeypatch, capsys):
    ok = "OtherFiles/" + "o" * 115 + ".txt"  # 130
    over = "OtherFiles/" + "p" * 116 + ".txt"  # 131
    repo = make_repo(
        tmp_path,
        {"Fixlets/A/1- a.bes": None, ok: "x", over: "x"},
        name="bigfix-site-reporting-jgstew",
    )
    monkeypatch.chdir(repo)
    # E807: a path a Windows server cannot clone fails the sync, so it fails here
    assert hook.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert over in out and "[E807]" in out
    assert ok not in out


def test_main_path_options(tmp_path, monkeypatch, capsys):
    rel = "OtherFiles/" + "o" * 115 + ".txt"  # 130: fits the default prefix
    repo = make_repo(
        tmp_path,
        {"Fixlets/A/1- a.bes": None, rel: "x"},
        name="bigfix-site-reporting-jgstew",
    )
    monkeypatch.chdir(repo)
    for args in (
        ["--repo-name", "bigfix-site-reporting-jgstew2"],
        ["--branch", "mainx"],
        ["--server-root", hook.DEFAULT_SERVER_ROOT + "x"],
        ["--max-path", "258"],
    ):
        capsys.readouterr()
        assert hook.main(["--check", "--strict", *args]) == 1, args
        assert "[E807]" in capsys.readouterr().out
    assert hook.main(["--check", "--strict", "--server-root", "C:\\BES"]) == 0


def test_main_repo_name_defaults_to_origin(tmp_path, monkeypatch, capsys):
    rel = "OtherFiles/" + "o" * 115 + ".txt"
    repo = make_repo(tmp_path, {"Fixlets/A/1- a.bes": None, rel: "x"}, name="x")
    git(repo, "remote", "add", "origin", "https://h/o/bigfix-site-reporting-jgstew.git")
    monkeypatch.chdir(repo)
    assert hook.main(["--check", "--strict"]) == 0  # 129 + 130 = 259
    git(
        repo, "remote", "set-url", "origin", "git@h:o/bigfix-site-reporting-jgstewX.git"
    )
    assert hook.main(["--check", "--strict"]) == 1


# --- rename auto-fix: name helpers --------------------------------------------


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("plain - name.bes", "plain - name.bes"),
        ("Euro \u20ac only", "Euro EUR only"),  # #32
        ("\u00a3 pound", "GBP pound"),
        ("Docker\u2019s key", "Docker's key"),  # the one in bigfix-content
        ("\u2018quoted\u2019 \u201cdouble\u201d", "'quoted' 'double'"),
        ("a \u2013 b \u2014 c", "a - b - c"),
        ("r\u00e9sum\u00e9 na\u00efve \u00c5ngstr\u00f6m", "resume naive Angstrom"),
        ("Stra\u00dfe", "Strasse"),
        ("check \u2713", "check _"),  # no ASCII equivalent
        ("\u65e5\u672c", "__"),
        ("full\uff1awidth", "full_width"),  # NFKD gives ':', which Windows forbids
        ("\u2122", "TM"),
        ("emoji \U0001f600", "emoji _"),
    ],
)
def test_fold_ascii(text, folded):
    assert hook.fold_ascii(text) == folded


@pytest.mark.parametrize(
    ("title", "safe"),
    [
        ('Install: Foo/Bar <x> | y? * "z" \\', "Install_ Foo_Bar _x_ _ y_ _ _z_ _"),
        ("  lots\tof\n white   space  ", "lots of white space"),
        ("ctrl\x01char", "ctrl_char"),
        ("R\u00e9sum\u00e9 \u20ac", "Resume EUR"),
    ],
)
def test_safe_title(title, safe):
    assert hook.safe_title(title) == safe


# --- rename auto-fix ------------------------------------------------------------


def plain_repo(tmp_path, files):
    """A folder (not a git repo) holding `files`; returns (root, file list)."""
    root = tmp_path / "plain"
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(bes(Path(rel).stem) if text is None else text, encoding="utf-8")
    return root, sorted(files)


def listing(root):
    """Every file under `root` (but .git), as sorted repo-relative paths."""
    return sorted(
        p.relative_to(root).as_posix()
        for p in Path(root).rglob("*")
        if p.is_file() and ".git" not in p.relative_to(root).parts
    )


def test_e803_check_reports_and_changes_nothing(tmp_path):
    root, files = plain_repo(tmp_path, {"Fixlets/A/0042- X.bes": None})
    found = messages(root, files=files, check=True)
    assert [(p, c) for p, c, m in found] == [("Fixlets/A/0042- X.bes", "E803")]
    assert "42- X.bes" in found[0][2]
    assert listing(root) == ["Fixlets/A/0042- X.bes"]


def test_e803_fix_strips_zero_padding(tmp_path):
    root, files = plain_repo(tmp_path, {"Fixlets/A/0042- X.bes": None})
    results = hook.check_repo(str(root), files, check=False)
    assert listing(root) == ["Fixlets/A/42- X.bes"]
    ((path, issues, fixed),) = results
    assert path == "Fixlets/A/0042- X.bes"
    assert issues == []
    assert [code for _l, code, _m in fixed] == ["E803"]


def test_e804_fix_folds_non_ascii(tmp_path):
    root, files = plain_repo(
        tmp_path, {"Fixlets/A/11903- Euro in name \u20ac only.bes": None}
    )
    assert run(root, files=files, check=False) == {
        "Fixlets/A/11903- Euro in name \u20ac only.bes": ["E804"]
    }
    assert listing(root) == ["Fixlets/A/11903- Euro in name EUR only.bes"]


def test_fixes_combine_into_one_rename(tmp_path):
    name = (
        "00011822- AAC Change the Currency Unit to \u20ac and the Weight Unit "
        "to kg in the Client Dashboard.bes"
    )
    root, files = plain_repo(tmp_path, {f"Fixlets/Fixlets/{name}": None})
    assert run(root, files=files, check=False) == {
        f"Fixlets/Fixlets/{name}": ["E803", "E804"]
    }
    assert listing(root) == [
        "Fixlets/Fixlets/11822- AAC Change the Currency Unit to EUR and the "
        "Weight Unit to kg in the Client Dashboard.bes"
    ]


def test_e805_shortens_to_id_and_title(tmp_path):
    long_name = "Fixlets/A/12- " + "n" * 60 + ".bes"
    root, files = plain_repo(
        tmp_path, {long_name: bes("Install: Widget/Pro \u2013 v2.0 for Windows")}
    )
    # 10 + len("Fixlets/A/12 ") 13 + len(".bes") 4 = 27, so 53 leaves 26
    results = hook.check_repo(
        str(root), files, prefix=SHORT_PREFIX, max_path=53, check=False
    )
    new = "Fixlets/A/12 Install_ Widget_Pro - v2.0.bes"
    assert listing(root) == [new]
    assert hook.server_path_length(SHORT_PREFIX, new) == 53
    ((_path, issues, fixed),) = results
    assert issues == [] and [c for _l, c, _m in fixed] == ["E805"]


def test_e805_cut_drops_trailing_space_dot_and_hyphen(tmp_path):
    # the cut lands right after "v2.-"; all of " .-" at the end goes
    root, files = plain_repo(
        tmp_path, {"Fixlets/A/12- " + "n" * 60 + ".bes": bes("Abc v2.- tail")}
    )
    # 10 + len("Fixlets/A/12 ") 13 + 4 = 27; limit 35 leaves 8: "Abc v2.-"
    hook.check_repo(str(root), files, prefix=SHORT_PREFIX, max_path=35, check=False)
    assert listing(root) == ["Fixlets/A/12 Abc v2.bes"]


def test_e805_exactly_at_the_limit(tmp_path):
    root, files = plain_repo(
        tmp_path, {"Fixlets/A/12- " + "n" * 60 + ".bes": bes("T" * 100)}
    )
    hook.check_repo(str(root), files, prefix=SHORT_PREFIX, max_path=50, check=False)
    (new,) = listing(root)
    assert hook.server_path_length(SHORT_PREFIX, new) == 50
    assert new == "Fixlets/A/12 " + "T" * 23 + ".bes"


def test_e805_title_falls_back_to_the_file_name(tmp_path):
    root, files = plain_repo(
        tmp_path, {"Fixlets/A/0012- Fallback name here " + "n" * 40 + ".bes": "not xml"}
    )
    hook.check_repo(str(root), files, prefix=SHORT_PREFIX, max_path=50, check=False)
    assert listing(root) == ["Fixlets/A/12 Fallback name here nnnn.bes"]


def test_e805_keeps_the_extension_case(tmp_path):
    root, files = plain_repo(
        tmp_path, {"Fixlets/A/12- " + "n" * 60 + ".BES": bes("Title")}
    )
    hook.check_repo(str(root), files, prefix=SHORT_PREFIX, max_path=50, check=False)
    assert listing(root) == ["Fixlets/A/12 Title.BES"]


def test_names_that_fit_are_left_alone(tmp_path):
    # its title differs from its name, but it fits; the long one is the control
    root, files = plain_repo(
        tmp_path,
        {
            "Fixlets/A/1- short.bes": bes("A completely different title"),
            "Fixlets/A/2- " + "n" * 60 + ".bes": bes("Two"),
        },
    )
    hook.check_repo(str(root), files, prefix=SHORT_PREFIX, max_path=50, check=False)
    assert listing(root) == ["Fixlets/A/1- short.bes", "Fixlets/A/2 Two.bes"]


def test_unfixable_and_ungathered_files_are_not_renamed(tmp_path):
    root, files = plain_repo(
        tmp_path,
        {
            "Archive/0042- X.bes": None,  # W800: not gathered
            "Fixlets/A/Name \u20ac.bes": None,  # E800: no ID
            "Fixlets/" + "f" * 40 + "/7- a.bes": None,  # E802: folders too long
            "Fixlets/A/0009- control.bes": None,
        },
    )
    found = run(root, files=files, prefix=SHORT_PREFIX, max_path=55, check=False)
    assert found["Fixlets/" + "f" * 40 + "/7- a.bes"] == ["E802"]
    assert "E803" not in found.get("Archive/0042- X.bes", [])
    assert "E804" not in found.get("Fixlets/A/Name \u20ac.bes", [])
    assert listing(root) == sorted(
        [
            "Archive/0042- X.bes",
            "Fixlets/A/Name \u20ac.bes",
            "Fixlets/" + "f" * 40 + "/7- a.bes",
            "Fixlets/A/9- control.bes",
        ]
    )


def test_e806_collision_with_a_tracked_file_ignoring_case(tmp_path):
    root, files = plain_repo(
        tmp_path,
        {
            "Fixlets/A/0042- X.bes": None,
            "Fixlets/B/42- y.bes": None,
            "Fixlets/A/42- x.bes": None,
        },
    )
    found = messages(root, files=files, check=False)
    e806 = [(p, m) for p, c, m in found if c == "E806"]
    assert [p for p, m in e806] == ["Fixlets/A/0042- X.bes"]
    assert "Fixlets/A/42- x.bes" in e806[0][1]
    assert "Fixlets/A/0042- X.bes" in listing(root)  # left alone


def test_e806_collision_between_two_planned_renames(tmp_path):
    root, files = plain_repo(
        tmp_path, {"Fixlets/A/007- X.bes": None, "Fixlets/A/07- X.bes": None}
    )
    found = run(root, files=files, check=True)
    assert found["Fixlets/A/007- X.bes"] == ["E801", "E803"]
    assert found["Fixlets/A/07- X.bes"] == ["E801", "E806"]


def test_e806_never_overwrites_an_untracked_file(tmp_path):
    root, files = plain_repo(tmp_path, {"Fixlets/A/0042- X.bes": None})
    (root / "Fixlets/A/42- X.bes").write_text("untracked", encoding="utf-8")
    found = run(root, files=files, check=False)
    assert found == {"Fixlets/A/0042- X.bes": ["E806"]}
    assert (root / "Fixlets/A/42- X.bes").read_text(encoding="utf-8") == "untracked"
    assert (root / "Fixlets/A/0042- X.bes").is_file()


def test_disable_a_fix_code_skips_that_fix(tmp_path):
    root, files = plain_repo(
        tmp_path, {"Fixlets/A/0042- X \u20ac.bes": None, "Fixlets/A/0043- Y.bes": None}
    )
    hook.check_repo(str(root), files, disabled={"E803"}, check=False)
    assert listing(root) == ["Fixlets/A/0042- X EUR.bes", "Fixlets/A/0043- Y.bes"]


def test_disable_e805_skips_the_length_fix(tmp_path):
    # the other fixes still run: 0013- y.bes is the control
    root, files = plain_repo(
        tmp_path,
        {"Fixlets/A/12- " + "n" * 60 + ".bes": None, "Fixlets/A/0013- y.bes": None},
    )
    hook.check_repo(
        str(root),
        files,
        prefix=SHORT_PREFIX,
        max_path=50,
        disabled={"E805"},
        check=False,
    )
    assert listing(root) == [
        "Fixlets/A/12- " + "n" * 60 + ".bes",
        "Fixlets/A/13- y.bes",
    ]


def test_fix_is_idempotent(tmp_path):
    root, files = plain_repo(
        tmp_path, {"Fixlets/A/0012- \u20ac " + "n" * 60 + ".bes": bes("T\u00eftle")}
    )
    hook.check_repo(str(root), files, prefix=SHORT_PREFIX, max_path=50, check=False)
    assert listing(root) == ["Fixlets/A/12 Title.bes"]
    assert run(root, files=listing(root), prefix=SHORT_PREFIX, max_path=50) == {}


def test_main_renames_with_git_mv(tmp_path, monkeypatch, capsys):
    repo = make_repo(
        tmp_path, {"Fixlets/A/0042- X.bes": None, "Fixlets/A/1- ok.bes": None}
    )
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    monkeypatch.chdir(repo)
    assert hook.main([]) == 1
    out = capsys.readouterr().out
    assert "[E803] auto-fixed" in out
    assert "review" in out.lower()
    # staged as a rename, with nothing left unstaged
    staged = git(repo, "diff", "--cached", "--name-status", "-M", "-z").split("\0")
    assert staged[:3] == ["R100", "Fixlets/A/0042- X.bes", "Fixlets/A/42- X.bes"]
    assert git(repo, "diff", "--name-only") == ""
    assert listing(repo) == ["Fixlets/A/1- ok.bes", "Fixlets/A/42- X.bes"]
    # nothing left to do
    assert hook.main([]) == 0


def test_main_git_mv_keeps_unstaged_edits(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, {"Fixlets/A/0042- X.bes": None})
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    (repo / "Fixlets/A/0042- X.bes").write_text(bes("edited"), encoding="utf-8")
    monkeypatch.chdir(repo)
    assert hook.main([]) == 1
    assert "edited" in (repo / "Fixlets/A/42- X.bes").read_text(encoding="utf-8")


def test_main_check_renames_nothing(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, {"Fixlets/A/0042- X.bes": None})
    monkeypatch.chdir(repo)
    assert hook.main(["--check"]) == 1
    assert "[E803]" in capsys.readouterr().out
    assert listing(repo) == ["Fixlets/A/0042- X.bes"]
    staged = git(repo, "diff", "--cached", "--name-status", "-z")
    assert staged == "A\0Fixlets/A/0042- X.bes\0"


# --- renames inside a pre-commit run ------------------------------------------


def write_patch(home, pid, repo, edits):
    """Write a pre-commit-style stash patch of `edits` {path: appended line}."""
    for rel, line in edits.items():
        with open(Path(repo) / rel, "a", encoding="utf-8") as handle:
            handle.write(line)
    patch = git(repo, "diff", "--binary", "--no-color", "--no-ext-diff")
    git(repo, "checkout", "--", ".")
    home.mkdir(parents=True, exist_ok=True)
    (home / f"patch1792519987-{pid}").write_text(patch, encoding="utf-8")


def test_pre_commit_stashed_paths(tmp_path):
    repo = make_repo(
        tmp_path, {"Fixlets/A/0042- X.bes": None, "Fixlets/A/1- \u20ac.bes": None}
    )
    home = tmp_path / "pc-home"
    write_patch(home, 4242, repo, {"Fixlets/A/1- \u20ac.bes": "edit\n"})
    environ = {"PRE_COMMIT_HOME": str(home)}
    assert hook.pre_commit_stashed_paths(str(repo), 4242, environ) == {
        "Fixlets/A/1- \u20ac.bes"
    }
    # another process's patch is not ours
    assert hook.pre_commit_stashed_paths(str(repo), 4243, environ) == set()


def test_pre_commit_stashed_paths_cache_locations(tmp_path):
    repo = make_repo(tmp_path, {"Fixlets/A/1- a.bes": None})
    write_patch(tmp_path / "xdg" / "pre-commit", 7, repo, {"Fixlets/A/1- a.bes": "e\n"})
    found = hook.pre_commit_stashed_paths(
        str(repo), 7, {"XDG_CACHE_HOME": str(tmp_path / "xdg")}
    )
    assert found == {"Fixlets/A/1- a.bes"}
    write_patch(
        tmp_path / ".cache" / "pre-commit", 8, repo, {"Fixlets/A/1- a.bes": "e\n"}
    )
    found = hook.pre_commit_stashed_paths(str(repo), 8, {"HOME": str(tmp_path)})
    assert found == {"Fixlets/A/1- a.bes"}


def test_held_files_are_not_renamed(tmp_path):
    root, files = plain_repo(
        tmp_path, {"Fixlets/A/0042- X.bes": None, "Fixlets/A/0043- Y.bes": None}
    )
    found = messages(root, files=files, held={"Fixlets/A/0042- X.bes"})
    assert [(p, c) for p, c, m in found] == [
        ("Fixlets/A/0042- X.bes", "E806"),
        ("Fixlets/A/0043- Y.bes", "E803"),
    ]
    assert "unstaged" in found[0][2]
    assert listing(root) == ["Fixlets/A/0042- X.bes", "Fixlets/A/43- Y.bes"]


def test_main_renames_an_untracked_listed_file_without_git(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, {"Fixlets/A/1- ok.bes": None})
    (repo / "Fixlets/A/0042- X.bes").write_text(bes(), encoding="utf-8")
    monkeypatch.chdir(repo)

    def lister(_root):
        return ["Fixlets/A/0042- X.bes", "Fixlets/A/1- ok.bes"]

    assert hook.main([], list_files=lister) == 1
    assert listing(repo) == ["Fixlets/A/1- ok.bes", "Fixlets/A/42- X.bes"]
    # still untracked: git mv would have refused it
    assert "Fixlets/A/42- X.bes" not in git(repo, "ls-files")


PRE_COMMIT = shutil.which("pre-commit")


def pre_commit_repo(tmp_path):
    """A committed site repo whose pre-commit config runs this hook."""
    module = Path(hook.__file__).resolve()
    repo = make_repo(
        tmp_path,
        {
            ".pre-commit-config.yaml": (
                "repos:\n  - repo: local\n    hooks:\n      - id: layout\n"
                "        name: layout\n"
                f"        entry: {json.dumps(shlex.join([sys.executable, str(module)]))}\n"
                "        language: system\n        pass_filenames: false\n"
                "        always_run: true\n"
            ),
            "Fixlets/A/0042- X.bes": None,
            "Fixlets/A/1- ok.bes": None,
        },
    )
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    return repo


def pre_commit_run(repo, tmp_path):
    env = dict(os.environ, PRE_COMMIT_HOME=str(tmp_path / "pc-home"))
    return subprocess.run(
        [PRE_COMMIT, "run"], cwd=repo, env=env, capture_output=True, text=True
    )


@pytest.mark.skipif(PRE_COMMIT is None, reason="pre-commit is not installed")
def test_pre_commit_run_stages_the_rename(tmp_path):
    repo = pre_commit_repo(tmp_path)
    with open(repo / "Fixlets/A/0042- X.bes", "a", encoding="utf-8") as handle:
        handle.write("staged\n")
    git(repo, "add", "-A")
    result = pre_commit_run(repo, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "[E803] auto-fixed" in result.stdout
    staged = git(repo, "diff", "--cached", "--name-status", "-M", "-z").split("\0")
    assert staged[0].startswith("R")
    assert staged[1:3] == ["Fixlets/A/0042- X.bes", "Fixlets/A/42- X.bes"]
    assert pre_commit_run(repo, tmp_path).returncode == 0


@pytest.mark.skipif(PRE_COMMIT is None, reason="pre-commit is not installed")
def test_pre_commit_run_leaves_a_file_with_unstaged_edits(tmp_path):
    # pre-commit stashes the unstaged edit and must re-apply it to the same
    # path afterwards; renaming that file would make it fail and crash
    repo = pre_commit_repo(tmp_path)
    path = repo / "Fixlets/A/0042- X.bes"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("staged\n")
    git(repo, "add", "-A")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("unstaged\n")
    result = pre_commit_run(repo, tmp_path)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "[E806]" in output
    assert "unexpected error" not in output.lower()
    assert path.read_text(encoding="utf-8").endswith("staged\nunstaged\n")
    assert (
        git(repo, "diff", "--cached", "--name-only", "-z") == "Fixlets/A/0042- X.bes\0"
    )


# --- commits that use a temporary index ---------------------------------------


def hook_env(tmp_path):
    """Environment for running pre-commit and git commit in a test repo."""
    return dict(
        os.environ,
        PRE_COMMIT_HOME=str(tmp_path / "pc-home"),
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@t",
    )


def installed_hook_repo(tmp_path):
    """Pre_commit_repo() with the hook installed as .git/hooks/pre-commit."""
    repo = pre_commit_repo(tmp_path)
    subprocess.run(
        [PRE_COMMIT, "install"],
        cwd=repo,
        env=hook_env(tmp_path),
        check=True,
        capture_output=True,
    )
    return repo


def git_commit(repo, tmp_path, *args):
    """Run `git commit` (and so the installed hook) in `repo`."""
    return subprocess.run(
        ["git", "commit", *args],
        cwd=repo,
        env=hook_env(tmp_path),
        capture_output=True,
        text=True,
    )


def status(repo):
    """`git status --porcelain -z` entries as a sorted list."""
    out = git(repo, "status", "--porcelain", "-z", "--untracked-files=all")
    return sorted(entry for entry in out.split("\0") if entry)


@pytest.mark.skipif(PRE_COMMIT is None, reason="pre-commit is not installed")
@pytest.mark.parametrize(
    "commit_args",
    [["-a", "-m", "m"], ["-m", "m", "--", "Fixlets/A/0042- X.bes"]],
    ids=["commit-a", "commit-pathspec"],
)
def test_temporary_index_commit_renames_nothing(tmp_path, commit_args):
    # git commit -a and git commit <paths> give the hook a temporary index,
    # which git discards when the hook fails: a git mv there would be lost,
    # leaving the old name deleted and the new one untracked
    repo = installed_hook_repo(tmp_path)
    with open(repo / "Fixlets/A/0042- X.bes", "a", encoding="utf-8") as handle:
        handle.write("edit\n")
    result = git_commit(repo, tmp_path, *commit_args)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "[E806]" in output and "temporary index" in output
    assert "auto-fixed" not in output
    assert listing(repo) == [
        ".pre-commit-config.yaml",
        "Fixlets/A/0042- X.bes",
        "Fixlets/A/1- ok.bes",
    ]
    assert status(repo) == [" M Fixlets/A/0042- X.bes"]
    # a plain commit after git add renames and stages it as before
    git(repo, "add", "-A")
    result = git_commit(repo, tmp_path, "-m", "m")
    assert result.returncode != 0
    assert "[E803] auto-fixed" in result.stdout + result.stderr
    # porcelain -z gives a rename as "R  <new>" then "<old>"; status() sorts
    assert status(repo) == ["Fixlets/A/0042- X.bes", "R  Fixlets/A/42- X.bes"]
    assert git_commit(repo, tmp_path, "-m", "m").returncode == 0


def test_uses_real_index(tmp_path):
    repo = make_repo(tmp_path, {"Fixlets/A/1- a.bes": None})
    git_dir = os.path.join(str(repo), ".git")
    assert hook.uses_real_index(str(repo), {})
    assert hook.uses_real_index(
        str(repo), {"GIT_INDEX_FILE": os.path.join(git_dir, "index")}
    )
    # relative to the repo root, as git may set it
    assert hook.uses_real_index(str(repo), {"GIT_INDEX_FILE": ".git/index"})
    assert not hook.uses_real_index(
        str(repo), {"GIT_INDEX_FILE": os.path.join(git_dir, "index.lock")}
    )
    assert not hook.uses_real_index(
        str(repo), {"GIT_INDEX_FILE": os.path.join(git_dir, "next-index-12.lock")}
    )


def test_temporary_index_reported_under_e806(tmp_path):
    root, files = plain_repo(tmp_path, {"Fixlets/A/0042- X.bes": None})
    found = messages(root, files=files, temporary_index=True)
    assert [(p, c) for p, c, m in found] == [("Fixlets/A/0042- X.bes", "E806")]
    assert "42- X.bes" in found[0][2] and "git add" in found[0][2]
    assert listing(root) == ["Fixlets/A/0042- X.bes"]
    # --check reports the fix as usual: nothing is renamed either way
    found = messages(root, files=files, temporary_index=True, check=True)
    assert [c for p, c, m in found] == ["E803"]


# --- names that are not UTF-8 -------------------------------------------------


def add_raw_name(repo, raw_path, text="x"):
    """Stage `text` under the bytes path `raw_path`, in the index only.

    macOS refuses such names on disk, so the work tree does not have it.
    """
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=repo,
        input=text.encode(),
        check=True,
        capture_output=True,
    ).stdout.strip()
    subprocess.run(
        [
            b"git",
            b"update-index",
            b"--add",
            b"--cacheinfo",
            b"100644," + blob + b"," + raw_path,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_non_utf8_name_is_reported_not_a_crash(tmp_path, monkeypatch, capfd):
    repo = make_repo(tmp_path, {"Fixlets/A/1- ok.bes": None})
    add_raw_name(repo, b"Fixlets/A/2- calf\xe9.bes", bes())
    add_raw_name(repo, b"OtherFiles/n\xe9e.txt")
    monkeypatch.chdir(repo)
    assert hook.main(["--check"]) == 1
    out = capfd.readouterr().out
    assert "[E804]" in out and "would be renamed to 2- calf_.bes" in out
    assert "\\udce9" in out  # the undecodable byte, shown escaped
    # fix mode: the file is not on disk here, so git mv fails: E806, no crash
    assert hook.main([]) == 1
    assert "[E806]" in capfd.readouterr().out


def test_server_path_length_of_an_undecodable_name():
    assert hook.server_path_length("", "a\udce9.bes") == 6


# --- decomposed accents and format characters ---------------------------------


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("R\u00e9sum\u00e9", "Resume"),
        ("\u00c5ngstr\u00f6m \u00d1and\u00fa", "Angstrom Nandu"),
        ("\u20ac\u00e9", "EURe"),
    ],
)
def test_fold_ascii_decomposed_input(text, folded):
    # names committed from macOS, or Titles pasted with combining marks, are
    # often NFD: the accent is a separate character after its letter
    decomposed = unicodedata.normalize("NFD", text)
    assert decomposed != text or text.startswith("\u20ac")
    assert hook.fold_ascii(decomposed) == folded
    assert hook.safe_title(decomposed) == folded


def test_fold_ascii_combining_mark_without_a_precomposed_form():
    # q + combining dot above has no single-character form, even in NFC
    assert hook.fold_ascii("q\u0307x") == "qx"


@pytest.mark.parametrize(
    ("text", "folded"),
    [("a\u200bb", "ab"), ("\ufeffbom", "bom"), ("x\u200dy", "xy")],
)
def test_fold_ascii_drops_format_characters(text, folded):
    # zero-width space, BOM and zero-width joiner are invisible (category Cf)
    assert hook.fold_ascii(text) == folded


def test_disable_e805_still_reports_the_long_path(tmp_path, monkeypatch, capsys):
    # turning off the rename must not turn off the path-length check
    long_name = "Fixlets/A/42- " + "L" * 140 + ".bes"
    repo = make_repo(tmp_path, {long_name: None})
    found = messages(repo, check=True, disabled={"E805"})
    assert [(p, c) for p, c, m in found] == [(long_name, "E802")]
    assert "E805" in found[0][2]  # says the fix is turned off
    monkeypatch.chdir(repo)
    assert hook.main(["--check", "--disable", "E805"]) == 1
    assert hook.main(["--disable", "E805"]) == 1
    assert listing(repo) == [long_name]


# --- finding pre-commit's stash through a launcher ----------------------------


def test_stash_found_through_a_launcher_process(tmp_path, monkeypatch):
    # on Windows a console script is an .exe launcher that starts python.exe
    # as its child, so pre-commit is the hook's grandparent, not its parent
    repo = make_repo(tmp_path, {"Fixlets/A/1- a.bes": None})
    home = tmp_path / "pc-home"
    write_patch(home, 200, repo, {"Fixlets/A/1- a.bes": "e\n"})
    chain = {100: 200, 200: 300, 300: 400}
    monkeypatch.setattr(hook, "_parent_pid", chain.get)
    monkeypatch.setattr(hook, "_is_windows", lambda: True)
    environ = {"PRE_COMMIT_HOME": str(home)}
    assert hook.pre_commit_stashed_paths(str(repo), 100, environ) == {
        "Fixlets/A/1- a.bes"
    }
    # three generations at most: pre-commit is never further away than that
    assert hook.pre_commit_stashed_paths(str(repo), 50, environ) == set()
    chain[50] = 100
    assert hook.pre_commit_stashed_paths(str(repo), 50, environ) == {
        "Fixlets/A/1- a.bes"
    }
    chain[25] = 50
    assert hook.pre_commit_stashed_paths(str(repo), 25, environ) == set()


@pytest.mark.skipif(os.name == "nt", reason="uses ps")
def test_parent_pid():
    assert hook._parent_pid(os.getpid()) == os.getppid()
    assert hook._parent_pid(2**22 + 12345) is None  # no such process


# --- review nits --------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("./Content", "Content"),
        ("Content/./", "Content"),
        (".\\Content\\", "Content"),
        ("Content/Sub/../Fixlets", "Content/Fixlets"),
        (".", "Fixlets"),  # names no folder, so the default stands
    ],
)
def test_site_config_folder_is_normalized(tmp_path, value, expected):
    repo = make_repo(
        tmp_path,
        {
            "siteConfig.xml": f"<SiteConfig><BesFileDir>{value}</BesFileDir></SiteConfig>"
        },
    )
    config = hook.read_site_config(str(repo), "", hook.git_ls_files(repo))
    assert config.bes_dir == expected


def test_site_config_dot_slash_folder_has_no_false_warnings(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "siteConfig.xml": "<SiteConfig><BesFileDir>./Content</BesFileDir></SiteConfig>",
            "Content/A/42- x.bes": None,
        },
    )
    assert run(repo, check=True) == {}


@pytest.mark.parametrize(
    ("url", "name"),
    [
        ("C:\\repos\\my-site", "my-site"),
        ("\\\\server\\share\\my-site.git", "my-site"),
        ("https://h/o/My-Site.GIT", "My-Site"),
    ],
)
def test_repo_name_from_local_and_windows_remotes(url, name):
    assert hook.repo_name_from_url(url) == name


def test_e805_title_without_letters_or_digits_falls_back(tmp_path):
    root, files = plain_repo(
        tmp_path,
        {"Fixlets/A/0012- Fallback name here " + "n" * 40 + ".bes": bes("???***")},
    )
    hook.check_repo(str(root), files, prefix=SHORT_PREFIX, max_path=50, check=False)
    assert listing(root) == ["Fixlets/A/12 Fallback name here nnnn.bes"]


def test_held_message_names_who_could_not_restore(tmp_path):
    root, files = plain_repo(tmp_path, {"Fixlets/A/0042- X.bes": None})
    found = messages(root, files=files, held={"Fixlets/A/0042- X.bes"})
    assert "pre-commit could not" in found[0][2]


def test_server_prefix_uses_slashes_for_a_posix_server_root():
    prefix = hook.server_prefix("/var/opt/BESServer/", "r", "main")
    assert (
        prefix
        == "/var/opt/BESServer/RepositorySiteGather/Sites/r_main_00000000/Source/"
    )
    # every separator is one character either way, so lengths do not change
    windows = hook.server_prefix("C:\\BESServer", "r", "main")
    assert hook.server_path_length(prefix, "a/b.bes") - len(prefix) == (
        hook.server_path_length(windows, "a/b.bes") - len(windows)
    )


# --- names valid on a RHEL server too -----------------------------------------

CJK = "\u6587"  # 3 bytes in UTF-8


def test_e808_file_name_over_255_bytes(tmp_path):
    # 100 CJK characters: 104 characters, fine on Windows, 304 bytes on Linux
    long_name = "NonClientFiles/" + CJK * 100 + ".txt"
    ok_name = "NonClientFiles/" + CJK * 83 + "ab.txt"  # 249 + 6 = 255 bytes
    repo = make_repo(tmp_path, {long_name: "x", ok_name: "x"})
    found = messages(repo, check=True, prefix="", max_path=4000)
    assert [(p, c) for p, c, m in found] == [(long_name, "E808")]
    assert "304" in found[0][2] and "255" in found[0][2]


def test_e808_folder_name_over_255_bytes_reported_once(tmp_path):
    folder = "Fixlets/" + CJK * 90  # 270 bytes
    repo = make_repo(tmp_path, {f"{folder}/1- a.bes": None, f"{folder}/2- b.bes": None})
    found = messages(repo, check=True, prefix="", max_path=4000)
    assert [(p, c) for p, c, m in found] == [(folder, "E808")]
    assert "folder" in found[0][2]


def test_e805_fixes_a_bes_name_over_255_bytes(tmp_path):
    # the path is fine (no Windows limit hit); only the name is too long:
    # 94 characters (macOS limits characters, so the file can exist here)
    # but 266 bytes. E804 is off, or folding the CJK to _ would fix it first.
    long_name = "Fixlets/A/12- " + CJK * 86 + ".bes"
    root, files = plain_repo(tmp_path, {long_name: bes("T" * 300)})
    options = {"prefix": "", "max_path": 4000, "disabled": {"E804"}}
    found = run(root, files=files, check=True, **options)
    assert found == {long_name: ["E805"]}
    hook.check_repo(str(root), files, check=False, **options)
    (new,) = listing(root)
    assert new == "Fixlets/A/12 " + "T" * 248 + ".bes"
    assert len(new.rsplit("/", 1)[-1].encode()) == 255


def test_e808_bes_name_the_rename_cannot_fix(tmp_path):
    no_id = "Fixlets/A/" + CJK * 86 + ".bes"  # 262 bytes
    with_id = "Fixlets/A/12- " + CJK * 86 + ".bes"  # 266 bytes
    root, files = plain_repo(tmp_path, {no_id: None, with_id: None})
    found = run(root, files=files, prefix="", max_path=4000, disabled={"E804", "E805"})
    assert found == {no_id: ["E800", "E808"], with_id: ["E808"]}
    assert listing(root) == sorted([no_id, with_id])


def test_w808_case_only_differences(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "siteConfig.xml": (
                "<SiteConfig><NonClientFilesDir>ServerFiles</NonClientFilesDir>"
                "</SiteConfig>"
            ),
            "fixlets/A/1- a.bes": None,  # BesFileDir is Fixlets
            "fixlets/A/2- b.bes": None,
            "fixlets/A/Digest.xml": "<D/>",
            "fixlets/B/3- c.BES": None,
            "serverfiles/x.ojo": "x",
            "OtherFiles/y.txt": "x",  # exact: the control
        },
    )
    found = messages(repo, check=True)
    assert sorted((p, c) for p, c, m in found) == [
        ("fixlets", "W808"),
        ("fixlets/A/Digest.xml", "W808"),
        ("fixlets/B/3- c.BES", "W808"),
        ("serverfiles", "W808"),
    ]
    by_path = {p: m for p, c, m in found}
    assert "Fixlets" in by_path["fixlets"]
    assert "ServerFiles" in by_path["serverfiles"]
    assert "digest.xml" in by_path["fixlets/A/Digest.xml"]


def test_w808_upper_case_bes_name_without_an_id(tmp_path):
    repo = make_repo(tmp_path, {"Fixlets/A/Name.BES": None})
    assert run(repo, check=True) == {"Fixlets/A/Name.BES": ["E800", "W808"]}


def test_stash_lookup_is_the_parent_only_off_windows(tmp_path, monkeypatch):
    # pre-commit never deletes its patch files, and on Linux and macOS the
    # grandparent is git or a shell: an old patch whose pid matches one of
    # those would hold a file with no unstaged changes. Only Windows has a
    # launcher between pre-commit and the hook.
    repo = make_repo(tmp_path, {"Fixlets/A/1- a.bes": None, "Fixlets/A/2- b.bes": None})
    home = tmp_path / "pc-home"
    write_patch(home, 200, repo, {"Fixlets/A/1- a.bes": "e\n"})  # grandparent
    write_patch(home, 100, repo, {"Fixlets/A/2- b.bes": "e\n"})  # parent
    asked = []

    def parent_of(pid):
        asked.append(pid)
        return {100: 200, 200: 300}.get(pid)

    monkeypatch.setattr(hook, "_parent_pid", parent_of)
    monkeypatch.setattr(hook, "_is_windows", lambda: False)
    environ = {"PRE_COMMIT_HOME": str(home)}
    assert hook.pre_commit_stashed_paths(str(repo), 100, environ) == {
        "Fixlets/A/2- b.bes"
    }
    assert asked == []  # no process lookup at all
    monkeypatch.setattr(hook, "_is_windows", lambda: True)
    assert hook.pre_commit_stashed_paths(str(repo), 100, environ) == {
        "Fixlets/A/1- a.bes",
        "Fixlets/A/2- b.bes",
    }
