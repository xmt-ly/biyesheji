from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ..database import get_db
from ..models import Card, Message, Requirement, Task, now
from ..permissions import require_project, resource
from ..schemas import MessageInput
from ..security import current_user
from ..serializers import message_json
from ..config import MAX_SQL_ID

router=APIRouter(prefix='/api',tags=['聊天室'])


@router.get('/projects/{project_id}/messages')
def list_messages(project_id:int,after_id:int=Query(default=0,ge=0,le=MAX_SQL_ID),limit:int=Query(default=200,ge=1,le=500),db=Depends(get_db),user=Depends(current_user)):
    require_project(db,project_id,user,internal=True)
    return [message_json(db,m) for m in db.scalars(select(Message).where(Message.project_id==project_id,Message.id>after_id).order_by(Message.id).limit(limit))]


@router.post('/projects/{project_id}/messages')
async def send(project_id:int,payload:MessageInput,request:Request,db=Depends(get_db),user=Depends(current_user)):
    p,_=require_project(db,project_id,user,internal=True)
    previous=db.scalar(select(Message).where(Message.project_id==p.id,Message.user_id==user.id,Message.client_id==payload.client_id))
    if previous:
        return message_json(db,previous)
    if bool(payload.related_type)!=bool(payload.related_id):
        raise HTTPException(422,'related_type 与 related_id 必须同时填写')
    if payload.related_type:
        model={'task':Task,'requirement':Requirement,'card':Card}[payload.related_type]
        related=db.get(model,payload.related_id)
        if not related or related.project_id!=p.id:
            raise HTTPException(422,'消息关联对象必须属于当前项目')
    superseded=[]
    for cid in payload.supersedes_card_ids:
        old=db.get(Card,cid)
        if not old or old.project_id!=p.id:
            raise HTTPException(422,'更正卡片必须属于当前项目')
        if old.status not in ('published','rejected'):
            old.status='stale'
        superseded.append(cid)
    msg=Message(project_id=p.id,user_id=user.id,content=payload.content,client_id=payload.client_id,
                related_type=payload.related_type,related_id=payload.related_id,supersedes_card_ids=superseded)
    db.add(msg)
    try:
        db.flush()
        for cid in superseded:
            old=db.get(Card,cid)
            old.feedback=[*old.feedback,{'user_id':user.id,'author_name':user.name,'kind':'correction',
                                        'content':'后续消息更正了此建议','confirmed':False,'source_message_id':msg.id,'created_at':now()}]
        request.app.state.agent.enqueue(db,p.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing=db.scalar(select(Message).where(Message.project_id==p.id,Message.user_id==user.id,Message.client_id==payload.client_id))
        if existing:
            return message_json(db,existing)
        raise
    data=message_json(db,msg)
    request.app.state.agent.wake(p.id)
    await request.app.state.hub.broadcast(p.id,{'type':'message','message':data})
    if superseded:
        await request.app.state.hub.broadcast(p.id,{'type':'cards_changed'})
    return data


@router.websocket('/projects/{project_id}/ws')
async def websocket_endpoint(websocket:WebSocket,project_id:int,token:str|None=None):
    hub=websocket.app.state.hub
    try:
        if not token:
            raise HTTPException(401,'请先登录')
        await hub.connect(project_id,websocket,token)
        while True:
            data=await websocket.receive_json()
            hub.authorize(websocket)
            if isinstance(data,dict) and data.get('type')=='ping':
                await websocket.send_json({'type':'pong'})
            else:
                await websocket.send_json({'type':'error','message':'使用 HTTP 消息接口发送，WebSocket 用于接收事件'})
    except HTTPException:
        await websocket.close(code=1008)
    except (WebSocketDisconnect,ValueError,KeyError):
        pass
    finally:
        hub.disconnect(websocket)
