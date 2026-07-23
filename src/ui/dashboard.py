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

from ui.graph_view import STYLESHEET, net_to_elements


def _kpi(titulo, id_, unidad=""):
    return html.Div(
        [html.Div(titulo, style={"fontSize": "12px", "color": "#555"}),
         html.Div(["—", html.Span(unidad, style={"fontSize": "12px"})], id=id_,
                  style={"fontSize": "22px", "fontWeight": "bold"})],
        style={"flex": "1", "minWidth": "120px", "padding": "10px", "background": "#f5f5f5",
               "borderRadius": "6px", "textAlign": "center", "margin": "4px"},
    )


def _campo(label, id_, value, tipo="number", **kw):
    return html.Div(
        [html.Label(label, style={"fontSize": "12px", "display": "block"}),
         dcc.Input(id=id_, type=tipo, value=value, style={"width": "100%"}, **kw)],
        style={"flex": "1", "minWidth": "90px", "margin": "2px"},
    )


def layout():
    return html.Div(
        [
            html.H3("Dashboard de simulación"),
            html.Div(
                [
                    html.Div([html.Label("Tipo de flujo", style={"fontSize": "12px"}),
                              dcc.Dropdown(id="db-mode", options=[{"label": "Flujo de carga (runpp)", "value": "pp"},
                                                                  {"label": "Flujo óptimo (runopp)", "value": "opp"}],
                                           value="pp", clearable=False)],
                             style={"flex": "1", "minWidth": "180px", "margin": "2px"}),
                    _campo("Horas", "db-horas", 24, min=1, max=168),
                    html.Div([html.Label("Tipo de carga", style={"fontSize": "12px"}),
                              dcc.Dropdown(id="db-tipo", options=[{"label": t.capitalize(), "value": t}
                                                                  for t in ("residencial", "comercial", "industrial")],
                                           value="residencial", clearable=False)],
                             style={"flex": "1", "minWidth": "140px", "margin": "2px"}),
                    _campo("Región", "db-region", "LITORAL", tipo="text"),
                    _campo("Lat", "db-lat", -31.4),
                    _campo("Lon", "db-lon", -60.5),
                    _campo("SoC inicial %", "db-soc", 50),
                    html.Button("Correr simulación", id="db-btn-run", n_clicks=0,
                                style={"alignSelf": "flex-end", "margin": "2px", "height": "36px"}),
                ],
                style={"display": "flex", "flexWrap": "wrap", "alignItems": "flex-end", "gap": "4px"},
            ),
            html.Div(id="db-status", style={"margin": "6px 0", "fontWeight": "bold", "minHeight": "18px"}),
            html.Div(
                [
                    _kpi("Pérdidas totales", "db-kpi-losses", " MW"),
                    _kpi("Tensión mín.", "db-kpi-vmin", " pu"),
                    _kpi("Tensión máx.", "db-kpi-vmax", " pu"),
                    _kpi("Cargabilidad máx.", "db-kpi-load", " %"),
                    _kpi("Autosuficiencia", "db-kpi-auto", " %"),
                    _kpi("Curtailment solar", "db-kpi-curt", " MW"),
                ],
                style={"display": "flex", "flexWrap": "wrap"},
            ),
            html.Div([html.Label("Hora de la corrida", style={"fontSize": "12px"}),
                      dcc.Slider(id="db-hora", min=0, max=0, step=1, value=0, marks={0: "0"})],
                     style={"margin": "10px 4px"}),
            html.Div(
                [
                    html.Div(
                        cyto.Cytoscape(id="db-graph", layout={"name": "cose", "animate": False},
                                       style={"width": "100%", "height": "48vh"},
                                       stylesheet=STYLESHEET, elements=[]),
                        style={"flex": "1", "minWidth": "340px"},
                    ),
                    html.Div(dcc.Graph(id="db-fig-voltage", style={"height": "48vh"}),
                             style={"flex": "1", "minWidth": "340px"}),
                ],
                style={"display": "flex", "flexWrap": "wrap", "gap": "8px"},
            ),
            dcc.Graph(id="db-fig-series", style={"height": "34vh"}),
            # ---- panel de sincronización de datos ----
            html.Details(
                [
                    html.Summary("Sincronizar datos externos"),
                    html.Div(
                        [
                            html.Button("SimBench", id="db-sync-simbench", n_clicks=0, style={"margin": "2px"}),
                            html.Button("NASA POWER (irradiación)", id="db-sync-nasa", n_clicks=0, style={"margin": "2px"}),
                            html.Button("CAMMESA (demanda)", id="db-sync-cammesa", n_clicks=0, style={"margin": "2px"}),
                        ]
                    ),
                    html.Div(id="db-sync-status", style={"fontSize": "13px", "marginTop": "6px"}),
                ]
            ),
            dcc.Store(id="db-store"),
        ],
        style={"padding": "8px"},
    )


def _fig_vacia(titulo):
    fig = go.Figure()
    fig.update_layout(title=titulo, margin=dict(l=40, r=10, t=40, b=30))
    return fig


def register_callbacks(app, services):
    network_service = services["network_service"]
    simulation_service = services["simulation_service"]
    data_sync_service = services["data_sync_service"]

    # ---- correr simulación ----
    @app.callback(
        Output("db-store", "data"),
        Output("db-status", "children"),
        Input("db-btn-run", "n_clicks"),
        State("db-mode", "value"), State("db-horas", "value"), State("db-tipo", "value"),
        State("db-region", "value"), State("db-lat", "value"), State("db-lon", "value"),
        State("db-soc", "value"),
        prevent_initial_call=True,
    )
    def correr(_n, mode, horas, tipo, region, lat, lon, soc):
        try:
            run = simulation_service.run_corrida(
                horas=int(horas or 24), mode=mode or "pp",
                nombre_red=network_service.net_repo.nombre_de(network_service.red_id) or "actual",
                tipo_carga=tipo or "residencial", region=region or "LITORAL",
                lat=float(lat or -31.4), lon=float(lon or -60.5), soc_inicial=float(soc or 50),
            )
            data = [{
                "hour": r.hour_index,
                "voltage": {int(k): v for k, v in r.voltage_profile.items()},
                "loading": {int(k): v for k, v in r.line_loading_pct.items()},
                "losses": r.total_losses_mw,
                "auto": r.autosufficiency_pct,
                "curt": r.curtailment_solar_mw,
            } for r in run["resultados"]]
            return data, f"Corrida completa: {len(data)} instantes (run {run['run_id'][:8]}…)."
        except Exception as exc:  # noqa: BLE001
            return None, f"⚠ Error: {exc}"

    # ---- actualizar vista según store + hora ----
    @app.callback(
        Output("db-kpi-losses", "children"), Output("db-kpi-vmin", "children"),
        Output("db-kpi-vmax", "children"), Output("db-kpi-load", "children"),
        Output("db-kpi-auto", "children"), Output("db-kpi-curt", "children"),
        Output("db-graph", "elements"), Output("db-fig-voltage", "figure"),
        Output("db-fig-series", "figure"), Output("db-hora", "max"), Output("db-hora", "marks"),
        Input("db-store", "data"), Input("db-hora", "value"),
    )
    def actualizar(data, hora):
        net = network_service.get_network().net
        if not data:
            elements = net_to_elements(net)
            vacio = "—"
            return (vacio, vacio, vacio, vacio, vacio, vacio, elements,
                    _fig_vacia("Perfil de tensión"), _fig_vacia("Indicadores por hora"), 0, {0: "0"})

        h = min(int(hora or 0), len(data) - 1)
        inst = data[h]
        volt = {int(k): v for k, v in inst["voltage"].items()}
        load = {int(k): v for k, v in inst["loading"].items()}
        vmin = min(volt.values()) if volt else 0.0
        vmax = max(volt.values()) if volt else 0.0
        load_max = max(load.values()) if load else 0.0

        elements = net_to_elements(net, voltage_profile=volt, line_loading=load)

        fig_v = go.Figure()
        fig_v.add_bar(x=[f"Bus {k}" for k in volt], y=list(volt.values()), marker_color="#1565c0")
        fig_v.add_hline(y=1.05, line_dash="dot", line_color="red")
        fig_v.add_hline(y=0.95, line_dash="dot", line_color="red")
        fig_v.update_layout(title=f"Perfil de tensión — hora {h}", yaxis_title="pu",
                            margin=dict(l=40, r=10, t=40, b=30))

        horas = [d["hour"] for d in data]
        fig_s = go.Figure()
        fig_s.add_scatter(x=horas, y=[d["losses"] for d in data], name="Pérdidas [MW]", mode="lines+markers")
        fig_s.add_scatter(x=horas, y=[d["auto"] for d in data], name="Autosuf. [%]", yaxis="y2", mode="lines+markers")
        fig_s.add_scatter(x=horas, y=[d["curt"] for d in data], name="Curtailment [MW]", mode="lines+markers")
        fig_s.update_layout(
            title="Indicadores por hora", margin=dict(l=40, r=40, t=40, b=30),
            yaxis=dict(title="MW"), yaxis2=dict(title="%", overlaying="y", side="right"),
            legend=dict(orientation="h"),
        )

        marks = {d["hour"]: str(d["hour"]) for d in data if d["hour"] % max(1, len(data) // 12) == 0}
        return (f"{inst['losses']:.4f} MW", f"{vmin:.3f} pu", f"{vmax:.3f} pu",
                f"{load_max:.1f} %", f"{inst['auto']:.1f} %", f"{inst['curt']:.4f} MW",
                elements, fig_v, fig_s, len(data) - 1, marks)

    # ---- sincronización de datos ----
    @app.callback(
        Output("db-sync-status", "children"),
        Input("db-sync-simbench", "n_clicks"),
        Input("db-sync-nasa", "n_clicks"),
        Input("db-sync-cammesa", "n_clicks"),
        State("db-region", "value"),
        State("db-lat", "value"), State("db-lon", "value"),
        prevent_initial_call=True,
    )
    def sincronizar(_s, _n, _c, region, lat, lon):
        disp = ctx.triggered_id
        if disp == "db-sync-simbench":
            r = data_sync_service.sync_simbench()
            return f"SimBench: {r}"
        if disp == "db-sync-nasa":
            r = data_sync_service.sync_nasa(float(lat or -31.4), float(lon or -60.5), "20230101", "20230107")
            return f"NASA POWER: {r}"
        if disp == "db-sync-cammesa":
            r = data_sync_service.sync_cammesa(region or "LITORAL")
            return f"CAMMESA: {r}"
        return ""
