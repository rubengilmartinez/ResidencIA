"""Tests del logging estructurado."""

from __future__ import annotations

import json
import logging
import sys

from residencia_shared.logging import JsonFormatter


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord("svc.test", logging.WARNING, __file__, 1, "event_rejected", (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formats_one_json_object_with_extra_fields() -> None:
    line = JsonFormatter("orchestrator").format(_record(event_id="evt_1", zone_id="hab_12"))
    data = json.loads(line)
    assert data["level"] == "warning"
    assert data["service"] == "orchestrator"
    assert data["msg"] == "event_rejected"
    assert data["event_id"] == "evt_1"
    assert data["zone_id"] == "hab_12"
    assert data["ts"].endswith("Z")


def test_non_serializable_values_do_not_break_logging() -> None:
    data = json.loads(JsonFormatter("x").format(_record(obj=object())))
    assert data["obj"].startswith("<object")


def test_includes_exception_traceback() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    data = json.loads(JsonFormatter("x").format(record))
    assert "RuntimeError: boom" in data["exc"]


def test_drops_uvicorn_color_message() -> None:
    data = json.loads(JsonFormatter("x").format(_record(color_message="[36mhola[0m")))
    assert "color_message" not in data
