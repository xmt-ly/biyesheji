from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from ..business import audit, bump_revision
from ..database import get_db
from ..models import Course, Requirement
from ..permissions import require_project, resource
from ..schemas import RequirementInput, RequirementPatch
from ..security import current_user
from ..serializers import requirement_json

router=APIRouter(prefix='/api',tags=['需求'])


def validate_feature(db,project,feature):
    course=db.get(Course,project.course_id)
    if feature and feature not in [*course.required_features,*course.optional_features]:
        raise HTTPException(422,'course_feature 必须来自本课程的功能要求')


@router.get('/projects/{project_id}/requirements')
def list_requirements(project_id:int,db=Depends(get_db),user=Depends(current_user)):
    require_project(db,project_id,user)
    query=select(Requirement).where(Requirement.project_id==project_id).order_by(Requirement.id)
    if user.identity=='teacher':
        query=query.where(Requirement.status=='confirmed')
    return [requirement_json(r) for r in db.scalars(query)]


@router.post('/projects/{project_id}/requirements')
async def create_requirement(project_id:int,payload:RequirementInput,request:Request,db=Depends(get_db),user=Depends(current_user)):
    p,m=require_project(db,project_id,user,internal=True)
    if payload.status=='confirmed' and m.role!='leader':
        raise HTTPException(403,'仅本项目组长可以确认需求')
    validate_feature(db,p,payload.course_feature)
    r=Requirement(project_id=p.id,creator_id=user.id,**payload.model_dump())
    db.add(r)
    db.flush()
    bump_revision(db,p)
    audit(db,user.id,p.id,'requirement',r.id,'created',payload.model_dump())
    db.commit()
    await request.app.state.hub.broadcast(p.id,{'type':'project_changed'})
    return requirement_json(r)


@router.patch('/requirements/{requirement_id}')
async def update_requirement(requirement_id:int,payload:RequirementPatch,request:Request,db=Depends(get_db),user=Depends(current_user)):
    r=resource(db,Requirement,requirement_id)
    p,m=require_project(db,r.project_id,user,internal=True)
    changes=payload.model_dump(exclude_unset=True)
    if any(v is None for v in changes.values()):
        raise HTTPException(422,'需求字段不能设为 null')
    if m.role!='leader' and (r.creator_id!=user.id or r.status=='confirmed' or 'status' in changes):
        raise HTTPException(403,'成员只能修改本人未确认需求，确认需求由组长处理')
    if 'course_feature' in changes:
        validate_feature(db,p,changes['course_feature'])
    for k,v in changes.items():
        setattr(r,k,v)
    bump_revision(db,p)
    audit(db,user.id,p.id,'requirement',r.id,'updated',changes)
    db.commit()
    await request.app.state.hub.broadcast(p.id,{'type':'project_changed'})
    return requirement_json(r)
