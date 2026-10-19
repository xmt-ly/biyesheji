"""以隔离的子运行时验证整条测试命令不会继承真实业务目录或模型凭据。"""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('failure_target', ['', 'backend', 'experiments/reliability_followup/tests'])
def test_test_command_isolates_environment_and_restores_it(tmp_path, failure_target):
    root = Path(__file__).resolve().parents[2]
    for folder in ('scripts', 'backend', 'frontend'):
        (tmp_path / folder).mkdir()
    shutil.copyfile(root / 'scripts' / 'Test.ps1', tmp_path / 'scripts' / 'Test.ps1')
    (tmp_path / 'scripts' / 'Common.ps1').write_text('''
$script:TaskProjectRoot = Split-Path $PSScriptRoot -Parent
function Get-TaskPython { param([string]$Python) return (Join-Path $script:TaskProjectRoot 'fake.ps1') }
function Get-TaskNpm { return (Join-Path $script:TaskProjectRoot 'fake.ps1') }
''', encoding='utf-8')
    (tmp_path / 'fake.ps1').write_text('''
@{ data=$env:DATA_DIR; signing=$env:JWT_SECRET; api=$env:LLM_API_KEY; model=$env:LLM_MODEL;
   arguments=@($args); directory=(Get-Location).Path } |
  ConvertTo-Json -Compress | Add-Content -LiteralPath $env:TASK_RUNTIME_RECORD
if ($env:TASK_RUNTIME_FAIL -eq 'backend' -and (Split-Path (Get-Location).Path -Leaf) -eq 'backend') { exit 1 }
if ($env:TASK_RUNTIME_FAIL -ne '' -and $args -contains $env:TASK_RUNTIME_FAIL) { exit 1 }
exit 0
''', encoding='utf-8')
    original = {'DATA_DIR': 'SENTINEL_FORMAL_DIRECTORY_NOT_READ',
                'JWT_SECRET': 'sentinel-original-signing-not-a-real-key',
                'LLM_API_KEY': 'sentinel-provider-not-a-real-key', 'LLM_MODEL': 'sentinel-model'}
    record = tmp_path / 'calls.jsonl'
    env = dict(os.environ, **original, TASK_RUNTIME_RECORD=str(record), TASK_RUNTIME_FAIL=failure_target)
    task = str(tmp_path / 'scripts' / 'Test.ps1').replace("'", "''")
    command = "try { & '" + task + "' } catch { $taskCaught=$true }; " + '''
@{ data=$env:DATA_DIR; signing=$env:JWT_SECRET; api=$env:LLM_API_KEY; model=$env:LLM_MODEL;
   caught=[bool]$taskCaught } | ConvertTo-Json -Compress
'''
    result = subprocess.run([shutil.which('pwsh') or 'powershell', '-NoProfile', '-NonInteractive', '-Command', command],
                            env=env, stdin=subprocess.DEVNULL, text=True, encoding='utf-8', capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    restored = json.loads(result.stdout.strip().splitlines()[-1])
    observed = [json.loads(line) for line in record.read_text(encoding='utf-8-sig').splitlines()]
    assert observed
    if failure_target != 'backend':
        followup_calls = [call for call in observed if 'experiments/reliability_followup/tests' in call['arguments']]
        assert len(followup_calls) == 1, '整条测试命令必须包含一次 followup 离线测试'
        assert followup_calls[0]['arguments'] == [
            '-X', 'utf8', '-m', 'pytest', 'experiments/reliability_followup/tests', '-q', '--tb=short']
        assert Path(followup_calls[0]['directory']) == tmp_path
    for call in observed:
        assert call['data'] != original['DATA_DIR'], '测试命令继承了真实业务目录'
        assert Path(call['data']).is_relative_to(tmp_path / 'work'), '测试数据不在独立工作目录'
        assert call['api'] in ('', None) and call['model'] in ('', None), '测试命令继承了模型凭据'
        assert call['signing'] != original['JWT_SECRET'] and len(call['signing']) >= 32
    assert restored == dict(data=original['DATA_DIR'], signing=original['JWT_SECRET'],
                           api=original['LLM_API_KEY'], model=original['LLM_MODEL'], caught=bool(failure_target))
