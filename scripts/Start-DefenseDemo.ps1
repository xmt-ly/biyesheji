param(
    [Parameter(Mandatory = $true)][string]$DataDir,
    [string]$Python = 'D:\Anaconda3\envs\face_env\python.exe',
    [ValidateRange(1024, 65535)][int]$Port = 8001,
    [switch]$EnableAI,
    [switch]$DirectModelConnection
)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskAllowed = [IO.Path]::GetFullPath((Join-Path $taskRoot 'work\defense-demo')).TrimEnd('\', '/')
$taskData = [IO.Path]::GetFullPath($DataDir).TrimEnd('\', '/')
if (-not $taskData.StartsWith($taskAllowed + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'DataDir must be an initialized child of project work/defense-demo.'
}
# 先验路径及全部祖先，禁止 junction/symlink 后再读取库和 manifest。
$taskCursor = $taskData
while ($taskCursor) {
    if (Test-Path -LiteralPath $taskCursor) {
        $taskItem = Get-Item -LiteralPath $taskCursor -Force
        if ($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point paths are not allowed.' }
    }
    $taskCursor = [IO.Path]::GetDirectoryName($taskCursor)
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Python executable was not found.' }
# 默认不读取 .env，清除继承配置；只有显式 EnableAI 时载入模型配置。
$env:LLM_API_KEY = ''
$env:LLM_MODEL = ''
$env:LLM_BASE_URL = 'http://127.0.0.1:9/v1'
$env:JWT_SECRET = ''
$env:DATA_DIR = $taskData
$env:PYTHONDONTWRITEBYTECODE = '1'
# 独立解释器只运行 stdlib 校验，不导入 app；先验全部附件链接，再只读检查 SQLite。
$taskValidationArgs = @('-I', '-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'seed_defense_demo.py'),
                        '--validate-existing', '--data-dir', $taskData)
& $Python @taskValidationArgs
if ($LASTEXITCODE -ne 0) { throw 'Demo validation refused startup; no service was started.' }
if ($EnableAI) {
    $env:LLM_BASE_URL = 'https://api.openai.com/v1'
    $taskEnvFile = Join-Path $taskRoot '.env'
    if (Test-Path -LiteralPath $taskEnvFile -PathType Leaf) {
        foreach ($taskLine in Get-Content -LiteralPath $taskEnvFile -Encoding UTF8) {
            if ($taskLine -match '^\s*(LLM_API_KEY|LLM_MODEL|LLM_BASE_URL)\s*=(.*)$') {
                $taskKey = $Matches[1]
                $taskValue = $Matches[2].Trim()
                if ($taskValue.Length -ge 2 -and (($taskValue.StartsWith('"') -and $taskValue.EndsWith('"')) -or
                    ($taskValue.StartsWith("'") -and $taskValue.EndsWith("'")))) {
                    $taskValue = $taskValue.Substring(1, $taskValue.Length - 2)
                }
                [Environment]::SetEnvironmentVariable($taskKey, $taskValue, 'Process')
            }
        }
    }
    if (-not $env:LLM_API_KEY -or -not $env:LLM_MODEL) { throw 'EnableAI requires LLM_API_KEY and LLM_MODEL in project .env.' }
}
# 必须在配置载入后覆盖：原 .env DATA_DIR/JWT_SECRET 不能切换到正式库。
$env:DATA_DIR = $taskData
$env:JWT_SECRET = ''
$env:PYTHONDONTWRITEBYTECODE = '1'
if ($DirectModelConnection) {
    if (-not $EnableAI) { throw 'DirectModelConnection requires EnableAI.' }
    $taskUri = $null
    if (-not [Uri]::TryCreate($env:LLM_BASE_URL, [UriKind]::Absolute, [ref]$taskUri) -or -not $taskUri.Host) {
        throw 'Model base URL must be an absolute URL.'
    }
    $taskNoProxyHosts = @($env:NO_PROXY -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if ($taskNoProxyHosts -notcontains $taskUri.Host) { $taskNoProxyHosts += $taskUri.Host }
    $env:NO_PROXY = $taskNoProxyHosts -join ','
}
$taskArgs = @('-X', 'utf8', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
              '--port', "$Port", '--workers', '1', '--no-access-log')
Write-Host "Defense demo: http://127.0.0.1:$Port ; AI enabled: $($EnableAI.IsPresent)"
Push-Location (Join-Path $taskRoot 'backend')
try {
    & $Python @taskArgs
    if ($LASTEXITCODE -ne 0) { throw "Demo backend exited with code $LASTEXITCODE" }
} finally { Pop-Location }
