from dotenv import load_dotenv
load_dotenv()

import hmac
import os
from datetime import datetime, timedelta

from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

SECRET_KEY = os.environ.get("JWT_SECRET", "change-me-in-production")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "password")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

# The insecure defaults we ship for local dev — flagged loudly at startup.
_DEFAULT_SECRET = "change-me-in-production"
_DEFAULT_PASSWORD = "password"

security = HTTPBearer()


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> str | None:
    """Return the username for a valid token, or None. Non-raising — for contexts
    (like the WebSocket handshake) where FastAPI's Depends isn't available."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def verify_credentials(username: str, password: str) -> bool:
    """Constant-time credential check (avoids leaking length/prefix via timing)."""
    u_ok = hmac.compare_digest(username.encode(), ADMIN_USERNAME.encode())
    p_ok = hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())
    return u_ok and p_ok


def security_warnings() -> list[str]:
    """Insecure-config warnings to surface at startup."""
    warns = []
    if SECRET_KEY == _DEFAULT_SECRET:
        warns.append("JWT_SECRET is the insecure default — set a strong random JWT_SECRET.")
    if ADMIN_PASSWORD == _DEFAULT_PASSWORD:
        warns.append("ADMIN_PASSWORD is the insecure default — set a strong ADMIN_PASSWORD.")
    return warns


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")