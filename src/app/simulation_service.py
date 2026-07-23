from __future__ import annotations

import hashlib
import json
import uuid
from typing import Optional

from app.network_service import NetworkService
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
    """

    _TABLAS_INPUT = ["bus", "line", "trafo", "load", "sgen", "storage", "ext_grid"]
    # Columnas que no son parte de la identidad eléctrica de la red: la posición
    # gráfica y el estado por hora (escala/SoC que fija la simulación).
    _SIG_EXCLUDE = {"geo", "scaling", "soc_percent"}

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

    def network_signature(self, net=None) -> str:
        """Hash de la identidad eléctrica de la red (topología + parámetros).

        Excluye la posición gráfica y el estado por hora, de modo que mover un
        bus o simular no cambia la firma, pero sí lo hace agregar/quitar/editar
        un elemento eléctrico. Sirve para saber si la red del editor difiere de la
        que refleja el Dashboard.
        """
        net = net if net is not None else self.network_service.get_network().net
        payload: dict = {}
        for tabla in self._TABLAS_INPUT:
            df = getattr(net, tabla, None)
            if df is not None and len(df):
                cols = [c for c in df.columns if c not in self._SIG_EXCLUDE]
                payload[tabla] = json.loads(df[cols].round(6).to_json(orient="index"))
        serial = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serial.encode("utf-8")).hexdigest()

    # ---- corrida de un solo instante (estado actual de la red) -----------
    def run_pp(self, nombre_red: str = "", escenario: str = "") -> SimulationResult:
        return self._run_instante("pp", nombre_red, escenario)

    def run_opp(self, nombre_red: str = "", escenario: str = "") -> SimulationResult:
        return self._run_instante("opp", nombre_red, escenario)

    def _run_instante(self, mode: str, nombre_red: str, escenario: str) -> SimulationResult:
        network = self.network_service.get_network()
        h = self._hash_instante(network, mode)
        if self.sim_repo.existe(h):
            return self.sim_repo.cargar_por_hash(h)
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
        tipo_carga: str = "residencial",
        region: str = "LITORAL",
        lat: float = -31.4,
        lon: float = -60.5,
        soc_inicial: float = 50.0,
    ) -> dict:
        """Corre ``horas`` instantes encadenando el SoC y devuelve la corrida.

        Para cada hora aplica el factor de carga y solar del perfil, fija el SoC
        inicial (definido por el usuario en la primera hora, y por el resultado
        de la hora anterior en las siguientes), simula y cachea por hash. Devuelve
        ``{"run_id": ..., "resultados": [SimulationResult, ...]}``.
        """
        network = self.network_service.get_network()
        run_id = uuid.uuid4().hex

        perfil_carga = self.profile_builder.build_load_profile(tipo_carga, horas, region)
        perfil_solar = self.profile_builder.build_solar_profile(lat, lon, horas)

        # SoC inicial por batería para la primera hora.
        soc_actual: dict[int, float] = {}
        if len(network.net.storage):
            soc_actual = {int(i): float(soc_inicial) for i in network.net.storage.index}

        resultados: list[SimulationResult] = []
        hashes: list[str] = []
        for h in range(horas):
            network.apply_load_scaling(perfil_carga[h])
            network.apply_sgen_scaling(perfil_solar[h])
            if soc_actual:
                network.set_storage_soc(soc_actual)

            input_hash = self._hash_instante(network, mode)
            if self.sim_repo.existe(input_hash):
                resultado = self.sim_repo.cargar_por_hash(input_hash)
            else:
                runner = SimEngine.runpp if mode == "pp" else SimEngine.runopp
                resultado = runner(network, nombre_red=nombre_red, escenario=escenario)
                resultado.input_hash = input_hash

            resultado.run_id = run_id
            resultado.hour_index = h
            self.sim_repo.guardar_por_hash(resultado)
            resultados.append(resultado)
            hashes.append(input_hash)

            # El SoC resultante de esta hora es el inicial de la siguiente.
            if resultado.battery_soc_result:
                soc_actual = {int(k): float(v) for k, v in resultado.battery_soc_result.items()}

        self.sim_repo.guardar_indice_corrida(run_id, hashes)
        # La red simulada pasa a ser la referencia del Dashboard.
        self.last_run_signature = self.network_signature(network.net)
        return {"run_id": run_id, "resultados": resultados}

    def cargar_corrida(self, run_id: str) -> list[SimulationResult]:
        """Reconstruye una corrida juntando sus instantes cacheados."""
        return self.sim_repo.listar_corrida(run_id)

    # ---- hash canónico de las entradas de un instante --------------------
    def _hash_instante(self, network, mode: str) -> str:
        """Hash de ``(red sin res_*, carga[H], solar[H], modo, SoC inicial[H])``.

        La serialización es canónica (claves ordenadas, floats redondeados) para
        que la misma entrada siempre produzca el mismo hash. Las tablas ``res_*``
        se excluyen porque no son parte del input.
        """
        net = network.net
        payload: dict = {"mode": mode, "tablas": {}}
        for tabla in self._TABLAS_INPUT:
            df = getattr(net, tabla, None)
            if df is not None and len(df):
                # round() sólo afecta columnas numéricas; el resto queda igual.
                payload["tablas"][tabla] = json.loads(df.round(6).to_json(orient="index"))
        serial = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serial.encode("utf-8")).hexdigest()
