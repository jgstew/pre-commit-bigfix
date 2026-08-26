#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_conventions_check.py.

These exercise the BES content checks (E200-E214, W200-W211), the auto-fixers
(DownloadSize, missing dates, blank-line collapse, CDATA wrap, Title trim,
trailing whitespace, XML declaration), the file-level and per-family opt-out
markers, the mustache-template skip, and main()'s exit codes.
"""

from datetime import datetime, timezone

import pytest

from pre_commit_bigfix import bes_conventions_check as checker

FIXED_NOW = datetime(2026, 7, 14, 18, 32, 35, tzinfo=timezone.utc)


def task(
    title="Example",
    description="A real description of what this does.",
    download_size="0",
    srd="2026-07-14",
    modtime="Tue, 14 Jul 2026 18:32:35 +0000",
    mimetype="application/x-Fixlet-Windows-Shell",
    body="\necho hi\n",
    cdata=True,
    extra_mimefields=(),
    marker=None,
    relevance='exists folder "/tmp"',
):
    """Build a well-formed single-Task BES document.

    srd / modtime = None omit that field. `cdata` wraps the ActionScript body.
    `extra_mimefields` is an iterable of (name, value). `marker` inserts an XML
    comment right after <BES> (used to exercise opt-out markers).
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            '<BES xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:noNamespaceSchemaLocation="BES.xsd">'
        ),
    ]
    if marker:
        lines.append(f"\t<!-- {marker} -->")
    lines.append("\t<Task>")
    lines.append(f"\t\t<Title>{title}</Title>")
    lines.append(f"\t\t<Description><![CDATA[{description}]]></Description>")
    lines.append(f"\t\t<Relevance>{relevance}</Relevance>")
    lines.append(f"\t\t<DownloadSize>{download_size}</DownloadSize>")
    lines.append("\t\t<Source>test</Source>")
    if srd is not None:
        lines.append(f"\t\t<SourceReleaseDate>{srd}</SourceReleaseDate>")
    if modtime is not None:
        lines.append("\t\t<MIMEField>")
        lines.append("\t\t\t<Name>x-fixlet-modification-time</Name>")
        lines.append(f"\t\t\t<Value>{modtime}</Value>")
        lines.append("\t\t</MIMEField>")
    for name, value in extra_mimefields:
        lines.append("\t\t<MIMEField>")
        lines.append(f"\t\t\t<Name>{name}</Name>")
        lines.append(f"\t\t\t<Value>{value}</Value>")
        lines.append("\t\t</MIMEField>")
    lines.append("\t\t<Domain>BESC</Domain>")
    lines.append('\t\t<DefaultAction ID="Action1">')
    action_body = f"<![CDATA[{body}]]>" if cdata else body
    lines.append(
        f'\t\t\t<ActionScript MIMEType="{mimetype}">{action_body}</ActionScript>'
    )
    lines.append('\t\t\t<SuccessCriteria Option="OriginalRelevance"></SuccessCriteria>')
    lines.append("\t\t</DefaultAction>")
    lines.append("\t</Task>")
    lines.append("</BES>")
    return "\n".join(lines) + "\n"


def write(tmp_path, name, content):
    """Write `content` to tmp_path/name with CRLF endings; return the path str.

    BES files must be CRLF (E208), so fixtures are written CRLF by default;
    tests that exercise line endings write raw bytes via write_bytes directly.
    """
    path = tmp_path / name
    crlf = content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    path.write_bytes(crlf.encode("utf-8"))
    return str(path)


def codes(tmp_path, content, name="x.bes", disabled=frozenset()):
    """Return the sorted set of check codes flagged for `content` (read-only)."""
    path = write(tmp_path, name, content)
    issues, _ = checker.check_file(path, disabled)
    return sorted({item[1] for item in issues})


def autofix(tmp_path, content, name="x.bes", strict=False):
    """Run check_file with auto_fix and a fixed clock; return (rewritten, fixed)."""
    path = write(tmp_path, name, content)
    _, fixed = checker.check_file(path, strict=strict, auto_fix=True, now=FIXED_NOW)
    return (tmp_path / name).read_text(encoding="utf-8"), fixed


# --- clean baseline -------------------------------------------------------


def test_good_task_is_clean(tmp_path):
    assert codes(tmp_path, task()) == []


@pytest.mark.parametrize(
    "mimetype",
    [
        "application/x-Fixlet-Windows-Shell",
        "application/x-sh",
        "application/x-AppleScript",
        "application/x-Fixlet-Windows-PowerShell",
        "text/x-uri",
    ],
)
def test_all_allowed_mimetypes_clean(tmp_path, mimetype):
    assert codes(tmp_path, task(mimetype=mimetype)) == []


# --- E200 ActionScript MIMEType ------------------------------------------


def test_e200_disallowed_mimetype(tmp_path):
    assert "E200" in codes(tmp_path, task(mimetype="application/x-python"))


def test_e200_marker_opts_out(tmp_path):
    assert "E200" not in codes(
        tmp_path, task(mimetype="application/x-python", marker="mimetype-ok")
    )


# --- E201 / E202 formats --------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "07/14/2026",
        "2026-7-14",
        "2026/07/14",
        "2026-13-01",
        # right shape, impossible day: only the date parse can reject these
        "2026-02-30",
        "2023-02-29",
        "2026-04-31",
    ],
)
def test_e201_bad_dates(tmp_path, bad):
    assert "E201" in codes(tmp_path, task(srd=bad))


@pytest.mark.parametrize("good", ["2026-07-14", "2024-02-29", "2026-12-31"])
def test_e201_accepts_real_dates(tmp_path, good):
    assert "E201" not in codes(tmp_path, task(srd=good))


@pytest.mark.parametrize(
    "bad",
    [
        "2026-07-14 18:32:35",
        "Fri, 19 Jan 2018 15:45:57 0800",
        "Xyz, 14 Jul 2026 18:32:35 +0000",
        "Tue, 14 Zzz 2026 18:32:35 +0000",
    ],
)
def test_e202_bad_modtime(tmp_path, bad):
    assert "E202" in codes(tmp_path, task(modtime=bad))


@pytest.mark.parametrize(
    "good",
    [
        "Tue, 14 Jul 2026 18:32:35 +0000",  # with day-of-week
        "14 Jul 2026 18:32:35 +0000",  # day-of-week is optional
        "Thu, 06 Aug 2026 12:43:34 +0000",  # 6 Aug 2026 really is a Thursday
    ],
)
def test_e202_accepts_optional_and_correct_dow(tmp_path, good):
    assert "E202" not in codes(tmp_path, task(modtime=good))


def test_e202_wrong_dow_for_date_flagged(tmp_path):
    # 6 Aug 2026 is a Thursday, not a Friday
    assert "E202" in codes(tmp_path, task(modtime="Fri, 06 Aug 2026 12:43:34 +0000"))


def test_e202_marker_opts_out(tmp_path):
    assert "E202" not in codes(
        tmp_path,
        task(modtime="not a timestamp at all", marker="modification-time-ok"),
    )


# --- E216 x-fixlet-first-propagation format -------------------------------


def _with_first_propagation(value, marker=None):
    return task(
        modtime=None,
        marker=marker,
        extra_mimefields=[("x-fixlet-first-propagation", value)],
    )


@pytest.mark.parametrize(
    "bad",
    [
        "2026-07-14 18:32:35",
        "Fri, 19 Jan 2018 15:45:57 0800",
        "Xyz, 14 Jul 2026 18:32:35 +0000",
        "Tue, 14 Zzz 2026 18:32:35 +0000",
        # 6 Aug 2026 is a Thursday, not a Friday
        "Fri, 06 Aug 2026 12:43:34 +0000",
    ],
)
def test_e216_bad_first_propagation(tmp_path, bad):
    assert "E216" in codes(tmp_path, _with_first_propagation(bad))


@pytest.mark.parametrize(
    "good",
    [
        "Tue, 14 Jul 2026 18:32:35 +0000",
        "14 Jul 2026 18:32:35 +0000",  # day-of-week is optional
        "Thu, 06 Aug 2026 12:43:34 +0000",
    ],
)
def test_e216_accepts_optional_and_correct_dow(tmp_path, good):
    assert "E216" not in codes(tmp_path, _with_first_propagation(good))


def test_e216_marker_opts_out(tmp_path):
    content = _with_first_propagation(
        "not a timestamp at all", marker="first-propagation-ok"
    )
    assert "E216" not in codes(tmp_path, content)


# --- E203 / W203 DownloadSize --------------------------------------------


@pytest.mark.parametrize("bad", ["", "-5", "1.5", "abc", "0x10"])
def test_e203_bad_download_size(tmp_path, bad):
    assert "E203" in codes(tmp_path, task(download_size=bad))


@pytest.mark.parametrize("good", ["0", "5", "104632873"])
def test_e203_good_download_size(tmp_path, good):
    assert "E203" not in codes(tmp_path, task(download_size=good))


def test_e203_autofix_to_zero(tmp_path):
    out, fixed = autofix(tmp_path, task(download_size=""))
    assert "<DownloadSize>0</DownloadSize>" in out
    assert any(code == "E203" for _, code, _ in fixed)


def test_w203_download_without_action(tmp_path):
    # DownloadSize > 0 but the ActionScript has no download/prefetch keyword
    assert "W203" in codes(tmp_path, task(download_size="1234", body="\necho hi\n"))


def test_w203_download_with_prefetch_ok(tmp_path):
    body = "\nprefetch x.pkg sha1:{} size:10 https://e/x sha256:{}\ninstaller\n".format(
        "a" * 40,
        "b" * 64,
    )
    assert "W203" not in codes(tmp_path, task(download_size="1234", body=body))


def test_w203_marker_opts_out(tmp_path):
    assert "W203" not in codes(
        tmp_path, task(download_size="1234", marker="download-size-ok")
    )


# --- E204 Description placeholder -----------------------------------------


def test_e204_placeholder(tmp_path):
    assert "E204" in codes(
        tmp_path, task(description="Enter a description of the Task here.")
    )


def test_e204_marker_opts_out(tmp_path):
    assert "E204" not in codes(
        tmp_path,
        task(
            description="Enter a description of the Task here.", marker="description-ok"
        ),
    )


def analysis(description, marker=None):
    """Build a minimal single-Analysis BES document with `description`."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<BES xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:noNamespaceSchemaLocation="BES.xsd">\n'
        + (f"\t<!-- {marker} -->\n" if marker else "")
        + "\t<Analysis>\n"
        "\t\t<Title>Some analysis</Title>\n"
        f"\t\t<Description><![CDATA[{description}]]></Description>\n"
        '\t\t<Property Name="X">whose (it) of it</Property>\n'
        "\t</Analysis>\n"
        "</BES>\n"
    )


@pytest.mark.parametrize(
    "description",
    [
        "Enter a description of the Analysis here.",
        "ENTER A DESCRIPTION OF THE ANALYSIS HERE.",
        "enter a description of the analysis here",
    ],
)
def test_e204_analysis_placeholder(tmp_path, description):
    # the placeholder is not Task/Fixlet-only: Analysis carries the same boilerplate
    assert "E204" in codes(tmp_path, analysis(description))


def test_e204_analysis_real_description(tmp_path):
    assert codes(tmp_path, analysis("A real description of what this analyses.")) == []


def test_e204_analysis_marker_opts_out(tmp_path):
    assert "E204" not in codes(
        tmp_path,
        analysis("Enter a description of the Analysis here.", marker="description-ok"),
    )


# --- E205 CPE 2.3 ---------------------------------------------------------


def test_e205_valid_cpe_clean(tmp_path):
    cpe = "cpe:2.3:a:microsoft:auto_update:4.83:*:*:*:*:macos:*:*"
    assert "E205" not in codes(
        tmp_path, task(extra_mimefields=[("x-fixlet-cpe23-item-name", cpe)])
    )


@pytest.mark.parametrize(
    "bad",
    [
        "cpe:/a:microsoft:auto_update",  # 2.2 URI, not 2.3
        "microsoft:auto_update:4.83",
        "cpe:2.3:a:microsoft",  # too few components
    ],
)
def test_e205_invalid_cpe(tmp_path, bad):
    assert "E205" in codes(
        tmp_path, task(extra_mimefields=[("x-fixlet-cpe23-item-name", bad)])
    )


def test_e205_case_insensitive_name(tmp_path):
    assert "E205" in codes(
        tmp_path, task(extra_mimefields=[("X-Fixlet-CPE23-Item-Name", "nope")])
    )


# --- E206 action-ui-metadata ---------------------------------------------


@pytest.mark.parametrize(
    "good",
    [
        '{ "version":"4.83","size":4417205 }',
        '{"version": "1.0.0", "size": 10}',
        '{ "version":"1.2","size":10,"icon":"data:image/png;base64,AAAA" }',
        '{ "version":"1.0","size":"10" }',  # size quoted
        '{ "size":10,"version":"1.0" }',  # key order is not significant
        # the console's own spacing, with a quoted size and an icon
        (
            '{"version": "1.6.108.0", "size": "104632873", '
            '"icon": "data:image/png;base64,iVBORw0KGgo="}'
        ),
        '{"version":"2019.09.29","size":0,"icon":"data:image/x-icon;base64,AAAA"}',
    ],
)
def test_e206_valid_metadata(tmp_path, good):
    assert "E206" not in codes(
        tmp_path, task(extra_mimefields=[("action-ui-metadata", good)])
    )


@pytest.mark.parametrize(
    "bad",
    [
        '{ "version":"1.0" }',  # no size
        '{ "size":10 }',  # no version
        '{ "version":1.0,"size":10 }',  # version not a string
        '{ "version":"1.0","size":"lots" }',  # size not an integer
        '{ "version":"1.0","size":-10 }',  # negative size
        '{ "version":"v1.0","size":10 }',  # version not dotted-numeric
        '{ "version":"1.0","size":10,"icon":"nope" }',  # icon not a data URI
        '{ "version":"1.0","size":10,"extra":1 }',  # unrecognised key
        '[ "version","1.0" ]',  # JSON, but not an object
        "not json at all",
    ],
)
def test_e206_invalid_metadata(tmp_path, bad):
    assert "E206" in codes(
        tmp_path, task(extra_mimefields=[("action-ui-metadata", bad)])
    )


# --- W204 CDATA -----------------------------------------------------------


def test_w204_no_cdata(tmp_path):
    assert "W204" in codes(tmp_path, task(cdata=False))


def test_w204_marker_opts_out(tmp_path):
    assert "W204" not in codes(tmp_path, task(cdata=False, marker="cdata-ok"))


def test_w204_autofix_only_under_strict(tmp_path):
    # without --strict, auto-fix leaves the body unwrapped
    out, fixed = autofix(tmp_path, task(cdata=False), strict=False)
    assert "<![CDATA[" not in out.split("<ActionScript")[1].split("</ActionScript>")[0]
    assert not any(code == "W204" for _, code, _ in fixed)


def test_w204_autofix_wraps_under_strict(tmp_path):
    out, fixed = autofix(tmp_path, task(cdata=False), strict=True)
    segment = out.split("<ActionScript")[1].split("</ActionScript>")[0]
    assert "<![CDATA[" in segment and "]]>" in segment
    assert any(code == "W204" for _, code, _ in fixed)


# --- E207 CDATA-required (entity-escaped special chars) -------------------


def test_e207_relevance_entity_escaped(tmp_path):
    content = task(relevance="exists x whose (a &lt; b)")
    assert "E207" in codes(tmp_path, content)


def test_e207_actionscript_entity_amp(tmp_path):
    # &amp; in a non-CDATA ActionScript -> E207 (and NOT also W204)
    got = codes(tmp_path, task(body="echo a &amp;&amp; b", cdata=False))
    assert "E207" in got and "W204" not in got


def test_e207_literal_gt_not_flagged(tmp_path):
    # a literal > is valid XML text and does not require CDATA
    content = task(relevance="a > b")
    assert "E207" not in codes(tmp_path, content)


def test_e207_cdata_body_clean(tmp_path):
    content = task(relevance="<![CDATA[exists x whose (a < b)]]>")
    assert "E207" not in codes(tmp_path, content)


def test_e207_action_description_markup_not_flagged(tmp_path):
    # the DefaultAction <Description> is <PreLink>/<Link>/<PostLink> markup, not
    # an entity-escaped text body, even if a PostLink contains &amp;
    content = task().replace(
        '<DefaultAction ID="Action1">',
        '<DefaultAction ID="Action1"><Description><PreLink>Click </PreLink>'
        "<Link>here</Link><PostLink> to run A &amp; B.</PostLink></Description>",
    )
    assert "E207" not in codes(tmp_path, content)


def test_e207_marker_opts_out(tmp_path):
    content = task(marker="cdata-ok", relevance="a &lt; b")
    assert "E207" not in codes(tmp_path, content)


def test_e207_autofix_unescapes_and_wraps(tmp_path):
    content = task(relevance="version of it &gt;= &quot;1.0&quot; &amp; exists x")
    out, fixed = autofix(tmp_path, content)
    assert '<Relevance><![CDATA[version of it >= "1.0" & exists x]]></Relevance>' in out
    assert any(code == "E207" for _, code, _ in fixed)
    assert "E207" not in codes(tmp_path, out, name="after.bes")


def test_e207_autofix_is_not_strict_gated(tmp_path):
    # unlike W204, the E207 wrap happens whenever auto-fix is on (no --strict)
    content = task(body="echo a &amp; b", cdata=False)
    out, fixed = autofix(tmp_path, content, strict=False)
    assert any(code == "E207" for _, code, _ in fixed)
    assert "<![CDATA[echo a & b]]>" in out


# --- E215 whitespace around the ActionScript CDATA terminator -------------


def test_e215_indented_terminator(tmp_path):
    assert "E215" in codes(tmp_path, task(body="\necho hi\n\t\t\t"))


def test_e215_space_after_terminator(tmp_path):
    content = task().replace("]]></ActionScript>", "]]>  </ActionScript>")
    assert "E215" in codes(tmp_path, content)


def test_e215_flush_terminator_ok(tmp_path):
    assert "E215" not in codes(tmp_path, task(body="\necho hi\n"))


def test_e215_other_elements_not_flagged(tmp_path):
    content = task().replace("]]></Description>", "\n\t\t]]></Description>")
    assert "E215" not in codes(tmp_path, content)


def test_e215_marker_opts_out(tmp_path):
    content = task(body="\necho hi\n\t\t\t", marker="cdata-close-ok")
    assert "E215" not in codes(tmp_path, content)


def test_e215_autofix_strips(tmp_path):
    out, fixed = autofix(tmp_path, task(body="\necho hi\n\t\t\t"))
    assert any(code == "E215" for _, code, _ in fixed)
    assert "\t]]></ActionScript>" not in out
    assert "]]></ActionScript>" in out
    assert "E215" not in codes(tmp_path, out, name="after.bes")


def test_e215_indented_plain_close_flagged(tmp_path):
    assert "E215" in codes(tmp_path, task(body="\necho hi\n\t\t\t", cdata=False))


def test_e215_flush_plain_close_ok(tmp_path):
    assert "E215" not in codes(tmp_path, task(body="\necho hi\n", cdata=False))


def test_e215_marker_opts_out_plain_close(tmp_path):
    content = task(body="\necho hi\n\t\t\t", cdata=False, marker="cdata-close-ok")
    assert "E215" not in codes(tmp_path, content)


def test_e215_autofix_strips_plain_close(tmp_path):
    out, fixed = autofix(tmp_path, task(body="\necho hi\n\t\t\t", cdata=False))
    assert any(code == "E215" for _, code, _ in fixed)
    assert "\t</ActionScript>" not in out
    assert "echo hi\n</ActionScript>" in out
    assert "E215" not in codes(tmp_path, out, name="after.bes")


def test_e215_autofix_after_blank_line_collapse(tmp_path):
    out, fixed = autofix(tmp_path, task(body="\necho hi\n\n\n\t\t\t"))
    got = {code for _, code, _ in fixed}
    assert {"W205", "E215"} <= got
    assert codes(tmp_path, out, name="after.bes") == []


# --- W205 blank lines before </ActionScript> ------------------------------


def test_w205_multiple_blank_lines(tmp_path):
    assert "W205" in codes(tmp_path, task(body="\necho hi\n\n\n"))


def test_w205_single_blank_line_ok(tmp_path):
    assert "W205" not in codes(tmp_path, task(body="\necho hi\n\n"))


def test_w205_autofix_collapses(tmp_path):
    out, fixed = autofix(tmp_path, task(body="\necho hi\n\n\n\n"))
    assert any(code == "W205" for _, code, _ in fixed)
    assert "W205" not in codes(tmp_path, out, name="after.bes")


# --- W206 prefetch shape --------------------------------------------------


def test_w206_valid_prefetch_statement(tmp_path):
    body = "\nprefetch x.pkg sha1:{} size:10 https://e/x sha256:{}\n".format(
        "a" * 40,
        "b" * 64,
    )
    assert "W206" not in codes(tmp_path, task(download_size="10", body=body))


def test_w206_valid_add_prefetch_item(tmp_path):
    body = "\n\tadd prefetch item name=x.pkg sha1={} size=10 url=https://e/x sha256={}\n".format(
        "a" * 40,
        "b" * 64,
    )
    assert "W206" not in codes(tmp_path, task(download_size="10", body=body))


def test_w206_valid_sha1_less_prefetch_statement(tmp_path):
    """Current BigFix clients accept a statement with sha256 alone."""
    body = "\nprefetch x.pkg size:10 https://e/x sha256:{}\n".format("b" * 64)
    assert "W206" not in codes(tmp_path, task(download_size="10", body=body))


def test_w206_malformed_prefetch(tmp_path):
    # missing the sha256 field
    body = "\nprefetch x.pkg sha1:%s size:10 https://e/x\n" % ("a" * 40)
    assert "W206" in codes(tmp_path, task(download_size="10", body=body))


def test_w206_marker_opts_out(tmp_path):
    body = "\nprefetch x.pkg sha1:%s size:10 https://e/x\n" % ("a" * 40)
    assert "W206" not in codes(
        tmp_path, task(download_size="10", body=body, marker="prefetch-ok")
    )


# --- W201 / W202 presence + auto-insert -----------------------------------


def test_w201_missing_modification_time(tmp_path):
    assert "W201" in codes(tmp_path, task(modtime=None))


def test_w202_missing_source_release_date(tmp_path):
    assert "W202" in codes(tmp_path, task(srd=None))


def test_autofix_inserts_missing_dates(tmp_path):
    out, fixed = autofix(tmp_path, task(srd=None, modtime=None))
    assert "<SourceReleaseDate>2026-07-14</SourceReleaseDate>" in out
    assert "Tue, 14 Jul 2026 18:32:35 +0000" in out
    assert {"W201", "W202"} <= {code for _, code, _ in fixed}
    # and the rewritten file is now clean of those warnings
    assert not ({"W201", "W202"} & set(codes(tmp_path, out, name="after.bes")))


def test_autofix_dates_respects_single_marker(tmp_path):
    # a lone source-release-date-ok must not suppress the modtime insert
    content = task(srd=None, modtime=None).replace(
        "\t<Task>", "\t<!-- source-release-date-ok -->\n\t<Task>", 1
    )
    out, fixed = autofix(tmp_path, content)
    assert "<SourceReleaseDate>" not in out
    assert "x-fixlet-modification-time" in out
    assert {code for _, code, _ in fixed} == {"W201"}


def test_analysis_exempt_from_presence(tmp_path):
    analysis = """<?xml version="1.0" encoding="UTF-8"?>
<BES xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="BES.xsd">
\t<Analysis>
\t\t<Title>Some analysis</Title>
\t\t<Property Name="X">whose (it) of it</Property>
\t</Analysis>
</BES>
"""
    assert codes(tmp_path, analysis) == []


# --- multiple content objects treated as independent entities -------------


def two_objects(first, second):
    """Wrap two content-object blocks (each without the <?xml>/<BES> shell)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<BES xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:noNamespaceSchemaLocation="BES.xsd">\n'
        f"{first}\n{second}\n</BES>\n"
    )


def _inner(content):
    """Return just the <Task>...</Task> block from a task() document."""
    return content[
        content.index("\t<Task>") : content.index("</Task>") + len("</Task>")
    ]


def test_fault_in_one_object_fails_whole_file(tmp_path):
    # a clean Fixlet next to a Task with a bad MIMEType -> E200 still raised
    clean = _inner(task()).replace("<Task>", "<Fixlet>").replace("</Task>", "</Fixlet>")
    bad = _inner(task(mimetype="application/x-python"))
    assert "E200" in codes(tmp_path, two_objects(clean, bad))


def test_each_object_flagged_separately(tmp_path):
    # first object: bad date; second object: bad mimetype -> both codes present
    a = _inner(task(srd="07/14/2026"))
    b = _inner(task(mimetype="application/x-python"))
    assert set(codes(tmp_path, two_objects(a, b))) >= {"E200", "E201"}


def test_marker_in_one_object_does_not_leak_to_sibling(tmp_path):
    # Task A opts out of the date check inside its own block; Task B still flagged
    a = _inner(task(srd=None)).replace(
        "<Title>Example</Title>",
        "<Title>A</Title>\n\t\t<!-- source-release-date-ok -->",
    )
    b = _inner(task(srd=None)).replace("<Title>Example</Title>", "<Title>B</Title>")
    got = codes(tmp_path, two_objects(a, b))
    assert "W202" in got  # Task B is still flagged


def test_marker_outside_all_objects_is_file_level(tmp_path):
    a = _inner(task(srd=None))
    b = _inner(task(srd=None))
    doc = two_objects(a, b).replace(
        "<BES ", "<!-- source-release-date-ok -->\n<BES ", 1
    )
    assert "W202" not in codes(tmp_path, doc)


def test_autofix_scopes_marker_per_object(tmp_path):
    # Task A opts out (keep it un-dated); Task B gets its dates inserted
    a = _inner(task(srd=None, modtime=None)).replace(
        "<Title>Example</Title>",
        "<Title>A</Title>\n\t\t<!-- source-release-date-ok --><!-- modification-time-ok -->",
    )
    b = _inner(task(srd=None, modtime=None)).replace(
        "<Title>Example</Title>", "<Title>B</Title>"
    )
    out, fixed = autofix(tmp_path, two_objects(a, b))
    # exactly one SourceReleaseDate / modtime inserted (for B, not A)
    assert out.count("<SourceReleaseDate>") == 1
    assert out.count("x-fixlet-modification-time") == 1
    assert {code for _, code, _ in fixed} == {"W201", "W202"}


# --- E208 CRLF line endings ------------------------------------------------


def test_crlf_file_is_clean(tmp_path):
    # write() already writes CRLF, so a good task has no E208
    assert "E208" not in codes(tmp_path, task())


def test_lf_file_flagged(tmp_path):
    path = tmp_path / "lf.bes"
    lf = task().replace("\r\n", "\n").replace("\r", "\n")  # force pure LF
    path.write_bytes(lf.encode("utf-8"))
    issues, _ = checker.check_file(str(path))
    assert "E208" in {code for _, code, _ in issues}


def test_mixed_endings_flagged(tmp_path):
    path = tmp_path / "mixed.bes"
    body = task()
    lf = body.replace("\r\n", "\n").replace("\r", "\n")
    # make only the first newline a CRLF, rest LF -> mixed
    mixed = lf.replace("\n", "\r\n", 1)
    path.write_bytes(mixed.encode("utf-8"))
    issues, _ = checker.check_file(str(path))
    assert "E208" in {code for _, code, _ in issues}


def test_autofix_normalizes_to_crlf(tmp_path):
    path = tmp_path / "lf.bes"
    lf = task().replace("\r\n", "\n").replace("\r", "\n")
    path.write_bytes(lf.encode("utf-8"))
    _, fixed = checker.check_file(str(path), auto_fix=True, now=FIXED_NOW)
    out = path.read_bytes()
    assert out.count(b"\n") == out.count(b"\r\n")  # every LF is part of a CRLF
    assert b"\r\n" in out
    assert any(code == "E208" for _, code, _ in fixed)


def test_autofix_makes_whole_file_crlf_after_content_fix(tmp_path):
    # an LF file that also needs a content fix ends up entirely CRLF
    path = tmp_path / "lf2.bes"
    lf = task(download_size="").replace("\r\n", "\n").replace("\r", "\n")
    path.write_bytes(lf.encode("utf-8"))
    _, fixed = checker.check_file(str(path), auto_fix=True, now=FIXED_NOW)
    out = path.read_bytes()
    assert out.count(b"\n") == out.count(b"\r\n")
    assert b"<DownloadSize>0</DownloadSize>" in out
    assert {"E203", "E208"} <= {code for _, code, _ in fixed}


def test_already_crlf_autofix_is_noop(tmp_path):
    path = tmp_path / "crlf.bes"
    crlf = task().replace("\r\n", "\n").replace("\n", "\r\n")
    before = crlf.encode("utf-8")
    path.write_bytes(before)
    _, fixed = checker.check_file(str(path), auto_fix=True, now=FIXED_NOW)
    assert path.read_bytes() == before  # unchanged
    assert not any(code == "E208" for _, code, _ in fixed)


def test_disable_e208_skips(tmp_path):
    path = tmp_path / "lf.bes"
    lf = task().replace("\r\n", "\n").replace("\r", "\n")
    path.write_bytes(lf.encode("utf-8"))
    issues, _ = checker.check_file(str(path), disabled={"E208"})
    assert "E208" not in {code for _, code, _ in issues}


# --- skips ----------------------------------------------------------------


def test_file_skip_marker(tmp_path):
    # uses checker.SKIP_MARKER rather than a literal so a future marker rename
    # cannot leave this test silently exercising the old string
    content = task(mimetype="application/x-python").replace(
        "\t<Task>", f"\t<!-- {checker.SKIP_MARKER} -->\n\t<Task>", 1
    )
    assert codes(tmp_path, content) == []


def test_mustache_template_skipped(tmp_path):
    tmpl = task().replace("<Title>Example</Title>", "<Title>{{DisplayName}}</Title>")
    assert codes(tmp_path, tmpl) == []


def test_unparsable_xml_is_w200_only(tmp_path):
    assert codes(tmp_path, "<BES><Task><Unclosed></Task></BES>") == ["W200"]


def test_non_bes_extension_skipped(tmp_path):
    path = write(tmp_path, "notbes.txt", task(mimetype="application/x-python"))
    assert checker.check_files([path]) == []


# --- autofix output stays XSD-valid (needs validate_bes_xml) --------------


def test_autofixed_dates_are_xsd_valid(tmp_path):
    validate = pytest.importorskip("validate_bes_xml")
    from pathlib import Path

    example = (Path(__file__).parent / "examples" / "example-test.bes").read_text(
        encoding="utf-8"
    )
    # strip the existing SourceReleaseDate and modification-time so the fixer
    # has to re-insert them, then confirm the result still validates
    import re

    example = re.sub(r"\s*<SourceReleaseDate>.*?</SourceReleaseDate>", "", example)
    example = re.sub(
        r"\s*<MIMEField>\s*<Name>x-fixlet-modification-time</Name>.*?</MIMEField>",
        "",
        example,
        flags=re.DOTALL,
    )
    path = write(tmp_path, "fixme.bes", example)
    checker.check_file(path, auto_fix=True, now=FIXED_NOW)
    assert validate.validate_xml(path)


# --- main() exit codes ----------------------------------------------------


def test_main_clean_returns_zero(tmp_path):
    good = write(tmp_path, "good.bes", task())
    assert checker.main([good]) == 0


def test_main_error_returns_one(tmp_path):
    bad = write(tmp_path, "bad.bes", task(mimetype="application/x-python"))
    assert checker.main([bad]) == 1


def test_main_warning_only_zero_without_strict_no_autofix(tmp_path):
    warn = write(tmp_path, "warn.bes", task(srd=None))
    assert checker.main(["--auto-fix=no", warn]) == 0


def test_main_warning_fails_under_strict_no_autofix(tmp_path):
    warn = write(tmp_path, "warn.bes", task(srd=None))
    assert checker.main(["--strict", "--auto-fix=no", warn]) == 1


def test_main_autofix_returns_one_and_rewrites(tmp_path):
    warn = write(tmp_path, "warn.bes", task(srd=None))
    assert checker.main(["--auto-fix=yes", warn]) == 1
    assert "<SourceReleaseDate>" in (tmp_path / "warn.bes").read_text(encoding="utf-8")


def test_main_disable_suppresses(tmp_path):
    bad = write(tmp_path, "bad.bes", task(mimetype="application/x-python"))
    assert checker.main(["--disable", "E200", bad]) == 0


def test_main_errors_only_hides_warnings(tmp_path, capsys):
    warn = write(tmp_path, "warn.bes", task(srd=None))
    assert checker.main(["--errors-only", "--auto-fix=no", warn]) == 0
    out = capsys.readouterr().out
    assert "W202" not in out
    assert "warning" not in out


def test_main_errors_only_still_reports_errors(tmp_path, capsys):
    bad = write(tmp_path, "bad.bes", task(mimetype="application/x-python", srd=None))
    assert checker.main(["--errors-only", "--auto-fix=no", bad]) == 1
    out = capsys.readouterr().out
    assert "E200" in out
    assert "W202" not in out


def test_main_errors_only_beats_strict(tmp_path):
    warn = write(tmp_path, "warn.bes", task(srd=None))
    assert checker.main(["--errors-only", "--strict", "--auto-fix=no", warn]) == 0


def test_main_errors_only_keeps_warning_fixers(tmp_path, capsys):
    # unlike --disable W202, --errors-only leaves the fixer running
    warn = write(tmp_path, "warn.bes", task(srd=None))
    assert checker.main(["--errors-only", "--auto-fix=yes", warn]) == 1
    assert "<SourceReleaseDate>" in (tmp_path / "warn.bes").read_text(encoding="utf-8")
    assert "auto-fixed" in capsys.readouterr().out


def test_main_disable_skips_warning_fixers(tmp_path):
    warn = write(tmp_path, "warn.bes", task(srd=None))
    assert checker.main(["--disable", "W202", "--auto-fix=yes", warn]) == 0
    assert "<SourceReleaseDate>" not in (tmp_path / "warn.bes").read_text(
        encoding="utf-8"
    )


def test_main_no_files_is_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert checker.main([]) == 0


# --- W207 prefetch URL must be https --------------------------------------

SHA1 = "a" * 40
SHA256 = "b" * 64


def _prefetch(scheme="https"):
    return (
        f"\nprefetch file.exe sha1:{SHA1} size:100 "
        f"{scheme}://example.com/file.exe sha256:{SHA256}\n"
    )


def test_w207_http_prefetch_flagged(tmp_path):
    got = codes(tmp_path, task(body=_prefetch("http"), download_size="100"))
    assert "W207" in got
    assert "W206" not in got  # the line is well-formed, just insecure


def test_w207_https_prefetch_clean(tmp_path):
    got = codes(tmp_path, task(body=_prefetch("https"), download_size="100"))
    assert "W207" not in got


def test_w207_marker_opts_out(tmp_path):
    got = codes(
        tmp_path,
        task(body=_prefetch("http"), download_size="100", marker="prefetch-https-ok"),
    )
    assert "W207" not in got


# --- W208 empty ActionScript ----------------------------------------------


def test_w208_whitespace_only_body(tmp_path):
    assert "W208" in codes(tmp_path, task(body="\n   \n\t\n"))


def test_w208_only_comments(tmp_path):
    assert "W208" in codes(tmp_path, task(body="\n// just a note\n// another\n"))


def test_w208_real_body_clean(tmp_path):
    assert "W208" not in codes(tmp_path, task(body="\n// note\necho hi\n"))


def test_w208_marker_opts_out(tmp_path):
    assert "W208" not in codes(
        tmp_path, task(body="\n// note\n", marker="actionscript-empty-ok")
    )


# --- W211 dynamic download ------------------------------------------------


def test_w211_download_statement_flagged(tmp_path):
    assert "W211" in codes(tmp_path, task(body="\ndownload http://example.com/x\n"))


def test_w211_download_now_flagged(tmp_path):
    assert "W211" in codes(tmp_path, task(body="\n\tdownload now as file http://x\n"))


def test_w211_download_in_comment_not_flagged(tmp_path):
    assert "W211" not in codes(
        tmp_path, task(body="\n// download the file first\necho hi\n")
    )


def test_w211_download_midline_not_flagged(tmp_path):
    assert "W211" not in codes(tmp_path, task(body="\nappendfile download this\n"))


def test_w211_marker_opts_out(tmp_path):
    got = codes(tmp_path, task(body="\ndownload http://x\n", marker="download-ok"))
    assert "W211" not in got


# --- E209 CVENames --------------------------------------------------------


def _with_cve(cve_block):
    return task().replace(
        "<Source>test</Source>", f"<Source>test</Source>\n\t\t{cve_block}"
    )


def test_e209_valid_single_cve_clean(tmp_path):
    assert "E209" not in codes(
        tmp_path, _with_cve("<CVENames>CVE-2021-44228</CVENames>")
    )


def test_e209_valid_multiple_values_clean(tmp_path):
    content = _with_cve("<CVENames>CVE-2021-44228, CVE-2021-45046</CVENames>")
    assert "E209" not in codes(tmp_path, content)


def test_e209_invalid_value_flagged(tmp_path):
    assert "E209" in codes(tmp_path, _with_cve("<CVENames>CVE-BAD</CVENames>"))


def test_e209_multiple_cvenames_flagged(tmp_path):
    content = _with_cve(
        "<CVENames>CVE-2021-44228</CVENames>\n\t\t<CVENames>CVE-2021-45046</CVENames>"
    )
    assert "E209" in codes(tmp_path, content)


def test_e209_marker_opts_out(tmp_path):
    content = task(marker="cve-names-ok").replace(
        "<Source>test</Source>",
        "<Source>test</Source>\n\t\t<CVENames>CVE-BAD</CVENames>",
    )
    assert "E209" not in codes(tmp_path, content)


# --- E210 duplicate MIMEField Name ----------------------------------------


def test_e210_duplicate_name_flagged(tmp_path):
    content = task(
        extra_mimefields=[("x-fixlet-source", "a"), ("x-fixlet-source", "b")]
    )
    assert "E210" in codes(tmp_path, content)


def test_e210_distinct_names_clean(tmp_path):
    content = task(extra_mimefields=[("x-fixlet-source", "a"), ("x-other", "b")])
    assert "E210" not in codes(tmp_path, content)


def test_e210_marker_opts_out(tmp_path):
    content = task(
        marker="mimefield-name-ok",
        extra_mimefields=[("x-dup", "a"), ("x-dup", "b")],
    )
    assert "E210" not in codes(tmp_path, content)


# --- E211 / W209 Title hygiene --------------------------------------------


@pytest.mark.parametrize(
    "title", ["Custom Fixlet", "Custom Task", "Custom Baseline", "Custom Analysis"]
)
def test_e211_default_titles_flagged(tmp_path, title):
    assert "E211" in codes(tmp_path, task(title=title))


def test_e211_case_insensitive(tmp_path):
    assert "E211" in codes(tmp_path, task(title="custom task"))


def test_e211_real_title_clean(tmp_path):
    assert "E211" not in codes(tmp_path, task(title="Install Widget 1.2"))


def test_w209_leading_trailing_whitespace_flagged(tmp_path):
    got = codes(tmp_path, task(title=" Example "))
    assert "W209" in got and "E211" not in got


def test_w209_tab_flagged(tmp_path):
    assert "W209" in codes(tmp_path, task(title="Ex\tample"))


def test_w209_autofix_trims_and_detabs(tmp_path):
    out, fixed = autofix(tmp_path, task(title="  Ex\tample  "))
    assert "<Title>Ex ample</Title>" in out
    assert any(code == "W209" for _, code, _ in fixed)


def test_title_marker_opts_out(tmp_path):
    assert "E211" not in codes(tmp_path, task(title="Custom Task", marker="title-ok"))


# --- E212 / E213 Relevance ------------------------------------------------


def test_e212_literal_true_flagged(tmp_path):
    assert "E212" in codes(tmp_path, task(relevance="true"))


def test_e212_case_insensitive(tmp_path):
    assert "E212" in codes(tmp_path, task(relevance="TRUE"))


def test_e213_empty_relevance_flagged(tmp_path):
    assert "E213" in codes(tmp_path, task(relevance=""))


def test_e213_whitespace_relevance_flagged(tmp_path):
    assert "E213" in codes(tmp_path, task(relevance="   "))


def test_relevance_real_clause_clean(tmp_path):
    got = codes(tmp_path, task(relevance='exists file "/etc/hosts"'))
    assert "E212" not in got and "E213" not in got


def test_relevance_marker_opts_out(tmp_path):
    assert "E212" not in codes(tmp_path, task(relevance="true", marker="relevance-ok"))


# --- E214 XML declaration -------------------------------------------------


def _no_decl(content):
    return "\n".join(content.split("\n")[1:])


def test_e214_missing_declaration_flagged(tmp_path):
    assert "E214" in codes(tmp_path, _no_decl(task()))


def test_e214_wrong_encoding_flagged(tmp_path):
    content = task().replace('encoding="UTF-8"', 'encoding="ISO-8859-1"')
    assert "E214" in codes(tmp_path, content)


def test_e214_lowercase_utf8_clean(tmp_path):
    content = task().replace('encoding="UTF-8"', 'encoding="utf-8"')
    assert "E214" not in codes(tmp_path, content)


def test_e214_autofix_inserts_declaration(tmp_path):
    out, fixed = autofix(tmp_path, _no_decl(task()))
    assert out.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert any(code == "E214" for _, code, _ in fixed)
    assert "E214" not in codes(tmp_path, out, name="after.bes")


def test_e214_autofix_sets_encoding(tmp_path):
    content = task().replace('encoding="UTF-8"', 'encoding="ISO-8859-1"')
    out, _ = autofix(tmp_path, content)
    assert 'encoding="UTF-8"' in out.split("\n")[0]


def test_e214_marker_opts_out(tmp_path):
    content = _no_decl(task()).replace("<BES", "<!-- xml-declaration-ok -->\n<BES", 1)
    assert "E214" not in codes(tmp_path, content)


# --- W210 trailing whitespace ---------------------------------------------


def test_w210_trailing_whitespace_flagged(tmp_path):
    content = task().replace("<Source>test</Source>", "<Source>test</Source>   ")
    assert "W210" in codes(tmp_path, content)


def test_w210_clean_when_none(tmp_path):
    assert "W210" not in codes(tmp_path, task())


def test_w210_autofix_strips(tmp_path):
    content = task().replace("<Source>test</Source>", "<Source>test</Source>\t ")
    out, fixed = autofix(tmp_path, content)
    assert "<Source>test</Source>\t " not in out
    assert "<Source>test</Source>\n" in out
    assert any(code == "W210" for _, code, _ in fixed)
    assert "W210" not in codes(tmp_path, out, name="after.bes")


def test_w210_marker_opts_out(tmp_path):
    content = task(marker="trailing-whitespace-ok").replace(
        "<Source>test</Source>", "<Source>test</Source>   "
    )
    assert "W210" not in codes(tmp_path, content)


# --- W212 / W213 Relevance: literal `false`, stray whitespace -------------


def test_w212_literal_false_flagged(tmp_path):
    got = codes(tmp_path, task(relevance="false"))
    assert "W212" in got and "E212" not in got and "E213" not in got


def test_w212_case_insensitive(tmp_path):
    assert "W212" in codes(tmp_path, task(relevance="FALSE"))


def test_w212_marker_opts_out(tmp_path):
    assert "W212" not in codes(tmp_path, task(relevance="false", marker="relevance-ok"))


def test_w213_leading_trailing_whitespace_flagged(tmp_path):
    content = task().replace(
        '<Relevance>exists folder "/tmp"</Relevance>',
        '<Relevance> exists folder "/tmp" </Relevance>',
    )
    assert "W213" in codes(tmp_path, content)


def test_w213_clean_relevance_not_flagged(tmp_path):
    assert "W213" not in codes(tmp_path, task())


def test_w213_cdata_wrapped_not_flagged(tmp_path):
    content = task().replace(
        '<Relevance>exists folder "/tmp"</Relevance>',
        '<Relevance><![CDATA[ exists folder "/tmp" ]]></Relevance>',
    )
    assert "W213" not in codes(tmp_path, content)


def test_w213_autofix_trims(tmp_path):
    content = task().replace(
        '<Relevance>exists folder "/tmp"</Relevance>',
        '<Relevance> exists folder "/tmp" </Relevance>',
    )
    out, fixed = autofix(tmp_path, content)
    assert '<Relevance>exists folder "/tmp"</Relevance>' in out
    assert any(code == "W213" for _, code, _ in fixed)
    assert "W213" not in codes(tmp_path, out, name="after.bes")


def test_w213_marker_opts_out(tmp_path):
    content = task(marker="relevance-ok").replace(
        '<Relevance>exists folder "/tmp"</Relevance>',
        '<Relevance> exists folder "/tmp" </Relevance>',
    )
    assert "W213" not in codes(tmp_path, content)


# --- W214 Title TODO/FIXME marker ------------------------------------------


@pytest.mark.parametrize(
    "title",
    ["Install Widget - Windows  TODO:testing", "Install Widget - Windows FIXME"],
)
def test_w214_todo_marker_flagged(tmp_path, title):
    assert "W214" in codes(tmp_path, task(title=title))


def test_w214_case_insensitive(tmp_path):
    assert "W214" in codes(tmp_path, task(title="Install Widget todo: verify"))


def test_w214_real_title_clean(tmp_path):
    assert "W214" not in codes(tmp_path, task(title="Install Widget 1.2"))


def test_w214_marker_opts_out(tmp_path):
    assert "W214" not in codes(
        tmp_path, task(title="Install Widget TODO", marker="title-ok")
    )


# --- W215 Task/Fixlet empty or missing Description ------------------------


def test_w215_empty_description_flagged(tmp_path):
    content = task().replace(
        "<Description><![CDATA[A real description of what this does.]]></Description>",
        "<Description></Description>",
    )
    assert "W215" in codes(tmp_path, content)


def test_w215_whitespace_only_description_flagged(tmp_path):
    content = task().replace(
        "<Description><![CDATA[A real description of what this does.]]></Description>",
        "<Description><![CDATA[   ]]></Description>",
    )
    assert "W215" in codes(tmp_path, content)


def test_w215_real_description_clean(tmp_path):
    assert "W215" not in codes(tmp_path, task())


def test_w215_marker_opts_out(tmp_path):
    content = task(marker="description-ok").replace(
        "<Description><![CDATA[A real description of what this does.]]></Description>",
        "<Description></Description>",
    )
    assert "W215" not in codes(tmp_path, content)


def test_w215_analysis_exempt(tmp_path):
    # Analysis is not a DATED_CONTENT_TAGS member; W215 does not apply.
    assert "W215" not in codes(tmp_path, analysis(""))


# --- E217 SuccessCriteria body/Option consistency --------------------------


def _with_success_criteria(option, body=""):
    return task().replace(
        '<SuccessCriteria Option="OriginalRelevance"></SuccessCriteria>',
        f'<SuccessCriteria Option="{option}">{body}</SuccessCriteria>',
    )


def test_e217_empty_custom_relevance_flagged(tmp_path):
    content = _with_success_criteria("CustomRelevance", "")
    assert "E217" in codes(tmp_path, content)


def test_e217_literal_false_custom_relevance_flagged(tmp_path):
    content = _with_success_criteria("CustomRelevance", "false")
    assert "E217" in codes(tmp_path, content)


def test_e217_nonempty_original_relevance_flagged(tmp_path):
    content = _with_success_criteria("OriginalRelevance", 'computer name = "x"')
    assert "E217" in codes(tmp_path, content)


def test_e217_real_custom_relevance_clean(tmp_path):
    content = _with_success_criteria("CustomRelevance", 'computer name = "x"')
    assert "E217" not in codes(tmp_path, content)


def test_e217_empty_original_relevance_clean(tmp_path):
    assert "E217" not in codes(tmp_path, task())


def test_e217_marker_opts_out(tmp_path):
    content = _with_success_criteria("CustomRelevance", "").replace(
        "<Task>", "<Task>\n\t\t<!-- success-criteria-ok -->"
    )
    assert "E217" not in codes(tmp_path, content)


# --- E218 duplicate Action ID ----------------------------------------------


def test_e218_duplicate_default_action_id_flagged(tmp_path):
    content = task().replace(
        "</DefaultAction>\n\t</Task>",
        (
            "</DefaultAction>\n"
            '\t\t<Action ID="Action1">\n'
            '\t\t\t<ActionScript MIMEType="application/x-Fixlet-Windows-Shell">'
            "<![CDATA[\necho hi\n]]></ActionScript>\n"
            "\t\t</Action>\n\t</Task>"
        ),
    )
    assert "E218" in codes(tmp_path, content)


def test_e218_distinct_ids_clean(tmp_path):
    content = task().replace(
        "</DefaultAction>\n\t</Task>",
        (
            "</DefaultAction>\n"
            '\t\t<Action ID="Action2">\n'
            '\t\t\t<ActionScript MIMEType="application/x-Fixlet-Windows-Shell">'
            "<![CDATA[\necho hi\n]]></ActionScript>\n"
            "\t\t</Action>\n\t</Task>"
        ),
    )
    assert "E218" not in codes(tmp_path, content)


def test_e218_marker_opts_out(tmp_path):
    content = task(marker="action-id-ok").replace(
        "</DefaultAction>\n\t</Task>",
        (
            "</DefaultAction>\n"
            '\t\t<Action ID="Action1">\n'
            '\t\t\t<ActionScript MIMEType="application/x-Fixlet-Windows-Shell">'
            "<![CDATA[\necho hi\n]]></ActionScript>\n"
            "\t\t</Action>\n\t</Task>"
        ),
    )
    assert "E218" not in codes(tmp_path, content)


# --- E219 x-relevance-evaluation-period format ------------------------------


@pytest.mark.parametrize("bad", ["6:00:00", "06:60:00", "06:00:60", "not-a-duration"])
def test_e219_bad_evaluation_period(tmp_path, bad):
    content = task(extra_mimefields=[("x-relevance-evaluation-period", bad)])
    assert "E219" in codes(tmp_path, content)


@pytest.mark.parametrize("good", ["06:00:00", "01:00:00", "00:00:01"])
def test_e219_good_evaluation_period(tmp_path, good):
    content = task(extra_mimefields=[("x-relevance-evaluation-period", good)])
    assert "E219" not in codes(tmp_path, content)


def test_e219_case_insensitive_field_name(tmp_path):
    content = task(extra_mimefields=[("X-Relevance-Evaluation-Period", "6:00:00")])
    assert "E219" in codes(tmp_path, content)


def test_e219_marker_opts_out(tmp_path):
    content = task(
        marker="evaluation-period-ok",
        extra_mimefields=[("x-relevance-evaluation-period", "6:00:00")],
    )
    assert "E219" not in codes(tmp_path, content)


# --- W216 SourceSeverity vocabulary -----------------------------------------


@pytest.mark.parametrize("bad", ["high", "Recommended", "CRITICAL"])
def test_w216_bad_severity_flagged(tmp_path, bad):
    content = task().replace(
        "<Source>test</Source>",
        f"<Source>test</Source>\n\t\t<SourceSeverity>{bad}</SourceSeverity>",
    )
    assert "W216" in codes(tmp_path, content)


@pytest.mark.parametrize(
    "good", ["", "Low", "Moderate", "Important", "Critical", "Unspecified"]
)
def test_w216_good_severity_clean(tmp_path, good):
    content = task().replace(
        "<Source>test</Source>",
        f"<Source>test</Source>\n\t\t<SourceSeverity>{good}</SourceSeverity>",
    )
    assert "W216" not in codes(tmp_path, content)


def test_w216_marker_opts_out(tmp_path):
    content = task(marker="severity-ok").replace(
        "<Source>test</Source>",
        "<Source>test</Source>\n\t\t<SourceSeverity>high</SourceSeverity>",
    )
    assert "W216" not in codes(tmp_path, content)


# --- --severity-values overrides the W216 vocabulary ------------------------


def _severity_content(value):
    return task().replace(
        "<Source>test</Source>",
        f"<Source>test</Source>\n\t\t<SourceSeverity>{value}</SourceSeverity>",
    )


def _codes_with_severities(tmp_path, content, severities, name="x.bes"):
    path = write(tmp_path, name, content)
    issues, _ = checker.check_file(path, severities=severities)
    return sorted({item[1] for item in issues})


def test_severity_values_allows_custom_vocabulary(tmp_path):
    got = _codes_with_severities(
        tmp_path, _severity_content("high"), frozenset({"low", "high", "critical"})
    )
    assert "W216" not in got


def test_severity_values_still_flags_outside_custom_vocabulary(tmp_path):
    got = _codes_with_severities(
        tmp_path, _severity_content("Critical"), frozenset({"low", "high", "critical"})
    )
    # exact-case match: the canonical "Critical" is not in the lowercase set
    assert "W216" in got


def test_severity_values_replaces_rather_than_extends_default(tmp_path):
    # Low is in the canonical default but not in this custom vocabulary
    got = _codes_with_severities(
        tmp_path, _severity_content("Low"), frozenset({"high"})
    )
    assert "W216" in got


def test_severity_values_none_keeps_canonical_default(tmp_path):
    assert "W216" not in codes(tmp_path, _severity_content("Critical"))


def test_severity_values_empty_string_always_allowed(tmp_path):
    got = _codes_with_severities(tmp_path, _severity_content(""), frozenset({"high"}))
    assert "W216" not in got


def test_main_severity_values_cli_flag(tmp_path, capsys):
    path = write(tmp_path, "x.bes", _severity_content("high"))
    rc = checker.main(["--severity-values", "low,high,critical", path])
    assert rc == 0
    out = capsys.readouterr().out
    assert "W216" not in out


def test_main_severity_values_cli_flag_still_flags(tmp_path, capsys):
    path = write(tmp_path, "x.bes", _severity_content("Recommended"))
    rc = checker.main(["--strict", "--severity-values", "low,high,critical", path])
    assert rc == 1
    out = capsys.readouterr().out
    assert "W216" in out


def test_main_without_severity_values_uses_canonical_default(tmp_path, capsys):
    path = write(tmp_path, "x.bes", _severity_content("high"))
    checker.main([path])
    out = capsys.readouterr().out
    assert "W216" in out


# --- W217 filename vs Title (--check-filename only) -------------------------


def _codes_with_filename(tmp_path, content, name="x.bes"):
    path = write(tmp_path, name, content)
    issues, _ = checker.check_file(path, check_filename=True)
    return sorted({item[1] for item in issues})


def test_w217_off_by_default(tmp_path):
    assert "W217" not in codes(tmp_path, task(title="Something Else"), name="x.bes")


def test_w217_mismatch_flagged_when_enabled(tmp_path):
    got = _codes_with_filename(tmp_path, task(title="Something Else"), name="x.bes")
    assert "W217" in got


def test_w217_matching_title_clean(tmp_path):
    got = _codes_with_filename(tmp_path, task(title="x"), name="x.bes")
    assert "W217" not in got


def test_w217_illegal_chars_sanitized(tmp_path):
    # the "/" in the Title is not legal in a filename, so the expected stem
    # replaces it with "_"; a filename that already does that is clean.
    content = task(title="Add Docker key - Debian/Ubuntu")
    got = _codes_with_filename(
        tmp_path, content, name="Add Docker key - Debian_Ubuntu.bes"
    )
    assert "W217" not in got


def test_w217_marker_opts_out(tmp_path):
    content = task(title="Something Else", marker="filename-ok")
    got = _codes_with_filename(tmp_path, content, name="x.bes")
    assert "W217" not in got
