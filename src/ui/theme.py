"""Paleta y helpers de estilo compartidos por los gráficos Plotly.

Los colores provienen de una paleta validada para daltonismo (dataviz). Los
gráficos usan fondos transparentes y tinta/grilla neutra (#898781 y grises
translúcidos) que se leen bien tanto en tema claro como oscuro, así el mismo
``Figure`` sirve para ambos sin re-render.
"""
from __future__ import annotations

import plotly.graph_objects as go

# Paleta categórica (orden fijo, nunca ciclado).
SERIES = {
    "blue": "#2a78d6",
    "orange": "#eb6834",
    "aqua": "#1baf7a",
    "yellow": "#eda100",
    "magenta": "#e87ba4",
    "violet": "#4a3aa7",
    "red": "#e34948",
}
GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"

# Neutros que funcionan en claro y oscuro.
INK = "#898781"          # ejes / etiquetas (muted, invariante al tema)
GRID = "rgba(137,135,129,0.22)"
BASELINE = "rgba(137,135,129,0.45)"

_FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'


def style(fig: go.Figure, title: str = "", height: int | None = None) -> go.Figure:
    """Aplica el template neutro del proyecto a un ``Figure``."""
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color=INK), x=0.01, xanchor="left"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=_FONT, size=12, color=INK),
        margin=dict(l=48, r=16, t=40 if title else 16, b=34),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=11)),
        hoverlabel=dict(font_size=12, font_family=_FONT),
        colorway=list(SERIES.values()),
    )
    axis = dict(gridcolor=GRID, zerolinecolor=BASELINE, linecolor=BASELINE,
                tickfont=dict(color=INK, size=11), title_font=dict(color=INK, size=12))
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    if height:
        fig.update_layout(height=height)
    return fig


def empty(title: str) -> go.Figure:
    """Figura vacía con un mensaje centrado (estado inicial)."""
    fig = go.Figure()
    fig.add_annotation(text="Corré una simulación para ver resultados",
                       showarrow=False, font=dict(color=INK, size=13),
                       x=0.5, y=0.5, xref="paper", yref="paper")
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return style(fig, title)
