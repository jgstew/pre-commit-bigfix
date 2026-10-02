# Release Notes

## v1.9.0

### Added (bes-relevance-convert-group)

- **`bes-relevance-convert-group`**, a new hook. It rewrites a
  console-exported `<GroupRelevance>` into plain `<Relevance>`. With
  `JoinByIntersection="true"` you get one `<Relevance>` per search component.
  With `"false"` you get one `(a) OR (b)` `<Relevance>`, or the bare statement
  when there is only one component. Codes `E700`-`E704` and `W700`; see the
  README. A `SearchComponentGroupReference` is not converted yet (`E701`).
- **`JoinByIntersection`.** A missing attribute converts when the group has
  a single component, because AND and OR then mean the same thing. With two
  or more components it is `E702`, and the message says which attribute to
  add. BES.xsd makes the attribute optional and documents no default.

### Changed (BES.xsd check on every auto-fix)

This changes four existing hooks: a commit they used to fix and pass can now
fail with a new error instead.

- **Each hook that rewrites BES files now checks its fixes against BES.xsd
  before writing**, one fix pass at a time. A pass that would turn a
  schema-valid file into an invalid one is not written, and the other passes
  still are. For example, sha256 values downloaded for `E401` are kept even
  if an unrelated fix is held back. Each hook reports a held-back pass with a
  new error: `E222` (`bes-conventions-check`), `E304`
  (`bes-actionscript-lint-schclass`), `E404`
  (`bes-actionscript-validate-prefetch`), `E526`
  (`bes-actionscript-validate-script`), or `E704`
  (`bes-relevance-convert-group`). In `bes-conventions-check` all the
  per-block fixes form one pass, and `bes-actionscript-lint-schclass` has only
  one pass, so there one bad fix holds back the others with it.
- A file that already fails validation is still fixed, since
  `bes-schema-validate` reports it either way. Once a pass makes such a file
  valid, the passes after it are checked as usual. Disabling the code (for
  example `--disable E222`) writes the fix anyway.
- The check calls `validate_bes_xml.validate_bes()` with only the schemas
  bundled with that package, so a repo-local `.xsd` can neither stand in for
  `BES.xsd` nor make an unknown root checkable. `BESOJO.xsd` is used for an
  `.ojo` file and `BESDomain.xsd` for a `.BESDomain` file. Nothing is printed
  while validating.
- This needs **`validate_bes_xml >= 2.2.1`** (which brings `lxml >= 5`). The
  published hooks install it. If it is missing, for example when
  `bes_conventions_check.py` is run as a bare script, the fixes are written
  unchecked and a one-line warning on stderr says to install it.

### Changed (shared helpers)

- The helpers the hooks used to copy (file reading and writing with
  line-ending preservation, `.bes` discovery, the report printer, the
  mustache-template pattern) now live in `pre_commit_bigfix/bes_common.py`.
  Behavior is unchanged.

## v1.2.2 - v1.8.4

These releases were recorded together and are not split by version.

### Changed (bigfix-relevance-analyzer 1.13.3)

- **`bes-relevance-lint`** now requires `bigfix-relevance-analyzer >= 1.13.3`.
- **`W602`** reports more: besides a `whose` filter on a singular spelling, it
  now flags an unfiltered singular in the middle of a chain where a plural is
  built from it, such as `exists values of setting "x" of client`. That form
  errors when the setting is absent; `settings "x"` answers False. Expect new
  W602 warnings after upgrading. They are advisory unless `--strict` is set.

### Added (bigfix-relevance-analyzer 1.13.3)

- **`bes-relevance-lint` suggested fixes.** When the analyzer can safely
  rewrite a whole statement (today, the singular spellings behind `W602`), the
  fixed statement is printed once under that statement's first finding as
  `suggested fix: ...`. Files are not rewritten.

### Removed (auto-fix review)

- **`bes-actionscript-validate-script` `W504`** is retired. It warned that the
  `dos` verb was deprecated, but the
  [BigFix reference](https://developer.bigfix.com/action-script/reference/execution/dos.html)
  doesn't deprecate it. Its suggested replacement, `waithidden cmd.exe /c`,
  also behaves differently: `dos` shows its window and ends the action
  script when the command fails. `dos` is no longer reported, and the code
  won't be reused. A leftover `--disable W504` now only prints the
  unknown-code notice.

### Fixed (auto-fix review)

- **`bes-relevance-lint` `W605`** (an ActionScript substitution whose value is
  an opaque object with no text form) was reported but missing from the
  module docstring and the hook description. It is now documented in both,
  and a test fails if any reported code is missing from the docstring, the
  hook description, or the README table.

### Added (auto-fix review)

A review of every check without an auto-fix. A fix was added only where the
right rewrite can be worked out from the file itself and keeps the author's
intent. Each new fix was run over jgstew/bigfix-content and a 2,987-file
server export, and a second run changed nothing.

- **`bes-conventions-check`**:
  - `E200`: a missing ActionScript MIMEType is set to the Windows-Shell
    default, and an allowed MIMEType in the wrong case is respelled. Text
    inside a CDATA body is never touched.
  - `E201`: an unambiguous year-first SourceReleaseDate (`2026-7-4`,
    `2026/07/14`, `2026-07-14T...`) becomes `YYYY-MM-DD`. A month/day-first
    date is never guessed at.
  - `E202`/`E216`: a timestamp that is only badly formatted is respelled.
    That covers padding, capitalization, full month or day names, and a
    `GMT`/`UTC`/`Z` zone or a `+HH:MM` offset. A day-of-week that is wrong
    for the date is **dropped**, not recomputed.
  - `E209`: a `cve-` prefix is uppercased. Several `<CVENames>` elements are
    not merged.
  - `E219`: an evaluation period is zero-padded (`6:00:00` -> `06:00:00`).
  - `W216`: a case-only mismatch (`HIGH` -> `High`) is respelled.
  - `W220`: DownloadSize is set to the knowable prefetch total, with unzip
    left out.
- **`bes-actionscript-validate-script`**:
  - `E524`: `else if` is joined into `elseif`, unless a stray `endif` shows
    that an `if` really was nested inside the `else`.
  - `W505`: a waiting cmd.exe's `/k` becomes `/c`, or a missing `/c` is
    inserted after cmd's leading switches. `/r` and unknown switches are left
    alone.
  - `E521`: a bracketed but unquoted registry key is quoted.
- **`bes-actionscript-lint-schclass`**: new `--auto-fix` (on by default when
  files are given) lowercases `W302` verbs and `W303` override options. This
  hook's first and only fix, and it changes case only.
- **`bes-actionscript-validate-prefetch`**:
  - `E403`: `sha2:` in front of a 64-hex value becomes `sha256:`, and a space
    directly after the URL becomes `%20`.
  - Under the opt-in `--auto-fix-network`, an `http://` prefetch URL is
    switched to `https://` (the fix for conventions-check's `W207`). This
    happens only when the https copy is proven identical: its HEAD
    `Content-Length` must equal the line's size, checked before anything is
    downloaded, and then the size and every hash on the line must match.
    Otherwise the new warning **`W407`** is reported and the line stays on
    http.

Found by a false-positive/false-negative sweep of a BigFix server export
(2,987 `.bes` files), each change compared before/after against it,
bigfix/CommunityContent and jgstew/bigfix-content.

### Added (server-export sweep)

- **`bes-conventions-check` `W221`**: a Relevance that is true *until* a
  client setting has value V (`not exists settings "N" whose ("V" = value of
  it) of client`, or `value of setting "N" of client != "V"`) while the
  action sets N to something else, so the content stays relevant after it
  runs. Branches waiting for several values are fine when the action sets
  one of them. Marker: `setting-value-ok`.
- **`bes-actionscript-validate-prefetch` `E403`**: text the prefetch syntax
  doesn't define. That includes a stray token (an AutoPkg template's
  `vs_SSMS.exe; filename*=UTF-8''vs_SSMS.exe`), a misspelt field (`sha2:`),
  and an unencoded space splitting the URL. The reference parser silently
  drops such text. A space-separated trailing `// comment` is allowed.

### Changed (server-export sweep)

- **`bes-conventions-check` `E212`/`W212`** also catch a top-level
  `true OR ...` (always true) or `false AND ...` (always false), e.g. a test hack
  left on a destructive BitLocker task.

### Fixed (server-export sweep)

- **`bes-actionscript-lint-schclass` `E301`**: an escaped `{{` (or `}}`
  inside a substitution) was reported as an unclosed substitution. The two
  ActionScript hooks now apply the same escape rule.
- **`bes-conventions-check` `W220`**: a prefetch mirror (same hashes and
  size, another URL) is counted once.
- **`bes-actionscript-validate-script` `E512`**: a `>>` append to an existing
  `__Download` file is not a second declaration.
- **`bes-actionscript-validate-script` `W505`**: `/k` is only flagged under a
  verb that waits (`wait`/`waithidden`), not `run`/`runhidden`.

Found by a false-negative sweep of every hook over
[bigfix/CommunityContent](https://github.com/bigfix/CommunityContent) and
jgstew/bigfix-content, each change compared before/after against both.

### Added

- **`bes-actionscript-validate-script` `E525`**: a `folder create` /
  `folder delete` path that is not double-quoted. It's required even when
  today's value has no spaces, because a user profile or parameter value can
  contain one. Auto-fixed by wrapping the path in quotes (`&quot;` in an
  entity-escaped body).
- **`bes-actionscript-validate-script` `W508`**: a `parameter "X"` whose
  name occurs nowhere else in the whole file: not assigned, not queried,
  not in a Description form. This is almost always copy-paste from a sibling
  fixlet, and the substitution fails at runtime. The platform-supplied
  `action issue date` is exempt.
- **`bes-conventions-check` `W219`**: a `<SourceReleaseDate>` later than the
  `x-fixlet-modification-time`, which is a sign of a hand edit that missed a
  field.
- **`bes-actionscript-validate-prefetch` `W406`**: a prefetch whose declared
  name ends in a different extension from the URL's file, e.g. `<sha1>.msi`
  fetched from `ccsetup531.exe`. The extension decides how the file is run or
  unpacked, so this is usually a copy-paste slip. An extension is any
  trailing `.` plus 1-4 characters that include a letter. Not compared: names
  or URLs without an extension (such as sha1-named prefetches), server-side
  script URLs (`download.php`), and a URL that is the name with one more
  extension appended (`7z.dll.txt`, to get past web filtering). Found 12
  CCleaner fixlets and both Inkscape fixlets in CommunityContent.
- **`bes-conventions-check` `W220`**: a `<DownloadSize>` that doesn't match
  the total of the prefetch sizes. Only checked when that total is knowable:
  a single prefetching action, no conditional prefetch, literal sizes, and no
  dynamic `download`. The `unzip.exe` utility may be left out.

### Changed

- **`bes-actionscript-validate-script` `W506`** now covers a `move`/`copy` of
  *any* source (a download, a file, a scratch file) onto an undeleted
  destination, and is **auto-fixed** by inserting `delete <destination>`
  before the command. More kinds of clearing are recognized: a `delete` that
  looks the same file up by relevance, a `folder delete` of a substituted
  ancestor, and a shell `rm`/`del` naming the path.
- **`bes-actionscript-validate-script` `E508`** now also checks
  `createfile until` content for an unclosed `{`. The agent substitutes
  relevance there too, so a literal brace must be written `{{`.
- **`bes-conventions-check` `W202`** auto-fix: a missing SourceReleaseDate is
  now filled with the date of the content's existing modification time
  instead of today, so the fix no longer makes it later than the
  modification time (`W219`).

### Fixed

- **`bes-actionscript-validate-script`**: a trailing `// comment` on an
  `if`/`elseif`/`else`/`endif`, `begin`/`end prefetch block` or `override`
  line is now ignored. Before, `endif // ...` wasn't recognized as an endif,
  causing 23 cascading `E500`s in CommunityContent, and `else // ...` was read
  as a command. Command lines are unchanged, since `cscript //Nologo` uses
  `//` for its own options.
- **`bes-conventions-check` `E212`/`W212`** now see a literal `true`/`false`
  behind a `/* ... */` comment or wrapping parentheses (e.g.
  `true /* not exists settings ... */`).

### Changed

`bes-relevance-lint` picks up one more rule added in `bigfix-relevance-analyzer`
1.12.4: `W605`, an ordinary ActionScript `{...}` substitution whose value is an
opaque object with no text form (the `bes *` family, `dmi *`/`smbios *`
structs, `xml dom *`, `active directory *` objects, `sqlite *`, and bare
objects like `dictionary`, `registry`, `process`, `socket`, `connection`) --
unlike `E608`'s hard error on a plural value, nobody has confirmed one of
these actually fails at runtime, so it is a warning. Requires
`bigfix-relevance-analyzer >= 1.12.4`.

`bes-conventions-check`'s `W216` no longer accepts `Unspecified` as a
`<SourceSeverity>`: it carries no information an empty SourceSeverity does
not, so `Unspecified` (any case, CDATA-wrapped or not) and the console's
bracketed `&lt;Unspecified&gt;` are now auto-fixed to an empty element. A repo
that wants to keep it can list `Unspecified` in `--severity-values`. In
bigfix/CommunityContent this affects about 1,600 files.

### Added

`bes-conventions-check` picks up `E221`: a `// comment` style JavaScript
comment inside a `<Description>`'s `<script>` block. When a `.bes` file is
converted to FXF (the path Prop-tool / Git-based sites take), newlines inside
the Description are collapsed onto one line, so everything after a `//` on
that collapsed line - including real code that follows it - is silently
swallowed as part of the comment. Auto-fixed by default (not `--strict`-gated,
like `E207`) by rewriting the comment as `/* comment */`, which survives the
collapse; a comment whose text itself contains `*/` cannot be wrapped in a
single block comment and is left as an unfixed error. Only `//` outside a
string/template literal, regex literal, and existing `/* */` block comment is
flagged, so a `//` in an ordinary `http://` URL or a protocol-relative href
is not touched, and the legacy `<!-- ... //-->` HTML-comment-hiding idiom is
recognized and left alone. Opt out with the `script-comment-ok` marker.
Closes [#17](https://github.com/jgstew/pre-commit-bigfix/issues/17).

`bes-actionscript-validate-script` picks up `E524`: `else if` written as two
words instead of `elseif`. It matched neither `else` nor `elseif`, so it was
silently read as an unrelated command and nothing was reported, although the
branch logic was not what the author wrote. It is now tracked as the `elseif`
it was meant to be, so the rest of the `if`/`endif` pairing does not cascade,
and belongs to the `actionscript-if-ok` family. (`E513` is not reused: it was
retired when it became `W507`.)

`bes-conventions-check` picks up `--prefetch-url-schemes`: the URL schemes a
`W206` prefetch line may use, comma-separated and case-insensitive. The
default is `http,https,SWDProtocol,RedHatProtocol`. The shape check used to
hard-code `https?://`, so console uploads (`SWDProtocol://127.0.0.1:52311/...`)
and RHEL plug-in URLs (`RedHatProtocol://...`) were reported as malformed.

### Fixed

`bes-actionscript-validate-script` no longer reports a false `E512` duplicate
download name when several files are moved or copied into the same
`__Download` subdirectory (`move __Download\a.msp "__Download\Dir\Sub\a.msp"`).
The destination's first path segment was read as a download named `Dir`, so
each move looked like another write of the same file. A nested destination
now counts as a subdirectory: it still satisfies `W507` for later
`__Download\Dir\...` references, but is never compared for `E512`.
Fixes [#21](https://github.com/jgstew/pre-commit-bigfix/issues/21).

The following were found by running every hook in `--strict` mode over
[bigfix/CommunityContent](https://github.com/bigfix/CommunityContent) (9,719
`.bes` files):

- **`bes-conventions-check` `W204` auto-fix corrupted ActionScript.** Under
  `--strict --auto-fix`, an un-wrapped body was wrapped in CDATA without being
  XML-unescaped first. Inside CDATA an entity is literal text, so a body using
  `&quot;`, `&apos;` or a numeric reference was rewritten so the agent received
  `&quot;` instead of `"`. That covers about 8,000 of CommunityContent's
  un-wrapped bodies. The body is now unescaped before wrapping, and a body
  whose decoded text contains `]]>` is left unwrapped.
- **`bes-conventions-check` `E206`** parsed an `action-ui-metadata` value
  without decoding it, so every value written outside CDATA
  (`{&quot;version&quot;:...}`) was reported malformed. CDATA content is
  still taken literally.
- **Files silently skipped by all four hooks.** The mustache-template
  detector matched `msiexec /x{{{GUID}}` (an escaped `{` before an MSI
  product code), so the whole file was skipped as an unrendered template.
  GUID-shaped contents no longer count as placeholders.
- **`bes-actionscript-validate-script` `W507`** now recognizes four more ways
  a file gets into `__Download`: `folder create "__Download\<dir>"`; an
  archive extractor (`unzip`, `7z`/`7za`/`7zr`, `expand`, `tar`) run against
  `__Download`, whose output names are unknowable, like `extract`;
  `move <elsewhere> __Download\X`; and it no longer reads
  `__Global\__Download\...` (the client's shared download cache) as this
  action's download folder.
- **`bes-actionscript-validate-script` `W506`** counts `move <destination>
  <backup>` as clearing the destination, as a `delete` does (a `copy` does
  not), treats `{parameter "X" of action}` and `{parameter "X"}` as the same
  path, and compares Windows-style paths (drive letter or backslash)
  case-insensitively. Bare names and POSIX paths stay case-sensitive.
- **`bes-actionscript-validate-script` `E517`** no longer reports a parameter
  defined by `action parameter query`, or tested with `exists parameter "X"`
  (the supported way to give a parameter a default), as used before it is
  assigned.
- **`bes-actionscript-validate-script` messages that quote another line**
  (`E512`, `E516`, `E517`, `E522`, `W501`, `W502`) counted from the start of
  the ActionScript body, while the issue itself used a file line. Both now
  use file lines.
- **`bes-actionscript-lint-schclass` `W301`**: ActionScript has no escape
  character, but the console display grammar treats `\"` as an escaped quote,
  so a closed string ending in a backslash (`folder create "C:\Bes\"`,
  `"__Download\"`) was reported as unterminated. The override grammar drops
  the escape. A `regset`/`regset64` value, which is `.reg`-file syntax where
  `\"` and `\\` are escapes, is still scanned with them, and `appendfile`
  content (raw file text) is exempt.
  Fixes [#16](https://github.com/jgstew/pre-commit-bigfix/issues/16).

### Changed

`bes-relevance-lint` picks up two rules added in `bigfix-relevance-analyzer`
1.10.1: `E607`, a path given to the linter that does not exist or could not
be read (always an error - a misspelled path used to lint nothing silently
and pass), and `W602`, a `whose` filter written on a singular spelling where
the plural reads safer (the sibling of `W601`, for the shape where a singular
collapse can't raise `Singular expression refers to non-unique object.` but
still raises on no match). Requires `bigfix-relevance-analyzer >= 1.10.1`.

`bes-relevance-lint` picks up two more rules added in
`bigfix-relevance-analyzer` 1.11.0, both errors: `E608`, a value that does not
fit the kind of site it was extracted from (a `<Relevance>` body that is not a
boolean, or an ActionScript `{...}` substitution that is plural - the content
cannot work either way), and `E609`, a statement mixing inspectors that exist
only in client relevance with inspectors that exist only in session relevance,
which no engine can answer. Requires `bigfix-relevance-analyzer >= 1.11.0`.

`bes-actionscript-lint-schclass`'s `E300` now quotes the whole offending line
instead of its first whitespace-delimited run, and adds a "did you mean"
naming the nearest known command verbs: `action log commands` suggests
`action log command`, a bare `action log` suggests `action log all` and
`action log command`, and a bare `action launch preference` suggests its two
priorities. The verbs come from the merged schclass grammar, so the
suggestions track the vendored file with no list to maintain, and a line
whose first word begins no known command (`badverb y`) still gets no
suggestion. The plural and bare forms remain `E300` -- they are not valid
ActionScript; `action log all` and `action log command` were already
accepted. Closes
[#15](https://github.com/jgstew/pre-commit-bigfix/issues/15).

## v1.2.1

### Added

**New hook: `bes-relevance-lint`** - the first check in this repo that looks
*inside* relevance instead of treating `{...}` as an opaque lexer state. It
hands every `<Relevance>` body, CustomRelevance `<SuccessCriteria>`, Analysis
`<Property>` and ActionScript `{...}` substitution to
[bigfix-relevance-analyzer](https://github.com/jgstew/bigfix-relevance-analyzer),
which parses it, binds `it`, resolves inspectors against the client dumps,
type-checks the result and scores its evaluation cost: `E600` parse failure,
`E601` unlexable text, `E602` unbound `it`, `E603` type error, `E604`
complexity over `--max-score`, `E605` evaluation cost over
`--max-evaluation-cost`, `E606` a walk stopped at `--max-depth`, `W600` an
unknown inspector name, `W601` a singular property over a possibly-plural
object.

Tuned against the 1,108 `.bes` files in `bigfix-content`: `W601` fires 6,127
times there, so the hook declaration disables it by default (`--enable W601`
switches it back on), while the whole rest of the corpus produces 8 findings -
a signal worth reading. Unparsable XML is skipped (`bes-schema-validate` owns
validity), a file opts out with `pre-commit-skip: bes-relevance-lint`, and
there is no auto-fix.

This hook requires **Python 3.11+**; the dependency carries an environment
marker so the other six hooks stay installable on 3.8-3.10, and on an older
interpreter the hook prints why it cannot run and skips instead of failing. Closes
[#14](https://github.com/jgstew/pre-commit-bigfix/issues/14).

New `bes-conventions-check` checks, found by surveying the non-ActionScript
content of the same 1,043 `.bes` files in `bigfix-content/fixlet` used for the
v0.9.0 `bes-actionscript-validate-script` survey, this time for defect
patterns outside ActionScript bodies:

- **`E217`**: a `<SuccessCriteria Option="CustomRelevance">` body that is
  empty or the literal `false` (can never succeed), or a non-CustomRelevance
  `<SuccessCriteria>` with a non-empty body (silently ignored by BigFix). Found
  one real hit in `bigfix-content`: a CustomRelevance success criterion whose
  body is literally `false`.
- **`E218`**: two `<Action ID="...">` / `<DefaultAction ID="...">` elements in
  one content object sharing the same ID - the BES.xsd types `ID` as
  `xs:normalizedString`, not `xs:ID`, so a duplicate passes schema validation.
- **`E219`**: an `x-relevance-evaluation-period` value that is not a valid
  `HH:MM:SS` duration (matched case-insensitively, since the corpus has both
  `x-relevance-evaluation-period` and `X-Relevance-Evaluation-Period`).
- **`W212`**: a `<Relevance>` that is the literal `false` (case-insensitive) -
  it never applies to any endpoint. Advisory rather than an error like `E212`
  (literal `true`), since the corpus's hits are almost all intentional
  never-deployable "library" content.
- **`W213`**: a `<Relevance>` with leading/trailing whitespace (fixable ->
  trimmed; a CDATA-wrapped Relevance is left untouched, as with `Title`/`W209`).
- **`W214`**: a `<Title>` containing a `TODO`/`FIXME` marker - several
  `bigfix-content` fixlets ship a title like `... - Windows  TODO:testing`.
- **`W215`**: a Task/Fixlet `<Description>` that is empty or missing, distinct
  from `E204`'s boilerplate-placeholder check.
- **`W216`**: a non-empty `<SourceSeverity>` that is not one of
  Low/Moderate/Important/Critical/Unspecified (exact case) - the corpus has
  `high`, `High`, and `Recommended`, none of which BigFix treats specially.
  The default vocabulary can be replaced with a new `--severity-values`
  flag (a comma-separated, exact-case list), for repos that use a different
  severity scheme.
- **`W217`** (only under the new `--check-filename` flag, off by default): a
  file's basename does not match its first content object's `<Title>`,
  sanitized for filename-illegal characters. Opt-in because several
  `bigfix-content` files deliberately diverge (versioned titles, generated
  content).

`W213` and `W215` are fixable/scoped via the existing `relevance-ok` and
`description-ok` markers respectively; the rest get their own new markers
(`success-criteria-ok`, `action-id-ok`, `evaluation-period-ok`, `severity-ok`,
`filename-ok`). See the module docstring in
[bes_conventions_check.py](pre_commit_bigfix/bes_conventions_check.py) for the
full list.

Further checks in both content hooks, found by surveying a second corpus: the
2,986 `.bes` files (2,743 Tasks, 112 Fixlets, 91 Analyses, 28 ComputerGroups,
12 Baselines) exported from a live BigFix instance in
`bigfix_backup_plugin_jgstew/export`. Unlike `bigfix-content`, roughly two
thirds of that corpus is machine-generated (AutoPkg recipes), so a single
template defect repeats thousands of times; each check below was measured
against the whole corpus and its hits reviewed before being kept.

New `bes-conventions-check` checks:

- **`E220`**: two `<Property>` entries in one `<Analysis>` sharing a `Name` or
  an `ID` - reporting cannot tell two same-named properties apart, and the API
  addresses a property by its ID. Two real hits, both authoring slips made in
  the console (`BES_Client_Info`, `DEX_relevance_draft`). New
  `analysis-property-ok` marker.
- **`W218`**: a `<PreLink>`/`<Link>`/`<PostLink>` containing a run of 2+
  spaces. The three are assembled into one sentence in the console, and the
  gap is almost always where a generator substituted an empty product name -
  130 hits, e.g. `<PostLink> to deploy  v11.3.2.</PostLink>` and
  `... to uninstall Microsoft SQL Server  2016  Policies CTP3.2`. Deliberately
  not auto-fixed: the missing word is what needs restoring, not the space. New
  `link-text-ok` marker.
- **`W209`** now also covers an internal run of 2+ spaces in a `<Title>` (40
  hits, mostly `... - Windows  TODO`), and its auto-fix collapses such runs to
  a single space alongside the trim and de-tab it already did.

New `bes-actionscript-validate-script` checks:

- **`W505`**: a `wait`/`run` of cmd.exe that passes a command line but no `/c`
  (or `/k`). Without the switch cmd.exe opens an interactive shell and never
  runs the command, so the action reports success having done nothing. Nine
  hits, all real (`wait cmd.exe __Download\vs_setup.exe --nocache ...` in the
  Visual Studio tasks, and one `waithidden CMD __Download\replace_file.bat`).
  An executable merely *ending* in `cmd` (`firewall-cmd`, `NirCmd`) is not
  matched. New `actionscript-cmd-ok` marker.
- **`W506`**: a `move`/`copy` of `__createfile`/`__appendfile` onto a
  destination that is not deleted earlier in the body. Both verbs fail when
  the destination already exists, so the action works once and fails on every
  later run. Nine hits. Two exemptions keep it quiet on correct content: a
  destination inside the action's own download folder (action-scoped, not
  persistent) and a `folder delete` of an ancestor directory. New
  `actionscript-scratch-dest-ok` marker.
- **`E523`**: an `action uses wow64 redirection` argument that is not `true`,
  `false`, or a `{...}` substitution. Zero corpus hits - a guard rail on a
  line whose only valid shapes are these, added alongside `E520`/`E521` under
  the existing `actionscript-command-shape-ok` marker.

A check considered and **not** added: `appendfile` without a preceding
`delete __appendfile`. All 162 apparent violations turned out to be one
baseline that does clear the file, spelled as the fully-qualified
`"{(client folder of current site as string) & "/__appendfile"}"` rather than
the bare token - leaving no real hits and a demonstrated false-positive trap.

`bes-actionscript-validate-script` gets its first auto-fix:

- **`--auto-fix` (`W503`)**: rewrites every wrong-case `__download`,
  `__createfile`, or `__appendfile` reference in place to its canonical
  spelling. On by default when files are given (as pre-commit does), off
  when auto-discovering, matching the sibling hooks' `--auto-fix` convention.
  No other check in this hook is auto-fixable.

### Changed

- **`E513` downgraded to `W507`**: a `__Download\<name>` consumer reference
  with no matching prefetch/download producer is now advisory, not a hard
  failure. It fired too many false positives against real content to block a
  commit on; the check logic, gating (skipped whenever any producer's names
  are unknowable), and `actionscript-download-ok` marker are unchanged.
- **`W505`** now also flags `cmd.exe` invoked with `/k` instead of `/c`. `/k`
  does run the command, but leaves the shell open afterward; under the BES
  client (SYSTEM account, no interactive desktop) that shell never exits, so
  the action hangs instead of completing rather than silently doing nothing
  like the no-switch case. `/c` is the only switch that lets `cmd.exe` exit;
  `/c` alongside `/k` still passes, since `/c` wins.

### Fixed

The mustache-template skip in **all four hooks** no longer swallows real
content. `{{ ... }}` was matched with `re.DOTALL`, so any file containing a
`{{` anywhere was skipped entirely - but `{{` is also the ActionScript escape
for a literal `{`, which heredoc payloads (YARA rules, JSON, C#) contain
routinely. The pattern now matches only an identifier-like placeholder
(`{{name}}`, `{{ vendor }}`), so genuine `*.bes.mustache` templates are still
skipped while a task like `OpenSSL 3.0.0 - 3.0.6 Detection - YARA Scan` is
checked for the first time. A new cross-module test keeps the four patterns
identical. One known limit remains: a minified JavaScript payload containing
`{{this.stateChangeEl}}` is still indistinguishable from a placeholder.

More `bes-actionscript-validate-script` false positives, found the same way
v0.8.1's were:

- **`E520`**: the documented `setting delete "name" on "{...}" for
  client|user|action` deletion shape is now recognized alongside the
  `setting "name"="value" on ...` assignment shape it already accepted.
- **`E518`**: a literal `continue if false` (any case) is no longer flagged -
  a documented idiom for forcing a branch to fail unconditionally, e.g. in
  the `else` of an `if`/`else`/`endif`. `continue if true` is still flagged
  (it always continues, so the check does nothing), and `pause while` gets no
  such exception at all (`true` hangs forever, `false` never pauses).
- **`E513`**: a `__Download\<name>` consumer reference containing a shell
  glob wildcard (`*` or `?`, e.g. `__Download\mysql*rpm` for a versioned
  filename) is no longer flagged - the shell matches it at runtime, not this
  checker. The skip is per-reference, not a whole-body knowability escape
  hatch.
- **`E522`**: a line starting with `{` inside an open `override wait`/
  `override run` block now counts as an option line, not the closing
  command - a `{...}` relevance substitution can itself evaluate to a
  `keyword=value` option (e.g. picking `hidden=true` vs `completion=none` by
  OS).
- **`E508`/`E509`**: an `appendfile <content>` line is now exempt from both -
  everything after the verb is one line of raw file content written out
  verbatim, the same as `createfile until` heredoc content, so
  `appendfile }` (appending a literal `}`) no longer misreports as an
  unbalanced brace.

## v0.9.0

### Added

New `bes-actionscript-validate-script` checks, found by surveying all 7,069
ActionScript bodies across 1,043 `.bes` files in `bigfix-content/fixlet` for
defect patterns the hook did not yet cover:

- **`E516`**: a second `parameter "name" = ...` assignment to the same name
  that can co-execute with an earlier one (the same conditional-context rule
  `E512` uses). Action parameters are write-once; the second assignment
  silently overwrites the first.
- **`E517`**: a `parameter "name"` reference before that name's assignment
  elsewhere in the body - an ordering bug, since the substitution evaluates
  to empty at that point. A name never assigned in-script (a secure
  parameter from the Description page, say) is not flagged.
- **`E518`**: a `continue if` or `pause while` condition that is not a
  `{...}` relevance substitution - the same rule `E514` applies to `if`/
  `elseif`, extended to these two other condition-bearing verbs.
- **`E519`**: a command references `__createfile` or `__appendfile` but the
  body has no matching `createfile until` / `appendfile` line anywhere - the
  `E513` rule reapplied to these two scratch-file verbs, with the same
  `delete`/`folder delete` cleanup exemption.
- **`W503`**: a `__Download`, `__createfile`, or `__appendfile` reference
  whose case does not match exactly - Windows tolerates this, a
  case-sensitive Linux/macOS filesystem does not.
- **`E520`**: a `setting` line that is not the documented
  `setting "name"="value" on "{...}" for client|user|action` shape.
- **`E521`**: a `regset`/`regset64`/`regdelete`/`regdelete64` key that is not
  a quoted, bracketed `"[HKEY_...]..."` keyname.
- **`W504`**: the deprecated `dos` verb; use `waithidden cmd.exe /c ...`
  instead. The one new check that fires on existing `bigfix-content`
  (6 uses across Node.js/uBlock tasks) - everything else surveyed clean.
- **`E522`**: an `override wait` / `override run` block not terminated by
  its own matching verb (end of body, the *other* verb's command, or being
  reopened by another `override` first).
  `bes-actionscript-lint-schclass` validates the option lines inside a block
  (`E303`); this is the pairing check that block's state machine cannot
  express.

## v0.8.2

### Changed

- **`bes-actionscript-validate-prefetch`**: a prefetch *statement* with no
  sha1 no longer fails as `E400`. Current BigFix clients accept a statement
  with sha256 alone, and the old `E400` message ("could not be parsed") was
  actually upstream `bigfix_prefetch` choking on the missing sha1, not a real
  parse failure. It is now its own advisory code, `W405`, on the same footing
  as `W402`'s block-item case - still reported, but does not fail the hook
  unless `--strict` is given.
- **`bes-conventions-check`**: `W206`'s prefetch-shape regex no longer
  requires `sha1:<40>` in the statement form when a `sha256:<64>` is present,
  matching the `W405` judgement above.

## v0.8.1

Fixes false positives found by running v0.8.0's new checks against real
BigFix content in `bigfix-content`.

### Fixed

- **`E512`**: now compares two same-named declarations only when they were
  reached through the *same conditional context* (both unconditional, or
  both via an identical sequence of `if`/`elseif`/`else` branch choices).
  Cross-platform prefetch blocks routinely declare one `name=jre.tar.gz` per
  OS in a *separate* `if` per platform rather than one `if`/`elseif` chain,
  and the hook cannot prove those conditions are mutually exclusive, so it
  no longer guesses across different `if`s.
- **`E513`**: a `delete` or `folder delete` of a `__Download\<name>` is
  cleanup, not consumption, and no longer counts as a reference. A script
  can also *create* a file under `__Download` itself, so `copy`/`move`
  destinations (including from `__createfile`/`__appendfile`, and the
  `{download path "X"}` idiom) and shell redirection targets
  (`... > __Download\<name>`, `>>` too) now register as producers.
- **E513 gating**: a bare `download {...}` whose URL matches neither
  recognized download shape (e.g. `download now {parameter "u"}`) now marks
  its target unknowable, instead of being silently missed by both shapes.
- **`E508`/`E509`**: `}}` is now recognized as an escaped literal `}` inside
  an open substitution too, not just outside one - e.g.
  `{ ... "@{'k'='v'}}" ... }`, a quoted PowerShell hashtable literal nested
  inside a substitution, no longer misreports as an unbalanced `}`.

## v0.8.0

Adds eight semantic checks to `bes-actionscript-validate-script`: prefetch
placement, download-name consistency, if-condition shape, unreachable code,
and `action parameter query` placement.

### Added

- **`E510` / `E511`**: an `add prefetch item` / `add nohash prefetch item`
  (`E510`) or `collect prefetch items` (`E511`) outside an open
  `begin prefetch block` - the agent rejects these outside a block.
- **`E512`**: two prefetch/download producers (statement `prefetch <name>`,
  block `add prefetch item name=<name>`, or `download [now] as <name>`, plus
  a literal `download <url>` basename) declare the same download name,
  compared case-insensitively - the second silently overwrites the first.
- **`E513`**: a command references `__Download\<name>` but nothing prefetches
  or downloads a file of that name - a typo catcher. Conservatively gated:
  skipped for the whole body whenever any producer's names are unknowable
  (an `extract`/`unarchive`/`archive now`/`utility` command, a `download`
  with no `as <name>` and no literal URL basename, or a `{...}` substitution
  in a name or URL), and a substituted consumer name is never judged.
- **`E514`**: an `if` or `elseif` whose condition is not a `{...}` relevance
  substitution (`if true`, bare `if`) - the agent requires one. Joins the
  `actionscript-if-ok` opt-out family.
- **`E515`**: a `begin prefetch block` that is not at the top of the script -
  only blank lines, `//` comments, `action parameter query` lines, and
  `parameter` assignments may precede it. Plain `prefetch` statements are
  legal anywhere in a script and are deliberately not placement-checked.
- **`W501`**: unreachable command - a line after an unconditional `exit`,
  `restart`, or `shutdown` (one outside any `if`) can never run; only the
  first unreachable line is reported.
- **`W502`**: an `action parameter query` after the first execution command -
  these are console-time prompts and belong at the top.
- New opt-out markers, following the per-family pattern:
  `actionscript-prefetch-placement-ok` (`E510`, `E511`, `E515`),
  `actionscript-download-ok` (`E512`, `E513`), `actionscript-unreachable-ok`
  (`W501`), and `actionscript-parameter-query-ok` (`W502`).

No auto-fixes, same rationale as `E500`-`E509`: the hook cannot know intent.

## v0.7.1

Adds per-line `{...}` relevance-substitution brace balance to
`bes-actionscript-validate-script`.

### Added

- **`E508` in `bes-actionscript-validate-script`**: a `{` relevance
  substitution that is never closed by a `}` before the end of its line. A
  substitution is evaluated per line and cannot span lines, so a `{` left open
  at end of line is a broken substitution, not a continued one.
- **`E509` in `bes-actionscript-validate-script`**: a `}` reached with no `{`
  substitution open on that line.
- `{{` (and `}}`) is treated as an escape that passes a literal brace through
  to the command rather than opening or closing a substitution, and a later
  lone `}` pairs with that escape instead of being reported as stray - so
  escaped braces stay quiet.
- Both codes opt out with `actionscript-substitution-ok`, the same marker
  `bes-actionscript-lint-schclass` uses for its `E301`, so one marker covers
  both hooks.

## v0.7.0

Adds a new hook, `bes-actionscript-validate-script`: checks `if`/`endif` and
`begin prefetch block`/`end prefetch block` pairing in every `<ActionScript>`
body of a BES file - the sibling hook `bes-actionscript-lint-schclass`'s SCOPE
note already named for checks that need pairing, ordering, and
block-interleaving knowledge the lexical grammar does not carry.

### Added

- **`bes-actionscript-validate-script`**, a new hook. Only
  `application/x-Fixlet-Windows-Shell` (matched case-insensitively) or
  missing-MIMEType bodies are checked; bodies are extracted with lxml, so
  entities are decoded, CDATA sections merged, and line numbers map back to
  the file. This hook has no auto-fixes: a hook has no way to know where a
  missing `endif` or `end prefetch block` was meant to go, and guessing could
  silently change what the action does.
  - **`E500`**: an `if` is never closed by a matching `endif`.
  - **`E501`**: an `endif` with no open `if`.
  - **`E502`**: a `begin prefetch block` is never closed by `end prefetch block`.
  - **`E503`**: an `end prefetch block` with no open `begin prefetch block`.
  - **`E504`**: a `begin prefetch block` nested inside another one - prefetch blocks do not nest.
  - **`E505`**: an `else` or `elseif` outside any open `if`.
  - **`E506`**: an `elseif` after `else`, or a second `else` for the same `if`.
  - **`E507`**: an `if` opened inside a prefetch block is still open at that block's `end prefetch block` - blocks interleave rather than nest.
  - **`W500`**: the file is not parseable BES XML; skipped (`bes-schema-validate` owns validity).
  - Lines inside a `createfile until` block are file content, not
    ActionScript, and are not scanned - that block's own well-formedness is
    `bes-actionscript-lint-schclass`'s `E302`, not reported here.
  - Opt-outs: `<!-- pre-commit-skip: bes-actionscript-validate-script -->` for
    the whole file, or `actionscript-if-ok` (`E500`, `E501`, `E505`, `E506`),
    `actionscript-prefetch-block-ok` (`E502`, `E503`, `E504`), and
    `actionscript-block-nesting-ok` (`E507`) per check family.

## v0.6.2

Adds `x-fixlet-first-propagation` to the timestamp fields `bes-conventions-check` validates, and tightens the existing `x-fixlet-modification-time` check to actually verify a supplied day-of-week against the date.

### Added

- **`E216` in `bes-conventions-check`**: every `x-fixlet-first-propagation` MIMEField value must be a valid RFC 5322 date-time (e.g. `Tue, 14 Jul 2026 18:32:35 +0000`) - the same rule `E202` already applied to `x-fixlet-modification-time`, now applied to this separate field. A file that knowingly carries a nonconforming value opts out with the `first-propagation-ok` marker, the same pattern as every other value check in the hook.

### Changed

- **`E202` in `bes-conventions-check`**: the leading day-of-week is now optional, matching RFC 5322 itself (`14 Jul 2026 18:32:35 +0000` is accepted, with no day-of-week at all) - but when one is supplied, it must be the *actual* day of week for the date given. `Fri, 06 Aug 2026 12:43:34 +0000` is now rejected, because 6 Aug 2026 is a Thursday, not a Friday; previously the day-of-week was mandatory and only checked for being spelled like a real weekday, not for matching the date. The weekday cross-check is timezone-naive relative to the value's own offset (it compares against the date as written, not a UTC-converted one) and does not depend on the host's locale.
- `SourceReleaseDate` (`E201`) is unaffected by either change above; it remains a plain `YYYY-MM-DD` date with no time or timezone component.

## v0.6.1

Teaches `bes-actionscript-validate-prefetch` to fix prefetches, not just report them: the retired `unzip-5.52.exe` download is replaced offline, and `--auto-fix-network` fills in a missing sha256 by downloading the file.

### Added

- **`E402` in `bes-actionscript-validate-prefetch`**: the prefetch downloads the retired `unzip-5.52.exe` from the BigFix redist folder (matched on either scheme); `http://software.bigfix.com/download/redist/unzip-6.0.exe` is the current one.
  - This is the hook's offline auto-fix, and it is **on by default** (`args: ["--auto-fix", "no"]` turns it off): the line is rewritten in place to the current unzip prefetch, built by `prefetch_from_dictionary()` from `bigfix_prefetch` in whichever spelling the line already used, so a `prefetch ... sha1:...` statement stays a statement and an `add prefetch item ...` stays a block item.
  - The original download's **name** is kept and only the url, size, sha1, and sha256 are replaced: the rest of the ActionScript refers to the downloaded file by name, so renaming it would break the script.
  - An `add nohash prefetch item` on the old URL is reported but not rewritten - giving it hashes would change what the line does, not just which file it fetches.
- **`--auto-fix-network`, off by default**: adds the missing sha256 of an `E401`, which means downloading the file to hash it - there is no other way to learn a sha256. The download is handed to `add_sha256_prefetch()` from `bigfix_prefetch`, which streams the file, checks it against the size and sha1 already on the line, and re-emits the prefetch with sha256 added - in the same spelling, and again keeping the line's own download name (upstream would rename it after the URL's basename).
  - It is a flag of its own rather than part of `--auto-fix`, and never on by default, because it reaches out to whatever URLs the content names.
  - Each URL is fetched at most once per run, and each download gives up after 60 seconds (upstream sets no timeout, and a hanging URL should not hang a commit).
- **`W404`**: `--auto-fix-network` was asked to add a sha256 and could not - the URL would not download, or what came back did not match the size and sha1 already on the line. The line is left exactly as it was and its `E401` stands, so an upstream file that has changed is never quietly re-hashed into looking valid.

### Changed

- An auto-fixed file fails the hook, so the rewrite is reviewed and re-staged - the same behavior as `bes-conventions-check`. Both fixes honor `--disable` and the `prefetch-ok` / `pre-commit-skip` opt-out markers, and preserve the file's CRLF line endings.
- The `bigfix_prefetch` dependency now has a `>= 1.1.5` floor: that is where `prefetch.add_sha256_prefetch()` arrived.
- The hook is no longer offline in every mode. Its **checks** still are - none of them downloads a URL or verifies hashes against the real file - but `--auto-fix-network` does, when asked for.

## v0.6.0

Adds a new hook, `bes-actionscript-validate-prefetch`.

### Added

- **`bes-actionscript-validate-prefetch`**: validates every prefetch line in every `<ActionScript>` body with `validate_prefetch()` from the [bigfix_prefetch](https://pypi.org/project/bigfix-prefetch/) package, which is now an install dependency. Both the `prefetch <name> sha1:<40> size:<n> <url> sha256:<64>` statement and the `add prefetch item name=... sha1=... size=... url=...` block item are covered.
  - `E400`: the line failed validation, with the reason `bigfix_prefetch` reported - a missing size or a size that is not > 0, a hash of the wrong length, a sha1 missing from a prefetch statement, or an unparsable line.
  - `E401`: the line has no sha256. `bigfix_prefetch` treats sha256 as optional unless asked; this hook treats it as mandatory, which is the 2026 expectation. It is a code of its own rather than part of `E400` so a repo that still wants sha256 optional can pass `args: ["--disable", "E401"]`.
  - `W402`: a prefetch block item has no sha1 - technically valid, but unusual.
  - `W403`: an `add nohash prefetch item` line, which is hashless by definition, so it is reported rather than validated.
  - `W400`: the file is not parseable BES XML and was skipped (`bes-schema-validate` owns validity).
  - A file whose prefetches knowingly do not meet these rules opts out of every check in the hook with `prefetch-ok` anywhere in it - the same marker that opts out of `W206` in `bes-conventions-check`, since it is the same judgement. `<!-- pre-commit-skip: bes-actionscript-validate-prefetch -->` also skips the file.
  - Scope is internal validity only: the hook is offline and never downloads a URL or verifies the hashes against the real file. Dynamic prefetches (a line holding a `{...}` substitution), `//` comments, and the raw content of a `createfile until` block are skipped. There are no auto-fixes.
  - This is a third altitude on the same lines, alongside the existing shape/scheme warnings (`W206`/`W207` in `bes-conventions-check`) and the lexical check (`E300` in `bes-actionscript-lint-schclass`).

## v0.5.1

Broadens the `E204` description-placeholder check in `bes-conventions-check` to every content object.

There is no v0.5.0 release; the version went from v0.4.2 straight to v0.5.1.

### Changed

- `E204` in **`bes-conventions-check`** now applies to every content object, not just `Task`/`Fixlet`. `Analysis`, `ComputerGroup`, `Baseline`, and `SingleAction` carry the same boilerplate placeholder, so `Enter a description of the Analysis here.` is now flagged. The match is on the substring `enter a description of the` and remains case-insensitive; `description-ok` still opts out.

## v0.4.2

Adds `E215` to `bes-conventions-check`: whitespace around an `<ActionScript>` CDATA terminator.

### Added

- `E215` in **`bes-conventions-check`** (fixable): an `<ActionScript>` whose CDATA terminator has whitespace around it, e.g. an indented `\t\t\t]]></ActionScript>`. Whitespace before `]]>` sits *inside* the CDATA and whitespace after it is element text appended to the same body, so either way the action gains a spurious whitespace-only last line. The fix strips it to a flush `]]></ActionScript>`. Opt out with `cdata-close-ok`.
  - Previously nothing covered this: `W210` only strips whitespace at end-of-line (here the tabs are followed by `]]></ActionScript>`), `W205` only fires on 2+ blank lines before the close tag, and `W204`/`E207` still see a correctly CDATA-wrapped body.
  - The fixer runs after the `W205` blank-line collapse, which preserves the terminator's indentation, so a block with both issues is fully fixed in one pass.

## v0.4.1

Fixes false `E206` errors on well-formed `action-ui-metadata` values in `bes-conventions-check`, and adds `--errors-only` for a warnings-free report that still runs every fixer.

There is no v0.4.0 release; the version went from v0.3.3 straight to v0.4.1.

### Fixed

- **`bes-conventions-check`** no longer reports false `E206` errors on well-formed `action-ui-metadata` values. The value is now parsed as JSON instead of matched against two fixed patterns, so whitespace (`{"version": "1.0", "size": 10}`) and key order no longer matter, a quoted `size` (`"size": "104632873"`) is accepted alongside a bare one, and an `icon` data URI is accepted in any of those spellings. It must still be a JSON object with a dotted-numeric `version` string, a non-negative integer `size`, and at most an optional `icon` data URI.
- The `E206` message now truncates the offending value at 120 characters, so a base64 `icon` blob no longer buries the rest of the report.

### Added

- `--errors-only` in **`bes-conventions-check`**: warnings are left out of the report and cannot fail the run (even with `--strict`), while every check and every W-code auto-fix still runs. Use this instead of `--disable W2xx,...` when you want a quiet, errors-only report but still want the fixers (`W201`, `W202`, `W205`, `W209`, `W210`) to keep working - `--disable` skips a check *and* its fixer.

## v0.3.3

Fixes false `E300` errors on `override` blocks in `bes-actionscript-lint-schclass`, and validates override options against the documented keywords and values.

There is no v0.3.2 release; the version went from v0.3.1 straight to v0.3.3.

### Fixed

- **`bes-actionscript-lint-schclass`** no longer reports `E300` for the `keyword=value` option lines of an `override run` / `override wait` block. Those lines are options, not commands, and were being judged as unknown command verbs, so any content using `override` failed the hook. This is the main reason to upgrade from v0.3.1.

### Added

- `E303` / `W303` in **`bes-actionscript-lint-schclass`**: an `override run` / `override wait` line now opens a block whose following `keyword=value` lines are validated against the [documented keywords and values](https://developer.bigfix.com/action-script/reference/execution/override.html) - `completion`, `priority`, `hidden`, `detached`, `runas`, `user`, `password`, `asadmin`, `targetuser`, `timeout_seconds`, `disposition`.
  - `E303` - an unknown keyword, a missing value, a value outside the documented set for that keyword, a non-integer `timeout_seconds`, or a `keyword=value` option line outside any override block
  - `W303` - the keyword or value matched case-insensitively but is not lowercase (e.g. `RunAs=`), mirroring `W302` for command verbs
  - A value holding `{...}` is a relevance substitution and is accepted unchecked, since its real value is not known until the agent runs
  - Opt out per check with `actionscript-override-ok` / `actionscript-override-case-ok`
- More `E201` test coverage in `bes-conventions-check`: dates with the right shape but an impossible day (`2026-02-30`, `2023-02-29`, `2026-04-31`), which only the date parse can reject, plus real dates including a leap day.

### Changed

- `<SourceReleaseDate>` validation (`E201`) parses with `date.fromisoformat` instead of `datetime.strptime`, because a calendar date has no timezone to be naive about. No behavior change: for every string the `YYYY-MM-DD` format check admits, both accept and reject exactly the same values.
- Both `check_file` readers use a context manager rather than a bare `open(...).read()`, so the file handle is closed deterministically.
- `bes-schema-validate` calls `sys.exit()` instead of the `exit()` builtin, which is only installed by `site` and can be missing under `python -S`.
- Ruff bumped v0.15.21 -> v0.16.1. Its expanded default rule set surfaced the three items above, plus internal cleanups with no behavior change (a collapsed nested conditional in the tokenizer's `match_literal`, an unused unpacked variable, and a local renamed so it no longer shadows an import). `EXE001` (shebang present but file not executable) is ignored on purpose in `pyproject.toml`, since the hook modules and tests carry `#!/usr/bin/env python3` to stay directly runnable but are imported modules / console-script entry points, not executables.
- Added the `typos` pre-commit hook. Bumped `pre-commit-jgstew` v2.1.1 -> v2.3.0, `codespell` v2.4.2 -> v2.4.3, `zizmor` v1.27.0 -> v1.28.0.

### Removed

- The `misspell` GitHub Actions workflow, superseded by the `typos` pre-commit hook.

**Full Changelog**: https://github.com/jgstew/pre-commit-bigfix/compare/v0.3.1...v0.3.3

---

## v0.3.1

Hook ids renamed to the `<type>-<subtype>-<action>-<mechanism>` convention, plus a new ActionScript linter.

### Added

- **`bes-actionscript-lint-schclass`** - lints every `<ActionScript>` body against the BigFix console's own lexical grammar (vendored `ExpandedActionScript.schclass` plus a small validation override):
  - `E300` - the first token of a line must be a known command verb, a `//` comment, a `{...}` substitution, a continuation, or the line must be blank
  - `E301` - a `{...}` substitution must close before end of line
  - `E302` - a `createfile until <MARKER>` block must reach its marker line (the block's raw content is excluded from linting)
  - `W301` - unbalanced `"`; `W302` - verb matched case-insensitively but is not lowercase

  Only `application/x-Fixlet-Windows-Shell` (or missing `MIMEType`) bodies are treated as ActionScript. Bodies are extracted with lxml, so entities are decoded, CDATA sections merged, and line numbers map back to the source file. Unparsable files are skipped - `bes-schema-validate` owns validity. Pass `--strict` to fail on warnings too.
- Tests asserting that each renamed hook and its deprecated alias stay in lockstep.

### Changed

- `validate-bes` -> **`bes-schema-validate`**, and it now validates against the `BES.xsd` schema explicitly.
- `check-bes-conventions` -> **`bes-conventions-check`**.
- Dependabot bumps: `actions/setup-python` 6.3.0 -> 7.0.0, `lewagon/wait-on-check-action` 0.2 -> 1.8.1.

### Deprecated

- The old ids `validate-bes` and `check-bes-conventions` are kept as aliases pointing at the same entry points, so existing `.pre-commit-config.yaml` files keep working with no behavior change. Prefer the new ids in new configs.

**Full Changelog**: https://github.com/jgstew/pre-commit-bigfix/compare/v0.2.0...v0.3.1

---

## v0.2.0

### Added

- **`validate-bes`** hook - validates BigFix `.bes` / `.ojo` XML files, with README documentation.

**Full Changelog**: https://github.com/jgstew/pre-commit-bigfix/compare/v0.1.1...v0.2.0

---

## v0.1.1

First published release: the repo set up as an installable pre-commit hook package.

### Added

- `pre_commit_bigfix` package with the **`check-bes-conventions`** hook (moved over from `pre-commit-jgstew`) - opinionated content checks and in-place auto-fixes for BES files that the `BES.xsd` schema cannot express: ActionScript `MIMEType`, date/size/metadata value formats, prefetch-line shape and https URLs, CDATA usage, spacing, dynamic downloads, the XML declaration, Title and Relevance content, unique `MIMEField` names, and Task/Fixlet date and download-action presence.
- Full test suite plus an example BES fixture.
- Packaging: `setup.cfg` entry point, `pyproject.toml`, `setup.py` stub.
- GitHub Actions: pre-commit, test_build, tag_and_release, misspell, yamllint; plus dependabot and zizmor config.
- Lint configs and `.pre-commit-config.yaml`.

### Fixed

- `.gitattributes` excludes `.bes` files from text processing; ActionScript content in `example-test.bes` wrapped in CDATA.
- Version bumped to 0.1.1 for module compatibility.

**Full Changelog**: https://github.com/jgstew/pre-commit-bigfix/commits/v0.1.1
