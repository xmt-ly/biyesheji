from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from ..business import audit, bump_revision, validate_course
from ..database import get_db
from ..models import Course, Project, now
from ..permissions import require_course, require_teacher
from ..schemas import CourseInput, CoursePatch
from ..security import current_user
from ..serializers import course_json

router=APIRouter(prefix='/api',tags=['课程'])


@router.get('/courses')
def list_courses(db=Depends(get_db),user=Depends(current_user)):
    query=select(Course).order_by(Course.id)
    query=query.where(Course.teacher_id==user.id) if user.identity=='teacher' else query.where(Course.status=='published')
    return [course_json(c,public=user.identity!='teacher') for c in db.scalars(query)]


@router.get('/courses/{course_id}')
def get_course(course_id:int,db=Depends(get_db),user=Depends(current_user)):
    return course_json(require_course(db,course_id,user),public=user.identity!='teacher')


@router.post('/courses')
def create_course(payload:CourseInput,db=Depends(get_db),user=Depends(current_user)):
    require_teacher(user)
    data=payload.model_dump(mode='json')
    validate_course(data)
    course=Course(**data,teacher_id=user.id)
    db.add(course)
    db.flush()
    audit(db,user.id,None,'course',course.id,'created')
    db.commit()
    return course_json(course)


@router.patch('/courses/{course_id}')
async def update_course(course_id:int,payload:CoursePatch,request:Request,db=Depends(get_db),user=Depends(current_user)):
    require_teacher(user)
    course=require_course(db,course_id,user,write=True)
    changes=payload.model_dump(mode='json',exclude_unset=True)
    if any(v is None for v in changes.values()):
        raise HTTPException(422,'课程字段不能设为 null')
    if course.status in ('published','archived') and changes.get('status')=='draft':
        raise HTTPException(409,'课程一经发布或归档不能退回草稿，请维护公开要求或归档')
    before=course_json(course)
    merged=dict(before,**changes)
    validate_course(merged)
    course.history=[*course.history,{'version':course.version,'snapshot':{k:v for k,v in before.items() if k!='history'},
                                    'changed_by':user.id,'created_at':now()}]
    for k,v in changes.items():
        setattr(course,k,v)
    course.version+=1
    related_projects=db.scalars(select(Project).where(Project.course_id==course.id)).all()
    for project in related_projects:
        bump_revision(db,project)
    audit(db,user.id,None,'course',course.id,'updated',changes)
    db.commit()
    for project in related_projects:
        await request.app.state.hub.broadcast(project.id,{'type':'project_changed'})
        await request.app.state.hub.broadcast(project.id,{'type':'cards_changed'})
    return course_json(course)
