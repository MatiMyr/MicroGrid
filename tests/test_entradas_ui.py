"""Arreglos de la capa de UI que no se ven desde el dominio.

Cubre el manejo de valores de formulario (donde el 0 se confundía con "sin
valor"), el borrado de redes guardadas y el reparto de posiciones cuando todos
los buses caen en la misma coordenada.
"""
from __future__ import annotations

import pytest

from repositories.json_net_repository import JsonRedRepository
from ui.dashboard import _aviso_sin_solucion, _valor


# ---- el 0 es un valor, no un hueco ----------------------------------------
@pytest.mark.parametrize("dado,default,esperado", [
    (0, 50, 0),                  # SoC 0 %: antes se convertía en 50
    (0.0, -31.4, 0.0),           # latitud 0 (ecuador)
    (0, 24, 0),                  # horas 0
    (None, 50, 50),              # ausente de verdad
    ("", "LITORAL", "LITORAL"),  # texto vacío
    ("   ", "LITORAL", "LITORAL"),
    (-31.4, 0, -31.4),
    ("CUYO", "LITORAL", "CUYO"),
])
def test_valor_solo_cae_al_default_si_falta(dado, default, esperado):
    assert _valor(dado, default) == esperado


# ---- aviso de elementos sin solución --------------------------------------
class _Resultado:
    def __init__(self, buses=(), lineas=()):
        self.buses_sin_solucion = list(buses)
        self.lineas_sin_solucion = list(lineas)


def test_sin_elementos_aislados_no_hay_aviso():
    assert _aviso_sin_solucion([_Resultado()]) == ""
    assert _aviso_sin_solucion([]) == ""


def test_el_aviso_nombra_lo_que_quedo_afuera():
    aviso = _aviso_sin_solucion([_Resultado(buses=[3], lineas=[0, 1])])

    assert "1 bus" in aviso and "2 líneas" in aviso
    assert "sin conexión al nodo slack" in aviso


def test_el_aviso_concuerda_en_numero():
    assert "2 buses" in _aviso_sin_solucion([_Resultado(buses=[3, 4])])
    assert "1 línea" in _aviso_sin_solucion([_Resultado(lineas=[0])])


# ---- borrado de redes guardadas -------------------------------------------
@pytest.fixture
def con_repo_temporal(network_service, tmp_path):
    network_service.net_repo = JsonRedRepository(tmp_path / "redes")
    return network_service


def test_borrar_una_red_la_saca_del_listado(con_repo_temporal):
    red_id = con_repo_temporal.guardar("Para borrar")
    assert [r["id"] for r in con_repo_temporal.listar_guardadas()] == [red_id]

    con_repo_temporal.eliminar_guardada(red_id)

    assert con_repo_temporal.listar_guardadas() == []


def test_borrar_la_red_abierta_corta_el_vinculo_con_el_repositorio(con_repo_temporal):
    """Si siguiera apuntando al id borrado, «Sobrescribir» fallaría al guardar."""
    red_id = con_repo_temporal.guardar("Abierta")
    assert con_repo_temporal.red_id == red_id

    con_repo_temporal.eliminar_guardada(red_id)

    assert con_repo_temporal.red_id is None
    with pytest.raises(ValueError):
        con_repo_temporal.guardar_cambios()


def test_borrar_otra_red_no_afecta_a_la_abierta(con_repo_temporal):
    otra = con_repo_temporal.guardar("Otra")
    con_repo_temporal.cargar_ejemplo()
    abierta = con_repo_temporal.guardar("Abierta")

    con_repo_temporal.eliminar_guardada(otra)

    assert con_repo_temporal.red_id == abierta


def test_el_nombre_visible_se_resuelve_por_id(con_repo_temporal):
    red_id = con_repo_temporal.guardar("Mi barrio")

    assert con_repo_temporal.nombre_guardada(red_id) == "Mi barrio"
    assert con_repo_temporal.nombre_guardada("no-existe") is None


# ---- posiciones coincidentes ----------------------------------------------
def test_buses_en_la_misma_coordenada_se_reparten(network_service):
    """Con span 0 no había nada que reescalar y el grafo recibía píxeles fuera del lienzo."""
    modelo = network_service.get_network()
    for bus in modelo.net.bus.index:
        modelo.set_bus_position(bus, -31.4, -60.5)

    modelo.normalize_positions()

    posiciones = set(modelo.bus_positions().values())
    assert len(posiciones) == len(modelo.net.bus)
    assert all(abs(x) <= 12 and abs(y) <= 12 for x, y in posiciones)
