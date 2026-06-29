<#
.SYNOPSIS
  Read a single day's messages from the local Outlook Sent Items folder and emit them as JSON.

.DESCRIPTION
  Used by the `close-day` skill to sweep the mail Dan sent today, so it can spot questions /
  requests he made of other people and propose matching "Waiting For" entries. Talks to a
  locally-installed Outlook through its COM automation interface using LATE-BOUND IDispatch
  (`New-Object -ComObject Outlook.Application`). Do NOT switch this to Python win32com /
  EnsureDispatch — the gencache/typelib path is broken on this machine.

  Sent-mail reads only. The script never sends, moves, or modifies any Outlook item.

.PARAMETER Date
  The day to read (any parseable date). Defaults to today.

.PARAMETER OutFile
  Optional path to also write the JSON to (UTF-8, no BOM). JSON is always written to stdout.

.PARAMETER BodyMaxChars
  Truncate each message body to this many characters (default 1500) to keep output sane.

.OUTPUTS
  JSON object: { date, dayOfWeek, count, messages: [ { sentOn, subject, to, cc, recipients,
  containsQuestion, body } ] }
  `containsQuestion` is a heuristic flag (a '?' appears in the subject or body) so the caller
  can prioritize messages where Dan likely asked someone for something. The caller still reads
  the body to judge whether a "Waiting For" item is warranted and who owns the next move.

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

    $ol   = New-Object -ComObject Outlook.Application
    $ns   = $ol.GetNamespace('MAPI')
    $sent = $ns.GetDefaultFolder(5)   # olFolderSentMail

    $items = $sent.Items
    $items.Sort('[SentOn]', $true)

    # Outlook Restrict requires US-style "MM/dd/yyyy hh:mm tt" literals regardless of locale.
    $fmt    = 'MM/dd/yyyy hh:mm tt'
    $filter = "[SentOn] >= '" + $dayStart.ToString($fmt) + "' AND [SentOn] < '" + $dayEnd.ToString($fmt) + "'"
    $msgs   = $items.Restrict($filter)

    $messages = @()
    foreach ($m in $msgs) {
        # Sent Items can contain non-mail items (meeting responses, etc.); guard property access.
        $subject = ''
        try { $subject = [string]$m.Subject } catch {}
        $body = ''
        try { $body = [string]$m.Body } catch {}
        if ($body -and $body.Length -gt $BodyMaxChars) {
            $body = $body.Substring(0, $BodyMaxChars) + ' …[truncated]'
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

        $containsQuestion = ($subject -match '\?') -or ($body -match '\?')

        $messages += [ordered]@{
            sentOn           = $sentOn
            subject          = $subject
            to               = $to
            cc               = $cc
            recipients       = $recipients
            containsQuestion = [bool]$containsQuestion
            body             = $body
        }
    }

    $messages = @($messages | Sort-Object { $_.sentOn })

    Write-JsonResult ([ordered]@{
        date      = $dayStart.ToString('yyyy-MM-dd')
        dayOfWeek = $dayStart.DayOfWeek.ToString()
        count     = $messages.Count
        messages  = $messages
    })
}
catch {
    Write-JsonResult ([ordered]@{
        date      = $Date.Date.ToString('yyyy-MM-dd')
        dayOfWeek = $Date.Date.DayOfWeek.ToString()
        count     = 0
        messages  = @()
        error     = $_.Exception.Message
    })
    exit 1
}
