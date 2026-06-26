"""Execution router — run scripts and stream logs via SSE."""
import asyncio
import json
import time
import queue

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from database.connection import get_db
from engine.executor import ScriptExecutor

router = APIRouter(prefix="/api/scripts/{script_id}", tags=["execution"])

# Store active executors (one per script, simplified)
_active_executors: dict[int, ScriptExecutor] = {}


def _row_to_dict(row) -> dict:
    if row is None: return None
    return dict(row)


@router.post("/execute")
async def execute_script(script_id: int):
    """Start script execution in background, return log stream endpoint."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM scripts WHERE id=?", (script_id,))
    script_row = await cursor.fetchone()
    if not script_row:
        raise HTTPException(status_code=404, detail="Script not found")

    script = _row_to_dict(script_row)
    cursor2 = await db.execute(
        "SELECT * FROM actions WHERE script_id=? ORDER BY order_num", (script_id,)
    )
    script["actions"] = [_row_to_dict(r) for r in await cursor2.fetchall()]

    if not script["actions"]:
        raise HTTPException(status_code=400, detail="Script has no actions")

    # Create log entry in DB
    log_cursor = await db.execute(
        "INSERT INTO execution_logs (script_id, script_name, status, total_actions) VALUES (?, ?, 'running', ?)",
        (script_id, script["name"], len(script["actions"]))
    )
    log_id = log_cursor.lastrowid
    await db.commit()

    # Create executor
    executor = ScriptExecutor(mock_mode=True)
    _active_executors[log_id] = executor

    # Build log array
    log_entries: list[dict] = []

    def log_cb(level: str, message: str):
        t = time.strftime("%H:%M:%S")
        log_entries.append({"time": t, "level": level, "message": message})

    # Run in background task
    async def run_and_save():
        result = await executor.execute(script, log_cb)
        # Update DB
        await db.execute(
            "UPDATE execution_logs SET status=?, log_json=?, success_count=?, fail_count=?, duration_sec=?, ended_at=datetime('now') WHERE id=?",
            (result["status"], json.dumps(log_entries, ensure_ascii=False),
             result["success_count"], result["fail_count"], result["duration_sec"], log_id)
        )
        await db.commit()
        _active_executors.pop(log_id, None)

    asyncio.create_task(run_and_save())

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
