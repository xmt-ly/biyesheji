from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, update
from ..business import audit, bump_revision
from ..database import get_db
from ..models import Card, Message, Plan, Project, Task, now
from ..permissions import require_project, resource
from ..planning import check_plan
from ..schemas import CardInput, CardPatch, Feedback
from ..security import current_user
from ..serializers import card_json, plan_json, task_json, current_tasks_json

router=APIRouter(prefix='/api',tags=['规划卡片与计划'])


def validate_sources(db,project_id,ids):
    if len(ids)!=len(set(ids)):
        raise HTTPException(422,'消息来源不能重复')
    if ids:
        valid=set(db.scalars(select(Message.id).where(Message.project_id==project_id,Message.id.in_(ids),Message.kind=='human')))
        if valid!=set(ids):
            raise HTTPException(422,'消息来源必须是真实的本项目人类消息')


def refresh_checks(db,project,card):
    card.checks=check_plan(db,project,card.tasks)
    card.status='ready' if card.checks['valid'] and card.tasks and not card.questions else 'pending'


@router.get('/projects/{project_id}/cards')
def list_cards(project_id:int,db=Depends(get_db),user=Depends(current_user)):
    require_project(db,project_id,user,internal=True)
    return [card_json(c) for c in db.scalars(select(Card).where(Card.project_id==project_id).order_by(Card.id))]


@router.post('/projects/{project_id}/cards')
async def create_manual_card(project_id:int,payload:CardInput,request:Request,db=Depends(get_db),user=Depends(current_user)):
    p,_=require_project(db,project_id,user,internal=True)
    validate_sources(db,p.id,payload.source_message_ids)
    card=Card(project_id=p.id,base_revision=p.revision,creator_id=user.id,**payload.model_dump(mode='json'))
    db.add(card)
    refresh_checks(db,p,card)
    db.flush()
    audit(db,user.id,p.id,'card',card.id,'manual_created')
    db.commit()
    await request.app.state.hub.broadcast(p.id,{'type':'cards_changed'})
    return card_json(card)


@router.patch('/cards/{card_id}')
async def update_card(card_id:int,payload:CardPatch,request:Request,db=Depends(get_db),user=Depends(current_user)):
    card=resource(db,Card,card_id)
    p,_=require_project(db,card.project_id,user,internal=True)
    if card.status in ('published','rejected'):
        raise HTTPException(409,'已发布或已拒绝卡片不可直接修改，请新建草案')
    changes=payload.model_dump(mode='json',exclude_unset=True)
    reason=changes.pop('reason','')
    if any(v is None for v in changes.values()):
        raise HTTPException(422,'卡片字段不能设为 null')
    if card.base_revision!=p.revision or card.status=='stale':
        if not reason.strip():
            raise HTTPException(409,'失效草案重新核对需要 reason，确认已按当前项目状态复核')
        card.base_revision=p.revision
    rejected=changes.pop('status',None)=='rejected'
    for k,v in changes.items():
        setattr(card,k,v)
    refresh_checks(db,p,card)
    if rejected:
        card.status='rejected'
    card.feedback=[*[dict(f,confirmed=False,confirmation_invalidated_at=now()) if f.get('confirmed') else f for f in card.feedback],
                   {'user_id':user.id,'author_name':user.name,'content':reason or '修改草案',
                                  'confirmed':False,'created_at':now(),'kind':'edit'}]
    audit(db,user.id,p.id,'card',card.id,'updated',{'changes':changes,'reason':reason})
    db.commit()
    await request.app.state.hub.broadcast(p.id,{'type':'cards_changed'})
    return card_json(card)


@router.post('/cards/{card_id}/feedback')
async def feedback(card_id:int,payload:Feedback,request:Request,db=Depends(get_db),user=Depends(current_user)):
    card=resource(db,Card,card_id)
    p,_=require_project(db,card.project_id,user,internal=True)
    card.feedback=[*card.feedback,dict(payload.model_dump(),user_id=user.id,author_name=user.name,created_at=now(),kind='feedback')]
    audit(db,user.id,p.id,'card',card.id,'feedback',payload.model_dump())
    db.commit()
    await request.app.state.hub.broadcast(p.id,{'type':'cards_changed'})
    return card_json(card)


@router.post('/cards/{card_id}/publish')
async def publish(card_id:int,request:Request,db=Depends(get_db),user=Depends(current_user)):
    card=resource(db,Card,card_id)
    p,_=require_project(db,card.project_id,user,leader=True)
    if card.published_plan_id:
        return plan_json(db.get(Plan,card.published_plan_id))
    if card.status in ('stale','rejected','failed') or card.base_revision!=p.revision:
        raise HTTPException(409,'草案已失效或不可发布，请重新核对')
    if not card.tasks or card.questions:
        raise HTTPException(422,'草案需要完整任务并解决待澄清问题后才能发布')
    validate_sources(db,p.id,card.source_message_ids)
    checks=check_plan(db,p,card.tasks)
    if not checks['valid']:
        raise HTTPException(422,checks)
    # CAS 与全部任务变更、快照在同一数据库事务内。
    result=db.execute(update(Project).where(Project.id==p.id,Project.revision==card.base_revision)
                      .values(revision=Project.revision+1,status='active'))
    if result.rowcount!=1:
        raise HTTPException(409,'项目状态已改变，请重新核对草案')
    changes=[]
    before_by_id={t['id']:t for t in current_tasks_json(db,p.id)}
    key_to_id={f'task_{t.id}':t.id for t in db.scalars(select(Task).where(Task.project_id==p.id))}
    mapped=[]
    for draft in card.tasks:
        data={k:v for k,v in draft.items() if k not in ('key','existing_id','dependencies')}
        if data['status']=='done':
            data.update(progress=100,remaining_hours=0)
        existing_id=draft.get('existing_id')
        if existing_id:
            task=db.get(Task,existing_id)
            before=before_by_id[task.id]
            for k,v in data.items():
                setattr(task,k,v)
            task.updated_at=now()
        else:
            before=None
            task=Task(project_id=p.id,creator_id=user.id,dependencies=[],**data)
            db.add(task)
            db.flush()
        key_to_id[draft['key']]=task.id
        mapped.append((draft,task,before))
    for draft,task,before in mapped:
        task.dependencies=[key_to_id[key] for key in draft['dependencies']]
    db.flush()
    snapshots=current_tasks_json(db,p.id)
    after_by_id={t['id']:t for t in snapshots}
    for draft,task,before in mapped:
        after=after_by_id[task.id]
        changes.append({'task_id':task.id,'action':'updated' if before else 'created','before':before,'after':after})
        audit(db,user.id,p.id,'task',task.id,'plan_published',{'card_id':card.id,'before':before,'after':after})
    version=(db.scalar(select(func.max(Plan.version)).where(Plan.project_id==p.id)) or 0)+1
    plan=Plan(project_id=p.id,version=version,created_by=user.id,summary='组长确认的任务与排期版本',changes=changes,
              tasks=snapshots)
    db.add(plan)
    db.flush()
    card.published_plan_id=plan.id
    card.status='published'
    card.checks=checks
    db.execute(update(Card).where(Card.project_id==p.id,Card.id!=card.id,Card.status.in_(['ready','pending'])).values(status='stale'))
    audit(db,user.id,p.id,'card',card.id,'published',{'plan_id':plan.id})
    db.commit()
    await request.app.state.hub.broadcast(p.id,{'type':'cards_changed'})
    await request.app.state.hub.broadcast(p.id,{'type':'project_changed'})
    return plan_json(plan)


@router.get('/projects/{project_id}/plans')
def list_plans(project_id:int,db=Depends(get_db),user=Depends(current_user)):
    require_project(db,project_id,user)
    return [plan_json(p) for p in db.scalars(select(Plan).where(Plan.project_id==project_id).order_by(Plan.version))]
