from __future__ import annotations

import copy
import json
from typing import Optional

import pandapower as pp
import pandapower.std_types as st
import pandas.api.types as ptypes

from domain.entities import (
    TIPO_CARGA_POR_DEFECTO,
    TIPOS_CARGA,
    Battery,
    Bus,
    ExternalGrid,
    Line,
    Load,
    SolarPanel,
    Transformer,
)


def _es_numerico(valor) -> bool:
    """Indica si ``valor`` representa un número (incluye el texto de un formulario)."""
    if isinstance(valor, bool) or valor is None:
        return False
    try:
        float(valor)
    except (TypeError, ValueError):
        return False
    return True


class NetworkModel:
    """Capa de dominio que encapsula todas las llamadas a pandapower."""

    def __init__(self, net: Optional[pp.pandapowerNet] = None):
        if net is None:
            self.net = pp.create_empty_network()
            st.add_basic_std_types(self.net)
        else:
            self.net = net

    def copy(self) -> "NetworkModel":
        """Devuelve una copia profunda e independiente de la red.

        La usa la simulación para no escribir sobre la red viva del Editor: una
        corrida horaria pisa ``scaling`` y ``soc_percent`` hora tras hora y
        ``pp.runpp`` agrega las tablas ``res_*``. Sobre una copia, la red que el
        usuario está editando (y que eventualmente va a guardar) queda intacta.
        """
        return NetworkModel(copy.deepcopy(self.net))

    def add_bus(self, bus: Bus) -> int:
        return pp.create_bus(
            self.net,
            index=bus.index,
            vn_kv=bus.vn_kv,
            name=bus.name,
            type=bus.type,
            in_service=bus.in_service,
        )

    def add_line(self, line: Line) -> int:
        return pp.create_line(
            self.net,
            index=line.index,
            from_bus=line.from_bus,
            to_bus=line.to_bus,
            length_km=line.length_km,
            std_type=line.std_type,
            name=line.name,
            df=line.df,
            parallel=line.parallel,
            in_service=line.in_service,
        )

    def add_transformer(self, transformer: Transformer) -> int:
        return pp.create_transformer(
            self.net,
            index=transformer.index,
            hv_bus=transformer.hv_bus,
            lv_bus=transformer.lv_bus,
            std_type=transformer.std_type,
            name=transformer.name,
            tap_pos=transformer.tap_pos,
            in_service=transformer.in_service,
        )

    def add_load(self, load: Load) -> int:
        return pp.create_load(
            self.net,
            index=load.index,
            bus=load.bus,
            p_mw=load.p_mw,
            q_mvar=load.q_mvar,
            name=load.name,
            scaling=load.scaling,
            in_service=load.in_service,
            # Columna propia del proyecto: viaja con la red en ``pp.to_json``.
            perfil_tipo=load.perfil_tipo,
        )

    def add_solar_panel(self, panel: SolarPanel) -> int:
        return pp.create_sgen(
            self.net,
            index=panel.index,
            bus=panel.bus,
            p_mw=panel.p_mw,
            q_mvar=panel.q_mvar,
            name=panel.name,
            scaling=panel.scaling,
            type="wye",
            in_service=panel.in_service,
        )

    def add_battery(self, battery: Battery) -> int:
        return pp.create_storage(
            self.net,
            index=battery.index,
            bus=battery.bus,
            p_mw=battery.p_mw,
            q_mvar=battery.q_mvar,
            max_e_mwh=battery.max_e_mwh,
            soc_percent=battery.soc_percent,
            name=battery.name,
            scaling=battery.scaling,
            in_service=battery.in_service,
        )

    def add_ext_grid(self, ext_grid: ExternalGrid) -> int:
        return pp.create_ext_grid(
            self.net,
            index=ext_grid.index,
            bus=ext_grid.bus,
            vm_pu=ext_grid.vm_pu,
            va_degree=ext_grid.va_degree,
            name=ext_grid.name,
            in_service=ext_grid.in_service,
        )

    def set_field(self, table: str, index: int, field: str, value) -> None:
        """Asigna un parámetro a un elemento existente (edición puntual).

        La conversión la decide el **dtype de la columna**, no el tipo del valor
        recibido: las columnas numéricas castean a ``float`` (así los formularios
        del Editor, que entregan texto, siguen funcionando) y las columnas de
        texto o booleanas se asignan tal cual. Sin esto, campos como
        ``trafo.tap_side='hv'`` o ``line.type='cs'`` no se podían escribir.
        """
        df = getattr(self.net, table, None)
        if df is None or index not in df.index:
            return
        if field not in df.columns:
            # Columna opcional de pandapower que la red todavía no tiene (p. ej.
            # ``min_vm_pu`` o ``max_loading_percent``, que solo aparecen cuando
            # se usan). Se crea vacía para poder escribirla: si no, reconstruir
            # una red desde el código generado perdía los límites de OPF.
            #
            # El tipo de la columna nueva lo define el valor, pero un texto que
            # es un número (lo que entregan los formularios) crea una columna
            # numérica: si no, quedaba de objetos y rompía la coherencia que
            # promete el resto del método.
            if isinstance(value, bool):
                df[field] = False
            elif _es_numerico(value):
                df[field] = float("nan")
            else:
                df[field] = None
        if field == "name":
            df.at[index, field] = None if value in (None, "") else str(value)
            return
        columna = df[field]
        if ptypes.is_bool_dtype(columna):
            df.at[index, field] = bool(value)
        elif ptypes.is_numeric_dtype(columna):
            try:
                df.at[index, field] = float(value)
            except (TypeError, ValueError):
                pass
        else:
            df.at[index, field] = value

    def remove_bus(self, bus_index: int) -> None:
        pp.drop_buses(self.net, buses=[bus_index], drop_elements=True)

    def remove_element(self, element_type: str, index: int) -> None:
        pp.drop_elements(self.net, element_type=element_type, element_index=[index])

    # ---- tipo de consumidor por carga -----------------------------------
    def tipo_de_carga(self, idx: int) -> str:
        """Tipo de consumidor de una carga, con respaldo al valor por defecto.

        Las redes importadas (SimBench) y las guardadas antes de que existiera la
        columna no la traen, y ``pp.from_json`` deja ``None`` donde no había
        dato: en ambos casos se asume el tipo por defecto.
        """
        df = self.net.load
        if "perfil_tipo" not in df.columns or idx not in df.index:
            return TIPO_CARGA_POR_DEFECTO
        valor = df.at[idx, "perfil_tipo"]
        if valor is None or str(valor) == "nan":
            return TIPO_CARGA_POR_DEFECTO
        valor = str(valor).lower()
        return valor if valor in TIPOS_CARGA else TIPO_CARGA_POR_DEFECTO

    def tipos_de_carga(self) -> dict[int, str]:
        """Mapa ``índice de carga -> tipo de consumidor`` para toda la red."""
        return {int(i): self.tipo_de_carga(i) for i in self.net.load.index}

    def set_tipo_de_carga(self, idx: int, tipo: str) -> None:
        """Asigna el tipo de consumidor de una carga (ignora valores desconocidos)."""
        tipo = str(tipo).lower()
        if idx not in self.net.load.index or tipo not in TIPOS_CARGA:
            return
        if "perfil_tipo" not in self.net.load.columns:
            self.net.load["perfil_tipo"] = TIPO_CARGA_POR_DEFECTO
        self.net.load.at[idx, "perfil_tipo"] = tipo

    # ---- ajustes para simulación horaria --------------------------------
    def apply_load_scaling(self, factor: float) -> None:
        """Aplica un mismo factor de escala horario a todas las cargas."""
        if len(self.net.load):
            self.net.load["scaling"] = float(factor)

    def apply_load_scaling_por_tipo(self, factores: dict[str, float]) -> None:
        """Escala cada carga según el factor horario de **su** tipo de consumidor.

        ``factores`` es ``{tipo -> factor de esta hora}``. A diferencia de
        ``apply_load_scaling``, permite que en la misma red convivan viviendas,
        comercios e industria con curvas distintas —lo necesario para mapear,
        por ejemplo, un barrio— en vez de imponer una única curva a toda la red.
        """
        if not len(self.net.load):
            return
        for idx in self.net.load.index:
            tipo = self.tipo_de_carga(idx)
            self.net.load.at[idx, "scaling"] = float(
                factores.get(tipo, factores.get(TIPO_CARGA_POR_DEFECTO, 1.0))
            )

    def apply_sgen_scaling(self, factor: float) -> None:
        """Aplica un factor de escala horario a toda la generación solar (sgen)."""
        if len(self.net.sgen):
            self.net.sgen["scaling"] = float(factor)

    # ---- posición gráfica de los buses (geo) ----------------------------
    def set_bus_position(self, bus_index: int, x: float, y: float) -> None:
        """Fija la posición gráfica de un bus (se guarda como GeoJSON Point)."""
        if bus_index in self.net.bus.index:
            self.net.bus.at[bus_index, "geo"] = json.dumps(
                {"coordinates": [round(float(x), 4), round(float(y), 4)], "type": "Point"}
            )

    def get_bus_position(self, bus_index: int) -> Optional[tuple[float, float]]:
        """Devuelve (x, y) del bus, o ``None`` si no tiene posición asignada."""
        if bus_index not in self.net.bus.index:
            return None
        geo = self.net.bus.at[bus_index, "geo"]
        if geo is None or str(geo) == "nan":
            return None
        try:
            x, y = json.loads(geo)["coordinates"]
            return float(x), float(y)
        except (ValueError, KeyError, TypeError):
            return None

    def bus_positions(self) -> dict[int, tuple[float, float]]:
        """Mapa ``bus_index -> (x, y)`` de los buses con posición asignada."""
        out: dict[int, tuple[float, float]] = {}
        for idx in self.net.bus.index:
            pos = self.get_bus_position(idx)
            if pos is not None:
                out[int(idx)] = pos
        return out

    def normalize_positions(self, target: float = 10.0) -> None:
        """Reescala las posiciones de los buses a un rango consistente (0..target).

        Las redes SimBench traen ``geo`` con lat/lon reales cuyo rango es
        minúsculo (p. ej. span de 0.003°): con una escala fija todos los nodos
        colapsarían en un punto. Esto los remapea a un lienzo homogéneo,
        preservando la relación de aspecto, para que el grafo se vea legible y
        el arrastre (que asume este rango) guarde coordenadas coherentes.
        """
        pos = self.bus_positions()
        if len(pos) < 2:
            return
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        span_x, span_y = maxx - minx, maxy - miny
        span = max(span_x, span_y)
        if span <= 0:
            # Todos los buses en la misma coordenada: no hay nada que reescalar y
            # dejarlos así mandaba al grafo píxeles muy fuera del lienzo. Se los
            # reparte con el layout automático, que sí produce un rango usable.
            for idx in pos:
                self.net.bus.at[idx, "geo"] = None
            self.ensure_positions()
            return
        scale = target / span
        for idx, (x, y) in pos.items():
            self.set_bus_position(idx, (x - minx) * scale, (y - miny) * scale)

    def ensure_positions(self) -> None:
        """Asigna posiciones a los buses que no tengan una (layout automático).

        Usa un layout de resorte (networkx) sobre el grafo de líneas y trafos,
        determinista, para que toda red — nueva o importada sin geodata — tenga
        coordenadas y el grafo pueda dibujarse con posiciones fijas y editables.
        """
        faltan = [int(i) for i in self.net.bus.index if self.get_bus_position(i) is None]
        if not faltan:
            return
        import networkx as nx

        g = nx.Graph()
        g.add_nodes_from(int(i) for i in self.net.bus.index)
        for _, row in self.net.line.iterrows():
            g.add_edge(int(row["from_bus"]), int(row["to_bus"]))
        for _, row in self.net.trafo.iterrows():
            g.add_edge(int(row["hv_bus"]), int(row["lv_bus"]))
        pos = nx.spring_layout(g, seed=42, scale=10.0) if len(g) else {}
        for i in faltan:
            x, y = pos.get(i, (0.0, 0.0))
            self.set_bus_position(i, x, y)

    def set_storage_soc(self, soc_percent) -> None:
        """Fija el SoC inicial de las baterías.

        ``soc_percent`` puede ser un único valor (para todas) o un dict
        ``{index -> soc_percent}``.
        """
        if not len(self.net.storage):
            return
        if isinstance(soc_percent, dict):
            for idx, soc in soc_percent.items():
                if idx in self.net.storage.index:
                    self.net.storage.at[idx, "soc_percent"] = float(soc)
        else:
            self.net.storage["soc_percent"] = float(soc_percent)
