"""Validación de las salidas contra resultados esperados independientes.

A diferencia del resto de la suite —que fija el comportamiento de los arreglos—
acá se comprueba que lo que el proyecto *reporta* es la física correcta, usando
referencias que no salen del propio código:

- una red de dos buses con solución analítica cerrada,
- conservación de potencia activa en las redes reales,
- identidad contra lo que dice pandapower directamente,
- invariantes cualitativos de una red radial de baja tensión.
"""
from __future__ import annotations

import math

import networkx as nx
import pandapower as pp
import pytest

from app.network_service import NetworkService
from domain.entities import Bus, ExternalGrid, Load
from domain.network_model import NetworkModel
from domain.profile_builder import ProfileBuilder
from domain.simulation_engine import SimEngine

SIMBENCH = [
    "1-LV-rural1--0-no_sw",
    "1-LV-rural2--0-no_sw",
    "1-LV-rural3--0-no_sw",
    "1-LV-semiurb4--0-no_sw",
    "1-LV-urban6--0-no_sw",
]


@pytest.fixture(scope="module")
def redes_simbench():
    """Carga cada red SimBench una sola vez para todo el módulo."""
    cache = {}
    for codigo in SIMBENCH:
        servicio = NetworkService()
        servicio.cargar_desde_simbench(codigo)
        cache[codigo] = servicio.get_network()
    return cache


# ---- caso analítico --------------------------------------------------------
def _dos_buses(largo_km: float, r_ohm_per_km: float, p_mw: float) -> NetworkModel:
    modelo = NetworkModel()
    modelo.add_bus(Bus(index=0, vn_kv=0.4, name="Slack"))
    modelo.add_bus(Bus(index=1, vn_kv=0.4, name="Carga"))
    modelo.add_ext_grid(ExternalGrid(bus=0, vm_pu=1.0))
    pp.create_line_from_parameters(
        modelo.net, index=0, from_bus=0, to_bus=1, length_km=largo_km,
        r_ohm_per_km=r_ohm_per_km,
        # Reactancia despreciable en vez de cero: pandapower divide por x al
        # inicializar con flujo de continua y con x=0 explota.
        x_ohm_per_km=1e-6, c_nf_per_km=0.0, g_us_per_km=0.0, max_i_ka=1.0,
    )
    modelo.add_load(Load(bus=1, p_mw=p_mw, q_mvar=0.0))
    return modelo


def _analitico(v_ll: float, r_ohm: float, p_total_w: float) -> tuple[float, float]:
    """Solución cerrada de una línea resistiva con carga a factor de potencia 1.

    Por fase, con ``v1 = V/raiz(3)``, ``p = P/3`` y ``i = p/v2``:

        v1 = v2 + i*R  ->  v2^2 - v1*v2 + p*R = 0  ->  v2 = (v1 + sqrt(v1^2 - 4pR)) / 2

    Devuelve ``(tensión en pu del bus de carga, pérdidas en MW)``.
    """
    v1 = v_ll / math.sqrt(3.0)
    p = p_total_w / 3.0
    v2 = (v1 + math.sqrt(v1 * v1 - 4.0 * p * r_ohm)) / 2.0
    perdidas_w = 3.0 * (p / v2) ** 2 * r_ohm
    return v2 / v1, perdidas_w / 1e6


@pytest.mark.parametrize("largo_km,r_ohm_per_km,p_mw", [
    (0.10, 0.642, 0.020),
    (0.25, 0.642, 0.050),
    (0.50, 0.320, 0.080),
    (1.00, 0.208, 0.100),
])
def test_dos_buses_contra_solucion_analitica(largo_km, r_ohm_per_km, p_mw):
    v_esperada, perdidas_esperadas = _analitico(400.0, r_ohm_per_km * largo_km, p_mw * 1e6)

    resultado = SimEngine.runpp(_dos_buses(largo_km, r_ohm_per_km, p_mw))

    assert resultado.voltage_profile[1] == pytest.approx(v_esperada, rel=1e-6)
    assert resultado.total_losses_mw == pytest.approx(perdidas_esperadas, rel=1e-5)


def test_las_perdidas_crecen_con_el_cuadrado_de_la_carga():
    """Al duplicar la carga las pérdidas se cuadruplican (algo más, porque baja la tensión)."""
    perdidas = [SimEngine.runpp(_dos_buses(0.2, 0.642, p)).total_losses_mw
                for p in (0.025, 0.050, 0.100)]

    for anterior, siguiente in zip(perdidas, perdidas[1:]):
        assert 4.0 < siguiente / anterior < 4.6


# ---- conservación de energía ----------------------------------------------
@pytest.mark.parametrize("codigo", SIMBENCH)
def test_conservacion_de_potencia_activa(redes_simbench, codigo):
    """red_externa + solar = consumo + baterías + pérdidas, para cada red real."""
    net = redes_simbench[codigo].copy().net
    pp.runpp(net, numba=False)

    entra = float(net.res_ext_grid.p_mw.sum()) + float(net.res_sgen.p_mw.sum())
    sale = (float(net.res_load.p_mw.sum())
            + float(net.res_storage.p_mw.sum())
            + float(net.res_line.pl_mw.sum())
            + float(net.res_trafo.pl_mw.sum()))

    assert entra == pytest.approx(sale, abs=1e-9)


def test_conservacion_en_la_red_de_ejemplo(network_service):
    net = network_service.get_network().net
    pp.runpp(net, numba=False)

    entra = float(net.res_ext_grid.p_mw.sum()) + float(net.res_sgen.p_mw.sum())
    sale = (float(net.res_load.p_mw.sum()) + float(net.res_storage.p_mw.sum())
            + float(net.res_line.pl_mw.sum()))

    assert entra == pytest.approx(sale, abs=1e-9)


# ---- el proyecto no distorsiona la solución -------------------------------
@pytest.mark.parametrize("codigo", SIMBENCH)
def test_los_indicadores_coinciden_con_pandapower(redes_simbench, codigo):
    modelo = redes_simbench[codigo].copy()

    resultado = SimEngine.runpp(modelo)
    net = modelo.net

    assert resultado.total_losses_mw == float(net.res_line.pl_mw.sum())
    assert min(resultado.voltage_profile.values()) == float(net.res_bus.vm_pu.min())
    assert max(resultado.line_loading_pct.values()) == float(net.res_line.loading_percent.max())
    assert resultado.export_surplus_mw == max(0.0, -float(net.res_ext_grid.p_mw.sum()))
    assert len(resultado.voltage_profile) == len(net.bus)
    assert len(resultado.line_loading_pct) == len(net.line)


# ---- invariantes de una red radial de baja tensión ------------------------
def _grafo(net) -> nx.Graph:
    g = nx.Graph()
    for _, fila in net.line.iterrows():
        if fila["in_service"]:
            g.add_edge(int(fila["from_bus"]), int(fila["to_bus"]))
    for _, fila in net.trafo.iterrows():
        g.add_edge(int(fila["hv_bus"]), int(fila["lv_bus"]))
    return g


@pytest.mark.parametrize("codigo", SIMBENCH)
def test_la_tension_cae_alejandose_del_slack(redes_simbench, codigo):
    """Sin generación distribuida, ningún bus puede tener más tensión que su padre.

    Con la PV encendida esto **no** vale, y no es un error: la inyección
    distribuida invierte el flujo y levanta la tensión hacia los nodos con
    paneles. Es el fenómeno clásico de sobretensión por PV en redes de BT.
    """
    modelo = redes_simbench[codigo].copy()
    net = modelo.net
    if len(net.sgen):
        net.sgen["in_service"] = False
    pp.runpp(net, numba=False)

    slack = int(net.ext_grid.bus.iloc[0])
    subidas = 0
    for camino in nx.single_source_shortest_path(_grafo(net), slack).values():
        for previo, siguiente in zip(camino, camino[1:]):
            if float(net.res_bus.at[siguiente, "vm_pu"]) > \
                    float(net.res_bus.at[previo, "vm_pu"]) + 1e-9:
                subidas += 1

    assert subidas == 0


@pytest.mark.parametrize("codigo", SIMBENCH)
def test_la_tension_minima_sigue_el_perfil_de_carga(redes_simbench, codigo):
    """Sin generación distribuida, la tensión mínima es imagen espejo de la demanda."""
    modelo = redes_simbench[codigo].copy()
    if len(modelo.net.sgen):
        modelo.net.sgen["in_service"] = False
    perfil = ProfileBuilder().build_load_profile("residencial", 24, "LITORAL")

    vmins = []
    for factor in perfil:
        modelo.apply_load_scaling(factor)
        vmins.append(min(SimEngine.runpp(modelo).voltage_profile.values()))

    hora_pico = max(range(24), key=lambda h: perfil[h])
    hora_vmin = min(range(24), key=lambda h: vmins[h])
    assert hora_vmin == hora_pico
    assert _correlacion(perfil, vmins) < -0.999


def _correlacion(xs, ys) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return cov / (sx * sy) if sx and sy else 0.0


# ---- reuso de caché entre corridas ----------------------------------------
def test_la_segunda_corrida_no_recalcula_nada(simulation_service):
    """Una corrida idéntica debe salir entera de la caché y dar los mismos números."""
    primera = simulation_service.run_corrida(horas=24)
    tamanio = simulation_service.sim_repo.tamanio()["instantes"]

    segunda = simulation_service.run_corrida(horas=24)

    assert simulation_service.sim_repo.tamanio()["instantes"] == tamanio
    for a, b in zip(primera["resultados"], segunda["resultados"]):
        assert a.total_losses_mw == b.total_losses_mw
        assert a.voltage_profile == b.voltage_profile
        assert a.autosufficiency_pct == b.autosufficiency_pct
        assert a.export_surplus_mw == b.export_surplus_mw
