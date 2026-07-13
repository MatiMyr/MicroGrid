from __future__ import annotations

from app.network_service import NetworkService
from domain.simulation_engine import SimEngine, SimulationResult


class SimulationService:
    """Servicio mínimo de integración entre red y motor de simulación."""

    def __init__(self, network_service: NetworkService | None = None):
        self.network_service = network_service or NetworkService()

    def run_pp(self, nombre_red: str = "", escenario: str = "") -> SimulationResult:
        return SimEngine.runpp(self.network_service.get_network(), nombre_red=nombre_red, escenario=escenario)

    def run_opp(self, nombre_red: str = "", escenario: str = "") -> SimulationResult:
        return SimEngine.runopp(self.network_service.get_network(), nombre_red=nombre_red, escenario=escenario)
