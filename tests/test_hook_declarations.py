#!/usr/bin/env python3
"""Tests that the hook declarations stay consistent with the package.

Hook ids, console-script names, and module paths are three separate places
that must agree, and nothing else in the suite notices when a rename updates
only some of them. These checks tie them together:

    - every hook in .pre-commit-hooks.yaml runs a console_script that
      setup.cfg actually declares
    - every `python <path>` local hook in .pre-commit-config.yaml points at a
      file that exists
    - the removed `validate-bes` and `check-bes-conventions` aliases stay
      removed, as hook ids and as console scripts
"""

import configparser
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")  # ships with pre-commit; skip if absent

REPO = Path(__file__).resolve().parent.parent
HOOKS_FILE = REPO / ".pre-commit-hooks.yaml"
CONFIG_FILE = REPO / ".pre-commit-config.yaml"
SETUP_CFG = REPO / "setup.cfg"

# pre-rename hook ids, removed after v1.13.0: {old id: current id}
REMOVED_ALIASES = {
    "validate-bes": "bes-schema-validate",
    "check-bes-conventions": "bes-conventions-check",
}


def load_hooks():
    """Return the declared hooks as {id: hook dict}."""
    hooks = yaml.safe_load(HOOKS_FILE.read_text(encoding="utf-8"))
    return {hook["id"]: hook for hook in hooks}


def console_scripts():
    """Return the console_scripts declared in setup.cfg as {name: target}."""
    parser = configparser.ConfigParser()
    parser.read(SETUP_CFG, encoding="utf-8")
    raw = parser["options.entry_points"]["console_scripts"]
    scripts = {}
    for line in raw.splitlines():
        if "=" in line:
            name, _, target = line.partition("=")
            scripts[name.strip()] = target.strip()
    return scripts


def test_hook_ids_are_unique():
    hooks = yaml.safe_load(HOOKS_FILE.read_text(encoding="utf-8"))
    ids = [hook["id"] for hook in hooks]
    assert len(ids) == len(set(ids))


def test_every_hook_entry_is_a_declared_console_script():
    scripts = console_scripts()
    for hook_id, hook in load_hooks().items():
        command = hook["entry"].split()[0]
        assert command in scripts, f"hook {hook_id} entry {command!r} is not declared"


def test_every_console_script_target_module_exists():
    for name, target in console_scripts().items():
        module, _, function = target.partition(":")
        path = REPO / (module.replace(".", "/") + ".py")
        assert path.is_file(), f"console script {name} points at missing {path}"
        assert function == "main"


def test_local_hook_script_paths_exist():
    config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    checked = 0
    for repo in config["repos"]:
        if repo.get("repo") != "local":
            continue
        for hook in repo["hooks"]:
            match = re.match(r"python\s+(\S+\.py)$", hook["entry"])
            if match is None:
                continue
            checked += 1
            path = REPO / match.group(1)
            assert path.is_file(), f"local hook {hook['id']} points at missing {path}"
    assert checked >= 3  # the three local python hooks


@pytest.mark.parametrize("old_id", sorted(REMOVED_ALIASES))
def test_removed_alias_is_not_declared(old_id):
    """The deprecated aliases are gone: a config using one gets pre-commit's error."""
    assert old_id not in load_hooks()
    assert REMOVED_ALIASES[old_id] in load_hooks()
    assert old_id not in console_scripts()


@pytest.mark.parametrize(
    ("path", "matched"),
    [
        ("Sites/Foo/siteConfig.xml", True),
        ("Sites/Foo/site.xml", True),
        ("Fixlets/A/digest.xml", True),
        ("siteConfig.xml", True),
        ("Signatures/a b-1.0-12.xml", True),
        ("Sites/X/Signatures/y.xml", True),
        ("x.bes", True),
        ("x.ojo", True),
        ("Signatures/sub/x.xml", False),
        ("Sites/broken_site.xml", False),
        ("mysite.xml", False),
        ("pom.xml", False),
        ("site.xml.bak", False),
        ("SiteConfig.xml", False),  # case-sensitive, like the documented names
    ],
)
def test_bes_schema_validate_files_pattern(path, matched):
    """Match `files` the way pre-commit does: re.search on the repo path."""
    pattern = load_hooks()["bes-schema-validate"]["files"]
    assert bool(re.search(pattern, path)) is matched


def test_bes_siterepo_validate_layout_checks_the_whole_repo():
    """The layout hook must check the whole repo on every commit.

    It reads `git ls-files` itself, so pre-commit must not pass file names,
    and it must run even when no staged file matches: deleting a file can
    leave a site without content, say.
    """
    hook = load_hooks()["bes-siterepo-validate-layout"]
    assert hook["entry"] == "bes-siterepo-validate-layout"
    assert hook["pass_filenames"] is False
    assert hook["always_run"] is True
    assert console_scripts()["bes-siterepo-validate-layout"] == (
        "pre_commit_bigfix.bes_siterepo_validate_layout:main"
    )
