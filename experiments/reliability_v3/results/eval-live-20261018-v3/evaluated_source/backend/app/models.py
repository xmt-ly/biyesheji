from datetime import datetime, timezone
from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


def now():
    return datetime.now(timezone.utc).isoformat()


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str]
    identity: Mapped[str]
    password_hash: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)


class Course(Base):
    __tablename__ = 'courses'
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    title: Mapped[str]
    description: Mapped[str] = mapped_column(Text, default='')
    acceptance_criteria: Mapped[str] = mapped_column(Text, default='')
    required_features: Mapped[list] = mapped_column(JSON, default=list)
    optional_features: Mapped[list] = mapped_column(JSON, default=list)
    references: Mapped[list] = mapped_column(JSON, default=list)
    stages: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(default='draft')
    version: Mapped[int] = mapped_column(default=1)
    history: Mapped[list] = mapped_column(JSON, default=list)


class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey('courses.id'))
    name: Mapped[str]
    description: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(default='preparing')
    revision: Mapped[int] = mapped_column(default=1)
    analyzed_message_id: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[str] = mapped_column(default=now)


class Member(Base):
    __tablename__ = 'members'
    __table_args__ = (UniqueConstraint('project_id', 'user_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    role: Mapped[str] = mapped_column(default='member')
    skills: Mapped[list] = mapped_column(JSON, default=list)
    weekly_hours: Mapped[float] = mapped_column(default=0)


class Requirement(Base):
    __tablename__ = 'requirements'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    title: Mapped[str]
    description: Mapped[str] = mapped_column(Text, default='')
    acceptance: Mapped[str]
    course_feature: Mapped[str] = mapped_column(default='')
    priority: Mapped[str] = mapped_column(default='must')
    status: Mapped[str] = mapped_column(default='draft')
    creator_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[str] = mapped_column(default=now)


class Task(Base):
    __tablename__ = 'tasks'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    title: Mapped[str]
    description: Mapped[str] = mapped_column(Text, default='')
    requirement_id: Mapped[int] = mapped_column(ForeignKey('requirements.id'))
    acceptance: Mapped[str]
    assignee_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    estimated_hours: Mapped[float]
    remaining_hours: Mapped[float]
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    start_date: Mapped[str]
    due_date: Mapped[str]
    status: Mapped[str] = mapped_column(default='todo')
    progress: Mapped[float] = mapped_column(default=0)
    artifact_url: Mapped[str] = mapped_column(default='')
    blocker: Mapped[str] = mapped_column(Text, default='')
    planning_risks: Mapped[list] = mapped_column(JSON, default=list)
    stage_index: Mapped[int] = mapped_column(default=2)
    creator_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[str] = mapped_column(default=now)
    updated_at: Mapped[str] = mapped_column(default=now)


class Comment(Base):
    __tablename__ = 'comments'
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    kind: Mapped[str] = mapped_column(default='comment')
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(default=now)


class Message(Base):
    __tablename__ = 'messages'
    __table_args__ = (UniqueConstraint('project_id', 'user_id', 'client_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    kind: Mapped[str] = mapped_column(default='human')
    content: Mapped[str] = mapped_column(Text)
    client_id: Mapped[str | None] = mapped_column(nullable=True)
    related_type: Mapped[str | None] = mapped_column(nullable=True)
    related_id: Mapped[int | None] = mapped_column(nullable=True)
    supersedes_card_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(default=now)


class Card(Base):
    __tablename__ = 'cards'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    kind: Mapped[str]
    title: Mapped[str]
    summary: Mapped[str] = mapped_column(Text)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    source_message_ids: Mapped[list] = mapped_column(JSON, default=list)
    supersedes_card_ids: Mapped[list] = mapped_column(JSON, default=list)
    tasks: Mapped[list] = mapped_column(JSON, default=list)
    checks: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(default='pending')
    base_revision: Mapped[int]
    feedback: Mapped[list] = mapped_column(JSON, default=list)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(default=now)
    published_plan_id: Mapped[int | None] = mapped_column(ForeignKey('plans.id'), nullable=True)


class Plan(Base):
    __tablename__ = 'plans'
    __table_args__ = (UniqueConstraint('project_id', 'version'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    version: Mapped[int]
    created_at: Mapped[str] = mapped_column(default=now)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    summary: Mapped[str]
    tasks: Mapped[list] = mapped_column(JSON)
    changes: Mapped[list] = mapped_column(JSON, default=list)


class Submission(Base):
    __tablename__ = 'submissions'
    __table_args__ = (UniqueConstraint('project_id', 'stage_index', 'version'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    stage_index: Mapped[int]
    version: Mapped[int]
    status: Mapped[str] = mapped_column(default='pending')
    summary: Mapped[str] = mapped_column(Text)
    artifact_urls: Mapped[list] = mapped_column(JSON, default=list)
    file_ids: Mapped[list] = mapped_column(JSON, default=list)
    materials: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(default=now)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    plan_version: Mapped[int | None] = mapped_column(nullable=True)
    progress_snapshot: Mapped[dict] = mapped_column(JSON)
    reviews: Mapped[list] = mapped_column(JSON, default=list)


class StoredFile(Base):
    __tablename__ = 'files'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    filename: Mapped[str]
    storage_name: Mapped[str]
    content_type: Mapped[str]
    size: Mapped[int]
    created_at: Mapped[str] = mapped_column(default=now)


class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey('projects.id'), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    object_type: Mapped[str]
    object_id: Mapped[int]
    action: Mapped[str]
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(default=now)


class AgentRun(Base):
    __tablename__ = 'agent_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    base_revision: Mapped[int]
    source_message_ids: Mapped[list] = mapped_column(JSON, default=list)
    mode: Mapped[str] = mapped_column(default='discussion')
    intent_ids: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str]
    prompt_version: Mapped[str] = mapped_column(default='v1')
    status: Mapped[str]
    error: Mapped[str | None] = mapped_column(nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(nullable=True)
    tokens: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(default=now)


class AgentIntent(Base):
    """持久处理意图：与消息游标分别保存，业务调整不依赖人类聊天消息。"""
    __tablename__ = 'agent_intents'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'),index=True)
    mode: Mapped[str]
    requested: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(default='queued',index=True)
    message_id: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[str] = mapped_column(default=now)
    updated_at: Mapped[str] = mapped_column(default=now)
