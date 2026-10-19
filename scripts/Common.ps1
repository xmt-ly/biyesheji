$script:TaskProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

function Get-TaskPython {
    param([string]$Python = "D:\Anaconda3\envs\face_env\python.exe")
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "Python executable not found: $Python"
    }
    return $Python
}

function Get-TaskNpm {
    $taskNpm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($taskNpm) { return $taskNpm.Source }
    if (Test-Path -LiteralPath "D:\nodejs\npm.cmd") { return "D:\nodejs\npm.cmd" }
    throw "npm.cmd is unavailable. Install Node.js compatible with Vite."
}

function Import-TaskEnv {
    $taskEnvPath = Join-Path $script:TaskProjectRoot ".env"
    if (-not (Test-Path -LiteralPath $taskEnvPath -PathType Leaf)) { return }
    $taskAllowedKeys = @("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "JWT_SECRET", "DATA_DIR")
    foreach ($taskEnvLine in Get-Content -LiteralPath $taskEnvPath -Encoding UTF8) {
        if ($taskEnvLine.Trim() -eq "" -or $taskEnvLine.TrimStart().StartsWith("#")) { continue }
        if ($taskEnvLine -notmatch "^\s*([A-Z][A-Z0-9_]*)\s*=(.*)$") {
            throw "Invalid .env line. Use NAME=value; values are never executed."
        }
        $taskEnvName = $Matches[1]
        $taskEnvValue = $Matches[2].Trim()
        if ($taskAllowedKeys -notcontains $taskEnvName) { throw "Unsupported .env key: $taskEnvName" }
        if ($taskEnvValue.Length -ge 2) {
            if (($taskEnvValue.StartsWith('"') -and $taskEnvValue.EndsWith('"')) -or
                ($taskEnvValue.StartsWith("'") -and $taskEnvValue.EndsWith("'"))) {
                $taskEnvValue = $taskEnvValue.Substring(1, $taskEnvValue.Length - 2)
            }
        }
        [Environment]::SetEnvironmentVariable($taskEnvName, $taskEnvValue, "Process")
    }
}
