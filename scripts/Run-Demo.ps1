param(
    [string]$Python = "D:\Anaconda3\envs\face_env\python.exe",
    [ValidateRange(1024, 65535)][int]$Port = 8000,
    [switch]$DisableAI
)
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "Build-Frontend.ps1")
& (Join-Path $PSScriptRoot "Initialize-Demo.ps1") -Python $Python
& (Join-Path $PSScriptRoot "Start-Backend.ps1") -Python $Python -Port $Port -DisableAI:$DisableAI
