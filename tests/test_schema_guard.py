#!/usr/bin/env python3
"""Every hook that rewrites BES files refuses a rewrite that breaks BES.xsd.

Each case swaps one of the hook's fixers for one that returns schema-invalid
text (a second <Title>), then checks the hook writes nothing, reports its
guard code, and reports no fixes; that a schema-valid rewrite is still
written; and that disabling the guard code lets the rewrite through. The
guard only stops a valid file becoming invalid -- the many fixture-based fix
tests elsewhere start from minimal, schema-invalid documents and are
unaffected.
"""

import shutil
from pathlib import Path

import pytest

from pre_commit_bigfix import bes_actionscript_lint_schclass as schclass
from pre_commit_bigfix import bes_actionscript_validate_prefetch as prefetch
from pre_commit_bigfix import bes_actionscript_validate_script as script
from pre_commit_bigfix import bes_conventions_check as conventions
from pre_commit_bigfix import bes_relevance_convert_group as convert_group

pytest.importorskip("validate_bes_xml")

EXAMPLE = Path(__file__).parent / "examples" / "example-test.bes"

# (hook module, fixer it calls by module-global name, guard code, a code the
# fake fix reports, check_file kwargs that make it run that fixer)
CASES = [
    pytest.param(
        conventions, "_autofix", "E222", "W213", {"auto_fix": True}, id="conventions"
    ),
    pytest.param(
        schclass, "_apply_fixes", "E304", "W302", {"auto_fix": True}, id="schclass"
    ),
    pytest.param(
        prefetch, "fix_stray_tokens", "E404", "E403", {"auto_fix": True}, id="prefetch"
    ),
    pytest.param(
        script, "fix_scratch_case", "E526", "W503", {"auto_fix": True}, id="script"
    ),
]


def breaking(src):
    """`src` with a second <Title>: well-formed XML, but not BES.xsd-valid."""
    return src.replace("</Title>", "</Title><Title>again</Title>", 1)


def harmless(src):
    """`src` with an extra XML comment: still schema-valid."""
    return src.replace("<BES ", "<!-- touched -->\n<BES ", 1)


def fake_fixer(transform, code):
    """A stand-in fixer: rewrites the text and reports one fix under `code`."""

    def fixer(src, *_args, **_kwargs):
        return transform(src), [(1, code, "fake fix")]

    return fixer


def copy_example(tmp_path):
    path = tmp_path / "example-test.bes"
    shutil.copy(EXAMPLE, path)
    return path


@pytest.mark.parametrize(("hook", "fixer", "guard", "fix_code", "kwargs"), CASES)
def test_schema_breaking_fix_is_not_written(
    tmp_path, monkeypatch, hook, fixer, guard, fix_code, kwargs
):
    path = copy_example(tmp_path)
    original = path.read_bytes()
    monkeypatch.setattr(hook, fixer, fake_fixer(breaking, fix_code))
    issues, fixed = hook.check_file(str(path), **kwargs)
    assert path.read_bytes() == original
    assert fixed == []
    guard_issues = [issue for issue in issues if issue[1] == guard]
    assert len(guard_issues) == 1
    assert "BES.xsd" in guard_issues[0][2]


@pytest.mark.parametrize(("hook", "fixer", "guard", "fix_code", "kwargs"), CASES)
def test_schema_valid_fix_is_written(
    tmp_path, monkeypatch, hook, fixer, guard, fix_code, kwargs
):
    path = copy_example(tmp_path)
    monkeypatch.setattr(hook, fixer, fake_fixer(harmless, fix_code))
    issues, fixed = hook.check_file(str(path), **kwargs)
    assert b"<!-- touched -->" in path.read_bytes()
    assert fix_code in [code for _l, code, _m in fixed]
    assert guard not in [code for _l, code, _m in issues]


@pytest.mark.parametrize(("hook", "fixer", "guard", "fix_code", "kwargs"), CASES)
def test_disabling_the_guard_lets_the_fix_through(
    tmp_path, monkeypatch, hook, fixer, guard, fix_code, kwargs
):
    path = copy_example(tmp_path)
    monkeypatch.setattr(hook, fixer, fake_fixer(breaking, fix_code))
    hook.check_file(str(path), disabled=frozenset({guard}), **kwargs)
    assert b"<Title>again</Title>" in path.read_bytes()


@pytest.mark.parametrize(
    ("hook", "guard"),
    [
        (conventions, "E222"),
        (schclass, "E304"),
        (prefetch, "E404"),
        (script, "E526"),
        (convert_group, "E704"),
    ],
)
def test_guard_code_is_known_and_documented(hook, guard):
    root = Path(__file__).resolve().parent.parent
    hook_id = hook.SKIP_MARKER.partition(": ")[2]
    hooks = (root / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    description = hooks.partition(f"- id: {hook_id}\n")[2].partition("\n- id: ")[0]
    readme = (root / "README.md").read_text(encoding="utf-8")
    section = readme.partition(f"### {hook_id}\n")[2].partition("\n### ")[0]
    assert guard in hook.KNOWN_CODES
    assert guard in hook.__doc__
    assert guard in description
    assert guard in section


# --- review fix: one refused pass must not drop the others (PR #28) ----------

# (hook, the first fix pass it runs, a later pass, guard code, the codes they report)
MULTI_PASS = [
    pytest.param(
        conventions,
        "_autofix",
        "fix_trailing_whitespace",
        "E222",
        ("W213", "W210"),
        id="conventions",
    ),
    pytest.param(
        prefetch,
        "fix_stray_tokens",
        "fix_outdated_unzip",
        "E404",
        ("E403", "E402"),
        id="prefetch",
    ),
    pytest.param(
        script,
        "fix_scratch_case",
        "fix_scratch_destinations",
        "E526",
        ("W503", "W506"),
        id="script",
    ),
]


@pytest.mark.parametrize(("hook", "first", "later", "guard", "codes"), MULTI_PASS)
def test_only_the_breaking_pass_is_dropped(
    tmp_path, monkeypatch, hook, first, later, guard, codes
):
    path = copy_example(tmp_path)
    monkeypatch.setattr(hook, first, fake_fixer(breaking, codes[0]))
    monkeypatch.setattr(hook, later, fake_fixer(harmless, codes[1]))
    issues, fixed = hook.check_file(str(path), auto_fix=True)
    written = path.read_bytes()
    assert b"<!-- touched -->" in written  # the later, valid pass was kept
    assert b"<Title>again</Title>" not in written  # the breaking one was not
    assert [code for _l, code, _m in fixed] == [codes[1]]
    refusals = [issue for issue in issues if issue[1] == guard]
    assert len(refusals) == 1
    assert codes[0] in refusals[0][2]  # names the fix that was held back
