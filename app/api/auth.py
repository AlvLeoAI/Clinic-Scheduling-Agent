import hashlib
import re

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import ChatSession
from app.db.session import get_db

bearer = HTTPBearer(auto_error=False)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def require_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> ChatSession:
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or re.fullmatch(r"[A-Za-z0-9_-]{43}", credentials.credentials) is None
    ):
        raise ApiError(401, "UNAUTHORIZED", "A valid session bearer is required.")
    session = db.scalar(
        select(ChatSession).where(
            ChatSession.token_hash == token_hash(credentials.credentials),
            ChatSession.expires_at > request.app.state.clock(),
        )
    )
    if session is None:
        raise ApiError(401, "UNAUTHORIZED", "A valid session bearer is required.")
    return session
