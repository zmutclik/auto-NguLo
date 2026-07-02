"""Execution router — run scripts and stream logs via SSE."""
import asyncio
import json
import time
import queue

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from database.connection import get_db
from engine.executor import ScriptExecutor, adb_available

router = APIRouter(prefix="/api/scripts/{script_id}", tags=["execution"])

# Store active executors (one per script, simplified)
_active_executors: dict[int, ScriptExecutor] = {}


def _row_to_dict(row) -> dict:
    if row is None: return None
    return dict(row)


async def _get_script_dict(script_id: int) -> dict | None:
    """Load a script with its actions from DB by ID. Returns None if not found."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM scripts WHERE id=?", (script_id,))
    script_row = await cursor.fetchone()
    if not script_row:
        return None
    script = _row_to_dict(script_row)
    cursor2 = await db.execute(
        "SELECT * FROM actions WHERE script_id=? ORDER BY order_num", (script_id,)
    )
    script["actions"] = [_row_to_dict(r) for r in await cursor2.fetchall()]
    return script

async def _get_script_dict_by_name(script_name: str) -> dict | None:
    """Load a script with its actions from DB by name. Returns None if not found."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM scripts WHERE name=?", (script_name,))
    script_row = await cursor.fetchone()
    if not script_row:
        return None
    script = _row_to_dict(script_row)
    cursor2 = await db.execute(
        "SELECT * FROM actions WHERE script_id=? ORDER BY order_num", (script["id"],)
    )
    script["actions"] = [_row_to_dict(r) for r in await cursor2.fetchall()]
    return script


@router.post("/execute")
async def execute_script(script_id: int):
    """Start script execution in background, return log stream endpoint.
    Supports goto_script chaining: if a goto_script action is encountered,
    execution transfers to the target script automatically."""
    db = await get_db()
    script = await _get_script_dict(script_id)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    if not script["actions"]:
        raise HTTPException(status_code=400, detail="Script has no actions")

    # Create log entry in DB
    log_cursor = await db.execute(
        "INSERT INTO execution_logs (script_id, script_name, status, total_actions) VALUES (?, ?, 'running', ?)",
        (script_id, script["name"], len(script["actions"]))
    )
    log_id = log_cursor.lastrowid
    await db.commit()

    # Create executor — auto-detect ADB availability
    use_mock = not await adb_available()
    executor = ScriptExecutor(mock_mode=use_mock)

    # Set up script_loader so call_script / goto_script actions can load other scripts by name
    async def _load_script(sname: str) -> dict:
        return await _get_script_dict_by_name(sname)

    executor.script_loader = _load_script

    _active_executors[log_id] = executor

    # Build log array
    log_entries: list[dict] = []

    def log_cb(level: str, message: str):
        t = time.strftime("%H:%M:%S")
        log_entries.append({"time": t, "level": level, "message": message})

    # Run in background task with goto_script chaining support
    async def _run_chain():
        nonlocal executor
        current_script = script
        current_log_id = log_id
        current_logs = log_entries
        goto_chain = []  # track visited script IDs to prevent infinite loops
        inherited_vars: dict | None = None  # None = fresh start, dict = inherit dari goto_script

        while True:
            result = await executor.execute(current_script, log_cb, inherit_variables=inherited_vars)
            inherited_vars = None  # reset setelah dipakai, agar tidak bocor ke iterasi berikutnya

            # Update the current execution_logs row
            final_status = result["status"]
            await db.execute(
                "UPDATE execution_logs SET status=?, log_json=?, success_count=?, fail_count=?, duration_sec=?, ended_at=datetime('now') WHERE id=?",
                (final_status, json.dumps(current_logs, ensure_ascii=False),
                 result["success_count"], result["fail_count"], result["duration_sec"], current_log_id)
            )
            await db.commit()

            # Check if we should chain to another script via goto_script
            goto_target = result.get("_goto_target")  # now a script name string
            if goto_target and goto_target not in goto_chain:
                goto_chain.append(goto_target)
                next_script = await _get_script_dict_by_name(goto_target)
                if next_script and next_script.get("actions"):
                    # Create a new log entry for the target script
                    new_log_cursor = await db.execute(
                        "INSERT INTO execution_logs (script_id, script_name, status, total_actions) VALUES (?, ?, 'running', ?)",
                        (next_script["id"], next_script["name"], len(next_script["actions"]))
                    )
                    new_log_id = new_log_cursor.lastrowid
                    await db.commit()

                    # Build a new executor for the target script
                    new_exec = ScriptExecutor(mock_mode=use_mock)
                    new_exec.script_loader = executor.script_loader
                    new_exec.last_match_result = executor.last_match_result
                    _active_executors[new_log_id] = new_exec
                    # Simpan variabel dari executor lama untuk diwariskan via inherit_variables
                    inherited_vars = dict(executor.variables)
                    executor = new_exec

                    # Reset logs for the new script
                    current_logs.clear()
                    log_cb("info", f"🔀 Transferred from script [{current_script.get('name')}] via goto_script")
                    current_script = next_script
                    current_log_id = new_log_id
                    continue
                else:
                    log_cb("error", f"❌ goto_script target [{goto_target}] not found or has no actions")
            break

        _active_executors.pop(log_id, None)

    asyncio.create_task(_run_chain())

    return {"message": "Execution started", "log_id": log_id, "stream_url": f"/api/scripts/{script_id}/stream/{log_id}"}


@router.get("/stream/{log_id}")
async def stream_execution_log(script_id: int, log_id: int, request: Request):
    """SSE stream for live execution logs."""
    db = await get_db()

    async def event_generator():
        last_len = 0
        closed = False
        while not closed:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            # Read current logs from DB
            cursor = await db.execute("SELECT log_json, status FROM execution_logs WHERE id=?", (log_id,))
            row = await cursor.fetchone()
            if not row:
                yield f"data: {json.dumps({'error': 'Log not found'})}\n\n"
                break

            try:
                entries = json.loads(row["log_json"])
            except (json.JSONDecodeError, TypeError):
                entries = []

            # Stream new entries since last check
            if len(entries) > last_len:
                new_entries = entries[last_len:]
                last_len = len(entries)
                for entry in new_entries:
                    yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"

            status = row["status"]
            if status in ("success", "stopped", "failed"):
                yield f"event: done\ndata: {json.dumps({'status': status})}\n\n"
                break

            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/logs")
async def list_execution_logs(script_id: int):
    """Get all execution logs for a script."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, script_id, script_name, status, success_count, fail_count, total_actions, duration_sec, started_at, ended_at FROM execution_logs WHERE script_id=? ORDER BY started_at DESC LIMIT 50",
        (script_id,)
    )
    return [_row_to_dict(r) for r in await cursor.fetchall()]


@router.get("/logs/{log_id}")
async def get_execution_log_detail(script_id: int, log_id: int):
    """Get full detail of an execution log including all log entries."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM execution_logs WHERE id=? AND script_id=?", (log_id, script_id))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Log not found")
    result = _row_to_dict(row)
    try:
        result["logs"] = json.loads(result.get("log_json", "[]"))
    except (json.JSONDecodeError, TypeError):
        result["logs"] = []
    return result


@router.post("/execute/{log_id}/stop")
async def stop_execution(script_id: int, log_id: int):
    """Stop a running execution."""
    executor = _active_executors.get(log_id)
    if executor:
        executor.stop()
        return {"message": "Stop requested"}
    return {"message": "No active execution found"}
