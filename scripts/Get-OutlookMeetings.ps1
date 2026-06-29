<#
.SYNOPSIS
  Read a single day's appointments from the local Outlook calendar and emit them as JSON.

.DESCRIPTION
  Used by the `close-day` skill to gather tomorrow's meetings so it can draft an agenda for
  each. Talks to a locally-installed Outlook through its COM automation interface using
  LATE-BOUND IDispatch (`New-Object -ComObject Outlook.Application`). Do NOT switch this to
  Python win32com / EnsureDispatch — the gencache/typelib path is broken on this machine.

  Calendar reads only. The script never sends, moves, or modifies any Outlook item.

.PARAMETER Date
  The day to read (any parseable date). Defaults to tomorrow.

.PARAMETER OutFile
  Optional path to also write the JSON to (UTF-8, no BOM). JSON is always written to stdout.

.PARAMETER BodyMaxChars
  Truncate each appointment body to this many characters (default 2000) to keep output sane.

.OUTPUTS
  JSON object: { date, dayOfWeek, isWeekend, suggestedTargetDay, holidayHints, count,
  meetings: [ { subject, start, end, location, organizer, requiredAttendees,
  optionalAttendees, isAllDay, body } ] }
  `suggestedTargetDay` is the next weekday on/after `date` (handy when `date` is a weekend).
  `holidayHints` lists all-day event subjects on `date` that look like holidays / time off, so
  the caller can prompt for which day to actually prep.

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

    $ol  = New-Object -ComObject Outlook.Application
    $ns  = $ol.GetNamespace('MAPI')
    $cal = $ns.GetDefaultFolder(9)   # olFolderCalendar

    $items = $cal.Items
    $items.IncludeRecurrences = $true
    $items.Sort('[Start]')

    # Outlook Restrict requires US-style "MM/dd/yyyy hh:mm tt" literals regardless of locale.
    $fmt    = 'MM/dd/yyyy hh:mm tt'
    $filter = "[Start] >= '" + $dayStart.ToString($fmt) + "' AND [Start] < '" + $dayEnd.ToString($fmt) + "'"
    $appts  = $items.Restrict($filter)

    $meetings = @()
    foreach ($a in $appts) {
        $body = [string]$a.Body
        if ($body -and $body.Length -gt $BodyMaxChars) {
            $body = $body.Substring(0, $BodyMaxChars) + ' …[truncated]'
        }
        $meetings += [ordered]@{
            subject           = [string]$a.Subject
            start             = (Get-Date $a.Start).ToString('yyyy-MM-ddTHH:mm')
            end               = (Get-Date $a.End).ToString('yyyy-MM-ddTHH:mm')
            location          = [string]$a.Location
            organizer         = [string]$a.Organizer
            requiredAttendees = [string]$a.RequiredAttendees
            optionalAttendees = [string]$a.OptionalAttendees
            isAllDay          = [bool]$a.AllDayEvent
            body              = $body
        }
    }

    # Sort by start time (Restrict on a recurrence-expanded collection isn't guaranteed sorted).
    $meetings = @($meetings | Sort-Object { $_.start })

    $holidayHints = @(
        $meetings | Where-Object { $_.isAllDay -and $_.subject -match $HolidayRe } |
            ForEach-Object { $_.subject }
    )

    Write-JsonResult ([ordered]@{
        date               = $dayStart.ToString('yyyy-MM-dd')
        dayOfWeek          = $dayStart.DayOfWeek.ToString()
        isWeekend          = ($dayStart.DayOfWeek -eq [DayOfWeek]::Saturday -or $dayStart.DayOfWeek -eq [DayOfWeek]::Sunday)
        suggestedTargetDay = (Get-NextWeekday $dayStart).ToString('yyyy-MM-dd')
        holidayHints       = $holidayHints
        count              = $meetings.Count
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
        meetings           = @()
        error              = $_.Exception.Message
    })
    exit 1
}
