"""Scripts CRUD router."""
from fastapi import APIRouter, HTTPException, Request
from database.connection import get_db
from schemas.requests import ScriptCreate, ScriptUpdate

router = APIRouter(prefix="/api/scripts", tags=["scripts"])


def _row_to_dict(row) -> dict:
    if row is None:
        return None
    return dict(row)


async def _get_script_or_404(script_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM scripts WHERE id=?", (script_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Script not found")
    return _row_to_dict(row)


async def _get_actions_for_script(script_id: int) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM actions WHERE script_id=? ORDER BY order_num",
        (script_id,)
    )
    return [_row_to_dict(r) for r in await cursor.fetchall()]


@router.get("")
async def list_scripts():
    db = await get_db()
    cursor = await db.execute("SELECT * FROM scripts ORDER BY updated_at DESC")
    scripts = [_row_to_dict(r) for r in await cursor.fetchall()]
    for s in scripts:
        cursor2 = await db.execute("SELECT COUNT(*) as cnt FROM actions WHERE script_id=?", (s["id"],))
        row = await cursor2.fetchone()
        s["action_count"] = row["cnt"] if row else 0
    return scripts


@router.get("/export")
async def export_all_scripts():
    """Export all scripts with their actions as JSON."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM scripts ORDER BY id")
    scripts = [_row_to_dict(r) for r in await cursor.fetchall()]
    for s in scripts:
        cursor2 = await db.execute(
            "SELECT * FROM actions WHERE script_id=? ORDER BY order_num", (s["id"],)
        )
        s["actions"] = [_row_to_dict(r) for r in await cursor2.fetchall()]
    return scripts

@router.post("/import")
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

@router.get("/{script_id}")
async def get_script(script_id: int):
    script = await _get_script_or_404(script_id)
    script["actions"] = await _get_actions_for_script(script_id)
    return script


@router.post("")
async def create_script(data: ScriptCreate):
    db = await get_db()
    # Check unique name
    cursor_check = await db.execute("SELECT id FROM scripts WHERE name=?", (data.name,))
    if await cursor_check.fetchone():
        raise HTTPException(status_code=409, detail=f"Script name '{data.name}' already exists")
    cursor = await db.execute(
        """INSERT INTO scripts (name, description, repeat_count, delay_between_ms, stop_on_failure)
           VALUES (?, ?, ?, ?, ?)""",
        (data.name, data.description, data.repeat_count, data.delay_between_ms,
         int(data.stop_on_failure))
    )
    await db.commit()
    return await _get_script_or_404(cursor.lastrowid)


@router.put("/{script_id}")
async def update_script(script_id: int, data: ScriptUpdate):
    await _get_script_or_404(script_id)
    db = await get_db()
    updates = {}
    if data.name is not None:
        # Check unique name (exclude current script)
        cursor_check = await db.execute(
            "SELECT id FROM scripts WHERE name=? AND id!=?", (data.name, script_id)
        )
        if await cursor_check.fetchone():
            raise HTTPException(status_code=409, detail=f"Script name '{data.name}' already exists")
        updates["name"] = data.name
    if data.description is not None:
        updates["description"] = data.description
    if data.repeat_count is not None:
        updates["repeat_count"] = data.repeat_count
    if data.delay_between_ms is not None:
        updates["delay_between_ms"] = data.delay_between_ms
    if data.stop_on_failure is not None:
        updates["stop_on_failure"] = int(data.stop_on_failure)
    if updates:
        updates["updated_at"] = "datetime('now')"
        set_clause = ", ".join(f"{k}=?" for k in updates.keys() if k != "updated_at")
        set_clause = ", ".join(f"{k}=?" if k != "updated_at" else f"{k}=datetime('now')" for k in updates.keys())
        # simpler approach:
        set_parts = [f"{k}=?" for k in updates.keys() if k != "updated_at"]
        values = [updates[k] for k in updates.keys() if k != "updated_at"]
        if "updated_at" in updates:
            set_parts.append("updated_at=datetime('now')")
        # Just write it inline:
        set_parts = []
        values = []
        for k, v in updates.items():
            if k == "updated_at":
                set_parts.append("updated_at=datetime('now')")
            else:
                set_parts.append(f"{k}=?")
                values.append(v)
        await db.execute(
            f"UPDATE scripts SET {', '.join(set_parts)} WHERE id=?",
            [*values, script_id]
        )
        await db.commit()
    return await _get_script_or_404(script_id)


@router.delete("/{script_id}")
async def delete_script(script_id: int):
    await _get_script_or_404(script_id)
    db = await get_db()
    await db.execute("DELETE FROM scripts WHERE id=?", (script_id,))
    await db.commit()
    return {"message": "Script deleted"}
