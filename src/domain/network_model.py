from __future__ import annotations

import json
from typing import Optional

import pandapower as pp
import pandapower.std_types as st

from domain.entities import Battery, Bus, ExternalGrid, Line, Load, SolarPanel, Transformer


class NetworkModel:
    """Capa de dominio que encapsula todas las llamadas a pandapower."""

    def __init__(self, net: Optional[pp.pandapowerNet] = None):
        if net is None:
            self.net = pp.create_empty_network()
            st.add_basic_std_types(self.net)
        else:
            self.net = net

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
            bus=load.bus,
            p_mw=load.p_mw,
            q_mvar=load.q_mvar,
            name=load.name,
            scaling=load.scaling,
            in_service=load.in_service,
        )

    def add_solar_panel(self, panel: SolarPanel) -> int:
        return pp.create_sgen(
            self.net,
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
            bus=ext_grid.bus,
            vm_pu=ext_grid.vm_pu,
            va_degree=ext_grid.va_degree,
            name=ext_grid.name,
            in_service=ext_grid.in_service,
        )

    def set_field(self, table: str, index: int, field: str, value) -> None:
        """Asigna un parámetro a un elemento existente (edición puntual)."""
        df = getattr(self.net, table, None)
        if df is None or index not in df.index or field not in df.columns:
            return
        if field == "name":
            df.at[index, field] = None if value in (None, "") else str(value)
        else:
            try:
                df.at[index, field] = float(value)
            except (TypeError, ValueError):
                pass

    def remove_bus(self, bus_index: int) -> None:
        pp.drop_buses(self.net, buses=[bus_index], drop_elements=True)

    def remove_element(self, element_type: str, index: int) -> None:
        pp.drop_elements(self.net, element_type=element_type, element_index=[index])

    # ---- ajustes para simulación horaria --------------------------------
    def apply_load_scaling(self, factor: float) -> None:
        """Aplica un factor de escala horario a todas las cargas."""
        if len(self.net.load):
            self.net.load["scaling"] = float(factor)

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
