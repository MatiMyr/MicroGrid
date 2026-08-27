from __future__ import annotations

from typing import Optional

import pandapower as pp

from app import code_gen
from domain.network_model import (
    Battery,
    Bus,
    ExternalGrid,
    Line,
    Load,
    NetworkModel,
    SolarPanel,
    Transformer,
)
from repositories.json_net_repository import JsonRedRepository
from repositories.json_simbench_repository import JsonSimbenchRepository


class NetworkService:
    """Servicio Red: mantiene siempre una red lista para simular.

    Sabe cargar una red desde tres fuentes (SimBench, una red guardada por el
    usuario o código Python), aplicar cambios del Editor sobre la red cargada, y
    guardar/recuperar configuraciones a través del repositorio. Delega la
    construcción real en ``NetworkModel``: decide qué construir, pero no toca
    pandapower directamente.
    """

    def __init__(
        self,
        model: Optional[NetworkModel] = None,
        net_repo: Optional[JsonRedRepository] = None,
        simbench_repo: Optional[JsonSimbenchRepository] = None,
    ):
        self.net_repo = net_repo or JsonRedRepository()
        self.simbench_repo = simbench_repo or JsonSimbenchRepository()
        self.model = model or self._build_sample_network()
        # Id estable de la red actual si proviene del repositorio (None si es nueva).
        self.red_id: Optional[str] = None
        # Bus seleccionado en el panel de detalle (None si no hay ninguno).
        self.selected_bus: Optional[int] = None

    # ---- acceso ----------------------------------------------------------
    def get_network(self) -> NetworkModel:
        return self.model

    def set_network(self, model: NetworkModel, red_id: Optional[str] = None) -> None:
        self.model = model
        self.red_id = red_id

    # ---- fuentes de carga ------------------------------------------------
    def cargar_ejemplo(self) -> NetworkModel:
        """Carga la red de ejemplo, descartando la red actual."""
        self.set_network(self._build_sample_network())
        self.selected_bus = None
        return self.model

    def cargar_desde_simbench(self, codigo: str = "1-LV-rural1--0-no_sw") -> NetworkModel:
        """Carga una red base de SimBench, usando el caché local si está disponible."""
        if self.simbench_repo.existe(codigo):
            net = self.simbench_repo.cargar(codigo)
        else:
            import simbench as sb

            net = sb.get_simbench_net(codigo)
            self.simbench_repo.guardar(codigo, net)
        self.set_network(NetworkModel(net))
        # SimBench trae lat/lon reales de rango minúsculo: normalizar para el grafo.
        self.model.ensure_positions()
        self.model.normalize_positions()
        return self.model

    def cargar_guardada(self, red_id: str) -> NetworkModel:
        """Carga una red guardada por su id estable."""
        net = self.net_repo.cargar(red_id)
        self.set_network(NetworkModel(net), red_id=red_id)
        self.model.ensure_positions()
        self.model.normalize_positions()
        return self.model

    def aplicar_codigo(self, codigo_py: str) -> NetworkModel:
        """Ejecuta código Python del usuario que construye/edita la red.

        Expone ``model`` (el ``NetworkModel`` actual), las entidades del dominio
        y ``pp`` (pandapower) para máxima flexibilidad.

        .. warning::
           ``exec`` sin sandbox: el código recibido puede hacer cualquier cosa
           que pueda hacer el proceso (leer y borrar archivos, abrir la red,
           etc.). Es aceptable **solo** porque la app es una herramienta local
           monousuario que escucha en ``127.0.0.1`` — quien escribe el código es
           quien ya tiene la sesión de la máquina. Exponer la app en red
           convierte esto en ejecución remota de código sin autenticación; ver
           la nota de ``src/main.py``.
        """
        contexto = {
            "model": self.model,
            "pp": pp,
            "NetworkModel": NetworkModel,
            "Bus": Bus,
            "Line": Line,
            "Transformer": Transformer,
            "Load": Load,
            "SolarPanel": SolarPanel,
            "Battery": Battery,
            "ExternalGrid": ExternalGrid,
        }
        exec(codigo_py, contexto)  # noqa: S102 - ejecución local intencional
        # El usuario puede reasignar ``model`` a un NetworkModel nuevo.
        nuevo = contexto.get("model")
        if isinstance(nuevo, NetworkModel):
            self.model = nuevo
        return self.model

    # ---- edición gráfica -------------------------------------------------
    def agregar(self, entidad) -> int:
        """Agrega un elemento del dominio a la red y devuelve su índice."""
        despacho = {
            Bus: self.model.add_bus,
            Line: self.model.add_line,
            Transformer: self.model.add_transformer,
            Load: self.model.add_load,
            SolarPanel: self.model.add_solar_panel,
            Battery: self.model.add_battery,
            ExternalGrid: self.model.add_ext_grid,
        }
        for tipo, metodo in despacho.items():
            if isinstance(entidad, tipo):
                return metodo(entidad)
        raise TypeError(f"Entidad no soportada: {type(entidad).__name__}")

    def eliminar(self, element_type: str, index: int) -> None:
        """Quita un elemento de la red. ``bus`` usa el borrado en cascada."""
        if element_type == "bus":
            self.model.remove_bus(index)
        else:
            self.model.remove_element(element_type, index)

    # ---- persistencia ----------------------------------------------------
    def guardar(self, nombre: str) -> str:
        """Guarda la red actual con un nombre nuevo. Devuelve su id estable."""
        red_id = self.net_repo.guardar(nombre, self.model.net)
        self.red_id = red_id
        return red_id

    def guardar_cambios(self) -> None:
        """Sobrescribe la red guardada actual (requiere haberla cargado del repo)."""
        if self.red_id is None:
            raise ValueError("La red actual no proviene del repositorio; usá guardar(nombre).")
        self.net_repo.actualizar(self.red_id, self.model.net)

    def listar_guardadas(self) -> list[dict]:
        return self.net_repo.listar()

    def nombre_guardada(self, red_id: str) -> Optional[str]:
        """Nombre visible de una red guardada, o ``None`` si no existe."""
        return self.net_repo.nombre_de(red_id)

    def eliminar_guardada(self, red_id: str) -> None:
        """Borra una red guardada del repositorio.

        Si es la que está abierta, se conserva en memoria pero se corta el
        vínculo con el repositorio: «Sobrescribir» dejaría de tener a qué
        apuntar, así que pasa a comportarse como una red nueva sin guardar.
        """
        self.net_repo.eliminar(red_id)
        if self.red_id == red_id:
            self.red_id = None

    # ---- detalle y edición por bus (panel estilo mapa) -------------------
    # Campos editables por tipo de elemento.
    CAMPOS = {
        "bus": ["name", "vn_kv"],
        "load": ["name", "p_mw", "q_mvar", "scaling", "perfil_tipo"],
        "sgen": ["name", "p_mw", "q_mvar", "scaling"],
        "storage": ["name", "p_mw", "q_mvar", "max_e_mwh", "soc_percent", "scaling"],
        "ext_grid": ["name", "vm_pu", "va_degree"],
    }

    def detalle_bus(self, bus_idx: int) -> Optional[dict]:
        """Devuelve los datos del bus y de todos los elementos conectados a él."""
        net = self.model.net
        if bus_idx not in net.bus.index:
            return None

        def _nombre(df, i):
            nom = df.at[i, "name"] if "name" in df.columns else None
            return "" if nom is None or str(nom) == "nan" else str(nom)

        def _campos(tabla):
            df = getattr(net, tabla)
            filas = []
            for i in df.index[df["bus"] == bus_idx]:
                fila = {"idx": int(i), "name": _nombre(df, i)}
                for c in self.CAMPOS[tabla]:
                    if c in ("name", "perfil_tipo") or c not in df.columns:
                        continue
                    fila[c] = round(float(df.at[i, c]), 6)
                if tabla == "load":
                    fila["perfil_tipo"] = self.model.tipo_de_carga(i)
                filas.append(fila)
            return filas

        pos = self.model.get_bus_position(bus_idx)
        return {
            "idx": int(bus_idx),
            "name": _nombre(net.bus, bus_idx),
            "vn_kv": round(float(net.bus.at[bus_idx, "vn_kv"]), 6),
            "x": round(pos[0], 4) if pos else 0.0,
            "y": round(pos[1], 4) if pos else 0.0,
            "load": _campos("load"),
            "sgen": _campos("sgen"),
            "storage": _campos("storage"),
            "ext_grid": _campos("ext_grid"),
        }

    def editar_campo(self, kind: str, idx: int, field: str, value) -> None:
        """Edita un parámetro de un bus o de un elemento conectado."""
        if kind == "load" and field == "perfil_tipo":
            # No es un parámetro eléctrico: pasa por el validador de tipos, que
            # descarta valores fuera de ``TIPOS_CARGA``.
            self.model.set_tipo_de_carga(idx, value)
            return
        tabla = "bus" if kind == "bus" else kind
        self.model.set_field(tabla, idx, field, value)

    def mover_bus(self, bus_idx: int, x: float, y: float) -> None:
        self.model.set_bus_position(bus_idx, x, y)

    def agregar_en_bus(self, kind: str, bus_idx: int) -> int:
        """Agrega un elemento nuevo con valores por defecto al bus dado."""
        constructores = {
            "load": lambda: self.agregar(Load(bus=bus_idx, p_mw=0.01, q_mvar=0.0, name="Carga")),
            "sgen": lambda: self.agregar(SolarPanel(bus=bus_idx, p_mw=0.01, q_mvar=0.0, name="Solar")),
            "storage": lambda: self.agregar(
                Battery(bus=bus_idx, p_mw=0.01, max_e_mwh=0.02, soc_percent=50.0, name="Batería")
            ),
            "ext_grid": lambda: self.agregar(ExternalGrid(bus=bus_idx, vm_pu=1.0, name="Red externa")),
        }
        return constructores[kind]()

    def quitar_elemento(self, kind: str, idx: int) -> None:
        self.eliminar(kind, idx)

    # ---- generación de código editable -----------------------------------
    # La emisión vive en ``app.code_gen``: es un tema aparte (una función por
    # tabla de pandapower) y acá sólo se documenta el contrato.
    EXTRAS = code_gen.EXTRAS

    def generar_codigo(self) -> str:
        """Genera un script Python que **reconstruye** la red actual desde cero.

        El script es la fuente de verdad de la red: al ejecutarlo se arma un
        ``NetworkModel`` nuevo con exactamente los elementos que figuran. Así el
        usuario puede editar parámetros y nombres, **borrar** un elemento
        (eliminando su línea) o agregar uno nuevo, y "Ejecutar código" lo aplica.
        Las posiciones ``set_bus_position`` se reflejan en el grafo y se
        actualizan al arrastrar los nodos en el Editor.

        Como el script se regenera después de cada acción del Editor y se aplica
        con un botón, tiene que ser **fiel**: se emiten el índice de cada
        elemento (para que no se renumeren al reconstruir), ``in_service``, los
        parámetros de regulación del transformador, los interruptores y los
        límites de OPF. Antes se perdían en silencio, así que apretar "Ejecutar
        código" reactivaba elementos fuera de servicio y desarmaba el regulador.

        Líneas y transformadores se emiten con ``create_*_from_parameters`` (con
        sus valores eléctricos reales) para que cualquier red se reconstruya sin
        depender de que su ``std_type`` esté en la librería de tipos.

        Limitación conocida: las columnas de metadatos propias de SimBench
        (``subnet``, ``voltLvl``, ``profile``, ``phys_type``, …) no se emiten.
        No son eléctricas y no afectan el resultado de la simulación.
        """
        return code_gen.generar_codigo(self.model)

    # ---- red de ejemplo --------------------------------------------------
    def _build_sample_network(self) -> NetworkModel:
        model = NetworkModel()

        model.add_bus(Bus(index=0, vn_kv=0.4, name="Subestación"))
        model.add_bus(Bus(index=1, vn_kv=0.4, name="Nodo 1"))
        model.add_bus(Bus(index=2, vn_kv=0.4, name="Nodo 2"))

        model.add_ext_grid(ExternalGrid(bus=0, vm_pu=1.0, va_degree=0.0, name="Grid"))
        model.add_line(Line(from_bus=0, to_bus=1, length_km=0.1, name="Línea 0-1"))
        model.add_line(Line(from_bus=1, to_bus=2, length_km=0.15, name="Línea 1-2"))

        model.add_load(Load(bus=1, p_mw=0.05, q_mvar=0.01, name="Carga 1"))
        model.add_load(Load(bus=2, p_mw=0.03, q_mvar=0.008, name="Carga 2"))
        model.add_solar_panel(SolarPanel(bus=2, p_mw=0.04, q_mvar=0.0, name="Panel solar 2"))
        model.add_battery(
            Battery(bus=1, p_mw=0.02, max_e_mwh=0.05, soc_percent=50.0, name="Batería 1")
        )

        return model
