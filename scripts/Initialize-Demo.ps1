param([string]$Python = "D:\Anaconda3\envs\face_env\python.exe")
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
$taskPython = Get-TaskPython -Python $Python
Import-TaskEnv
Push-Location (Join-Path $script:TaskProjectRoot "backend")
try {
    & $taskPython -X utf8 -m app.seed
    if ($LASTEXITCODE -ne 0) { throw "Demo initialization failed." }
} finally { Pop-Location }
