"""El tipo de consumidor es un atributo de cada carga, no de la corrida.

Antes la corrida recibía un único ``tipo_carga`` y lo aplicaba a toda la red, así
que no se podía representar un barrio con viviendas, comercios e industria
mezclados. Peor: si había caché de CAMMESA, su curva regional tenía precedencia y
el desplegable de la UI quedaba inerte.
"""
from __future__ import annotations

import pytest

from domain.entities import TIPO_CARGA_POR_DEFECTO, TIPOS_CARGA, Load
from domain.profile_builder import ProfileBuilder


def test_una_carga_nueva_arranca_con_el_tipo_por_defecto(network_service):
    modelo = network_service.get_network()

    assert set(modelo.tipos_de_carga().values()) == {TIPO_CARGA_POR_DEFECTO}


def test_cada_carga_puede_tener_su_propio_tipo(network_service):
    modelo = network_service.get_network()
    modelo.set_tipo_de_carga(0, "industrial")
    modelo.add_load(Load(bus=2, p_mw=0.01, perfil_tipo="comercial"))

    assert modelo.tipos_de_carga() == {0: "industrial", 1: "residencial", 2: "comercial"}


def test_un_tipo_desconocido_se_ignora(network_service):
    modelo = network_service.get_network()
    modelo.set_tipo_de_carga(0, "comercial")

    modelo.set_tipo_de_carga(0, "no_existe")

    assert modelo.tipo_de_carga(0) == "comercial"


def test_una_red_sin_la_columna_usa_el_tipo_por_defecto(network_service):
    """Las redes importadas y las guardadas antes del cambio no traen la columna."""
    modelo = network_service.get_network()
    modelo.net.load.drop(columns=["perfil_tipo"], inplace=True)

    assert modelo.tipo_de_carga(0) == TIPO_CARGA_POR_DEFECTO


def test_cada_carga_se_escala_con_la_curva_de_su_tipo(network_service):
    modelo = network_service.get_network()
    modelo.set_tipo_de_carga(0, "industrial")
    modelo.set_tipo_de_carga(1, "comercial")

    modelo.apply_load_scaling_por_tipo({"residencial": 0.4, "comercial": 0.9, "industrial": 0.7})

    assert list(modelo.net.load.scaling) == [0.7, 0.9]


def test_la_corrida_usa_curvas_distintas_por_tipo(network_service, simulation_service):
    """Dos redes iguales salvo el tipo de sus cargas dan resultados distintos."""
    modelo = network_service.get_network()
    corrida_residencial = simulation_service.run_corrida(horas=24)

    for idx in modelo.net.load.index:
        modelo.set_tipo_de_carga(idx, "industrial")
    corrida_industrial = simulation_service.run_corrida(horas=24)

    perdidas_r = [r.total_losses_mw for r in corrida_residencial["resultados"]]
    perdidas_i = [r.total_losses_mw for r in corrida_industrial["resultados"]]
    assert perdidas_r != perdidas_i


def test_el_tipo_forma_parte_de_la_clave_de_cache(network_service, simulation_service):
    modelo = network_service.get_network()
    antes = simulation_service._hash_instante(modelo, "pp")

    modelo.set_tipo_de_carga(0, "industrial")

    assert simulation_service._hash_instante(modelo, "pp") != antes


def test_el_tipo_sobrevive_al_codigo_generado(network_service):
    modelo = network_service.get_network()
    modelo.set_tipo_de_carga(0, "industrial")
    modelo.set_tipo_de_carga(1, "comercial")

    network_service.aplicar_codigo(network_service.generar_codigo())

    assert network_service.get_network().tipos_de_carga() == {0: "industrial", 1: "comercial"}


def test_el_tipo_sobrevive_a_guardar_y_abrir(network_service, tmp_path):
    from repositories.json_net_repository import JsonRedRepository

    network_service.net_repo = JsonRedRepository(tmp_path / "redes")
    modelo = network_service.get_network()
    modelo.set_tipo_de_carga(0, "comercial")
    red_id = network_service.guardar("Con tipos")

    network_service.cargar_ejemplo()
    network_service.cargar_guardada(red_id)

    assert network_service.get_network().tipo_de_carga(0) == "comercial"


def test_el_panel_de_detalle_muestra_el_tipo(network_service):
    modelo = network_service.get_network()
    modelo.set_tipo_de_carga(0, "industrial")

    detalle = network_service.detalle_bus(1)

    assert detalle["load"][0]["perfil_tipo"] == "industrial"


def test_el_panel_de_detalle_edita_el_tipo(network_service):
    network_service.editar_campo("load", 0, "perfil_tipo", "comercial")

    assert network_service.get_network().tipo_de_carga(0) == "comercial"


@pytest.mark.parametrize("tipo", TIPOS_CARGA)
def test_cada_tipo_tiene_una_curva_propia(tipo):
    perfil = ProfileBuilder().build_load_profile(tipo, 24)

    assert len(perfil) == 24
    assert max(perfil) == pytest.approx(1.0)


def test_las_curvas_de_los_tres_tipos_son_distintas():
    builder = ProfileBuilder()

    curvas = {t: tuple(builder.build_load_profile(t, 24)) for t in TIPOS_CARGA}

    assert len(set(curvas.values())) == len(TIPOS_CARGA)
