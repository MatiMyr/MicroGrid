from __future__ import annotations

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

    def remove_bus(self, bus_index: int) -> None:
        pp.drop_buses(self.net, buses=[bus_index], drop_elements=True)

    def remove_element(self, element_type: str, index: int) -> None:
        pp.drop_elements(self.net, element_type=element_type, element_index=[index])
