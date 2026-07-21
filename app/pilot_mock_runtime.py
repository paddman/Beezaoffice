from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import FastAPI

app = FastAPI(title="BeezaOffice Pilot Runtime Simulator", version="0.16.0")


def result(runtime: str, run_id: str) -> dict[str, Any]:
    return {
        "id": run_id,
        "run_id": run_id,
        "runId": run_id,
        "session_id": run_id,
        "status": "COMPLETED",
        "output": f"{runtime} pilot runtime completed with evidence",
        "summary": f"{runtime} pilot runtime completed with evidence",
        "result": {"runtime_key": runtime, "status": "ok", "evidence": "simulated-contract"},
        "last_event": "completed",
    }


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": "pilot-runtime"}]}


@app.post("/v1/chat/completions")
def openclaw_chat(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = f"mock-openclaw-{uuid4().hex[:10]}"
    return {
        "id": run_id,
        "object": "chat.completion",
        "model": payload.get("model") or "openclaw/default",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '{"runtime_key":"openclaw","status":"ok","evidence":"simulated-contract"}',
                },
                "finish_reason": "stop",
            }
        ],
    }


@app.post("/orchestrator/runs")
def cherry_run(_: dict[str, Any]) -> dict[str, Any]:
    return result("cherryagent", f"mock-cherry-{uuid4().hex[:10]}")


@app.get("/orchestrator/runs/{run_id}")
def cherry_status(run_id: str) -> dict[str, Any]:
    return result("cherryagent", run_id)


@app.post("/v1/runs")
def hermes_run(_: dict[str, Any]) -> dict[str, Any]:
    return result("hermes", f"mock-hermes-{uuid4().hex[:10]}")


@app.get("/v1/runs/{run_id}")
def hermes_status(run_id: str) -> dict[str, Any]:
    return result("hermes", run_id)


@app.post("/v1/runs/{run_id}/stop")
def hermes_stop(run_id: str) -> dict[str, Any]:
    return {**result("hermes", run_id), "status": "CANCELLED"}


@app.post("/v1/runs/{run_id}/approval")
def hermes_approval(run_id: str, _: dict[str, Any]) -> dict[str, Any]:
    return result("hermes", run_id)


@app.post("/agent/run")
def thclaws_run(_: dict[str, Any]) -> dict[str, Any]:
    return result("thclaws", f"mock-thclaws-{uuid4().hex[:10]}")
