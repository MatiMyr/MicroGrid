"""Traducción de una red pandapower a elementos de Dash Cytoscape.

Compartido por el Editor (vista en vivo) y el Dashboard (vista con resultados).
"""
from __future__ import annotations

from typing import Dict, Optional


def _color_por_tension(vm_pu: float) -> str:
    """Verde en tensión sana, amarillo/rojo a medida que se aleja de 1.0 pu."""
    if vm_pu <= 0:
        return "#9e9e9e"
    desvio = abs(vm_pu - 1.0)
    if desvio <= 0.05:
        return "#2e7d32"  # verde
    if desvio <= 0.10:
        return "#f9a825"  # amarillo
    return "#c62828"  # rojo


def _color_por_carga(loading_pct: float) -> str:
    if loading_pct >= 100:
        return "#c62828"
    if loading_pct >= 80:
        return "#f9a825"
    return "#546e7a"


def net_to_elements(
    net,
    voltage_profile: Optional[Dict[int, float]] = None,
    line_loading: Optional[Dict[int, float]] = None,
) -> list[dict]:
    """Devuelve la lista de elementos (nodos y aristas) para ``cyto.Cytoscape``.

    Si se pasan ``voltage_profile`` / ``line_loading`` (resultados de una
    simulación), colorea buses y líneas según su estado.
    """
    elements: list[dict] = []
    voltage_profile = voltage_profile or {}
    line_loading = line_loading or {}

    # Buses
    for idx in net.bus.index:
        nombre = net.bus.at[idx, "name"]
        etiqueta = str(nombre) if nombre is not None and str(nombre) != "nan" else f"Bus {idx}"
        data = {"id": f"b{idx}", "label": etiqueta}
        vm = voltage_profile.get(idx, voltage_profile.get(str(idx)))
        if vm is not None:
            data["color"] = _color_por_tension(float(vm))
            data["label"] = f"{etiqueta}\n{float(vm):.3f} pu"
        else:
            data["color"] = "#1565c0"
        elements.append({"data": data, "classes": "bus"})

    # Líneas
    for idx in net.line.index:
        f, t = int(net.line.at[idx, "from_bus"]), int(net.line.at[idx, "to_bus"])
        data = {"source": f"b{f}", "target": f"b{t}", "id": f"l{idx}", "label": f"L{idx}"}
        load = line_loading.get(idx, line_loading.get(str(idx)))
        data["color"] = _color_por_carga(float(load)) if load is not None else "#90a4ae"
        if load is not None:
            data["label"] = f"L{idx} · {float(load):.0f}%"
        elements.append({"data": data, "classes": "line"})

    # Transformadores
    for idx in net.trafo.index:
        hv, lv = int(net.trafo.at[idx, "hv_bus"]), int(net.trafo.at[idx, "lv_bus"])
        elements.append(
            {
                "data": {"source": f"b{hv}", "target": f"b{lv}", "id": f"t{idx}", "label": f"T{idx}"},
                "classes": "trafo",
            }
        )

    # Elementos conectados (carga, solar, batería, red externa) como nodos hijos.
    _agregar_conectados(elements, net, "load", "Carga", "load")
    _agregar_conectados(elements, net, "sgen", "PV", "sgen")
    _agregar_conectados(elements, net, "storage", "Bat", "storage")
    _agregar_conectados(elements, net, "ext_grid", "Grid", "ext_grid")
    return elements


def _agregar_conectados(elements: list[dict], net, tabla: str, prefijo: str, clase: str) -> None:
    df = getattr(net, tabla, None)
    if df is None:
        return
    for idx in df.index:
        bus = int(df.at[idx, "bus"])
        node_id = f"{clase}{idx}"
        elements.append(
            {"data": {"id": node_id, "label": f"{prefijo} {idx}"}, "classes": clase}
        )
        elements.append(
            {"data": {"source": node_id, "target": f"b{bus}", "id": f"{clase}e{idx}"}, "classes": "conn"}
        )


# Hoja de estilos de Cytoscape reutilizable.
STYLESHEET = [
    {
        "selector": "node.bus",
        "style": {
            "background-color": "data(color)",
            "label": "data(label)",
            "color": "#fff",
            "text-wrap": "wrap",
            "text-valign": "center",
            "text-halign": "center",
            "font-size": "9px",
            "width": "46px",
            "height": "46px",
        },
    },
    {"selector": "node.load", "style": {"background-color": "#6d4c41", "label": "data(label)", "shape": "round-rectangle", "font-size": "8px", "width": "30px", "height": "20px", "color": "#fff"}},
    {"selector": "node.sgen", "style": {"background-color": "#f9a825", "label": "data(label)", "shape": "triangle", "font-size": "8px", "width": "26px", "height": "26px", "color": "#000"}},
    {"selector": "node.storage", "style": {"background-color": "#00897b", "label": "data(label)", "shape": "barrel", "font-size": "8px", "width": "26px", "height": "26px", "color": "#fff"}},
    {"selector": "node.ext_grid", "style": {"background-color": "#37474f", "label": "data(label)", "shape": "diamond", "font-size": "8px", "width": "30px", "height": "30px", "color": "#fff"}},
    {"selector": "edge.line", "style": {"line-color": "data(color)", "width": 4, "label": "data(label)", "font-size": "8px", "curve-style": "bezier"}},
    {"selector": "edge.trafo", "style": {"line-color": "#5e35b1", "width": 5, "label": "data(label)", "line-style": "dashed", "font-size": "8px"}},
    {"selector": "edge.conn", "style": {"line-color": "#b0bec5", "width": 1.5, "line-style": "dotted"}},
]
