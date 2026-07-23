"""Editor de red: modo gráfico (formularios) y modo código Python.

Muestra la red en vivo mientras el usuario la edita. Envía los cambios al
Servicio Red y recibe el estado actualizado para mostrarlo. Los callbacks
propios del Editor viven en este archivo.
"""
from __future__ import annotations

import dash_cytoscape as cyto
from dash import Input, Output, State, ctx, dcc, html

from domain.network_model import Battery, Bus, ExternalGrid, Line, Load, SolarPanel
from repositories.json_net_repository import NombreDuplicadoError
from ui.graph_view import LEGEND_NODES, LEGEND_STATUS, STYLESHEET, net_to_elements, pixel_to_geo


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _campo(label, id_, value="", tipo="number", **kw):
    return html.Div(
        [html.Label(label), dcc.Input(id=id_, type=tipo, value=value, **kw)],
        className="field",
    )


def _fila(children):
    return html.Div(children, className="row", style={"marginBottom": "10px"})


def _acc(titulo, children, open=False):
    return html.Details(
        [html.Summary(titulo), html.Div(children, className="acc-body")],
        className="acc", open=open,
    )


def _btn(label, id_, primary=False):
    cls = "btn btn-primary" if primary else "btn"
    return html.Button(label, id=id_, n_clicks=0, className=cls)


def _legend():
    items = [html.Div([html.Span(className="dot", style={"background": c}), t], className="item")
             for c, t in LEGEND_NODES]
    return html.Div(items, className="legend")


def layout():
    return html.Div(
        [
            # ---- Panel de edición ----
            html.Div(
                [
                    html.Div(
                        [
                            html.H3("Editor de red"),
                            html.P("Cargá, editá y guardá la microgrid. El grafo se actualiza en vivo.",
                                   className="card-sub"),
                            _acc("📥  Cargar red", [
                                _fila([_btn("Red de ejemplo", "ed-btn-ejemplo")]),
                                _fila([
                                    _campo("Código SimBench", "ed-simbench-code", "1-LV-rural1--0-no_sw", tipo="text"),
                                    _btn("Cargar", "ed-btn-simbench"),
                                ]),
                                _fila([
                                    html.Div(dcc.Dropdown(id="ed-guardadas", placeholder="Red guardada…",
                                                          className="dash-dropdown"),
                                             className="field", style={"minWidth": "180px"}),
                                    _btn("Abrir", "ed-btn-guardada"),
                                ]),
                            ], open=True),
                            _acc("✏️  Agregar elementos (gráfico)", [
                                _fila([
                                    _campo("Bus vn_kv", "ed-bus-vn", 0.4),
                                    _campo("Nombre", "ed-bus-name", "", tipo="text"),
                                    _btn("+ Bus", "ed-btn-bus"),
                                ]),
                                _fila([
                                    _campo("Línea desde", "ed-line-from", 0),
                                    _campo("hasta", "ed-line-to", 1),
                                    _campo("largo km", "ed-line-len", 0.1),
                                    _btn("+ Línea", "ed-btn-line"),
                                ]),
                                _fila([
                                    _campo("Carga bus", "ed-load-bus", 1),
                                    _campo("p_mw", "ed-load-p", 0.05),
                                    _campo("q_mvar", "ed-load-q", 0.01),
                                    _btn("+ Carga", "ed-btn-load"),
                                ]),
                                _fila([
                                    _campo("Solar bus", "ed-sgen-bus", 1),
                                    _campo("p_mw", "ed-sgen-p", 0.03),
                                    _btn("+ Solar", "ed-btn-sgen"),
                                ]),
                                _fila([
                                    _campo("Batería bus", "ed-bat-bus", 1),
                                    _campo("p_mw", "ed-bat-p", 0.02),
                                    _campo("max_e_mwh", "ed-bat-maxe", 0.05),
                                    _campo("soc %", "ed-bat-soc", 50),
                                    _btn("+ Batería", "ed-btn-bat"),
                                ]),
                                _fila([
                                    _campo("Red externa bus", "ed-ext-bus", 0),
                                    _btn("+ Red externa", "ed-btn-ext"),
                                ]),
                                _fila([
                                    _campo("Quitar tipo", "ed-rm-type", "line", tipo="text"),
                                    _campo("índice", "ed-rm-index", 0),
                                    _btn("Quitar", "ed-btn-rm"),
                                ]),
                            ]),
                            _acc("🐍  Editor de código Python", [
                                html.P("Muestra la red actual: editá los parámetros y ejecutá. También podés "
                                       "agregar elementos con model.add_… (Bus, Line, Load, SolarPanel, Battery, "
                                       "ExternalGrid, Transformer).",
                                       className="card-sub"),
                                dcc.Textarea(id="ed-code", className="code", value="",
                                             style={"height": "260px"}),
                                html.Div([
                                    _btn("Ejecutar código", "ed-btn-code", primary=True),
                                    _btn("Regenerar desde la red", "ed-btn-code-refresh"),
                                ], className="row", style={"marginTop": "8px"}),
                            ]),
                            _acc("💾  Guardar red", [
                                _fila([
                                    _campo("Nombre", "ed-save-name", "Mi red", tipo="text"),
                                    _btn("Guardar nueva", "ed-btn-save", primary=True),
                                    _btn("Sobrescribir", "ed-btn-save-changes"),
                                ]),
                            ]),
                            html.Div(id="ed-status", className="status", style={"marginTop": "10px"}),
                            html.Div(html.Pre(id="ed-summary", className="summary"),
                                     style={"marginTop": "10px"}),
                        ],
                        className="card",
                    ),
                ],
            ),
            # ---- Grafo ----
            html.Div(
                html.Div(
                    [
                        _legend(),
                        html.Div("Arrastrá los buses para acomodarlos: la posición queda guardada en el código.",
                                 className="card-sub", style={"padding": "0 14px"}),
                        cyto.Cytoscape(
                            id="ed-graph",
                            layout={"name": "preset", "fit": True, "padding": 40},
                            style={"width": "100%", "height": "70vh"},
                            stylesheet=STYLESHEET,
                            autoRefreshLayout=False,
                            elements=[],
                        ),
                    ],
                    className="graph-frame",
                ),
            ),
        ],
        className="grid-2",
    )


def _resumen(net) -> str:
    return (
        f"Buses: {len(net.bus)}   Líneas: {len(net.line)}   Trafos: {len(net.trafo)}\n"
        f"Cargas: {len(net.load)}   Solar: {len(net.sgen)}   Baterías: {len(net.storage)}   "
        f"Red externa: {len(net.ext_grid)}"
    )


def register_callbacks(app, services):
    network_service = services["network_service"]

    # Al soltar un bus tras arrastrarlo, cytoscape emite 'dragfree' (no 'tap').
    # Este hook reenvía ese evento como 'tap' para que el callback de posición
    # (Input ed-graph.tapNode) se dispare y guarde la nueva posición en el código.
    app.clientside_callback(
        """
        function(elements) {
            setTimeout(function() {
                var d = document.getElementById('ed-graph');
                var cy = d && d._cyreg && d._cyreg.cy;
                if (cy && !cy._dragHooked) {
                    cy._dragHooked = true;
                    cy.on('dragfree', 'node', function(e) { e.target.emit('tap'); });
                }
            }, 120);
            return window.dash_clientside.no_update;
        }
        """,
        Output("ed-graph", "autolock"),
        Input("ed-graph", "elements"),
    )

    def _opciones_guardadas():
        return [{"label": r["nombre"], "value": r["id"]} for r in network_service.listar_guardadas()]

    @app.callback(
        Output("ed-graph", "elements"),
        Output("ed-summary", "children"),
        Output("ed-status", "children"),
        Output("ed-guardadas", "options"),
        Output("ed-code", "value"),
        Input("ed-btn-ejemplo", "n_clicks"),
        Input("ed-btn-simbench", "n_clicks"),
        Input("ed-btn-guardada", "n_clicks"),
        Input("ed-btn-bus", "n_clicks"),
        Input("ed-btn-line", "n_clicks"),
        Input("ed-btn-load", "n_clicks"),
        Input("ed-btn-sgen", "n_clicks"),
        Input("ed-btn-bat", "n_clicks"),
        Input("ed-btn-ext", "n_clicks"),
        Input("ed-btn-rm", "n_clicks"),
        Input("ed-btn-code", "n_clicks"),
        Input("ed-btn-code-refresh", "n_clicks"),
        Input("ed-btn-save", "n_clicks"),
        Input("ed-btn-save-changes", "n_clicks"),
        Input("ed-graph", "tapNode"),
        State("ed-simbench-code", "value"),
        State("ed-guardadas", "value"),
        State("ed-bus-vn", "value"), State("ed-bus-name", "value"),
        State("ed-line-from", "value"), State("ed-line-to", "value"), State("ed-line-len", "value"),
        State("ed-load-bus", "value"), State("ed-load-p", "value"), State("ed-load-q", "value"),
        State("ed-sgen-bus", "value"), State("ed-sgen-p", "value"),
        State("ed-bat-bus", "value"), State("ed-bat-p", "value"), State("ed-bat-maxe", "value"), State("ed-bat-soc", "value"),
        State("ed-ext-bus", "value"),
        State("ed-rm-type", "value"), State("ed-rm-index", "value"),
        State("ed-code", "value"),
        State("ed-save-name", "value"),
    )
    def actualizar(_e, _sb, _g, _bus, _line, _load, _sgen, _bat, _ext, _rm, _code, _coderef, _save, _savech,
                   tap_node, simbench_code, guardada_id,
                   bus_vn, bus_name, line_from, line_to, line_len,
                   load_bus, load_p, load_q, sgen_bus, sgen_p,
                   bat_bus, bat_p, bat_maxe, bat_soc, ext_bus,
                   rm_type, rm_index, code_text, save_name):
        disparador = ctx.triggered_id
        status = ""
        try:
            if disparador == "ed-btn-ejemplo":
                network_service.set_network(network_service._build_sample_network())
                status = "Red de ejemplo cargada."
            elif disparador == "ed-btn-simbench":
                network_service.cargar_desde_simbench(simbench_code or "1-LV-rural1--0-no_sw")
                status = f"Red SimBench '{simbench_code}' cargada."
            elif disparador == "ed-btn-guardada":
                if not guardada_id:
                    status = "Elegí una red guardada primero."
                else:
                    network_service.cargar_guardada(guardada_id)
                    status = "Red guardada cargada."
            elif disparador == "ed-btn-bus":
                i = network_service.agregar(Bus(vn_kv=_num(bus_vn, 0.4), name=bus_name or None))
                status = f"Bus {i} agregado."
            elif disparador == "ed-btn-line":
                i = network_service.agregar(Line(from_bus=_int(line_from), to_bus=_int(line_to), length_km=_num(line_len, 0.1)))
                status = f"Línea {i} agregada."
            elif disparador == "ed-btn-load":
                i = network_service.agregar(Load(bus=_int(load_bus), p_mw=_num(load_p), q_mvar=_num(load_q)))
                status = f"Carga {i} agregada."
            elif disparador == "ed-btn-sgen":
                i = network_service.agregar(SolarPanel(bus=_int(sgen_bus), p_mw=_num(sgen_p)))
                status = f"Panel solar {i} agregado."
            elif disparador == "ed-btn-bat":
                i = network_service.agregar(Battery(bus=_int(bat_bus), p_mw=_num(bat_p), max_e_mwh=_num(bat_maxe, 0.05), soc_percent=_num(bat_soc, 50)))
                status = f"Batería {i} agregada."
            elif disparador == "ed-btn-ext":
                i = network_service.agregar(ExternalGrid(bus=_int(ext_bus)))
                status = f"Red externa {i} agregada."
            elif disparador == "ed-btn-rm":
                network_service.eliminar((rm_type or "line").strip(), _int(rm_index))
                status = f"Elemento {rm_type} {rm_index} eliminado."
            elif disparador == "ed-btn-code":
                network_service.aplicar_codigo(code_text or "")
                status = "Código ejecutado."
            elif disparador == "ed-btn-code-refresh":
                status = "Código regenerado desde la red actual."
            elif disparador == "ed-graph" and tap_node:
                nid = (tap_node.get("data") or {}).get("id", "")
                pos = tap_node.get("position") or {}
                if nid.startswith("b") and nid[1:].isdigit() and "x" in pos:
                    bus_idx = int(nid[1:])
                    gx, gy = pixel_to_geo(pos["x"], pos["y"])
                    network_service.get_network().set_bus_position(bus_idx, gx, gy)
                    status = f"Posición del bus {bus_idx} guardada ({gx}, {gy})."
            elif disparador == "ed-btn-save":
                rid = network_service.guardar((save_name or "Mi red").strip())
                status = f"Red guardada (id {rid[:8]}…)."
            elif disparador == "ed-btn-save-changes":
                network_service.guardar_cambios()
                status = "Cambios guardados sobre la red actual."
        except NombreDuplicadoError as exc:
            status = f"⚠ {exc} — elegí otro nombre."
        except Exception as exc:  # noqa: BLE001
            status = f"⚠ Error: {exc}"

        modelo = network_service.get_network()
        modelo.ensure_positions()
        net = modelo.net
        return (net_to_elements(net, editable=True), _resumen(net), status,
                _opciones_guardadas(), network_service.generar_codigo())
