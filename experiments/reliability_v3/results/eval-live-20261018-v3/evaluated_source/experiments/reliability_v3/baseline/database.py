from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import Request


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url):
        options = {'connect_args': {'check_same_thread': False, 'timeout': 15}} if url.startswith('sqlite:') else {}
        if url in ('sqlite://', 'sqlite:///:memory:'):
            options['poolclass'] = StaticPool
        self.engine = create_engine(url, **options)
        if url.startswith('sqlite:'):
            @event.listens_for(self.engine, 'connect')
            def configure_sqlite(connection, _):
                connection.execute('PRAGMA foreign_keys=ON')
                connection.execute('PRAGMA busy_timeout=15000')
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def create_tables(self):
        from . import models  # 注册模型
        Base.metadata.create_all(self.engine)


def get_db(request: Request):
    with request.app.state.db.Session() as session:
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
