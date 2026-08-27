from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# Versión del esquema de ``SimulationResult`` tal como se persiste en la caché
# de instantes. Se sube cada vez que cambia el significado o el nombre de un
# campo cacheado, para que los archivos viejos se descarten (cache miss) en vez
# de reconstruirse mal o romper la lectura con un ``TypeError``.
#
# Es independiente de ``SCHEMA_VERSION_CORRIDA`` (en el repositorio): el índice
# de corrida tiene su propia forma, y compartir un único número obligaba a
# invalidar los índices por un cambio de física y viceversa.
SCHEMA_VERSION_INSTANTE = 3


@dataclass
class Bus:
    """Nodo eléctrico de la red."""

    index: Optional[int] = None
    vn_kv: float = 0.4
    name: Optional[str] = None
    type: str = "b"
    in_service: bool = True


@dataclass
class Line:
    """Línea entre dos buses."""

    from_bus: int
    to_bus: int
    length_km: float
    std_type: str = "NAYY 4x50 SE"
    name: Optional[str] = None
    index: Optional[int] = None
    df: float = 1.0
    parallel: int = 1
    in_service: bool = True


@dataclass
class Transformer:
    """Transformador de la red."""

    hv_bus: int
    lv_bus: int
    std_type: str = "0.4 MVA 20/0.4 kV"
    name: Optional[str] = None
    index: Optional[int] = None
    tap_pos: float = 0.0
    in_service: bool = True


# Tipos de consumidor con curva horaria característica. Es un atributo **de cada
# carga**, no de la corrida: así una misma red puede mezclar viviendas, comercios
# e industria (p. ej. para mapear un barrio) en vez de compartir una única curva.
TIPOS_CARGA = ("residencial", "comercial", "industrial")
TIPO_CARGA_POR_DEFECTO = "residencial"


@dataclass
class Load:
    """Carga conectada a un bus.

    ``perfil_tipo`` selecciona la curva horaria con la que se escala esta carga
    en una corrida (ver ``TIPOS_CARGA``). Se persiste como una columna propia de
    ``net.load``, así viaja con la red al guardarla y al regenerar el código.
    """

    bus: int
    p_mw: float
    q_mvar: float = 0.0
    name: Optional[str] = None
    index: Optional[int] = None
    scaling: float = 1.0
    perfil_tipo: str = TIPO_CARGA_POR_DEFECTO
    in_service: bool = True


@dataclass
class SolarPanel:
    """Panel solar representado como generación distribuida."""

    bus: int
    p_mw: float
    q_mvar: float = 0.0
    name: Optional[str] = None
    index: Optional[int] = None
    scaling: float = 1.0
    in_service: bool = True


@dataclass
class Battery:
    """Batería de almacenamiento conectada a un bus.

    ``p_mw`` sigue la convención de signo de pandapower para el elemento
    ``storage`` (ver ``pandapower/create/storage_create.py``):

    - ``p_mw > 0`` → la batería **carga** (consume potencia de la red).
    - ``p_mw < 0`` → la batería **descarga** (inyecta potencia a la red).

    Es la convención de carga (igual que ``load``), no la de generación. El
    cálculo de SoC en ``SimEngine._battery_soc_result`` depende de este signo.
    """

    bus: int
    p_mw: float
    max_e_mwh: float
    q_mvar: float = 0.0
    soc_percent: float = 100.0
    name: Optional[str] = None
    index: Optional[int] = None
    scaling: float = 1.0
    in_service: bool = True


@dataclass
class ExternalGrid:
    """Fuente externa de alimentación para la red."""

    bus: int
    vm_pu: float = 1.0
    va_degree: float = 0.0
    name: Optional[str] = None
    index: Optional[int] = None
    in_service: bool = True


@dataclass
class SimulationResult:
    """Resultado de una simulación sobre una red, para un instante.

    Los campos se dividen en dos grupos con ciclos de vida distintos:

    - **De instante** (``_CAMPOS_INSTANTE``): dependen solo de las entradas
      físicas y por lo tanto son los únicos que se guardan en la caché
      direccionada por contenido (``input_hash``). Dos corridas con las mismas
      entradas comparten legítimamente este archivo.
    - **De corrida** (``run_id``, ``hour_index``, ``nombre_red``, ``escenario``,
      ``id``, ``timestamp``): identifican *qué corrida* usó el instante. NO se
      persisten junto al instante — si lo hicieran, una corrida nueva que reusa
      un instante cacheado le pisaría los metadatos a la corrida vieja. Viven en
      el índice de corrida (``data/resultados/_corridas/{run_id}.json``).
    """

    mode: str
    total_losses_mw: float
    voltage_profile: Dict[int, float]
    line_loading_pct: Dict[int, float]
    autosufficiency_pct: float
    # Energía que la microgrid inyecta a la red externa en el instante (MW).
    # Reemplaza al viejo ``curtailment_solar_mw``: bajo ``runpp`` el ``sgen`` es
    # una inyección fija, así que no existe recorte de generación que medir.
    export_surplus_mw: float
    node_results: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    line_results: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    battery_soc_result: Dict[int, float] = field(default_factory=dict)
    # Buses y líneas para los que el flujo no devolvió solución (``NaN``): los
    # que quedan sin camino al nodo slack, por estar aislados o aguas abajo de un
    # elemento fuera de servicio. Se listan aparte en vez de dejar el ``NaN``
    # dentro de los perfiles, donde contaminaba mínimos y máximos y llegaba a
    # romper el Dashboard.
    buses_sin_solucion: List[int] = field(default_factory=list)
    lineas_sin_solucion: List[int] = field(default_factory=list)
    # Clave de caché por instante (hash de los inputs).
    input_hash: str = ""
    # ---- metadatos de corrida (no se cachean con el instante) ----
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    nombre_red: str = ""
    escenario: str = ""
    run_id: str = ""
    hour_index: int = 0

    # Campos que definen el contenido físico del instante.
    _CAMPOS_INSTANTE = (
        "mode",
        "total_losses_mw",
        "voltage_profile",
        "line_loading_pct",
        "autosufficiency_pct",
        "export_surplus_mw",
        "node_results",
        "line_results",
        "battery_soc_result",
        "buses_sin_solucion",
        "lineas_sin_solucion",
        "input_hash",
    )

    # ---- serialización de la caché por instante --------------------------
    def to_cache_dict(self) -> dict:
        """Vuelca solo el contenido físico del instante, con la versión de esquema."""
        datos: dict = {"schema_version": SCHEMA_VERSION_INSTANTE}
        for campo in self._CAMPOS_INSTANTE:
            datos[campo] = getattr(self, campo)
        return datos

    @classmethod
    def from_cache_dict(cls, data: dict) -> Optional["SimulationResult"]:
        """Reconstruye un instante cacheado, o ``None`` si el archivo no sirve.

        Devuelve ``None`` —en vez de lanzar— cuando la versión de esquema no
        coincide o faltan campos, para que el llamador lo trate como un cache
        miss y vuelva a simular. Las claves de los diccionarios indexados por
        bus/línea se re-castean a ``int``: JSON las convierte a ``str`` al
        guardar, y el resto del código indexa por índice numérico.
        """
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION_INSTANTE:
            return None
        try:
            return cls(
                mode=str(data["mode"]),
                total_losses_mw=float(data["total_losses_mw"]),
                voltage_profile=_claves_int(data["voltage_profile"]),
                line_loading_pct=_claves_int(data["line_loading_pct"]),
                autosufficiency_pct=float(data["autosufficiency_pct"]),
                export_surplus_mw=float(data["export_surplus_mw"]),
                node_results=_claves_int(data.get("node_results", {})),
                line_results=_claves_int(data.get("line_results", {})),
                battery_soc_result=_claves_int(data.get("battery_soc_result", {})),
                buses_sin_solucion=[int(i) for i in data.get("buses_sin_solucion", [])],
                lineas_sin_solucion=[int(i) for i in data.get("lineas_sin_solucion", [])],
                input_hash=str(data.get("input_hash", "")),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _claves_int(mapa) -> dict:
    """Normaliza a ``int`` las claves de un mapa indexado por bus/línea."""
    if not isinstance(mapa, dict):
        return {}
    salida = {}
    for clave, valor in mapa.items():
        try:
            salida[int(clave)] = valor
        except (TypeError, ValueError):
            salida[clave] = valor
    return salida
