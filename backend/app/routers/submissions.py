from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from ..business import audit, progress_snapshot
from ..database import get_db
from ..models import Course, Plan, StoredFile, Submission, now
from ..permissions import require_project, require_teacher, resource
from ..schemas import ReviewInput, SubmissionInput
from ..security import current_user
from ..serializers import submission_json

router=APIRouter(prefix='/api',tags=['阶段提交与审核'])


@router.get('/projects/{project_id}/submissions')
def list_submissions(project_id:int,db=Depends(get_db),user=Depends(current_user)):
    require_project(db,project_id,user)
    return [submission_json(s) for s in db.scalars(select(Submission).where(Submission.project_id==project_id).order_by(Submission.id))]


@router.post('/projects/{project_id}/submissions')
async def submit(project_id:int,payload:SubmissionInput,request:Request,db=Depends(get_db),user=Depends(current_user)):
    p,_=require_project(db,project_id,user,leader=True)
    course=db.get(Course,p.course_id)
    if len(course.stages)!=3:
        raise HTTPException(422,'课程尚未设置完整的三个阶段')
    if not payload.artifact_urls and not payload.file_ids:
        raise HTTPException(422,'阶段材料缺失：至少提供一个成果链接或上传文件')
    valid=set(db.scalars(select(StoredFile.id).where(StoredFile.project_id==p.id,StoredFile.id.in_(payload.file_ids)))) if payload.file_ids else set()
    if valid!=set(payload.file_ids):
        raise HTTPException(422,'附件必须属于当前项目')
    deliverables=course.stages[payload.stage_index]['deliverables']
    if payload.materials:
        missing=[d for d in deliverables if not payload.materials.get(d)]
        if missing:
            raise HTTPException(422,{'message':'缺少课程要求材料','missing':missing})
        provided=set(payload.artifact_urls)|{f'file:{i}' for i in payload.file_ids}
        if any(ref not in provided for refs in payload.materials.values() for ref in refs):
            raise HTTPException(422,'materials 引用只能来自本次成果链接或 file:<id>')
    elif len(deliverables)>1:
        raise HTTPException(422,{'message':'请用 materials 将材料映射到各项交付物','required':deliverables})
    version=(db.scalar(select(func.max(Submission.version)).where(Submission.project_id==p.id,Submission.stage_index==payload.stage_index)) or 0)+1
    plan_version=db.scalar(select(func.max(Plan.version)).where(Plan.project_id==p.id))
    data=payload.model_dump()
    if not data['materials'] and len(deliverables)==1:
        data['materials']={deliverables[0]:[*payload.artifact_urls,*[f'file:{i}' for i in payload.file_ids]]}
    sub=Submission(project_id=p.id,version=version,created_by=user.id,plan_version=plan_version,
                   progress_snapshot=progress_snapshot(db,p.id),**data)
    db.add(sub)
    db.flush()
    audit(db,user.id,p.id,'submission',sub.id,'submitted',{'stage_index':payload.stage_index,'version':version,'course_version':course.version})
    db.commit()
    await request.app.state.hub.broadcast(p.id,{'type':'project_changed'})
    return submission_json(sub)


@router.post('/submissions/{submission_id}/review')
async def review(submission_id:int,payload:ReviewInput,request:Request,db=Depends(get_db),user=Depends(current_user)):
    require_teacher(user)
    sub=resource(db,Submission,submission_id)
    p,_=require_project(db,sub.project_id,user)
    sub.reviews=[*sub.reviews,{'reviewer_id':user.id,'reviewer_name':user.name,'result':payload.result,
                              'comment':payload.comment,'created_at':now()}]
    sub.status=payload.result
    audit(db,user.id,p.id,'submission',sub.id,'reviewed',payload.model_dump())
    db.commit()
    await request.app.state.hub.broadcast(p.id,{'type':'project_changed'})
    return submission_json(sub)
