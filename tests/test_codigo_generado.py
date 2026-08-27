"""El código generado reconstruye la red sin perder nada eléctrico.

El Editor regenera este script después de cada acción y lo describe como "la
fuente de verdad de la red", así que apretar «Ejecutar código» tiene que dejar
una red equivalente. Antes no emitía ``in_service``, la regulación del
transformador, los interruptores, los índices ni los límites de OPF: un click
reactivaba elementos fuera de servicio y desarmaba el tap del trafo.
"""
from __future__ import annotations

import pandapower as pp
import pytest

from app.network_service import NetworkService

REDES_SIMBENCH = [
    "1-LV-rural1--0-no_sw",
    "1-LV-rural3--0-no_sw",
    "1-LV-semiurb4--0-no_sw",
    "1-LV-urban6--0-no_sw",
]


def _fisica(net) -> tuple[float, float, float]:
    pp.runpp(net, numba=False)
    return (
        float(net.res_line.pl_mw.sum()),
        float(net.res_bus.vm_pu.min()),
        float(net.res_ext_grid.p_mw.sum()),
    )


def test_round_trip_de_la_red_de_ejemplo(network_service):
    original = _fisica(network_service.get_network().net)

    network_service.aplicar_codigo(network_service.generar_codigo())

    assert _fisica(network_service.get_network().net) == pytest.approx(original, abs=1e-12)


@pytest.mark.parametrize("codigo", REDES_SIMBENCH)
def test_round_trip_de_redes_simbench(codigo):
    """Con elementos fuera de servicio y un tap fuera del neutro, que es lo que se perdía."""
    servicio = NetworkService()
    servicio.cargar_desde_simbench(codigo)
    net = servicio.get_network().net
    net.line.loc[net.line.index[0], "in_service"] = False
    net.load.loc[net.load.index[0], "in_service"] = False
    net.trafo.loc[net.trafo.index[0], "tap_pos"] = 2.0
    original = _fisica(net)

    servicio.aplicar_codigo(servicio.generar_codigo())
    reconstruida = servicio.get_network().net

    assert _fisica(reconstruida) == pytest.approx(original, abs=1e-12)
    assert int((~reconstruida.line.in_service).sum()) == 1
    assert int((~reconstruida.load.in_service).sum()) == 1
    assert list(reconstruida.trafo.tap_side) == list(net.trafo.tap_side)
    assert list(reconstruida.trafo.tap_pos) == [2.0]


def test_conserva_los_indices_de_los_elementos(network_service):
    """Si los índices se renumeraran, el panel de detalle apuntaría a otro elemento."""
    modelo = network_service.get_network()
    modelo.remove_element("load", 0)          # deja un hueco en la numeración
    indices = {t: list(getattr(modelo.net, t).index)
               for t in ("bus", "line", "load", "sgen", "storage", "ext_grid")}

    network_service.aplicar_codigo(network_service.generar_codigo())
    net = network_service.get_network().net

    assert {t: list(getattr(net, t).index) for t in indices} == indices


def test_conserva_los_limites_de_opf(network_service):
    """``min_vm_pu`` y compañía no existen en una red vacía: hay que crearlas al reconstruir."""
    modelo = network_service.get_network()
    modelo.set_field("bus", 0, "min_vm_pu", 0.93)
    modelo.set_field("bus", 0, "max_vm_pu", 1.07)
    modelo.set_field("line", 0, "max_loading_percent", 80.0)

    network_service.aplicar_codigo(network_service.generar_codigo())
    net = network_service.get_network().net

    assert float(net.bus.at[0, "min_vm_pu"]) == 0.93
    assert float(net.bus.at[0, "max_vm_pu"]) == 1.07
    assert float(net.line.at[0, "max_loading_percent"]) == 80.0


def test_conserva_los_interruptores(network_service):
    modelo = network_service.get_network()
    pp.create_switch(modelo.net, bus=1, element=1, et="l", closed=False, name="Seccionador")

    network_service.aplicar_codigo(network_service.generar_codigo())
    net = network_service.get_network().net

    assert len(net.switch) == 1
    assert bool(net.switch.at[0, "closed"]) is False
    assert net.switch.at[0, "et"] == "l"


def test_conserva_valores_chicos_sin_perder_precision(network_service):
    """El redondeo por decimales fijos degradaba los valores chicos; ahora es por cifras."""
    modelo = network_service.get_network()
    modelo.set_field("line", 0, "length_km", 0.0123456789)

    network_service.aplicar_codigo(network_service.generar_codigo())
    net = network_service.get_network().net

    assert float(net.line.at[0, "length_km"]) == pytest.approx(0.0123456789, rel=1e-11)


def test_el_codigo_generado_es_estable(network_service):
    """Generar dos veces seguidas da lo mismo: si no, el Editor 'parpadearía' solo."""
    primero = network_service.generar_codigo()

    assert network_service.generar_codigo() == primero
