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
Folder names are matched ignoring case, as on the Windows server.

Checks (E-codes fail the hook; W-codes are advisory unless --strict):

    E800  a .bes file in the .bes folder whose name does not start with a
          numeric ID followed by a space or hyphen (`42- Name.bes`,
          `42 Name.bes`); the server skips it
    E801  two or more .bes files in one site share an ID, compared as
          integers (0042 and 42 collide); each names the others
    E802  a .bes file's server path is over the limit and cannot be fixed:
          even `<ID> X.bes` is too long (the folders are), or it has no ID.
          Renaming a folder changes its .fxf or digest, so it is not done
    E803  fix: zero padding in the ID (0042- X.bes -> 42- X.bes)
    E804  fix: non-ASCII characters in the name, folded to ASCII
    E805  fix: the server path is over the limit; renamed `<ID> <Title>.bes`
    E806  a rename was skipped: the new name is taken, ignoring case (by a
          tracked file, another planned rename or an untracked file), the
          file has unstaged changes pre-commit set aside, or the rename failed
    W800  a .bes file outside the .bes folder; it is not gathered
    W801  a .bes file directly in the .bes folder, or deeper than
          <BesFileDir>/<fxf>/<digest>/ (server behavior undocumented)
    W802  a file in the .bes folder other than .bes or digest.xml (an .xsd
          too: bes-schema-validate already has the schemas)
    W803  a folder siteConfig.xml renames does not exist (has no files); a
          default name spelled out, as the template does, is not checked
    W804  a site with no content: no .bes files in the .bes folder and no
          files in the NonClient or Other folders (server files alone pass)
    W805  any other tracked file whose server path is over the limit; it is
          not renamed, since actions may refer to it by name
    W806  an ID outside 1..2147483647 (the range is undocumented)
    W807  siteConfig.xml is not readable XML; the default folders are used

Server path: the server clones the whole repo to
`<server-root>\\RepositorySiteGather\\Sites\\<repo>_<branch>_<8 hex>\\Source\\`
and each file's path relative to the REPO root (not the site root) follows
that. It must be at most --max-path (259: MAX_PATH 260 includes the NUL),
counted in UTF-16 units. <repo> is the git repo's name (--repo-name, default
the origin remote's, else the repo folder's), not the BigFix site name.
Over-long paths fail on 11.0.7 even with Windows long paths enabled.

Auto-fix (the default; --check is a dry run that reports and changes
nothing): each .bes file in the .bes folder is renamed at most once, combining
E803, E804 and, if the path is still too long, E805. E805 builds
`<ID> <Title><extension>` (no hyphen) from the first content object's
<Title> (or the current name without its ID, if there is none), made ASCII
and Windows-safe, cut to fit, with trailing spaces, dots and hyphens dropped.
A name that already fits is left alone, even when it differs from <Title>.
The ID never changes and no file moves between folders. Files without an ID
are not given one: assigning IDs is a policy decision (CommunityContent uses
a counter file; max+1 would reuse the IDs of deleted content), so there is
no --assign-ids.

How files are renamed: a tracked file with `git mv`, anything else with a
plain rename. git mv stages the rename, so the next commit carries both the
new name and the removal of the old one; a plain rename would leave an
unstaged deletion plus an untracked file, and `git commit -a` (or
`git add -u`) would then commit the deletion alone, dropping the content
from the repo. Inside a pre-commit run the work tree matches the index,
because pre-commit stashed unstaged changes in a patch it re-applies after
the hooks; it cannot re-apply that patch to a renamed file, so a file named
in the patch is left alone (E806; see pre_commit_stashed_paths). Any rename
makes the hook exit 1, so the commit stops and the renames can be reviewed.

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
        "W800",
        "W801",
        "W802",
        "W803",
        "W804",
        "W805",
        "W806",
        "W807",
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

    ASCII_TABLE first, then Unicode NFKD with the combining marks dropped
    (\u00e9 -> e, \u2122 -> TM); a character with no Windows-safe ASCII
    equivalent becomes `_`. ASCII characters are left as they are.
    """
    out = []
    for char in text:
        if char.isascii():
            out.append(char)
        elif char in ASCII_TABLE:
            out.append(ASCII_TABLE[char])
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
    except (OSError, etree.XMLSyntaxError):
        return None
    return "".join(titles[0].itertext()) if titles else None


def _within(rel, folder):
    """`rel` relative to `folder` if it is inside it, else None.

    Compared case-insensitively: the server runs on Windows, where
    `fixlets/` and `Fixlets/` are the same folder.
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
    for path in site_files:
        rel = _within(path, site)
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
            continue
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


def _check_lengths(results, files, gathered, prefix, max_path):
    """W805 and E802: server paths over `max_path`.

    `gathered` are the .bes files in a site's .bes folder; the rename fix
    can shorten those, so only one even the shortest name cannot bring
    under the limit is reported here (E802). Every other tracked file is a
    W805: the server clones the whole repo, so a long path anywhere breaks
    the sync, but actions may refer to those files by name.
    """
    for path in files:
        length = server_path_length(prefix, path)
        if length <= max_path:
            continue
        over = f"server path is {length} characters, over the {max_path} limit"
        if path not in gathered:
            results.issue(
                path,
                "W805",
                f"{over}; shorten it by hand (not renamed automatically, since "
                "actions may refer to it by name)",
            )
        elif _id_of(path) is None:
            results.issue(
                path,
                "E802",
                f"{over}, and with no numeric ID there is no short name to "
                "rename it to",
            )
        else:
            shortest = _shortest_name(path)
            shortest_length = server_path_length(prefix, shortest)
            if shortest_length > max_path:
                results.issue(
                    path,
                    "E802",
                    f"{over}, and even the shortest name ({shortest}) would be "
                    f"{shortest_length}: the folders are too long. Renaming a "
                    "folder changes its .fxf or digest, so this is not fixed",
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
        if "E805" not in self.disabled and length > self.max_path:
            extension = os.path.splitext(name)[1]
            stem = _join(folder, f"{number} ")
            room = self.max_path - self._length(stem + extension)
            if room >= 1:  # otherwise _check_lengths reported E802
                title = read_title(os.path.join(self.root, path))
                if title is None or not safe_title(title):
                    # the current name, without its ID prefix
                    title = os.path.splitext(name[len(digits) :])[0].lstrip(" -")
                short = safe_title(title)[:room].rstrip(" .-")
                if short:
                    new = f"{number} {short}{extension}"
                    reasons.append(
                        (
                            "E805",
                            (
                                f"server path is {length} characters, over the "
                                f"{self.max_path} limit"
                            ),
                        )
                    )
                else:
                    results.issue(
                        path,
                        "E802",
                        f"server path is {length} characters, over the "
                        f"{self.max_path} limit, and there is no title to "
                        "build a shorter name from",
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
                f"not renamed to {new}: it has unstaged changes that pre-commit "
                "set aside for this run, and could not restore to a renamed "
                "file; stage or stash them, then run again",
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
                text=True,
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


def pre_commit_stashed_paths(root, pid=None, environ=None):
    """Return the files whose unstaged changes pre-commit set aside for this run.

    Before running hooks on staged files, pre-commit saves unstaged changes
    as a patch named `patch<time>-<its pid>` in its cache folder, checks
    them out, and re-applies the patch afterwards. Its pid is this hook's
    parent's (`pid` defaults to os.getppid()). A file renamed in between
    is not where the patch expects it, so pre-commit cannot restore those
    changes and stops with an error. The file names are read with
    `git apply --numstat -z`, which applies nothing. Outside a pre-commit
    run, or with no unstaged changes, there is no such patch: empty set.
    This relies on how pre-commit names the patch; if that changes, the set
    is empty and such a file is renamed as before.
    """
    pid = os.getppid() if pid is None else pid
    environ = os.environ if environ is None else environ
    pattern = os.path.join(glob.escape(_pre_commit_home(environ)), f"patch*-{pid}")
    paths = set()
    for patch in glob.glob(pattern):
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
    _check_lengths(results, files, gathered, prefix, max_path)
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
