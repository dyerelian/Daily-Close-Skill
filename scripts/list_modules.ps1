[CmdletBinding()]
param(
    [string] $Config,
    [switch] $Json
)

$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'list_modules.py'
$argsList = @($script)
if ($Config) { $argsList += @('--config', $Config) }
if ($Json) { $argsList += '--json' }
python @argsList
exit $LASTEXITCODE
