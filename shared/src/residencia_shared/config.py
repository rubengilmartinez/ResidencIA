"""Configuración de la residencia: plantas y zonas, personal y turnos, y escalado.

Todo vive en ficheros YAML (``config/``) y se valida al arrancar. Un error de configuración
(una zona sin cuidador en algún turno, un turno que deja horas sin cubrir...) debe impedir
que el sistema arranque, no descubrirse en mitad de una emergencia.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PrivateAttr, model_validator

from residencia_shared.events import ID_PATTERN, Location, Severity, ZoneType
from residencia_shared.internal import EscalationStage

_STRICT = ConfigDict(frozen=True, extra="forbid")


# --- Residencia -------------------------------------------------------------------------


class ZoneConfig(BaseModel):
    model_config = _STRICT

    id: str = Field(pattern=ID_PATTERN)
    name: str
    type: ZoneType
    bedridden: bool = False

    @model_validator(mode="after")
    def _bedridden_only_in_rooms(self) -> Self:
        if self.bedridden and self.type is not ZoneType.ROOM:
            raise ValueError(f"zone '{self.id}': only rooms can have bedridden residents")
        return self


class FloorConfig(BaseModel):
    model_config = _STRICT

    id: str = Field(pattern=ID_PATTERN)
    name: str
    zones: list[ZoneConfig] = Field(min_length=1)


class ResidenceConfig(BaseModel):
    model_config = _STRICT

    name: str
    timezone: str
    floors: list[FloorConfig] = Field(min_length=1)

    _zone_index: dict[str, tuple[FloorConfig, ZoneConfig]] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone: {self.timezone!r}") from None
        floor_ids = [f.id for f in self.floors]
        if len(floor_ids) != len(set(floor_ids)):
            raise ValueError("duplicate floor ids")
        index: dict[str, tuple[FloorConfig, ZoneConfig]] = {}
        for floor in self.floors:
            for zone in floor.zones:
                if zone.id in index:
                    raise ValueError(f"duplicate zone id: {zone.id!r}")
                index[zone.id] = (floor, zone)
        self._zone_index = index
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def zone_ids(self) -> list[str]:
        return list(self._zone_index)

    def has_zone(self, zone_id: str) -> bool:
        return zone_id in self._zone_index

    def zone(self, zone_id: str) -> ZoneConfig:
        return self._zone_index[zone_id][1]

    def floor_of(self, zone_id: str) -> FloorConfig:
        return self._zone_index[zone_id][0]

    def location(self, zone_id: str) -> Location:
        """Ubicación canónica de una zona (la que deben llevar los eventos)."""
        floor, zone = self._zone_index[zone_id]
        return Location(floor_id=floor.id, zone_id=zone.id, zone_type=zone.type)


# --- Personal y turnos ------------------------------------------------------------------


class Role(StrEnum):
    CAREGIVER = "caregiver"
    SUPERVISOR = "supervisor"


class ShiftConfig(BaseModel):
    model_config = _STRICT

    id: str = Field(pattern=ID_PATTERN)
    name: str
    # Horas locales de la residencia. Si end < start, el turno cruza la medianoche.
    start: time
    end: time

    @model_validator(mode="after")
    def _non_empty(self) -> Self:
        if self.start == self.end:
            raise ValueError(f"shift '{self.id}': start and end must differ")
        return self

    def contains(self, local_time: time) -> bool:
        if self.start < self.end:
            return self.start <= local_time < self.end
        return local_time >= self.start or local_time < self.end


class StaffMember(BaseModel):
    model_config = _STRICT

    id: str = Field(pattern=ID_PATTERN)
    name: str
    role: Role
    shift: str
    zones: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _caregivers_have_zones(self) -> Self:
        if self.role is Role.CAREGIVER and not self.zones:
            raise ValueError(f"caregiver '{self.id}' has no assigned zones")
        return self


class StaffConfig(BaseModel):
    model_config = _STRICT

    shifts: list[ShiftConfig] = Field(min_length=1)
    staff: list[StaffMember] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        shift_ids = [s.id for s in self.shifts]
        if len(shift_ids) != len(set(shift_ids)):
            raise ValueError("duplicate shift ids")
        staff_ids = [m.id for m in self.staff]
        if len(staff_ids) != len(set(staff_ids)):
            raise ValueError("duplicate staff ids")
        for member in self.staff:
            if member.shift not in shift_ids:
                raise ValueError(f"staff '{member.id}' references unknown shift {member.shift!r}")
        # Cada minuto del día debe pertenecer exactamente a un turno: sin huecos ni solapes.
        for minute in range(24 * 60):
            t = time(minute // 60, minute % 60)
            covering = [s.id for s in self.shifts if s.contains(t)]
            if len(covering) != 1:
                raise ValueError(f"time {t:%H:%M} is covered by {len(covering)} shifts: {covering}")
        return self


# --- Escalado ---------------------------------------------------------------------------


class StageTimeouts(BaseModel):
    model_config = _STRICT

    normal_s: PositiveFloat
    critical_s: PositiveFloat

    @model_validator(mode="after")
    def _critical_not_slower(self) -> Self:
        if self.critical_s > self.normal_s:
            raise ValueError("critical timeout cannot be longer than the normal one")
        return self

    def for_priority(self, priority: Severity) -> float:
        return self.critical_s if priority is Severity.CRITICAL else self.normal_s


class EscalationConfig(BaseModel):
    """Plazos de cada etapa. Cada plazo cuenta desde que se envía la alerta de esa etapa.

    La última etapa (todo el personal) no tiene plazo: sigue activa hasta que alguien acepte.
    """

    model_config = _STRICT

    zone_caregiver: StageTimeouts
    floor: StageTimeouts

    def timeout(self, stage: EscalationStage, priority: Severity) -> timedelta | None:
        if stage is EscalationStage.ZONE_CAREGIVER:
            return timedelta(seconds=self.zone_caregiver.for_priority(priority))
        if stage is EscalationStage.FLOOR:
            return timedelta(seconds=self.floor.for_priority(priority))
        return None


# --- Configuración completa -------------------------------------------------------------


class SystemConfig(BaseModel):
    model_config = _STRICT

    residence: ResidenceConfig
    staff: StaffConfig
    escalation: EscalationConfig

    @model_validator(mode="after")
    def _cross_validate(self) -> Self:
        for member in self.staff.staff:
            for zone_id in member.zones:
                if not self.residence.has_zone(zone_id):
                    raise ValueError(f"staff '{member.id}' references unknown zone {zone_id!r}")
        for shift in self.staff.shifts:
            on_shift = [m for m in self.staff.staff if m.shift == shift.id]
            if not any(m.role is Role.SUPERVISOR for m in on_shift):
                raise ValueError(f"shift '{shift.id}' has no supervisor")
            covered = {z for m in on_shift if m.role is Role.CAREGIVER for z in m.zones}
            uncovered = [z for z in self.residence.zone_ids if z not in covered]
            if uncovered:
                raise ValueError(f"shift '{shift.id}' leaves zones without caregiver: {uncovered}")
        return self

    def staff_member(self, staff_id: str) -> StaffMember | None:
        return next((m for m in self.staff.staff if m.id == staff_id), None)

    def active_shift(self, now: datetime) -> ShiftConfig:
        local = now.astimezone(self.residence.tz).time()
        # La validación garantiza que hay exactamente un turno para cada minuto.
        return next(
            s for s in self.staff.shifts if s.contains(local.replace(second=0, microsecond=0))
        )

    def on_duty(self, now: datetime) -> list[StaffMember]:
        shift = self.active_shift(now)
        return [m for m in self.staff.staff if m.shift == shift.id]

    def zone_caregivers(self, zone_id: str, now: datetime) -> list[str]:
        return [m.id for m in self.on_duty(now) if m.role is Role.CAREGIVER and zone_id in m.zones]

    def floor_caregivers(self, floor_id: str, now: datetime) -> list[str]:
        floor_zones = {z.id for f in self.residence.floors if f.id == floor_id for z in f.zones}
        return [
            m.id
            for m in self.on_duty(now)
            if m.role is Role.CAREGIVER and floor_zones.intersection(m.zones)
        ]

    def all_staff(self, now: datetime) -> list[str]:
        return [m.id for m in self.on_duty(now)]

    def stage_targets(self, stage: EscalationStage, location: Location, now: datetime) -> list[str]:
        """Personas a las que va dirigida una etapa de escalado (sin acumular las anteriores)."""
        if stage is EscalationStage.ZONE_CAREGIVER:
            return self.zone_caregivers(location.zone_id, now)
        if stage is EscalationStage.FLOOR:
            return self.floor_caregivers(location.floor_id, now)
        return self.all_staff(now)


# --- Carga ------------------------------------------------------------------------------

RESIDENCE_FILE = "residence.yaml"
STAFF_FILE = "staff.yaml"
ESCALATION_FILE = "escalation.yaml"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")
    return data


def load_system_config(
    config_dir: Path,
    *,
    residence_file: Path | None = None,
    staff_file: Path | None = None,
    escalation_file: Path | None = None,
) -> SystemConfig:
    """Carga y valida la configuración. Cada fichero se puede sustituir por separado
    (por ejemplo, los tests de extremo a extremo usan un ``escalation.yaml`` con plazos cortos).
    """
    return SystemConfig(
        residence=ResidenceConfig.model_validate(
            load_yaml(residence_file or config_dir / RESIDENCE_FILE)
        ),
        staff=StaffConfig.model_validate(load_yaml(staff_file or config_dir / STAFF_FILE)),
        escalation=EscalationConfig.model_validate(
            load_yaml(escalation_file or config_dir / ESCALATION_FILE)
        ),
    )
