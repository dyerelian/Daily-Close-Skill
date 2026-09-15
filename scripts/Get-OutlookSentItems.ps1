<#
.SYNOPSIS
  Read a single day's messages from the local Outlook Sent Items folder and emit them as JSON.

.DESCRIPTION
  Used by the `close-day` skill to sweep the mail Dan sent today, so it can spot questions /
  requests he made of other people and propose matching "Waiting For" entries. Talks to a
  locally-installed Outlook through its COM automation interface using LATE-BOUND IDispatch.
  It first attaches to the already-running, authenticated Outlook session
  (Marshal.GetActiveObject) and only falls back to launching a new instance. Do NOT switch this
  to Python win32com / EnsureDispatch — the gencache/typelib path is broken on this machine.

  Sent-mail reads only. The script never sends, moves, or modifies any Outlook item.

  EMPTY BODY / RECIPIENTS: message BODIES and RECIPIENTS can come back empty even though
  Subject/SentOn are present. Two different causes, and the script distinguishes them in
  `warning` because only one of them is fixable:

    * EVERY item empty — on this machine that is the GPO-enforced Outlook OBJECT MODEL GUARD
      blocking programmatic access to that content. It is not fixable from Outlook's UI:
      switching to "Download Full Items" does NOT help (verified). The waiting-for sweep then
      has to run on subjects and send times alone.
    * SOME items empty — genuine Cached Exchange Mode "Download Headers Only" (Outlook does this
      when it thinks the connection, e.g. a VPN, is slow). Those items report `DownloadState = 1`
      (olHeaderOnly). Fix in Outlook: Send/Receive > Download Preferences > "Download Full Items",
      uncheck "On Slow Connections Download Only Headers", then press F9.

  Either way it is NOT a script bug; the script surfaces `headerOnlyCount` and a `warning`.
  `headerOnlyCount` counts explicit `DownloadState = 1`; the all-empty case is detected
  separately, since the Object Model Guard empties content without setting DownloadState.

.PARAMETER Date
  The day to read (any parseable date). Defaults to today.

.PARAMETER OutFile
  Optional path to also write the JSON to (UTF-8, no BOM). JSON is always written to stdout.

.PARAMETER BodyMaxChars
  Truncate each message body to this many characters (default 1500) to keep output sane.

.OUTPUTS
  JSON object: { date, dayOfWeek, count, headerOnlyCount, warning, messages: [ { sentOn,
  subject, to, cc, recipients, containsQuestion, downloadState, body } ] }
  `downloadState`: 0 unknown, 1 header-only (body/recipients not synced), 2 full item.
  `containsQuestion` is a heuristic ('?' in subject or body) to prioritize likely requests.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File Get-OutlookSentItems.ps1
.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File Get-OutlookSentItems.ps1 -Date 2026-06-29 -OutFile "$env:TEMP\sent.json"
#>
[CmdletBinding()]
param(
    [datetime] $Date = (Get-Date).Date,
    [string]   $OutFile,
    [int]      $BodyMaxChars = 1500
)

$ErrorActionPreference = 'Stop'

# Attach to the user's already-running, authenticated Outlook session when possible (its store
# is the one with cached content); only launch a fresh background instance as a fallback.
function Get-OutlookApp {
    try { return [System.Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') }
    catch { return New-Object -ComObject Outlook.Application }
}

function Write-JsonResult {
    param([object] $Obj)
    $json = $Obj | ConvertTo-Json -Depth 6
    Write-Output $json
    if ($OutFile) {
        $enc = New-Object System.Text.UTF8Encoding($false)  # no BOM
        [System.IO.File]::WriteAllText($OutFile, $json, $enc)
    }
}

try {
    $dayStart = $Date.Date
    $dayEnd   = $dayStart.AddDays(1)

    $ol   = Get-OutlookApp
    $ns   = $ol.GetNamespace('MAPI')
    $sent = $ns.GetDefaultFolder(5)   # olFolderSentMail

    $items = $sent.Items
    $items.Sort('[SentOn]', $true)

    # Outlook Restrict requires US-style "MM/dd/yyyy hh:mm tt" literals regardless of locale.
    $fmt    = 'MM/dd/yyyy hh:mm tt'
    $filter = "[SentOn] >= '" + $dayStart.ToString($fmt) + "' AND [SentOn] < '" + $dayEnd.ToString($fmt) + "'"
    $msgs   = $items.Restrict($filter)

    $messages     = @()
    $headerOnly   = 0
    $emptyContent = 0
    foreach ($m in $msgs) {
        # Sent Items can contain non-mail items (meeting responses, etc.); guard property access.
        $subject = ''
        try { $subject = [string]$m.Subject } catch {}
        $body = ''
        try { $body = [string]$m.Body } catch {}
        if ($body -and $body.Length -gt $BodyMaxChars) {
            $body = $body.Substring(0, $BodyMaxChars) + ' ...[truncated]'
        }

        $to = ''
        try { $to = [string]$m.To } catch {}
        $cc = ''
        try { $cc = [string]$m.CC } catch {}

        # Resolved display names of the actual recipients, when available.
        $recipients = @()
        try {
            foreach ($r in $m.Recipients) { $recipients += [string]$r.Name }
        } catch {}

        $sentOn = ''
        try { $sentOn = (Get-Date $m.SentOn).ToString('yyyy-MM-ddTHH:mm') } catch {}

        # 1 = olHeaderOnly: body/recipients are on the server but not synced into the local cache.
        $ds = $null
        try { $ds = [int]$m.DownloadState } catch {}
        if ($ds -eq 1) { $headerOnly++ }
        # Fallback signal: the Object Model Guard empties bodies/recipients without setting
        # DownloadState, so count subjects-only items too (mirrors Get-OutlookMeetings.ps1).
        if ([string]::IsNullOrEmpty($body) -and [string]::IsNullOrEmpty($to) -and $recipients.Count -eq 0) { $emptyContent++ }

        $containsQuestion = ($subject -match '\?') -or ($body -match '\?')

        $messages += [ordered]@{
            sentOn           = $sentOn
            subject          = $subject
            to               = $to
            cc               = $cc
            recipients       = $recipients
            containsQuestion = [bool]$containsQuestion
            downloadState    = $ds
            body             = $body
        }
    }

    $messages = @($messages | Sort-Object { $_.sentOn })

    $warning = ''
    if ($headerOnly -gt 0 -or ($messages.Count -gt 0 -and $emptyContent -eq $messages.Count)) {
        $n = if ($headerOnly -gt 0) { $headerOnly } else { $emptyContent }
        $allEmpty = ($messages.Count -gt 0 -and $emptyContent -eq $messages.Count)
        $warning = "$n of $($messages.Count) sent items returned no body/recipients. This is NOT a script bug."
        if ($allEmpty) {
            # 100% empty is the signature of the GPO-enforced Outlook Object Model Guard on this
            # machine, not Cached Exchange Mode. Changing Download Preferences does NOT fix it --
            # do not send Dan down that path. Genuine header-only sync is partial, not total.
            $warning += " EVERY item came back empty, which on this machine is the GPO-enforced Outlook Object Model Guard blocking programmatic access to bodies/recipients -- 'Download Full Items' will NOT fix it (already verified). The waiting-for sweep has to run on subjects and send times alone; ask Dan to paste any thread that matters."
        } else {
            $warning += " Cached Exchange Mode 'Download Headers Only' keeps that content on the server, unsynced, so COM reads it empty. Fix in Outlook: Send/Receive > Download Preferences > 'Download Full Items', uncheck 'On Slow Connections Download Only Headers', then press F9."
        }
    }

    Write-JsonResult ([ordered]@{
        date            = $dayStart.ToString('yyyy-MM-dd')
        dayOfWeek       = $dayStart.DayOfWeek.ToString()
        count           = $messages.Count
        headerOnlyCount = $headerOnly
        warning         = $warning
        messages        = $messages
    })
}
catch {
    Write-JsonResult ([ordered]@{
        date            = $Date.Date.ToString('yyyy-MM-dd')
        dayOfWeek       = $Date.Date.DayOfWeek.ToString()
        count           = 0
        headerOnlyCount = 0
        warning         = ''
        messages        = @()
        error           = $_.Exception.Message
    })
    exit 1
}
