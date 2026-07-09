<#
.SYNOPSIS
  Read a single day's appointments from the local Outlook calendar and emit them as JSON.

.DESCRIPTION
  Used by the `close-day` skill to gather tomorrow's meetings so it can draft an agenda for
  each. Talks to a locally-installed Outlook through its COM automation interface using
  LATE-BOUND IDispatch. It first attaches to the already-running, authenticated Outlook session
  (Marshal.GetActiveObject) and only falls back to launching a new instance. Do NOT switch this
  to Python win32com / EnsureDispatch — the gencache/typelib path is broken on this machine.

  Calendar reads only. The script never sends, moves, or modifies any Outlook item.

  CACHED-MODE / HEADER-ONLY CAVEAT: if the mailbox is in Cached Exchange Mode set to
  "Download Headers Only" (Outlook does this when it thinks the connection — e.g. a VPN — is
  slow), appointment BODIES, ORGANIZER, and ATTENDEES live on the server but are not synced
  locally, so COM returns them empty even though Subject/Start/End/Location are present. Such
  items report `DownloadState = 1` (olHeaderOnly); the script surfaces `headerOnlyCount` and a
  `warning`. This is NOT a script bug — fix it in Outlook: Send/Receive > Download Preferences >
  "Download Full Items", uncheck "On Slow Connections Download Only Headers", then press F9.

.PARAMETER Date
  The day to read (any parseable date). Defaults to tomorrow.

.PARAMETER OutFile
  Optional path to also write the JSON to (UTF-8, no BOM). JSON is always written to stdout.

.PARAMETER BodyMaxChars
  Truncate each appointment body to this many characters (default 2000) to keep output sane.

.OUTPUTS
  JSON object: { date, dayOfWeek, isWeekend, suggestedTargetDay, holidayHints, count,
  headerOnlyCount, warning, meetings: [ { subject, start, end, location, organizer,
  requiredAttendees, optionalAttendees, isAllDay, downloadState, body } ] }
  `downloadState`: 0 unknown, 1 header-only (body/organizer/attendees not synced), 2 full item.
  `suggestedTargetDay` is the next weekday on/after `date` (handy when `date` is a weekend).
  `holidayHints` lists all-day event subjects on `date` that look like holidays / time off.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File Get-OutlookMeetings.ps1
.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File Get-OutlookMeetings.ps1 -Date 2026-06-29 -OutFile "$env:TEMP\meetings.json"
#>
[CmdletBinding()]
param(
    [datetime] $Date = (Get-Date).Date.AddDays(1),
    [string]   $OutFile,
    [int]      $BodyMaxChars = 2000
)

$ErrorActionPreference = 'Stop'

# All-day events whose subject matches this are surfaced as holiday/time-off hints.
$HolidayRe = 'holiday|day off|time off|\bpto\b|\booo\b|out of office|vacation|observ|closed|' +
             "new year|memorial day|independence|juneteenth|labor day|thanksgiving|christmas|" +
             'veterans day|presidents day|martin luther king|\bmlk\b'

# Attach to the user's already-running, authenticated Outlook session when possible (its store
# is the one with cached content); only launch a fresh background instance as a fallback.
function Get-OutlookApp {
    try { return [System.Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') }
    catch { return New-Object -ComObject Outlook.Application }
}

function Get-NextWeekday {
    param([datetime] $From)
    $d = $From.Date
    while ($d.DayOfWeek -eq [DayOfWeek]::Saturday -or $d.DayOfWeek -eq [DayOfWeek]::Sunday) {
        $d = $d.AddDays(1)
    }
    return $d
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

    $ol  = Get-OutlookApp
    $ns  = $ol.GetNamespace('MAPI')
    $cal = $ns.GetDefaultFolder(9)   # olFolderCalendar

    $items = $cal.Items
    $items.IncludeRecurrences = $true
    $items.Sort('[Start]')

    # Outlook Restrict requires US-style "MM/dd/yyyy hh:mm tt" literals regardless of locale.
    $fmt    = 'MM/dd/yyyy hh:mm tt'
    $filter = "[Start] >= '" + $dayStart.ToString($fmt) + "' AND [Start] < '" + $dayEnd.ToString($fmt) + "'"
    $appts  = $items.Restrict($filter)

    $meetings    = @()
    $headerOnly  = 0
    $emptyContent = 0
    foreach ($a in $appts) {
        $body = ''
        try { $body = [string]$a.Body } catch {}
        if ($body -and $body.Length -gt $BodyMaxChars) {
            $body = $body.Substring(0, $BodyMaxChars) + ' ...[truncated]'
        }
        $organizer = ''; try { $organizer = [string]$a.Organizer } catch {}
        $req = '';       try { $req = [string]$a.RequiredAttendees } catch {}
        $opt = '';       try { $opt = [string]$a.OptionalAttendees } catch {}

        # 1 = olHeaderOnly: body/organizer/attendees on the server but not synced locally.
        $ds = $null
        try { $ds = [int]$a.DownloadState } catch {}
        if ($ds -eq 1) { $headerOnly++ }
        if ([string]::IsNullOrEmpty($organizer) -and [string]::IsNullOrEmpty($req) -and [string]::IsNullOrEmpty($body)) { $emptyContent++ }

        $meetings += [ordered]@{
            subject           = [string]$a.Subject
            start             = (Get-Date $a.Start).ToString('yyyy-MM-ddTHH:mm')
            end               = (Get-Date $a.End).ToString('yyyy-MM-ddTHH:mm')
            location          = [string]$a.Location
            organizer         = $organizer
            requiredAttendees = $req
            optionalAttendees = $opt
            isAllDay          = [bool]$a.AllDayEvent
            downloadState     = $ds
            body              = $body
        }
    }

    # Sort by start time (Restrict on a recurrence-expanded collection isn't guaranteed sorted).
    $meetings = @($meetings | Sort-Object { $_.start })

    $holidayHints = @(
        $meetings | Where-Object { $_.isAllDay -and $_.subject -match $HolidayRe } |
            ForEach-Object { $_.subject }
    )

    # Warn if content is header-only (explicit DownloadState) or, as a fallback heuristic, if
    # every meeting came back with no organizer/attendees/body (the same cached-mode symptom).
    $warning = ''
    if ($headerOnly -gt 0 -or ($meetings.Count -gt 0 -and $emptyContent -eq $meetings.Count)) {
        $n = if ($headerOnly -gt 0) { $headerOnly } else { $emptyContent }
        $warning = "$n of $($meetings.Count) meetings returned no body/organizer/attendees -- Cached Exchange Mode 'Download Headers Only' keeps that content on the server, unsynced, so COM reads it empty. This is NOT a script bug. Fix in Outlook: Send/Receive > Download Preferences > 'Download Full Items', uncheck 'On Slow Connections Download Only Headers', then press F9."
    }

    Write-JsonResult ([ordered]@{
        date               = $dayStart.ToString('yyyy-MM-dd')
        dayOfWeek          = $dayStart.DayOfWeek.ToString()
        isWeekend          = ($dayStart.DayOfWeek -eq [DayOfWeek]::Saturday -or $dayStart.DayOfWeek -eq [DayOfWeek]::Sunday)
        suggestedTargetDay = (Get-NextWeekday $dayStart).ToString('yyyy-MM-dd')
        holidayHints       = $holidayHints
        count              = $meetings.Count
        headerOnlyCount    = $headerOnly
        warning            = $warning
        meetings           = $meetings
    })
}
catch {
    Write-JsonResult ([ordered]@{
        date               = $Date.Date.ToString('yyyy-MM-dd')
        dayOfWeek          = $Date.Date.DayOfWeek.ToString()
        isWeekend          = ($Date.Date.DayOfWeek -eq [DayOfWeek]::Saturday -or $Date.Date.DayOfWeek -eq [DayOfWeek]::Sunday)
        suggestedTargetDay = (Get-NextWeekday $Date.Date).ToString('yyyy-MM-dd')
        holidayHints       = @()
        count              = 0
        headerOnlyCount    = 0
        warning            = ''
        meetings           = @()
        error              = $_.Exception.Message
    })
    exit 1
}
