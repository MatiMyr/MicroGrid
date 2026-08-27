"""Un bus sin camino al slack no puede contaminar los resultados.

pandapower devuelve ``NaN`` para los elementos que quedan fuera de la parte
resuelta de la red. Ese ``NaN`` recorría todo el sistema: arrastraba el mínimo y
el máximo de tensión, pintaba el bus de rojo como si fuera una violación grave,
se escribía en la caché como un token que no es JSON válido y, al volver del
navegador convertido en ``null``, rompía el callback del Dashboard con un 500
mientras el cartel anunciaba "Corrida completa".
"""
from __future__ import annotations

import json
import math

import pytest

from domain.entities import Bus
from domain.simulation_engine import SimEngine
from ui.graph_view import net_to_elements

GRIS = "#9e9e9e"


@pytest.fixture
def con_bus_aislado(network_service):
    """Red de ejemplo más un bus suelto, como al agregarlo desde el Editor."""
    modelo = network_service.get_network()
    idx = modelo.add_bus(Bus(vn_kv=0.4, name="Aislado"))
    return modelo, idx


def test_el_bus_aislado_no_entra_al_perfil_de_tension(con_bus_aislado):
    modelo, idx = con_bus_aislado

    resultado = SimEngine.runpp(modelo)

    assert idx not in resultado.voltage_profile
    assert resultado.buses_sin_solucion == [idx]


def test_ningun_indicador_queda_en_nan(con_bus_aislado):
    modelo, _ = con_bus_aislado

    resultado = SimEngine.runpp(modelo)

    assert not any(math.isnan(v) for v in resultado.voltage_profile.values())
    assert not any(math.isnan(v) for v in resultado.line_loading_pct.values())
    assert not math.isnan(resultado.total_losses_mw)
    for valores in resultado.node_results.values():
        assert not any(math.isnan(v) for v in valores.values())


def test_una_linea_fuera_de_servicio_aisla_su_seccion(network_service):
    modelo = network_service.get_network()
    modelo.net.line.loc[0, "in_service"] = False

    resultado = SimEngine.runpp(modelo)

    # Sólo queda resuelto el bus del slack; el resto pierde el camino.
    assert set(resultado.voltage_profile) == {0}
    assert resultado.buses_sin_solucion == [1, 2]
    assert resultado.lineas_sin_solucion == [0, 1]
    assert resultado.line_loading_pct == {}


def test_el_json_de_la_cache_es_valido(con_bus_aislado):
    """Un ``NaN`` suelto genera un token que ningún lector JSON estricto acepta."""
    modelo, _ = con_bus_aislado
    resultado = SimEngine.runpp(modelo)

    crudo = json.dumps(resultado.to_cache_dict())

    assert "NaN" not in crudo
    # parse_constant se dispara justamente ante NaN / Infinity.
    json.loads(crudo, parse_constant=_rechazar)


def _rechazar(token):
    raise AssertionError(f"token no estándar en el JSON: {token}")


def test_el_grafo_pinta_el_bus_sin_solucion_en_gris(con_bus_aislado):
    """Gris de "sin dato": antes salía rojo, como una violación crítica de tensión."""
    modelo, idx = con_bus_aislado
    resultado = SimEngine.runpp(modelo)

    elementos = {e["data"]["id"]: e["data"]
                 for e in net_to_elements(modelo.net,
                                          voltage_profile=resultado.voltage_profile,
                                          line_loading=resultado.line_loading_pct)}

    assert elementos[f"b{idx}"]["color"] == GRIS
    assert "sin conexión" in elementos[f"b{idx}"]["label"]
    assert elementos["b0"]["color"] != GRIS          # el resto sí tiene solución


def test_sin_simular_ningun_bus_se_marca_como_sin_solucion(con_bus_aislado):
    """Antes de correr nada, todos los buses son "sin simular", no "sin conexión"."""
    modelo, _ = con_bus_aislado

    colores = {e["data"]["id"]: e["data"]["color"]
               for e in net_to_elements(modelo.net) if e["data"]["id"].startswith("b")}

    assert set(colores.values()) == {"#2a78d6"}


def test_la_corrida_completa_se_reconstruye_desde_la_cache(con_bus_aislado, simulation_service):
    modelo, idx = con_bus_aislado

    corrida = simulation_service.run_corrida(horas=3)
    recuperada = simulation_service.cargar_corrida(corrida["run_id"])

    assert len(recuperada) == 3
    assert all(r.buses_sin_solucion == [idx] for r in recuperada)
    assert all(idx not in r.voltage_profile for r in recuperada)


def test_el_store_del_dashboard_no_lleva_huecos(con_bus_aislado, simulation_service):
    """El diccionario que viaja al navegador tiene que ser numérico de punta a punta.

    Es el paso exacto donde se rompía: Dash serializa el ``NaN`` como ``null``,
    vuelve como ``None`` y ``min()`` lanza ``TypeError``.
    """
    modelo, _ = con_bus_aislado
    corrida = simulation_service.run_corrida(horas=2)

    for r in corrida["resultados"]:
        valores = list(r.voltage_profile.values()) + list(r.line_loading_pct.values())
        assert all(isinstance(v, float) and not math.isnan(v) for v in valores)
        assert min(r.voltage_profile.values()) > 0     # la comparación no explota
