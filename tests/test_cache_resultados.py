"""La caché de resultados es direccionada por contenido y no mezcla corridas.

Dos problemas que cubre este archivo:

1. La clave de caché incluía la posición gráfica de los buses, así que mover un
   bus invalidaba todos los resultados sin que cambiara nada eléctrico.
2. El archivo del instante guardaba ``run_id``/``hour_index``: una corrida nueva
   que reusaba un instante cacheado le pisaba los metadatos a la corrida vieja.
"""
from __future__ import annotations

import json

from domain.entities import SCHEMA_VERSION_INSTANTE, SimulationResult


# ---- clave de caché --------------------------------------------------------
def test_mover_un_bus_no_invalida_la_cache(network_service, simulation_service):
    modelo = network_service.get_network()
    antes = simulation_service._hash_instante(modelo, "pp")

    modelo.set_bus_position(0, 7.5, 2.5)

    assert simulation_service._hash_instante(modelo, "pp") == antes


def test_renombrar_un_elemento_no_invalida_la_cache(network_service, simulation_service):
    modelo = network_service.get_network()
    antes = simulation_service._hash_instante(modelo, "pp")

    modelo.set_field("load", 0, "name", "Otro nombre")

    assert simulation_service._hash_instante(modelo, "pp") == antes


def test_cambiar_la_potencia_si_invalida_la_cache(network_service, simulation_service):
    modelo = network_service.get_network()
    antes = simulation_service._hash_instante(modelo, "pp")

    modelo.set_field("load", 0, "p_mw", 0.123)

    assert simulation_service._hash_instante(modelo, "pp") != antes


def test_el_modo_forma_parte_de_la_clave(network_service, simulation_service):
    modelo = network_service.get_network()

    assert simulation_service._hash_instante(modelo, "pp") != \
        simulation_service._hash_instante(modelo, "opp")


def test_mover_un_bus_si_marca_el_dashboard_como_desactualizado(network_service, simulation_service):
    """La firma del Editor es otra cosa que la clave de caché: esa sí mira la posición."""
    simulation_service.run_corrida(horas=2)

    network_service.get_network().set_bus_position(0, 1.5, 9.5)

    assert simulation_service.network_signature() != simulation_service.last_run_signature


# ---- separación instante / corrida ----------------------------------------
def test_una_corrida_nueva_no_pisa_los_metadatos_de_la_vieja(simulation_service):
    """Dos corridas idénticas comparten los instantes, pero no la identidad."""
    primera = simulation_service.run_corrida(horas=3, nombre_red="Red A")
    segunda = simulation_service.run_corrida(horas=3, nombre_red="Red B")

    # Comparten los archivos cacheados (misma entrada -> mismo hash)...
    assert [r.input_hash for r in primera["resultados"]] == \
        [r.input_hash for r in segunda["resultados"]]
    assert primera["run_id"] != segunda["run_id"]

    # ...y sin embargo cada corrida se reconstruye con sus propios metadatos.
    recuperada = simulation_service.cargar_corrida(primera["run_id"])
    assert [r.nombre_red for r in recuperada] == ["Red A"] * 3
    assert [r.hour_index for r in recuperada] == [0, 1, 2]
    assert all(r.run_id == primera["run_id"] for r in recuperada)


def test_el_archivo_del_instante_no_guarda_metadatos_de_corrida(simulation_service, sim_repo):
    corrida = simulation_service.run_corrida(horas=2, nombre_red="Red A")
    ruta = sim_repo._path(corrida["resultados"][0].input_hash)

    datos = json.loads(ruta.read_text(encoding="utf-8"))

    assert datos["schema_version"] == SCHEMA_VERSION_INSTANTE
    for campo in ("run_id", "hour_index", "nombre_red", "escenario", "id", "timestamp"):
        assert campo not in datos


def test_horas_repetidas_conservan_su_lugar_en_la_corrida(simulation_service, network_service):
    """Dos horas con la misma entrada comparten archivo; el índice preserva la secuencia."""
    # Sin batería el estado no evoluciona, así que muchas horas dan el mismo hash.
    network_service.get_network().net.storage.drop(
        network_service.get_network().net.storage.index, inplace=True
    )
    corrida = simulation_service.run_corrida(horas=24)

    recuperada = simulation_service.cargar_corrida(corrida["run_id"])

    assert len(recuperada) == 24
    assert [r.hour_index for r in recuperada] == list(range(24))


# ---- versionado del esquema ------------------------------------------------
def test_un_instante_de_esquema_viejo_se_trata_como_cache_miss(sim_repo):
    ruta = sim_repo._path("a" * 8)
    ruta.write_text(json.dumps({"schema_version": SCHEMA_VERSION_INSTANTE - 1, "mode": "pp"}), encoding="utf-8")

    assert sim_repo.buscar_por_hash("a" * 8) is None


def test_un_instante_corrupto_se_trata_como_cache_miss(sim_repo):
    ruta = sim_repo._path("b" * 8)
    ruta.write_text("{ esto no es JSON", encoding="utf-8")

    assert sim_repo.buscar_por_hash("b" * 8) is None


def test_las_claves_vuelven_a_int_al_releer(sim_repo):
    """JSON convierte las claves a texto; el resto del código indexa por número."""
    resultado = SimulationResult(
        mode="pp", total_losses_mw=0.1,
        voltage_profile={0: 1.0, 1: 0.99}, line_loading_pct={0: 12.5},
        autosufficiency_pct=50.0, export_surplus_mw=0.0,
        battery_soc_result={0: 75.0}, input_hash="c" * 8,
    )
    sim_repo.guardar_por_hash(resultado)

    releido = sim_repo.buscar_por_hash("c" * 8)

    assert set(releido.voltage_profile) == {0, 1}
    assert set(releido.line_loading_pct) == {0}
    assert set(releido.battery_soc_result) == {0}


def test_purgar_vacia_la_cache(simulation_service, sim_repo):
    simulation_service.run_corrida(horas=3)
    assert sim_repo.tamanio()["instantes"] > 0

    antes = sim_repo.purgar()

    assert antes["instantes"] > 0
    assert sim_repo.tamanio() == {"instantes": 0, "corridas": 0, "bytes": 0}
