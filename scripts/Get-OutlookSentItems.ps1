<#
.SYNOPSIS
  Read a single day's messages from the local Outlook Sent Items folder and emit them as JSON.

.DESCRIPTION
  Used by the `close-day` skill to sweep mail the user sent today, so it can spot questions /
  requests made of other people and propose matching "Waiting For" entries. Talks to a
  locally-installed Outlook through its COM automation interface using LATE-BOUND IDispatch.
  It first attaches to the already-running, authenticated Outlook session
  (Marshal.GetActiveObject) and only falls back to launching a new instance. Do NOT switch this
  to Python win32com / EnsureDispatch — the gencache/typelib path is broken on this machine.

  Sent-mail reads only. The script never sends, moves, or modifies any Outlook item.

  CACHED-MODE / HEADER-ONLY CAVEAT: if the mailbox is in Cached Exchange Mode set to
  "Download Headers Only" (Outlook does this when it thinks the connection — e.g. a VPN — is
  slow), message BODIES and RECIPIENTS live on the server but are not synced locally, so COM
  returns them empty even though Subject/SentOn are present. Such items report
  `DownloadState = 1` (olHeaderOnly); the script surfaces `headerOnlyCount` and a `warning`.
  This is NOT a script bug — fix it in Outlook: Send/Receive > Download Preferences >
  "Download Full Items", uncheck "On Slow Connections Download Only Headers", then press F9.

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

    $messages   = @()
    $headerOnly = 0
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
    if ($headerOnly -gt 0) {
        $warning = "$headerOnly of $($messages.Count) sent items are header-only (Cached Exchange Mode 'Download Headers Only'): bodies/recipients are on the server but not synced locally, so COM returns them empty. This is NOT a script bug. Fix in Outlook: Send/Receive > Download Preferences > 'Download Full Items', uncheck 'On Slow Connections Download Only Headers', then press F9."
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
