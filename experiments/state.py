"""每次尝试新建独立 SQLite 内存库，复用生产项目工具和约束检查。"""
from contextlib import contextmanager
from .backend import (Database, Card, Course, Member, Message, Project, Requirement, Task,
                      User, ProjectTools, message_json)
from .cases import STAMP


@contextmanager
def isolated_state(case):
    database = Database('sqlite:///:memory:')
    database.create_tables()
    try:
        state = case['state']
        with database.Session() as db:
            db.add_all([User(**u, password_hash='unusable-experiment-password', active=True) for u in state['users']])
            db.flush()
            db.add(Course(**state['course']))
            db.flush()
            db.add(Project(**state['project']))
            db.flush()
            db.add_all([Member(project_id=1, **m) for m in state['members']])
            db.add_all([Requirement(project_id=1, creator_id=11, created_at=STAMP, **r) for r in state['requirements']])
            db.flush()
            for draft in state['tasks']:
                values = {k: v for k, v in draft.items() if k not in ('key', 'existing_id', 'dependencies')}
                db.add(Task(id=draft['existing_id'], project_id=1, creator_id=11,
                    dependencies=[int(k.removeprefix('task_')) for k in draft['dependencies']],
                    created_at=STAMP, updated_at=STAMP, planning_risks=[], **values))
            db.flush()
            db.add_all([Card(project_id=1, **c) for c in state['cards']])
            db.add_all([Message(project_id=1, **m) for m in case['messages']])
            db.commit()
        yield database
    finally:
        database.engine.dispose()


def inputs(case, database):
    tools = ProjectTools(database, 1)
    context = tools.execute('get_project_context', {})
    with database.Session() as db:
        messages = [message_json(db, db.get(Message, m['id'])) for m in case['messages']]
    # 翻译目录只含名称与编号，不包含角色容量、排期、期限或标签类别。
    directory = dict(members=[dict(name=u['name'], user_id=u['id']) for u in case['state']['users'] if u['identity'] == 'student'],
        requirements=[dict(title=r['title'], requirement_id=r['id']) for r in case['state']['requirements']],
        tasks=[dict(title=t['title'], key=t['key'], existing_id=t['existing_id']) for t in case['state']['tasks']],
        cards=[dict(title=c['title'], card_id=c['id']) for c in case['state']['cards']])
    context['name_id_directory'] = directory
    return context, messages, directory
