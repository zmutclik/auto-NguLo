"""Auth router — password-only login, change password."""
from fastapi import APIRouter, HTTPException, Response, Request
from fastapi.responses import JSONResponse
from database.connection import get_db
from middleware.auth_middleware import create_token, verify_token, get_token_from_request
from schemas.requests import LoginRequest, PasswordUpdateRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_MAX_AGE = 86400  # 24 hours


@router.post("/login")
async def login(req: LoginRequest, response: Response):
    """Login with just a password. Returns JWT token."""
    db = await get_db()
    cursor = await db.execute("SELECT value FROM config WHERE key='password'")
    row = await cursor.fetchone()
    stored_password = row["value"] if row else "123456"

    if req.password != stored_password:
        raise HTTPException(status_code=401, detail="Password salah!")

    token = create_token(stored_password)
    response.set_cookie(
        key="ngulo_token",
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return {"token": token, "message": "Login successful"}


@router.put("/password")
async def update_password(data: PasswordUpdateRequest, request: Request):
    """Change the app password."""
    db = await get_db()
    cursor = await db.execute("SELECT value FROM config WHERE key='password'")
    row = await cursor.fetchone()
    stored_password = row["value"] if row else "123456"

    if data.current_password != stored_password:
        raise HTTPException(status_code=400, detail="Password saat ini salah!")

    if len(data.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password baru minimal 4 karakter!")

    await db.execute("UPDATE config SET value=? WHERE key='password'", (data.new_password,))
    await db.commit()

    # Issue new token with new password
    new_token = create_token(data.new_password)
    response = JSONResponse({"message": "Password berhasil diperbarui!"})
    response.set_cookie(
        key="ngulo_token",
        value=new_token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/check")
async def check_auth(request: Request):
    """Check if the current user is authenticated."""
    token = get_token_from_request(request)
    if not token or not verify_token(token):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"authenticated": True}
