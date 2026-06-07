from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

import pandapower as pp

from domain.network_model import NetworkModel


@dataclass
class SimulationResult:
    """Resultado mínimo de simulación para visualización inicial."""

    mode: str
    total_losses_mw: float
    voltage_profile: Dict[int, float]
    line_loading_pct: Dict[int, float]
    autosufficiency_pct: float
    curtailment_solar_mw: float
    node_results: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    line_results: Dict[int, Dict[str, Any]] = field(default_factory=dict)


class SimEngine:
    """Capa de dominio mínima para ejecutar simulaciones sobre una red."""

    @staticmethod
    def runpp(network: NetworkModel) -> SimulationResult:
        pp.runpp(network.net)
        return SimEngine._build_result(network, mode="pp")

    @staticmethod
    def runopp(network: NetworkModel) -> SimulationResult:
        try:
            pp.runopp(network.net)
        except Exception:
            # Fallback sencillo: la versión inicial usa el flujo de potencia
            # como base para no bloquear la integración.
            pp.runpp(network.net)
        return SimEngine._build_result(network, mode="opp")

    @staticmethod
    def _build_result(network: NetworkModel, mode: str) -> SimulationResult:
        bus_results = getattr(network.net, "res_bus", None)
        line_results = getattr(network.net, "res_line", None)
        load_results = getattr(network.net, "res_load", None)
        sgen_results = getattr(network.net, "res_sgen", None)

        node_map: Dict[int, Dict[str, Any]] = {}
        if bus_results is not None:
            for idx, row in bus_results.iterrows():
                node_map[int(idx)] = {
                    "vm_pu": float(row.get("vm_pu", 0.0)),
                    "va_degree": float(row.get("va_degree", 0.0)),
                    "p_mw": float(row.get("p_mw", 0.0)),
                    "q_mvar": float(row.get("q_mvar", 0.0)),
                }

        line_map: Dict[int, Dict[str, Any]] = {}
        if line_results is not None:
            for idx, row in line_results.iterrows():
                line_map[int(idx)] = {
                    "p_from_mw": float(row.get("p_from_mw", 0.0)),
                    "q_from_mvar": float(row.get("q_from_mvar", 0.0)),
                    "p_to_mw": float(row.get("p_to_mw", 0.0)),
                    "q_to_mvar": float(row.get("q_to_mvar", 0.0)),
                    "pl_mw": float(row.get("pl_mw", 0.0)),
                    "ql_mvar": float(row.get("ql_mvar", 0.0)),
                    "loading_percent": float(row.get("loading_percent", 0.0)),
                }

        total_load_mw = 0.0
        if load_results is not None:
            total_load_mw += float(load_results.get("p_mw", 0.0).sum())
        if sgen_results is not None:
            solar_generation_mw = float(sgen_results.get("p_mw", 0.0).sum())
        else:
            solar_generation_mw = 0.0

        total_losses_mw = 0.0
        if line_results is not None:
            total_losses_mw = float(line_results.get("pl_mw", 0.0).sum())

        voltage_profile = {bus_index: values["vm_pu"] for bus_index, values in node_map.items()}
        line_loading_pct = {line_index: values["loading_percent"] for line_index, values in line_map.items()}

        autosufficiency_pct = 0.0
        if total_load_mw > 0:
            autosufficiency_pct = (solar_generation_mw / total_load_mw) * 100.0

        curtailment_solar_mw = max(0.0, solar_generation_mw - total_load_mw)

        return SimulationResult(
            mode=mode,
            total_losses_mw=total_losses_mw,
            voltage_profile=voltage_profile,
            line_loading_pct=line_loading_pct,
            autosufficiency_pct=autosufficiency_pct,
            curtailment_solar_mw=curtailment_solar_mw,
            node_results=node_map,
            line_results=line_map,
        )
