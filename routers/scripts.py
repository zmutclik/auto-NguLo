"""Scripts CRUD router."""
from fastapi import APIRouter, HTTPException
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


@router.get("/{script_id}")
async def get_script(script_id: int):
    script = await _get_script_or_404(script_id)
    script["actions"] = await _get_actions_for_script(script_id)
    return script


@router.post("")
async def create_script(data: ScriptCreate):
    db = await get_db()
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
