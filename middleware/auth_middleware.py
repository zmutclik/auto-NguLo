"""
Simple password-based JWT auth for Auto-NguLo.
No username needed — just a single password for the entire app.
"""
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Request, HTTPException, status
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
    """Middleware that protects routes except login and static files."""
    # Public paths
    public_prefixes = ("/api/auth/login", "/static", "/favicon.ico")
    if any(request.url.path.startswith(p) for p in public_prefixes):
        return await call_next(request)

    # Allow unauthenticated access to login page and static
    if request.url.path in ("/", "/login", ""):
        return await call_next(request)

    # Check API routes
    if request.url.path.startswith("/api/"):
        token = get_token_from_request(request)
        if not token or not verify_token(token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )

    # Check page routes — redirect to login if no token
    if not request.url.path.startswith("/api/"):
        token = get_token_from_request(request)
        if not token or not verify_token(token):
            return RedirectResponse(url="/", status_code=302)

    return await call_next(request)
