#!/usr/bin/env python3
"""Tests for .github/workflows/tag_and_release.yaml, the release workflow.

A release publishes to PyPI with trusted publishing (OIDC), so these pin the
parts that keep that safe: publishing is off until the PYPI_PUBLISH repository
variable is `true`; only the release job gets `id-token: write`, under the
`pypi` environment that the PyPI trusted publisher names; every action is
pinned to a commit SHA; nothing is released until the test workflow passes; and
the version it releases is the package's `__version__`.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

from pre_commit_bigfix import __version__

yaml = pytest.importorskip("yaml")  # ships with pre-commit; skip if absent

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
RELEASE = WORKFLOWS / "tag_and_release.yaml"
TEST_BUILD = WORKFLOWS / "test_build.yaml"


def load(path):
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on` as the boolean True
    workflow["on"] = workflow.pop(True, workflow.get("on"))
    return workflow


def steps(job):
    return job.get("steps", [])


def step(job, name):
    return next(s for s in steps(job) if s.get("name") == name)


@pytest.fixture(scope="module")
def release():
    return load(RELEASE)


def test_workflow_token_is_read_only_by_default(release):
    assert release["permissions"] == {"contents": "read"}


def test_only_the_release_job_can_write_or_mint_an_oidc_token(release):
    for name, job in release["jobs"].items():
        permissions = job.get("permissions", {})
        if name == "release":
            assert permissions == {"contents": "write", "id-token": "write"}
        else:
            assert "id-token" not in permissions, name
            assert permissions.get("contents", "read") == "read", name


def test_release_job_runs_in_the_pypi_environment(release):
    """The PyPI trusted publisher names this environment; they must match."""
    assert release["jobs"]["release"]["environment"] == "pypi"


def test_publish_is_off_unless_pypi_publish_is_true(release):
    publish = step(release["jobs"]["release"], "Publish to PyPI (trusted publishing)")
    assert publish["if"] == "vars.PYPI_PUBLISH == 'true'"
    run = publish["run"]
    assert "--trusted-publishing always" in run
    # both distributions, and nothing else from dist/ (SHA256SUMS.txt)
    assert "dist/*.whl" in run
    assert "dist/*.tar.gz" in run
    # no long-lived token
    assert "secrets." not in yaml.safe_dump(publish)


def test_publish_is_the_last_step(release):
    """A failed upload must leave the tag and GitHub release already made."""
    last = steps(release["jobs"]["release"])[-1]
    assert last["name"] == "Publish to PyPI (trusted publishing)"


def test_release_waits_for_the_test_workflow(release):
    jobs = release["jobs"]
    assert jobs["test"]["uses"] == "./.github/workflows/test_build.yaml"
    assert "test" in jobs["release"]["needs"]
    assert "workflow_call" in load(TEST_BUILD)["on"]


def test_release_waits_for_pre_commit_manual_stage(release):
    """The manual-stage hooks (zizmor, pyroma, pytest, ...) gate a release too."""
    jobs = release["jobs"]
    assert "pre-commit" in jobs["release"]["needs"]
    run = step(jobs["pre-commit"], "Run pre-commit")["with"]["extra_args"]
    assert "--all-files" in run
    assert "--hook-stage manual" in run


def test_every_action_is_pinned_to_a_commit(release):
    for workflow in (release, load(TEST_BUILD)):
        for job in workflow["jobs"].values():
            for s in steps(job):
                uses = s.get("uses")
                if uses is None or uses.startswith("./"):
                    continue
                assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", uses), uses


def test_no_unmaintained_release_actions():
    text = RELEASE.read_text(encoding="utf-8")
    assert "marvinpinto/action-automatic-releases" not in text
    assert "lewagon/wait-on-check-action" not in text


def test_builds_and_attaches_wheel_and_sdist(release):
    job = release["jobs"]["release"]
    assert "uv build" in step(job, "uv build (wheel + sdist)")["run"]
    create = step(job, "Create the GitHub release")["run"]
    for asset in ("dist/*.whl", "dist/*.tar.gz", "dist/SHA256SUMS.txt"):
        assert asset in create


def test_version_step_reads_the_package_version(release, tmp_path):
    """Run the workflow's own version step and compare with __version__."""
    run = step(release["jobs"]["version"], "Read version")["run"]
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    subprocess.run(
        ["bash", "-e", "-c", run],
        cwd=REPO,
        env={**os.environ, "GITHUB_OUTPUT": str(output)},
        check=True,
        capture_output=True,
    )
    assert f"version={__version__}" in output.read_text(encoding="utf-8")


def test_releases_from_main_of_this_repo_only(release):
    assert release["on"]["push"]["branches"] == ["main"]
    assert "pre_commit_bigfix/__init__.py" in release["on"]["push"]["paths"]
    assert release["jobs"]["version"]["if"] == (
        "github.repository == 'jgstew/pre-commit-bigfix'"
    )
