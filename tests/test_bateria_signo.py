"""El signo de la potencia de batería sigue la convención de pandapower.

pandapower modela el elemento ``storage`` con convención de **carga**:
``p_mw > 0`` significa que la batería consume de la red (se carga) y
``p_mw < 0`` que inyecta (se descarga). El proyecto asumía lo contrario, así que
el SoC se movía al revés: una batería cargando se vaciaba.
"""
from __future__ import annotations

import pandapower as pp
import pytest

from domain.entities import Battery
from domain.simulation_engine import SimEngine


def test_potencia_positiva_carga_la_bateria(network_service):
    """``p_mw > 0`` sube el SoC: la batería está tomando energía de la red."""
    modelo = network_service.get_network()
    modelo.net.storage.loc[0, "p_mw"] = 0.02      # 0.02 MW durante 1 h
    modelo.net.storage.loc[0, "max_e_mwh"] = 0.05
    modelo.net.storage.loc[0, "soc_percent"] = 50.0

    resultado = SimEngine.runpp(modelo)

    # 0.025 MWh iniciales + 0.02 MWh = 0.045 MWh sobre 0.05 -> 90 %
    assert resultado.battery_soc_result[0] == 90.0


def test_potencia_negativa_descarga_la_bateria(network_service):
    """``p_mw < 0`` baja el SoC: la batería está entregando energía."""
    modelo = network_service.get_network()
    modelo.net.storage.loc[0, "p_mw"] = -0.02
    modelo.net.storage.loc[0, "max_e_mwh"] = 0.05
    modelo.net.storage.loc[0, "soc_percent"] = 50.0

    resultado = SimEngine.runpp(modelo)

    # 0.025 MWh - 0.02 MWh = 0.005 MWh sobre 0.05 -> 10 %
    assert resultado.battery_soc_result[0] == 10.0


def test_el_signo_coincide_con_el_balance_de_potencia(network_service):
    """Verificación independiente: una batería cargando aumenta lo que aporta la red.

    Es la comprobación que ata el signo a la física y no a la documentación:
    si la convención se invirtiera de nuevo, el balance dejaría de cerrar.
    """
    modelo = network_service.get_network()
    net = modelo.net
    net.storage.loc[0, "p_mw"] = 0.02

    pp.runpp(net, numba=False)

    aporte_red = float(net.res_ext_grid.p_mw.sum())
    consumo = float(net.res_load.p_mw.sum())
    solar = float(net.res_sgen.p_mw.sum())
    perdidas = float(net.res_line.pl_mw.sum())
    almacenamiento = float(net.res_storage.p_mw.sum())

    # red + solar = consumo + almacenamiento + pérdidas
    assert aporte_red + solar == \
        __import__("pytest").approx(consumo + almacenamiento + perdidas, abs=1e-9)
    # Y el almacenamiento aparece del lado del consumo, no del de la generación.
    assert almacenamiento > 0


def test_el_soc_se_recorta_entre_0_y_100(network_service):
    """Una batería llena que sigue cargando no supera el 100 %."""
    modelo = network_service.get_network()
    modelo.net.storage.loc[0, "p_mw"] = 0.02
    modelo.net.storage.loc[0, "max_e_mwh"] = 0.005   # se llena en menos de una hora
    modelo.net.storage.loc[0, "soc_percent"] = 95.0

    resultado = SimEngine.runpp(modelo)

    assert resultado.battery_soc_result[0] == 100.0


def test_bateria_sin_capacidad_conserva_su_soc(network_service):
    """``max_e_mwh = 0`` no puede dividir por cero: el SoC queda como estaba."""
    modelo = network_service.get_network()
    modelo.add_battery(Battery(bus=1, p_mw=0.01, max_e_mwh=0.0, soc_percent=42.0))

    resultado = SimEngine.runpp(modelo)

    assert resultado.battery_soc_result[1] == 42.0
