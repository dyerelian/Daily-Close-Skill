[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Args
)

$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'onboard_close_day.py'
python $script @Args
exit $LASTEXITCODE
