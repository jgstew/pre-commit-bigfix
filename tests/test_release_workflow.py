#!/usr/bin/env python3
"""Tests for .github/workflows/tag_and_release.yaml, the release workflow.

A release publishes to PyPI with trusted publishing (OIDC), so these pin the
parts that keep that safe:
- publishing is off until the PYPI_PUBLISH repository variable is `true`;
- only the publish job can mint an OIDC token, and it runs no build: the
  wheel and sdist are built by a job with no write access and handed over as
  an artifact, so a build dependency never runs where a token can be minted;
- only the release job can write (tag + GitHub release);
- releases happen from main of this repository only, never a dispatched branch;
- every action is pinned to a commit SHA;
- nothing is released until the test workflow and manual-stage hooks pass;
- the version released is the package's `__version__`;
- a failed upload can be retried: creating the release is idempotent, and
  publishing is decided by whether PyPI has the version, not by the tag.
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


def needs(job):
    value = job.get("needs", [])
    return [value] if isinstance(value, str) else value


def run_step(run, env, cwd=REPO):
    """Run a workflow `run:` script under bash -e; return (returncode, outputs)."""
    output = Path(env["GITHUB_OUTPUT"])
    output.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["bash", "-e", "-c", run],
        cwd=cwd,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )
    pairs = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    return result.returncode, pairs


@pytest.fixture(scope="module")
def release():
    return load(RELEASE)


def test_workflow_token_is_read_only_by_default(release):
    assert release["permissions"] == {"contents": "read"}


def test_only_publish_mints_oidc_and_only_release_writes(release):
    for name, job in release["jobs"].items():
        permissions = job.get("permissions", {})
        if name == "publish":
            assert permissions == {"contents": "read", "id-token": "write"}
        elif name == "release":
            assert permissions == {"contents": "write"}
        else:
            assert "id-token" not in permissions, name
            assert permissions.get("contents", "read") == "read", name


def test_publish_job_runs_no_build(release):
    """Nothing but uv itself is installed or run where a token can be minted."""
    text = yaml.safe_dump(release["jobs"]["publish"])
    assert "uv build" not in text
    assert "actions/checkout" not in text  # no repository code at all
    assert "setup.py" not in text and "pip install -e" not in text


def test_publish_job_runs_in_the_pypi_environment(release):
    """The PyPI trusted publisher names this environment; they must match."""
    assert release["jobs"]["publish"]["environment"] == "pypi"


def test_publish_is_off_unless_pypi_publish_is_true(release):
    jobs = release["jobs"]
    decide = step(jobs["version"], "Check whether PyPI needs this version")
    assert decide["env"]["PYPI_PUBLISH"] == "${{ vars.PYPI_PUBLISH }}"
    assert "needs.version.outputs.publish_needed == 'true'" in jobs["publish"]["if"]
    publish = step(jobs["publish"], "Publish to PyPI (trusted publishing)")
    run = publish["run"]
    assert "--trusted-publishing always" in run
    # a retried upload skips files PyPI already has instead of failing on them
    assert "--check-url https://pypi.org/simple/" in run
    # both distributions, and nothing else from dist/ (SHA256SUMS.txt)
    assert "dist/*.whl" in run
    assert "dist/*.tar.gz" in run
    # no long-lived token anywhere in the workflow
    assert "secrets.PYPI" not in RELEASE.read_text(encoding="utf-8")


def test_publish_decision_needs_no_network_when_publishing_is_off(release, tmp_path):
    run = step(release["jobs"]["version"], "Check whether PyPI needs this version")[
        "run"
    ]
    # a curl that fails loudly: asking PyPI while publishing is off is a bug
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "curl").write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    (fake_bin / "curl").chmod(0o755)
    for value in ("", "false", "TRUE", "yes"):
        code, out = run_step(
            run,
            {
                "GITHUB_OUTPUT": str(tmp_path / "out"),
                "PYPI_PUBLISH": value,
                "VERSION": __version__,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            },
        )
        assert code == 0, value
        assert out == {"publish_needed": "false"}, value


@pytest.mark.parametrize(("status", "expected"), [("200", "false"), ("404", "true")])
def test_publish_decision_asks_pypi_when_publishing_is_on(
    release, tmp_path, status, expected
):
    """200: PyPI has this version (nothing to do); 404: it does not (publish)."""
    run = step(release["jobs"]["version"], "Check whether PyPI needs this version")[
        "run"
    ]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "curl").write_text(f"#!/bin/sh\nprintf '{status}'\n", encoding="utf-8")
    (fake_bin / "curl").chmod(0o755)
    code, out = run_step(
        run,
        {
            "GITHUB_OUTPUT": str(tmp_path / "out"),
            "PYPI_PUBLISH": "true",
            "VERSION": __version__,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        },
    )
    assert code == 0
    assert out == {"publish_needed": expected}


def test_publish_decision_fails_on_an_unexpected_pypi_answer(release, tmp_path):
    """A PyPI outage must fail the run, not be read as "not published yet"."""
    run = step(release["jobs"]["version"], "Check whether PyPI needs this version")[
        "run"
    ]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "curl").write_text("#!/bin/sh\nprintf '503'\n", encoding="utf-8")
    (fake_bin / "curl").chmod(0o755)
    code, out = run_step(
        run,
        {
            "GITHUB_OUTPUT": str(tmp_path / "out"),
            "PYPI_PUBLISH": "true",
            "VERSION": __version__,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        },
    )
    assert code != 0
    assert "publish_needed" not in out


def test_publish_waits_for_a_successful_or_existing_release(release):
    publish = release["jobs"]["publish"]
    assert set(needs(publish)) == {"version", "release"}
    condition = publish["if"]
    assert "!cancelled()" in condition
    assert "needs.release.result == 'success'" in condition
    # the only acceptable skipped release is one that was not needed
    assert "needs.release.result == 'skipped'" in condition
    assert "needs.version.outputs.release_needed != 'true'" in condition


def test_publish_uploads_exactly_what_was_released(release):
    publish = release["jobs"]["publish"]
    built = step(publish, "Download the built distributions")
    assert built["uses"].startswith("actions/download-artifact@")
    assert built["with"]["name"] == "dist"
    assert built["if"] == "needs.version.outputs.release_needed == 'true'"
    existing = step(publish, "Download the released distributions")
    assert existing["if"] == "needs.version.outputs.release_needed != 'true'"
    assert "gh release download" in existing["run"]
    assert "sha256sum -c SHA256SUMS.txt" in existing["run"]


def test_build_job_uploads_the_artifact_release_and_publish_use(release):
    jobs = release["jobs"]
    build = jobs["build"]
    assert "uv build" in step(build, "uv build (wheel + sdist)")["run"]
    upload = step(build, "Upload the distributions")
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["with"]["name"] == "dist"
    assert upload["with"]["if-no-files-found"] == "error"
    release_dl = step(jobs["release"], "Download the built distributions")
    assert release_dl["with"]["name"] == "dist"


def test_release_is_built_only_after_the_gates(release):
    jobs = release["jobs"]
    assert jobs["test"]["uses"] == "./.github/workflows/test_build.yaml"
    assert "workflow_call" in load(TEST_BUILD)["on"]
    assert {"test", "pre-commit"} <= set(needs(jobs["build"]))
    assert "build" in needs(jobs["release"])


def test_release_waits_for_pre_commit_manual_stage(release):
    """The manual-stage hooks (zizmor, pyroma, pytest, ...) gate a release too."""
    run = step(release["jobs"]["pre-commit"], "Run pre-commit")["with"]["extra_args"]
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


def test_release_attaches_wheel_sdist_and_checksums(release):
    create = step(release["jobs"]["release"], "Create the GitHub release")["run"]
    for asset in ("dist/*.whl", "dist/*.tar.gz", "dist/SHA256SUMS.txt"):
        assert asset in create


def test_creating_the_release_is_idempotent(release):
    """A re-run after the release was made must not fail before publishing."""
    create = step(release["jobs"]["release"], "Create the GitHub release")["run"]
    assert 'gh release view "v${VERSION}"' in create
    assert create.index("gh release view") < create.index("gh release create")


def test_pre_release_versions_are_not_marked_latest(release):
    create = step(release["jobs"]["release"], "Create the GitHub release")["run"]
    assert "--prerelease" in create


def test_version_step_reads_the_package_version(release, tmp_path):
    """Run the workflow's own version step and compare with __version__."""
    run = step(release["jobs"]["version"], "Read version")["run"]
    code, out = run_step(run, {"GITHUB_OUTPUT": str(tmp_path / "out")})
    assert code == 0
    assert out["version"] == __version__


@pytest.mark.parametrize("bad", ["", "2.0", "v2.0.1", "2.0.1; rm -rf /", "2.0.1\nx=y"])
def test_version_step_rejects_unexpected_versions(release, tmp_path, bad):
    run = step(release["jobs"]["version"], "Read version")["run"]
    package = tmp_path / "pre_commit_bigfix"
    package.mkdir()
    (package / "__init__.py").write_text(f"__version__ = {bad!r}\n", encoding="utf-8")
    code, out = run_step(run, {"GITHUB_OUTPUT": str(tmp_path / "out")}, cwd=tmp_path)
    assert code != 0
    assert "version" not in out


def test_release_notes_section_exists_for_this_version(release, tmp_path):
    """The awk in the release-notes step finds a non-empty section for __version__."""
    run = step(release["jobs"]["release"], "Build release notes")["run"]
    awk = re.search(r"awk .*?RELEASE_NOTES\.md", run, re.S).group(0)
    result = subprocess.run(
        ["bash", "-e", "-c", awk],
        cwd=REPO,
        env={**os.environ, "VERSION": __version__},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip()
    assert "## v" not in result.stdout  # stopped at the next version heading


def test_releases_from_main_of_this_repo_only(release):
    assert release["on"]["push"]["branches"] == ["main"]
    assert "pre_commit_bigfix/__init__.py" in release["on"]["push"]["paths"]
    condition = release["jobs"]["version"]["if"]
    assert "github.repository == 'jgstew/pre-commit-bigfix'" in condition
    # workflow_dispatch can pick any branch; only main may release
    assert "github.ref == 'refs/heads/main'" in condition
