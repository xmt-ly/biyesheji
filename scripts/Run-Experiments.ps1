param(
    [string]$Python = 'D:\Anaconda3\envs\face_env\python.exe',
    [switch]$Live,
    [switch]$DirectModelConnection,
    [ValidateSet('reliability', 'legacy')][string]$Protocol = 'reliability',
    [ValidateSet('dev', 'eval')][string]$Split = 'eval',
    [ValidateRange(1, 10)][int]$Repetitions = 2,
    [ValidateRange(1, 180)][int]$MaxCalls = 180,
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Common.ps1')
$taskPython = Get-TaskPython -Python $Python
$taskModule = if ($Protocol -eq 'reliability') { 'experiments.reliability_v3.runner' } else { 'experiments.runner' }
$taskResultsRoot = if ($Protocol -eq 'reliability') { 'experiments\reliability_v3\results' } else { 'experiments\results' }
if (-not $OutputDirectory) {
    $taskStamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
    $taskMode = if ($Live) { 'live' } else { 'dry-run' }
    $OutputDirectory = Join-Path $script:TaskProjectRoot "$taskResultsRoot\$Split-$taskMode-$taskStamp"
}
if ($Live) {
    Import-TaskEnv
    if ($DirectModelConnection -and $env:LLM_BASE_URL) {
        $taskModelHost = ([uri]$env:LLM_BASE_URL).Host
        $env:NO_PROXY = (@(($env:NO_PROXY -split ',') | Where-Object { $_ }) + $taskModelHost | Select-Object -Unique) -join ','
    }
}
$taskArguments = @('-X', 'utf8', '-m', $taskModule, '--split', $Split,
    '--repetitions', $Repetitions, '--max-calls', $MaxCalls, '--output-dir', $OutputDirectory)
$taskArguments += if ($Live) { '--live' } else { '--dry-run' }
Push-Location $script:TaskProjectRoot
try {
    & $taskPython @taskArguments
    if ($LASTEXITCODE -ne 0) { throw 'Experiment incomplete. Inspect the saved manifest and records; no retry is automatic.' }
} finally { Pop-Location }
