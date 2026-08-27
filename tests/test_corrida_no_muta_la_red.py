"""Una corrida no puede tocar la red que el usuario está editando.

``run_corrida`` escribe ``scaling`` y ``soc_percent`` hora tras hora y ``runpp``
agrega las tablas ``res_*``. Antes eso caía sobre la red viva: al terminar, el
Editor mostraba (y guardaba) la red con el factor de la última hora simulada.
"""
from __future__ import annotations


def _estado(net) -> dict:
    return {
        "load_scaling": list(net.load.scaling),
        "sgen_scaling": list(net.sgen.scaling),
        "soc": list(net.storage.soc_percent),
    }


def test_la_red_del_editor_queda_intacta(network_service, simulation_service):
    net = network_service.get_network().net
    antes = _estado(net)

    simulation_service.run_corrida(horas=6)

    assert _estado(net) == antes
    assert antes["load_scaling"] == [1.0, 1.0]
    assert antes["soc"] == [50.0]


def test_la_corrida_no_deja_tablas_de_resultado_en_la_red_viva(network_service, simulation_service):
    """Sin esto, ``pp.to_json`` guardaba la red con los ``res_*`` de la última corrida."""
    net = network_service.get_network().net

    simulation_service.run_corrida(horas=3)

    assert len(net.res_bus) == 0
    assert len(net.res_line) == 0


def test_un_instante_suelto_tampoco_muta_la_red(network_service, simulation_service):
    net = network_service.get_network().net
    antes = _estado(net)

    simulation_service.run_pp()

    assert _estado(net) == antes
    assert len(net.res_bus) == 0


def test_la_firma_de_referencia_es_la_de_la_red_original(network_service, simulation_service):
    """Tras correr, el Dashboard no debe marcar la red como desincronizada."""
    simulation_service.run_corrida(horas=4)

    assert simulation_service.network_signature() == simulation_service.last_run_signature


def test_el_soc_se_encadena_entre_horas(network_service, simulation_service):
    """El SoC resultante de una hora es el inicial de la siguiente."""
    net = network_service.get_network().net
    net.storage.loc[0, "p_mw"] = 0.005
    net.storage.loc[0, "max_e_mwh"] = 0.1
    net.storage.loc[0, "soc_percent"] = 20.0

    corrida = simulation_service.run_corrida(horas=4)
    socs = [r.battery_soc_result[0] for r in corrida["resultados"]]

    # Carga constante: el SoC crece monótonamente hora a hora.
    assert socs == sorted(socs)
    assert socs[0] > 20.0


def test_el_soc_inicial_es_el_que_define_el_editor(network_service, simulation_service):
    """El SoC de arranque sale de cada batería, no de un valor global de la corrida.

    Antes el Dashboard lo pisaba con un único campo, así que el SoC por batería
    que el Editor deja editar no tenía ningún efecto.
    """
    net = network_service.get_network().net
    net.storage.loc[0, "p_mw"] = 0.0            # sin carga ni descarga
    net.storage.loc[0, "max_e_mwh"] = 0.1
    net.storage.loc[0, "soc_percent"] = 17.5

    corrida = simulation_service.run_corrida(horas=2)

    assert corrida["resultados"][0].battery_soc_result[0] == 17.5


def test_las_horas_se_recortan_al_rango_permitido(simulation_service):
    """El máximo del formulario es del navegador; el servidor tiene que validarlo igual."""
    corrida = simulation_service.run_corrida(horas=10_000)

    assert len(corrida["resultados"]) == simulation_service.MAX_HORAS
    assert simulation_service._validar_horas(0) == simulation_service.MIN_HORAS
    assert simulation_service._validar_horas("no es un número") == 24
