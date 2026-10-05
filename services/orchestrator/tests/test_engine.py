"""Tests del motor de incidentes con reloj simulado.

Ningún test espera en tiempo real: el instante se pasa explícitamente a cada operación,
así que los resultados son deterministas.

Plazos reales (config/escalation.yaml): zona 30 s (10 s crítica), planta 60 s (30 s
crítica). Turno de noche: un cuidador por planta, así que la etapa de planta se salta.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest
from orchestrator.engine import ActionRejectedError, EventRejectedError, IncidentEngine
from residencia_shared.config import SystemConfig
from residencia_shared.events import Event, EventType, Location, Severity, new_id
from residencia_shared.internal import (
    CaregiverAction,
    CaregiverActionType,
    EscalationStage,
    IncidentStatus,
    IncidentUpdate,
    UpdateReason,
)

EventFactory = Callable[..., Event]

FUSION_WINDOW = timedelta(seconds=120)
DAY_P1_FLOOR = ["cuid_d4", "cuid_d5", "cuid_d6"]
DAY_ALL = ["cuid_d1", "cuid_d2", "cuid_d3", "cuid_d4", "cuid_d5", "cuid_d6", "sup_d"]


def s(seconds: float) -> timedelta:
    return timedelta(seconds=seconds)


@pytest.fixture
def engine(system_config: SystemConfig) -> IncidentEngine:
    return IncidentEngine(system_config, FUSION_WINDOW)


def action(
    incident_id: str, staff_id: str, kind: CaregiverActionType, at: datetime
) -> CaregiverAction:
    return CaregiverAction(
        action_id=new_id("act"),
        timestamp=at,
        incident_id=incident_id,
        staff_id=staff_id,
        action=kind,
    )


def only(updates: list[IncidentUpdate]) -> IncidentUpdate:
    assert len(updates) == 1, updates
    return updates[0]


# --- Creación ----------------------------------------------------------------------------


def test_suspected_fall_creates_high_priority_incident_for_zone_caregiver(
    engine: IncidentEngine, make_event: EventFactory, night: datetime
) -> None:
    update = only(engine.handle_event(make_event(EventType.FALL_SUSPECTED, at=night), night))
    inc = update.incident
    assert update.reason is UpdateReason.CREATED
    assert inc.status is IncidentStatus.OPEN
    assert inc.priority is Severity.HIGH
    assert inc.stage is EscalationStage.ZONE_CAREGIVER
    assert inc.notified == ["cuid_n2"]
    assert update.new_recipients == ["cuid_n2"]
    assert inc.title == "Posible caída"
    assert inc.version == 1


def test_confirmed_fall_is_critical_whatever_the_module_says(
    engine: IncidentEngine, make_event: EventFactory, night: datetime
) -> None:
    event = make_event(
        EventType.FALL_CONFIRMED, at=night, confidence=0.3, severity_hint=Severity.LOW
    )
    assert only(engine.handle_event(event, night)).incident.priority is Severity.CRITICAL


def test_severity_hint_does_not_raise_priority(
    engine: IncidentEngine, make_event: EventFactory, night: datetime
) -> None:
    event = make_event(EventType.FALL_SUSPECTED, at=night, severity_hint=Severity.CRITICAL)
    assert only(engine.handle_event(event, night)).incident.priority is Severity.HIGH


def test_shared_zone_notifies_all_its_caregivers(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    update = only(engine.handle_event(make_event(zone_id="hab_14", at=day), day))
    assert update.incident.notified == ["cuid_d4", "cuid_d6"]


# --- Validación ----------------------------------------------------------------------------


def test_duplicate_event_is_ignored(
    engine: IncidentEngine, make_event: EventFactory, night: datetime
) -> None:
    event = make_event(at=night, event_id="evt_dup0001")
    engine.handle_event(event, night)
    assert engine.handle_event(event, night + s(1)) == []
    assert len(engine.active_incidents) == 1


def test_rejects_zone_unknown_to_the_residence(engine: IncidentEngine, night: datetime) -> None:
    event = Event.create(
        event_type=EventType.FALL_SUSPECTED,
        location=Location(floor_id="p1", zone_id="hab_99", zone_type="room"),
        confidence=0.9,
        severity_hint=Severity.HIGH,
        timestamp=night,
    )
    with pytest.raises(EventRejectedError, match="unknown zone"):
        engine.handle_event(event, night)
    assert engine.active_incidents == []


def test_rejects_location_that_contradicts_the_config(
    engine: IncidentEngine, night: datetime
) -> None:
    event = Event.create(
        event_type=EventType.FALL_SUSPECTED,
        location=Location(floor_id="p0", zone_id="hab_12", zone_type="room"),
        confidence=0.9,
        severity_hint=Severity.HIGH,
        timestamp=night,
    )
    with pytest.raises(EventRejectedError, match="location mismatch"):
        engine.handle_event(event, night)


def test_requires_utc_now(
    engine: IncidentEngine, make_event: EventFactory, night: datetime
) -> None:
    local = night.astimezone(timezone(timedelta(hours=2)))
    with pytest.raises(ValueError, match="UTC"):
        engine.handle_event(make_event(at=night), local)


# --- Escalado ----------------------------------------------------------------------------


def test_normal_escalation_by_day(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    created = only(engine.handle_event(make_event(EventType.FALL_SUSPECTED, at=day), day))
    assert created.incident.notified == ["cuid_d4"]

    assert engine.tick(day + s(29.9)) == []
    to_floor = only(engine.tick(day + s(30)))
    assert to_floor.reason is UpdateReason.ESCALATED
    assert to_floor.incident.stage is EscalationStage.FLOOR
    assert to_floor.new_recipients == ["cuid_d5", "cuid_d6"]
    assert to_floor.incident.notified == DAY_P1_FLOOR

    # El plazo de planta cuenta desde que se envió la etapa de planta.
    assert engine.tick(day + s(30 + 59.9)) == []
    to_all = only(engine.tick(day + s(90)))
    assert to_all.incident.stage is EscalationStage.ALL_STAFF
    assert set(to_all.new_recipients) == {"cuid_d1", "cuid_d2", "cuid_d3", "sup_d"}
    assert set(to_all.incident.notified) == set(DAY_ALL)

    # La última etapa no tiene plazo: sigue activa hasta que alguien acepte.
    assert engine.tick(day + s(3600)) == []
    assert engine.active_incidents[0].stage is EscalationStage.ALL_STAFF


def test_critical_escalation_by_day(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    engine.handle_event(make_event(EventType.FALL_CONFIRMED, at=day), day)
    assert engine.tick(day + s(9.9)) == []
    assert only(engine.tick(day + s(10))).incident.stage is EscalationStage.FLOOR
    assert engine.tick(day + s(10 + 29.9)) == []
    assert only(engine.tick(day + s(40))).incident.stage is EscalationStage.ALL_STAFF


def test_night_skips_floor_stage_when_it_adds_nobody(
    engine: IncidentEngine, make_event: EventFactory, night: datetime
) -> None:
    engine.handle_event(make_event(EventType.FALL_CONFIRMED, at=night), night)
    update = only(engine.tick(night + s(10)))
    assert update.incident.stage is EscalationStage.ALL_STAFF
    assert set(update.new_recipients) == {"cuid_n1", "sup_n"}
    assert update.incident.notified[0] == "cuid_n2"


def test_tick_before_deadline_changes_nothing(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    created = only(engine.handle_event(make_event(at=day), day))
    for offset in (1, 10, 20, 29.99):
        assert engine.tick(day + s(offset)) == []
    assert engine.active_incidents[0].version == created.incident.version


def test_late_tick_escalates_one_stage_at_a_time(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    """Si el tick llega tarde (p. ej. tras un reinicio), la nueva etapa empieza a contar
    desde que realmente se envía, como establece la política de escalado."""
    engine.handle_event(make_event(at=day), day)
    late = day + s(500)
    assert only(engine.tick(late)).incident.stage is EscalationStage.FLOOR
    assert engine.tick(late + s(59)) == []
    assert only(engine.tick(late + s(60))).incident.stage is EscalationStage.ALL_STAFF


# --- Fusión de eventos ---------------------------------------------------------------------


def test_confirmation_merges_into_suspected_incident_and_raises_priority(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    created = only(engine.handle_event(make_event(EventType.FALL_SUSPECTED, at=day), day))
    t = day + s(5)
    updates = engine.handle_event(
        make_event(EventType.FALL_CONFIRMED, at=t, payload={"immobile_seconds": 4}), t
    )
    raised = only(updates)
    assert raised.reason is UpdateReason.PRIORITY_RAISED
    assert raised.incident.incident_id == created.incident.incident_id
    assert raised.incident.priority is Severity.CRITICAL
    assert raised.incident.title == "Caída confirmada"
    assert "Sin movimiento desde hace 4 s" in raised.incident.message
    assert len(raised.incident.event_ids) == 2
    assert len(engine.active_incidents) == 1
    # Ahora el plazo de zona es el crítico (10 s) contado desde la creación.
    assert engine.tick(day + s(9.9)) == []
    assert only(engine.tick(day + s(10))).incident.stage is EscalationStage.FLOOR


def test_priority_raise_can_trigger_immediate_escalation(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    engine.handle_event(make_event(EventType.FALL_SUSPECTED, at=day), day)
    t = day + s(12)  # el plazo crítico de 10 s ya ha vencido
    updates = engine.handle_event(make_event(EventType.FALL_CONFIRMED, at=t), t)
    assert [u.reason for u in updates] == [UpdateReason.PRIORITY_RAISED, UpdateReason.ESCALATED]
    assert updates[1].incident.stage is EscalationStage.FLOOR
    assert updates[1].incident.version == updates[0].incident.version + 1


def test_same_priority_event_is_added_without_new_notifications(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    engine.handle_event(make_event(at=day), day)
    update = only(engine.handle_event(make_event(at=day + s(3)), day + s(3)))
    assert update.reason is UpdateReason.EVENT_ADDED
    assert update.new_recipients == []


def test_event_outside_fusion_window_opens_new_incident(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    engine.handle_event(make_event(at=day), day)
    later = day + FUSION_WINDOW + s(1)
    assert only(engine.handle_event(make_event(at=later), later)).reason is UpdateReason.CREATED
    assert len(engine.active_incidents) == 2


def test_events_in_different_zones_are_separate_incidents(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    engine.handle_event(make_event(zone_id="hab_12", at=day), day)
    engine.handle_event(make_event(zone_id="hab_13", at=day), day)
    assert len(engine.active_incidents) == 2


# --- Acciones de cuidadores ----------------------------------------------------------------


def test_accept_stops_escalation(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    inc_id = only(engine.handle_event(make_event(at=day), day)).incident.incident_id
    accepted = only(
        engine.handle_action(action(inc_id, "cuid_d4", CaregiverActionType.ACCEPT, day), day + s(5))
    )
    assert accepted.reason is UpdateReason.ACCEPTED
    assert accepted.incident.status is IncidentStatus.ACCEPTED
    assert accepted.incident.accepted_by == "cuid_d4"
    assert engine.tick(day + s(3600)) == []


def test_first_accept_wins(engine: IncidentEngine, make_event: EventFactory, day: datetime) -> None:
    inc_id = only(engine.handle_event(make_event(at=day), day)).incident.incident_id
    engine.handle_action(action(inc_id, "cuid_d4", CaregiverActionType.ACCEPT, day), day)
    with pytest.raises(ActionRejectedError) as exc:
        engine.handle_action(action(inc_id, "cuid_d5", CaregiverActionType.ACCEPT, day), day)
    assert exc.value.code == ActionRejectedError.NOT_OPEN
    assert engine.active_incidents[0].accepted_by == "cuid_d4"


def test_accept_from_unknown_staff_is_rejected(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    inc_id = only(engine.handle_event(make_event(at=day), day)).incident.incident_id
    with pytest.raises(ActionRejectedError) as exc:
        engine.handle_action(action(inc_id, "intruso", CaregiverActionType.ACCEPT, day), day)
    assert exc.value.code == ActionRejectedError.UNKNOWN_STAFF
    assert engine.active_incidents[0].status is IncidentStatus.OPEN


def test_action_on_unknown_incident_is_rejected(engine: IncidentEngine, day: datetime) -> None:
    with pytest.raises(ActionRejectedError) as exc:
        engine.handle_action(action("inc_nope", "cuid_d4", CaregiverActionType.ACCEPT, day), day)
    assert exc.value.code == ActionRejectedError.UNKNOWN_INCIDENT


def test_confirmation_after_accept_raises_priority_without_escalating(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    inc_id = only(engine.handle_event(make_event(at=day), day)).incident.incident_id
    engine.handle_action(action(inc_id, "cuid_d4", CaregiverActionType.ACCEPT, day), day + s(2))
    t = day + s(20)
    update = only(engine.handle_event(make_event(EventType.FALL_CONFIRMED, at=t), t))
    assert update.incident.priority is Severity.CRITICAL
    assert update.incident.status is IncidentStatus.ACCEPTED
    assert engine.tick(day + s(3600)) == []


def test_resolve_closes_incident_and_next_event_opens_a_new_one(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    first = only(engine.handle_event(make_event(at=day), day)).incident.incident_id
    engine.handle_action(action(first, "cuid_d4", CaregiverActionType.ACCEPT, day), day + s(2))
    resolved = only(
        engine.handle_action(
            action(first, "cuid_d4", CaregiverActionType.RESOLVE, day), day + s(60)
        )
    )
    assert resolved.incident.status is IncidentStatus.RESOLVED
    assert resolved.incident.resolved_by == "cuid_d4"
    assert engine.active_incidents == []
    t = day + s(70)
    second = only(engine.handle_event(make_event(at=t), t)).incident.incident_id
    assert second != first


def test_versions_increase_with_every_change(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    versions = [only(engine.handle_event(make_event(at=day), day)).incident.version]
    inc_id = engine.active_incidents[0].incident_id
    versions.append(only(engine.tick(day + s(30))).incident.version)
    accept = action(inc_id, "cuid_d5", CaregiverActionType.ACCEPT, day)
    versions.append(only(engine.handle_action(accept, day + s(31))).incident.version)
    assert versions == [1, 2, 3]


def test_updates_are_snapshots_not_live_references(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    created = only(engine.handle_event(make_event(at=day), day))
    engine.tick(day + s(30))
    assert created.incident.stage is EscalationStage.ZONE_CAREGIVER
    assert created.incident.notified == ["cuid_d4"]


# --- Recuperación tras reinicio ------------------------------------------------------------


def test_restored_engine_resumes_escalation(
    system_config: SystemConfig, engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    created = only(engine.handle_event(make_event(EventType.FALL_CONFIRMED, at=day), day))
    # Simula un reinicio: un motor nuevo a partir del estado persistido.
    restored = IncidentEngine(system_config, FUSION_WINDOW, [created.incident])
    assert restored.tick(day + s(9.9)) == []
    assert only(restored.tick(day + s(10))).incident.stage is EscalationStage.FLOOR


def test_restored_engine_still_deduplicates_known_events(
    system_config: SystemConfig, engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    event = make_event(at=day)
    created = only(engine.handle_event(event, day))
    restored = IncidentEngine(system_config, FUSION_WINDOW, [created.incident])
    assert restored.handle_event(event, day + s(1)) == []


def test_restored_engine_ignores_resolved_incidents(
    system_config: SystemConfig, engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    inc_id = only(engine.handle_event(make_event(at=day), day)).incident.incident_id
    resolved = only(
        engine.handle_action(action(inc_id, "cuid_d4", CaregiverActionType.RESOLVE, day), day)
    )
    restored = IncidentEngine(system_config, FUSION_WINDOW, [resolved.incident])
    assert restored.active_incidents == []


def test_snapshot_republishes_state_without_bumping_versions(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    created = only(engine.handle_event(make_event(at=day), day))
    snapshot = only(engine.snapshot_updates(day + s(1)))
    assert snapshot.reason is UpdateReason.RESTORED
    assert snapshot.incident.version == created.incident.version
    assert snapshot.new_recipients == []


# --- Falsa alarma (docs/decisions/0006) ----------------------------------------------------


def test_false_alarm_stops_escalation_and_asks_for_review(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    created = only(engine.handle_event(make_event(EventType.FALL_SUSPECTED, at=day), day))
    t = day + s(5)
    update = only(engine.handle_event(make_event(EventType.FALL_DISMISSED, at=t), t))
    inc = update.incident
    assert update.reason is UpdateReason.DISMISSED
    assert inc.incident_id == created.incident.incident_id
    assert inc.status is IncidentStatus.PENDING_REVIEW
    assert inc.priority is Severity.LOW
    assert inc.title == "Revisar posible caída"
    assert "se ha levantado" in inc.message
    # Los ya avisados siguen viendo el incidente; no se avisa a nadie nuevo.
    assert inc.notified == ["cuid_d4"]
    assert update.new_recipients == []
    # No escala nunca, pero sigue activo hasta que un cuidador lo cierre.
    assert engine.tick(day + s(3600)) == []
    assert [i.incident_id for i in engine.active_incidents] == [inc.incident_id]


def test_false_alarm_does_not_cancel_a_confirmed_fall(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    engine.handle_event(make_event(EventType.FALL_SUSPECTED, at=day), day)
    engine.handle_event(make_event(EventType.FALL_CONFIRMED, at=day + s(2)), day + s(2))
    t = day + s(5)
    update = only(engine.handle_event(make_event(EventType.FALL_DISMISSED, at=t), t))
    inc = update.incident
    assert update.reason is UpdateReason.EVENT_ADDED
    assert inc.status is IncidentStatus.OPEN
    assert inc.priority is Severity.CRITICAL
    assert inc.title == "Caída confirmada"
    assert inc.message.endswith("El detector indica que la persona se ha levantado.")
    # Sigue escalando con el plazo crítico (10 s desde la creación).
    assert only(engine.tick(day + s(10))).incident.stage is EscalationStage.FLOOR


def test_repeated_false_alarm_on_confirmed_fall_adds_the_note_once(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    engine.handle_event(make_event(EventType.FALL_CONFIRMED, at=day), day)
    for offset in (3, 6):
        t = day + s(offset)
        engine.handle_event(make_event(EventType.FALL_DISMISSED, at=t), t)
    assert engine.active_incidents[0].message.count("se ha levantado") == 1


def test_false_alarm_on_accepted_incident_keeps_it_accepted(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    inc_id = only(engine.handle_event(make_event(at=day), day)).incident.incident_id
    engine.handle_action(action(inc_id, "cuid_d4", CaregiverActionType.ACCEPT, day), day + s(2))
    t = day + s(5)
    update = only(engine.handle_event(make_event(EventType.FALL_DISMISSED, at=t), t))
    assert update.reason is UpdateReason.DISMISSED
    assert update.incident.status is IncidentStatus.ACCEPTED
    assert update.incident.accepted_by == "cuid_d4"
    assert update.incident.priority is Severity.LOW


def test_false_alarm_never_opens_an_incident(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    assert engine.handle_event(make_event(EventType.FALL_DISMISSED, at=day), day) == []
    assert engine.active_incidents == []


def test_false_alarm_outside_fusion_window_is_ignored(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    engine.handle_event(make_event(EventType.FALL_SUSPECTED, at=day), day)
    late = day + FUSION_WINDOW + s(1)
    assert engine.handle_event(make_event(EventType.FALL_DISMISSED, at=late), late) == []
    assert engine.active_incidents[0].status is IncidentStatus.OPEN


def test_false_alarm_in_another_zone_does_not_affect_the_incident(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    engine.handle_event(make_event(EventType.FALL_SUSPECTED, "hab_12", at=day), day)
    t = day + s(3)
    assert engine.handle_event(make_event(EventType.FALL_DISMISSED, "hab_13", at=t), t) == []
    assert engine.active_incidents[0].status is IncidentStatus.OPEN


def test_pending_review_can_be_accepted_and_resolved(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    inc_id = only(engine.handle_event(make_event(at=day), day)).incident.incident_id
    engine.handle_event(make_event(EventType.FALL_DISMISSED, at=day + s(4)), day + s(4))
    accept = action(inc_id, "cuid_d4", CaregiverActionType.ACCEPT, day)
    accepted = only(engine.handle_action(accept, day + s(60)))
    assert accepted.incident.status is IncidentStatus.ACCEPTED
    resolve = action(inc_id, "cuid_d4", CaregiverActionType.RESOLVE, day)
    resolved = only(engine.handle_action(resolve, day + s(120)))
    assert resolved.incident.status is IncidentStatus.RESOLVED
    assert engine.active_incidents == []


def test_new_fall_after_false_alarm_resumes_escalation(
    engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    engine.handle_event(make_event(EventType.FALL_SUSPECTED, at=day), day)
    engine.handle_event(make_event(EventType.FALL_DISMISSED, at=day + s(5)), day + s(5))
    t = day + s(20)
    updates = engine.handle_event(make_event(EventType.FALL_CONFIRMED, at=t), t)
    # Vuelve a estar abierto y crítico; el plazo de zona (10 s) ya ha vencido: escala ya.
    assert [u.reason for u in updates] == [UpdateReason.PRIORITY_RAISED, UpdateReason.ESCALATED]
    assert updates[0].incident.status is IncidentStatus.OPEN
    assert updates[0].incident.priority is Severity.CRITICAL
    assert updates[1].incident.stage is EscalationStage.FLOOR


def test_restored_pending_review_incident_does_not_escalate(
    system_config: SystemConfig, engine: IncidentEngine, make_event: EventFactory, day: datetime
) -> None:
    engine.handle_event(make_event(at=day), day)
    dismissed = only(
        engine.handle_event(make_event(EventType.FALL_DISMISSED, at=day + s(4)), day + s(4))
    )
    restored = IncidentEngine(system_config, FUSION_WINDOW, [dismissed.incident])
    assert restored.tick(day + s(3600)) == []
    assert restored.active_incidents[0].status is IncidentStatus.PENDING_REVIEW
