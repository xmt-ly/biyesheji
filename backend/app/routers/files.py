import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from ..business import audit
from ..database import get_db
from ..models import StoredFile, Submission
from ..permissions import require_project, resource
from ..security import current_user
from ..serializers import file_json

router=APIRouter(prefix='/api',tags=['附件'])
ALLOWED={'.txt','.md','.pdf','.docx','.xlsx','.csv','.png','.jpg','.jpeg','.webp','.zip','.py','.js','.html','.css','.json','.pptx'}


@router.get('/projects/{project_id}/files')
def list_files(project_id:int,db=Depends(get_db),user=Depends(current_user)):
    require_project(db,project_id,user,internal=True)
    return [file_json(f) for f in db.scalars(select(StoredFile).where(StoredFile.project_id==project_id).order_by(StoredFile.id))]


@router.post('/projects/{project_id}/files')
async def upload(project_id:int,request:Request,file:UploadFile=File(...),db=Depends(get_db),user=Depends(current_user)):
    p,_=require_project(db,project_id,user,internal=True)
    original=Path((file.filename or 'file').replace('\\','/')).name
    if len(original)>200 or '\x00' in original:
        raise HTTPException(422,'文件名无效或过长')
    suffix=Path(original).suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(422,'文件类型不支持，请上传文档、图片、源文件或 zip')
    settings=request.app.state.settings
    storage_name=uuid.uuid4().hex+suffix
    target=settings.data_dir/'files'/storage_name
    size=0
    try:
        with target.open('xb') as stream:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>settings.max_upload_bytes:
                    raise HTTPException(413,'附件不得超过 20 MiB')
                stream.write(chunk)
        if not size:
            raise HTTPException(422,'不能上传空文件')
        stored=StoredFile(project_id=p.id,user_id=user.id,filename=original,storage_name=storage_name,
                          content_type=file.content_type or 'application/octet-stream',size=size)
        db.add(stored)
        db.flush()
        audit(db,user.id,p.id,'file',stored.id,'uploaded',{'filename':original,'size':size})
        db.commit()
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return file_json(stored)


@router.get('/files/{file_id}/metadata')
def metadata(file_id:int,db=Depends(get_db),user=Depends(current_user)):
    stored=resource(db,StoredFile,file_id)
    authorize_file(db,stored,user)
    return file_json(stored)


def authorize_file(db,stored,user):
    require_project(db,stored.project_id,user)
    if user.identity=='teacher':
        submitted=any(stored.id in s.file_ids for s in db.scalars(select(Submission).where(Submission.project_id==stored.project_id)))
        if not submitted:
            raise HTTPException(403,'教师只能下载已关联阶段提交的材料')


@router.get('/files/{file_id}')
def download(file_id:int,request:Request,db=Depends(get_db),user=Depends(current_user)):
    stored=resource(db,StoredFile,file_id)
    authorize_file(db,stored,user)
    directory=(request.app.state.settings.data_dir/'files').resolve()
    target=(directory/stored.storage_name).resolve()
    if target.parent!=directory or not target.is_file():
        raise HTTPException(404,'附件不存在')
    return FileResponse(target,filename=stored.filename,media_type='application/octet-stream',
                        headers={'X-Content-Type-Options':'nosniff'})
