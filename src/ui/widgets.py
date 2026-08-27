"""Componentes de UI compartidos por el Editor y el Dashboard.

Sólo lo que las dos pestañas usan igual. Los helpers propios de una (el panel de
detalle del Editor, los KPIs del Dashboard) se quedan en su módulo.
"""
from __future__ import annotations

from dash import dcc, html

from ui.graph_view import LEGEND_BADGES, LEGEND_NODES, LEGEND_STATUS


def error(texto: str):
    """Mensaje de error para una línea de estado.

    Lo distingue el color, no un glifo: el CSS también tiñe la caja entera vía
    `.status:has(.status-error)`, así el aviso se lee de un vistazo sin recurrir
    a un emoji de advertencia.
    """
    return html.Span(texto, className="status-error")


def campo(label: str, id_, value="", tipo: str = "number", **kw):
    """Campo de formulario con su etiqueta encima."""
    return html.Div(
        [html.Label(label), dcc.Input(id=id_, type=tipo, value=value, **kw)],
        className="field",
    )


def _punto(color):
    return html.Span(className="dot", style={"background": color})


def _badge(emoji):
    return html.Span(emoji, className="badge")


def _items(pares, marca):
    """Una fila ``marca — texto`` por par, con ``marca`` armada por ``marca()``."""
    return [html.Div([marca(a), texto], className="item") for a, texto in pares]


def leyenda(con_estado: bool = False):
    """Leyenda del grafo: nodos y badges, y opcionalmente el estado de tensión.

    El estado (sana / alerta / crítica) sólo tiene sentido después de simular, así
    que es exclusivo del Dashboard: en el Editor la red todavía no tiene tensiones.
    """
    partes = _items(LEGEND_NODES, _punto) + _items(LEGEND_BADGES, _badge)
    if con_estado:
        partes.append(html.Span("·", style={"color": "var(--muted)"}))
        partes += _items(LEGEND_STATUS, _punto)
    return html.Div(partes, className="legend")
