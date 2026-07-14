"""
Auto-NguLo — FastAPI Application Entry Point
Android Automation Manager running on Termux.
"""
import json
import os
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import HOST, PORT, DEBUG, DATABASE_PATH, TEMPLATE_DIR
from database.connection import init_db, close_db, get_db
from middleware.auth_middleware import AuthMiddleware, get_token_from_request, verify_token
from routers import auth, scripts, actions, executor, device, keyboard
from routers.executor import vars_router

# ---- App Lifespan ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    os.makedirs("data", exist_ok=True)
    await init_db()
    print(f"🚀 Auto-NguLo started on http://{HOST}:{PORT}")
    print(f"   Database: {DATABASE_PATH}")
    yield
    # Shutdown
    await close_db()


# ---- Create App ----
app = FastAPI(
    title="Auto-NguLo",
    description="Android Automation Manager — Remote control your Android device",
    version="1.0.0",
    lifespan=lifespan,
)

# ---- Middleware ----
app.add_middleware(AuthMiddleware)

# ---- Static Files ----
os.makedirs("data/templates", exist_ok=True)
app.mount("/static", StaticFiles(directory="data"), name="static")

# ---- Templates ----
import jinja2
from fastapi.responses import HTMLResponse as HTMLR

_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("templates"),
    auto_reload=True,
)

def render_template(name: str, context: dict) -> HTMLR:
    """Render a Jinja2 template and return HTMLResponse."""
    template = _jinja_env.get_template(name)
    return HTMLR(template.render(**context))

# ---- API Routers ----
app.include_router(auth.router)
app.include_router(scripts.router)
app.include_router(actions.router)
app.include_router(executor.router)
app.include_router(device.router)
app.include_router(keyboard.router)
app.include_router(vars_router)


# ===== PAGE ROUTES =====

@app.get("/favicon.ico")
async def favicon():
    """Favicon — return empty response to prevent 404 noise."""
    return Response(status_code=204)

@app.get("/")
async def login_page(request: Request):
    """Login page."""
    token = get_token_from_request(request)
    if token and verify_token(token):
        return RedirectResponse(url="/dashboard", status_code=302)
    return render_template("login.html", {"request": request, "nav_active": "nologin"})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Dashboard — list all scripts."""
    return render_template("dashboard.html", {"request": request, "title": "Dashboard", "nav_active": "scripts"})


@app.get("/scripts/new", response_class=HTMLResponse)
async def new_script_page(request: Request):
    """Create a new script."""
    return render_template("script_editor.html", {"request": request, "title": "Script Editor"})


@app.get("/scripts/{script_id}/edit", response_class=HTMLResponse)
async def edit_script_page(request: Request, script_id: int):
    """Edit an existing script."""
    return render_template("script_editor.html", {"request": request, "title": "Script Editor", "script_id": script_id})


@app.get("/execute/{script_id}", response_class=HTMLResponse)
async def execute_page(request: Request, script_id: int):
    """Execution page with live log."""
    return render_template("execution.html", {"request": request, "title": "Execution", "script_id": script_id})


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    """Execution history page."""
    return render_template("history.html", {"request": request, "title": "History", "nav_active": "history"})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings page."""
    return render_template("settings.html", {"request": request, "title": "Settings", "nav_active": "settings"})

@app.get("/gallery", response_class=HTMLResponse)
async def gallery_page(request: Request):
    """Template gallery — view, upload, rename, delete template images."""
    return render_template("gallery.html", {"request": request, "title": "Gallery", "nav_active": "gallery"})


@app.get("/variables", response_class=HTMLResponse)
async def variables_page(request: Request):
    """Global variable editor page."""
    return render_template("variables.html", {"request": request, "title": "Variables", "nav_active": "variables"})

@app.get("/keyboard", response_class=HTMLResponse)
async def keyboard_page(request: Request):
    """Keyboard mapping editor page."""
    return render_template("keyboard.html", {"request": request, "title": "Keyboard Mapping", "nav_active": "keyboard"})


@app.get("/logout")
async def logout():
    """Logout — clear cookie and redirect to login."""
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("ngulo_token")
    return response


# ===== UTILITY API ENDPOINTS =====

@app.get("/api/history")
async def get_all_history():
    """Get all execution history across all scripts."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, script_id, script_name, status, success_count, fail_count, total_actions, duration_sec, log_json, started_at, ended_at FROM execution_logs ORDER BY started_at DESC LIMIT 100"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/history")
async def clear_all_history():
    """Clear all execution history."""
    db = await get_db()
    await db.execute("DELETE FROM execution_logs")
    await db.commit()
    return {"message": "All history cleared"}


@app.delete("/api/history/{log_id}")
async def delete_history_entry(log_id: int):
    """Delete a single history entry."""
    db = await get_db()
    await db.execute("DELETE FROM execution_logs WHERE id=?", (log_id,))
    await db.commit()
    return {"message": "Entry deleted"}


# ===== FILE UPLOAD =====

@app.post("/api/upload/template")
async def upload_template(file: UploadFile = File(...)):
    """Upload a template image for screenshot_match actions."""
    allowed = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'}
    ext = os.path.splitext(file.filename or '')[-1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"File type '{ext}' not allowed. Use: {', '.join(sorted(allowed))}")

    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    import time
    safe_name = f"{int(time.time()*1000)}_{file.filename.replace(' ', '_')}"
    file_path = os.path.join(TEMPLATE_DIR, safe_name)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Return path relative to data/ so it can be served as static
    relative_path = f"templates/{safe_name}"
    return {"path": relative_path, "filename": safe_name, "url": f"/static/{relative_path}"}

@app.get("/api/templates")
async def list_template_images():
    """List all template images available on the server."""
    import config
    os.makedirs(config.TEMPLATE_DIR, exist_ok=True)
    files = []
    allowed = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'}
    try:
        for fname in sorted(os.listdir(config.TEMPLATE_DIR)):
            ext = os.path.splitext(fname)[-1].lower()
            if ext in allowed:
                full = os.path.join(config.TEMPLATE_DIR, fname)
                size = os.path.getsize(full)
                mtime = os.path.getmtime(full)
                files.append({
                    "path": f"templates/{fname}",
                    "filename": fname,
                    "url": f"/static/templates/{fname}",
                    "size": size,
                    "mtime": mtime,
                })
    except FileNotFoundError:
        pass
    return {"templates": files}


@app.delete("/api/templates/{filename}")
async def delete_template(filename: str):
    """Delete a template image by filename."""
    import config
    # Sanitize: no path traversal
    safe = os.path.basename(filename)
    file_path = os.path.join(config.TEMPLATE_DIR, safe)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    os.remove(file_path)
    return {"message": f"Deleted {safe}"}


@app.put("/api/templates/{filename}/rename")
async def rename_template(filename: str, request: Request):
    """Rename a template image."""
    import config
    body = await request.json()
    new_name = body.get("new_name", "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name is required")

    allowed = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'}
    new_ext = os.path.splitext(new_name)[-1].lower()
    if new_ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Extension '{new_ext}' not allowed")

    safe_old = os.path.basename(filename)
    safe_new = new_name.replace(" ", "_")
    old_path = os.path.join(config.TEMPLATE_DIR, safe_old)
    new_path = os.path.join(config.TEMPLATE_DIR, safe_new)

    if not os.path.isfile(old_path):
        raise HTTPException(status_code=404, detail="File not found")
    if os.path.exists(new_path):
        raise HTTPException(status_code=409, detail="File with that name already exists")

    os.rename(old_path, new_path)
    return {
        "message": f"Renamed to {safe_new}",
        "filename": safe_new,
        "url": f"/static/templates/{safe_new}",
        "path": f"templates/{safe_new}",
    }

# ---- Run ----
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=DEBUG, log_level="info")
