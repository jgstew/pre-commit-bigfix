#!/usr/bin/env python3
"""Score how risky a BES file's content is, to flag it for careful review.

This is a triage signal, not a verdict: each finding below adds points to the
file's risk score, and a file whose score reaches --fail-score (default 50,
the HIGH band) fails the hook so a person looks at it before it is trusted.
Content is never changed. Bands: LOW under 25, MEDIUM 25-49, HIGH 50 and up.

Signals (default points in brackets; --weight CODE=N changes one):

    W901  [20] script in a Description: <script>, javascript:, an on*= handler
    W902  [25] session relevance in a Description: <?relevance ...?> or an
          EvaluateRelevance( call
    W903  [15] both of the above in one Description
    W910  [25] an ActionScript `download` / `download now` -- not hashed; a
          later `continue if {sha1 of ...}` does not excuse it, use a prefetch
    W911  [25] `add nohash prefetch item`
    W912  [10] a download or prefetch URL over plain http:// or to a raw IP
    W913  [15] a download command in script content (curl, wget,
          Invoke-WebRequest, DownloadString, bitsadmin, ...)
    W920   [2] base64 of a real image of its declared data:image/ type
    W921  [20] base64 (80+ characters) anywhere else
    W922  [25] a decoded payload is an executable or a script
    W923  [20] a decode or dynamic-run command: certutil -decode, base64 -d,
          FromBase64String, powershell -EncodedCommand, Invoke-Expression /
          iex, PsExec, a pipe into sh (curl ... | sh)
    W924  [15] other obfuscation: long \\x / \\u / %XX / hex runs that decode
          to ASCII, or eval( unescape( atob( Function( fromCharCode(
    W925  [15] a decoded payload is gzip, zlib or zip compressed
    W926  [30] base64 labelled data:image/ whose bytes are not that image
    W927  [10] a decoded payload itself holds findings: scores their points
          plus 10 per layer, and names the decode path (base64->gzip->text)
    W930  [25] a hardcoded secret: password= / token= / api_key: with a literal
          value (not a {parameter}, $var or %VAR%), a private key, an AWS key
    W931  [20] a command that weakens security: disables UAC, Defender, a
          firewall, SELinux, Gatekeeper or SIP; deletes shadow copies or
          clears logs; adds a user or an administrator; edits sudoers or
          authorized_keys
    W932  [30] a Description that loads remote content or reaches outside the
          page: <script src> / <iframe src> to a URL, ActiveXObject,
          WScript.Shell, XMLHttpRequest, fetch(, document.cookie
    W940  [30] tampers with the BigFix client: stops, disables or uninstalls
          BESClient, deletes __BESData, replaces masthead/ActionSite.afxm
    W941  [25] redirects the client to another relay or server
          (__RelayServer1/2, _BESClient_RelaySelect_*, ParentRelay,
          affiliation)
    W942  [10] uploads endpoint files to the root server (archive now,
          _BESClient_ArchiveManager_*, _BESClient_UploadManager_*); the
          destination cannot be redirected, but the files become readable on
          the server
    W943  [25] calls the BigFix REST API (/api/actions, ...): content that can
          create more content or actions
    W944  [30] an action that targets all computers (<AllComputers>true)
    W945  [20] runs a command taken from a client setting or a file (wait
          {value of setting ...})
    W946  [30] compares now to a fixed date in relevance or an action (a time
          bomb?)
    W947  [15] relevance or an action pinned to one host name, IP or MAC
    W948  [ 5] a {parameter} placed straight into a command line (command
          injection?)
    W949  [20] uploads files (W942) and reads a credential store (W950) in one
          file: secrets may end up on the server
    W950  [30] reads a credential store: /etc/shadow, the SAM or SECURITY
          hive, SSH keys, browser logins, keychains, .aws/credentials,
          NTDS.dit, lsass; in ActionScript, Relevance or an Analysis Property
    W951  [30] dumps credentials or prompts for a password: mimikatz, procdump
          of lsass, reg save HKLM\\SAM, Get-Credential, an AppleScript with
          hidden answer dialog
    W952  [25] weakens credential protection: WDigest UseLogonCredential=1,
          RunAsPPL=0, NoLMHash=0
    W953  [25] sends data off the endpoint: curl -d/-F/-T, an Invoke-
          WebRequest/Invoke-RestMethod POST or PUT, scp, sftp, ftp, UploadFile
    W954  [20] a URL on a paste site, URL shortener, tunnel (ngrok,
          trycloudflare), raw.githubusercontent/gist, the Discord CDN, or
          dynamic DNS
    W955  [25] a URL with credentials in it (https://user:pass@...)
    W956  [25] turns off TLS or host-key verification: curl -k, --no-check-
          certificate, ServerCertificateValidationCallback,
          StrictHostKeyChecking no
    W957  [30] adds a trusted root CA (certutil -addstore root, add-trusted-
          cert, update-ca-certificates)
    W958  [20] changes hosts, DNS or proxy settings
    W959  [20] enables remote access: RDP, WinRM, SSH root or password login,
          SMBv1, the guest account, LocalAccountTokenFilterPolicy=1
    W960  [30] bypasses AMSI or ETW, loads code reflectively, or compiles it
          at run time (Add-Type -TypeDefinition, csc.exe, an MSBuild project,
          VirtualAlloc)
    W961  [20] a built-in binary used to run code: mshta, regsvr32 /i:,
          rundll32 javascript:, wmic process call create, odbcconf, forfiles
          /c, cmstp
    W962  [20] keyword obfuscation: PowerShell backticks or cmd carets inside
          a word, env-var substrings other than %DATE%/%TIME%, split-and-
          joined strings, -bxor, string reversal
    W963  [30] a bidi or zero-width character, which can hide code (a byte-
          order mark opening the file is fine)
    W964  [20] stops or removes a security tool: Defender, an EDR agent,
          Sysmon, Tanium, osquery, auditd
    W965  [15] hides or backdates files (attrib +h +s, touch -t, SetFileTime)
    W966  [25] loads a kernel driver or module (insmod, kextload), or turns on
          test signing
    W967  [15] setuid or world-writable permissions, Everyone:F
    W968  [20] an offensive, recon or mining tool: nmap, responder,
          BloodHound, impacket, xmrig, stratum+tcp
    W970  [25] stealthy persistence: IFEO Debugger, sticky-keys replacement,
          WMI event subscriptions, Winlogon Userinit/Shell, AppInit_DLLs,
          LD_PRELOAD, DYLD_INSERT_LIBRARIES, shell rc and profile.d files
    W971  [10] ordinary persistence: a Run key, service, launchd or systemd
          unit, scheduled task or cron job
    W972  [30] a destructive disk operation: diskpart, format, dd of=/dev/...,
          mkfs, shred, cipher /w, rm -rf /
    W973  [20] SQL that changes data (DROP, DELETE, UPDATE, TRUNCATE, ALTER),
          or xp_cmdshell
    W980  [20] a password field in a Description: credentials collected in the
          console
    W981  [30] a UNC (\\\\server\\share) or file: link or image in a Description;
          rendering it may send the operator's NTLM hash
    W982  [15] a remote image or media file in a Description: a beacon on
          whoever opens it
    W983  [25] a <meta refresh>, <base href>, or a <form action> posting to
          another site, in a Description
    W984  [10] a hidden element (display:none, visibility:hidden) in a
          Description
    W990  [10] a createfile payload longer than 200 lines: hard to review
    W991  [15] a Task or Fixlet titled like a check (Check, Get, Report,
          Inventory, ...) whose action changes state
    W900       a MEDIUM score (summary line)
    W908       not parseable XML; skipped (bes-schema-validate owns validity)
    E900       the score is at or over --fail-score

Signals favor recall: a finding that a reviewer decides is fine costs a
minute, a missed one may cost far more. Content written by createfile is
scanned like any other script content.

Every encoded blob is decoded and inspected: base64 is tried as UTF-8 and as
UTF-16LE (PowerShell -EncodedCommand), compressed data is decompressed, and
decoded text is scanned again with the same signals, at most MAX_DEPTH layers
deep and MAX_DECODED bytes in all, so a decompression bomb cannot run away.
"""

import argparse
import base64
import binascii
import io
import re
import sys
import zipfile
import zlib
from typing import NamedTuple

from lxml import etree

from pre_commit_bigfix import bes_common
from pre_commit_bigfix.bes_actionscript_lint_schclass import _mask_heredocs

ACTIONSCRIPT_MIMETYPE = "application/x-Fixlet-Windows-Shell"

WEIGHTS = {
    "W901": 20,
    "W902": 25,
    "W903": 15,
    "W910": 25,
    "W911": 25,
    "W912": 10,
    "W913": 15,
    "W920": 2,
    "W921": 20,
    "W922": 25,
    "W923": 20,
    "W924": 15,
    "W925": 15,
    "W926": 30,
    "W927": 10,
    "W930": 25,
    "W931": 20,
    "W932": 30,
    "W940": 30,
    "W941": 25,
    "W942": 10,
    "W943": 25,
    "W944": 30,
    "W945": 20,
    "W946": 30,
    "W947": 15,
    "W948": 5,
    "W949": 20,
    "W950": 30,
    "W951": 30,
    "W952": 25,
    "W953": 25,
    "W954": 20,
    "W955": 25,
    "W956": 25,
    "W957": 30,
    "W958": 20,
    "W959": 20,
    "W960": 30,
    "W961": 20,
    "W962": 20,
    "W963": 30,
    "W964": 20,
    "W965": 15,
    "W966": 25,
    "W967": 15,
    "W968": 20,
    "W970": 25,
    "W971": 10,
    "W972": 30,
    "W973": 20,
    "W980": 20,
    "W981": 30,
    "W982": 15,
    "W983": 25,
    "W984": 10,
    "W990": 10,
    "W991": 15,
}

MEDIUM = 25
HIGH = 50
MAX_DEPTH = 3
MAX_DECODED = 4 * 1024 * 1024  # bytes decoded per file, all layers together
MAX_INFLATE = 1024 * 1024  # bytes one decompression may produce
MAX_HEREDOC_LINES = 200  # a longer createfile payload is hard to review

SCRIPT_RE = re.compile(r"<script\b|\bjavascript:|<[^>]*\son[a-z]+\s*=", re.IGNORECASE)
SESSION_RE = re.compile(r"<\?relevance\b|\bEvaluateRelevance\s*\(", re.IGNORECASE)
# case-sensitive: `function(` is in every script; `Function(` builds code
OBFUSCATION_API_RE = re.compile(
    r"\b(?:eval|unescape|atob|Function)\s*\(|\bfromCharCode\s*\("
)
DOWNLOAD_CMD_RE = re.compile(
    r"\b(?:curl|wget|iwr|bitsadmin)\b|Invoke-WebRequest|Invoke-RestMethod"
    r"|Start-BitsTransfer|DownloadString|DownloadFile|Net\.WebClient"
    r"|certutil\b[^\n]*-urlcache",
    re.IGNORECASE,
)
DECODE_CMD_RE = re.compile(
    r"certutil(?:\.exe)?\s+-decode|\bbase64\s+(?:-d|-D|--decode)\b"
    r"|FromBase64String|\bpowershell(?:\.exe)?\b[^\n]*\s-(?:e|ec|enc|encodedcommand)\s"
    r"|Invoke-Expression|\biex\b|\bpsexec(?:64)?\b"
    r"|\|\s*(?:sudo\s+)?(?:bash|zsh|dash|sh)\b",
    re.IGNORECASE,
)
# a literal value after a secret-looking name; a {relevance} substitution,
# $variable or %VARIABLE% is not one
SECRET_RE = re.compile(
    r"\b(?:password|passwd|pwd|secret|api[_-]?key|auth[_-]?token|access[_-]?token"
    r"|token)\s*[:=]\s*[\"']?(?![\s\"'{$%<])[^\s\"'&;<]{4,}"
    r"|-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b",
    re.IGNORECASE,
)
WEAKEN_RE = re.compile(
    r"Set-MpPreference\s[^\n]*-Disable|Add-MpPreference\s[^\n]*-Exclusion"
    r"|DisableAntiSpyware|DisableRealtimeMonitoring"
    r"|advfirewall\s+set\s+\w+\s+state\s+off|netsh\s+firewall\s+set\s+opmode\s+disable"
    r"|Set-NetFirewallProfile\s[^\n]*-Enabled\s+(?:\$?false|0)"
    r"|systemctl\s+(?:stop|disable|mask)\s+(?:firewalld|ufw|iptables|auditd)"
    r"|\bufw\s+disable|\bsetenforce\s+0|SELINUX=disabled"
    r"|EnableLUA[^\n]*dword:0+\b|spctl\s+--master-disable|csrutil\s+disable"
    r"|vssadmin\s+delete\s+shadows|wevtutil\s+(?:cl|clear-log)\b|Clear-EventLog"
    r"|wbadmin\s+delete|bcdedit\s[^\n]*recoveryenabled\s+no"
    r"|\bnet\s+user\s+\S+\s+\S+\s+/add|\bnet\s+localgroup\s+administrators\s+\S+\s+/add"
    r"|Add-LocalGroupMember\s[^\n]*Administrators|\buseradd\b|\badduser\b"
    r"|usermod\s+-a?G\s+(?:sudo|wheel|admin)|/etc/sudoers|NOPASSWD|authorized_keys",
    re.IGNORECASE,
)
REMOTE_CONTENT_RE = re.compile(
    r"<(?:script|iframe|frame|embed|object|link)\b[^>]*\b(?:src|href|data)\s*=\s*"
    r"[\"']?(?:https?:)?//"
    r"|ActiveXObject|WScript\.Shell|Shell\.Application|Scripting\.FileSystemObject"
    r"|XMLHttpRequest|\bfetch\s*\(|document\.cookie",
    re.IGNORECASE,
)
# Where a rule looks: "script" is every ActionScript line (createfile content
# included) and every line of decoded text; "relevance" is each Relevance and
# Analysis Property; "desc" is each Description; "file" is the whole file.
SCRIPT, RELEVANCE, DESC, FILE = "script", "relevance", "desc", "file"


def _rule(code, scopes, label, pattern, flags=re.IGNORECASE):
    return code, frozenset(scopes), label, re.compile(pattern, flags)


# (code, scopes, label, regex) for the signals that are one pattern each
RULES = (
    # --- the BigFix platform itself
    _rule(
        "W940",
        [SCRIPT],
        "tampers with the BigFix client",
        r"\b(?:net|sc)(?:\.exe)?\s+(?:stop|config|delete)\s+\"?besclient"
        r"|systemctl\s+(?:stop|disable|mask)\s+besclient|service\s+besclient\s+stop"
        r"|/etc/init\.d/besclient\s+stop|launchctl\s+(?:unload|bootout)[^\n]*BESAgent"
        r"|BESAgent\s+(?:stop|uninstall)|(?:delete|\brm\b|Remove-Item)[^\n]*__BESData"
        r"|\b(?:actionsite|masthead)\.afxm",
    ),
    _rule(
        "W941",
        [SCRIPT],
        "redirects the client to another relay or server",
        r"setting\s+(?:delete\s+)?\"(?:__RelayServer[12]|_BESClient_RelaySelect_\w+"
        r"|_BESRelay_\w*ParentRelay\w*|_BESClient_Register_Affiliation\w*)\"",
    ),
    _rule(
        "W942",
        [SCRIPT],
        "uploads endpoint files to the root server",
        r"^archive\s+now\b|_BESClient_ArchiveManager_\w+|_BESClient_UploadManager_\w+",
    ),
    _rule(
        "W943",
        [FILE],
        "calls the BigFix REST API",
        r"/api/(?:actions?|fixlets?|tasks?|baselines?|sites?|computers?|query|login"
        r"|import|upload)\b",
    ),
    _rule(
        "W944", [FILE], "an action targeting all computers", r"<AllComputers>\s*true"
    ),
    _rule(
        "W945",
        [SCRIPT],
        "runs a command taken from a setting or a file",
        r"^(?:wait|run|waithidden|runhidden|dos)\s[^\n]*\{[^}]*"
        r"(?:value of setting|lines? of file|content of file)",
    ),
    _rule(
        "W946",
        [SCRIPT, RELEVANCE],
        "compares now to a fixed date (a time bomb?)",
        r"\bnow\s*[<>]=?\s*\(?\s*\"[^\"]*\d{4}[^\"]*\"\s*as\s+time"
        r"|\"[^\"]*\d{4}[^\"]*\"\s*as\s+time\s*\)?\s*[<>]=?\s*now\b",
    ),
    _rule(
        "W947",
        [SCRIPT, RELEVANCE],
        "pinned to one host",
        r"\b(?:computer name|hostname|dns name|mac address(?:es)?(?: of \w+)*"
        r"|address(?:es)? of (?:ip interfaces?|adapters?)(?: of \w+)*)\b"
        r"[^\n]{0,40}?=\s*\"[^\"]+\"",
    ),
    _rule(
        "W948",
        [SCRIPT],
        "a {parameter} in a command line (injection?)",
        r"^(?:wait|run|waithidden|runhidden|dos)\s[^\n]*\{\s*parameter\s+\"",
    ),
    # --- credentials and data leaving the endpoint
    _rule(
        "W950",
        [SCRIPT, RELEVANCE],
        "reads a credential store",
        r"/etc/shadow|\\config\\SAM\b|\b(?:HKLM|HKEY_LOCAL_MACHINE)\\(?:SAM|SECURITY)\b"
        r"|\.ssh[/\\]id_\w+|\bid_(?:rsa|dsa|ecdsa|ed25519)\b|Login Data|logins\.json"
        r"|key4\.db|login\.keychain|\.aws[/\\]credentials|\.kube[/\\]config|NTDS\.dit"
        r"|\blsass(?:\.exe)?\b",
    ),
    _rule(
        "W951",
        [SCRIPT],
        "dumps credentials or prompts for a password",
        r"mimikatz|sekurlsa|procdump(?:64)?(?:\.exe)?\s[^\n]*lsass"
        r"|comsvcs(?:\.dll)?[^\n]*MiniDump"
        r"|reg(?:\.exe)?\s+save\s+(?:HKLM|HKEY_LOCAL_MACHINE)\\(?:SAM|SECURITY|SYSTEM)\b"
        r"|ntdsutil|Get-Credential|with\s+hidden\s+answer|CredUIPrompt|lazagne",
    ),
    _rule(
        "W952",
        [SCRIPT],
        "weakens credential protection",
        r"UseLogonCredential[^\n]*dword:0*1\b|RunAsPPL[^\n]*dword:0+\b"
        r"|NoLMHash[^\n]*dword:0+\b|DisableRestrictedAdmin",
    ),
    _rule(
        "W953",
        [SCRIPT],
        "sends data off the endpoint",
        r"\bcurl\b[^\n]*\s(?:-d|--data(?:-\w+)?|-F|--form|-T|--upload-file)[\s=]"
        r"|Invoke-(?:WebRequest|RestMethod)\b[^\n]*-Method\s+[\"']?(?:Post|Put)\b"
        r"|\bscp\s+\S|\bsftp\s|\bftp(?:\.exe)?\s+-|Upload(?:File|String|Data)\s*\(",
    ),
    _rule(
        "W954",
        [FILE],
        "a URL on a paste, shortener, tunnel, raw-git or dynamic-DNS host",
        r"https?://(?:[\w-]+\.)*(?:pastebin\.com|paste\.ee|hastebin\.com|ghostbin\.\w+"
        r"|rentry\.co|bit\.ly|tinyurl\.com|t\.co|goo\.gl|is\.gd|ow\.ly|rebrand\.ly"
        r"|ngrok(?:-free)?\.(?:io|app|dev)|trycloudflare\.com|local\.lt|serveo\.net"
        r"|transfer\.sh|file\.io|anonfiles\.com|mega\.nz|discord(?:app)?\.com/attachments"
        r"|cdn\.discordapp\.com|raw\.githubusercontent\.com|gist\.githubusercontent\.com"
        r"|duckdns\.org|no-ip\.\w+|ddns\.net|hopto\.org|zapto\.org)\b",
    ),
    _rule(
        "W955",
        [FILE],
        "a URL with credentials in it",
        r"\b(?:https?|ftp)://[^/\s:@\"'<>]+:[^/\s@\"'<>]+@",
    ),
    # --- network trust and remote access
    _rule(
        "W956",
        [SCRIPT],
        "turns off TLS or host-key verification",
        r"\bcurl\b[^\n]*\s(?:-k|--insecure)\b|--no-check-certificate"
        r"|ServerCertificateValidationCallback|-SkipCertificateCheck"
        r"|PYTHONHTTPSVERIFY\s*=\s*0|verify\s*=\s*False"
        r"|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*[\"']?0|StrictHostKeyChecking[= ]+no",
    ),
    _rule(
        "W957",
        [SCRIPT],
        "adds a trusted root CA",
        r"certutil(?:\.exe)?\s[^\n]*-addstore\s+(?:-\w+\s+)*[\"']?root|add-trusted-cert"
        r"|Import-Certificate[^\n]*Root|update-ca-certificates|update-ca-trust"
        r"|\btrust\s+anchor",
    ),
    _rule(
        "W958",
        [SCRIPT],
        "changes hosts, DNS or proxy settings",
        r"drivers\\etc\\hosts|/etc/hosts\b|/etc/resolv\.conf|netsh\s+winhttp\s+set\s+proxy"
        r"|\bProxyServer\b|\bProxyEnable\b|networksetup\s+-set\w*proxy"
        r"|Set-DnsClientServerAddress|scutil\s[^\n]*dns",
    ),
    _rule(
        "W959",
        [SCRIPT],
        "enables remote access",
        r"fDenyTSConnections[^\n]*dword:0+\b|Enable-PSRemoting|winrm\s+quickconfig"
        r"|PermitRootLogin\s+yes|PasswordAuthentication\s+yes"
        r"|SMB1[^\n]*(?:\$true|dword:0*1\b)|net\s+user\s+guest\s+/active:yes"
        r"|LocalAccountTokenFilterPolicy[^\n]*dword:0*1\b"
        r"|systemsetup\s+-setremotelogin\s+on|kickstart[^\n]*-activate",
    ),
    # --- execution and evasion
    _rule(
        "W960",
        [SCRIPT],
        "bypasses AMSI/ETW, loads code reflectively or compiles it at run time",
        r"AmsiUtils|amsiInitFailed|AmsiScanBuffer|EtwEventWrite|Assembly\]::Load"
        r"|Assembly\.Load\(|Add-Type\s[^\n]*-TypeDefinition|\bcsc(?:\.exe)?\s"
        r"|\bmsbuild(?:\.exe)?\s+\S+\.(?:xml|csproj|proj)\b|InstallUtil(?:\.exe)?\s"
        r"|VirtualAlloc",
    ),
    _rule(
        "W961",
        [SCRIPT],
        "a built-in binary used to run code (LOLBin)",
        r"\bmshta(?:\.exe)?\b|regsvr32(?:\.exe)?\s[^\n]*/i:"
        r"|rundll32(?:\.exe)?\s[^\n]*(?:javascript:|,\s*#\d)"
        r"|wmic(?:\.exe)?\s[^\n]*process\s+call\s+create|\bodbcconf\b"
        r"|forfiles(?:\.exe)?\s[^\n]*/c\s|\bpcalua\b|\bcmstp\b"
        r"|\bmsiexec(?:\.exe)?\s[^\n]*/i\s*https?:",
    ),
    _rule(
        "W962",
        [SCRIPT],
        "keyword obfuscation",
        # a PowerShell backtick inside a word (not an escape like `r`n), cmd
        # carets inside a word, an env-var substring other than %DATE%/%TIME%,
        # split-and-joined strings, XOR, reversal, char-code joins
        r"\w`(?![0abefnrtv\W])[A-Za-z]`(?![0abefnrtv\W])[A-Za-z]|\b[a-z]\^[a-z]\^[a-z]"
        r"|%(?!DATE|TIME)\w+:~-?\d+(?:,-?\d+)?%|'[A-Za-z]{2,6}'\s*\+\s*'[A-Za-z]{2,6}'\s*\+"
        r"|-bxor\b|\[array\]::Reverse|-join\s*\(?\s*\[char",
    ),
    _rule(
        "W963",
        [FILE],
        "a bidi or zero-width character, which can hide code",
        "[----]",
        0,
    ),
    _rule(
        "W964",
        [SCRIPT],
        "stops or removes a security tool",
        r"(?:taskkill|pkill|killall|Stop-Process|net\s+stop|sc(?:\.exe)?\s+(?:stop|delete|config)"
        r"|Stop-Service|Set-Service|systemctl\s+(?:stop|disable|mask)"
        r"|launchctl\s+(?:unload|bootout)|uninstall|msiexec(?:\.exe)?\s+/x)[^\n]{0,80}?"
        r"(?:MsMpEng|WinDefend|\bSense\b|CrowdStrike|CSFalcon|falcon-sensor|Symantec"
        r"|McAfee|Sophos|SentinelOne|SentinelAgent|CarbonBlack|CbDefense|Cylance|Tanium"
        r"|osquery|sysmon|auditd)",
    ),
    _rule(
        "W965",
        [SCRIPT],
        "hides or backdates files",
        r"attrib(?:\.exe)?\s[^\n]*\+[hs]\b|\btouch\s+(?:-[a-z]+\s+)*-[a-z]*t\s*\d{8}"
        r"|SetFileTime|\.(?:Creation|LastWrite|LastAccess)Time(?:Utc)?\s*="
        r"|chflags\s+hidden|SetFile\s+-a\s+V",
    ),
    _rule(
        "W966",
        [SCRIPT],
        "loads a kernel driver or module",
        r"\binsmod\b|\bmodprobe\b|kextload|kmutil\s+load|sc(?:\.exe)?\s+create[^\n]*type=\s*kernel"
        r"|testsigning\s+on|nointegritychecks|fltmc\s+load",
    ),
    _rule(
        "W967",
        [SCRIPT],
        "setuid or world-writable permissions",
        r"chmod\s+(?:-R\s+)?(?:0?777|[ugoa]*\+s|[2467][0-7]{3})\b"
        r"|icacls(?:\.exe)?\s[^\n]*(?:Everyone|\*S-1-1-0):[()OICI]*F\b",
    ),
    _rule(
        "W968",
        [SCRIPT],
        "an offensive, recon or mining tool",
        r"\b(?:nmap|masscan|zmap|responder|bloodhound|sharphound|rubeus|impacket"
        r"|crackmapexec|netexec|meterpreter|metasploit|msfvenom|cobaltstrike|xmrig"
        r"|minerd|cpuminer|hashcat|lazagne)\b|stratum\+tcp|net\s+group\s+\"domain admins\"",
    ),
    # --- persistence
    _rule(
        "W970",
        [SCRIPT],
        "stealthy persistence",
        r"Image File Execution Options[^\n]*Debugger|\bsethc\.exe|\butilman\.exe"
        r"|__EventFilter|CommandLineEventConsumer|ActiveScriptEventConsumer"
        r"|Winlogon\\?[^\n]*\b(?:Userinit|Shell)\b|AppInit_DLLs|AppCertDlls"
        r"|ld\.so\.preload|\bLD_PRELOAD\b|DYLD_INSERT_LIBRARIES|\.bashrc|\.bash_profile"
        r"|\.zshrc|/etc/rc\.local|/etc/profile\.d",
    ),
    _rule(
        "W971",
        [SCRIPT],
        "persistence: a Run key, service, unit, scheduled task or cron job",
        r"regset(?:64)?\s+\"\[[^\]]*CurrentVersion\\Run(?:Once)?\]\"\s+\"[^\"]+\"\s*="
        r"|New-ItemProperty[^\n]*CurrentVersion\\Run|reg(?:\.exe)?\s+add\s[^\n]*CurrentVersion\\Run"
        r"|\bsc(?:\.exe)?\s+create\b|New-Service\b|/etc/systemd/system/[^\s\"]+\.(?:service|timer)"
        r"|launchctl\s+(?:load|bootstrap)|schtasks(?:\.exe)?\s[^\n]*/create"
        r"|Register-ScheduledTask|\bcrontab\b|/etc/cron\.",
    ),
    # --- destructive
    _rule(
        "W972",
        [SCRIPT],
        "a destructive disk operation",
        r"\bdiskpart\b|\bformat(?:\.com)?\s+[a-z]:|\bdd\s+[^\n]*\bof=/dev/(?!null\b)"
        r"|\bmkfs\b|\bshred\b|cipher(?:\.exe)?\s+/w|\brm\s+-(?=[a-z]*r)[a-z]+\s+/(?:\*|\s|$)"
        r"|Clear-Disk|Remove-Partition|Format-Volume|\bwipefs\b"
        r"|diskutil\s+(?:erase\w*|zeroDisk|secureErase)",
    ),
    _rule(
        "W973",
        [SCRIPT],
        "SQL that changes data",
        r"\b(?:DROP\s+(?:TABLE|DATABASE|SCHEMA)|TRUNCATE\s+TABLE|DELETE\s+FROM"
        r"|UPDATE\s+[\w.\[\]]+\s+SET|ALTER\s+TABLE|xp_cmdshell|sp_configure)\b",
    ),
    # --- Description HTML, rendered in the operator's console
    _rule(
        "W980",
        [DESC],
        "a password field in a Description",
        r"<input\b[^>]*\btype\s*=\s*[\"']?password",
    ),
    _rule(
        "W981",
        [DESC],
        "a UNC or file: link or image (can leak the operator's NTLM hash)",
        r"\b(?:src|href|data|background)\s*=\s*[\"']?(?:file:|\\\\)",
    ),
    _rule(
        "W982",
        [DESC],
        "a remote image or media file (a beacon on whoever opens it)",
        r"<(?:img|source|video|audio|input|body|table|td)\b[^>]*\b(?:src|background)"
        r"\s*=\s*[\"']?(?:https?:)?//",
    ),
    _rule(
        "W983",
        [DESC],
        "a redirect, base URL or off-page form",
        r"http-equiv\s*=\s*[\"']?refresh|<base\b[^>]*\bhref"
        r"|<form\b[^>]*\baction\s*=\s*[\"']?(?:https?:)?//",
    ),
    _rule(
        "W984",
        [DESC],
        "a hidden element",
        r"display\s*:\s*none|visibility\s*:\s*hidden",
    ),
)
SCRIPT_RULES = tuple(r for r in RULES if SCRIPT in r[1])
RELEVANCE_RULES = tuple(r for r in RULES if RELEVANCE in r[1])
DESC_RULES = tuple(r for r in RULES if DESC in r[1])
FILE_RULES = tuple(r for r in RULES if FILE in r[1])

HEREDOC_RE = re.compile(r"^createfile\s+until\s+(\S+)", re.IGNORECASE)
# a Task or Fixlet whose title says it only looks (W991) ...
READ_ONLY_TITLE_RE = re.compile(
    r"^\s*(?:check|audit|report|get|list|show|query|scan|detect|inventory|collect"
    r"|view|verify)\b",
    re.IGNORECASE,
)
# ... but whose action changes state; deleting the temporary __createfile or
# __appendfile is housekeeping, not a change
WRITE_COMMAND_RE = re.compile(
    r"^\s*(?:regset(?:64)?|regdelete(?:64)?|setting\s+(?:delete\s+)?\""
    r"|delete\s+(?!\"?__(?:createfile|appendfile)\b))",
    re.IGNORECASE | re.MULTILINE,
)

URL_RE = re.compile(r"\b(?:https?|ftp)://([^\s/\"'<>:]+)", re.IGNORECASE)
RAW_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
DOWNLOAD_LINE_RE = re.compile(r"^download(?:\s|$)", re.IGNORECASE)
NOHASH_RE = re.compile(r"^add\s+nohash\s+prefetch\s+item\b", re.IGNORECASE)
PREFETCH_RE = re.compile(r"^(?:prefetch|add\s+prefetch\s+item)\b", re.IGNORECASE)

# base64 wrapped across lines counts as one run; it must reach MIN_BASE64
BASE64_RE = re.compile(r"[A-Za-z0-9+/]{16,}(?:\s*[A-Za-z0-9+/]{16,})*={0,2}")
MIN_BASE64 = 80
IMAGE_PREFIX_RE = re.compile(r"data:image/([\w.+-]+);base64,\s*$", re.IGNORECASE)
HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")
# (regex, label, decoder) for the other encodings W924 finds
ENCODED_RUNS = (
    (
        re.compile(r"(?:\\x[0-9A-Fa-f]{2}){16,}"),
        "\\x escapes",
        lambda s: bytes.fromhex(s.replace("\\x", "")),
    ),
    (
        re.compile(r"(?:\\u[0-9A-Fa-f]{4}){8,}"),
        "\\u escapes",
        lambda s: "".join(chr(int(h, 16)) for h in s.split("\\u")[1:]).encode("utf-8"),
    ),
    (
        re.compile(r"(?:%[0-9A-Fa-f]{2}){8,}"),
        "%XX encoding",
        lambda s: bytes.fromhex(s.replace("%", "")),
    ),
    (
        re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}){40,}(?![0-9A-Fa-f])"),
        "hex",
        bytes.fromhex,
    ),
)

# what the bytes of each data:image/ type start with (svg is checked as text)
IMAGE_MAGIC = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "gif": (b"GIF87a", b"GIF89a"),
    "jpeg": (b"\xff\xd8\xff",),
    "jpg": (b"\xff\xd8\xff",),
    "x-icon": (b"\x00\x00\x01\x00",),
    "vnd.microsoft.icon": (b"\x00\x00\x01\x00",),
    "bmp": (b"BM",),
    "webp": (b"RIFF",),
}
EXECUTABLE_MAGIC = (
    b"MZ",
    b"\x7fELF",
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
)
SCRIPT_MARKER_RE = re.compile(
    r"^#!|<script\b|\bpowershell\b|\bcmd(?:\.exe)?\s+/c\b|/bin/(?:ba)?sh\b"
    r"|\b(?:wscript|cscript|mshta|rundll32|regsvr32)\b",
    re.IGNORECASE | re.MULTILINE,
)


class Finding(NamedTuple):
    line: int
    code: str
    points: int
    message: str


def band(score):
    """LOW, MEDIUM or HIGH for a risk score."""
    if score >= HIGH:
        return "HIGH"
    if score >= MEDIUM:
        return "MEDIUM"
    return "LOW"


class _Scanner:
    """Collects findings for one file, with its weights and decode budget."""

    def __init__(self, weights, disabled):
        self.weights = {**WEIGHTS, **(weights or {})}
        self.disabled = set(disabled or ())
        self.budget = MAX_DECODED

    def finding(self, line, code, message, points=None):
        """A Finding, or None for a disabled code."""
        if code in self.disabled:
            return None
        if points is None:
            points = self.weights[code]
        return Finding(line, code, points, message)

    # --- the parts of a BES file ------------------------------------------------

    def description(self, element):
        """W901-W903 and W924's API calls for one Description element."""
        # itertext gives CDATA and entity-escaped HTML decoded; a <?relevance?>
        # outside CDATA is a processing instruction, which itertext skips
        view = "".join(element.itertext()) + "".join(
            f"<?{pi.target} {pi.text or ''}?>"
            for pi in element.iter(etree.ProcessingInstruction)
        )
        line = element.sourceline or 1
        found = []
        script = SCRIPT_RE.search(view)
        session = SESSION_RE.search(view)
        if script:
            found.append(
                self.finding(line, "W901", f"script in a Description: {script[0]!r}")
            )
        if session:
            found.append(
                self.finding(
                    line,
                    "W902",
                    "session relevance in a Description runs as the console "
                    f"operator: {session[0]!r}",
                )
            )
        if script and session:
            found.append(
                self.finding(
                    line, "W903", "a Description script built from session relevance"
                )
            )
        api = OBFUSCATION_API_RE.search(view)
        if api:
            found.append(
                self.finding(
                    line, "W924", f"obfuscation call in a Description: {api[0]!r}"
                )
            )
        remote = REMOTE_CONTENT_RE.search(view)
        if remote:
            found.append(
                self.finding(
                    line,
                    "W932",
                    f"a Description reaching outside the page: {remote[0]!r}",
                )
            )
        found.extend(self._rules(DESC_RULES, line, view))
        return found

    def relevance(self, element):
        """The relevance-scope rules for one Relevance or Property element."""
        return self._rules(RELEVANCE_RULES, element.sourceline or 1, element.text or "")

    def file(self, src, line_of):
        """The file-scope rules, at every match in `src`."""
        found = []
        for code, _scopes, label, regex in FILE_RULES:
            for match in regex.finditer(src):
                if code == "W963" and match.start() == 0 and match[0] == "\ufeff":
                    continue  # a byte-order mark opening the file
                found.append(
                    self.finding(line_of(match.start()), code, f"{label}: {match[0]!r}")
                )
        return found

    def _rules(self, rules, line, text):
        """One finding per rule that matches `text`, all on `line`."""
        found = []
        for code, _scopes, label, regex in rules:
            match = regex.search(text)
            if match:
                found.append(self.finding(line, code, f"{label}: {match[0]!r}"))
        return found

    def actionscript(self, element):
        """W910-W913 and W923 for one ActionScript element."""
        body = (element.text or "").replace("\r\n", "\n").replace("\r", "\n")
        start = element.sourceline or 1
        lines = body.split("\n")
        found = []
        mimetype = element.get("MIMEType")
        if mimetype is None or mimetype == ACTIONSCRIPT_MIMETYPE:
            # commands only: createfile content is data, scanned below
            masked, _issues = _mask_heredocs(lines)
            for offset, text in enumerate(masked):
                found.extend(self._command(start + offset, text.strip()))
            found.extend(self._large_heredocs(start, lines))
        for offset, text in enumerate(lines):
            stripped = text.strip()
            if not stripped or stripped.startswith("//"):
                continue
            found.extend(self._script_line(start + offset, stripped))
        return found

    def _large_heredocs(self, start, lines):
        """W990 for a createfile payload longer than MAX_HEREDOC_LINES."""
        found = []
        for offset, text in enumerate(lines):
            heredoc = HEREDOC_RE.match(text.strip())
            if not heredoc:
                continue
            size = 0
            for later in lines[offset + 1 :]:
                if later == heredoc[1]:
                    break
                size += 1
            if size > MAX_HEREDOC_LINES:
                found.append(
                    self.finding(
                        start + offset,
                        "W990",
                        f"a {size}-line createfile payload is hard to review",
                    )
                )
        return found

    def _command(self, line, text):
        """W910-W912 for one ActionScript command line."""
        if DOWNLOAD_LINE_RE.match(text):
            yield self.finding(
                line,
                "W910",
                "download with no hash check; use a prefetch with sha256 and size",
            )
        elif NOHASH_RE.match(text):
            yield self.finding(line, "W911", "nohash prefetch item: not hash-checked")
        elif not PREFETCH_RE.match(text):
            return
        for url in URL_RE.finditer(text):
            insecure = url[0].lower().startswith(("http:", "ftp:"))
            if insecure or RAW_IP_RE.match(url[1]):
                yield self.finding(
                    line,
                    "W912",
                    f"download URL over plain http or to a raw IP: {url[0]}",
                )

    def _script_line(self, line, text):
        """W913, W923, W931 and the script rules for a line of script content."""
        download = DOWNLOAD_CMD_RE.search(text)
        if download:
            yield self.finding(line, "W913", f"download command: {download[0]!r}")
        decode = DECODE_CMD_RE.search(text)
        if decode:
            yield self.finding(
                line, "W923", f"decode or dynamic-run command: {decode[0]!r}"
            )
        weaken = WEAKEN_RE.search(text)
        if weaken:
            yield self.finding(
                line, "W931", f"command that weakens security: {weaken[0]!r}"
            )
        yield from self._rules(SCRIPT_RULES, line, text)

    def secrets(self, src, line_of):
        """W930 for every hardcoded secret in `src`; line_of(pos) -> line."""
        return [
            # the value itself is left out of the message, so the report
            # does not copy the secret somewhere else
            self.finding(
                line_of(match.start()),
                "W930",
                f"hardcoded secret: {_secret_label(match[0])}",
            )
            for match in SECRET_RE.finditer(src)
            if not _not_a_secret(src, match)
        ]

    # --- encoded content anywhere ---------------------------------------------------

    def encoded(self, src, line_of, depth):
        """W920-W927 for every encoded run in `src`; line_of(pos) -> line."""
        found = []
        for match in BASE64_RE.finditer(src):
            found.extend(self._base64(src, match, line_of(match.start()), depth))
        for regex, label, decoder in ENCODED_RUNS:
            for match in regex.finditer(src):
                if label == "hex" and re.search(
                    r"sha\w*\W{0,3}$",
                    src[max(0, match.start() - 12) : match.start()],
                    re.IGNORECASE,
                ):
                    continue  # a hash value, not a payload
                try:
                    data = decoder(match[0])
                except (ValueError, OverflowError):
                    continue
                if not data.isascii():
                    continue  # non-English text, not hidden ASCII
                line = line_of(match.start())
                found.append(
                    self.finding(line, "W924", f"{len(match[0])} characters of {label}")
                )
                found.extend(self._payload(data, [label], line, depth))
        return found

    def _base64(self, src, match, line, depth):
        run = re.sub(r"\s+", "", match[0])
        if len(run) < MIN_BASE64 or HEX_RE.match(run.rstrip("=")):
            return []
        # real base64 of 60+ bytes all but surely has a digit or + in it;
        # a long path or word run (letters and slashes) does not
        if not re.search(r"[0-9+]", run) or run.count("/") > len(run) // 10 + 2:
            return []
        # a URL path (a VirusTotal report's /file/<sha256>/analysis) is not a
        # payload: skip a run in the same token as a `scheme://`
        token = re.split(
            r"[\s\"'<>()]", src[max(0, match.start() - 2048) : match.start()]
        )
        if "://" in token[-1]:
            return []
        try:
            data = base64.b64decode(run + "=" * (-len(run) % 4), validate=True)
        except (binascii.Error, ValueError):
            return []
        image = IMAGE_PREFIX_RE.search(src[max(0, match.start() - 80) : match.start()])
        if image:
            kind = image[1].lower()
            if kind == "svg+xml":
                text = _as_text(data)
                if text is not None and "<svg" in text.lower():
                    return [
                        self.finding(line, "W920", "base64 SVG image"),
                        *self._text(text, ["base64", "svg"], line, depth),
                    ]
            elif data.startswith(IMAGE_MAGIC.get(kind, (b"\x00\x00no",))):
                return [self.finding(line, "W920", f"base64 {kind} image")]
            return [
                self.finding(
                    line,
                    "W926",
                    f"base64 labelled image/{kind} is not a {kind} image",
                ),
                *self._payload(data, ["base64"], line, depth),
            ]
        return [
            self.finding(line, "W921", f"{len(run)} characters of base64"),
            *self._payload(data, ["base64"], line, depth),
        ]

    def _payload(self, data, path, line, depth):
        """Inspect decoded bytes: W922, W925, and W927 for what they hold."""
        self.budget -= len(data)
        if self.budget < 0 or depth >= MAX_DEPTH:
            return []
        found = []
        if data.startswith(EXECUTABLE_MAGIC):
            found.append(
                self.finding(
                    line, "W922", f"decoded {'->'.join(path)} is an executable"
                )
            )
            return found
        inflated = _inflate(data)
        if inflated is not None:
            kind, data = inflated
            path = [*path, kind]
            self.budget -= len(data)
            found.append(
                self.finding(line, "W925", f"decoded {'->'.join(path)} is compressed")
            )
            if data.startswith(EXECUTABLE_MAGIC):
                found.append(
                    self.finding(
                        line, "W922", f"decoded {'->'.join(path)} is an executable"
                    )
                )
                return found
        text = _as_text(data)
        if text is None:
            return found
        marker = SCRIPT_MARKER_RE.search(text)
        if marker:
            found.append(
                self.finding(
                    line,
                    "W922",
                    f"decoded {'->'.join(path)} is a script: {marker[0]!r}",
                )
            )
        found.extend(self._text(text, path, line, depth))
        return found

    def _text(self, text, path, line, depth):
        """W927: the findings in decoded text, folded into one."""
        inner = [f for f in self._generic(text, depth + 1) if f]
        if not inner:
            return []
        bonus = self.finding(line, "W927", "")
        if bonus is None:
            return []
        summary = ", ".join(f"{f.code} {f.message}" for f in inner[:5])
        if len(inner) > 5:
            summary += f", and {len(inner) - 5} more"
        return [
            bonus._replace(
                points=sum(f.points for f in inner) + bonus.points,
                message=f"decoded {'->'.join([*path, 'text'])} holds: {summary}",
            )
        ]

    def _generic(self, text, depth):
        """Every signal that can apply to decoded text, all on the outer line."""
        found = []
        line = 1  # rewritten by the caller's line through W927
        script = SCRIPT_RE.search(text)
        if script:
            found.append(self.finding(line, "W901", f"script {script[0]!r}"))
        api = OBFUSCATION_API_RE.search(text)
        if api:
            found.append(self.finding(line, "W924", f"obfuscation call {api[0]!r}"))
        remote = REMOTE_CONTENT_RE.search(text)
        if remote:
            found.append(self.finding(line, "W932", f"remote content {remote[0]!r}"))
        found.extend(self.secrets(text, lambda pos: line))
        found.extend(self.file(text, lambda pos: line))
        found.extend(self._rules(DESC_RULES, line, text))
        for text_line in text.splitlines():
            stripped = text_line.strip()
            if stripped and not stripped.startswith("//"):
                found.extend(self._command(line, stripped))
                found.extend(self._script_line(line, stripped))
        found.extend(self.encoded(text, lambda pos: line, depth))
        return found


# the `override` option password= takes one of these keywords, not a secret
# (bes_actionscript_lint_schclass documents the same set)
OVERRIDE_PASSWORD_VALUES = frozenset({"required", "empty", "impersonate", "system"})
# an unquoted identifier followed by a call, separator or close: a variable
# or function in code (`{ secret: params }`, `$PWD = Hash (...)`), not a value
CODE_REFERENCE_RE = re.compile(r"[A-Za-z_$][\w$.]*\s*[(,})]")


def _not_a_secret(src, match):
    """True for a SECRET_RE match that is plainly not a literal secret."""
    parts = re.split(r"\s*[:=]\s*", match[0], maxsplit=1)
    if len(parts) < 2 or parts[1][:1] in "\"'":
        return False  # a key, or a quoted value: always a finding
    name, value = parts
    if name.lower() == "password" and value.lower() in OVERRIDE_PASSWORD_VALUES:
        return True
    start = match.end() - len(value)
    return bool(CODE_REFERENCE_RE.match(src, start))


def _secret_label(text):
    """What a W930 match is, without the secret value."""
    if text.startswith("-----"):
        return "a private key"
    if text[:4].upper() == "AKIA":
        return "an AWS access key ID"
    name = re.match(r"[\w-]+", text)[0]
    return f"{name} set to a literal value"


def _inflate(data):
    """(kind, decompressed bytes) for gzip, zlib or zip data, else None."""
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
                if not names:
                    return None
                with archive.open(names[0]) as member:
                    return "zip", member.read(MAX_INFLATE)
        except (zipfile.BadZipFile, OSError, RuntimeError, ValueError):
            return None
    for kind, magic, wbits in (
        ("gzip", (b"\x1f\x8b",), 31),
        ("zlib", (b"\x78\x01", b"\x78\x5e", b"\x78\x9c", b"\x78\xda"), 15),
    ):
        if data.startswith(magic):
            try:
                return kind, zlib.decompressobj(wbits).decompress(data, MAX_INFLATE)
            except zlib.error:
                return None
    return None


def _as_text(data):
    """Decoded bytes as text (UTF-16LE when every other byte is NUL), or None."""
    if (
        len(data) >= 4
        and len(data) % 2 == 0
        and data[1::2].count(0) >= len(data) // 2 * 0.9
    ):
        candidates = ("utf-16-le",)
    else:
        candidates = ("utf-8", "latin-1")
    for encoding in candidates:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        printable = sum(1 for c in text if c.isprintable() or c in "\r\n\t")
        if text and printable >= 0.9 * len(text):
            return text
    return None


def score_text(src, weights=None, disabled=()):
    """Return (findings, score) for a BES document's text.

    Raises etree.XMLSyntaxError if it does not parse.
    """
    root = etree.fromstring(src.encode("utf-8"))
    scanner = _Scanner(weights, disabled)
    found = []
    for element in root.iter("Description"):
        found.extend(scanner.description(element))
    for element in root.iter("ActionScript"):
        found.extend(scanner.actionscript(element))
    for element in root.iter("Relevance", "Property"):
        found.extend(scanner.relevance(element))
    found.extend(_read_only_titles(scanner, root))

    def line_of(pos):
        return bes_common.lineno(src, pos)

    found.extend(scanner.secrets(src, line_of))
    found.extend(scanner.file(src, line_of))
    found.extend(scanner.encoded(src, line_of, 0))
    found = [f for f in found if f is not None]
    found.extend(_combinations(scanner, found))
    found = sorted(f for f in found if f is not None)
    return found, sum(f.points for f in found)


def _read_only_titles(scanner, root):
    """W991 for a Task or Fixlet titled like a check whose action writes."""
    for content in root:
        if content.tag not in ("Task", "Fixlet"):
            continue
        title = content.find("Title")
        if title is None or not READ_ONLY_TITLE_RE.match(title.text or ""):
            continue
        for script in content.iter("ActionScript"):
            write = WRITE_COMMAND_RE.search(script.text or "")
            if write:
                yield scanner.finding(
                    title.sourceline or 1,
                    "W991",
                    f"titled {title.text.strip()[:60]!r} but its action writes: "
                    f"{write[0].strip()!r}",
                )
                break


def _combinations(scanner, found):
    """W949: an upload (W942) from a file that reads a credential store (W950)."""
    by_code = {}
    for finding in found:
        by_code.setdefault(finding.code, finding)
    if "W942" in by_code and "W950" in by_code:
        yield scanner.finding(
            by_code["W942"].line,
            "W949",
            "uploads files and reads a credential store: secrets may end up on "
            "the server",
        )


def check_file(path, fail_score, weights=None, disabled=()):
    """Return (issues, score) for one file, issues as (line, code, message)."""
    _raw, src, _crlf = bes_common.read_source(path)
    try:
        found, total = score_text(src, weights, disabled)
    except etree.XMLSyntaxError as err:
        return [(1, "W908", f"not parseable XML ({err}); skipping")], 0
    issues = [(f.line, f.code, f"(+{f.points}) {f.message}") for f in found]
    if total >= fail_score:
        issues.insert(
            0,
            (
                1,
                "E900",
                (
                    f"risk score {total} ({band(total)}) is at or over --fail-score "
                    f"{fail_score}: review this content carefully before trusting it"
                ),
            ),
        )
    elif total >= MEDIUM:
        issues.insert(0, (1, "W900", f"risk score {total} ({band(total)})"))
    return issues, total


def _weight(value):
    """Argparse type for CODE=N."""
    code, sep, points = value.partition("=")
    code = code.strip().upper()
    if not sep or code not in WEIGHTS:
        raise argparse.ArgumentTypeError(
            f"expected CODE=N with a W9xx code, not {value!r}"
        )
    try:
        return code, int(points)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{points!r} is not a whole number") from None


def main(argv=None):
    """Execution starts here; returns 1 when any file reaches --fail-score."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("files", nargs="*", help="BES files (default: all under .)")
    parser.add_argument(
        "--fail-score",
        type=int,
        default=HIGH,
        help=f"fail a file whose risk score reaches this (default {HIGH}, HIGH)",
    )
    parser.add_argument(
        "--weight",
        type=_weight,
        action="append",
        default=[],
        metavar="CODE=N",
        help="change a signal's points, e.g. --weight W921=10 (repeatable)",
    )
    parser.add_argument(
        "--disable",
        default="",
        metavar="CODES",
        help="comma-separated signal codes to skip, e.g. --disable W920",
    )
    args = parser.parse_args(argv)
    weights = dict(args.weight)
    disabled = {c.strip().upper() for c in args.disable.split(",") if c.strip()}
    files = args.files or bes_common.discover_bes_files()
    results = []
    for path in files:
        try:
            issues, _total = check_file(path, args.fail_score, weights, disabled)
        except OSError as err:
            issues = [(1, "W908", f"cannot read ({err}); skipping")]
        results.append((path, issues, []))
    errors, _warnings, _fixes = bes_common.report(results)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
