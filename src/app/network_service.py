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
        """Genera un script Python que refleja la red actual, elemento por elemento.

        El script usa asignaciones directas sobre las tablas de pandapower
        (``net.load.at[i, 'p_mw'] = …``) para que el usuario edite parámetros de
        elementos ya cargados y los aplique con "Ejecutar código". Es robusto
        para cualquier red (incluidas las de SimBench) porque no reconstruye la
        red desde cero. Para agregar elementos nuevos siguen disponibles
        ``model.add_bus(Bus(...))`` y el resto de las entidades del dominio.
        """
        net = self.model.net
        L: list[str] = [
            "# Red actual — editá los valores y tocá «Ejecutar código» para aplicarlos.",
            "# Para agregar elementos: model.add_load(Load(bus=1, p_mw=0.05)), etc.",
            "net = model.net",
            "",
        ]

        def bloque(titulo: str, tabla: str, df, cols: list[str]) -> None:
            if df is None or not len(df):
                return
            L.append(f"# --- {titulo} ({len(df)}) ---")
            presentes = [c for c in cols if c in df.columns]
            for idx in df.index:
                vals = ", ".join(repr(round(float(df.at[idx, c]), 6)) for c in presentes)
                cols_txt = ", ".join(f"'{c}'" for c in presentes)
                comentario = ""
                if "name" in df.columns:
                    nom = df.at[idx, "name"]
                    if nom is not None and str(nom) != "nan":
                        comentario = f"  # {nom}"
                L.append(f"net.{tabla}.loc[{idx}, [{cols_txt}]] = [{vals}]{comentario}")
            L.append("")

        bloque("Buses", "bus", net.bus, ["vn_kv"])
        bloque("Líneas", "line", net.line, ["length_km", "parallel", "df"])
        bloque("Transformadores", "trafo", net.trafo, ["tap_pos"])
        bloque("Cargas", "load", net.load, ["p_mw", "q_mvar", "scaling"])
        bloque("Solar", "sgen", net.sgen, ["p_mw", "q_mvar", "scaling"])
        bloque("Baterías", "storage", net.storage, ["p_mw", "q_mvar", "max_e_mwh", "soc_percent", "scaling"])
        bloque("Red externa", "ext_grid", net.ext_grid, ["vm_pu", "va_degree"])
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
