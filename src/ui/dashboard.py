"""Dashboard: corre simulaciones y muestra resultados.

Pide la red al Servicio Red y los resultados al Servicio Simulación, y actualiza
los indicadores, el grafo y los gráficos. Incluye un panel para sincronizar los
datos externos (CAMMESA / NASA / SimBench) a mano. Callbacks propios del
Dashboard viven en este archivo.
"""
from __future__ import annotations

import dash_cytoscape as cyto
import plotly.graph_objects as go
from dash import Input, Output, State, ctx, dcc, html
from plotly.subplots import make_subplots

from app.data_sync_service import CAMMESA_REGIONES
from app.simulation_service import SimulationService
from domain import epocas as epocas_mod
from ui import theme
from ui.graph_view import STYLESHEET, net_to_elements
from ui.widgets import campo as _campo, error as _error, leyenda

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


def _dropdown(label, id_, options, value, searchable=False):
    """Desplegable de un campo del panel de control.

    Sin buscador por omisión: todos los desplegables de acá tienen a lo sumo
    ocho opciones, y el buscador que dcc.Dropdown trae de fábrica sólo agrega
    ruido. Se activa con searchable=True donde la lista pueda crecer.
    """
    return html.Div(
        [html.Label(label),
         dcc.Dropdown(id=id_, options=options, value=value, clearable=False,
                      searchable=searchable)],
        className="field", style={"minWidth": "150px"},
    )


def _aviso_irradiacion(r: dict) -> str:
    """Nota sobre la irradiación que se intentó bajar antes de la corrida.

    ``r`` es ``None`` cuando la corrida ni siquiera pidió datos reales (modo
    básico). El silencio es la señal de "todo bien": con NASA sólo se avisa
    cuando la serie se acaba de descargar o cuando no se pudo y el perfil
    quedó sintético.
    """
    if r is None:
        return " Perfil solar sintético (configuración solar avanzada sin marcar)."
    if r.get("cacheada"):
        return ""
    epoca = epocas_mod.etiqueta(r.get("epoca", ""))
    if r.get("ok"):
        anios, pedidos = r.get("anios", 0), r.get("anios_pedidos", 0)
        falta = "" if anios == pedidos else f", {pedidos - anios} sin datos"
        return (f" Irradiación NASA descargada para {epoca}: {r.get('registros', 0)} horas "
                f"de {anios} año(s){falta}.")
    return (f" Aviso: no se pudo descargar la irradiación de NASA para {epoca} "
            f"({r.get('error', 'error desconocido')}): el perfil solar es sintético.")


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
    return ("  Aviso: " + " y ".join(partes) + " sin conexión al nodo slack: quedan fuera de los "
            "indicadores y se muestran en gris en el grafo.")


# ---- figuras ------------------------------------------------------------
def _fig_tension(volt: dict, hora: int, vmin: float, vmax: float):
    """Perfil de tensión por nodo: una barra por bus (serie única, sin leyenda).

    El color marca el desvío respecto de 1 pu con los mismos umbrales que el
    grafo: sano, alerta por encima del 5 % y crítico por encima del 10 %.
    """
    fig = go.Figure()
    colores = [theme.CRITICAL if abs(v - 1) > 0.1 else theme.WARNING if abs(v - 1) > 0.05 else theme.SERIES["blue"]
               for v in volt.values()]
    fig.add_bar(x=[f"Bus {k}" for k in volt], y=list(volt.values()),
                marker_color=colores, marker_line_width=0,
                hovertemplate="%{x}: %{y:.3f} pu<extra></extra>")
    theme.style(fig, f"Perfil de tensión por nodo — hora {hora}")
    fig.update_yaxes(title="Tensión [pu]", range=[min(0.9, vmin - 0.02), max(1.1, vmax + 0.02)])
    for y in (0.95, 1.05):
        fig.add_hline(y=y, line_dash="dot", line_color=theme.CRITICAL, line_width=1,
                      annotation_text=f"{y:g} pu", annotation_font_size=10,
                      annotation_font_color=theme.INK)
    return fig


# Un panel por indicador (small multiples): cada uno con su propia escala, en
# vez de un doble eje que obliga a leer dos veces la misma curva.
# (clave en el store, título del panel, nombre de la serie, color, hover)
_PANELES = (
    ("losses", "Pérdidas [MW]", "Pérdidas", "blue", "h%{x}: %{y:.4f} MW<extra></extra>"),
    ("auto", "Autosuficiencia [%]", "Autosuf.", "aqua", "h%{x}: %{y:.1f} %<extra></extra>"),
    ("export", "Excedente exportado [MW]", "Exportado", "orange", "h%{x}: %{y:.4f} MW<extra></extra>"),
)


def _fig_series(data: list[dict]):
    """Los indicadores de la corrida hora a hora, un panel por indicador."""
    horas = [d["hour"] for d in data]
    fig = make_subplots(rows=1, cols=len(_PANELES), shared_xaxes=False,
                        subplot_titles=tuple(p[1] for p in _PANELES),
                        horizontal_spacing=0.08)
    for col, (clave, _titulo, nombre, color, hover) in enumerate(_PANELES, start=1):
        fig.add_scatter(x=horas, y=[d[clave] for d in data], mode="lines+markers",
                        line_color=theme.SERIES[color], marker_size=5, name=nombre,
                        hovertemplate=hover, row=1, col=col)
    # theme.style pisa todos los ejes, así que los retoques por panel van después.
    theme.style(fig, "Indicadores a lo largo de la corrida")
    fig.update_layout(showlegend=False)
    for col in range(1, len(_PANELES) + 1):
        fig.update_xaxes(title="hora", gridcolor=theme.GRID, zerolinecolor=theme.BASELINE,
                         tickfont=dict(color=theme.INK, size=11),
                         title_font=dict(color=theme.INK, size=11), row=1, col=col)
        fig.update_yaxes(gridcolor=theme.GRID, zerolinecolor=theme.BASELINE,
                         tickfont=dict(color=theme.INK, size=11), row=1, col=col)
    for ann in fig.layout.annotations:
        ann.font.color = theme.INK
        ann.font.size = 12
    return fig


def _kpi_valor(x, unidad):
    """Número grande del KPI con su unidad en tipografía chica."""
    return html.Span([f"{x}", html.Span(unidad, className="unit")])


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
                    html.Div(
                        [
                            _dropdown("Tipo de flujo", "db-mode",
                                      [{"label": "Flujo de carga (runpp)", "value": "pp"},
                                       {"label": "Flujo óptimo (runopp)", "value": "opp"}], "pp"),
                            _campo("Horas", "db-horas", 24,
                                   min=SimulationService.MIN_HORAS, max=SimulationService.MAX_HORAS),
                            html.Div(html.Button("Correr simulación", id="db-btn-run", n_clicks=0,
                                                 className="btn btn-primary"),
                                     className="field", style={"flex": "0 0 auto", "justifyContent": "flex-end"}),
                        ],
                        className="row",
                    ),
                    # ---- Configuración solar: básica (campana) o avanzada (NASA) ----
                    dcc.Checklist(
                        id="db-solar-avanzada",
                        options=[{"label": "Configuración solar avanzada", "value": "on"}],
                        value=[], className="check-inline",
                    ),
                    html.P("Sin marcar, el perfil solar es una campana diurna sintética —cero de "
                           "noche, pico al mediodía— igual en toda corrida. Alcanza para ver cómo "
                           "responde la red y no depende de ninguna descarga.",
                           id="db-solar-basico", className="card-sub"),
                    html.Div(
                        [
                            html.Div(
                                [_campo("Lat", "db-lat", -31.4),
                                 _campo("Lon", "db-lon", -60.5),
                                 _dropdown("Época del año", "db-epoca", epocas_mod.opciones(),
                                           epocas_mod.EPOCA_POR_DEFECTO)],
                                className="row",
                            ),
                            html.P(f"Con datos reales: al correr se baja de NASA POWER la irradiación de "
                                   f"los {epocas_mod.SEMIVENTANA_DIAS * 2 // 30} meses centrados en esa "
                                   f"época, de los últimos {epocas_mod.ANIOS_PROMEDIO} años, y se promedia "
                                   f"hora a hora para obtener el día típico. La primera descarga de cada "
                                   f"ubicación y época tarda unos minutos; después sale del caché. Si "
                                   f"falla, la corrida sigue con la campana sintética y se avisa.",
                                   className="card-sub", style={"marginTop": "10px"}),
                        ],
                        id="db-solar-campos", style={"display": "none"},
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
                            [leyenda(con_estado=True),
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
                    html.Summary("Sincronizar datos externos"),
                    html.Div(
                        [
                            html.P("Descargá series reales para reemplazar los perfiles sintéticos. "
                                   "Las series se guardan en hora local argentina.",
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
                                html.Button("Limpiar caché de resultados", id="db-purgar",
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
        return (html.Span(msg), {"display": "flex"})

    # ---- mostrar/ocultar la configuración solar avanzada ----
    @app.callback(
        Output("db-solar-campos", "style"),
        Output("db-solar-basico", "style"),
        Input("db-solar-avanzada", "value"),
    )
    def alternar_solar_avanzada(valor):
        """Los campos siguen en el DOM al ocultarse: la corrida los lee igual."""
        if valor:
            return {"display": "block"}, {"display": "none"}
        return {"display": "none"}, {}

    # ---- correr simulación ----
    @app.callback(
        Output("db-store", "data"),
        Output("db-status", "children"),
        Output("db-hora", "value"),
        Input("db-btn-run", "n_clicks"),
        State("db-mode", "value"), State("db-horas", "value"),
        State("db-lat", "value"), State("db-lon", "value"),
        State("db-epoca", "value"), State("db-solar-avanzada", "value"),
        prevent_initial_call=True,
    )
    def correr(_n, mode, horas, lat, lon, epoca, avanzada):
        try:
            avanzada = bool(avanzada)
            lat_f = float(_valor(lat, -31.4))
            lon_f = float(_valor(lon, -60.5))
            epoca = str(_valor(epoca, epocas_mod.EPOCA_POR_DEFECTO))
            # Sin configuración avanzada no se toca la red ni el caché: la
            # corrida usa la campana sintética. Con ella, la irradiación se baja
            # acá; si ya está cacheada no hay descarga, y si falla la corrida
            # sigue igual con el perfil sintético.
            irr = (data_sync_service.asegurar_irradiacion(lat_f, lon_f, epoca)
                   if avanzada else None)
            run = simulation_service.run_corrida(
                horas=_valor(horas, 24), mode=mode or "pp",
                nombre_red=network_service.nombre_guardada(network_service.red_id) or "actual",
                lat=lat_f, lon=lon_f, epoca=epoca, usar_nasa=avanzada,
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

            msg = f"Corrida completa: {len(data)} instantes simulados (run {run['run_id'][:8]}…)."
            msg += _aviso_irradiacion(irr)
            msg += _aviso_sin_solucion(resultados)
            # El slider vuelve a la hora 0: si no, una corrida más corta que la
            # anterior dejaba el cursor en una hora que ya no existe.
            return data, msg, 0
        except Exception as exc:  # noqa: BLE001
            return None, _error(f"Error: {exc}"), 0

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
        fig_v = _fig_tension(volt, h, vmin, vmax)
        fig_s = _fig_series(data)

        step = max(1, len(data) // 12)
        marks = {d["hour"]: str(d["hour"]) for d in data if d["hour"] % step == 0}

        return (_kpi_valor(f"{inst['losses']:.4f}", " MW"), _kpi_valor(f"{vmin:.3f}", " pu"),
                _kpi_valor(f"{vmax:.3f}", " pu"), _kpi_valor(f"{load_max:.1f}", " %"),
                _kpi_valor(f"{inst['auto']:.1f}", " %"), _kpi_valor(f"{inst['export']:.4f}", " MW"),
                elements, fig_v, fig_s, len(data) - 1, marks)

    # ---- sincronización de datos ----
    def _mensaje(fuente: str, r: dict) -> str:
        """Traduce el dict que devuelve el servicio de sync a una línea legible."""
        if not r.get("ok"):
            return _error(f"{fuente}: {r.get('error', 'error desconocido')}")
        if "codigo" in r:
            estado = "ya estaba en caché" if r.get("cacheada") else "descargada"
            return f"{fuente}: {r['codigo']} {estado}."
        if "registros" in r:
            extra = ""
            if r.get("descartados"):
                extra = f" ({r['descartados']} registros descartados por formato)"
            return f"{fuente}: {r['registros']} horas guardadas{extra}."
        return f"{fuente}: listo."

    @app.callback(
        Output("db-sync-status", "children"),
        Input("db-sync-simbench", "n_clicks"),
        Input("db-sync-cammesa", "n_clicks"),
        Input("db-purgar", "n_clicks"),
        State("db-region", "value"),
        State("db-simbench-code", "value"),
        prevent_initial_call=True,
    )
    def sincronizar(_s, _c, _p, region, simbench_code):
        disp = ctx.triggered_id
        try:
            if disp == "db-sync-simbench":
                # Antes se llamaba sin argumento y bajaba siempre 1-LV-rural1,
                # sin importar qué red hubiera pedido el usuario.
                return _mensaje("SimBench", data_sync_service.sync_simbench(
                    str(_valor(simbench_code, "1-LV-rural1--0-no_sw")).strip()))
            if disp == "db-sync-cammesa":
                return _mensaje("CAMMESA", data_sync_service.sync_cammesa(
                    str(_valor(region, "LITORAL"))))
            if disp == "db-purgar":
                antes = simulation_service.sim_repo.purgar()
                mb = antes["bytes"] / (1024 * 1024)
                return (f"Caché de resultados vaciada: {antes['instantes']} instantes y "
                        f"{antes['corridas']} corridas ({mb:.1f} MB). Volvé a correr la simulación.")
        except Exception as exc:  # noqa: BLE001
            return _error(f"Error: {exc}")
        return ""
