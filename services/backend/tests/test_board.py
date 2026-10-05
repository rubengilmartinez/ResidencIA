"""Tests del tablero de incidentes del backend."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.board import RESOLVED_RETENTION, IncidentBoard
from residencia_shared.events import EventType, Location, Severity, ZoneType, new_id
from residencia_shared.internal import (
    EscalationStage,
    Incident,
    IncidentStatus,
    IncidentUpdate,
    UpdateReason,
)

T0 = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)


def incident(
    version: int = 1,
    *,
    incident_id: str = "inc_a",
    status: IncidentStatus = IncidentStatus.OPEN,
    priority: Severity = Severity.HIGH,
    notified: list[str] | None = None,
    accepted_by: str | None = None,
    created_at: datetime = T0,
    resolved_at: datetime | None = None,
) -> Incident:
    return Incident(
        incident_id=incident_id,
        version=version,
        category="fall",
        status=status,
        priority=priority,
        location=Location(floor_id="p1", zone_id="hab_12", zone_type=ZoneType.ROOM),
        title="Posible caída",
        message="Posible caída en Habitación 12 (Planta 1).",
        stage=EscalationStage.ZONE_CAREGIVER,
        stage_started_at=created_at,
        notified=notified if notified is not None else ["cuid_d4"],
        accepted_by=accepted_by,
        created_at=created_at,
        updated_at=created_at,
        last_event_at=created_at,
        last_event_type=EventType.FALL_SUSPECTED,
        event_ids=["evt_000001"],
        resolved_at=resolved_at,
    )


def update(inc: Incident, at: datetime = T0) -> IncidentUpdate:
    return IncidentUpdate(
        message_id=new_id("msg"),
        timestamp=at,
        reason=UpdateReason.CREATED,
        new_recipients=[],
        incident=inc,
    )


def test_applies_newer_versions_only() -> None:
    board = IncidentBoard()
    assert board.apply(update(incident(1)))
    assert board.apply(update(incident(2, notified=["cuid_d4", "cuid_d5"])))
    assert not board.apply(update(incident(1)))  # antiguo
    assert not board.apply(update(incident(2)))  # repetido
    current = board.get("inc_a")
    assert current is not None
    assert current.notified == ["cuid_d4", "cuid_d5"]


def test_resolved_incidents_leave_the_active_list_but_are_not_resurrected() -> None:
    board = IncidentBoard()
    board.apply(update(incident(1)))
    board.apply(update(incident(2, status=IncidentStatus.RESOLVED, resolved_at=T0)))
    assert board.active() == []
    # Un mensaje antiguo que llega tarde no vuelve a abrir el incidente.
    assert not board.apply(update(incident(1)))
    assert board.active() == []


def test_resolved_incidents_are_pruned_after_retention() -> None:
    board = IncidentBoard()
    board.apply(update(incident(2, status=IncidentStatus.RESOLVED, resolved_at=T0)))
    later = T0 + RESOLVED_RETENTION + timedelta(seconds=1)
    board.apply(update(incident(1, incident_id="inc_b"), at=later))
    assert board.get("inc_a") is None


def test_remove_drops_active_incident_once() -> None:
    board = IncidentBoard()
    board.apply(update(incident(1)))
    assert board.remove("inc_a") is not None
    assert board.remove("inc_a") is None
    assert board.active() == []


def test_active_is_sorted_by_priority_then_age() -> None:
    board = IncidentBoard()
    board.apply(update(incident(incident_id="inc_oldhigh", created_at=T0)))
    board.apply(
        update(
            incident(
                incident_id="inc_newcritical",
                priority=Severity.CRITICAL,
                created_at=T0 + timedelta(minutes=1),
            )
        )
    )
    board.apply(update(incident(incident_id="inc_newhigh", created_at=T0 + timedelta(minutes=2))))
    assert [i.incident_id for i in board.active()] == [
        "inc_newcritical",
        "inc_oldhigh",
        "inc_newhigh",
    ]


def test_audience_includes_notified_and_who_accepted() -> None:
    inc = incident(notified=["cuid_d4"], accepted_by="sup_d", status=IncidentStatus.ACCEPTED)
    assert IncidentBoard.audience(inc) == {"cuid_d4", "sup_d"}


def test_active_for_filters_by_staff() -> None:
    board = IncidentBoard()
    board.apply(update(incident(incident_id="inc_a", notified=["cuid_d4"])))
    board.apply(update(incident(incident_id="inc_b", notified=["cuid_d5"])))
    assert [i.incident_id for i in board.active_for("cuid_d5")] == ["inc_b"]
    assert board.active_for("cuid_d1") == []
