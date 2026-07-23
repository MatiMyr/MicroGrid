"""Traducción de una red pandapower a elementos de Dash Cytoscape.

Compartido por el Editor (vista en vivo) y el Dashboard (vista con resultados).
"""
from __future__ import annotations

import json
from typing import Dict, Optional


# Estado eléctrico -> paleta de status (dataviz): good / warning / critical.
_GOOD, _WARNING, _CRITICAL, _IDLE = "#0ca30c", "#eda100", "#d03b3b", "#9e9e9e"

# Escala geo -> píxeles.
_SCALE = 34.0

# Emojis de los elementos conectados, mostrados como badges sobre el bus
# (en vez de nodos aparte) para que el grafo escale a redes grandes.
_BADGE = {"sgen": "☀", "storage": "🔋", "load": "🏠", "ext_grid": "🔌"}


def pixel_to_geo(x: float, y: float) -> tuple[float, float]:
    """Convierte una posición de pantalla (px) de vuelta a coordenadas geo."""
    return round(float(x) / _SCALE, 4), round(-float(y) / _SCALE, 4)


def _bus_xy(net, idx) -> Optional[tuple[float, float]]:
    """Posición (x, y) en píxeles de un bus a partir de su geo (GeoJSON)."""
    geo = net.bus.at[idx, "geo"] if "geo" in net.bus.columns else None
    if geo is None or str(geo) == "nan":
        return None
    try:
        x, y = json.loads(geo)["coordinates"]
        # y invertida: en pantalla crece hacia abajo.
        return float(x) * _SCALE, -float(y) * _SCALE
    except (ValueError, KeyError, TypeError):
        return None


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
    editable: bool = False,
) -> list[dict]:
    """Devuelve la lista de elementos (nodos y aristas) para ``cyto.Cytoscape``.

    Si se pasan ``voltage_profile`` / ``line_loading`` (resultados de una
    simulación), colorea buses y líneas según su estado. Si los buses tienen
    posición (``net.bus.geo``), cada nodo trae su ``position`` para usar el
    layout ``preset``. Con ``editable=True`` los buses son arrastrables; los
    demás nodos quedan fijos siempre.
    """
    elements: list[dict] = []
    voltage_profile = voltage_profile or {}
    line_loading = line_loading or {}

    # Conteo de elementos conectados por bus (para los badges).
    def _por_bus(tabla) -> Dict[int, int]:
        df = getattr(net, tabla, None)
        if df is None or not len(df):
            return {}
        return {int(k): int(v) for k, v in df["bus"].value_counts().items()}

    conteos = {clase: _por_bus(clase) for clase in _BADGE}

    def _badges(bus_idx: int) -> str:
        partes = []
        for clase, emoji in _BADGE.items():
            n = conteos[clase].get(bus_idx, 0)
            if n:
                partes.append(f"{emoji}{n}" if n > 1 else emoji)
        return " ".join(partes)

    # Buses (con badges de sus elementos conectados) + jitter anti-superposición.
    usados: Dict[tuple[int, int], int] = {}
    for idx in net.bus.index:
        bus_idx = int(idx)
        nombre = net.bus.at[idx, "name"]
        etiqueta = str(nombre) if nombre is not None and str(nombre) != "nan" else f"Bus {idx}"
        badges = _badges(bus_idx)
        vm = voltage_profile.get(idx, voltage_profile.get(str(idx)))
        if vm is not None:
            color = _color_por_tension(float(vm))
            label = f"{etiqueta}\n{float(vm):.3f} pu"
        else:
            color = "#2a78d6"
            label = etiqueta
        if badges:
            label = f"{label}\n{badges}"
        es_slack = conteos["ext_grid"].get(bus_idx, 0) > 0
        el = {
            "data": {"id": f"b{bus_idx}", "label": label, "color": color},
            "classes": "bus slack" if es_slack else "bus",
            "grabbable": bool(editable),
        }
        pos = _bus_xy(net, idx)
        if pos is not None:
            x, y = pos
            # Separa buses en coordenadas (casi) coincidentes con un desplazamiento
            # determinista, para que no queden apilados uno sobre otro.
            clave = (round(x / 6), round(y / 6))
            k = usados.get(clave, 0)
            usados[clave] = k + 1
            if k:
                x += 9 * k
                y += 9 * k
            el["position"] = {"x": x, "y": y}
        elements.append(el)

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

    return elements


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
            "width": "42px",
            "height": "42px",
            "border-width": 2,
            "border-color": "rgba(255,255,255,0.55)",
            "text-outline-width": 0,
            "text-max-width": "80px",
        },
    },
    # Bus con red externa (slack): anillo dorado distintivo.
    {"selector": "node.slack", "style": {"border-width": 4, "border-color": "#eda100"}},
    {"selector": "edge.line", "style": {"line-color": "data(color)", "width": 4, "label": "data(label)", "font-size": "8px", "color": "#898781", "curve-style": "bezier", "text-rotation": "autorotate"}},
    {"selector": "edge.trafo", "style": {"line-color": "#4a3aa7", "width": 5, "label": "data(label)", "line-style": "dashed", "font-size": "8px", "color": "#898781"}},
    {"selector": "node:selected", "style": {"border-width": 4, "border-color": "#2a78d6"}},
]


# Leyenda: nodo bus + badges de elementos conectados + estado de tensión.
LEGEND_NODES = [
    ("#2a78d6", "Bus (sin simular)"),
]
# Badges (emoji sobre el bus) — se renderizan como texto, no como punto de color.
LEGEND_BADGES = [
    ("☀", "Solar"),
    ("🔋", "Batería"),
    ("🏠", "Carga"),
    ("🔌", "Red externa"),
]
LEGEND_STATUS = [
    ("#0ca30c", "Tensión sana (±5%)"),
    ("#eda100", "Alerta (±5–10%)"),
    ("#d03b3b", "Crítica (>10%)"),
]
