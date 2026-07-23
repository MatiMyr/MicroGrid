from __future__ import annotations

from typing import Any, Dict

import pandapower as pp

from domain.entities import SimulationResult
from domain.network_model import NetworkModel


class SimEngine:
    """Capa de dominio mínima para ejecutar simulaciones sobre una red."""

    @staticmethod
    def runpp(network: NetworkModel, nombre_red: str = "", escenario: str = "") -> SimulationResult:
        pp.runpp(network.net)
        return SimEngine._build_result(network, mode="pp", nombre_red=nombre_red, escenario=escenario)

    @staticmethod
    def runopp(network: NetworkModel, nombre_red: str = "", escenario: str = "") -> SimulationResult:
        try:
            pp.runopp(network.net)
        except Exception:
            # Fallback sencillo: la versión inicial usa el flujo de potencia
            # como base para no bloquear la integración.
            pp.runpp(network.net)
        return SimEngine._build_result(network, mode="opp", nombre_red=nombre_red, escenario=escenario)

    @staticmethod
    def _col_sum(df, col: str) -> float:
        if df is None or col not in df.columns:
            return 0.0
        return float(df[col].sum())

    @staticmethod
    def _battery_soc_result(network: NetworkModel, dt_h: float = 1.0) -> Dict[int, float]:
        """Calcula el SoC resultante de cada batería tras simular un instante.

        Conocimiento eléctrico del dominio: a partir de ``res_storage.p_mw``
        (positivo = descarga, negativo = carga) y la energía almacenada inicial
        derivada de ``soc_percent`` y ``max_e_mwh``, actualiza el estado de carga.
        El resultado permite retomar la cadena de una corrida desde un instante
        cacheado sin tener la corrida en memoria.
        """
        storage = getattr(network.net, "storage", None)
        res_storage = getattr(network.net, "res_storage", None)
        soc: Dict[int, float] = {}
        if storage is None or res_storage is None:
            return soc
        for idx in storage.index:
            max_e = float(storage.at[idx, "max_e_mwh"])
            soc0 = float(storage.at[idx, "soc_percent"])
            if max_e <= 0:
                soc[int(idx)] = soc0
                continue
            e0 = soc0 / 100.0 * max_e
            p_mw = float(res_storage.at[idx, "p_mw"]) if idx in res_storage.index else 0.0
            # Descarga (p>0) reduce la energía almacenada; carga (p<0) la aumenta.
            e1 = e0 - p_mw * dt_h
            e1 = max(0.0, min(max_e, e1))
            soc[int(idx)] = round(e1 / max_e * 100.0, 4)
        return soc

    @staticmethod
    def _build_result(
        network: NetworkModel, mode: str, nombre_red: str = "", escenario: str = ""
    ) -> SimulationResult:
        bus_results = getattr(network.net, "res_bus", None)
        line_results = getattr(network.net, "res_line", None)
        load_results = getattr(network.net, "res_load", None)
        sgen_results = getattr(network.net, "res_sgen", None)
        ext_grid_results = getattr(network.net, "res_ext_grid", None)
        storage_results = getattr(network.net, "res_storage", None)

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

        total_load_mw = SimEngine._col_sum(load_results, "p_mw")
        solar_generation_mw = SimEngine._col_sum(sgen_results, "p_mw")
        total_losses_mw = SimEngine._col_sum(line_results, "pl_mw")

        voltage_profile = {bus_index: values["vm_pu"] for bus_index, values in node_map.items()}
        line_loading_pct = {line_index: values["loading_percent"] for line_index, values in line_map.items()}

        # res_ext_grid p_mw: positivo = la red inyecta a la microgrid, negativo = exportación.
        export_to_grid_mw = max(0.0, -SimEngine._col_sum(ext_grid_results, "p_mw"))

        # res_storage p_mw: positivo = descarga, negativo = carga de batería.
        battery_charging_mw = max(0.0, -SimEngine._col_sum(storage_results, "p_mw"))

        autosufficiency_pct = 0.0
        denominator = total_load_mw + total_losses_mw
        if denominator > 0:
            autosufficiency_pct = min(solar_generation_mw / denominator * 100.0, 100.0)

        curtailment_solar_mw = max(
            0.0,
            solar_generation_mw - total_load_mw - total_losses_mw - export_to_grid_mw - battery_charging_mw,
        )

        return SimulationResult(
            mode=mode,
            total_losses_mw=total_losses_mw,
            voltage_profile=voltage_profile,
            line_loading_pct=line_loading_pct,
            autosufficiency_pct=autosufficiency_pct,
            curtailment_solar_mw=curtailment_solar_mw,
            node_results=node_map,
            line_results=line_map,
            battery_soc_result=SimEngine._battery_soc_result(network),
            nombre_red=nombre_red,
            escenario=escenario,
        )
