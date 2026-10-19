"""每次尝试独立内存 SQLite；只使用合成项目与真实生产工具。"""
from contextlib import contextmanager
from .backend import Database, User, Course, Project, Member, Requirement, Task, Card, Message, ProjectTools, message_json
from .cases import STAMP


@contextmanager
def isolated_state(case):
    database = Database('sqlite:///:memory:')
    database.create_tables()
    try:
        state = case['state']
        with database.Session() as db:
            db.add_all([User(**u, password_hash='unusable-evaluation-password', active=True) for u in state['users']])
            db.flush()
            db.add(Course(**state['course']))
            db.flush()
            db.add(Project(**state['project']))
            db.flush()
            db.add_all([Member(project_id=1, **m) for m in state['members']])
            db.add_all([Requirement(project_id=1, creator_id=21, created_at=STAMP, **r) for r in state['requirements']])
            db.flush()
            for draft in state['tasks']:
                values = {k:v for k,v in draft.items() if k not in ('key', 'existing_id', 'dependencies')}
                db.add(Task(id=draft['existing_id'], project_id=1, creator_id=21,
                    dependencies=[int(key.removeprefix('task_')) for key in draft['dependencies']],
                    created_at=STAMP, updated_at=STAMP, planning_risks=[], **values))
            db.flush()
            db.add_all([Card(project_id=1, **c) for c in state['cards']])
            db.add_all([Message(project_id=1, **m) for m in case['messages']])
            db.commit()
        yield database
    finally:
        database.engine.dispose()


def inputs(case, database):
    context = ProjectTools(database, 1).execute('get_project_context', {})
    with database.Session() as db:
        messages = [message_json(db, db.get(Message, m['id'])) for m in case['messages']]
    return context, messages
