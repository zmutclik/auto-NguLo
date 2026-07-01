"""Actions CRUD router — nested under scripts."""
from fastapi import APIRouter, HTTPException
from database.connection import get_db
from schemas.requests import ActionCreate, ActionUpdate, ActionReorderRequest

router = APIRouter(prefix="/api/scripts/{script_id}/actions", tags=["actions"])


def _row_to_dict(row) -> dict:
    if row is None: return None
    return dict(row)


async def _script_exists(script_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT id FROM scripts WHERE id=?", (script_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Script not found")


async def _get_next_order(script_id: int) -> int:
    db = await get_db()
    cursor = await db.execute(
        "SELECT COALESCE(MAX(order_num), -1) + 1 AS nxt FROM actions WHERE script_id=?",
        (script_id,)
    )
    row = await cursor.fetchone()
    return row["nxt"] if row else 0


@router.get("")
async def list_actions(script_id: int):
    await _script_exists(script_id)
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM actions WHERE script_id=? ORDER BY order_num",
        (script_id,)
    )
    return [_row_to_dict(r) for r in await cursor.fetchall()]


@router.post("")
async def create_action(script_id: int, data: ActionCreate):
    await _script_exists(script_id)
    db = await get_db()
    order = await _get_next_order(script_id)
    cursor = await db.execute(
        """INSERT INTO actions (
            script_id, order_num, name, action_type,
            x, y, x2, y2, duration_ms,
            template_path, template_path2, match_threshold, retry_count, retry_delay_ms,
            jump_on_success, jump_on_fail,
            match_region_x, match_region_y, match_region_w, match_region_h, match_region_screen,
            key_code, combo_action,
            api_url, api_method, api_headers, api_body, api_save_to_var,
            var_name, var_operation, var_value,
            text_content, text_speed_ms,
            jump_to,
            condition_var, condition_op, condition_value, jump_on_true, jump_on_false,
            orientation_value,
            app_package,
            call_script_name, goto_script_name,            toast_message, toast_duration,            use_match_result, wait_ms, wait_before_ms, wait_after_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            script_id, order, data.name, data.action_type,
            data.x, data.y, data.x2, data.y2, data.duration_ms,
            data.template_path, data.template_path2, data.match_threshold, data.retry_count, data.retry_delay_ms,
            data.jump_on_success, data.jump_on_fail,
            data.match_region_x, data.match_region_y, data.match_region_w, data.match_region_h, data.match_region_screen,
            data.key_code, data.combo_action,
            data.api_url, data.api_method, data.api_headers, data.api_body, data.api_save_to_var,
            data.var_name, data.var_operation, data.var_value,
            data.text_content, data.text_speed_ms,
            data.jump_to,
            data.condition_var, data.condition_op, data.condition_value, data.jump_on_true, data.jump_on_false,
            data.orientation_value,
            data.app_package,
            data.call_script_name, data.goto_script_name,
            data.toast_message, data.toast_duration,
            int(data.use_match_result), data.wait_ms, data.wait_before_ms, data.wait_after_ms,
        )
    )
    await db.commit()
    return _row_to_dict(await (await db.execute("SELECT * FROM actions WHERE id=?", (cursor.lastrowid,))).fetchone())


@router.get("/{action_id}")
async def get_action(script_id: int, action_id: int):
    await _script_exists(script_id)
    db = await get_db()
    cursor = await db.execute("SELECT * FROM actions WHERE id=? AND script_id=?", (action_id, script_id))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Action not found")
    return _row_to_dict(row)


@router.put("/{action_id}")
async def update_action(script_id: int, action_id: int, data: ActionUpdate):
    await _script_exists(script_id)
    db = await get_db()
    cursor = await db.execute("SELECT * FROM actions WHERE id=? AND script_id=?", (action_id, script_id))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Action not found")

    field_map = {
        "name": data.name, "action_type": data.action_type,
        "x": data.x, "y": data.y, "x2": data.x2, "y2": data.y2,
        "duration_ms": data.duration_ms,
        "template_path": data.template_path, "template_path2": data.template_path2,
        "match_threshold": data.match_threshold,
        "retry_count": data.retry_count, "retry_delay_ms": data.retry_delay_ms,
        "jump_on_success": data.jump_on_success, "jump_on_fail": data.jump_on_fail,
        "match_region_x": data.match_region_x, "match_region_y": data.match_region_y,
        "match_region_w": data.match_region_w, "match_region_h": data.match_region_h,
        "match_region_screen": data.match_region_screen,
        "key_code": data.key_code, "combo_action": data.combo_action,
        "api_url": data.api_url, "api_method": data.api_method,
        "api_headers": data.api_headers, "api_body": data.api_body,
        "api_save_to_var": data.api_save_to_var,
        "var_name": data.var_name, "var_operation": data.var_operation,
        "var_value": data.var_value,
        "text_content": data.text_content, "text_speed_ms": data.text_speed_ms,
        "jump_to": data.jump_to,
        "condition_var": data.condition_var, "condition_op": data.condition_op,
        "condition_value": data.condition_value,
        "jump_on_true": data.jump_on_true, "jump_on_false": data.jump_on_false,
        "orientation_value": data.orientation_value,
        "app_package": data.app_package,
        "call_script_name": data.call_script_name,
        "goto_script_name": data.goto_script_name,
        "toast_message": data.toast_message, "toast_duration": data.toast_duration,
        "use_match_result": int(data.use_match_result) if data.use_match_result is not None else None,
        "wait_ms": data.wait_ms, "wait_before_ms": data.wait_before_ms,
        "wait_after_ms": data.wait_after_ms,
    }

    set_parts = []
    values = []
    for col, val in field_map.items():
        if val is not None:
            set_parts.append(f"{col}=?")
            values.append(val)

    if set_parts:
        await db.execute(
            f"UPDATE actions SET {', '.join(set_parts)} WHERE id=?",
            [*values, action_id]
        )
        await db.commit()

    cursor = await db.execute("SELECT * FROM actions WHERE id=?", (action_id,))
    return _row_to_dict(await cursor.fetchone())


@router.delete("/{action_id}")
async def delete_action(script_id: int, action_id: int):
    await _script_exists(script_id)
    db = await get_db()
    await db.execute("DELETE FROM actions WHERE id=? AND script_id=?", (action_id, script_id))
    # Reorder remaining
    remaining = await (await db.execute(
        "SELECT id FROM actions WHERE script_id=? ORDER BY order_num", (script_id,)
    )).fetchall()
    for i, row in enumerate(remaining):
        await db.execute("UPDATE actions SET order_num=? WHERE id=?", (i, row["id"]))
    await db.commit()
    return {"message": "Action deleted"}


@router.put("/reorder/apply")
async def reorder_actions(script_id: int, data: ActionReorderRequest):
    await _script_exists(script_id)
    db = await get_db()
    for i, action_id in enumerate(data.order):
        await db.execute(
            "UPDATE actions SET order_num=? WHERE id=? AND script_id=?",
            (i, action_id, script_id)
        )
    await db.commit()
    return await list_actions(script_id)


from pydantic import BaseModel as _BaseModel

class _CopyMoveRequest(_BaseModel):
    action_ids: list[int]
    target_script_id: int
    mode: str = "copy"  # "copy" or "move"


@router.post("/copy-move")
async def copy_move_actions(script_id: int, data: _CopyMoveRequest):
    """Copy or move one or more actions to another script."""
    await _script_exists(script_id)
    db = await get_db()

    # Validate target script exists
    cursor = await db.execute("SELECT id FROM scripts WHERE id=?", (data.target_script_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Target script not found")

    if data.mode not in ("copy", "move"):
        raise HTTPException(status_code=400, detail="mode must be 'copy' or 'move'")

    # Fetch the actions to copy/move (in order)
    placeholders = ",".join("?" * len(data.action_ids))
    cursor = await db.execute(
        f"SELECT * FROM actions WHERE id IN ({placeholders}) AND script_id=? ORDER BY order_num",
        (*data.action_ids, script_id)
    )
    rows = [_row_to_dict(r) for r in await cursor.fetchall()]
    if not rows:
        raise HTTPException(status_code=404, detail="No matching actions found in source script")

    # Get next order_num in target script
    cursor = await db.execute(
        "SELECT COALESCE(MAX(order_num), -1) + 1 AS nxt FROM actions WHERE script_id=?",
        (data.target_script_id,)
    )
    next_order = (await cursor.fetchone())["nxt"]

    inserted_ids = []
    for i, row in enumerate(rows):
        cursor = await db.execute(
            """INSERT INTO actions (
                script_id, order_num, name, action_type,
                x, y, x2, y2, duration_ms,
                template_path, template_path2, match_threshold, retry_count, retry_delay_ms,
                jump_on_success, jump_on_fail,
                match_region_x, match_region_y, match_region_w, match_region_h, match_region_screen,
                key_code, combo_action,
                api_url, api_method, api_headers, api_body, api_save_to_var,
                var_name, var_operation, var_value,
                text_content, text_speed_ms,
                jump_to,
                condition_var, condition_op, condition_value, jump_on_true, jump_on_false,
                orientation_value, app_package,
                call_script_name, goto_script_name,
                toast_message, toast_duration,
                use_match_result, wait_ms, wait_before_ms, wait_after_ms
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data.target_script_id, next_order + i,
                row.get("name", f"action_{i}"), row.get("action_type", "wait"),
                row.get("x"), row.get("y"), row.get("x2"), row.get("y2"),
                row.get("duration_ms", 300),
                row.get("template_path", ""), row.get("template_path2", ""),
                row.get("match_threshold", 0.8),
                row.get("retry_count", 1), row.get("retry_delay_ms", 1000),
                row.get("jump_on_success", ""), row.get("jump_on_fail", ""),
                row.get("match_region_x"), row.get("match_region_y"),
                row.get("match_region_w"), row.get("match_region_h"),
                row.get("match_region_screen"),
                row.get("key_code", "HOME"), row.get("combo_action", "select_all"),
                row.get("api_url", ""), row.get("api_method", "GET"),
                row.get("api_headers", "{}"), row.get("api_body", ""),
                row.get("api_save_to_var", ""),
                row.get("var_name", ""), row.get("var_operation", "set"),
                row.get("var_value", ""),
                row.get("text_content", ""), row.get("text_speed_ms", 50),
                row.get("jump_to", ""),
                row.get("condition_var", ""), row.get("condition_op", "eq"),
                row.get("condition_value", ""),
                row.get("jump_on_true", ""), row.get("jump_on_false", ""),
                row.get("orientation_value", "auto"), row.get("app_package", ""),
                row.get("call_script_name", ""), row.get("goto_script_name", ""),
                row.get("toast_message", ""), row.get("toast_duration", "short"),
                row.get("use_match_result", 0),
                row.get("wait_ms", 1000), row.get("wait_before_ms", 500),
                row.get("wait_after_ms", 500),
            )
        )
        inserted_ids.append(cursor.lastrowid)

    if data.mode == "move":
        # Delete originals from source script
        await db.execute(
            f"DELETE FROM actions WHERE id IN ({placeholders}) AND script_id=?",
            (*data.action_ids, script_id)
        )
        # Re-number remaining actions in source script
        remaining = await (await db.execute(
            "SELECT id FROM actions WHERE script_id=? ORDER BY order_num", (script_id,)
        )).fetchall()
        for i, r in enumerate(remaining):
            await db.execute("UPDATE actions SET order_num=? WHERE id=?", (i, r["id"]))

    await db.commit()
    return {
        "message": f"{'Moved' if data.mode == 'move' else 'Copied'} {len(rows)} action(s) to script {data.target_script_id}",
        "inserted_ids": inserted_ids,
        "count": len(rows),
    }
