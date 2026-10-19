from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from ..database import get_db
from ..models import AgentRun
from ..permissions import require_project
from ..schemas import Analyze
from ..security import current_user

router=APIRouter(prefix='/api',tags=['Agent'])


@router.post('/projects/{project_id}/agent/analyze',status_code=202)
async def analyze(project_id:int,payload:Analyze,request:Request,db=Depends(get_db),user=Depends(current_user)):
    require_project(db,project_id,user,internal=True)
    if not request.app.state.agent.ready:
        raise HTTPException(503,'AI 尚未配置，请在服务端配置 LLM_API_KEY、LLM_MODEL 和兼容接口地址')
    request.app.state.agent.enqueue(db,project_id,payload.mode,requested=True)
    db.commit()
    request.app.state.agent.wake(project_id)
    return {'status':'queued','mode':payload.mode}


@router.get('/projects/{project_id}/agent/runs')
def runs(project_id:int,db=Depends(get_db),user=Depends(current_user)):
    require_project(db,project_id,user,internal=True)
    return [{'id':r.id,'project_id':r.project_id,'base_revision':r.base_revision,'source_message_ids':r.source_message_ids,
             'mode':r.mode,'intent_ids':r.intent_ids,
             'model':r.model,'prompt_version':r.prompt_version,'status':r.status,'error':r.error,'elapsed_ms':r.elapsed_ms,
             'tokens':r.tokens,'tool_results':r.tool_results,'created_at':r.created_at}
            for r in db.scalars(select(AgentRun).where(AgentRun.project_id==project_id).order_by(AgentRun.id.desc()).limit(50))]
