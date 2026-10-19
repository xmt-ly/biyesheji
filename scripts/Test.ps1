param([string]$Python = "D:\Anaconda3\envs\face_env\python.exe")
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
$taskPython = Get-TaskPython -Python $Python
$taskNpm = Get-TaskNpm
$taskEnvironment = @{}
foreach ($taskName in @('DATA_DIR', 'JWT_SECRET', 'LLM_API_KEY', 'LLM_MODEL')) {
    $taskEnvironment[$taskName] = [Environment]::GetEnvironmentVariable($taskName, 'Process')
}
$taskStamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$taskTestData = Join-Path $script:TaskProjectRoot "work\test-runs\$taskStamp"
New-Item -ItemType Directory -Path $taskTestData -Force | Out-Null
$env:DATA_DIR = $taskTestData
$env:JWT_SECRET = 'isolated-test-signing-secret-long-enough-2026'
$env:LLM_API_KEY = ''
$env:LLM_MODEL = ''
try {
Push-Location (Join-Path $script:TaskProjectRoot "backend")
try {
    & $taskPython -X utf8 -m pytest -q --tb=short
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed." }
} finally { Pop-Location }
Push-Location $script:TaskProjectRoot
try {
    & $taskPython -X utf8 -m pytest scripts/tests -q --tb=short
    if ($LASTEXITCODE -ne 0) { throw "Backup tests failed." }
    & $taskPython -X utf8 -m pytest experiments/tests -q --tb=short
    if ($LASTEXITCODE -ne 0) { throw "Offline evaluation tests failed." }
    & $taskPython -X utf8 -m pytest experiments/reliability_v3/tests -q --tb=short
    if ($LASTEXITCODE -ne 0) { throw "Reliability evaluation tests failed." }
    & $taskPython -X utf8 -m pytest experiments/reliability_followup/tests -q --tb=short
    if ($LASTEXITCODE -ne 0) { throw "Followup evaluation tests failed." }
} finally { Pop-Location }
Push-Location (Join-Path $script:TaskProjectRoot "frontend")
try {
    & $taskNpm test
    if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed." }
    & $taskNpm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
} finally { Pop-Location }
} finally {
    foreach ($taskName in $taskEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($taskName, $taskEnvironment[$taskName], 'Process')
    }
}
