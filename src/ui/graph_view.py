"""Traducción de una red pandapower a elementos de Dash Cytoscape.

Compartido por el Editor (vista en vivo) y el Dashboard (vista con resultados).
"""
from __future__ import annotations

from typing import Dict, Optional


# Estado eléctrico -> paleta de status (dataviz): good / warning / critical.
_GOOD, _WARNING, _CRITICAL, _IDLE = "#0ca30c", "#eda100", "#d03b3b", "#9e9e9e"


def _color_por_tension(vm_pu: float) -> str:
    """Verde en tensión sana, ámbar/rojo a medida que se aleja de 1.0 pu."""
    if vm_pu <= 0:
        return _IDLE
    desvio = abs(vm_pu - 1.0)
    if desvio <= 0.05:
        return _GOOD
    if desvio <= 0.10:
        return _WARNING
    return _CRITICAL


def _color_por_carga(loading_pct: float) -> str:
    if loading_pct >= 100:
        return _CRITICAL
    if loading_pct >= 80:
        return _WARNING
    return "#7a8a99"


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
            data["color"] = "#2a78d6"
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


# Hoja de estilos de Cytoscape reutilizable (paleta del proyecto).
_LABEL = {
    "label": "data(label)", "text-wrap": "wrap", "text-valign": "center",
    "text-halign": "center", "font-family": "system-ui, -apple-system, Segoe UI, sans-serif",
    "font-weight": 600,
}
STYLESHEET = [
    {
        "selector": "node.bus",
        "style": {
            **_LABEL,
            "background-color": "data(color)",
            "color": "#fff",
            "font-size": "9px",
            "width": "48px",
            "height": "48px",
            "border-width": 2,
            "border-color": "rgba(255,255,255,0.55)",
            "text-outline-width": 0,
        },
    },
    {"selector": "node.load", "style": {**_LABEL, "background-color": "#6d5849", "shape": "round-rectangle", "font-size": "8px", "width": "32px", "height": "22px", "color": "#fff"}},
    {"selector": "node.sgen", "style": {**_LABEL, "background-color": "#eda100", "shape": "triangle", "font-size": "8px", "width": "28px", "height": "28px", "color": "#3a2c00"}},
    {"selector": "node.storage", "style": {**_LABEL, "background-color": "#1baf7a", "shape": "barrel", "font-size": "8px", "width": "28px", "height": "28px", "color": "#fff"}},
    {"selector": "node.ext_grid", "style": {**_LABEL, "background-color": "#37474f", "shape": "diamond", "font-size": "8px", "width": "34px", "height": "34px", "color": "#fff"}},
    {"selector": "edge.line", "style": {"line-color": "data(color)", "width": 4, "label": "data(label)", "font-size": "8px", "color": "#898781", "curve-style": "bezier", "text-rotation": "autorotate"}},
    {"selector": "edge.trafo", "style": {"line-color": "#4a3aa7", "width": 5, "label": "data(label)", "line-style": "dashed", "font-size": "8px", "color": "#898781"}},
    {"selector": "edge.conn", "style": {"line-color": "rgba(137,135,129,0.55)", "width": 1.5, "line-style": "dotted"}},
]


# Ítems de leyenda (para render en HTML fuera del canvas Cytoscape).
LEGEND_NODES = [
    ("#2a78d6", "Bus"),
    ("#eda100", "Solar"),
    ("#1baf7a", "Batería"),
    ("#6d5849", "Carga"),
    ("#37474f", "Red externa"),
]
LEGEND_STATUS = [
    ("#0ca30c", "Tensión sana (±5%)"),
    ("#eda100", "Alerta (±5–10%)"),
    ("#d03b3b", "Crítica (>10%)"),
]
