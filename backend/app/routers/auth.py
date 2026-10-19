from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from ..database import get_db
from ..models import User
from ..schemas import Login
from ..security import current_user, make_token, user_json, verify_password

router=APIRouter(prefix='/api',tags=['认证与状态'])


@router.post('/auth/login')
def login(payload:Login,request:Request,db=Depends(get_db)):
    user=db.scalar(select(User).where(User.username==payload.username))
    if not user or not user.active or not verify_password(payload.password,user.password_hash):
        raise HTTPException(401,'用户名或密码错误')
    return {'access_token':make_token(user,request.app.state.settings),'token_type':'bearer','user':user_json(user)}


@router.get('/auth/me')
def me(user=Depends(current_user)):
    return user_json(user)


@router.get('/health')
def health():
    return {'status':'ok'}


@router.get('/config/status')
def config_status(request:Request,db=Depends(get_db),user=Depends(current_user)):
    return {'ai_ready':request.app.state.agent.ready,'ai_status':'ready' if request.app.state.agent.ready else 'not_configured',
            'storage':'sqlite','realtime':'single_process',
            'demo_data':db.scalar(select(User.id).where(User.username=='teacher',User.name=='演示教师')) is not None}
