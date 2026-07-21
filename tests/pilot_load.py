#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def request_once(base_url: str, path: str, token: str, tenant: str) -> tuple[bool, float, int]:
    started = time.perf_counter()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Beeza-Identity": "human:operator",
            "X-Beeza-Tenant": tenant,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
            status = response.status
            success = 200 <= status < 400
    except urllib.error.HTTPError as exc:
        exc.read()
        status = exc.code
        success = False
    except Exception:
        status = 0
        success = False
    elapsed_ms = (time.perf_counter() - started) * 1000
    return success, elapsed_ms, status


def run_load(
    base_url: str,
    path: str,
    token: str,
    tenant: str,
    concurrency: int,
    duration_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + duration_seconds
    lock = threading.Lock()
    latencies: list[float] = []
    statuses: dict[int, int] = {}
    successes = 0
    failures = 0

    def worker() -> None:
        nonlocal successes, failures
        while time.monotonic() < deadline:
            success, latency, status = request_once(base_url, path, token, tenant)
            with lock:
                latencies.append(latency)
                statuses[status] = statuses.get(status, 0) + 1
                if success:
                    successes += 1
                else:
                    failures += 1

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(worker) for _ in range(concurrency)]
        for future in futures:
            future.result()
    elapsed = max(time.perf_counter() - started, 0.001)
    total = successes + failures
    return {
        "base_url": base_url,
        "path": path,
        "concurrency": concurrency,
        "duration_seconds": round(elapsed, 3),
        "requests": total,
        "successes": successes,
        "failures": failures,
        "error_rate": failures / total if total else 1.0,
        "requests_per_second": total / elapsed,
        "latency_ms": {
            "minimum": min(latencies) if latencies else 0.0,
            "mean": statistics.fmean(latencies) if latencies else 0.0,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "maximum": max(latencies) if latencies else 0.0,
        },
        "status_counts": {str(key): value for key, value in sorted(statuses.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the BeezaOffice pilot HTTP load gate.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--path", default="/api/missions")
    parser.add_argument("--token", default="pilot-token")
    parser.add_argument("--tenant", default="tenant:beeza")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=1500.0)
    parser.add_argument("--minimum-rps", type=float, default=5.0)
    parser.add_argument("--output", default="pilot-load-report.json")
    args = parser.parse_args()

    if args.concurrency < 1 or args.concurrency > 500:
        raise SystemExit("--concurrency must be between 1 and 500")
    if args.duration < 1 or args.duration > 3600:
        raise SystemExit("--duration must be between 1 and 3600 seconds")

    result = run_load(
        args.base_url,
        args.path,
        args.token,
        args.tenant,
        args.concurrency,
        args.duration,
    )
    result["thresholds"] = {
        "max_error_rate": args.max_error_rate,
        "max_p95_ms": args.max_p95_ms,
        "minimum_rps": args.minimum_rps,
    }
    failures = []
    if result["error_rate"] > args.max_error_rate:
        failures.append("error_rate")
    if result["latency_ms"]["p95"] > args.max_p95_ms:
        failures.append("p95_latency")
    if result["requests_per_second"] < args.minimum_rps:
        failures.append("throughput")
    result["gate_status"] = "PASS" if not failures else "FAIL"
    result["failed_thresholds"] = failures

    output = Path(args.output).resolve()
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(f"Load gate failed: {', '.join(failures)}")


if __name__ == "__main__":
    main()
