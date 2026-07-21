from __future__ import annotations

import os

import business_service
import phase13_app  # noqa: F401 — install Phase 1–13 runtime and business layer
from main import app

business_service.DEFAULT_LABOR_RATE_USD = float(
    os.getenv("BEEZA_DEFAULT_LABOR_RATE_USD", "30")
)

_original_meter_for_request = phase13_app.meter_for_request


def phase13_meter_for_request(request):
    # Industry-pack installation records its own business meter with the
    # installation transaction, so do not double-count it in HTTP metering.
    return [
        meter
        for meter in _original_meter_for_request(request)
        if meter != "pack_installs"
    ]


phase13_app.meter_for_request = phase13_meter_for_request
app.version = "0.14.0"
