from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from ..business import audit, bump_revision, progress_snapshot
from ..database import get_db
from ..models import Course, Member, Project, User
from ..permissions import require_project, require_course
from ..schemas import Capacity, Invite, ProjectInput, ProjectPatch
from ..security import current_user
from ..serializers import member_json, project_json

router=APIRouter(prefix='/api',tags=['项目与成员'])


@router.get('/projects')
def list_projects(db=Depends(get_db),user=Depends(current_user)):
    query=select(Project).order_by(Project.id)
    if user.identity=='teacher':
        query=query.join(Course).where(Course.teacher_id==user.id)
    else:
        query=query.join(Member).where(Member.user_id==user.id)
    return [project_json(db,p,user) for p in db.scalars(query)]


@router.post('/projects')
def create_project(payload:ProjectInput,db=Depends(get_db),user=Depends(current_user)):
    if user.identity!='student':
        raise HTTPException(403,'学生才能创建团队项目')
    course=require_course(db,payload.course_id,user)
    project=Project(**payload.model_dump())
    db.add(project)
    db.flush()
    db.add(Member(project_id=project.id,user_id=user.id,role='leader'))
    audit(db,user.id,project.id,'project',project.id,'created')
    db.commit()
    return project_json(db,project,user)


@router.get('/projects/{project_id}')
def get_project(project_id:int,db=Depends(get_db),user=Depends(current_user)):
    p,_=require_project(db,project_id,user)
    return project_json(db,p,user)


@router.get('/projects/{project_id}/progress')
def project_progress(project_id:int,db=Depends(get_db),user=Depends(current_user)):
    require_project(db,project_id,user)
    return progress_snapshot(db,project_id)


@router.patch('/projects/{project_id}')
async def update_project(project_id:int,payload:ProjectPatch,request:Request,db=Depends(get_db),user=Depends(current_user)):
    p,_=require_project(db,project_id,user,leader=True)
    changes=payload.model_dump(exclude_unset=True)
    if any(v is None for v in changes.values()):
        raise HTTPException(422,'项目字段不能设为 null')
    for k,v in changes.items():
        setattr(p,k,v)
    bump_revision(db,p)
    audit(db,user.id,p.id,'project',p.id,'updated',changes)
    db.commit()
    await request.app.state.hub.broadcast(p.id,{'type':'project_changed'})
    return project_json(db,p,user)


@router.post('/projects/{project_id}/members')
async def invite(project_id:int,payload:Invite,request:Request,db=Depends(get_db),user=Depends(current_user)):
    p,_=require_project(db,project_id,user,leader=True)
    invited=db.scalar(select(User).where(User.username==payload.username,User.active==True))
    if not invited or invited.identity!='student':
        raise HTTPException(422,'只能邀请有效的学生账号')
    existing=db.scalar(select(Member).where(Member.project_id==p.id,Member.user_id==invited.id))
    if existing:
        return member_json(db,existing)
    member=Member(project_id=p.id,user_id=invited.id)
    db.add(member)
    bump_revision(db,p)
    audit(db,user.id,p.id,'member',invited.id,'joined')
    db.commit()
    await request.app.state.hub.broadcast(p.id,{'type':'project_changed'})
    return member_json(db,member)


@router.patch('/projects/{project_id}/members/me')
async def update_capacity(project_id:int,payload:Capacity,request:Request,db=Depends(get_db),user=Depends(current_user)):
    p,m=require_project(db,project_id,user,internal=True)
    m.skills=payload.skills
    m.weekly_hours=payload.weekly_hours
    bump_revision(db,p)
    audit(db,user.id,p.id,'member',m.id,'capacity_updated',payload.model_dump())
    db.commit()
    await request.app.state.hub.broadcast(p.id,{'type':'project_changed'})
    return member_json(db,m)
