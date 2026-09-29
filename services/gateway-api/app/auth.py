"""JWT auth: a /token endpoint plus a dependency that guards REST/WS routes.

Traefik sits in front of this for TLS + rate limiting; this module is the
application-level auth boundary the gateway itself enforces.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Hashed once at import time so the demo password is never stored in plaintext.
_DEMO_HASH = pwd_context.hash(settings.demo_password)


def authenticate(username: str, password: str) -> bool:
    return username == settings.demo_username and pwd_context.verify(password, _DEMO_HASH)


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        subject = payload.get("sub")
        if subject is None:
            raise JWTError("missing subject")
        return subject
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def current_user(token: str = Depends(oauth2_scheme)) -> str:
    return decode_token(token)


def login_for_token(form: OAuth2PasswordRequestForm) -> str:
    if not authenticate(form.username, form.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    return create_access_token(form.username)
