from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.network_service import NetworkService
from domain.entities import TIPO_CARGA_POR_DEFECTO
from domain.epocas import EPOCA_POR_DEFECTO
from domain.profile_builder import ProfileBuilder
from domain.simulation_engine import SimEngine, SimulationResult
from repositories.json_simulation_repository import JsonSimRepository


class SimulationService:
    """Servicio Simulación: coordina una corrida de punta a punta.

    Busca los datos de carga y sol (via ``ProfileBuilder``), arma los perfiles,
    se los da al ``SimEngine`` instante por instante, encadena el SoC de las
    baterías entre horas y persiste cada resultado en el repositorio, indexado
    por el hash de sus entradas para no resimular instantes ya calculados. No
    sabe simular ni leer archivos: sólo coordina.

    Trabaja siempre sobre una **copia** de la red: una corrida pisa ``scaling``
    y ``soc_percent`` hora tras hora, y ``pp.runpp`` agrega las tablas ``res_*``.
    Si eso cayera sobre la red viva, el Editor quedaría mostrando (y guardando)
    la red con el factor de la última hora simulada.
    """

    _TABLAS_INPUT = ["bus", "line", "trafo", "load", "sgen", "storage", "ext_grid", "switch"]

    # Firma del estado del Editor: incluye TODOS los campos de la red (incluida
    # la posición gráfica), porque cualquier cambio —hasta mover un bus— debe
    # marcar el Dashboard como desactualizado.
    _SIG_EXCLUDE: set[str] = set()

    # Clave de caché de un instante: excluye lo que NO cambia el resultado
    # eléctrico. La posición gráfica y los nombres son metadatos de
    # presentación; incluirlos hacía que mover un bus invalidara toda la caché
    # de simulaciones sin que hubiera cambiado nada físico.
    _HASH_EXCLUDE: set[str] = {"geo", "coords", "name"}

    # Tope de horas por corrida (cada hora es un flujo de potencia completo).
    MIN_HORAS, MAX_HORAS = 1, 168

    def __init__(
        self,
        network_service: Optional[NetworkService] = None,
        sim_repo: Optional[JsonSimRepository] = None,
        profile_builder: Optional[ProfileBuilder] = None,
    ):
        self.network_service = network_service or NetworkService()
        self.sim_repo = sim_repo or JsonSimRepository()
        self.profile_builder = profile_builder or ProfileBuilder()
        # Firma de la red de la última corrida (para detectar cambios en el editor).
        self.last_run_signature: Optional[str] = None

    # ---- serialización canónica de la red --------------------------------
    def _serializar(self, net, excluir: set[str]) -> str:
        payload: dict = {}
        for tabla in self._TABLAS_INPUT:
            df = getattr(net, tabla, None)
            if df is not None and len(df):
                cols = [c for c in df.columns if c not in excluir]
                # round() sólo afecta columnas numéricas; el resto queda igual.
                payload[tabla] = json.loads(df[cols].round(6).to_json(orient="index"))
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    def network_signature(self, net=None) -> str:
        """Hash de todo el estado de la red (incluida la posición de los buses).

        Cualquier cambio en el editor —agregar/quitar/editar un elemento o mover
        un bus— altera la firma. Sirve para saber si la red del editor difiere de
        la que refleja el Dashboard.
        """
        net = net if net is not None else self.network_service.get_network().net
        serial = self._serializar(net, self._SIG_EXCLUDE)
        return hashlib.sha256(serial.encode("utf-8")).hexdigest()

    # ---- hash canónico de las entradas de un instante --------------------
    def _hash_instante(self, network, mode: str) -> str:
        """Hash de la red eléctrica más el modo, para un instante.

        Los factores horarios de carga y sol y el SoC inicial no van aparte: ya
        están escritos en las columnas ``scaling`` y ``soc_percent`` de la red al
        momento de hashear. La serialización es canónica (claves ordenadas,
        floats redondeados) para que la misma entrada siempre produzca el mismo
        hash, y deja afuera los campos de presentación (``_HASH_EXCLUDE``) y las
        tablas ``res_*``.
        """
        tablas = json.loads(self._serializar(network.net, self._HASH_EXCLUDE))
        serial = json.dumps({"mode": mode, "tablas": tablas}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serial.encode("utf-8")).hexdigest()

    # ---- corrida de un solo instante (estado actual de la red) -----------
    def run_pp(self, nombre_red: str = "", escenario: str = "") -> SimulationResult:
        return self._run_instante("pp", nombre_red, escenario)

    def run_opp(self, nombre_red: str = "", escenario: str = "") -> SimulationResult:
        return self._run_instante("opp", nombre_red, escenario)

    def _run_instante(self, mode: str, nombre_red: str, escenario: str) -> SimulationResult:
        network = self.network_service.get_network().copy()
        h = self._hash_instante(network, mode)
        cacheado = self.sim_repo.buscar_por_hash(h)
        if cacheado is not None:
            cacheado.nombre_red = nombre_red
            cacheado.escenario = escenario
            return cacheado
        runner = SimEngine.runpp if mode == "pp" else SimEngine.runopp
        resultado = runner(network, nombre_red=nombre_red, escenario=escenario)
        resultado.input_hash = h
        self.sim_repo.guardar_por_hash(resultado)
        return resultado

    # ---- corrida multi-horaria con perfiles y encadenado de SoC ----------
    def run_corrida(
        self,
        horas: int = 24,
        mode: str = "pp",
        nombre_red: str = "",
        escenario: str = "",
        lat: float = -31.4,
        lon: float = -60.5,
        epoca: str = EPOCA_POR_DEFECTO,
        usar_nasa: bool = True,
    ) -> dict:
        """Corre ``horas`` instantes encadenando el SoC y devuelve la corrida.

        Cada hora escala **cada carga según su propio tipo de consumidor** (el
        que tiene asignado en la red) y toda la generación solar según el perfil
        de irradiación **típico de la época del año pedida** (o la campana
        sintética, si ``usar_nasa`` es falso), simula y cachea
        por hash. Devuelve
        ``{"run_id": ..., "resultados": [SimulationResult, ...]}``.

        El SoC inicial de la primera hora es el que cada batería trae en la red
        —se edita en el Editor, batería por batería—; de ahí en más lo encadena
        el resultado de la hora anterior.

        ``horas`` se recorta al rango ``[MIN_HORAS, MAX_HORAS]``: cada hora es un
        flujo de potencia completo, así que un valor arbitrario colgaría el
        servidor. Los límites del formulario son sólo del navegador.
        """
        horas = self._validar_horas(horas)
        if mode not in ("pp", "opp"):
            raise ValueError("Modo de simulación desconocido: %r (esperado 'pp' u 'opp')." % (mode,))

        # Copia defensiva: la corrida escribe scaling/soc_percent y res_* hora a
        # hora; la red del Editor tiene que quedar exactamente como estaba.
        original = self.network_service.get_network()
        network = original.copy()
        run_id = uuid.uuid4().hex
        timestamp = datetime.now(timezone.utc).isoformat()

        # Un perfil por cada tipo de consumidor presente en la red: así una misma
        # red puede mezclar viviendas, comercios e industria con curvas distintas.
        tipos = set(network.tipos_de_carga().values()) or {TIPO_CARGA_POR_DEFECTO}
        perfiles_carga = {t: self.profile_builder.build_load_profile(t, horas) for t in tipos}
        perfil_solar = self.profile_builder.build_solar_profile(
            lat, lon, horas, epoca, usar_nasa)

        # El SoC inicial de la primera hora es el que cada batería trae en la
        # red; sólo a partir de la segunda se escribe el encadenado.
        soc_actual: dict[int, float] = {}

        runner = SimEngine.runpp if mode == "pp" else SimEngine.runopp
        resultados: list[SimulationResult] = []
        hashes: list[str] = []
        for h in range(horas):
            network.apply_load_scaling_por_tipo({t: p[h] for t, p in perfiles_carga.items()})
            network.apply_sgen_scaling(perfil_solar[h])
            if soc_actual:
                network.set_storage_soc(soc_actual)

            input_hash = self._hash_instante(network, mode)
            resultado = self.sim_repo.buscar_por_hash(input_hash)
            if resultado is None:
                resultado = runner(network, nombre_red=nombre_red, escenario=escenario)
                resultado.input_hash = input_hash
                self.sim_repo.guardar_por_hash(resultado)

            # Metadatos de corrida: viven en el objeto y en el índice de la
            # corrida, nunca en el archivo cacheado del instante (que es
            # compartido entre corridas).
            resultado.run_id = run_id
            resultado.hour_index = h
            resultado.nombre_red = nombre_red
            resultado.escenario = escenario
            resultado.timestamp = timestamp
            resultados.append(resultado)
            hashes.append(input_hash)

            # El SoC resultante de esta hora es el inicial de la siguiente.
            if resultado.battery_soc_result:
                soc_actual = {int(k): float(v) for k, v in resultado.battery_soc_result.items()}

        self.sim_repo.guardar_indice_corrida(
            run_id, hashes, nombre_red=nombre_red, escenario=escenario,
            mode=mode, timestamp=timestamp,
        )
        # La red simulada pasa a ser la referencia del Dashboard. Se calcula
        # sobre la red original: la copia trae el scaling de la última hora.
        self.last_run_signature = self.network_signature(original.net)
        return {"run_id": run_id, "resultados": resultados}

    def _validar_horas(self, horas) -> int:
        try:
            horas = int(horas)
        except (TypeError, ValueError):
            horas = 24
        return max(self.MIN_HORAS, min(self.MAX_HORAS, horas))

    def cargar_corrida(self, run_id: str) -> list[SimulationResult]:
        """Reconstruye una corrida juntando sus instantes cacheados."""
        return self.sim_repo.listar_corrida(run_id)

    def listar_corridas(self) -> list[dict]:
        """Metadatos de las corridas guardadas, de la más nueva a la más vieja."""
        return self.sim_repo.listar()
