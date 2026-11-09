from datetime import UTC, datetime, timedelta

import jwt
from passlib.context import CryptContext

from app.config import settings


# bcrypt 5.x changed internals in a way that causes runtime failures with passlib's bcrypt handler.
# pbkdf2_sha256 is stable across environments and suitable for password storage here.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(raw_password: str) -> str:
    return pwd_context.hash(raw_password)


def verify_password(raw_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(raw_password, hashed_password)


def create_access_token(user_id: int) -> str:
    expires_at = datetime.now(UTC) + timedelta(hours=settings.token_exp_hours)
    payload = {"sub": str(user_id), "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    sub = payload.get("sub")
    if not sub:
        raise jwt.InvalidTokenError("Token is missing sub.")

    return int(sub)
