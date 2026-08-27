"""El excedente exportado mide lo que la microgrid inyecta a la red.

Reemplaza al viejo KPI de *curtailment*, que bajo ``runpp`` no podía medir nada
real —el ``sgen`` es una inyección fija, no hay recorte de generación— y que
además, por el signo invertido de la batería, terminaba reportando la potencia
de carga de la batería como si fuera solar recortada.
"""
from __future__ import annotations

import pytest

from domain.simulation_engine import SimEngine


def test_sin_excedente_no_hay_exportacion(network_service):
    """Con poco sol la red externa alimenta la microgrid: no exporta nada."""
    modelo = network_service.get_network()
    modelo.net.sgen.loc[0, "p_mw"] = 0.001

    resultado = SimEngine.runpp(modelo)

    assert float(modelo.net.res_ext_grid.p_mw.sum()) > 0     # la red aporta
    assert resultado.export_surplus_mw == 0.0


def test_con_mucho_sol_se_exporta_el_sobrante(network_service):
    modelo = network_service.get_network()
    modelo.net.sgen.loc[0, "p_mw"] = 0.5

    resultado = SimEngine.runpp(modelo)
    aporte_red = float(modelo.net.res_ext_grid.p_mw.sum())

    assert aporte_red < 0                                     # la microgrid inyecta
    assert resultado.export_surplus_mw == pytest.approx(-aporte_red, abs=1e-12)


def test_la_carga_de_la_bateria_no_se_reporta_como_exportacion(network_service):
    """El bug viejo: con sol alto reportaba exactamente la potencia de carga de la batería."""
    modelo = network_service.get_network()
    modelo.net.sgen.loc[0, "p_mw"] = 0.5
    modelo.net.storage.loc[0, "p_mw"] = 0.02                  # cargando

    resultado = SimEngine.runpp(modelo)

    assert resultado.export_surplus_mw != pytest.approx(0.02, abs=1e-6)
    assert resultado.export_surplus_mw == pytest.approx(
        -float(modelo.net.res_ext_grid.p_mw.sum()), abs=1e-12
    )


def test_la_autosuficiencia_no_supera_el_100_por_ciento(network_service):
    modelo = network_service.get_network()
    modelo.net.sgen.loc[0, "p_mw"] = 0.5

    resultado = SimEngine.runpp(modelo)

    assert resultado.autosufficiency_pct == 100.0


def test_las_perdidas_son_la_suma_de_las_lineas(network_service):
    modelo = network_service.get_network()

    resultado = SimEngine.runpp(modelo)

    assert resultado.total_losses_mw == pytest.approx(
        float(modelo.net.res_line.pl_mw.sum()), abs=1e-12
    )
    assert set(resultado.voltage_profile) == set(int(i) for i in modelo.net.bus.index)
