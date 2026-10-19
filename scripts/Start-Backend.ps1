param(
    [string]$Python = "D:\Anaconda3\envs\face_env\python.exe",
    [ValidateRange(1024, 65535)][int]$Port = 8000,
    [switch]$Reload,
    [switch]$DisableAI,
    [switch]$DirectModelConnection
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
$taskPython = Get-TaskPython -Python $Python
Import-TaskEnv
if ($DirectModelConnection) {
    $taskModelAddress = if ($env:LLM_BASE_URL) { $env:LLM_BASE_URL } else { 'https://api.openai.com/v1' }
    $taskModelUri = $null
    if (-not [Uri]::TryCreate($taskModelAddress, [UriKind]::Absolute, [ref]$taskModelUri) -or -not $taskModelUri.Host) {
        throw 'Model base URL must be an absolute URL when using DirectModelConnection'
    }
    $taskNoProxyHosts = @($env:NO_PROXY -split ',' | Where-Object { $_.Trim() })
    if ($taskNoProxyHosts -notcontains $taskModelUri.Host) { $taskNoProxyHosts += $taskModelUri.Host }
    $env:NO_PROXY = $taskNoProxyHosts -join ','
}
if ($DisableAI) {
    $env:LLM_API_KEY = ""
    $env:LLM_MODEL = ""
}
$taskArguments = @("-X", "utf8", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
    "--port", "$Port", "--workers", "1", "--no-access-log")
if ($Reload) { $taskArguments += "--reload" }
Push-Location (Join-Path $script:TaskProjectRoot "backend")
try {
    & $taskPython @taskArguments
    if ($LASTEXITCODE -ne 0) { throw "Backend exited with code $LASTEXITCODE" }
} finally { Pop-Location }
