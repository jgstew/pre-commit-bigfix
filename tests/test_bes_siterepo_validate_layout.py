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


def test_w805_long_non_bes_path(tmp_path):
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
        ("OtherFiles/" + "y" * 26 + ".txt", "W805")
    ]
    message = found[0][2]
    assert "51" in message and "50" in message
    assert "rename" in message.lower()  # says why it is not renamed


def test_w805_counts_the_prefix(tmp_path):
    # no .bes file, which would be over the limit too
    repo = make_repo(tmp_path, {"OtherFiles/x.txt": "x"})
    # 16 characters of path; 50 - 16 = 34 left for the prefix
    assert run(repo, check=True, prefix="P" * 34, max_path=50) == {}
    assert run(repo, check=True, prefix="P" * 35, max_path=50) == {
        "OtherFiles/x.txt": ["W805"]
    }


def test_w805_bes_outside_the_bes_folder(tmp_path):
    repo = make_repo(
        tmp_path, {"Fixlets/A/1- a.bes": None, "Archive/" + "z" * 40 + ".bes": None}
    )
    found = run(repo, check=True, prefix=SHORT_PREFIX, max_path=50)
    assert found == {"Archive/" + "z" * 40 + ".bes": ["W800", "W805"]}


def test_w805_files_outside_every_site_root(tmp_path):
    # the server clones the whole repo, so every tracked file counts
    repo = make_repo(
        tmp_path,
        {"Sites/A/Fixlets/X/1- a.bes": None, "tools/" + "t" * 40 + ".py": "x"},
    )
    found = run(repo, ["Sites/A"], check=True, prefix=SHORT_PREFIX, max_path=50)
    assert found == {"tools/" + "t" * 40 + ".py": ["W805"]}


def test_path_measured_from_the_repo_root_not_the_site_root(tmp_path):
    # Sites/A/OtherFiles/abc.txt is 26 characters; OtherFiles/abc.txt only 18
    repo = make_repo(
        tmp_path,
        {"Sites/A/Fixlets/X/1- a.bes": None, "Sites/A/OtherFiles/abc.txt": "x"},
    )
    assert run(repo, ["Sites/A"], check=True, prefix="", max_path=26) == {}
    found = run(repo, ["Sites/A"], check=True, prefix="", max_path=25)
    assert found["Sites/A/OtherFiles/abc.txt"] == ["W805"]


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
    assert hook.main(["--check"]) == 0  # W805 is a warning
    out = capsys.readouterr().out
    assert over in out and "[W805]" in out
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
        assert "[W805]" in capsys.readouterr().out
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
