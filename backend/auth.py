from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, Dict, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from .settings import (
    ACCESS_TOKEN_EXPIRE_SEC,
    AUTH_ALGORITHM,
    AUTH_SECRET_KEY,
    REFRESH_TOKEN_EXPIRE_SEC,
)

# Use pbkdf2_sha256 to avoid bcrypt backend issues on Windows.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user_id: int, username: str) -> Dict[str, Any]:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "username": username,
        "type": "access",
        "iat": now,
        "exp": now + ACCESS_TOKEN_EXPIRE_SEC,
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, AUTH_SECRET_KEY, algorithm=AUTH_ALGORITHM)
    return {"token": token, "expires_in": ACCESS_TOKEN_EXPIRE_SEC}


def create_refresh_token(user_id: int, username: str) -> Dict[str, Any]:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "username": username,
        "type": "refresh",
        "iat": now,
        "exp": now + REFRESH_TOKEN_EXPIRE_SEC,
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, AUTH_SECRET_KEY, algorithm=AUTH_ALGORITHM)
    return {"token": token, "expires_in": REFRESH_TOKEN_EXPIRE_SEC}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
    except JWTError:
        return None


def decode_token_unverified(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.get_unverified_claims(token)
    except Exception:
        return None
