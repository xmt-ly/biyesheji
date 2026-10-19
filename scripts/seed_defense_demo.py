"""独立答辩演示库：人工备用草案和真实 API 操作，不调用模型、不读取 .env。"""
import argparse
import ast
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'Demo2026!'
LABEL = '【答辩演示】'
ACCOUNTS = [('teacher', '答辩演示教师', 'teacher'), ('leader', '一组组长', 'student'),
            ('member1', '一组成员甲', 'student'), ('member2', '一组成员乙', 'student'),
            ('leader2', '二组组长', 'student'), ('member3', '二组成员甲', 'student')]


def _no_links(path):
    """先检查词法路径全部祖先；禁止 resolve 先跟随 junction/symlink。"""
    for part in [*reversed(path.parents), path]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('演示目录及祖先不能是符号链接或 Windows reparse point')


def _demo_path(project_root, destination):
    root = Path(os.path.abspath(project_root))
    target = Path(os.path.abspath(destination))
    if '..' in Path(destination).parts:
        raise ValueError('演示目录不能包含 ..')
    _no_links(root)
    _no_links(target)
    allowed = root / 'work' / 'defense-demo'
    if target == allowed or not target.is_relative_to(allowed):
        raise ValueError('仅允许项目 work/defense-demo 下的全新子目录')
    return root, target


def validate_destination(project_root, destination):
    _, target = _demo_path(project_root, destination)
    if target.exists():
        raise FileExistsError('目标目录已存在；请换一个全新目录，工具不会重置或覆盖')
    return target


def _check_demo_tree(directory):
    """只用 lstat 决定是否遍历；不进入 junction，不读取链接目标内容。"""
    pending = [directory]
    while pending:
        current = pending.pop()
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('演示目录内不能有符号链接或 reparse point')
        if stat.S_ISDIR(info.st_mode):
            pending.extend(current.iterdir())
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('演示文件必须是独立普通文件，不能是硬链接或特殊文件')


def _required_schema(root):
    # 解析本项目模型源码，不导入 app/SQLAlchemy，不执行源码，也不触发建表。
    source = root / 'backend' / 'app' / 'models.py'
    _no_links(source)
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    result = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        table = None
        columns = set()
        for field in node.body:
            if isinstance(field, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__tablename__' for t in field.targets):
                table = ast.literal_eval(field.value)
            elif isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name):
                if isinstance(field.annotation, ast.Subscript) and isinstance(field.annotation.value, ast.Name) and field.annotation.value.id == 'Mapped':
                    columns.add(field.target.id)
        if table:
            result[table] = columns
    if not {'users', 'courses', 'projects', 'tasks', 'cards', 'plans', 'submissions', 'files'} <= result.keys():
        raise ValueError('无法确定当前项目所需业务结构')
    return result


def validate_existing_demo(project_root, data_dir):
    """启动前纯只读验证；不导入业务 app、不读取密钥、不创建或修复数据库。"""
    root, destination = _demo_path(project_root, data_dir)
    if not destination.is_dir():
        raise ValueError('演示目录不存在')
    _check_demo_tree(destination)
    for name in ('collaboration.db', 'jwt.key', 'manifest.json'):
        if not (destination / name).is_file():
            raise ValueError('演示目录缺少必要初始化文件')
    if not (destination / 'files').is_dir():
        raise ValueError('演示附件目录缺失')
    if any((destination / ('collaboration.db' + suffix)).exists() for suffix in ('-journal', '-wal', '-shm')):
        raise ValueError('演示库存在事务辅助文件；请先正常关闭写入，不自动恢复或修库')
    manifest = json.loads((destination / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('demo_type') != 'defense_demo' or manifest.get('status') != 'passed':
        raise ValueError('缺少已通过验收的答辩演示清单')
    if Path(os.path.abspath(manifest.get('data_dir', ''))) != destination:
        raise ValueError('演示清单目录与当前目录不一致')
    schema = _required_schema(root)
    database = destination / 'collaboration.db'
    # immutable 禁止 journal 恢复及辅助文件创建；本工具只接收已干净关闭的演示库。
    uri = database.as_uri() + '?mode=ro&immutable=1'
    try:
        with sqlite3.connect(uri, uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('演示 SQLite 完整性检查未通过')
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not schema.keys() <= tables:
                raise ValueError('演示库缺少当前应用的必要业务表')
            for table, columns in schema.items():
                # 表名来自受信任的本地模型标识符，不接受 manifest 或用户 SQL。
                actual = {row[1] for row in db.execute('PRAGMA table_info("' + table.replace('"', '""') + '")')}
                if not columns <= actual:
                    raise ValueError('演示库缺少当前应用的必要业务列')
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('演示库业务引用不完整')
            expected_accounts = {username: identity for username, _, identity in ACCOUNTS}
            accounts = {username: identity for username, identity in db.execute('SELECT username,identity FROM users WHERE active=1')}
            if any(accounts.get(username) != identity for username, identity in expected_accounts.items()):
                raise ValueError('演示账号尚未完整初始化')
            pid, other, course = (manifest.get(key) for key in ('project_id', 'other_project_id', 'course_id'))
            if not all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in (pid, other, course)):
                raise ValueError('演示清单缺少课程及团队编号')
            projects = db.execute('SELECT id FROM projects WHERE id IN (?,?) AND course_id=?', (pid, other, course)).fetchall()
            if pid == other or len(projects) != 2 or not db.execute('SELECT 1 FROM courses WHERE id=?', (course,)).fetchone():
                raise ValueError('演示课程或两团队尚未初始化')
            for table, minimum in {'requirements': 2, 'tasks': 2, 'cards': 2, 'plans': 2, 'submissions': 5, 'files': 5}.items():
                count = db.execute('SELECT count(*) FROM "' + table + '" WHERE project_id=?', (pid,)).fetchone()[0]
                if count < minimum:
                    raise ValueError('演示业务记录尚未完整初始化')
            materials = manifest.get('materials', [])
            if len(materials) < 5:
                raise ValueError('演示清单缺少原始提交材料')
            for material in materials:
                stored = db.execute('SELECT storage_name,size FROM files WHERE id=? AND project_id=?', (material.get('id'), pid)).fetchone()
                if not stored or not isinstance(stored[0], str) or Path(stored[0]).name != stored[0] or '/' in stored[0] or '\\' in stored[0]:
                    raise ValueError('演示材料文件引用无效')
                asset = destination / 'files' / stored[0]
                if not asset.is_file() or asset.stat().st_size != stored[1] or hashlib.sha256(asset.read_bytes()).hexdigest() != material.get('sha256'):
                    raise ValueError('原始演示材料缺失或字节发生变化')
    except sqlite3.DatabaseError as error:
        raise ValueError('演示 SQLite 不可读或结构损坏，未执行创建或修复') from error
    finally:
        if 'db' in locals():
            db.close()
    return {'status': 'passed', 'data_dir': str(destination), 'validated_tables': len(schema), 'read_only': True}


def _load_backend(data_dir, signing_key, backend_root):
    # app.main 的模块级 app=create_app() 也只能获得隔离配置。
    # 本工具是进程级命令；故意不恢复继承的凭据，防止后续导入意外使用它们。
    os.environ['DATA_DIR'] = str(data_dir)
    os.environ['JWT_SECRET'] = signing_key
    os.environ['LLM_API_KEY'] = ''
    os.environ['LLM_MODEL'] = ''
    os.environ['LLM_BASE_URL'] = 'http://127.0.0.1:9/v1'
    sys.path.insert(0, str(Path(backend_root).resolve()))
    from app.config import Settings
    from app.main import create_app
    from app.models import User
    from app.security import hash_password
    from fastapi.testclient import TestClient
    settings = Settings(data_dir=data_dir, jwt_secret=signing_key, llm_api_key='',
                        llm_model='', llm_base_url='http://127.0.0.1:9/v1')
    return create_app(settings), TestClient, User, hash_password


def initialize_demo(project_root=ROOT, data_dir=None, reference_date=None, *, backend_root=None):
    """只在新目录创建；project_root 参数供隔离测试使用，不读正式 data。"""
    root = Path(project_root)
    reference = date.fromisoformat(str(reference_date)) if reference_date else date.today()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = validate_destination(root, data_dir if data_dir is not None else
                                      root / 'work' / 'defense-demo' / stamp)
    destination.mkdir(parents=True, exist_ok=False)
    signing_key = secrets.token_urlsafe(48)
    (destination / 'jwt.key').write_text(signing_key, encoding='ascii')
    app, TestClient, User, hash_password = _load_backend(destination, signing_key,
                                                       backend_root or root / 'backend')
    report = {'demo_type': 'defense_demo', 'status': 'building', 'data_dir': str(destination),
              'reference_date': reference.isoformat(), 'created_at': datetime.now(timezone.utc).isoformat(),
              'timezone': 'Asia/Shanghai', 'external_model_calls': 0,
              'provenance': '全部为人工编排的答辩演示数据；卡片均为人工备用草案，非 Agent 输出。',
              'timeline': '按业务顺序压缩重放；created_at 为真实执行时间，排期按 reference_date 推导，不回填历史时间。',
              'accounts': [{'username': u, 'name': n, 'identity': i,
                            'role': 'teacher' if i == 'teacher' else ('leader' if u.startswith('leader') else 'member')}
                           for u, n, i in ACCOUNTS],
              'password': PASSWORD, 'checks': [], 'materials': []}
    tokens = {}

    def check(name, passed):
        report['checks'].append({'name': name, 'passed': bool(passed)})
        if not passed:
            raise RuntimeError('演示验收失败：' + name)

    def day(offset):
        return (reference + timedelta(days=offset)).isoformat()

    with TestClient(app) as client:
        # 无注册 API。只为独立库插入公开演示账号；其余业务记录均经 API。
        with app.state.db.Session() as db:
            for username, name, identity in ACCOUNTS:
                db.add(User(username=username, name=name, identity=identity, password_hash=hash_password(PASSWORD)))
            db.commit()
        users = {}
        for username, _, _ in ACCOUNTS:
            response = client.post('/api/auth/login', json={'username': username, 'password': PASSWORD})
            check('login_' + username, response.status_code == 200)
            payload = response.json()
            tokens[username] = payload['access_token']
            users[username] = payload['user']['id']

        def call(actor, method, path, payload=None, expected=200, **kwargs):
            response = client.request(method, '/api' + path,
                                      headers={'Authorization': 'Bearer ' + tokens[actor]}, json=payload, **kwargs)
            if response.status_code != expected:
                # 不输出请求头、输入配置或包含凭据的返回原文。
                raise RuntimeError(f'{method} {path}: expected {expected}, got {response.status_code}')
            return response

        deliverables = ['需求清单与首版计划', '中期成果与延期调整说明', '验收报告与演示材料']
        course = call('teacher', 'POST', '/courses', {
            'title': LABEL + '课程资料共享平台', 'description': LABEL + '实现资料上传检索与授权下载。仅用于答辩演示。',
            'acceptance_criteria': '资料按课程分类；成员仅下载授权资料；操作和测试证据可核对。',
            'required_features': ['资料上传与分类', '授权检索与下载'], 'optional_features': [], 'references': [],
            'stages': [{'name': name, 'deadline': day(offset), 'deliverables': [deliverable]}
                       for name, offset, deliverable in zip(['需求与计划检查', '开发中期检查', '最终验收'],
                                                          [14, 28, 42], deliverables)],
            'status': 'published'}).json()
        projects = []
        for leader, members, name in [('leader', ['member1', 'member2'], '一组'),
                                     ('leader2', ['member3'], '二组')]:
            project = call(leader, 'POST', '/projects', {'course_id': course['id'],
                           'name': LABEL + name + '课程资料共享平台',
                           'description': LABEL + ('完整业务链演示，草案均由人工创建。' if leader == 'leader' else '独立团队，用于验证项目隔离。')}).json()
            projects.append(project)
            for actor in members:
                call(leader, 'POST', f'/projects/{project["id"]}/members', {'username': actor})
            for actor in [leader, *members]:
                call(actor, 'PATCH', f'/projects/{project["id"]}/members/me',
                     {'skills': ['Python', 'API测试'] if actor != 'member2' else ['Vue', '权限测试'], 'weekly_hours': 12})
        pid = projects[0]['id']
        report.update(course_id=course['id'], project_id=pid, other_project_id=projects[1]['id'])
        requirements = []
        for feature, acceptance in [('资料上传与分类', '上传小文件后可按课程分类列出；空文件名和无权限操作被拒绝。'),
                                    ('授权检索与下载', '按标题检索；同组可下载，跨组下载返回403；下载字节与原始文件一致。')]:
            requirements.append(call('leader', 'POST', f'/projects/{pid}/requirements', {
                'title': feature, 'description': LABEL + '课程资料共享平台的必做需求。', 'acceptance': acceptance,
                'course_feature': feature, 'priority': 'must', 'status': 'confirmed'}).json())

        messages = []

        def message(actor, content, **extra):
            item = call(actor, 'POST', f'/projects/{pid}/messages', {
                'content': LABEL + content, 'client_id': f'defense-{len(messages) + 1}', **extra}).json()
            messages.append(item)
            return item

        message('leader', f'本次演示课程资料共享平台。先做资料上传与分类，再做授权检索与下载。排期基准为{reference}。草案将人工创建，不作为 Agent 实测结果。')
        message('member1', f'资料上传与分类由成员甲负责，预计6小时，剩余6小时，{day(0)}开始，{day(4)}截止；每周可投入12小时，验收按已确认需求。')
        message('member2', f'授权检索与下载由成员乙负责，预计8小时，剩余8小时，{day(5)}开始，{day(9)}截止，依赖资料上传与分类；每周可投入12小时。')
        drafts = []
        for index, (title, actor, hours, start, end) in enumerate([
            ('资料上传与分类', 'member1', 6, 0, 4), ('授权检索与下载', 'member2', 8, 5, 9)]):
            drafts.append({'key': 'new_upload' if index == 0 else 'new_search', 'existing_id': None,
                           'title': LABEL + title, 'description': LABEL + '人工备用草案中的明确分工。',
                           'requirement_id': requirements[index]['id'], 'acceptance': requirements[index]['acceptance'],
                           'assignee_id': users[actor], 'estimated_hours': hours, 'remaining_hours': hours,
                           'start_date': day(start), 'due_date': day(end), 'dependencies': [] if index == 0 else ['new_upload'],
                           'status': 'todo', 'progress': 0, 'artifact_url': '', 'blocker': '', 'stage_index': 1})

        def publish(kind, title, summary, task_drafts, source_ids):
            card = call('leader', 'POST', f'/projects/{pid}/cards', {
                'kind': kind, 'title': LABEL + '【人工备用草案】' + title, 'summary': LABEL + '【人工备用草案】' + summary,
                'questions': [], 'source_message_ids': source_ids, 'tasks': task_drafts}).json()
            check(title + '_constraints', card['checks']['valid'])
            for actor in ('member1', 'member2'):
                call(actor, 'POST', f'/cards/{card["id"]}/feedback', {'content': LABEL + '已核对本人安排、工时及依赖，同意由组长发布。', 'confirmed': True})
            call('member1', 'POST', f'/cards/{card["id"]}/publish', expected=403)
            return call('leader', 'POST', f'/cards/{card["id"]}/publish').json()

        plan1 = publish('plan', '首版分工与排期', '来源是成员的明确讨论；不包含任何模型输出。', drafts,
                        [m['id'] for m in messages])
        check('plan_v1', plan1['version'] == 1)
        tasks = call('leader', 'GET', f'/projects/{pid}/tasks').json()
        expected_materials = {}

        def submit(stage, version, result, findings, content):
            filename = f'stage-{stage + 1}-v{version}.md'
            body = (f'# {LABEL}{deliverables[stage]} v{version}\n\n仅用于答辩演示，不是正式课程成果。\n'
                    f'排期参考日期：{reference}；本轮按业务顺序压缩重放。\n\n{content}\n').encode('utf-8')
            uploaded = call('member1' if stage < 2 else 'member2', 'POST', f'/projects/{pid}/files',
                            files={'file': (filename, body, 'text/markdown')}).json()
            call('teacher', 'GET', f'/files/{uploaded["id"]}', expected=403)
            submission = call('leader', 'POST', f'/projects/{pid}/submissions', {
                'stage_index': stage, 'summary': f'{LABEL}{deliverables[stage]} v{version}：{content}',
                'artifact_urls': [], 'file_ids': [uploaded['id']],
                'materials': {deliverables[stage]: ['file:' + str(uploaded['id'])]}}).json()
            check(f'stage_{stage + 1}_v{version}_pending', submission['status'] == 'pending' and submission['version'] == version)
            reviewed = call('teacher', 'POST', f'/submissions/{submission["id"]}/review',
                            {'result': result, 'comment': LABEL + findings}).json()
            check(f'stage_{stage + 1}_v{version}_review', reviewed['status'] == result and len(reviewed['reviews']) == 1)
            check(f'stage_{stage + 1}_v{version}_download', call('teacher', 'GET', f'/files/{uploaded["id"]}').content == body)
            expected_materials[uploaded['id']] = body
            report['materials'].append({'id': uploaded['id'], 'submission_id': submission['id'], 'filename': filename,
                                        'stage_index': stage, 'version': version, 'sha256': hashlib.sha256(body).hexdigest()})

        submit(0, 1, 'needs_changes', '需求与首版计划已关联；请在材料补充跨组下载拒绝的明确验收步骤。',
               '首版计划v1：成员甲6小时完成上传分类，成员乙8小时完成检索下载。已有权限要求，测试步骤待补充。')
        submit(0, 2, 'passed', '已补齐同组允许、跨组拒绝及文件字节一致性步骤，初期检查通过。',
               '沿用计划v1；补充验收：同组下载成功；二组下载一组资料返回403；下载哈希应与上传一致。')
        updated = call('member1', 'PATCH', f'/tasks/{tasks[0]["id"]}', {
            'status': 'doing', 'progress': 25, 'remaining_hours': 4.5,
            'blocker': LABEL + '等待教师提供课程分类样例，原截止日存在延期风险。'}).json()
        check('member_own_update_25_percent', updated['progress'] == 25 and updated['remaining_hours'] == 4.5)
        call('member1', 'POST', f'/tasks/{tasks[0]["id"]}/comments', {
            'kind': 'blocker', 'content': LABEL + '本人推进25%，剩余4.5小时；已完成上传接口，课程分类样例未到，申请顺延两天。'})
        message('member1', f'资料上传与分类已推进25%，剩余4.5小时。等待课程分类样例，申请截止日从{day(4)}改到{day(6)}；负责人和预计6小时不变。')
        message('member2', f'同意联动依赖：授权检索与下载改为{day(7)}开始、{day(11)}截止，负责人、8小时不变。')
        adjusted = []
        for index, task in enumerate(call('leader', 'GET', f'/projects/{pid}/tasks').json()):
            draft = {field: task[field] for field in drafts[index] if field not in ('existing_id', 'dependencies')}
            draft.update(existing_id=task['id'], key=f'task_{task["id"]}',
                         dependencies=[] if index == 0 else [f'task_{tasks[0]["id"]}'],
                         due_date=day(6 if index == 0 else 11))
            if index == 1:
                draft['start_date'] = day(7)
            adjusted.append(draft)
        plan2 = publish('adjust', '延期与依赖联动调整', '依据本人25%进度和阻碍顺延首项两天，后项随依赖顺延；人工备用演示。',
                        adjusted, [m['id'] for m in messages[-2:]])
        check('plan_v2', plan2['version'] == 2)
        call('member1', 'PATCH', f'/tasks/{tasks[0]["id"]}', {'status': 'done', 'progress': 100, 'remaining_hours': 0, 'blocker': ''})
        message('member1', '分类样例已补齐，上传与分类已完成；提交本阶段演示说明，解除成员乙的前置依赖。')
        submit(1, 1, 'passed', '第一项已完成，整体按任务数为50%；延期理由、依赖联动与计划v2记录完整，中期检查通过。',
               '计划v2保留原分工：首项完成；第二项依赖已解除。延期两天的前后排期在计划历史可比较。')
        call('member2', 'PATCH', f'/tasks/{tasks[1]["id"]}', {'status': 'doing', 'progress': 60, 'remaining_hours': 3.2,
                                                           'blocker': LABEL + '正在补充跨组权限测试。'})
        call('member2', 'PATCH', f'/tasks/{tasks[1]["id"]}', {'status': 'done', 'progress': 100, 'remaining_hours': 0, 'blocker': ''})
        message('member2', '授权检索与下载已完成，同组允许、跨组拒绝及下载字节一致性检查通过。两项均完成，准备最终材料。')
        submit(2, 1, 'needs_changes', '任务完成比例为100%不等于验收通过；最终材料缺少测试步骤与预期结果对照，请补充。',
               '两项任务均完成。演示报告列出上传分类和授权下载功能，测试结果对照表待补充。')
        submit(2, 2, 'passed', '已补充权限边界测试步骤与结果、阶段历史和延期说明；最终材料检查通过。',
               '补充测试对照：上传后分类可见；同组下载200且哈希一致；跨组下载403；教师只看公开计划与已提交材料。')

        public_plans = call('teacher', 'GET', f'/projects/{pid}/plans').json()
        submissions = call('teacher', 'GET', f'/projects/{pid}/submissions').json()
        check('two_immutable_plan_snapshots', [p['version'] for p in public_plans] == [1, 2]
              and public_plans[0]['tasks'][0]['progress'] == 0 and public_plans[1]['tasks'][0]['progress'] == 25)
        check('five_reviewed_versions', [(s['stage_index'], s['version'], s['status']) for s in submissions] == [
            (0, 1, 'needs_changes'), (0, 2, 'passed'), (1, 1, 'passed'), (2, 1, 'needs_changes'), (2, 2, 'passed')])
        check('submission_plan_versions', [s['plan_version'] for s in submissions] == [1, 1, 2, 2, 2])
        check('independent_progress_snapshots', [s['progress_snapshot']['completion_percent'] for s in submissions] == [0, 0, 50, 100, 100])
        for file_id, content in expected_materials.items():
            check('history_material_bytes_' + str(file_id), call('teacher', 'GET', f'/files/{file_id}').content == content)
        for suffix in ('messages', 'cards', 'files', 'agent/runs'):
            call('teacher', 'GET', f'/projects/{pid}/{suffix}', expected=403)
        check('teacher_private_resources_denied', True)
        call('leader2', 'GET', f'/projects/{pid}/messages', expected=403)
        check('other_team_denied', True)
        call('member1', 'PATCH', f'/tasks/{tasks[1]["id"]}', {'blocker': '越权'}, expected=403)
        check('other_member_update_denied', True)
        call('leader', 'POST', f'/projects/{pid}/agent/analyze', {'mode': 'discussion'}, expected=503)
        check('ai_disabled', not app.state.settings.ai_ready and not app.state.agent.ready)
        from sqlalchemy import func, select
        from app.models import AgentRun
        with app.state.db.Session() as db:
            check('zero_agent_runs', db.scalar(select(func.count()).select_from(AgentRun)) == 0)
        check('private_card_summary_not_in_public_plan', '【人工备用草案】' not in json.dumps(public_plans, ensure_ascii=False))
        report['plans'] = [{'id': p['id'], 'version': p['version']} for p in public_plans]
        report['submissions'] = [{'id': s['id'], 'stage_index': s['stage_index'], 'version': s['version'],
                                  'status': s['status'], 'plan_version': s['plan_version'],
                                  'completion_percent': s['progress_snapshot']['completion_percent']} for s in submissions]
    report['counts'] = {'accounts': 6, 'teams': 2, 'requirements': 2, 'tasks': 2,
                        'plans': 2, 'cards': 2, 'submissions': 5, 'materials': 5}
    report['status'] = 'passed'
    (destination / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (destination / '演示说明.md').write_text(
        f'# {LABEL}课程资料共享平台\n\n数据目录：`{destination}`\n\n排期参考日期：{reference}。'
        '\n\n全部是人工编排的功能演示，卡片带【人工备用草案】，不冒充 Agent 真实输出。'
        '\n业务按顺序压缩重放，真实操作时间没有回填为排期日期。'
        f'\n\n公开演示密码：`{PASSWORD}`；账号：teacher / leader / member1 / member2 / leader2 / member3。'
        f'\n\n主项目ID：{pid}；对照团队ID：{projects[1]["id"]}；计划2版、审核提交5次、真实材料5份。'
        '\n\n顺序：讨论 → 人工备用草案 → 成员反馈 → 组长发布v1 → 初期v1需修改/v2通过'
        ' → 本人25%及阻碍 → 延期草案/发布v2 → 中期50%通过 → 最终100%时v1需修改/v2通过。'
        '\n\n教师能看公开计划、进度和已提交材料，不能读取聊天室、内部草案、附件列表和 Agent 记录。'
        '\n教师通过阶段提交下载材料；各版本原始字节和审核意见均保留。'
        '\n\n默认启动禁用AI、端口8001。开启 -EnableAI 会启用真实模型并可能恢复待处理讨论意图，需明确选择。'
        '\n\n验收详情及材料 SHA256：manifest.json。', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='新建隔离答辩演示库（不读 .env、不联网、不覆盖既有目录）')
    parser.add_argument('--data-dir', type=Path, help='项目 work/defense-demo 下的全新子目录；默认UTC时间戳')
    parser.add_argument('--reference-date', help='排期参考日 YYYY-MM-DD，默认运行当天')
    parser.add_argument('--validate-existing', action='store_true', help='仅只读验证已有演示目录；不导入 app、不读密钥、不建表')
    args = parser.parse_args(argv)
    try:
        if args.validate_existing:
            if args.data_dir is None:
                parser.error('--validate-existing 必须指定 --data-dir')
            validate_existing_demo(ROOT, args.data_dir)
            print('答辩演示启动前只读验证通过。')
            return
        manifest = initialize_demo(ROOT, args.data_dir, args.reference_date)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, SyntaxError) as error:
        parser.exit(1, f'{type(error).__name__}: {error}\n')
    print(f'答辩演示初始化完成：{manifest["data_dir"]}')
    print(f'主项目 {manifest["project_id"]}；计划2版、阶段提交5次、材料5份；外部模型调用0。')
    print('公开演示账号 teacher/leader/member1/member2/leader2/member3；密码 Demo2026!')


if __name__ == '__main__':
    main()
