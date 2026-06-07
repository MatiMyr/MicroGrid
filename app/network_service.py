from __future__ import annotations

import re

from domain.network_model import Battery, Bus, ExternalGrid, Line, Load, NetworkModel, SolarPanel, Transformer


class NetworkService:
    """Servicio mínimo para exponer una red de ejemplo a la capa de simulación."""

    def __init__(self, model: NetworkModel | None = None):
        self.model = model or self._build_sample_network()

    def get_network(self) -> NetworkModel:
        return self.model

    def apply_instruction(self, instruction: str) -> dict[str, object]:
        text = instruction.lower()
        if "panel solar" in text:
            power_match = re.search(r"(\d+(?:\.\d+)?)\s*kw", text)
            bus_match = re.search(r"nodo\s*(\d+)", text)
            if not power_match or not bus_match:
                raise ValueError("Instrucción de panel solar no reconocida")
            power_kw = float(power_match.group(1))
            bus = int(bus_match.group(1))
            index = self.model.add_solar_panel(SolarPanel(bus=bus, p_mw=power_kw / 1000.0, name=f"Solar-{bus}"))
            return {"type": "solar", "element_index": index, "bus": bus, "p_mw": power_kw / 1000.0}
        raise ValueError("Instrucción no soportada en esta versión mínima")

    def _build_sample_network(self) -> NetworkModel:
        model = NetworkModel()

        model.add_bus(Bus(index=0, vn_kv=0.4, name="Subestación"))
        model.add_bus(Bus(index=1, vn_kv=0.4, name="Nodo 1"))

        model.add_ext_grid(ExternalGrid(bus=0, vm_pu=1.0, va_degree=0.0, name="Grid"))
        model.add_line(Line(from_bus=0, to_bus=1, length_km=0.1, name="Línea 0-1"))

        model.add_load(Load(bus=1, p_mw=0.05, q_mvar=0.01, name="Carga 1"))
        model.add_solar_panel(SolarPanel(bus=1, p_mw=0.03, q_mvar=0.0, name="Panel solar 1"))

        return model
