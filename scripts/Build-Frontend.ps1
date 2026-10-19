$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
$taskNpm = Get-TaskNpm
$taskFrontend = [System.IO.Path]::GetFullPath((Join-Path $script:TaskProjectRoot "frontend"))
if (-not $taskFrontend.StartsWith($script:TaskProjectRoot + [System.IO.Path]::DirectorySeparatorChar)) {
    throw "Frontend path is outside the project."
}
Push-Location $taskFrontend
try {
    if (-not (Test-Path -LiteralPath "node_modules")) {
        & $taskNpm ci --cache (Join-Path $script:TaskProjectRoot "work\.npm-cache") --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
    }
    & $taskNpm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
} finally { Pop-Location }
