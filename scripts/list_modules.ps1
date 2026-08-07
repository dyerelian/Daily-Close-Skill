[CmdletBinding()]
param(
    [string] $Config,
    [string] $Profile,
    [string] $ConfigRoot,
    [switch] $Json
)

$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'list_modules.py'
$argsList = @($script)
if ($Config) { $argsList += @('--config', $Config) }
if ($Profile) { $argsList += @('--profile', $Profile) }
if ($ConfigRoot) { $argsList += @('--config-root', $ConfigRoot) }
if ($Json) { $argsList += '--json' }
python @argsList
exit $LASTEXITCODE
