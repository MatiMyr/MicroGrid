from __future__ import annotations

import math
from typing import Optional

import pandapower as pp
import pandas.api.types as ptypes

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
    # Columnas eléctricamente relevantes que las entidades del dominio no
    # reciben por constructor. Se emiten aparte con ``model.set_field`` para que
    # el round-trip no pierda límites de OPF ni parámetros avanzados.
    EXTRAS = {
        "bus": ["min_vm_pu", "max_vm_pu"],
        "line": ["std_type", "max_loading_percent"],
        "trafo": ["std_type", "max_loading_percent"],
        "load": ["sn_mva", "const_z_p_percent", "const_i_p_percent",
                 "const_z_q_percent", "const_i_q_percent", "type", "controllable",
                 "max_p_mw", "min_p_mw", "max_q_mvar", "min_q_mvar"],
        "sgen": ["sn_mva", "type", "current_source", "controllable",
                 "max_p_mw", "min_p_mw", "max_q_mvar", "min_q_mvar"],
        "storage": ["sn_mva", "type", "min_e_mwh", "controllable", "max_p_mw", "min_p_mw"],
        "ext_grid": ["slack_weight", "controllable",
                     "max_p_mw", "min_p_mw", "max_q_mvar", "min_q_mvar"],
    }

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
        self.model.ensure_positions()
        net = self.model.net
        L: list[str] = [
            "# Este código reconstruye la red. Es la fuente de verdad:",
            "# editá valores/nombres, borrá una línea para quitar un elemento,",
            "# o agregá elementos nuevos. «Ejecutar código» aplica todo.",
            "model = NetworkModel()",
            "net = model.net",
            "",
        ]

        def es_nulo(valor) -> bool:
            """``True`` para ``None`` y para ``NaN`` (numpy.float64 hereda de float)."""
            return valor is None or (isinstance(valor, float) and math.isnan(valor))

        def txt(df, idx, col) -> str:
            """Repr de una columna de texto: ``'hv'`` o ``None``."""
            if col not in df.columns:
                return "None"
            valor = df.at[idx, col]
            if valor is None or es_nulo(valor) or str(valor) == "nan":
                return "None"
            return repr(str(valor))

        def fmt(valor: float) -> float:
            """Recorta a 12 cifras **significativas**, no a 12 decimales.

            Redondear a una cantidad fija de decimales degrada los valores
            chicos: un ``length_km`` de 0.0123456789 perdía 4 órdenes de
            precisión relativa, y esa diferencia se propaga a las pérdidas de la
            simulación. Con cifras significativas el error relativo es el mismo
            para cualquier magnitud, y el número sigue siendo legible.
            """
            return float("%.12g" % float(valor))

        def num(df, idx, col, default=0.0):
            if col in df.columns:
                try:
                    valor = float(df.at[idx, col])
                except (TypeError, ValueError):
                    return default
                return default if valor != valor else fmt(valor)  # NaN -> default
            return default

        def opt_num(df, idx, col) -> str:
            """Repr de una columna numérica opcional: ``2.5`` o ``None``."""
            if col not in df.columns:
                return "None"
            try:
                valor = float(df.at[idx, col])
            except (TypeError, ValueError):
                return "None"
            return "None" if valor != valor else repr(fmt(valor))

        def flag(df, idx, col, default=True) -> str:
            if col not in df.columns:
                return repr(default)
            valor = df.at[idx, col]
            if es_nulo(valor):
                return repr(default)
            return repr(bool(valor))

        def repr_nom(df, idx) -> str:
            return txt(df, idx, "name")

        # --- Buses ---
        L.append("# --- Buses ---")
        for i in net.bus.index:
            L.append(f"model.add_bus(Bus(index={int(i)}, vn_kv={num(net.bus, i, 'vn_kv', 0.4)}, "
                     f"name={repr_nom(net.bus, i)}, type={txt(net.bus, i, 'type')}, "
                     f"in_service={flag(net.bus, i, 'in_service')}))")
        L.append("")

        # --- Posiciones (x, y) ---
        L.append("# --- Posiciones (x, y): editables y arrastrables en el grafo ---")
        for i, (x, y) in self.model.bus_positions().items():
            L.append(f"model.set_bus_position({int(i)}, {x}, {y})")
        L.append("")

        # --- Red externa ---
        if len(net.ext_grid):
            L.append("# --- Red externa ---")
            for i in net.ext_grid.index:
                L.append(f"model.add_ext_grid(ExternalGrid(index={int(i)}, "
                         f"bus={int(net.ext_grid.at[i, 'bus'])}, "
                         f"vm_pu={num(net.ext_grid, i, 'vm_pu', 1.0)}, "
                         f"va_degree={num(net.ext_grid, i, 'va_degree')}, "
                         f"name={repr_nom(net.ext_grid, i)}, "
                         f"in_service={flag(net.ext_grid, i, 'in_service')}))")
            L.append("")

        # --- Líneas ---
        if len(net.line):
            L.append("# --- Líneas ---")
            for i in net.line.index:
                L.append(
                    f"pp.create_line_from_parameters(net, index={int(i)}, "
                    f"from_bus={int(net.line.at[i, 'from_bus'])}, to_bus={int(net.line.at[i, 'to_bus'])}, "
                    f"length_km={num(net.line, i, 'length_km', 0.1)}, "
                    f"r_ohm_per_km={num(net.line, i, 'r_ohm_per_km')}, x_ohm_per_km={num(net.line, i, 'x_ohm_per_km')}, "
                    f"c_nf_per_km={num(net.line, i, 'c_nf_per_km')}, g_us_per_km={num(net.line, i, 'g_us_per_km')}, "
                    f"max_i_ka={num(net.line, i, 'max_i_ka', 1.0)}, "
                    f"parallel={int(num(net.line, i, 'parallel', 1))}, df={num(net.line, i, 'df', 1.0)}, "
                    f"type={txt(net.line, i, 'type')}, in_service={flag(net.line, i, 'in_service')}, "
                    f"name={repr_nom(net.line, i)})")
            L.append("")

        # --- Transformadores ---
        if len(net.trafo):
            L.append("# --- Transformadores (incluye la regulación del tap) ---")
            for i in net.trafo.index:
                L.append(
                    f"pp.create_transformer_from_parameters(net, index={int(i)}, "
                    f"hv_bus={int(net.trafo.at[i, 'hv_bus'])}, lv_bus={int(net.trafo.at[i, 'lv_bus'])}, "
                    f"sn_mva={num(net.trafo, i, 'sn_mva', 0.4)}, vn_hv_kv={num(net.trafo, i, 'vn_hv_kv', 20.0)}, "
                    f"vn_lv_kv={num(net.trafo, i, 'vn_lv_kv', 0.4)}, vkr_percent={num(net.trafo, i, 'vkr_percent', 1.0)}, "
                    f"vk_percent={num(net.trafo, i, 'vk_percent', 4.0)}, pfe_kw={num(net.trafo, i, 'pfe_kw')}, "
                    f"i0_percent={num(net.trafo, i, 'i0_percent')}, shift_degree={num(net.trafo, i, 'shift_degree')}, "
                    f"tap_side={txt(net.trafo, i, 'tap_side')}, tap_neutral={opt_num(net.trafo, i, 'tap_neutral')}, "
                    f"tap_min={opt_num(net.trafo, i, 'tap_min')}, tap_max={opt_num(net.trafo, i, 'tap_max')}, "
                    f"tap_step_percent={opt_num(net.trafo, i, 'tap_step_percent')}, "
                    f"tap_step_degree={opt_num(net.trafo, i, 'tap_step_degree')}, "
                    f"tap_pos={opt_num(net.trafo, i, 'tap_pos')}, "
                    f"tap_changer_type={txt(net.trafo, i, 'tap_changer_type')}, "
                    f"vector_group={txt(net.trafo, i, 'vector_group')}, "
                    f"parallel={int(num(net.trafo, i, 'parallel', 1))}, df={num(net.trafo, i, 'df', 1.0)}, "
                    f"in_service={flag(net.trafo, i, 'in_service')}, name={repr_nom(net.trafo, i)})")
            L.append("")

        # --- Cargas ---
        if len(net.load):
            L.append("# --- Cargas (perfil_tipo elige la curva horaria de cada una) ---")
            for i in net.load.index:
                L.append(f"model.add_load(Load(index={int(i)}, bus={int(net.load.at[i, 'bus'])}, "
                         f"p_mw={num(net.load, i, 'p_mw')}, q_mvar={num(net.load, i, 'q_mvar')}, "
                         f"scaling={num(net.load, i, 'scaling', 1.0)}, "
                         f"perfil_tipo={self.model.tipo_de_carga(i)!r}, "
                         f"in_service={flag(net.load, i, 'in_service')}, name={repr_nom(net.load, i)}))")
            L.append("")

        # --- Solar ---
        if len(net.sgen):
            L.append("# --- Solar ---")
            for i in net.sgen.index:
                L.append(f"model.add_solar_panel(SolarPanel(index={int(i)}, bus={int(net.sgen.at[i, 'bus'])}, "
                         f"p_mw={num(net.sgen, i, 'p_mw')}, q_mvar={num(net.sgen, i, 'q_mvar')}, "
                         f"scaling={num(net.sgen, i, 'scaling', 1.0)}, "
                         f"in_service={flag(net.sgen, i, 'in_service')}, name={repr_nom(net.sgen, i)}))")
            L.append("")

        # --- Baterías ---
        if len(net.storage):
            L.append("# --- Baterías (p_mw > 0 = carga, p_mw < 0 = descarga) ---")
            for i in net.storage.index:
                L.append(f"model.add_battery(Battery(index={int(i)}, bus={int(net.storage.at[i, 'bus'])}, "
                         f"p_mw={num(net.storage, i, 'p_mw')}, max_e_mwh={num(net.storage, i, 'max_e_mwh', 0.05)}, "
                         f"q_mvar={num(net.storage, i, 'q_mvar')}, soc_percent={num(net.storage, i, 'soc_percent', 50.0)}, "
                         f"scaling={num(net.storage, i, 'scaling', 1.0)}, "
                         f"in_service={flag(net.storage, i, 'in_service')}, name={repr_nom(net.storage, i)}))")
            L.append("")

        # --- Interruptores ---
        if len(net.switch):
            L.append("# --- Interruptores ---")
            for i in net.switch.index:
                L.append(f"pp.create_switch(net, index={int(i)}, bus={int(net.switch.at[i, 'bus'])}, "
                         f"element={int(net.switch.at[i, 'element'])}, et={txt(net.switch, i, 'et')}, "
                         f"closed={flag(net.switch, i, 'closed')}, type={txt(net.switch, i, 'type')}, "
                         f"z_ohm={num(net.switch, i, 'z_ohm')}, name={repr_nom(net.switch, i)})")
            L.append("")

        # --- Ajustes finos ---
        finos: list[str] = []
        for tabla, columnas in self.EXTRAS.items():
            df = getattr(net, tabla, None)
            if df is None or not len(df):
                continue
            for i in df.index:
                for col in columnas:
                    if col not in df.columns:
                        continue
                    valor = df.at[i, col]
                    if es_nulo(valor) or valor is None or str(valor) == "nan":
                        continue
                    # El tipo lo decide el dtype de la columna: numpy.bool_ no es
                    # bool de Python, y escribir 1.0 en una columna booleana la
                    # corrompe.
                    if ptypes.is_bool_dtype(df[col]):
                        literal = repr(bool(valor))
                    elif isinstance(valor, str):
                        literal = repr(valor)
                    else:
                        try:
                            literal = repr(fmt(valor))
                        except (TypeError, ValueError):
                            literal = repr(str(valor))
                    finos.append(f"model.set_field({tabla!r}, {int(i)}, {col!r}, {literal})")
        if finos:
            L.append("# --- Ajustes finos: límites de OPF y parámetros avanzados ---")
            L.extend(finos)
            L.append("")

        return "\n".join(L).rstrip() + "\n"

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
