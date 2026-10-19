import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from .agent import AgentManager
from .config import ROOT, Settings
from .database import Database
from .realtime import Hub
from .routers import auth, cards, courses, files, messages, projects, requirements, submissions, tasks, agent


class TokenRedactionFilter(logging.Filter):
    def filter(self,record):
        message=record.getMessage()
        if 'token=' in message:
            record.msg=re.sub(r'(token=)[^&\s\"\']+',r'\1[redacted]',message)
            record.args=()
        return True


def create_app(settings=None,provider=None):
    settings=(settings or Settings()).prepare()
    database=Database(settings.database_url)
    hub=Hub(database,settings)
    manager=AgentManager(database,settings,hub,provider)

    @asynccontextmanager
    async def lifespan(app):
        database.create_tables()
        await manager.recover()
        try:
            yield
        finally:
            await manager.close()
            await hub.close()
            database.engine.dispose()

    application=FastAPI(title='课程项目智能协作系统',version='1.0.0',lifespan=lifespan)
    application.state.settings=settings
    application.state.db=database
    application.state.hub=hub
    application.state.agent=manager
    @application.exception_handler(RequestValidationError)
    async def invalid_request(request,error):
        # 不回显 password、凭据或 NaN 等不可安全序列化的原始输入。
        return JSONResponse(status_code=422,content={'detail':[{'loc':list(e['loc']),
                            'msg':'字段格式或取值不符合要求','type':e['type']} for e in error.errors()]})
    application.add_middleware(CORSMiddleware,allow_origins=settings.cors_origins,allow_credentials=False,
                               allow_methods=['*'],allow_headers=['Authorization','Content-Type'])
    for route in (auth,courses,projects,requirements,tasks,messages,cards,submissions,files,agent):
        application.include_router(route.router)
    for name in ('uvicorn.access','uvicorn.error'):
        logging.getLogger(name).addFilter(TokenRedactionFilter())
    dist=ROOT/'frontend'/'dist'
    if dist.is_dir():
        if (dist/'assets').is_dir():
            application.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')

        @application.get('/{path:path}',include_in_schema=False)
        def frontend(path:str):
            if path=='api' or path.startswith('api/'):
                raise HTTPException(404,'API 不存在')
            target=(dist/path).resolve()
            if target.is_relative_to(dist.resolve()) and target.is_file():
                return FileResponse(target)
            return FileResponse(dist/'index.html')
    return application


app=create_app()
