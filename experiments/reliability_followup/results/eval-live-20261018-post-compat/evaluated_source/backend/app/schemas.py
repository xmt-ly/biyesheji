from datetime import date
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .config import MAX_SQL_ID

SqlId=Annotated[int,Field(ge=1,le=MAX_SQL_ID)]
TaskKey=Annotated[str,Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')]
Question=Annotated[str,Field(min_length=1,max_length=2000)]


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Login(Payload):
    username: str = Field(min_length=1,max_length=64)
    password: str = Field(min_length=1,max_length=256)


class Stage(Payload):
    name: str = Field(min_length=1,max_length=100)
    deadline: date
    deliverables: list[str] = Field(default_factory=list,max_length=30)


class CourseInput(Payload):
    title: str = Field(min_length=1,max_length=200)
    description: str = Field(default='',max_length=20000)
    acceptance_criteria: str = Field(default='',max_length=20000)
    required_features: list[str] = Field(default_factory=list,max_length=100)
    optional_features: list[str] = Field(default_factory=list,max_length=100)
    references: list[str] = Field(default_factory=list,max_length=100)
    stages: list[Stage] = Field(default_factory=list,max_length=3)
    status: Literal['draft','published','archived'] = 'draft'


class CoursePatch(Payload):
    title: str | None = Field(default=None,min_length=1,max_length=200)
    description: str | None = Field(default=None,max_length=20000)
    acceptance_criteria: str | None = Field(default=None,max_length=20000)
    required_features: list[str] | None = Field(default=None,max_length=100)
    optional_features: list[str] | None = Field(default=None,max_length=100)
    references: list[str] | None = Field(default=None,max_length=100)
    stages: list[Stage] | None = Field(default=None,max_length=3)
    status: Literal['draft','published','archived'] | None = None


class ProjectInput(Payload):
    course_id: SqlId
    name: str = Field(min_length=1,max_length=200)
    description: str = Field(default='',max_length=20000)


class ProjectPatch(Payload):
    name: str | None = Field(default=None,min_length=1,max_length=200)
    description: str | None = Field(default=None,max_length=20000)
    status: Literal['preparing','active','archived'] | None = None


class Invite(Payload):
    username: str


class Capacity(Payload):
    skills: list[str] = Field(max_length=30)
    weekly_hours: float = Field(ge=0,le=168)


class RequirementInput(Payload):
    title: str = Field(min_length=1,max_length=200)
    description: str = Field(default='',max_length=20000)
    acceptance: str = Field(min_length=1,max_length=10000)
    course_feature: str = Field(default='',max_length=200)
    priority: Literal['must','should','could'] = 'must'
    status: Literal['draft','confirmed'] = 'draft'


class RequirementPatch(Payload):
    title: str | None = Field(default=None,min_length=1,max_length=200)
    description: str | None = Field(default=None,max_length=20000)
    acceptance: str | None = Field(default=None,min_length=1,max_length=10000)
    course_feature: str | None = Field(default=None,max_length=200)
    priority: Literal['must','should','could'] | None = None
    status: Literal['draft','confirmed'] | None = None


class TaskInput(Payload):
    title: str = Field(min_length=1,max_length=200)
    description: str = Field(default='',max_length=20000)
    requirement_id: SqlId
    acceptance: str = Field(min_length=1,max_length=10000)
    assignee_id: SqlId
    estimated_hours: float = Field(ge=0,le=100000)
    remaining_hours: float = Field(ge=0,le=100000)
    dependencies: list[SqlId] = Field(default_factory=list,max_length=200)
    start_date: date
    due_date: date
    status: Literal['todo','doing','done'] = 'todo'
    progress: float = Field(default=0,ge=0,le=100)
    artifact_url: str = Field(default='',max_length=2000)
    blocker: str = Field(default='',max_length=10000)
    stage_index: int = Field(default=2,ge=0,le=2)


class DraftTask(TaskInput):
    key: TaskKey
    existing_id: SqlId | None = None
    dependencies: list[TaskKey] = Field(default_factory=list,max_length=200)


class TaskPatch(Payload):
    title: str | None = Field(default=None,min_length=1,max_length=200)
    description: str | None = Field(default=None,max_length=20000)
    requirement_id: SqlId | None = None
    acceptance: str | None = Field(default=None,min_length=1,max_length=10000)
    assignee_id: SqlId | None = None
    estimated_hours: float | None = Field(default=None,ge=0,le=100000)
    remaining_hours: float | None = Field(default=None,ge=0,le=100000)
    dependencies: list[SqlId] | None = Field(default=None,max_length=200)
    start_date: date | None = None
    due_date: date | None = None
    status: Literal['todo','doing','done'] | None = None
    progress: float | None = Field(default=None,ge=0,le=100)
    artifact_url: str | None = Field(default=None,max_length=2000)
    blocker: str | None = Field(default=None,max_length=10000)
    stage_index: int | None = Field(default=None,ge=0,le=2)
    correction_reason: str | None = Field(default=None,max_length=10000)


class CommentInput(Payload):
    kind: Literal['comment','blocker','artifact'] = 'comment'
    content: str = Field(min_length=1,max_length=20000)


class MessageInput(Payload):
    content: str = Field(min_length=1,max_length=20000)
    client_id: str = Field(min_length=1,max_length=100)
    related_type: Literal['task','requirement','card'] | None = None
    related_id: SqlId | None = None
    supersedes_card_ids: list[SqlId] = Field(default_factory=list,max_length=100)


class CardInput(Payload):
    kind: Literal['discussion','plan','adjust'] = 'plan'
    title: str = Field(default='人工规划草案',min_length=1,max_length=200)
    summary: str = Field(min_length=1,max_length=20000)
    questions: list[Question] = Field(default_factory=list,max_length=100)
    source_message_ids: list[SqlId] = Field(default_factory=list,max_length=200)
    tasks: list[DraftTask] = Field(default_factory=list,max_length=300)


class CardPatch(Payload):
    title: str | None = Field(default=None,min_length=1,max_length=200)
    summary: str | None = Field(default=None,min_length=1,max_length=20000)
    questions: list[Question] | None = Field(default=None,max_length=100)
    tasks: list[DraftTask] | None = Field(default=None,max_length=300)
    status: Literal['rejected'] | None = None
    reason: str = Field(default='',max_length=10000)


class Feedback(Payload):
    content: str = Field(min_length=1,max_length=20000)
    confirmed: bool = False


class Analyze(Payload):
    mode: Literal['discussion','plan','adjust'] = 'discussion'


class AgentOutput(CardInput):
    supersedes_card_ids: list[SqlId] = Field(default_factory=list,max_length=100)


class SubmissionInput(Payload):
    stage_index: int = Field(ge=0,le=2)
    summary: str = Field(min_length=1,max_length=20000)
    artifact_urls: list[str] = Field(default_factory=list,max_length=100)
    file_ids: list[SqlId] = Field(default_factory=list,max_length=100)
    materials: dict[str,list[str]] = Field(default_factory=dict,max_length=30)

    @field_validator('artifact_urls')
    @classmethod
    def url_list(cls, value):
        if any(not s.startswith(('https://','http://')) or len(s)>2000 for s in value):
            raise ValueError('成果链接必须是 http 或 https 地址')
        return value


class ReviewInput(Payload):
    result: Literal['passed','needs_changes']
    comment: str = Field(min_length=1,max_length=20000)
