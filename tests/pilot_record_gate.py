#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from pilot_api import api


def main() -> None:
    parser = argparse.ArgumentParser(description="Record CI or operator evidence in a Pilot Program.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--token", default="pilot-token")
    parser.add_argument("--tenant", default="tenant:beeza")
    parser.add_argument("--pilot-key", required=True)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--status", choices=["PENDING", "RUNNING", "PASS", "FAIL", "BLOCKED", "SKIPPED"], required=True)
    parser.add_argument("--source", default="PILOT_GATE")
    parser.add_argument("--summary", required=True)
    parser.add_argument("--artifact-ref", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    metrics: dict[str, Any] = {}
    if args.report:
        report_path = Path(args.report).resolve()
        metrics = json.loads(report_path.read_text(encoding="utf-8"))
        if not args.artifact_ref:
            args.artifact_ref = str(report_path)
    completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _, body, _ = api(
        args.base_url,
        "POST",
        f"/api/pilot/programs/{args.pilot_key}/gates",
        token=args.token,
        tenant=args.tenant,
        identity="service:runtime",
        payload={
            "gate_key": args.gate,
            "status": args.status,
            "source": args.source,
            "summary": args.summary,
            "metrics": metrics,
            "artifact_ref": args.artifact_ref,
            "completed_at": completed_at,
        },
    )
    print(json.dumps(body, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
