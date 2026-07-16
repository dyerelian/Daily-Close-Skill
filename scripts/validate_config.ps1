[CmdletBinding()]
param(
    [string] $Config = 'config/daily-close.example.json',
    [switch] $StrictPaths,
    [switch] $Json
)

$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'validate_config.py'
$argsList = @($script, '--config', $Config)
if ($StrictPaths) { $argsList += '--strict-paths' }
if ($Json) { $argsList += '--json' }
python @argsList
exit $LASTEXITCODE
