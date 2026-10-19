"""无模型 Linux HTTP 复验；服务与客户端在同一网络命名空间运行。"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.environ.get('LLM_API_KEY') or os.environ.get('LLM_MODEL'):
        raise SystemExit('复验要求显式关闭模型')
    if not os.environ.get('DATA_DIR'):
        raise SystemExit('请指定独立演示 DATA_DIR')
    checks = []
    with (ROOT / 'work/cloud-http-server.log').open('w') as log:
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend',
                                   '--host', '127.0.0.1', '--port', '8000'], cwd=ROOT, stdout=log, stderr=log)
        try:
            with httpx.Client(base_url='http://127.0.0.1:8000', trust_env=False, timeout=10) as client:
                for _ in range(100):
                    try:
                        if client.get('/api/health').status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    if server.poll() is not None:
                        raise RuntimeError('服务提前退出')
                    time.sleep(.1)
                else:
                    raise RuntimeError('服务未就绪')

                def req(method, path, expected=200, who=None, body=None):
                    headers = {'Authorization': 'Bearer ' + tokens[who]} if who else {}
                    response = client.request(method, path, headers=headers, json=body)
                    assert response.status_code == expected, (method, path, response.status_code)
                    checks.append({'method': method, 'path': path, 'role': who, 'status': response.status_code})
                    return response

                tokens = {}
                homepage = req('GET', '/')
                for asset in re.findall(r'(?:src|href)="(/assets/[^"]+)"', homepage.text):
                    req('GET', asset)
                req('GET', '/api/projects', 401)
                req('POST', '/api/auth/login', 401, body={'username': 'leader', 'password': 'wrong'})
                users = {}
                for name in ('teacher', 'leader', 'member1', 'leader2', 'member3'):
                    login = req('POST', '/api/auth/login', body={'username': name, 'password': 'Demo2026!'}).json()
                    tokens[name] = login['access_token']
                    users[name] = login['user']
                assert req('GET', '/api/config/status', who='leader').json()['ai_ready'] is False
                project = req('GET', '/api/projects', who='leader').json()[0]
                pid = project['id']
                for suffix in ('/messages', '/cards', '/agent/runs'):
                    req('GET', f'/api/projects/{pid}{suffix}', 403, who='teacher')
                for who in ('leader2', 'member3'):
                    req('GET', f'/api/projects/{pid}', 403, who=who)
                task = next(t for t in req('GET', f'/api/projects/{pid}/tasks', who='member1').json()
                            if t['assignee_id'] == users['member1']['id'])
                req('PATCH', f'/api/tasks/{task["id"]}', who='member1', body={'status': 'doing', 'progress': 25, 'remaining_hours': 4})
                req('POST', f'/api/projects/{pid}/submissions', 403, who='member1',
                    body={'stage_index': 0, 'summary': '权限验证', 'artifact_urls': ['https://example.com/cloud-demo']})
                for stage in range(3):
                    payload = {'stage_index': stage, 'summary': '【云端无模型 HTTP 演示】阶段验证',
                               'artifact_urls': ['https://example.com/cloud-demo']}
                    first = req('POST', f'/api/projects/{pid}/submissions', who='leader', body=payload).json()
                    req('POST', f'/api/submissions/{first["id"]}/review', 403, who='leader',
                        body={'result': 'passed', 'comment': '权限验证'})
                    req('POST', f'/api/submissions/{first["id"]}/review', who='teacher',
                        body={'result': 'needs_changes', 'comment': '【演示】补充验证材料'})
                    second = req('POST', f'/api/projects/{pid}/submissions', who='leader', body=payload).json()
                    assert second['version'] == first['version'] + 1
                    req('POST', f'/api/submissions/{second["id"]}/review', who='teacher',
                        body={'result': 'passed', 'comment': '【演示】复提交通过'})
                history = req('GET', f'/api/projects/{pid}/submissions', who='teacher').json()
                for stage in range(3):
                    versions = [s for s in history if s['stage_index'] == stage]
                    assert any(s['status'] == 'needs_changes' and s['reviews'] for s in versions)
                    assert any(s['status'] == 'passed' for s in versions)
            result = {'status': 'passed', 'checks': checks, 'browser_acceptance': False,
                      'model_calls': 0, 'note': '仅 HTTP；链接为明确标注的演示占位材料'}
            (ROOT / 'work/cloud-http-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'HTTP 验证通过：{len(checks)} 项；模型调用 0；浏览器验收未执行。')
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == '__main__':
    (ROOT / 'work').mkdir(exist_ok=True)
    main()
