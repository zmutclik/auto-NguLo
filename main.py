"""
Auto-NguLo — FastAPI Application Entry Point
Android Automation Manager running on Termux.
"""
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import HOST, PORT, DEBUG, DATABASE_PATH
from database.connection import init_db, close_db, get_db
from middleware.auth_middleware import auth_middleware, get_token_from_request, verify_token
from routers import auth, scripts, actions, executor, device

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
app.middleware("http")(auth_middleware)

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


# ===== PAGE ROUTES =====

@app.get("/", response_class=HTMLResponse)
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


@app.get("/api/scripts/export")
async def export_all_scripts():
    """Export all scripts with their actions as JSON."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM scripts ORDER BY id")
    scripts = [dict(r) for r in await cursor.fetchall()]
    for s in scripts:
        cursor2 = await db.execute(
            "SELECT * FROM actions WHERE script_id=? ORDER BY order_num", (s["id"],)
        )
        s["actions"] = [dict(r) for r in await cursor2.fetchall()]
    return scripts


@app.post("/api/scripts/import")
async def import_scripts(request: Request):
    """Import scripts from JSON."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="Expected a list of scripts")

    db = await get_db()
    imported = 0
    for script_data in data:
        name = script_data.get("name", "Imported Script")
        desc = script_data.get("description", "")
        repeat = script_data.get("repeat_count", 1)
        delay = script_data.get("delay_between_ms", 1000)

        cursor = await db.execute(
            "INSERT INTO scripts (name, description, repeat_count, delay_between_ms) VALUES (?,?,?,?)",
            (name, desc, repeat, delay)
        )
        new_id = cursor.lastrowid

        for i, action_data in enumerate(script_data.get("actions", [])):
            await db.execute(
                """INSERT INTO actions (script_id, order_num, name, action_type, x, y, x2, y2, duration_ms,
                   template_path, match_threshold, retry_count, retry_delay_ms, jump_on_success, jump_on_fail,
                   key_code, combo_action, api_url, api_method, api_headers, api_body, api_save_to_var,
                   var_name, var_operation, var_value, text_content, text_speed_ms,
                   use_match_result, wait_ms, wait_before_ms, wait_after_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    new_id, i,
                    action_data.get("name", f"action_{i}"),
                    action_data.get("action_type", "wait"),
                    action_data.get("x"), action_data.get("y"),
                    action_data.get("x2"), action_data.get("y2"),
                    action_data.get("duration_ms", 300),
                    action_data.get("template_path", ""),
                    action_data.get("match_threshold", 0.80),
                    action_data.get("retry_count", 1),
                    action_data.get("retry_delay_ms", 1000),
                    action_data.get("jump_on_success", ""),
                    action_data.get("jump_on_fail", ""),
                    action_data.get("key_code", "HOME"),
                    action_data.get("combo_action", "select_all"),
                    action_data.get("api_url", ""),
                    action_data.get("api_method", "GET"),
                    action_data.get("api_headers", "{}"),
                    action_data.get("api_body", ""),
                    action_data.get("api_save_to_var", ""),
                    action_data.get("var_name", ""),
                    action_data.get("var_operation", "set"),
                    action_data.get("var_value", ""),
                    action_data.get("text_content", ""),
                    action_data.get("text_speed_ms", 50),
                    action_data.get("use_match_result", 0),
                    action_data.get("wait_ms", 1000),
                    action_data.get("wait_before_ms", 500),
                    action_data.get("wait_after_ms", 500),
                )
            )
        imported += 1

    await db.commit()
    return {"message": f"Imported {imported} scripts"}


# ---- Run ----
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=DEBUG, log_level="info")
