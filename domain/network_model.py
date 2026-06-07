from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandapower as pp
import pandapower.std_types as st


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
    tap_pos: float = 0.0
    in_service: bool = True


@dataclass
class Load:
    """Carga conectada a un bus."""

    bus: int
    p_mw: float
    q_mvar: float = 0.0
    name: Optional[str] = None
    scaling: float = 1.0
    in_service: bool = True


@dataclass
class SolarPanel:
    """Panel solar representado como generación distribuida."""

    bus: int
    p_mw: float
    q_mvar: float = 0.0
    name: Optional[str] = None
    scaling: float = 1.0
    in_service: bool = True


@dataclass
class Battery:
    """Batería de almacenamiento conectada a un bus."""

    bus: int
    p_mw: float
    max_e_mwh: float
    q_mvar: float = 0.0
    soc_percent: float = 100.0
    name: Optional[str] = None
    in_service: bool = True


@dataclass
class ExternalGrid:
    """Fuente externa de alimentación para la red."""

    bus: int
    vm_pu: float = 1.0
    va_degree: float = 0.0
    name: Optional[str] = None
    in_service: bool = True


class NetworkModel:
    """Capa de dominio que encapsula todas las llamadas a pandapower."""

    def __init__(self, net: Optional[pp.pandapowerNet] = None):
        self.net = net if net is not None else pp.create_empty_network()

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
        st.add_basic_std_types(self.net)
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
        st.add_basic_std_types(self.net)
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

    def remove_bus(self, bus_index: int) -> None:
        pp.drop_buses(self.net, buses=[bus_index], drop_elements=True)

    def remove_line(self, line_index: int) -> None:
        pp.drop_elements(self.net, element_type="line", element_index=[line_index])

    def remove_transformer(self, transformer_index: int) -> None:
        pp.drop_elements(self.net, element_type="trafo", element_index=[transformer_index])

    def remove_load(self, load_index: int) -> None:
        pp.drop_elements(self.net, element_type="load", element_index=[load_index])

    def remove_solar_panel(self, sgen_index: int) -> None:
        pp.drop_elements(self.net, element_type="sgen", element_index=[sgen_index])

    def remove_battery(self, storage_index: int) -> None:
        pp.drop_elements(self.net, element_type="storage", element_index=[storage_index])

    def summary(self) -> dict[str, int]:
        return {
            "buses": len(self.net.bus),
            "lines": len(self.net.line),
            "trafos": len(self.net.trafo),
            "loads": len(self.net.load),
            "sgens": len(self.net.sgen),
            "storages": len(self.net.storage),
        }
