#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from pilot_api import ApiError, api, wait_ready

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
ACTIVE = {"DISPATCHING", "STARTED", "RUNNING", "QUEUED", "WAITING_APPROVAL", "STOPPING"}


def record_gate(
    base_url: str,
    token: str,
    tenant: str,
    pilot_key: str,
    report: dict[str, Any],
    artifact_ref: str,
) -> None:
    api(
        base_url,
        "POST",
        f"/api/pilot/programs/{pilot_key}/gates",
        token=token,
        tenant=tenant,
        identity="service:runtime",
        payload={
            "gate_key": "runtime_e2e",
            "status": report["gate_status"],
            "source": "PILOT_RUNTIME_E2E",
            "summary": report["summary"],
            "metrics": {
                "requested": report["requested"],
                "passed": report["passed"],
                "failed": report["failed"],
            },
            "artifact_ref": artifact_ref,
            "completed_at": report["completed_at"],
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BeezaOffice against configured real agent runtimes.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--token", default="pilot-token")
    parser.add_argument("--tenant", default="tenant:beeza")
    parser.add_argument("--runtimes", default="openclaw,cherryagent,hermes,thclaws")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--allow-accepted", action="store_true")
    parser.add_argument("--pilot-key", default="")
    parser.add_argument("--artifact-ref", default="")
    parser.add_argument("--output", default="pilot-runtime-e2e-report.json")
    args = parser.parse_args()

    wait_ready(args.base_url)
    requested = [item.strip() for item in args.runtimes.split(",") if item.strip()]
    _, runtimes, _ = api(
        args.base_url,
        "GET",
        "/api/runtimes",
        token=args.token,
        tenant=args.tenant,
    )
    runtime_map = {row["key"]: row for row in runtimes}
    results: list[dict[str, Any]] = []

    for runtime_key in requested:
        result: dict[str, Any] = {
            "runtime_key": runtime_key,
            "status": "FAIL",
            "probe": None,
            "mission_key": None,
            "dispatch_key": None,
            "dispatch_status": None,
            "error": None,
        }
        try:
            runtime = runtime_map.get(runtime_key)
            if runtime is None:
                raise AssertionError("Runtime is not registered")
            if not runtime.get("configured"):
                raise AssertionError("Runtime base URL is not configured")

            _, probe, _ = api(
                args.base_url,
                "POST",
                f"/api/runtimes/{runtime_key}/probe",
                token=args.token,
                tenant=args.tenant,
                identity="human:operator",
            )
            result["probe"] = probe
            if probe.get("status") != "ONLINE":
                raise AssertionError(f"Probe status is {probe.get('status')}")

            _, mission, _ = api(
                args.base_url,
                "POST",
                "/api/missions",
                token=args.token,
                tenant=args.tenant,
                payload={
                    "title": f"Pilot runtime verification — {runtime_key}",
                    "objective": (
                        "Return a concise JSON object with runtime_key, status='ok', "
                        "and a non-empty evidence message. Do not modify external systems."
                    ),
                    "priority": "NORMAL",
                },
            )
            mission_key = mission["key"]
            result["mission_key"] = mission_key

            _, dispatch, _ = api(
                args.base_url,
                "POST",
                f"/api/runtimes/{runtime_key}/dispatch",
                token=args.token,
                tenant=args.tenant,
                identity="human:operator",
                payload={
                    "mission_key": mission_key,
                    "prompt": "Pilot E2E: respond with verified harmless output only.",
                    "roles": ["pilot-verifier"],
                    "tags": ["pilot", "e2e", "safe"],
                    "instructions": "No tools, no file writes, no network changes.",
                },
                timeout=max(args.timeout, 30),
            )
            dispatch_key = dispatch["key"]
            result["dispatch_key"] = dispatch_key
            deadline = time.monotonic() + args.timeout
            current = dispatch

            while current.get("status") in ACTIVE and time.monotonic() < deadline:
                if current.get("remote_id") and current.get("can_sync", runtime_key in {"cherryagent", "hermes"}):
                    try:
                        _, current, _ = api(
                            args.base_url,
                            "POST",
                            f"/api/runtime-dispatches/{dispatch_key}/sync",
                            token=args.token,
                            tenant=args.tenant,
                            identity="human:operator",
                        )
                    except ApiError as exc:
                        if exc.status not in {409, 422}:
                            raise
                else:
                    _, current, _ = api(
                        args.base_url,
                        "GET",
                        f"/api/runtime-dispatches/{dispatch_key}",
                        token=args.token,
                        tenant=args.tenant,
                    )
                if current.get("status") in TERMINAL:
                    break
                time.sleep(args.poll_seconds)

            result["dispatch_status"] = current.get("status")
            output = current.get("output") or {}
            has_evidence = bool(
                current.get("remote_id")
                or output.get("summary")
                or output.get("remote")
            )
            if current.get("status") == "COMPLETED" and has_evidence:
                result["status"] = "PASS"
            elif args.allow_accepted and current.get("status") in ACTIVE and has_evidence:
                result["status"] = "PASS"
                result["accepted_not_completed"] = True
            else:
                raise AssertionError(
                    f"Dispatch did not complete with evidence: status={current.get('status')}"
                )
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        results.append(result)

    passed = sum(row["status"] == "PASS" for row in results)
    failed = len(results) - passed
    completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report = {
        "gate": "runtime_e2e",
        "gate_status": "PASS" if results and failed == 0 else "FAIL",
        "requested": len(results),
        "passed": passed,
        "failed": failed,
        "summary": f"{passed}/{len(results)} configured runtimes passed the end-to-end gate",
        "completed_at": completed_at,
        "results": results,
    }
    output_path = Path(args.output).resolve()
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))

    if args.pilot_key:
        record_gate(
            args.base_url,
            args.token,
            args.tenant,
            args.pilot_key,
            report,
            args.artifact_ref or str(output_path),
        )
    if report["gate_status"] != "PASS":
        raise SystemExit("Runtime E2E gate failed")


if __name__ == "__main__":
    main()
