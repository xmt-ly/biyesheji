import asyncio
from fastapi import HTTPException
from .security import decode_user
from .permissions import require_project


class Hub:
    """单进程广播。每次广播按最新成员关系及令牌有效期复核。"""
    def __init__(self,db,settings):
        self.db=db
        self.settings=settings
        self.sockets={}

    async def connect(self,project_id,websocket,token):
        with self.db.Session() as db:
            user=decode_user(token,self.settings,db)
            require_project(db,project_id,user,internal=True)
        await websocket.accept()
        self.sockets[websocket]=(project_id,token)

    def disconnect(self,websocket):
        self.sockets.pop(websocket,None)

    def authorize(self,websocket):
        project_id,token=self.sockets[websocket]
        with self.db.Session() as db:
            user=decode_user(token,self.settings,db)
            require_project(db,project_id,user,internal=True)

    async def broadcast(self,project_id,event):
        for socket,(pid,_) in list(self.sockets.items()):
            if pid!=project_id:
                continue
            try:
                self.authorize(socket)
                await asyncio.wait_for(socket.send_json(event),timeout=2)
            except (Exception, asyncio.TimeoutError):
                self.disconnect(socket)
                try:
                    await socket.close(code=1008)
                except Exception:
                    pass

    async def close(self):
        for socket in list(self.sockets):
            try:
                await socket.close(code=1001)
            except Exception:
                pass
        self.sockets.clear()
