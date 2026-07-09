from __future__ import annotations

from domain.network_model import Bus, ExternalGrid, Line, Load, NetworkModel, SolarPanel


class NetworkService:
    """Servicio mínimo para exponer una red de ejemplo a la capa de simulación."""

    def __init__(self, model: NetworkModel | None = None):
        self.model = model or self._build_sample_network()

    def get_network(self) -> NetworkModel:
        return self.model

    # Red ejemplo
    def _build_sample_network(self) -> NetworkModel:
        model = NetworkModel()

        model.add_bus(Bus(index=0, vn_kv=0.4, name="Subestación"))
        model.add_bus(Bus(index=1, vn_kv=0.4, name="Nodo 1"))

        model.add_ext_grid(ExternalGrid(bus=0, vm_pu=1.0, va_degree=0.0, name="Grid"))
        model.add_line(Line(from_bus=0, to_bus=1, length_km=0.1, name="Línea 0-1"))

        model.add_load(Load(bus=1, p_mw=0.05, q_mvar=0.01, name="Carga 1"))
        model.add_solar_panel(SolarPanel(bus=1, p_mw=0.03, q_mvar=0.0, name="Panel solar 1"))

        return model
