#!/usr/bin/env python3
"""Tests that the hook declarations stay consistent with the package.

Hook ids, console-script names, and module paths are three separate places
that must agree, and nothing else in the suite notices when a rename updates
only some of them. These checks tie them together:

    - every hook in .pre-commit-hooks.yaml runs a console_script that
      setup.cfg actually declares
    - every `python <path>` local hook in .pre-commit-config.yaml points at a
      file that exists
    - the deprecated `validate-bes` id is still declared, and is a true alias:
      same entry and same file matching as `bes-schema-validate`

The alias check is what keeps existing user configs working across the rename;
without it, dropping the old id would be a silent breaking change.
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

# hook ids kept only so pre-rename configs keep working: {old id: current id}
DEPRECATED_ALIASES = {
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


@pytest.mark.parametrize(("old_id", "new_id"), sorted(DEPRECATED_ALIASES.items()))
def test_deprecated_alias_is_declared_and_thin(old_id, new_id):
    hooks = load_hooks()
    assert old_id in hooks, f"deprecated alias {old_id} was dropped"
    assert new_id in hooks
    alias, current = hooks[old_id], hooks[new_id]
    # a true alias: same program, same files, same filename handling
    assert alias["entry"] == current["entry"]
    assert alias["files"] == current["files"]
    assert alias.get("types") == current.get("types")
    assert alias.get("pass_filenames") == current.get("pass_filenames")


@pytest.mark.parametrize("old_id", sorted(DEPRECATED_ALIASES))
def test_deprecated_alias_says_so(old_id):
    """The alias must be labelled, so nobody adopts it in a new config."""
    hook = load_hooks()[old_id]
    text = f"{hook['name']} {hook.get('description', '')}".lower()
    assert "deprecated" in text
