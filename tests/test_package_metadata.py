#!/usr/bin/env python3
"""Tests for what PyPI shows: the README as the project page, and classifiers.

PyPI renders README.md (setup.cfg's long_description) with no repository to
resolve relative links against, so every link must be absolute. The Python
version classifiers must agree with python_requires and the CI test matrix.
"""

import configparser
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")  # ships with pre-commit; skip if absent

REPO = Path(__file__).resolve().parent.parent


def setup_cfg():
    parser = configparser.ConfigParser()
    parser.read(REPO / "setup.cfg", encoding="utf-8")
    return parser


def python_classifiers():
    raw = setup_cfg()["metadata"]["classifiers"]
    return {
        match.group(1)
        for match in re.finditer(r"Programming Language :: Python :: (3\.\d+)", raw)
    }


def test_readme_links_are_absolute():
    text = (REPO / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)\s]+)\)", text)
    assert targets
    relative = [t for t in targets if not re.match(r"(https?://|mailto:|#)", t)]
    assert relative == []


def test_classifiers_start_at_python_requires():
    minimum = re.search(r">=\s*(3\.\d+)", setup_cfg()["options"]["python_requires"])
    versions = python_classifiers()
    assert min(versions, key=lambda v: int(v.split(".")[1])) == minimum.group(1)


def test_classifiers_cover_the_ci_matrix():
    workflow = yaml.safe_load(
        (REPO / ".github/workflows/test_build.yaml").read_text(encoding="utf-8")
    )
    matrix = workflow["jobs"]["test_build"]["strategy"]["matrix"]["py-version"]
    assert set(matrix) <= python_classifiers()
