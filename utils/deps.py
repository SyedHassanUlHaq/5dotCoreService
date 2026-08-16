from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from utils.jwt import decode_access_token
from utils.errors import AppError

bearer = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        raise AppError("UNAUTHORIZED", "Invalid or expired token.", 401)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AppError("UNAUTHORIZED", "User not found.", 401)
    if not user.is_active:
        raise AppError("ACCOUNT_DEACTIVATED", "This account has been deactivated.", 403)
    return user
