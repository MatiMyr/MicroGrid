from __future__ import annotations

import importlib.util
import math
from typing import Any, Dict, List

import pandapower as pp

from domain.entities import SimulationResult
from domain.network_model import NetworkModel


# pandapower usa numba para acelerar el flujo de potencia y, si no está
# instalado, emite una advertencia en CADA corrida. Se detecta una sola vez y se
# pasa el flag explícito: con numba presente se gana la aceleración, sin numba se
# corre igual pero sin ensuciar el log hora tras hora.
_NUMBA_DISPONIBLE = importlib.util.find_spec("numba") is not None


def _num(valor, default: float = 0.0) -> float:
    """Convierte a ``float`` mapeando ``NaN`` a ``default``.

    Ningún ``NaN`` debe escaparse de esta capa: se serializa a un token que no es
    JSON válido y, al volver del navegador convertido en ``null``, rompe
    cualquier comparación numérica río abajo.
    """
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(valor) else valor


class SimEngine:
    """Capa de dominio mínima para ejecutar simulaciones sobre una red."""

    @staticmethod
    def runpp(network: NetworkModel, nombre_red: str = "", escenario: str = "") -> SimulationResult:
        pp.runpp(network.net, numba=_NUMBA_DISPONIBLE)
        return SimEngine._build_result(network, mode="pp", nombre_red=nombre_red, escenario=escenario)

    @staticmethod
    def runopp(network: NetworkModel, nombre_red: str = "", escenario: str = "") -> SimulationResult:
        try:
            pp.runopp(network.net)
        except Exception:
            # Fallback sencillo: la versión inicial usa el flujo de potencia
            # como base para no bloquear la integración.
            pp.runpp(network.net, numba=_NUMBA_DISPONIBLE)
        return SimEngine._build_result(network, mode="opp", nombre_red=nombre_red, escenario=escenario)

    @staticmethod
    def _col_sum(df, col: str) -> float:
        if df is None or col not in df.columns:
            return 0.0
        return float(df[col].sum())

    @staticmethod
    def _battery_soc_result(network: NetworkModel, dt_h: float = 1.0) -> Dict[int, float]:
        """Calcula el SoC resultante de cada batería tras simular un instante.

        Conocimiento eléctrico del dominio: a partir de ``res_storage.p_mw`` y
        la energía almacenada inicial (derivada de ``soc_percent`` y
        ``max_e_mwh``), actualiza el estado de carga.

        **Signo**: pandapower modela el ``storage`` con convención de carga —
        ``p_mw > 0`` significa que la batería *consume* de la red (se está
        cargando) y ``p_mw < 0`` que *inyecta* (se está descargando). Por eso la
        energía almacenada se integra sumando: ``e1 = e0 + p * dt``.

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
            # Carga (p>0) aumenta la energía almacenada; descarga (p<0) la reduce.
            e1 = e0 + p_mw * dt_h
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

        # Los elementos sin camino al nodo slack —aislados, o aguas abajo de algo
        # fuera de servicio— no tienen solución: pandapower devuelve ``NaN``. Se
        # los aparta en vez de dejarlos dentro de los perfiles, donde arrastraban
        # el mínimo y el máximo y, tras pasar por el navegador (que convierte el
        # ``NaN`` en ``null``), llegaban a romper el Dashboard entero.
        node_map: Dict[int, Dict[str, Any]] = {}
        buses_sin_solucion: List[int] = []
        if bus_results is not None:
            for idx, row in bus_results.iterrows():
                vm_pu = float(row.get("vm_pu", 0.0))
                if math.isnan(vm_pu):
                    buses_sin_solucion.append(int(idx))
                    continue
                node_map[int(idx)] = {
                    "vm_pu": vm_pu,
                    "va_degree": _num(row.get("va_degree", 0.0)),
                    "p_mw": _num(row.get("p_mw", 0.0)),
                    "q_mvar": _num(row.get("q_mvar", 0.0)),
                }

        line_map: Dict[int, Dict[str, Any]] = {}
        lineas_sin_solucion: List[int] = []
        if line_results is not None:
            for idx, row in line_results.iterrows():
                if math.isnan(float(row.get("loading_percent", 0.0))):
                    lineas_sin_solucion.append(int(idx))
                    continue
                line_map[int(idx)] = {
                    "p_from_mw": _num(row.get("p_from_mw", 0.0)),
                    "q_from_mvar": _num(row.get("q_from_mvar", 0.0)),
                    "p_to_mw": _num(row.get("p_to_mw", 0.0)),
                    "q_to_mvar": _num(row.get("q_to_mvar", 0.0)),
                    "pl_mw": _num(row.get("pl_mw", 0.0)),
                    "ql_mvar": _num(row.get("ql_mvar", 0.0)),
                    "loading_percent": float(row.get("loading_percent", 0.0)),
                }

        total_load_mw = SimEngine._col_sum(load_results, "p_mw")
        solar_generation_mw = SimEngine._col_sum(sgen_results, "p_mw")
        total_losses_mw = SimEngine._col_sum(line_results, "pl_mw")

        voltage_profile = {bus_index: values["vm_pu"] for bus_index, values in node_map.items()}
        line_loading_pct = {line_index: values["loading_percent"] for line_index, values in line_map.items()}

        autosufficiency_pct = 0.0
        denominator = total_load_mw + total_losses_mw
        if denominator > 0:
            autosufficiency_pct = min(solar_generation_mw / denominator * 100.0, 100.0)

        # res_ext_grid p_mw: positivo = la red externa alimenta a la microgrid;
        # negativo = la microgrid exporta su excedente hacia la red.
        export_surplus_mw = max(0.0, -SimEngine._col_sum(ext_grid_results, "p_mw"))

        return SimulationResult(
            mode=mode,
            total_losses_mw=total_losses_mw,
            voltage_profile=voltage_profile,
            line_loading_pct=line_loading_pct,
            autosufficiency_pct=autosufficiency_pct,
            export_surplus_mw=export_surplus_mw,
            node_results=node_map,
            line_results=line_map,
            battery_soc_result=SimEngine._battery_soc_result(network),
            buses_sin_solucion=buses_sin_solucion,
            lineas_sin_solucion=lineas_sin_solucion,
            nombre_red=nombre_red,
            escenario=escenario,
        )
