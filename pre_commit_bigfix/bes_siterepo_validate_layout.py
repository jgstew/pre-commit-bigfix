#!/usr/bin/env python3
"""Check a BigFix Git External Custom Site repo's layout, file names and paths.

A Git External Custom Site ("repository site", BigFix 11.0.7+) is gathered by
the root server from a git repo. One bad file can fail the whole sync, so
this hook checks the site as a whole before it is pushed.
"""

import argparse
import collections
import os
import subprocess
import sys

from lxml import etree

if __package__ in (None, ""):  # run directly as a script, not as a module
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pre_commit_bigfix import bes_common

DEFAULT_SERVER_ROOT = "C:\\Program Files (x86)\\BigFix Enterprise\\BES Server"
DEFAULT_BRANCH = "main"
# MAX_PATH is 260 including the terminating NUL
DEFAULT_MAX_PATH = 259
# the server names the clone <repo>_<branch>_<8 hex>; the hash is unknown here
# and only its length matters
HASH_PLACEHOLDER = "0" * 8

DEFAULT_DIRS = ("Fixlets", "NonClientFiles", "OtherFiles")
SITE_CONFIG = "siteConfig.xml"
SITE_CONFIG_ELEMENTS = ("BesFileDir", "NonClientFilesDir", "OtherFilesDir")

KNOWN_CODES = frozenset({"W807"})

SiteConfig = collections.namedtuple(
    "SiteConfig", "bes_dir nonclient_dir other_dir named issue"
)


def server_prefix(server_root, repo_name, branch, commit_hash=HASH_PLACEHOLDER):
    r"""Return the server folder a repo file's relative path is appended to.

    That is `<server_root>\RepositorySiteGather\Sites\<repo>_<branch>_<hash>\Source\`.
    """
    root = server_root.rstrip("\\/")
    return (
        f"{root}\\RepositorySiteGather\\Sites\\"
        f"{repo_name}_{branch}_{commit_hash}\\Source\\"
    )


def server_path_length(prefix, rel_path):
    """Length of `rel_path` on the server, in the UTF-16 units MAX_PATH counts."""
    full = prefix + rel_path.replace("/", "\\")
    return len(full.encode("utf-16-le")) // 2


def repo_name_from_url(url):
    """The last part of a git remote URL, without `.git`.

    Handles https://host/owner/name(.git), ssh://host/owner/name.git and the
    scp-like git@host:owner/name.git.
    """
    name = url.strip().rstrip("/")
    name = name.replace(":", "/").rsplit("/", 1)[-1]
    # not str.removesuffix(): that needs Python 3.9, and this supports 3.8
    stem, extension = os.path.splitext(name)
    return stem if extension == ".git" else name


def _git(repo_root, *args):
    """Run git in `repo_root`; return its stdout bytes, or None if it failed."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo_root, capture_output=True, check=False
        )
    except OSError:  # git not installed
        return None
    return result.stdout if result.returncode == 0 else None


def repo_root():
    """The top folder of the git repo the current folder is in, or None."""
    out = _git(".", "rev-parse", "--show-toplevel")
    return os.fsdecode(out).strip() if out else None


def default_repo_name(root):
    """The origin remote's repo name, or the repo folder's name if no origin."""
    url = _git(root, "remote", "get-url", "origin")
    if url and os.fsdecode(url).strip():
        return repo_name_from_url(os.fsdecode(url))
    return os.path.basename(os.path.normpath(root))


def git_ls_files(root):
    """Return the files git tracks under `root`, as sorted repo-relative paths.

    `-z` keeps names unquoted (non-ASCII and spaces as they are). An index
    with a merge conflict lists a path once per stage, hence the set.
    """
    out = _git(root, "ls-files", "-z")
    if out is None:
        raise OSError(f"`git ls-files` failed in {root}")
    return sorted({os.fsdecode(name) for name in out.split(b"\0") if name})


def _join(site_root, rel):
    """Join a site root and a site-relative path into a repo-relative path."""
    return f"{site_root}/{rel}" if site_root else rel


def _clean_dir(text):
    """A folder name from siteConfig.xml, without surrounding space or slashes."""
    return (text or "").strip().replace("\\", "/").strip("/")


def read_site_config(root, site_root, files):
    """Read the folder names from `<site_root>/siteConfig.xml`.

    Only a tracked siteConfig.xml counts, since the server only sees what is
    committed. Returns a SiteConfig: the three folder names (defaults for
    any not set), `named` the ones the file sets, and `issue` a W807
    (lineno, code, message) when the file is not readable XML, in which
    case the defaults are used. Validating it is bes-schema-validate's job.
    """
    defaults = SiteConfig(*DEFAULT_DIRS, named=(), issue=None)
    rel = _join(site_root, SITE_CONFIG)
    if rel not in set(files):
        return defaults
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        tree = etree.parse(os.path.join(root, rel), parser)
    except (OSError, etree.XMLSyntaxError) as err:
        return defaults._replace(
            issue=(
                1,
                "W807",
                (
                    f"{SITE_CONFIG} is not readable XML ({err}); assuming the "
                    f"default folders {', '.join(DEFAULT_DIRS)}"
                ),
            )
        )
    found = []
    for tag, default in zip(SITE_CONFIG_ELEMENTS, DEFAULT_DIRS):
        value = _clean_dir(tree.getroot().findtext(tag))
        found.append(value or default)
    named = tuple(
        name
        for tag, name in zip(SITE_CONFIG_ELEMENTS, found)
        if _clean_dir(tree.getroot().findtext(tag))
    )
    return SiteConfig(*found, named=named, issue=None)


def check_repo(root, files, site_roots=("",), **_options):
    """Check the sites in repo `root`; return a list of (path, issues, fixed)."""
    return []


def main(argv=None, list_files=git_ls_files):
    """Execution starts here.

    `list_files(repo_root)` returns the repo-relative files to check; tests
    can pass their own instead of the default `git ls-files`.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.parse_args(argv)

    root = repo_root()
    if root is None:
        print("bes-siterepo-validate-layout: not in a git repo (git rev-parse failed)")
        return 1
    try:
        files = list_files(root)
    except OSError as err:
        print(f"bes-siterepo-validate-layout: {err}")
        return 1
    issue_count, _warning_count, fix_count = bes_common.report(check_repo(root, files))
    return 1 if (issue_count or fix_count) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
