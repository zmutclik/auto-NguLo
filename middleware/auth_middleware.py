"""
Simple password-based JWT auth for Auto-NguLo.
No username needed — just a single password for the entire app.
"""
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Request
from fastapi.responses import RedirectResponse
from config import SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_MINUTES


def create_token(password_hash: str) -> str:
    """Create a JWT token that encodes the password hash as subject."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {
        "sub": "admin",
        "pwd": password_hash,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> str | None:
    """Verify a JWT token. Returns the stored password hash or None."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload.get("pwd")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_token_from_request(request: Request) -> str | None:
    """Extract JWT token from cookie or Authorization header."""
    # Check cookie first
    token = request.cookies.get("ngulo_token")
    if token:
        return token
    # Check Authorization header
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


async def auth_middleware(request: Request, call_next):
    """Middleware that protects routes except login, logout and static files."""
    # Public paths — no auth required
    public_paths = (
        "/api/auth/login",
        "/static",
        "/favicon.ico",
        "/",
        "/login",
    )
    if any(request.url.path == p or request.url.path.startswith(p + "/") or
           request.url.path == p.rstrip("/") for p in public_paths):
        return await call_next(request)

    token = get_token_from_request(request)
    if not token or not verify_token(token):
        # API routes → 401 JSON
        if request.url.path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )
        # Page routes → redirect to login
        return RedirectResponse(url="/", status_code=302)

    return await call_next(request)
