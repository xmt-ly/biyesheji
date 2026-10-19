"""只在临时目录运行真实业务 API；不读取项目 data/.env，不请求外网。"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys

import pytest


SOURCE_ROOT = Path(os.environ.get('DEFENSE_DEMO_SOURCE_ROOT', Path(__file__).resolve().parents[2]))
SCRIPTS = Path(__file__).resolve().parents[1]


def tool():
    path = SCRIPTS / 'seed_defense_demo.py'
    assert path.is_file(), '独立答辩演示初始化工具尚未实现'
    spec = importlib.util.spec_from_file_location('seed_defense_demo', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def demo(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    root.mkdir()
    monkeypatch.setenv('LLM_API_KEY', 'NEVER-INHERIT-MODEL-SECRET')
    monkeypatch.setenv('LLM_MODEL', 'NEVER-INHERIT-MODEL')
    monkeypatch.setenv('LLM_BASE_URL', 'https://never-call.invalid/v1')
    monkeypatch.setenv('JWT_SECRET', 'NEVER-INHERIT-JWT-SECRET-' * 3)
    monkeypatch.setenv('DATA_DIR', str(root / 'data'))

    original_connect = socket.socket.connect

    def forbidden_network(sock, address):
        # Windows asyncio socketpair 的内部自唤醒需用回环；外网仍一律拒绝。
        if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1'):
            return original_connect(sock, address)
        pytest.fail('初始化演示库不允许发起外部网络连接')

    monkeypatch.setattr(socket.socket, 'connect', forbidden_network)
    import httpx

    def forbidden_http(*args, **kwargs):
        pytest.fail('仅允许 ASGI TestClient，不允许实际 HTTP 请求')

    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', forbidden_http)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', forbidden_http)
    module = tool()
    destination = root / 'work' / 'defense-demo' / 'test-run'
    manifest = module.initialize_demo(root, destination, '2026-10-18', backend_root=SOURCE_ROOT / 'backend')
    assert not (root / 'data').exists()
    return module, root, destination, manifest


def test_real_api_history_privacy_materials_and_member_update(demo):
    module, root, destination, manifest = demo
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    assert manifest['reference_date'] == '2026-10-18'
    assert manifest['external_model_calls'] == 0
    assert manifest['counts'] == {'accounts': 6, 'teams': 2, 'requirements': 2, 'tasks': 2,
                                  'plans': 2, 'cards': 2, 'submissions': 5, 'materials': 5}
    assert all(check['passed'] for check in manifest['checks'])
    assert (destination / 'manifest.json').is_file()
    assert (destination / '演示说明.md').is_file()
    pid = manifest['project_id']
    app = create_app(Settings(data_dir=destination, jwt_secret=(destination / 'jwt.key').read_text(),
                              llm_api_key='', llm_model='', llm_base_url='http://127.0.0.1:9/v1'))
    with TestClient(app) as client:
        tokens = {}
        for actor in ('teacher', 'leader', 'member1', 'member2', 'leader2'):
            login = client.post('/api/auth/login', json={'username': actor, 'password': 'Demo2026!'})
            assert login.status_code == 200
            tokens[actor] = login.json()['access_token']

        def call(actor, method, path, payload=None, status=200):
            response = client.request(method, '/api' + path, json=payload,
                                      headers={'Authorization': 'Bearer ' + tokens[actor]})
            assert response.status_code == status, response.text
            return response

        assert len(call('teacher', 'GET', '/projects').json()) == 2
        for suffix in ('messages', 'cards', 'files', 'agent/runs'):
            call('teacher', 'GET', f'/projects/{pid}/{suffix}', status=403)
        call('leader2', 'GET', f'/projects/{pid}/messages', status=403)
        plans = call('teacher', 'GET', f'/projects/{pid}/plans').json()
        assert [p['version'] for p in plans] == [1, 2]
        assert plans[0]['tasks'][0]['progress'] == 0
        assert plans[1]['tasks'][0]['progress'] == 25
        assert plans[1]['tasks'][0]['due_date'] > plans[0]['tasks'][0]['due_date']
        assert plans[1]['tasks'][1]['start_date'] > plans[1]['tasks'][0]['due_date']
        assert '【人工备用草案】' not in json.dumps(plans, ensure_ascii=False)
        cards = call('leader', 'GET', f'/projects/{pid}/cards').json()
        assert len(cards) == 2
        assert all('【人工备用草案】' in c['title'] and c['feedback'] for c in cards)
        assert all(c.get('agent_run_id') is None for c in cards)
        assert len(call('leader', 'GET', f'/projects/{pid}/messages').json()) >= 5
        subs = call('teacher', 'GET', f'/projects/{pid}/submissions').json()
        assert [(s['stage_index'], s['version'], s['status']) for s in subs] == [
            (0, 1, 'needs_changes'), (0, 2, 'passed'), (1, 1, 'passed'),
            (2, 1, 'needs_changes'), (2, 2, 'passed')]
        assert [s['plan_version'] for s in subs] == [1, 1, 2, 2, 2]
        assert [s['progress_snapshot']['completion_percent'] for s in subs] == [0, 0, 50, 100, 100]
        for sub in subs:
            assert len(sub['reviews']) == 1 and '【答辩演示】' in sub['reviews'][0]['comment']
            assert sub['materials'] and len(sub['file_ids']) == 1
        for material in manifest['materials']:
            content = call('teacher', 'GET', f'/files/{material["id"]}').content
            assert hashlib.sha256(content).hexdigest() == material['sha256']
            assert '仅用于答辩演示' in content.decode('utf-8')
        tasks = call('leader', 'GET', f'/projects/{pid}/tasks').json()
        call('member1', 'PATCH', f'/tasks/{tasks[0]["id"]}', {'progress': 10}, status=409)
        call('member1', 'PATCH', f'/tasks/{tasks[1]["id"]}', {'blocker': '越权'}, status=403)
        comments = call('member1', 'GET', f'/tasks/{tasks[0]["id"]}/comments').json()
        assert any('25%' in c['content'] for c in comments)
        assert call('teacher', 'GET', f'/projects/{pid}/progress').json()['completion_percent'] == 100
    with sqlite3.connect(destination / 'collaboration.db') as db:
        assert db.execute('SELECT count(*) FROM agent_runs').fetchone()[0] == 0
    report_text = (destination / 'manifest.json').read_text(encoding='utf-8')
    assert 'NEVER-INHERIT' not in report_text
    assert 'access_token' not in report_text and 'jwt_secret' not in report_text
    assert os.environ['DATA_DIR'] == str(destination)
    assert os.environ['LLM_API_KEY'] == os.environ['LLM_MODEL'] == ''


def test_repeat_initialization_refused_without_changing_database(demo):
    module, root, destination, _ = demo
    before = {p.name: digest(p) for p in destination.iterdir() if p.is_file()}
    with pytest.raises(FileExistsError):
        module.initialize_demo(root, destination, '2026-10-18', backend_root=SOURCE_ROOT / 'backend')
    assert {p.name: digest(p) for p in destination.iterdir() if p.is_file()} == before


@pytest.mark.parametrize('target', ['data', 'work/outside', 'work/defense-demo/../escaped', 'work/defense-demo'])
def test_unsafe_paths_refused_before_import_or_read(tmp_path, monkeypatch, target):
    module = tool()
    root = tmp_path / 'root'
    root.mkdir()
    original = root / 'data'
    original.mkdir()
    original.joinpath('collaboration.db').write_bytes(b'DO-NOT-READ')
    def forbidden(*args, **kwargs):
        pytest.fail('非法路径不得导入业务 app 或读取原始 data')
    monkeypatch.setattr(module, '_load_backend', forbidden)
    with pytest.raises(ValueError):
        module.initialize_demo(root, root / target, '2026-10-18')
    assert original.joinpath('collaboration.db').read_bytes() == b'DO-NOT-READ'


def test_existing_database_refused_before_backend_import(tmp_path, monkeypatch):
    module = tool()
    root = tmp_path / 'root'
    destination = root / 'work' / 'defense-demo' / 'existing'
    destination.mkdir(parents=True)
    database = destination / 'collaboration.db'
    database.write_bytes(b'KEEP-EXACTLY')
    monkeypatch.setattr(module, '_load_backend', lambda *args: pytest.fail('必须先拒绝已有库'))
    with pytest.raises(FileExistsError):
        module.initialize_demo(root, destination, '2026-10-18')
    assert database.read_bytes() == b'KEEP-EXACTLY'


def test_link_target_refused(tmp_path):
    module = tool()
    root = tmp_path / 'root'
    destination = root / 'work' / 'defense-demo'
    destination.mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = destination / 'linked'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        # Windows 普通权限可创建 junction，同样必须拒绝。
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
        assert result.returncode == 0, '测试环境无法创建链接边界用例'
    with pytest.raises(ValueError):
        module.initialize_demo(root, link / 'new-run', '2026-10-18')
    assert list(outside.iterdir()) == []


def run_launcher(tmp_path, *, enable_ai=False, direct=False, target='work/defense-demo/initialized',
                 database_bytes=None, attachments_mode=None, uninitialized=False):
    source = SCRIPTS / 'Start-DefenseDemo.ps1'
    assert source.is_file(), '独立演示启动脚本尚未实现'
    root = tmp_path / 'launcher'
    (root / 'scripts').mkdir(parents=True)
    (root / 'backend' / 'app').mkdir(parents=True)
    shutil.copyfile(source, root / 'scripts' / source.name)
    shutil.copyfile(SCRIPTS / 'seed_defense_demo.py', root / 'scripts' / 'seed_defense_demo.py')
    shutil.copyfile(SOURCE_ROOT / 'backend' / 'app' / 'models.py', root / 'backend' / 'app' / 'models.py')
    destination = root / 'work' / 'defense-demo' / 'initialized'
    tool().initialize_demo(root, destination, '2026-10-18', backend_root=SOURCE_ROOT / 'backend')
    if uninitialized:
        (destination / 'collaboration.db').unlink()
        with sqlite3.connect(destination / 'collaboration.db') as db:
            db.execute('CREATE TABLE sentinel (n INTEGER)')
        db.close()
    if database_bytes is not None:
        (destination / 'collaboration.db').write_bytes(database_bytes)
    if attachments_mode:
        outside = tmp_path / 'outside'
        outside.mkdir()
        (outside / 'marker.txt').write_bytes(b'OUTSIDE-DO-NOT-TOUCH')
        link = destination / 'files' / 'redirect'
        if attachments_mode == 'files_junction':
            # 已有真实附件移入同一演示目录，留下空位设置恶意 junction。
            (destination / 'files').rename(destination / 'original-files')
            link = destination / 'files'
        if attachments_mode == 'file_hardlink':
            os.link(outside / 'marker.txt', link)
        else:
            made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
            assert made.returncode == 0, '无法创建 junction 边界用例'
    # 仅 fake 项目的配置；不能让测试访问真实项目 .env。
    (root / '.env').write_text('LLM_API_KEY=fake-model-key\nLLM_MODEL=fake-model\nLLM_BASE_URL=https://model.invalid/v1\nDATA_DIR=C:\\unsafe\\production\nJWT_SECRET=do-not-inherit\n', encoding='utf-8')
    capture = root / 'capture.json'
    shim = root / 'python-shim.ps1'
    shim.write_text("if ($args -contains '--validate-existing') { & '" + str(Path(sys.executable)).replace("'", "''") + "' @args; $global:LASTEXITCODE=$LASTEXITCODE; return }\n"
                    "@{ args=@($args); data=$env:DATA_DIR; key=$env:LLM_API_KEY; model=$env:LLM_MODEL; jwt=$env:JWT_SECRET; no_proxy=$env:NO_PROXY } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath '" + str(capture).replace("'", "''") + "' -Encoding UTF8\n$global:LASTEXITCODE=0\n", encoding='utf-8')
    command = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(root / 'scripts' / source.name),
               '-Python', str(shim), '-DataDir', str(root / target)]
    if enable_ai:
        command.append('-EnableAI')
    if direct:
        command.append('-DirectModelConnection')
    env = dict(os.environ, LLM_API_KEY='inherited-secret', LLM_MODEL='inherited-model',
               JWT_SECRET='inherited-jwt', NO_PROXY='localhost')
    before_database = digest(destination / 'collaboration.db')
    before_names = sorted(path.name for path in destination.iterdir())
    result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    assert digest(destination / 'collaboration.db') == before_database, '启动前校验不得改库'
    assert sorted(path.name for path in destination.iterdir()) == before_names, '校验不得创建 journal/临时文件'
    if attachments_mode:
        assert (outside / 'marker.txt').read_bytes() == b'OUTSIDE-DO-NOT-TOUCH'
        assert sorted(path.name for path in outside.iterdir()) == ['marker.txt']
    payload = json.loads(capture.read_text(encoding='utf-8-sig')) if capture.exists() else None
    return result, payload, destination


def test_launcher_defaults_to_8001_ai_disabled_and_isolated_data(tmp_path):
    result, payload, destination = run_launcher(tmp_path)
    assert result.returncode == 0, result.stderr
    assert payload['args'][payload['args'].index('--port') + 1] == '8001'
    assert payload['data'] == str(destination)
    assert not payload['key'] and not payload['model'] and not payload['jwt']


def test_launcher_opt_in_ai_still_overrides_env_data_and_appends_no_proxy(tmp_path):
    result, payload, destination = run_launcher(tmp_path, enable_ai=True, direct=True)
    assert result.returncode == 0, result.stderr
    assert payload['data'] == str(destination)
    assert payload['key'] == 'fake-model-key' and payload['model'] == 'fake-model'
    assert not payload['jwt']
    assert set(payload['no_proxy'].split(',')) == {'localhost', 'model.invalid'}


def test_launcher_refuses_non_demo_data_before_running_python(tmp_path):
    result, payload, _ = run_launcher(tmp_path, target='data')
    assert result.returncode != 0 and payload is None


def test_launcher_refuses_empty_database_even_with_manifest(tmp_path):
    result, payload, _ = run_launcher(tmp_path, database_bytes=b'')
    assert result.returncode != 0 and payload is None


@pytest.mark.parametrize('attachments_mode', ['files_junction', 'nested_junction', 'file_hardlink'])
def test_launcher_refuses_attachment_redirect_before_service(tmp_path, attachments_mode):
    result, payload, _ = run_launcher(tmp_path, attachments_mode=attachments_mode)
    assert result.returncode != 0 and payload is None


def test_launcher_refuses_sqlite_magic_without_database(tmp_path):
    result, payload, _ = run_launcher(tmp_path, database_bytes=b'SQLite format 3\x00')
    assert result.returncode != 0 and payload is None


def test_launcher_refuses_valid_sqlite_without_business_schema(tmp_path):
    result, payload, _ = run_launcher(tmp_path, uninitialized=True)
    assert result.returncode != 0 and payload is None


def test_existing_validation_is_read_only_without_app_or_key_access(demo, monkeypatch):
    module, root, destination, _ = demo
    models = root / 'backend' / 'app' / 'models.py'
    models.parent.mkdir(parents=True)
    shutil.copyfile(SOURCE_ROOT / 'backend' / 'app' / 'models.py', models)
    before = digest(destination / 'collaboration.db')
    before_names = sorted(path.name for path in destination.iterdir())
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path.name not in ('jwt.key', '.env'), '只读启动验证不能读取凭据'
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', guarded_open)
    monkeypatch.setattr(module, '_load_backend', lambda *args: pytest.fail('只读验证不能导入 app 或初始化库'))
    checked = module.validate_existing_demo(root, destination)
    assert checked['read_only'] and checked['validated_tables'] >= 15
    assert digest(destination / 'collaboration.db') == before
    assert sorted(path.name for path in destination.iterdir()) == before_names
