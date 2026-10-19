import base64
import hashlib
import hmac
import secrets
import re
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from .database import get_db
from .models import User
from .config import MAX_SQL_ID

bearer = HTTPBearer(auto_error=False)


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 310000)
    return 'pbkdf2$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(digest).decode()


def verify_password(password, value):
    try:
        _, salt, expected = value.split('$')
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), base64.b64decode(salt), 310000)
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def make_token(user, settings):
    return jwt.encode({'sub': str(user.id), 'iat': datetime.now(timezone.utc),
                       'exp': datetime.now(timezone.utc) + timedelta(hours=settings.token_hours)},
                      settings.jwt_secret, algorithm='HS256')


def decode_user(token, settings, db):
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=['HS256'], options={'require':['exp','sub']})
        subject=claims['sub']
        if not isinstance(subject,str) or not re.fullmatch(r'[1-9][0-9]{0,18}',subject) or int(subject)>MAX_SQL_ID:
            raise ValueError('无效的用户 ID')
        user = db.get(User, int(subject))
    except (jwt.PyJWTError, ValueError, TypeError):
        user = None
    if not user or not user.active:
        raise HTTPException(401, '登录已失效，请重新登录')
    return user


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(get_db)):
    if not credentials:
        raise HTTPException(401, '请先登录', headers={'WWW-Authenticate':'Bearer'})
    return decode_user(credentials.credentials, request.app.state.settings, db)


def user_json(user):
    return {'id':user.id,'username':user.username,'name':user.name,'identity':user.identity}
