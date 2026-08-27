"""Un click sobre un bus no puede moverlo.

``net_to_elements`` separa los buses que caen en coordenadas casi coincidentes
para que no queden apilados. Ese corrimiento es solo visual, pero el Editor
guardaba la posición **renderizada** tal cual, y como el JS reenvía el
``dragfree`` como ``tap``, un click y un arrastre llegan iguales: un simple click
sobre un bus apilado lo desplazaba de verdad — y de paso invalidaba la caché de
simulaciones, porque la firma del Editor mira la posición.
"""
from __future__ import annotations

import pytest

from ui.graph_view import bus_pixel_offsets, geo_desde_pixel, net_to_elements


def _posiciones_renderizadas(net) -> dict[int, dict]:
    return {int(e["data"]["id"][1:]): e["position"]
            for e in net_to_elements(net)
            if e["data"]["id"].startswith("b") and "position" in e}


def test_un_tap_devuelve_exactamente_la_posicion_guardada(network_service):
    modelo = network_service.get_network()
    modelo.ensure_positions()

    for bus, pos in _posiciones_renderizadas(modelo.net).items():
        assert geo_desde_pixel(modelo.net, bus, pos["x"], pos["y"]) == \
            pytest.approx(modelo.get_bus_position(bus), abs=1e-4)


def test_el_corrimiento_de_buses_apilados_es_reversible(network_service):
    """El caso que rompía: dos buses en la misma coordenada."""
    modelo = network_service.get_network()
    modelo.set_bus_position(0, 3.0, 4.0)
    modelo.set_bus_position(1, 3.0, 4.0)

    renderizadas = _posiciones_renderizadas(modelo.net)

    # El grafo los separa...
    assert renderizadas[0] != renderizadas[1]
    # ...pero al descontar el corrimiento los dos vuelven a su valor guardado.
    for bus in (0, 1):
        pos = renderizadas[bus]
        assert geo_desde_pixel(modelo.net, bus, pos["x"], pos["y"]) == pytest.approx((3.0, 4.0))


def test_un_arrastre_real_si_cambia_la_posicion(network_service):
    modelo = network_service.get_network()
    modelo.set_bus_position(0, 1.0, 1.0)
    pos = _posiciones_renderizadas(modelo.net)[0]

    movida = geo_desde_pixel(modelo.net, 0, pos["x"] + 68.0, pos["y"])

    assert movida[0] == pytest.approx(3.0)     # 68 px / escala 34 = 2 unidades
    assert movida[1] == pytest.approx(1.0)


def test_un_tap_no_invalida_la_firma_de_la_red(network_service, simulation_service):
    """Reproduce el efecto completo: tap -> misma firma -> el Dashboard sigue al día."""
    modelo = network_service.get_network()
    modelo.set_bus_position(0, 5.0, 5.0)
    modelo.set_bus_position(1, 5.0, 5.0)
    simulation_service.run_corrida(horas=2)

    # Simula el tap: se recalcula la posición y sólo se escribe si cambió.
    for bus, pos in _posiciones_renderizadas(modelo.net).items():
        gx, gy = geo_desde_pixel(modelo.net, bus, pos["x"], pos["y"])
        actual = modelo.get_bus_position(bus)
        if actual is None or abs(actual[0] - gx) > 1e-4 or abs(actual[1] - gy) > 1e-4:
            modelo.set_bus_position(bus, gx, gy)

    assert simulation_service.network_signature() == simulation_service.last_run_signature


def test_los_buses_no_apilados_no_reciben_corrimiento(network_service):
    modelo = network_service.get_network()
    modelo.set_bus_position(0, 0.0, 0.0)
    modelo.set_bus_position(1, 5.0, 5.0)
    modelo.set_bus_position(2, 9.0, 1.0)

    assert set(bus_pixel_offsets(modelo.net).values()) == {(0.0, 0.0)}
