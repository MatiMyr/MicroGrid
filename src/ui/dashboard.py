"""Dashboard: corre simulaciones y muestra resultados.

Pide la red al Servicio Red y los resultados al Servicio Simulación, y actualiza
los indicadores, el grafo y los gráficos. Incluye un panel para sincronizar los
datos externos (CAMMESA / NASA / SimBench) a mano. Callbacks propios del
Dashboard viven en este archivo.
"""
from __future__ import annotations

from datetime import date, timedelta

import dash_cytoscape as cyto
import plotly.graph_objects as go
from dash import Input, Output, State, ctx, dcc, html
from plotly.subplots import make_subplots

from app.simulation_service import SimulationService
from ui import theme
from app.data_sync_service import CAMMESA_REGIONES
from ui.graph_view import LEGEND_BADGES, LEGEND_NODES, LEGEND_STATUS, STYLESHEET, net_to_elements

REGIONES = sorted(CAMMESA_REGIONES)


def _valor(dado, default):
    """Devuelve ``dado`` salvo que falte de verdad (``None`` o texto vacío).

    Reemplaza al patrón ``dado or default``, que trataba el 0 como "sin valor":
    una latitud 0 se convertía en -31.4 y un SoC inicial de 0 % en 50 %.
    """
    if dado is None:
        return default
    if isinstance(dado, str) and not dado.strip():
        return default
    return dado


def _kpi(titulo, id_, accent=False):
    return html.Div(
        [html.Div(titulo, className="kpi-label"),
         html.Div("—", id=id_, className="kpi-value")],
        className="kpi accent" if accent else "kpi",
    )


def _campo(label, id_, value, tipo="number", **kw):
    return html.Div(
        [html.Label(label), dcc.Input(id=id_, type=tipo, value=value, **kw)],
        className="field",
    )


def _dropdown(label, id_, options, value):
    return html.Div(
        [html.Label(label),
         dcc.Dropdown(id=id_, options=options, value=value, clearable=False,
                      className="dash-dropdown")],
        className="field", style={"minWidth": "150px"},
    )


def _rango_nasa_por_defecto() -> tuple[str, str]:
    """Semana equivalente del año pasado, en formato ``AAAAMMDD``.

    NASA POWER publica sus datos horarios con varios meses de demora, así que
    pedir "la semana pasada" devuelve vacío. Una semana del año anterior está
    siempre disponible y además es estacionalmente comparable con hoy.
    """
    hasta = date.today() - timedelta(days=365)
    desde = hasta - timedelta(days=6)
    return desde.strftime("%Y%m%d"), hasta.strftime("%Y%m%d")


_RANGO_NASA = _rango_nasa_por_defecto()


def _aviso_sin_solucion(resultados) -> str:
    """Texto de aviso cuando parte de la red no tuvo solución eléctrica.

    Los elementos sin camino al nodo slack quedan fuera de los indicadores; sin
    este aviso, la corrida parecía haber simulado la red entera.
    """
    if not resultados:
        return ""
    buses = len(resultados[0].buses_sin_solucion)
    lineas = len(resultados[0].lineas_sin_solucion)
    if not buses and not lineas:
        return ""
    partes = []
    if buses:
        partes.append(f"{buses} bus" + ("es" if buses > 1 else ""))
    if lineas:
        partes.append(f"{lineas} línea" + ("s" if lineas > 1 else ""))
    return ("  ⚠ " + " y ".join(partes) + " sin conexión al nodo slack: quedan fuera de los "
            "indicadores y se muestran en gris en el grafo.")


def _legend():
    nodes = [html.Div([html.Span(className="dot", style={"background": c}), t], className="item")
             for c, t in LEGEND_NODES]
    badges = [html.Div([html.Span(e, className="badge"), t], className="item")
              for e, t in LEGEND_BADGES]
    status = [html.Div([html.Span(className="dot", style={"background": c}), t], className="item")
              for c, t in LEGEND_STATUS]
    sep = html.Span("·", style={"color": "var(--muted)"})
    return html.Div(nodes + badges + [sep] + status, className="legend")


def layout():
    return html.Div(
        [
            # ---- Cartel sitewide: red del editor desincronizada ----
            html.Div(id="db-stale-banner", className="sitewide-banner", style={"display": "none"}),
            dcc.Interval(id="db-stale-check", interval=1500, n_intervals=0),
            # ---- Controles ----
            html.Div(
                [
                    html.H3("Configuración de la corrida"),
                    html.P("Simulá la microgrid hora a hora. El tipo de consumidor de cada carga "
                           "y el SoC inicial de cada batería se configuran en el Editor, tocando "
                           "su bus: así una misma red puede mezclar viviendas, comercios e industria.",
                           className="card-sub"),
                    html.Div(
                        [
                            _dropdown("Tipo de flujo", "db-mode",
                                      [{"label": "Flujo de carga (runpp)", "value": "pp"},
                                       {"label": "Flujo óptimo (runopp)", "value": "opp"}], "pp"),
                            _campo("Horas", "db-horas", 24,
                                   min=SimulationService.MIN_HORAS, max=SimulationService.MAX_HORAS),
                            _campo("Lat", "db-lat", -31.4),
                            _campo("Lon", "db-lon", -60.5),
                            html.Div(html.Button("▶  Correr simulación", id="db-btn-run", n_clicks=0,
                                                 className="btn btn-primary"),
                                     className="field", style={"flex": "0 0 auto", "justifyContent": "flex-end"}),
                        ],
                        className="row",
                    ),
                    dcc.Loading(html.Div(id="db-status", className="status", style={"marginTop": "12px"}),
                                type="dot", color=theme.SERIES["blue"]),
                ],
                className="card",
            ),
            # ---- KPIs ----
            html.Div(
                [
                    _kpi("Pérdidas totales", "db-kpi-losses", accent=True),
                    _kpi("Tensión mín.", "db-kpi-vmin"),
                    _kpi("Tensión máx.", "db-kpi-vmax"),
                    _kpi("Cargabilidad máx.", "db-kpi-load"),
                    _kpi("Autosuficiencia", "db-kpi-auto"),
                    _kpi("Excedente exportado", "db-kpi-export"),
                ],
                className="kpi-grid", style={"marginBottom": "16px"},
            ),
            # ---- Slider de hora ----
            html.Div(
                [
                    html.Div("Hora de la corrida", className="section-title"),
                    dcc.Slider(id="db-hora", min=0, max=0, step=1, value=0, marks={0: "0"}),
                ],
                className="card",
            ),
            # ---- Grafo + perfil de tensión ----
            html.Div(
                [
                    html.Div(
                        html.Div(
                            [_legend(),
                             html.Div("Solo lectura: zoom con la rueda (las marcas mantienen su tamaño y los buses se separan) "
                                      "y arrastre del fondo para desplazarte. Los nodos no se editan acá.",
                                      className="card-sub", style={"padding": "0 14px"}),
                             cyto.Cytoscape(id="db-graph", className="cyto-grid",
                                            layout={"name": "preset", "fit": True, "padding": 40},
                                            style={"width": "100%", "height": "44vh"},
                                            stylesheet=STYLESHEET, elements=[],
                                            autoRefreshLayout=False, autoungrabify=True,
                                            autounselectify=True, userPanningEnabled=True,
                                            userZoomingEnabled=True, boxSelectionEnabled=False,
                                            minZoom=0.1, maxZoom=12, wheelSensitivity=0.2)],
                            className="graph-frame",
                        ),
                    ),
                    html.Div(
                        html.Div(dcc.Graph(id="db-fig-voltage", config={"displaylogo": False},
                                           style={"height": "46vh"}),
                                 className="graph-frame", style={"padding": "8px"}),
                    ),
                ],
                className="grid-2",
            ),
            # ---- Series temporales ----
            html.Div(
                html.Div(dcc.Graph(id="db-fig-series", config={"displaylogo": False},
                                   style={"height": "34vh"}),
                         className="graph-frame", style={"padding": "8px", "marginTop": "16px"}),
            ),
            # ---- Sync de datos ----
            html.Details(
                [
                    html.Summary("🔄  Sincronizar datos externos"),
                    html.Div(
                        [
                            html.P("Descargá series reales para reemplazar los perfiles sintéticos. "
                                   "Las series se guardan en hora local argentina.",
                                   className="card-sub"),
                            html.Div(
                                [_campo("Irradiación desde", "db-nasa-desde", _RANGO_NASA[0], tipo="text"),
                                 _campo("hasta", "db-nasa-hasta", _RANGO_NASA[1], tipo="text"),
                                 html.Button("NASA POWER (irradiación)", id="db-sync-nasa", n_clicks=0,
                                             className="btn btn-sm")],
                                className="row",
                            ),
                            html.P("Formato AAAAMMDD. NASA POWER publica con unos meses de demora: "
                                   "por eso el rango por defecto es la misma semana del año pasado.",
                                   className="card-sub"),
                            html.Div(
                                [_campo("Código SimBench", "db-simbench-code", "1-LV-rural1--0-no_sw", tipo="text"),
                                 html.Button("Descargar red base", id="db-sync-simbench", n_clicks=0,
                                             className="btn btn-sm")],
                                className="row",
                            ),
                            html.Div(
                                [_dropdown("Región (CAMMESA)", "db-region",
                                           [{"label": r.capitalize(), "value": r} for r in REGIONES],
                                           "LITORAL"),
                                 html.Button("CAMMESA (demanda)", id="db-sync-cammesa", n_clicks=0,
                                             className="btn btn-sm", disabled=True)],
                                className="row",
                            ),
                            html.P("La demanda de CAMMESA está deshabilitada: su serie es el consumo "
                                   "agregado de una región entera, así que imponía una única curva a "
                                   "toda la red y anulaba el tipo de consumidor de cada carga. Se "
                                   "reactivará cuando se defina cómo repartirla entre cargas.",
                                   className="card-sub"),
                            html.Div(
                                html.Button("🗑  Limpiar caché de resultados", id="db-purgar",
                                            n_clicks=0, className="btn btn-sm"),
                                className="row", style={"marginTop": "10px"},
                            ),
                            html.P("Los resultados cacheados son datos derivados: borrarlos solo obliga "
                                   "a recalcular. No toca las redes guardadas ni los datos externos.",
                                   className="card-sub"),
                            dcc.Loading(html.Div(id="db-sync-status", className="status", style={"marginTop": "10px"}),
                                        type="dot", color=theme.SERIES["blue"]),
                        ],
                        className="acc-body",
                    ),
                ],
                className="acc", style={"marginTop": "16px"},
            ),
            dcc.Store(id="db-store"),
        ],
    )


def register_callbacks(app, services):
    network_service = services["network_service"]
    simulation_service = services["simulation_service"]
    data_sync_service = services["data_sync_service"]

    # El zoom-mapa y la grilla del db-graph se instalan solos desde
    # assets/graph_zoom.js (intervalo autónomo), no desde un callback de Dash.

    # ---- cartel: la red del editor difiere de la simulada ----
    @app.callback(
        Output("db-stale-banner", "children"),
        Output("db-stale-banner", "style"),
        Input("db-stale-check", "n_intervals"),
    )
    def revisar_desincronizacion(_n):
        actual = simulation_service.network_signature()
        ultima = simulation_service.last_run_signature
        if ultima is not None and actual == ultima:
            return "", {"display": "none"}
        if ultima is None:
            msg = ("Todavía no simulaste esta red. Corré la simulación para ver los "
                   "resultados en el Dashboard.")
        else:
            msg = ("La red fue modificada en el Editor desde la última simulación. "
                   "Corré la simulación para actualizar los resultados del Dashboard.")
        return ([html.Span("⚠", className="sw-icon"), html.Span(msg)],
                {"display": "flex"})

    # ---- correr simulación ----
    @app.callback(
        Output("db-store", "data"),
        Output("db-status", "children"),
        Output("db-hora", "value"),
        Input("db-btn-run", "n_clicks"),
        State("db-mode", "value"), State("db-horas", "value"),
        State("db-lat", "value"), State("db-lon", "value"),
        prevent_initial_call=True,
    )
    def correr(_n, mode, horas, lat, lon):
        try:
            run = simulation_service.run_corrida(
                horas=_valor(horas, 24), mode=mode or "pp",
                nombre_red=network_service.nombre_guardada(network_service.red_id) or "actual",
                lat=float(_valor(lat, -31.4)), lon=float(_valor(lon, -60.5)),
            )
            resultados = run["resultados"]
            data = [{
                "hour": r.hour_index,
                "voltage": {int(k): v for k, v in r.voltage_profile.items()},
                "loading": {int(k): v for k, v in r.line_loading_pct.items()},
                "losses": r.total_losses_mw,
                "auto": r.autosufficiency_pct,
                "export": r.export_surplus_mw,
            } for r in resultados]

            msg = f"✓ Corrida completa: {len(data)} instantes simulados (run {run['run_id'][:8]}…)."
            msg += _aviso_sin_solucion(resultados)
            # El slider vuelve a la hora 0: si no, una corrida más corta que la
            # anterior dejaba el cursor en una hora que ya no existe.
            return data, msg, 0
        except Exception as exc:  # noqa: BLE001
            return None, f"⚠ Error: {exc}", 0

    # ---- actualizar vista según store + hora ----
    @app.callback(
        Output("db-kpi-losses", "children"), Output("db-kpi-vmin", "children"),
        Output("db-kpi-vmax", "children"), Output("db-kpi-load", "children"),
        Output("db-kpi-auto", "children"), Output("db-kpi-export", "children"),
        Output("db-graph", "elements"), Output("db-fig-voltage", "figure"),
        Output("db-fig-series", "figure"), Output("db-hora", "max"), Output("db-hora", "marks"),
        Input("db-store", "data"), Input("db-hora", "value"),
    )
    def actualizar(data, hora):
        modelo = network_service.get_network()
        modelo.ensure_positions()
        net = modelo.net
        if not data:
            return ("—", "—", "—", "—", "—", "—", net_to_elements(net),
                    theme.empty("Perfil de tensión por nodo"),
                    theme.empty("Indicadores a lo largo de la corrida"), 0, {0: "0"})

        h = min(int(_valor(hora, 0)), len(data) - 1)
        inst = data[h]
        # Se filtran los no numéricos por si algún día vuelve a colarse un hueco:
        # el store viaja por JSON, donde un NaN llega convertido en ``null`` y
        # hacía reventar la comparación de ``min`` con un 500 del servidor.
        volt = {int(k): float(v) for k, v in inst["voltage"].items()
                if isinstance(v, (int, float))}
        load = {int(k): float(v) for k, v in inst["loading"].items()
                if isinstance(v, (int, float))}
        vmin = min(volt.values()) if volt else 0.0
        vmax = max(volt.values()) if volt else 0.0
        load_max = max(load.values()) if load else 0.0

        elements = net_to_elements(net, voltage_profile=volt, line_loading=load)

        # Perfil de tensión (barras, una serie -> sin leyenda).
        fig_v = go.Figure()
        colores = [theme.CRITICAL if abs(v - 1) > 0.1 else theme.WARNING if abs(v - 1) > 0.05 else theme.SERIES["blue"]
                   for v in volt.values()]
        fig_v.add_bar(x=[f"Bus {k}" for k in volt], y=list(volt.values()),
                      marker_color=colores, marker_line_width=0,
                      hovertemplate="%{x}: %{y:.3f} pu<extra></extra>")
        theme.style(fig_v, f"Perfil de tensión por nodo — hora {h}")
        fig_v.update_yaxes(title="Tensión [pu]", range=[min(0.9, vmin - 0.02), max(1.1, vmax + 0.02)])
        for y in (0.95, 1.05):
            fig_v.add_hline(y=y, line_dash="dot", line_color=theme.CRITICAL, line_width=1,
                            annotation_text=f"{y:g} pu", annotation_font_size=10,
                            annotation_font_color=theme.INK)

        # Series por hora: small multiples (una escala por panel, sin doble eje).
        horas = [d["hour"] for d in data]
        fig_s = make_subplots(rows=1, cols=3, shared_xaxes=False,
                              subplot_titles=("Pérdidas [MW]", "Autosuficiencia [%]", "Excedente exportado [MW]"),
                              horizontal_spacing=0.08)
        fig_s.add_scatter(x=horas, y=[d["losses"] for d in data], mode="lines+markers",
                          line_color=theme.SERIES["blue"], marker_size=5, name="Pérdidas",
                          hovertemplate="h%{x}: %{y:.4f} MW<extra></extra>", row=1, col=1)
        fig_s.add_scatter(x=horas, y=[d["auto"] for d in data], mode="lines+markers",
                          line_color=theme.SERIES["aqua"], marker_size=5, name="Autosuf.",
                          hovertemplate="h%{x}: %{y:.1f} %<extra></extra>", row=1, col=2)
        fig_s.add_scatter(x=horas, y=[d["export"] for d in data], mode="lines+markers",
                          line_color=theme.SERIES["orange"], marker_size=5, name="Exportado",
                          hovertemplate="h%{x}: %{y:.4f} MW<extra></extra>", row=1, col=3)
        theme.style(fig_s, "Indicadores a lo largo de la corrida")
        fig_s.update_layout(showlegend=False)
        for c in (1, 2, 3):
            fig_s.update_xaxes(title="hora", gridcolor=theme.GRID, zerolinecolor=theme.BASELINE,
                               tickfont=dict(color=theme.INK, size=11), title_font=dict(color=theme.INK, size=11),
                               row=1, col=c)
            fig_s.update_yaxes(gridcolor=theme.GRID, zerolinecolor=theme.BASELINE,
                               tickfont=dict(color=theme.INK, size=11), row=1, col=c)
        for ann in fig_s.layout.annotations:
            ann.font.color = theme.INK
            ann.font.size = 12

        step = max(1, len(data) // 12)
        marks = {d["hour"]: str(d["hour"]) for d in data if d["hour"] % step == 0}

        def val(x, unit):
            return html.Span([f"{x}", html.Span(unit, className="unit")])

        return (val(f"{inst['losses']:.4f}", " MW"), val(f"{vmin:.3f}", " pu"),
                val(f"{vmax:.3f}", " pu"), val(f"{load_max:.1f}", " %"),
                val(f"{inst['auto']:.1f}", " %"), val(f"{inst['export']:.4f}", " MW"),
                elements, fig_v, fig_s, len(data) - 1, marks)

    # ---- sincronización de datos ----
    def _mensaje(fuente: str, r: dict) -> str:
        """Traduce el dict que devuelve el servicio de sync a una línea legible."""
        if not r.get("ok"):
            return f"⚠ {fuente}: {r.get('error', 'error desconocido')}"
        if "codigo" in r:
            estado = "ya estaba en caché" if r.get("cacheada") else "descargada"
            return f"✓ {fuente}: {r['codigo']} {estado}."
        if "registros" in r:
            extra = ""
            if r.get("descartados"):
                extra = f" ({r['descartados']} registros descartados por formato)"
            return f"✓ {fuente}: {r['registros']} horas guardadas{extra}."
        return f"✓ {fuente}: listo."

    @app.callback(
        Output("db-sync-status", "children"),
        Input("db-sync-simbench", "n_clicks"),
        Input("db-sync-nasa", "n_clicks"),
        Input("db-sync-cammesa", "n_clicks"),
        Input("db-purgar", "n_clicks"),
        State("db-region", "value"),
        State("db-lat", "value"), State("db-lon", "value"),
        State("db-nasa-desde", "value"), State("db-nasa-hasta", "value"),
        State("db-simbench-code", "value"),
        prevent_initial_call=True,
    )
    def sincronizar(_s, _n, _c, _p, region, lat, lon, desde, hasta, simbench_code):
        disp = ctx.triggered_id
        try:
            if disp == "db-sync-simbench":
                # Antes se llamaba sin argumento y bajaba siempre 1-LV-rural1,
                # sin importar qué red hubiera pedido el usuario.
                return _mensaje("SimBench", data_sync_service.sync_simbench(
                    str(_valor(simbench_code, "1-LV-rural1--0-no_sw")).strip()))
            if disp == "db-sync-nasa":
                return _mensaje("NASA POWER", data_sync_service.sync_nasa(
                    float(_valor(lat, -31.4)), float(_valor(lon, -60.5)),
                    str(_valor(desde, _RANGO_NASA[0])).strip(),
                    str(_valor(hasta, _RANGO_NASA[1])).strip(),
                ))
            if disp == "db-sync-cammesa":
                return _mensaje("CAMMESA", data_sync_service.sync_cammesa(
                    str(_valor(region, "LITORAL"))))
            if disp == "db-purgar":
                antes = simulation_service.sim_repo.purgar()
                mb = antes["bytes"] / (1024 * 1024)
                return (f"✓ Caché de resultados vaciada: {antes['instantes']} instantes y "
                        f"{antes['corridas']} corridas ({mb:.1f} MB). Volvé a correr la simulación.")
        except Exception as exc:  # noqa: BLE001
            return f"⚠ Error: {exc}"
        return ""
