#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_siterepo_validate_layout.py.

The hook checks a Git External Custom Site ("repository site") repo as a
whole: its file list comes from `git ls-files`, so most tests build a small
git repo in tmp_path. Covered here: the server path prefix (pinned to the
path confirmed on a real server), the repo-name default, the file list,
siteConfig.xml folder names, the naming and duplicate-ID errors, the layout
warnings, path length, the rename auto-fix, --check, and main()'s exit codes.
"""

import os
import subprocess
from pathlib import Path

import pytest

from pre_commit_bigfix import bes_siterepo_validate_layout as hook

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


@pytest.mark.parametrize(
    "name", ["Name.bes", "42_Name.bes", "42.bes", "x42- Name.bes", "Name.BES"]
)
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
    assert "Archive" not in str(messages(repo, check=True))


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
