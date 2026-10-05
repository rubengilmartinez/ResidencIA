"""Flujo completo: evento de caída -> MQTT -> orquestador -> backend -> cuidadores.

Plazos de test (tests/e2e/config/escalation.yaml): zona 2 s (1 s crítica), planta 3 s
(2 s crítica). Cada test usa una zona distinta y la limpia al terminar.
"""

from __future__ import annotations

import time
from datetime import datetime

import pytest
from residencia_shared.events import EventType, utc_now
from residencia_shared.internal import EscalationStage
from residencia_shared.topics import event_topic

from .harness import Residence, SystemUnderTest, update_matches, wait_until

pytestmark = pytest.mark.e2e

# Margen para el periodo del tick (0,2 s), la red y la carga de la máquina.
LATE_TOLERANCE_S = 1.5
EARLY_TOLERANCE_S = 0.3
# Del evento publicado a la alerta en el WebSocket del cuidador.
MAX_DELIVERY_LATENCY_S = 1.0


def expected_stages(sut: SystemUnderTest, zone_id: str) -> list[list[str]]:
    """Destinatarios acumulados de cada etapa efectiva (saltando las que no añaden a nadie)."""
    now = utc_now()
    location = sut.config.residence.location(zone_id)
    stages: list[list[str]] = []
    notified: list[str] = []
    for stage in EscalationStage:
        new = [p for p in sut.config.stage_targets(stage, location, now) if p not in notified]
        if new or stage is EscalationStage.ALL_STAFF:
            notified = [*notified, *new]
            stages.append(notified)
    return stages


def test_fall_reaches_caregiver_and_accept_stops_escalation(
    sut: SystemUnderTest, residence: Residence
) -> None:
    zone = "hab_12"
    zone_staff = expected_stages(sut, zone)[0]
    [caregiver] = residence.caregivers(zone_staff[:1])
    try:
        residence.publish(EventType.FALL_SUSPECTED, zone)
        created = caregiver.wait_for(update_matches(zone, reason="created"), what="created")
        incident = created["data"]["incident"]
        incident_id = incident["incident_id"]
        assert incident["priority"] == "high"
        assert incident["notified"] == zone_staff

        residence.publish(EventType.FALL_CONFIRMED, zone, immobile_seconds=10)
        raised = caregiver.wait_for(
            update_matches(incident_id=incident_id, reason="priority_raised"), what="raised"
        )
        assert raised["data"]["incident"]["priority"] == "critical"

        assert residence.accept(incident_id, caregiver.staff_id).status_code == 202
        accepted = caregiver.wait_for(
            update_matches(incident_id=incident_id, status="accepted"), what="accepted"
        )
        assert accepted["data"]["incident"]["accepted_by"] == caregiver.staff_id

        # Con el incidente aceptado no debe escalar, aunque pasen todos los plazos.
        later = caregiver.drain(4.0)
        assert not any(m["data"]["reason"] == "escalated" for m in later), later

        assert residence.resolve(incident_id, caregiver.staff_id).status_code == 202
        caregiver.wait_for(update_matches(incident_id=incident_id, status="resolved"))
        wait_until(lambda: not residence.active_incidents(zone), 5, "incident removed")
    finally:
        caregiver.close()
        residence.resolve_all(zone)


def test_unattended_critical_fall_escalates_on_schedule(
    sut: SystemUnderTest, residence: Residence
) -> None:
    zone = "hab_15"
    stages = expected_stages(sut, zone)
    [first] = residence.caregivers(stages[0][:1])
    try:
        t0 = time.monotonic()
        residence.publish(EventType.FALL_CONFIRMED, zone, immobile_seconds=12)
        created = first.wait_for(update_matches(zone, reason="created"), what="created")
        incident_id = created["data"]["incident"]["incident_id"]
        last = first.wait_for(
            update_matches(incident_id=incident_id, stage=int(EscalationStage.ALL_STAFF)),
            timeout=15,
            what="all staff",
        )
        assert set(last["data"]["incident"]["notified"]) == set(stages[-1])

        # Cronología observada por el primer cuidador: una actualización por etapa.
        timeline = first.updates_for(incident_id)
        notified_seq = [m["data"]["incident"]["notified"] for _, m in timeline]
        assert notified_seq == stages
        # Plazos críticos de las etapas que realmente ocurren (de noche se salta la de planta,
        # así que solo hay un intervalo, el de zona).
        timeouts = [
            sut.config.escalation.zone_caregiver.critical_s,
            sut.config.escalation.floor.critical_s,
        ]
        for (t_prev, m_prev), (t_next, m_next), timeout in zip(
            timeline, timeline[1:], timeouts, strict=False
        ):
            # Según el reloj del orquestador: nunca antes de plazo, como mucho un tick tarde.
            server_gap = (
                datetime.fromisoformat(m_next["data"]["timestamp"])
                - datetime.fromisoformat(m_prev["data"]["timestamp"])
            ).total_seconds()
            assert timeout <= server_gap <= timeout + LATE_TOLERANCE_S
            # Según la llegada al cuidador: incluye la entrega por MQTT y WebSocket.
            assert timeout - EARLY_TOLERANCE_S <= t_next - t_prev <= timeout + LATE_TOLERANCE_S
        # Latencia de extremo a extremo: del evento publicado a la alerta en el cliente.
        assert timeline[0][0] - t0 < MAX_DELIVERY_LATENCY_S

        supervisor = residence.supervisor_on_duty()
        assert residence.accept(incident_id, supervisor).status_code == 202
        accepted = first.wait_for(update_matches(incident_id=incident_id, status="accepted"))
        assert accepted["data"]["incident"]["accepted_by"] == supervisor
    finally:
        first.close()
        residence.resolve_all(zone)


def test_simultaneous_accepts_first_one_wins(sut: SystemUnderTest, residence: Residence) -> None:
    zone = "hab_02"
    everyone = expected_stages(sut, zone)[-1]
    first_id, second_id = everyone[0], everyone[1]
    [observer] = residence.caregivers([first_id])
    try:
        residence.publish(EventType.FALL_CONFIRMED, zone)
        created = observer.wait_for(update_matches(zone, reason="created"))
        incident_id = created["data"]["incident"]["incident_id"]

        assert residence.accept(incident_id, first_id).status_code == 202
        # La segunda llega antes o después de que el backend vea la primera: 202 o 409.
        assert residence.accept(incident_id, second_id).status_code in (202, 409)

        accepted = observer.wait_for(update_matches(incident_id=incident_id, status="accepted"))
        assert accepted["data"]["incident"]["accepted_by"] == first_id
        time.sleep(1.0)
        [current] = residence.active_incidents(zone)
        assert current["accepted_by"] == first_id
    finally:
        observer.close()
        residence.resolve_all(zone)


def test_duplicate_delivery_creates_a_single_incident(
    sut: SystemUnderTest, residence: Residence
) -> None:
    zone = "hab_05"
    try:
        event = residence.publish(EventType.FALL_CONFIRMED, zone)
        residence.publish_raw(event_topic(event), event.model_dump_json())  # misma entrega otra vez
        wait_until(lambda: len(residence.active_incidents(zone)) == 1, 5, "incident")
        time.sleep(1.0)
        [incident] = residence.active_incidents(zone)
        assert incident["event_ids"] == [event.event_id]
    finally:
        residence.resolve_all(zone)


def test_malformed_messages_are_dropped_and_service_keeps_working(
    sut: SystemUnderTest, residence: Residence
) -> None:
    zone = "jardin"
    try:
        residence.publish_raw("residencia/p0/jardin/caidas", "esto no es JSON")
        residence.publish_raw("residencia/p0/jardin/caidas", '{"event_id": "evt_123456"}')
        # Evento válido publicado en un tema que no le corresponde (otra zona).
        stray = residence.publish(EventType.FALL_CONFIRMED, "comedor")
        residence.publish_raw("residencia/p0/jardin/caidas", stray.model_dump_json())
        time.sleep(1.0)
        assert residence.active_incidents(zone) == []

        residence.publish(EventType.FALL_SUSPECTED, zone)
        wait_until(lambda: len(residence.active_incidents(zone)) == 1, 5, "valid incident")
    finally:
        residence.resolve_all(zone)
        residence.resolve_all("comedor")


def test_orchestrator_restart_resumes_open_incidents(
    sut: SystemUnderTest, residence: Residence
) -> None:
    zone = "hab_17"
    stages = expected_stages(sut, zone)
    [caregiver] = residence.caregivers(stages[0][:1])
    try:
        residence.publish(EventType.FALL_SUSPECTED, zone)
        created = caregiver.wait_for(update_matches(zone, reason="created"))
        incident_id = created["data"]["incident"]["incident_id"]

        sut.restart_orchestrator()

        # Tras el reinicio el incidente sigue escalando hasta todo el personal.
        caregiver.wait_for(
            update_matches(incident_id=incident_id, stage=int(EscalationStage.ALL_STAFF)),
            timeout=20,
            what="escalation after restart",
        )
        assert residence.accept(incident_id, caregiver.staff_id).status_code == 202
        caregiver.wait_for(update_matches(incident_id=incident_id, status="accepted"))
    finally:
        caregiver.close()
        residence.resolve_all(zone)
