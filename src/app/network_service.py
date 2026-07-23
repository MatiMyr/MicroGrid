from __future__ import annotations

from typing import Optional

import pandapower as pp

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

    # ---- acceso ----------------------------------------------------------
    def get_network(self) -> NetworkModel:
        return self.model

    def set_network(self, model: NetworkModel, red_id: Optional[str] = None) -> None:
        self.model = model
        self.red_id = red_id

    # ---- fuentes de carga ------------------------------------------------
    def cargar_desde_simbench(self, codigo: str = "1-LV-rural1--0-no_sw") -> NetworkModel:
        """Carga una red base de SimBench, usando el caché local si está disponible."""
        if self.simbench_repo.existe(codigo):
            net = self.simbench_repo.cargar(codigo)
        else:
            import simbench as sb

            net = sb.get_simbench_net(codigo)
            self.simbench_repo.guardar(codigo, net)
        self.set_network(NetworkModel(net))
        return self.model

    def cargar_guardada(self, red_id: str) -> NetworkModel:
        """Carga una red guardada por su id estable."""
        net = self.net_repo.cargar(red_id)
        self.set_network(NetworkModel(net), red_id=red_id)
        return self.model

    def aplicar_codigo(self, codigo_py: str) -> NetworkModel:
        """Ejecuta código Python del usuario que construye/edita la red.

        El código corre en el proceso local (requisito de seguridad del
        proyecto: el editor de código ejecuta solo en proceso local). Expone
        ``model`` (el ``NetworkModel`` actual), las entidades del dominio y
        ``pp`` (pandapower) para máxima flexibilidad.
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

    # ---- generación de código editable -----------------------------------
    def generar_codigo(self) -> str:
        """Genera un script Python que **reconstruye** la red actual desde cero.

        El script es la fuente de verdad de la red: al ejecutarlo se arma un
        ``NetworkModel`` nuevo con exactamente los elementos que figuran. Así el
        usuario puede editar parámetros y nombres, **borrar** un elemento
        (eliminando su línea) o agregar uno nuevo, y "Ejecutar código" lo aplica.
        Las posiciones ``set_bus_position`` se reflejan en el grafo y se
        actualizan al arrastrar los nodos en el Editor.

        Líneas y transformadores se emiten con ``create_*_from_parameters`` (con
        sus valores eléctricos reales) para que cualquier red se reconstruya sin
        depender de que su ``std_type`` esté en la librería de tipos.
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

        def repr_nom(df, idx) -> str:
            if "name" in df.columns:
                nom = df.at[idx, "name"]
                if nom is not None and str(nom) != "nan":
                    return repr(str(nom))
            return "None"

        def num(df, idx, col, default=0.0):
            if col in df.columns:
                try:
                    return round(float(df.at[idx, col]), 6)
                except (TypeError, ValueError):
                    return default
            return default

        # --- Buses ---
        L.append("# --- Buses ---")
        for i in net.bus.index:
            L.append(f"model.add_bus(Bus(index={int(i)}, vn_kv={num(net.bus, i, 'vn_kv', 0.4)}, "
                     f"name={repr_nom(net.bus, i)}, type={repr(str(net.bus.at[i, 'type']))}))")
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
                L.append(f"model.add_ext_grid(ExternalGrid(bus={int(net.ext_grid.at[i, 'bus'])}, "
                         f"vm_pu={num(net.ext_grid, i, 'vm_pu', 1.0)}, "
                         f"va_degree={num(net.ext_grid, i, 'va_degree')}, name={repr_nom(net.ext_grid, i)}))")
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
                    f"c_nf_per_km={num(net.line, i, 'c_nf_per_km')}, max_i_ka={num(net.line, i, 'max_i_ka', 1.0)}, "
                    f"parallel={int(num(net.line, i, 'parallel', 1))}, df={num(net.line, i, 'df', 1.0)}, "
                    f"name={repr_nom(net.line, i)})")
            L.append("")

        # --- Transformadores ---
        if len(net.trafo):
            L.append("# --- Transformadores ---")
            for i in net.trafo.index:
                L.append(
                    f"pp.create_transformer_from_parameters(net, index={int(i)}, "
                    f"hv_bus={int(net.trafo.at[i, 'hv_bus'])}, lv_bus={int(net.trafo.at[i, 'lv_bus'])}, "
                    f"sn_mva={num(net.trafo, i, 'sn_mva', 0.4)}, vn_hv_kv={num(net.trafo, i, 'vn_hv_kv', 20.0)}, "
                    f"vn_lv_kv={num(net.trafo, i, 'vn_lv_kv', 0.4)}, vkr_percent={num(net.trafo, i, 'vkr_percent', 1.0)}, "
                    f"vk_percent={num(net.trafo, i, 'vk_percent', 4.0)}, pfe_kw={num(net.trafo, i, 'pfe_kw')}, "
                    f"i0_percent={num(net.trafo, i, 'i0_percent')}, tap_pos={num(net.trafo, i, 'tap_pos')}, "
                    f"name={repr_nom(net.trafo, i)})")
            L.append("")

        # --- Cargas ---
        if len(net.load):
            L.append("# --- Cargas ---")
            for i in net.load.index:
                L.append(f"model.add_load(Load(bus={int(net.load.at[i, 'bus'])}, "
                         f"p_mw={num(net.load, i, 'p_mw')}, q_mvar={num(net.load, i, 'q_mvar')}, "
                         f"scaling={num(net.load, i, 'scaling', 1.0)}, name={repr_nom(net.load, i)}))")
            L.append("")

        # --- Solar ---
        if len(net.sgen):
            L.append("# --- Solar ---")
            for i in net.sgen.index:
                L.append(f"model.add_solar_panel(SolarPanel(bus={int(net.sgen.at[i, 'bus'])}, "
                         f"p_mw={num(net.sgen, i, 'p_mw')}, q_mvar={num(net.sgen, i, 'q_mvar')}, "
                         f"scaling={num(net.sgen, i, 'scaling', 1.0)}, name={repr_nom(net.sgen, i)}))")
            L.append("")

        # --- Baterías ---
        if len(net.storage):
            L.append("# --- Baterías ---")
            for i in net.storage.index:
                L.append(f"model.add_battery(Battery(bus={int(net.storage.at[i, 'bus'])}, "
                         f"p_mw={num(net.storage, i, 'p_mw')}, max_e_mwh={num(net.storage, i, 'max_e_mwh', 0.05)}, "
                         f"q_mvar={num(net.storage, i, 'q_mvar')}, soc_percent={num(net.storage, i, 'soc_percent', 50.0)}, "
                         f"scaling={num(net.storage, i, 'scaling', 1.0)}, name={repr_nom(net.storage, i)}))")
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
