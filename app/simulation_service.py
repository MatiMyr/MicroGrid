from __future__ import annotations

from app.network_service import NetworkService
from domain.sim_engine import SimEngine, SimulationResult


class SimulationService:
    """Servicio mínimo de integración entre red y motor de simulación."""

    def __init__(self, network_service: NetworkService | None = None):
        self.network_service = network_service or NetworkService()

    def run_pp(self) -> SimulationResult:
        return SimEngine.runpp(self.network_service.get_network())

    def run_opp(self) -> SimulationResult:
        return SimEngine.runopp(self.network_service.get_network())
