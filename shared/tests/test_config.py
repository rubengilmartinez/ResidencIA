"""Tests de la configuración: la real debe ser válida y los errores típicos deben detectarse."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError
from residencia_shared.config import Role, SystemConfig
from residencia_shared.events import Location, Severity, ZoneType
from residencia_shared.internal import EscalationStage

RawConfig = dict[str, dict[str, Any]]


# --- La configuración real ----------------------------------------------------------------


def test_real_config_matches_the_example_residence(system_config: SystemConfig) -> None:
    residence = system_config.residence
    assert [f.id for f in residence.floors] == ["p0", "p1"]
    for floor in residence.floors:
        rooms = [z for z in floor.zones if z.type is ZoneType.ROOM]
        corridors = [z for z in floor.zones if z.type is ZoneType.CORRIDOR]
        assert len(rooms) == 8
        assert len(corridors) == 1
    types = {z.type for f in residence.floors for z in f.zones}
    assert {ZoneType.DINING_ROOM, ZoneType.LIVING_ROOM, ZoneType.BATHROOM, ZoneType.GARDEN} <= types
    assert any(z.bedridden for f in residence.floors for z in f.zones)


def test_real_config_staffing(system_config: SystemConfig) -> None:
    def count(shift: str, role: Role) -> int:
        return sum(1 for m in system_config.staff.staff if m.shift == shift and m.role is role)

    assert count("day", Role.CAREGIVER) == 6
    assert count("night", Role.CAREGIVER) == 2
    assert count("day", Role.SUPERVISOR) == 1
    assert count("night", Role.SUPERVISOR) == 1


def test_real_escalation_timeouts(system_config: SystemConfig) -> None:
    esc = system_config.escalation
    stage = EscalationStage
    assert esc.timeout(stage.ZONE_CAREGIVER, Severity.HIGH).total_seconds() == 30
    assert esc.timeout(stage.ZONE_CAREGIVER, Severity.CRITICAL).total_seconds() == 10
    assert esc.timeout(stage.FLOOR, Severity.HIGH).total_seconds() == 60
    assert esc.timeout(stage.FLOOR, Severity.CRITICAL).total_seconds() == 30
    assert esc.timeout(stage.ALL_STAFF, Severity.CRITICAL) is None


def test_location_lookup(system_config: SystemConfig) -> None:
    assert system_config.residence.location("hab_12") == Location(
        floor_id="p1", zone_id="hab_12", zone_type=ZoneType.ROOM
    )
    assert system_config.residence.floor_of("jardin").id == "p0"


# --- Turnos -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("utc_time", "expected"),
    [
        # Europe/Madrid es UTC+2 en octubre de 2026.
        (datetime(2026, 10, 2, 5, 59, 59, tzinfo=UTC), "night"),  # 07:59:59 local
        (datetime(2026, 10, 2, 6, 0, 0, tzinfo=UTC), "day"),  # 08:00 local
        (datetime(2026, 10, 2, 17, 59, 59, tzinfo=UTC), "day"),  # 19:59:59 local
        (datetime(2026, 10, 2, 18, 0, 0, tzinfo=UTC), "night"),  # 20:00 local
        (datetime(2026, 10, 2, 22, 0, 0, tzinfo=UTC), "night"),  # 00:00 local
        # Enero: UTC+1. Comprueba que se usa la zona horaria y no un desfase fijo.
        (datetime(2027, 1, 15, 6, 30, 0, tzinfo=UTC), "night"),  # 07:30 local
        (datetime(2027, 1, 15, 7, 0, 0, tzinfo=UTC), "day"),  # 08:00 local
    ],
)
def test_active_shift_boundaries(
    system_config: SystemConfig, utc_time: datetime, expected: str
) -> None:
    assert system_config.active_shift(utc_time).id == expected


def test_stage_targets_by_day(system_config: SystemConfig, day: datetime) -> None:
    loc = system_config.residence.location("hab_12")
    assert system_config.stage_targets(EscalationStage.ZONE_CAREGIVER, loc, day) == ["cuid_d4"]
    assert system_config.stage_targets(EscalationStage.FLOOR, loc, day) == [
        "cuid_d4",
        "cuid_d5",
        "cuid_d6",
    ]
    assert set(system_config.stage_targets(EscalationStage.ALL_STAFF, loc, day)) == {
        "cuid_d1",
        "cuid_d2",
        "cuid_d3",
        "cuid_d4",
        "cuid_d5",
        "cuid_d6",
        "sup_d",
    }


def test_stage_targets_by_night(system_config: SystemConfig, night: datetime) -> None:
    loc = system_config.residence.location("hab_12")
    assert system_config.stage_targets(EscalationStage.ZONE_CAREGIVER, loc, night) == ["cuid_n2"]
    assert system_config.stage_targets(EscalationStage.FLOOR, loc, night) == ["cuid_n2"]
    assert set(system_config.stage_targets(EscalationStage.ALL_STAFF, loc, night)) == {
        "cuid_n1",
        "cuid_n2",
        "sup_n",
    }


def test_shared_zone_notifies_every_assigned_caregiver(
    system_config: SystemConfig, day: datetime
) -> None:
    assert system_config.zone_caregivers("hab_14", day) == ["cuid_d4", "cuid_d6"]


# --- Errores de configuración que deben impedir el arranque --------------------------------


def _validate(raw: RawConfig) -> SystemConfig:
    return SystemConfig.model_validate(raw)


def test_raw_copy_is_valid(raw_config: RawConfig) -> None:
    _validate(raw_config)


def test_rejects_duplicate_zone_ids(raw_config: RawConfig) -> None:
    raw_config["residence"]["floors"][1]["zones"].append(
        {"id": "hab_01", "name": "Duplicada", "type": "room"}
    )
    with pytest.raises(ValidationError, match="duplicate zone id"):
        _validate(raw_config)


def test_rejects_unknown_timezone(raw_config: RawConfig) -> None:
    raw_config["residence"]["timezone"] = "Europe/Atlantis"
    with pytest.raises(ValidationError, match="unknown timezone"):
        _validate(raw_config)


def test_rejects_bedridden_outside_rooms(raw_config: RawConfig) -> None:
    zones = raw_config["residence"]["floors"][0]["zones"]
    comedor = next(z for z in zones if z["id"] == "comedor")
    comedor["bedridden"] = True
    with pytest.raises(ValidationError, match="only rooms"):
        _validate(raw_config)


def test_rejects_staff_in_unknown_zone(raw_config: RawConfig) -> None:
    raw_config["staff"]["staff"][0]["zones"].append("hab_99")
    with pytest.raises(ValidationError, match="unknown zone"):
        _validate(raw_config)


def test_rejects_zone_without_caregiver_in_a_shift(raw_config: RawConfig) -> None:
    night_p1 = next(m for m in raw_config["staff"]["staff"] if m["id"] == "cuid_n2")
    night_p1["zones"].remove("hab_12")
    with pytest.raises(ValidationError, match=r"shift 'night' leaves zones without caregiver"):
        _validate(raw_config)


def test_rejects_shift_without_supervisor(raw_config: RawConfig) -> None:
    raw_config["staff"]["staff"] = [m for m in raw_config["staff"]["staff"] if m["id"] != "sup_n"]
    with pytest.raises(ValidationError, match="no supervisor"):
        _validate(raw_config)


def test_rejects_gap_between_shifts(raw_config: RawConfig) -> None:
    raw_config["staff"]["shifts"][0]["end"] = "19:00"
    with pytest.raises(ValidationError, match="covered by 0 shifts"):
        _validate(raw_config)


def test_rejects_overlapping_shifts(raw_config: RawConfig) -> None:
    raw_config["staff"]["shifts"][0]["end"] = "21:00"
    with pytest.raises(ValidationError, match="covered by 2 shifts"):
        _validate(raw_config)


def test_rejects_caregiver_without_zones(raw_config: RawConfig) -> None:
    raw_config["staff"]["staff"][0]["zones"] = []
    with pytest.raises(ValidationError, match="no assigned zones"):
        _validate(raw_config)


def test_rejects_duplicate_staff_ids(raw_config: RawConfig) -> None:
    raw_config["staff"]["staff"].append(dict(raw_config["staff"]["staff"][0]))
    with pytest.raises(ValidationError, match="duplicate staff ids"):
        _validate(raw_config)


def test_rejects_critical_timeout_longer_than_normal(raw_config: RawConfig) -> None:
    raw_config["escalation"]["floor"]["critical_s"] = 90
    with pytest.raises(ValidationError, match="critical timeout"):
        _validate(raw_config)


@pytest.mark.parametrize("value", [0, -5])
def test_rejects_non_positive_timeouts(raw_config: RawConfig, value: int) -> None:
    raw_config["escalation"]["zone_caregiver"]["normal_s"] = value
    with pytest.raises(ValidationError):
        _validate(raw_config)


def test_rejects_unknown_keys(raw_config: RawConfig) -> None:
    raw_config["escalation"]["zone_caregiver"]["normal_seconds"] = 30
    with pytest.raises(ValidationError):
        _validate(raw_config)
