#!/usr/bin/env python3
"""Check a BigFix Git External Custom Site repo's layout, file names and paths.

A Git External Custom Site ("repository site", BigFix 11.0.7+) is gathered by
the root server from a git repo, and one bad file can fail the whole sync. This
hook checks the site as a whole, so pre-commit runs it once per commit
(pass_filenames: false, always_run: true). The files it sees are those
`git ls-files` lists: untracked and ignored files do not count.

Each site root (--site-root, repeatable; default the repo root) may hold a
siteConfig.xml naming its folders (BesFileDir, NonClientFilesDir,
OtherFilesDir); the defaults are Fixlets, NonClientFiles and OtherFiles.

A root server may run Windows or RHEL, and one repo site may serve both, so
names and paths must be valid on both: the stricter limit always applies.
Folder names, the .bes extension and digest.xml are matched ignoring case,
as on Windows, so nothing goes unchecked, but a name that matches only that
way is a warning (W808), since RHEL is case-sensitive.

Checks (E-codes fail the hook; W-codes are advisory unless --strict):

    E800  a .bes file in the .bes folder whose name does not start with a
          numeric ID followed by a space or hyphen (`42- Name.bes`,
          `42 Name.bes`); the server skips it
    E801  two or more .bes files in one site share an ID, compared as
          integers (0042 and 42 collide); each names the others
    E802  a .bes file's server path is over the limit and the rename cannot
          fix it: even `<ID> X.bes` is too long (the folders are), it has no
          ID, or E805 is disabled. Renaming a folder changes its .fxf or
          digest, so that is not done
    E803  fix: zero padding in the ID (0042- X.bes -> 42- X.bes); done even
          when the ID is a duplicate (E801), since the ID does not change
    E804  fix: non-ASCII characters in the name, folded to ASCII
    E805  fix: the server path is over the limit, or the name is over 255
          bytes; renamed `<ID> <Title>.bes`
    E806  a rename was skipped: the new name is taken, ignoring case (by a
          tracked file, another planned rename or an untracked file), the
          file has unstaged changes pre-commit set aside, the commit uses a
          temporary index (git commit -a, git commit <paths>), or the
          rename failed
    E807  any other tracked file whose server path is over the limit, in or
          outside the site roots (the server clones the whole repo); it is
          not renamed, since actions may refer to it by name
    E808  a file or folder name over 255 bytes in UTF-8 that the rename
          cannot fix; a folder is reported once
    W800  a .bes file outside the .bes folder; it is not gathered
    W801  a .bes file directly in the .bes folder, or deeper than
          <BesFileDir>/<fxf>/<digest>/ (server behavior undocumented)
    W802  a file in the .bes folder other than .bes or digest.xml (an .xsd
          too: bes-schema-validate already has the schemas)
    W803  a folder siteConfig.xml renames does not exist (has no files); a
          default name spelled out, as the template does, is not checked,
          since those folders are optional
    W804  a site with no content: no .bes files in the .bes folder and no
          files in the NonClient or Other folders (server files alone pass)
    W806  an ID outside 1..2147483647 (the range is undocumented)
    W807  siteConfig.xml is not readable XML; the default folders are used
    W808  a folder, .bes extension or digest.xml that matches the expected
          name only when case is ignored

Path limit (Windows): the server clones the whole repo to
`<server-root>\\RepositorySiteGather\\Sites\\<repo>_<branch>_<8 hex>\\Source\\`
and each file's path relative to the REPO root (not the site root) follows
that. It must be at most --max-path (259: MAX_PATH 260 includes the NUL),
counted in UTF-16 units. <repo> is the git repo's name (--repo-name, default
the origin remote's, else the repo folder's), not the BigFix site name.
Over-long paths fail on 11.0.7 even with Windows long paths enabled. Only
this Windows layout is confirmed; the RHEL clone path is not, so it is
the one measured.

Name limit (Linux): each file and folder name must be at most NAME_MAX, 255
bytes in UTF-8. Linux's PATH_MAX (4096 bytes) cannot be reached once the
Windows limit holds, so it has no check of its own.

Auto-fix (the default; --check is a dry run that reports and changes
nothing): each .bes file in the .bes folder is renamed at most once, combining
E803, E804 and, if the path or name is still too long, E805. E805 builds
`<ID> <Title><extension>` (no hyphen) from the first content object's
<Title> (or the current name without its ID, if the Title has no letter or
digit), made ASCII and Windows-safe, cut to fit both limits, with trailing
spaces, dots and hyphens dropped. A name that already fits is left alone,
even when it differs from <Title>. The ID never changes and no file moves
between folders. Files without an ID are not given one: --assign-ids is
deferred (assigning IDs is a policy decision; CommunityContent uses a
counter file, and max+1 would reuse the IDs of deleted content).

How files are renamed: a tracked file with `git mv`, anything else (only a
file list a caller passes in) with a plain rename. git mv stages the
rename, so the next commit carries both the new name and the removal of the
old one; a plain rename would leave an unstaged deletion plus an untracked
file, and `git commit -a` (or `git add -u`) would then commit the deletion
alone, dropping the content from the repo. Three cases rename nothing
(E806), because the rename would be lost:
  - git commit -a and git commit <paths> give the hook a temporary index
    that git discards when the hook fails (see uses_real_index);
  - inside a pre-commit run, pre-commit has stashed unstaged changes in a
    patch it re-applies after the hooks, and cannot re-apply it to a
    renamed file, so a file named in the patch is left alone (see
    pre_commit_stashed_paths; `pre-commit try-repo` uses a temporary cache,
    where the patch is not found);
  - --check.
Any rename makes the hook exit 1, so the commit stops and the renames can
be reviewed.

Not in scope: more than one object per .bes file and Baselines (repository
sites are thought to handle both); case conflicts and names Windows forbids
(use check-case-conflict and check-illegal-windows-names from
pre-commit-hooks >= 5.0.0); schemas, GroupRelevance and `//` comments (the
bes-schema-validate, bes-relevance-convert-group and bes-conventions-check
hooks); writing a siteConfig.xml for a blank repo.
"""

import argparse
import collections
import glob
import os
import posixpath
import re
import subprocess
import sys
import unicodedata

from lxml import etree

if __package__ in (None, ""):  # run directly as a script, not as a module
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pre_commit_bigfix import bes_common

DEFAULT_SERVER_ROOT = "C:\\Program Files (x86)\\BigFix Enterprise\\BES Server"
DEFAULT_BRANCH = "main"
# MAX_PATH is 260 including the terminating NUL
DEFAULT_MAX_PATH = 259
# a root server may run Linux (RHEL) instead, and one repo site may serve
# both, so the stricter limit always applies. Linux limits each file or
# folder name to NAME_MAX bytes (UTF-8). Its PATH_MAX (4096 bytes) needs no
# check of its own: 259 UTF-16 units are at most 777 bytes in UTF-8.
NAME_MAX = 255
# the server names the clone <repo>_<branch>_<8 hex>; the hash is unknown here
# and only its length matters
HASH_PLACEHOLDER = "0" * 8

DEFAULT_DIRS = ("Fixlets", "NonClientFiles", "OtherFiles")
SITE_CONFIG = "siteConfig.xml"
SITE_CONFIG_ELEMENTS = ("BesFileDir", "NonClientFilesDir", "OtherFilesDir")

KNOWN_CODES = frozenset(
    {
        "E800",
        "E801",
        "E802",
        "E803",
        "E804",
        "E805",
        "E806",
        "E807",
        "E808",
        "W800",
        "W801",
        "W802",
        "W803",
        "W804",
        "W806",
        "W807",
        "W808",
    }
)

# a numeric ID, then a space or a hyphen: `42- Name.bes`, `42 Name.bes`
ID_PREFIX_RE = re.compile(r"^([0-9]+)[ -]")
# undocumented; the largest signed 32-bit integer is the likely ceiling
MAX_ID = 2147483647

# non-ASCII characters NFKD does not fold, or folds to something unwanted:
# currency from #32, typographic quotes and dashes (the one non-ASCII name
# found in the corpora was Docker\u2019s). Double quotes become ' because
# Windows forbids " in file names.
ASCII_TABLE = {
    "\u20ac": "EUR",
    "\u00a3": "GBP",
    "\u00df": "ss",
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u201c": "'",
    "\u201d": "'",
    "\u201e": "'",
    "\u201f": "'",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
}
# characters Windows forbids in a file name (control characters too)
WINDOWS_FORBIDDEN = frozenset('<>:"/\\|?*')
FIX_CODES = ("E803", "E804", "E805")

SiteConfig = collections.namedtuple(
    "SiteConfig", "bes_dir nonclient_dir other_dir named issue"
)


def server_prefix(server_root, repo_name, branch, commit_hash=HASH_PLACEHOLDER):
    r"""Return the server folder a repo file's relative path is appended to.

    That is `<server_root>\RepositorySiteGather\Sites\<repo>_<branch>_<hash>\Source\`,
    joined with `/` instead when `server_root` is a POSIX path. Only the
    Windows layout is confirmed; a separator is one character either way,
    so the length is the same.
    """
    sep = "/" if server_root.startswith("/") else "\\"
    root = server_root.rstrip("\\/")
    return sep.join(
        [root, "RepositorySiteGather", "Sites", f"{repo_name}_{branch}_{commit_hash}"]
        + ["Source", ""]
    )


def server_path_length(prefix, rel_path):
    """Length of `rel_path` on the server, in the UTF-16 units MAX_PATH counts.

    A name git listed as bytes that are not UTF-8 holds lone surrogates
    (os.fsdecode); surrogatepass counts each as one unit instead of failing.
    """
    full = prefix + rel_path.replace("/", "\\")
    return len(full.encode("utf-16-le", "surrogatepass")) // 2


def name_bytes(name):
    """Bytes `name` takes in UTF-8, as a Linux file system counts NAME_MAX.

    A name git listed as bytes that are not UTF-8 holds surrogate escapes
    (os.fsdecode); surrogateescape turns those back into their bytes.
    """
    try:
        return len(name.encode("utf-8", "surrogateescape"))
    except UnicodeEncodeError:  # a surrogate that is not an escape
        return len(name.encode("utf-8", "surrogatepass"))


def repo_name_from_url(url):
    """The last part of a git remote URL, without `.git`.

    Handles https://host/owner/name(.git), ssh://host/owner/name.git, the
    scp-like git@host:owner/name.git, and local paths, Windows ones too
    (C:\\repos\\name, \\\\server\\share\\name.git). `.git` matches in any case.
    """
    name = url.strip().replace("\\", "/").rstrip("/")
    name = name.replace(":", "/").rsplit("/", 1)[-1]
    # not str.removesuffix(): that needs Python 3.9, and this supports 3.8
    stem, extension = os.path.splitext(name)
    return stem if extension.lower() == ".git" else name


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
    """A folder name from siteConfig.xml, without surrounding space or slashes.

    `./Content`, `.\\Content\\` and `Content/./` all mean Content; `.` (or
    nothing) names no folder, so the caller uses the default.
    """
    text = (text or "").strip().replace("\\", "/")
    if not text:
        return ""
    text = posixpath.normpath(text).strip("/")
    return "" if text == "." else text


def read_site_config(root, site_root, files):
    """Read the folder names from `<site_root>/siteConfig.xml`.

    Only a tracked siteConfig.xml counts, since the server only sees what is
    committed. Returns a SiteConfig: the three folder names (defaults for
    any not set), `named` the ones it renames to something other than
    the default, and `issue` a W807
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
    # a default name spelled out (as the RepositorySiteExample template does)
    # renames nothing, so it does not count
    named = tuple(
        name
        for name, default in zip(found, DEFAULT_DIRS)
        if name.lower() != default.lower()
    )
    return SiteConfig(*found, named=named, issue=None)


def _windows_safe(char):
    """True for a printable ASCII character Windows allows in a file name."""
    return " " <= char <= "~" and char not in WINDOWS_FORBIDDEN


def fold_ascii(text):
    """Return `text` with each non-ASCII character replaced by ASCII (#32).

    The text is first composed (NFC), so a decomposed accent (a combining
    mark after its letter, as macOS writes names) joins its letter. Then
    ASCII_TABLE, then Unicode NFKD with the combining marks dropped
    (\u00e9 -> e, \u2122 -> TM); a character with no Windows-safe ASCII
    equivalent becomes `_`. A combining mark with no letter to join, and an
    invisible format character (category Cf: zero-width space, BOM), are
    dropped. ASCII characters are left as they are.
    """
    out = []
    for char in unicodedata.normalize("NFC", text):
        if char.isascii():
            out.append(char)
        elif char in ASCII_TABLE:
            out.append(ASCII_TABLE[char])
        elif unicodedata.combining(char) or unicodedata.category(char) == "Cf":
            continue
        else:
            decomposed = "".join(
                c
                for c in unicodedata.normalize("NFKD", char)
                if not unicodedata.combining(c)
            )
            ok = decomposed and all(_windows_safe(c) for c in decomposed)
            out.append(decomposed if ok else "_")
    return "".join(out)


def safe_title(title):
    """Turn a Title into ASCII text that is safe in a Windows file name.

    Runs of whitespace become one space, and the ends are trimmed; then
    non-ASCII is folded and anything Windows forbids becomes `_`.
    """
    text = fold_ascii(re.sub(r"\s+", " ", title).strip())
    return "".join(c if _windows_safe(c) else "_" for c in text)


def read_title(path):
    """The first content object's <Title> in a .bes file, or None."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        titles = etree.parse(path, parser).xpath("/BES/*/Title")
    except (OSError, ValueError, etree.XMLSyntaxError):  # ValueError: Unicode
        return None
    return "".join(titles[0].itertext()) if titles else None


def _within(rel, folder):
    """`rel` relative to `folder` if it is inside it, else None.

    Compared ignoring case, so nothing goes unchecked: on a Windows root
    server `fixlets/` and `Fixlets/` are the same folder. A RHEL root server
    is case-sensitive, so a match that holds only this way is flagged W808.
    """
    if not folder:
        return rel
    if rel.lower().startswith(folder.lower() + "/"):
        return rel[len(folder) + 1 :]
    return None


def _is_bes(path):
    """True for a .bes file, whatever the case of its extension."""
    return path.lower().endswith(".bes")


def _assign_sites(files, site_roots):
    """Return {site root: [repo-relative paths]}; a file goes to its deepest root."""
    by_site = {site: [] for site in site_roots}
    deepest_first = sorted(site_roots, key=len, reverse=True)
    for path in files:
        for site in deepest_first:
            if _within(path, site) is not None:
                by_site[site].append(path)
                break
    return by_site


class _Results:
    """Collects (lineno, code, message) issues and fixes per path."""

    def __init__(self):
        self.issues = collections.defaultdict(list)
        self.fixed = collections.defaultdict(list)

    def issue(self, path, code, message):
        self.issues[path].append((1, code, message))

    def as_list(self, disabled):
        paths = sorted(set(self.issues) | set(self.fixed))
        return [
            (
                path,
                sorted(i for i in self.issues[path] if i[1] not in disabled),
                self.fixed[path],
            )
            for path in paths
        ]


def _id_of(path):
    """The numeric ID a .bes file's name starts with, as an int, or None."""
    match = ID_PREFIX_RE.match(path.rsplit("/", 1)[-1])
    return int(match.group(1)) if match else None


def _check_ids(results, bes_paths):
    """E800, W806 and E801 for the .bes files of one site's .bes folder."""
    by_id = collections.defaultdict(list)
    for path in bes_paths:
        name = path.rsplit("/", 1)[-1]
        match = ID_PREFIX_RE.match(name)
        if match is None:
            results.issue(
                path,
                "E800",
                "file name does not start with a numeric ID followed by a space "
                "or hyphen (`42- Name.bes` or `42 Name.bes`); the server "
                "skips it",
            )
            continue
        number = int(match.group(1))
        by_id[number].append(path)
        if not 1 <= number <= MAX_ID:
            results.issue(
                path,
                "W806",
                f"ID {number} is outside 1..{MAX_ID} (the range is undocumented)",
            )
    for number, paths in by_id.items():
        if len(paths) < 2:
            continue
        for path in paths:
            others = ", ".join(other for other in paths if other != path)
            results.issue(
                path,
                "E801",
                f"ID {number} is also used by {others} (IDs are compared as "
                "integers, so leading zeros do not count); the server skips "
                "duplicates",
            )


def _check_layout(results, site, site_files, config):
    """W800-W804 for one site; return the .bes files in its .bes folder."""
    bes_dir = config.bes_dir
    bes_paths = []
    case_reported = set()
    for path in site_files:
        rel = _within(path, site)
        for folder in (bes_dir, config.nonclient_dir, config.other_dir):
            actual = rel[: len(folder)]
            if (
                _within(rel, folder) is not None
                and actual != folder
                and actual not in case_reported
            ):
                case_reported.add(actual)
                results.issue(
                    _join(site, actual),
                    "W808",
                    f"folder {actual}/ is the {folder}/ the site uses only when "
                    "case is ignored; a case-sensitive root server (RHEL) may "
                    "not find it",
                )
        inside = _within(rel, bes_dir)
        if inside is None:
            if _is_bes(path):
                results.issue(
                    path,
                    "W800",
                    f"a .bes file outside the .bes folder ({_join(site, bes_dir)}/) "
                    "is not gathered",
                )
            continue
        name = inside.rsplit("/", 1)[-1]
        if _is_bes(path):
            bes_paths.append(path)
            if not path.endswith(".bes"):
                results.issue(
                    path,
                    "W808",
                    f"extension {path[-4:]} is .bes only when case is ignored; "
                    "a case-sensitive root server (RHEL) may not gather it",
                )
            depth = inside.count("/")
            if depth == 0 or depth > 2:
                where = "directly in" if depth == 0 else "more than two folders into"
                results.issue(
                    path,
                    "W801",
                    f"a .bes file {where} {bes_dir}/; the documented layout is "
                    f"{bes_dir}/<fxf>/ or {bes_dir}/<fxf>/<digest>/ (how the "
                    "server handles this is undocumented)",
                )
        elif name.lower() == "digest.xml":
            if name != "digest.xml":
                results.issue(
                    path,
                    "W808",
                    f"{name} is digest.xml only when case is ignored; a "
                    "case-sensitive root server (RHEL) may not find it",
                )
        elif name.lower().endswith(".xsd"):
            results.issue(
                path,
                "W802",
                f"an .xsd in {bes_dir}/ is not site content; the site does not "
                "need schemas, bes-schema-validate already has them",
            )
        else:
            results.issue(
                path,
                "W802",
                f"only .bes files and digest.xml belong in {bes_dir}/; this is "
                "not site content",
            )

    for folder in config.named:
        # a folder name may have several parts (Content/Fixlets)
        if not any(_within(_within(p, site), folder) for p in site_files):
            results.issue(
                _join(site, SITE_CONFIG),
                "W803",
                f"{SITE_CONFIG} names the folder {folder}/, which has no files",
            )

    has_content = bes_paths or any(
        _within(_within(p, site), folder)
        for p in site_files
        for folder in (config.nonclient_dir, config.other_dir)
    )
    if not has_content:
        results.issue(
            site or ".",
            "W804",
            f"the site has no content: no .bes files in {bes_dir}/ and no files "
            f"in {config.nonclient_dir}/ or {config.other_dir}/",
        )
    return bes_paths


def _shortest_name(path):
    """The shortest name the length fix could give a .bes file: `<ID> X.bes`."""
    folder, _, name = path.rpartition("/")
    extension = os.path.splitext(name)[1]
    short = f"{_id_of(path)} X{extension}"
    return f"{folder}/{short}" if folder else short


def _check_limits(results, files, gathered, prefix, max_path, disabled=frozenset()):
    """E802, E807 and E808: names and paths a root server cannot hold.

    Path: the server path must be at most `max_path` (Windows). Name: each
    file and folder name must be at most NAME_MAX bytes (Linux). `gathered`
    are the .bes files in a site's .bes folder; the rename fix can shorten
    those that have an ID, so only one even the shortest name cannot bring
    under the path limit is reported here (E802), or, with the E805 fix
    disabled, any of them over a limit. Every other tracked file over a
    limit is an error too (E807, E808): the server clones the whole repo, so
    one long path anywhere fails the sync. Those are not renamed, since
    actions may refer to them by name, and a folder is not renamed since
    that changes its .fxf or digest.
    """
    long_folders = set()
    for path in files:
        parts = path.split("/")
        for depth, part in enumerate(parts[:-1], start=1):
            folder = "/".join(parts[:depth])
            size = name_bytes(part)
            if size > NAME_MAX and folder not in long_folders:
                long_folders.add(folder)
                results.issue(
                    folder,
                    "E808",
                    f"folder name is {size} bytes in UTF-8, over the {NAME_MAX}-"
                    "byte limit of Linux file systems, so a RHEL root server "
                    "cannot check it out; rename it by hand",
                )
        fixable = path in gathered and _id_of(path) is not None
        _check_path_length(
            results, path, path in gathered, fixable, prefix, max_path, disabled
        )
        size = name_bytes(parts[-1])
        if size <= NAME_MAX:
            continue
        if fixable and "E805" not in disabled:
            continue  # the rename makes it ASCII and short
        if (
            fixable
            and "E804" not in disabled
            and name_bytes(fold_ascii(parts[-1])) <= NAME_MAX
        ):
            continue  # folding it to ASCII is enough
        results.issue(
            path,
            "E808",
            f"file name is {size} bytes in UTF-8, over the {NAME_MAX}-byte limit "
            "of Linux file systems, so a RHEL root server cannot check it out"
            + ("; renaming it would fix it, but E805 is disabled" if fixable else "")
            + ("" if fixable else "; shorten it by hand"),
        )


def _check_path_length(results, path, gathered, fixable, prefix, max_path, disabled):
    """E802 or E807 for `path` if its server path is over `max_path`.

    `gathered`: it is a .bes file in a site's .bes folder; `fixable`: one
    with an ID, which the E805 rename can shorten.
    """
    length = server_path_length(prefix, path)
    if length <= max_path:
        return
    over = f"server path is {length} characters, over the {max_path} limit"
    if not fixable:
        if gathered:  # a gathered .bes file with no ID
            results.issue(
                path,
                "E802",
                f"{over}, and with no numeric ID there is no short name to "
                "rename it to",
            )
        else:
            results.issue(
                path,
                "E807",
                f"{over}, so a Windows root server cannot check it out; "
                "shorten it by hand (it is not renamed automatically, since "
                "actions may refer to it by name)",
            )
        return
    shortest = _shortest_name(path)
    shortest_length = server_path_length(prefix, shortest)
    if shortest_length > max_path:
        results.issue(
            path,
            "E802",
            f"{over}, and even the shortest name ({shortest}) would be "
            f"{shortest_length}: the folders are too long. Renaming a folder "
            "changes its .fxf or digest, so this is not fixed",
        )
    elif "E805" in disabled:
        results.issue(
            path,
            "E802",
            f"{over}; renaming it to <ID> <Title> would fix it, but E805 is "
            "disabled",
        )


class _Renamer:
    """Plans the one rename each gathered .bes file may get, then makes them.

    The new name combines E803 (zero padding stripped from the ID), E804
    (non-ASCII folded) and, when the server path is still too long, E805
    (`<ID> <Title>` cut to fit). The ID never changes and the file never
    leaves its folder. A name already taken, ignoring case, by a tracked
    file, another planned rename or anything on disk is E806 instead.
    """

    def __init__(self, root, files, prefix, max_path, disabled, held=frozenset()):
        self.root = root
        self.held = held
        self.temporary_index = False
        self.prefix = prefix
        self.max_path = max_path
        self.disabled = disabled
        # lowercased path -> the path holding that name
        self.taken = {path.lower(): path for path in files}
        self.renames = []  # (old path, new path, [(code, reason)])

    def _length(self, path):
        return server_path_length(self.prefix, path)

    def _new_name(self, results, path):
        """Return (new name, [(code, reason)]) for `path`; reasons may be []."""
        folder, _, name = path.rpartition("/")
        digits = ID_PREFIX_RE.match(name).group(1)
        number = int(digits)
        new, reasons = name, []
        if "E803" not in self.disabled and digits != str(number):
            new = str(number) + new[len(digits) :]
            reasons.append(("E803", f"zero-padded ID {digits} is {number}"))
        if "E804" not in self.disabled and not new.isascii():
            new = fold_ascii(new)
            reasons.append(("E804", "non-ASCII characters in the file name"))
        length = self._length(_join(folder, new))
        size = name_bytes(new)
        if "E805" not in self.disabled and (length > self.max_path or size > NAME_MAX):
            extension = os.path.splitext(name)[1]
            stem = _join(folder, f"{number} ")
            room = min(
                self.max_path - self._length(stem + extension),
                NAME_MAX - name_bytes(f"{number} {extension}"),
            )
            if length > self.max_path:
                why = (
                    f"server path is {length} characters, over the "
                    f"{self.max_path} limit"
                )
            else:
                why = (
                    f"file name is {size} bytes in UTF-8, over the {NAME_MAX}-"
                    "byte limit of Linux file systems"
                )
            if room >= 1:  # otherwise _check_limits reported E802
                title = read_title(os.path.join(self.root, path))
                # a Title of only forbidden characters would give `42 ___`
                if title is None or not any(c.isalnum() for c in safe_title(title)):
                    # the current name, without its ID prefix
                    title = os.path.splitext(name[len(digits) :])[0].lstrip(" -")
                short = safe_title(title)[:room].rstrip(" .-")
                if short:
                    new = f"{number} {short}{extension}"
                    reasons.append(("E805", why))
                else:
                    # E802 is the path code, E808 the name code
                    results.issue(
                        path,
                        "E802" if length > self.max_path else "E808",
                        f"{why}, and there is no title to build a shorter name from",
                    )
        return new, reasons

    def plan(self, results, path):
        """Plan the rename of gathered .bes file `path`, if it needs one."""
        if ID_PREFIX_RE.match(path.rsplit("/", 1)[-1]) is None:
            return  # E800: no ID to keep
        new, reasons = self._new_name(results, path)
        if not reasons:
            return
        new_path = _join(path.rpartition("/")[0], new)
        if path in self.held:
            results.issue(
                path,
                "E806",
                f"not renamed to {new}: pre-commit set aside its unstaged "
                "changes for this run, and pre-commit could not restore them "
                "to a renamed file; stage or stash them, then run again",
            )
            return
        holder = self._holder(path, new_path)
        if holder:
            why = "; ".join(reason for _code, reason in reasons)
            results.issue(
                path,
                "E806",
                f"not renamed to {new} ({why}): {holder} has that name "
                "(names are compared ignoring case); rename it by hand",
            )
            return
        self.renames.append((path, new_path, reasons))

    def _holder(self, path, new_path):
        """Describe what already has the name `new_path`, or return None."""
        key = new_path.lower()
        if key == path.lower():
            return None  # only the file itself
        if key in self.taken:
            return self.taken[key]
        for old, planned, _reasons in self.renames:
            if key == planned.lower():
                return f"{old}, which is being renamed to it,"
        if os.path.lexists(os.path.join(self.root, new_path)):
            return "an untracked file"
        return None

    def apply(self, results, check, tracked):
        """Make the planned renames (or, under `check`, report them)."""
        for old, new_path, reasons in self.renames:
            new = new_path.rsplit("/", 1)[-1]
            if check:
                for code, reason in reasons:
                    results.issue(
                        old,
                        code,
                        f"{reason}; would be renamed to {new} (run without --check)",
                    )
                continue
            if self.temporary_index:
                results.issue(
                    old,
                    "E806",
                    f"not renamed to {new}: this commit uses a temporary index "
                    "(git commit -a, or git commit <paths>), which git throws "
                    "away when the hook fails, so the rename would be lost. "
                    "git add the changes and run a plain git commit (or "
                    "pre-commit run) to rename it",
                )
                continue
            error = _rename(self.root, old, new_path, old in tracked)
            if error:
                results.issue(old, "E806", f"could not rename to {new}: {error}")
                continue
            for code, reason in reasons:
                results.fixed[old].append((1, code, f"{reason}; renamed to {new}"))


def _rename(root, old, new, use_git):
    """Rename repo-relative `old` to `new`; return an error message or None."""
    if use_git:
        try:
            result = subprocess.run(
                ["git", "mv", "--", old, new],
                cwd=root,
                capture_output=True,
                encoding="utf-8",
                errors="backslashreplace",  # git echoes names that may not be UTF-8
                check=False,
            )
        except OSError as err:
            return str(err)
        return result.stderr.strip() or "git mv failed" if result.returncode else None
    try:
        os.rename(os.path.join(root, old), os.path.join(root, new))
    except OSError as err:
        return str(err)
    return None


def uses_real_index(root, environ=None):
    """False when git gave this hook a temporary index (GIT_INDEX_FILE).

    git commit -a and git commit <paths> run the pre-commit hook against a
    temporary index (index.lock, next-index-<pid>.lock) that git discards
    when the hook fails, so a `git mv` made there is lost while the work
    tree keeps the new name. A relative GIT_INDEX_FILE is taken relative to
    `root`, where the hook runs.
    """
    environ = os.environ if environ is None else environ
    index = environ.get("GIT_INDEX_FILE")
    if not index:
        return True
    git_dir = _git(root, "rev-parse", "--absolute-git-dir")
    if git_dir is None:
        return False
    real = os.path.join(os.fsdecode(git_dir).strip(), "index")
    given = os.path.join(root, index)  # an absolute `index` wins in join
    return os.path.realpath(given) == os.path.realpath(real)


def _pre_commit_home(environ):
    """The folder pre-commit keeps its cache, and so its stash patches, in."""
    if environ.get("PRE_COMMIT_HOME"):
        return environ["PRE_COMMIT_HOME"]
    cache = environ.get("XDG_CACHE_HOME") or os.path.join(
        environ.get("HOME") or os.path.expanduser("~"), ".cache"
    )
    return os.path.join(cache, "pre-commit")


def _is_windows():
    """True on Windows; a function so tests can pretend either way."""
    return os.name == "nt"


def _parent_pid_windows(pid):
    """The parent of process `pid` on Windows, from a Toolhelp snapshot."""
    import ctypes  # pylint: disable=import-outside-toplevel
    from ctypes import wintypes  # pylint: disable=import-outside-toplevel

    class ProcessEntry(ctypes.Structure):  # PROCESSENTRY32W
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    # declared, so a HANDLE is passed whole rather than as a C int
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for walk in (kernel32.Process32FirstW, kernel32.Process32NextW):
        walk.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        walk.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return None
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(ProcessEntry)
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32ProcessID == pid:
                return entry.th32ParentProcessID
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return None
    finally:
        kernel32.CloseHandle(snapshot)


def _parent_pid(pid):
    """The parent of process `pid`, or None when it cannot be told."""
    try:
        if _is_windows():
            return _parent_pid_windows(pid)
        out = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        return int(out) if out else None
    except Exception:  # noqa: BLE001 - e.g. ctypes.ArgumentError: fail safe
        return None


def pre_commit_stashed_paths(root, pid=None, environ=None):
    """Return the files whose unstaged changes pre-commit set aside for this run.

    Before running hooks on staged files, pre-commit saves unstaged changes
    as a patch named `patch<time>-<its pid>` in its cache folder, checks
    them out, and re-applies the patch afterwards. Its pid is this hook's
    parent's (`pid` defaults to os.getppid()). On Windows a launcher may sit
    in between (a console script is an .exe that starts python.exe as its
    child), so there the grandparent and great-grandparent are tried too,
    found with a Toolhelp snapshot; if that fails, only `pid` is tried. Not
    on Linux or macOS: there those are git and a shell, and pre-commit never
    deletes old patches, so one whose pid matches theirs would hold a file
    with no unstaged changes. Verified on macOS only. A file renamed in between
    is not where the patch expects it, so pre-commit cannot restore those
    changes and stops with an error. The file names are read with
    `git apply --numstat -z`, which applies nothing. Outside a pre-commit
    run, or with no unstaged changes, there is no such patch: empty set.
    This relies on how pre-commit names the patch; if that changes, the set
    is empty and such a file is renamed as before.
    """
    pid = os.getppid() if pid is None else pid
    environ = os.environ if environ is None else environ
    pids = [pid]
    while _is_windows() and len(pids) < 3 and pids[-1] is not None:
        pids.append(_parent_pid(pids[-1]))
    home = glob.escape(_pre_commit_home(environ))
    patches = []
    for candidate in pids:
        if candidate is not None:
            patches += glob.glob(os.path.join(home, f"patch*-{candidate}"))
    paths = set()
    for patch in patches:
        out = _git(root, "apply", "--numstat", "-z", os.path.abspath(patch))
        # records are `added<TAB>deleted<TAB>path`; a rename is
        # `added<TAB>deleted<TAB>`, then the old and new paths
        fields = (out or b"").split(b"\0")
        index = 0
        while index < len(fields):
            record = fields[index].split(b"\t", 2)
            index += 1
            if len(record) < 3:
                continue
            if record[2]:
                paths.add(os.fsdecode(record[2]))
            else:
                paths.update(os.fsdecode(f) for f in fields[index : index + 2])
                index += 2
    return paths


def check_repo(
    root,
    files,
    site_roots=("",),
    *,
    prefix=None,
    max_path=DEFAULT_MAX_PATH,
    disabled=frozenset(),
    check=False,
    tracked=frozenset(),
    held=frozenset(),
    temporary_index=False,
):
    """Check the sites in repo `root`; return a list of (path, issues, fixed).

    `files` are the repo-relative paths to consider (normally `git ls-files`)
    and `site_roots` the repo-relative folders holding a site ("" is the repo
    root). `prefix` is the server folder the repo is cloned into (see
    server_prefix(); by default the default server root, the repo's name and
    branch main). This is the programmatic entry point: it does no printing.

    Unless `check`, the .bes files the fix codes (E803-E805) apply to are
    renamed: with `git mv` when they are in `tracked`, otherwise with a
    plain filesystem rename. A file in `held` (see pre_commit_stashed_paths)
    is not renamed (E806); with `temporary_index` (see uses_real_index)
    nothing is (E806). Codes in `disabled` are dropped; for a fix code
    that also stops that part of the rename.
    """
    if prefix is None:
        prefix = server_prefix(
            DEFAULT_SERVER_ROOT, default_repo_name(root), DEFAULT_BRANCH
        )
    results = _Results()
    gathered = set()
    for site, site_files in _assign_sites(files, site_roots).items():
        config = read_site_config(root, site, files)
        if config.issue:
            results.issue(_join(site, SITE_CONFIG), *config.issue[1:])
        bes_paths = _check_layout(results, site, site_files, config)
        _check_ids(results, bes_paths)
        gathered.update(bes_paths)
    _check_limits(results, files, gathered, prefix, max_path, disabled)
    renamer = _Renamer(root, files, prefix, max_path, disabled, held)
    renamer.temporary_index = temporary_index
    for path in sorted(gathered):
        renamer.plan(results, path)
    renamer.apply(results, check, tracked)
    return results.as_list(disabled)


def main(argv=None, list_files=git_ls_files):
    """Execution starts here.

    `list_files(repo_root)` returns the repo-relative files to check; tests
    can pass their own instead of the default `git ls-files`.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="dry run: report what would be renamed, change nothing",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings (W8xx) as failures; default: advisory",
    )
    parser.add_argument(
        "--disable",
        default="",
        metavar="CODES",
        help="comma-separated check IDs to skip entirely, e.g. --disable W806",
    )
    parser.add_argument(
        "--site-root",
        action="append",
        default=[],
        metavar="DIR",
        help=(
            "a folder holding a site, relative to the current folder; repeat "
            "for a repo of several sites (default: the repo root)"
        ),
    )
    parser.add_argument(
        "--server-root",
        default=DEFAULT_SERVER_ROOT,
        help=f"the BES Server install folder (default: {DEFAULT_SERVER_ROOT})",
    )
    parser.add_argument(
        "--repo-name",
        help=(
            "the repo name the server names its clone after (default: the last "
            "part of the origin remote URL, or the repo folder's name)"
        ),
    )
    parser.add_argument(
        "--branch",
        default=DEFAULT_BRANCH,
        help=f"the branch the site syncs from (default: {DEFAULT_BRANCH})",
    )
    parser.add_argument(
        "--max-path",
        type=int,
        default=DEFAULT_MAX_PATH,
        metavar="N",
        help=f"longest allowed server path (default: {DEFAULT_MAX_PATH})",
    )
    args = parser.parse_args(argv)
    # a file name that is not UTF-8 holds lone surrogates; show them escaped
    # rather than fail on print
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")

    disabled = {
        code.strip().upper() for code in args.disable.split(",") if code.strip()
    }
    unknown = disabled - KNOWN_CODES
    if unknown:
        print(
            f"warning: ignoring unknown --disable code(s): {', '.join(sorted(unknown))}"
        )

    root = repo_root()
    if root is None:
        print("bes-siterepo-validate-layout: not in a git repo (git rev-parse failed)")
        return 1
    try:
        files = list_files(root)
    except OSError as err:
        print(f"bes-siterepo-validate-layout: {err}")
        return 1
    try:
        tracked = set(files if list_files is git_ls_files else git_ls_files(root))
    except OSError:
        tracked = set()
    site_roots = []
    for site in args.site_root or [root]:
        rel = os.path.relpath(os.path.realpath(site), os.path.realpath(root))
        if rel == os.pardir or rel.startswith(os.pardir + os.sep):
            print(f"bes-siterepo-validate-layout: --site-root {site} is outside {root}")
            return 1
        site_roots.append("" if rel == os.curdir else rel.replace(os.sep, "/"))

    issue_count, warning_count, fix_count = bes_common.report(
        check_repo(
            root,
            files,
            site_roots,
            prefix=server_prefix(
                args.server_root, args.repo_name or default_repo_name(root), args.branch
            ),
            max_path=args.max_path,
            disabled=disabled,
            check=args.check,
            tracked=tracked,
            held=set() if args.check else pre_commit_stashed_paths(root),
            temporary_index=not uses_real_index(root),
        )
    )
    if fix_count:
        print(
            f"\nrenamed .bes file(s) ({fix_count} fix(es)); tracked files are "
            "renamed with git mv, so the renames are staged: review them and "
            "commit again."
        )
    if warning_count:
        print(f"{warning_count} site layout warning(s).")
    if issue_count:
        print(f"{issue_count} site layout issue(s).")
    # E-codes and any rename always fail; warnings fail only under --strict
    return 1 if (issue_count or fix_count or (warning_count and args.strict)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
