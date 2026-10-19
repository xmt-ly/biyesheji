from fastapi import HTTPException
from sqlalchemy import select
from .models import Course, Member, Project
from .config import MAX_SQL_ID


def validate_sql_id(value):
    if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=MAX_SQL_ID:
        raise HTTPException(422,'ID 必须是 1 到 9223372036854775807 之间的整数')
    return value


def require_public_course(db,course_id):
    course=db.get(Course,validate_sql_id(course_id))
    if not course or course.status not in ('published','archived'):
        raise HTTPException(403,'项目关联课程未公开，不能读取课程要求或分析')
    return course


def require_teacher(user):
    if user.identity != 'teacher':
        raise HTTPException(403, '仅教师可以执行此操作')


def require_course(db, course_id, user, write=False):
    course = db.get(Course, validate_sql_id(course_id))
    if not course:
        raise HTTPException(404, '课程不存在')
    if user.identity == 'teacher':
        if course.teacher_id != user.id:
            raise HTTPException(403, '只能访问自己负责的课程')
    elif write or course.status != 'published':
        raise HTTPException(403, '课程尚未发布或无访问权限')
    return course


def require_project(db, project_id, user, internal=False, leader=False):
    project = db.get(Project, validate_sql_id(project_id))
    if not project:
        raise HTTPException(404, '项目不存在')
    if user.identity == 'teacher':
        course = db.get(Course, project.course_id)
        if internal or leader or course.teacher_id != user.id:
            raise HTTPException(403, '无权访问该项目的内部协作数据或执行此操作')
        return project, None
    member = db.scalar(select(Member).where(Member.project_id == project.id, Member.user_id == user.id))
    if not member or (leader and member.role != 'leader'):
        raise HTTPException(403, '无项目权限，或此操作需要本项目组长')
    require_public_course(db,project.course_id)
    return project, member


def resource(db, model, object_id):
    item = db.get(model, validate_sql_id(object_id))
    if not item:
        raise HTTPException(404, '记录不存在')
    return item
