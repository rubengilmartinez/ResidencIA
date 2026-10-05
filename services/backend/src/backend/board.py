"""Copia local del estado de los incidentes, alimentada por el orquestador.

El backend nunca decide nada sobre un incidente: solo refleja la última versión que ha
publicado el orquestador. Las versiones permiten descartar mensajes duplicados o que
lleguen desordenados (QoS 1 y mensajes retenidos pueden repetir estados antiguos).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from residencia_shared.internal import Incident, IncidentStatus, IncidentUpdate

# Los incidentes resueltos se conservan un tiempo para que un mensaje antiguo que llegue
# tarde no los "resucite".
RESOLVED_RETENTION = timedelta(minutes=10)


class IncidentBoard:
    def __init__(self) -> None:
        self._incidents: dict[str, Incident] = {}

    def apply(self, update: IncidentUpdate) -> bool:
        """Aplica una actualización. Devuelve False si es antigua o repetida."""
        incident = update.incident
        current = self._incidents.get(incident.incident_id)
        if current is not None and incident.version <= current.version:
            return False
        self._incidents[incident.incident_id] = incident
        self._prune(update.timestamp)
        return True

    def remove(self, incident_id: str) -> Incident | None:
        """Elimina un incidente activo (el orquestador ha borrado su estado retenido)."""
        incident = self._incidents.get(incident_id)
        if incident is None or incident.status is IncidentStatus.RESOLVED:
            return None
        del self._incidents[incident_id]
        return incident

    def get(self, incident_id: str) -> Incident | None:
        return self._incidents.get(incident_id)

    def active(self) -> list[Incident]:
        """Incidentes no resueltos, los más prioritarios y antiguos primero."""
        active = [i for i in self._incidents.values() if i.status is not IncidentStatus.RESOLVED]
        return sorted(active, key=lambda i: (-i.priority.rank, i.created_at))

    def active_for(self, staff_id: str) -> list[Incident]:
        return [i for i in self.active() if staff_id in self.audience(i)]

    @staticmethod
    def audience(incident: Incident) -> set[str]:
        """Quién debe recibir los cambios de un incidente: todos los avisados y quien lo
        aceptó o resolvió."""
        people = set(incident.notified)
        people.update(p for p in (incident.accepted_by, incident.resolved_by) if p is not None)
        return people

    def _prune(self, now: datetime) -> None:
        cutoff = now - RESOLVED_RETENTION
        self._incidents = {
            incident_id: inc
            for incident_id, inc in self._incidents.items()
            if inc.status is not IncidentStatus.RESOLVED
            or inc.resolved_at is None
            or inc.resolved_at >= cutoff
        }
