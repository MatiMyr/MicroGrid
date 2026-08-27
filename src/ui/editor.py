"""Editor de red: modo gráfico (formularios) y modo código Python.

Muestra la red en vivo mientras el usuario la edita. Envía los cambios al
Servicio Red y recibe el estado actualizado para mostrarlo. Los callbacks
propios del Editor viven en este archivo.
"""
from __future__ import annotations

from typing import Any, NamedTuple

import dash_cytoscape as cyto
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from domain.entities import TIPOS_CARGA
from domain.network_model import Battery, Bus, ExternalGrid, Line, Load, SolarPanel
from repositories.json_net_repository import NombreDuplicadoError
from ui.graph_view import STYLESHEET, geo_desde_pixel, net_to_elements
from ui.widgets import campo as _campo, leyenda


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


# ---- panel de detalle por bus (estilo mapa) ----------------------------
# Campos numéricos editables por tipo de elemento conectado.
_DET_CAMPOS = {
    "load": ["p_mw", "q_mvar", "scaling"],
    "sgen": ["p_mw", "q_mvar", "scaling"],
    "storage": ["p_mw", "q_mvar", "max_e_mwh", "soc_percent", "scaling"],
    "ext_grid": ["vm_pu", "va_degree"],
}
_DET_ETIQ = {"load": ("Cargas", "🏠"), "sgen": ("Solar", "☀"),
             "storage": ("Baterías", "🔋"), "ext_grid": ("Red externa", "🔌")}


def _dfield(label, id_dict, value, tipo="number"):
    return html.Div([html.Label(label), dcc.Input(id=id_dict, type=tipo, value=value)],
                    className="field")


def _dselect(label, id_dict, value, opciones):
    """Campo desplegable del panel de detalle (misma firma de State que _dfield).

    Sin buscador: son listas de tres o cuatro opciones fijas.
    """
    return html.Div(
        [html.Label(label),
         dcc.Dropdown(id=id_dict, value=value, clearable=False, searchable=False,
                      options=[{"label": o.capitalize(), "value": o} for o in opciones])],
        className="field", style={"minWidth": "140px"},
    )


def _detail_panel():
    return html.Div(
        [
            html.Div(
                [html.Button("← Volver", id="edd-back", className="btn btn-sm"),
                 html.Button("🗑 Borrar bus", id="edd-delbus", className="btn btn-sm",
                             style={"color": "var(--critical)", "borderColor": "var(--critical)"})],
                className="row", style={"justifyContent": "space-between"},
            ),
            html.H3(id="edd-title", style={"marginTop": "10px"}),
            html.Div(id="edd-body"),
            html.Div(html.Button("Aplicar cambios", id="edd-apply", className="btn btn-primary"),
                     style={"marginTop": "14px"}),
            html.Div(id="edd-status", className="status", style={"marginTop": "10px"}),
        ],
        id="ed-detail-panel", style={"display": "none"},
    )


def _detail_body(det):
    bidx = det["idx"]
    hijos = [
        html.Div("Bus", className="section-title"),
        _fila([
            _dfield("Nombre", {"role": "detf", "kind": "bus", "idx": bidx, "field": "name"}, det["name"], "text"),
            _dfield("vn_kv", {"role": "detf", "kind": "bus", "idx": bidx, "field": "vn_kv"}, det["vn_kv"]),
        ]),
        _fila([
            _dfield("Pos X", {"role": "detf", "kind": "pos", "idx": bidx, "field": "x"}, det["x"]),
            _dfield("Pos Y", {"role": "detf", "kind": "pos", "idx": bidx, "field": "y"}, det["y"]),
        ]),
    ]
    for kind, (titulo, emoji) in _DET_ETIQ.items():
        hijos.append(html.Div(
            [html.Span(f"{emoji}  {titulo}", className="section-title", style={"margin": 0}),
             html.Button("＋ Agregar", id={"role": "detadd", "kind": kind}, className="btn btn-sm")],
            className="row", style={"justifyContent": "space-between", "marginTop": "12px"},
        ))
        if not det[kind]:
            hijos.append(html.Div("Sin elementos.", className="card-sub"))
        for el in det[kind]:
            campos = [_dfield("Nombre", {"role": "detf", "kind": kind, "idx": el["idx"], "field": "name"},
                              el.get("name", ""), "text")]
            for f in _DET_CAMPOS[kind]:
                campos.append(_dfield(f, {"role": "detf", "kind": kind, "idx": el["idx"], "field": f},
                                      el.get(f, 0.0)))
            if kind == "load":
                # Curva horaria de esta carga: es un atributo del elemento, así
                # que una misma red puede mezclar viviendas, comercios e
                # industria (p. ej. para mapear un barrio).
                campos.append(_dselect(
                    "tipo",
                    {"role": "detf", "kind": "load", "idx": el["idx"], "field": "perfil_tipo"},
                    el.get("perfil_tipo", TIPOS_CARGA[0]), TIPOS_CARGA))
            campos.append(html.Div(
                html.Button("🗑", id={"role": "detdel", "kind": kind, "idx": el["idx"]},
                            className="btn btn-sm", style={"color": "var(--critical)"}),
                className="field", style={"flex": "0 0 auto", "justifyContent": "flex-end"}))
            hijos.append(html.Div(campos, className="row",
                                  style={"borderLeft": "2px solid var(--accent)", "paddingLeft": "8px",
                                         "marginBottom": "8px"}))
    return hijos


def layout():
    return html.Div(
        [
            # ---- Panel de edición ----
            html.Div(
                [
                    html.Div(
                        [
                          html.Div(id="ed-main-panel", children=[
                            html.H3("Editor de red"),
                            html.P("Cargá, editá y guardá la microgrid. Tocá un bus en el grafo para ver y editar sus datos.",
                                   className="card-sub"),
                            _acc("📥  Cargar red", [
                                _fila([_btn("Red de ejemplo", "ed-btn-ejemplo")]),
                                _fila([
                                    _campo("Código SimBench", "ed-simbench-code", "1-LV-rural1--0-no_sw", tipo="text"),
                                    _btn("Cargar", "ed-btn-simbench"),
                                ]),
                                _fila([
                                    html.Div(dcc.Dropdown(id="ed-guardadas", placeholder="Red guardada…",
                                                          searchable=True),
                                             className="field", style={"minWidth": "180px"}),
                                    _btn("Abrir", "ed-btn-guardada"),
                                    html.Button("🗑 Borrar", id="ed-btn-borrar", n_clicks=0,
                                                className="btn",
                                                style={"color": "var(--critical)",
                                                       "borderColor": "var(--critical)"}),
                                ]),
                                dcc.ConfirmDialog(id="ed-confirm-borrar"),
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
                          ]),
                          _detail_panel(),
                        ],
                        className="card",
                    ),
                ],
            ),
            # ---- Grafo ----
            html.Div(
                html.Div(
                    [
                        leyenda(),
                        cyto.Cytoscape(
                            id="ed-graph",
                            className="cyto-grid",
                            layout={"name": "preset", "fit": True, "padding": 40},
                            style={"width": "100%", "height": "70vh"},
                            stylesheet=STYLESHEET,
                            autoRefreshLayout=False,
                            userZoomingEnabled=True, userPanningEnabled=True,
                            minZoom=0.1, maxZoom=12, wheelSensitivity=0.2,
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


# ---- acciones del panel principal ---------------------------------------
class _Form(NamedTuple):
    """Valores del formulario del panel principal (los ``State`` del callback)."""

    simbench_code: Any
    guardada_id: Any
    bus_vn: Any
    bus_name: Any
    line_from: Any
    line_to: Any
    line_len: Any
    load_bus: Any
    load_p: Any
    load_q: Any
    sgen_bus: Any
    sgen_p: Any
    bat_bus: Any
    bat_p: Any
    bat_maxe: Any
    bat_soc: Any
    ext_bus: Any
    rm_type: Any
    rm_index: Any
    code_text: Any
    save_name: Any


# Cada acción recibe el Servicio Red y los valores del formulario, y devuelve el
# texto de estado. Lanzar es válido: el callback traduce la excepción a un aviso.
def _cargar_ejemplo(ns, v):
    ns.cargar_ejemplo()
    return "Red de ejemplo cargada."


def _cargar_simbench(ns, v):
    ns.cargar_desde_simbench(v.simbench_code or "1-LV-rural1--0-no_sw")
    return f"Red SimBench '{v.simbench_code}' cargada."


def _cargar_guardada(ns, v):
    if not v.guardada_id:
        return "Elegí una red guardada primero."
    ns.cargar_guardada(v.guardada_id)
    return "Red guardada cargada."


def _agregar_bus(ns, v):
    idx = ns.agregar(Bus(vn_kv=_num(v.bus_vn, 0.4), name=v.bus_name or None))
    return f"Bus {idx} agregado."


def _agregar_linea(ns, v):
    idx = ns.agregar(Line(from_bus=_int(v.line_from), to_bus=_int(v.line_to),
                          length_km=_num(v.line_len, 0.1)))
    return f"Línea {idx} agregada."


def _agregar_carga(ns, v):
    idx = ns.agregar(Load(bus=_int(v.load_bus), p_mw=_num(v.load_p), q_mvar=_num(v.load_q)))
    return f"Carga {idx} agregada."


def _agregar_solar(ns, v):
    idx = ns.agregar(SolarPanel(bus=_int(v.sgen_bus), p_mw=_num(v.sgen_p)))
    return f"Panel solar {idx} agregado."


def _agregar_bateria(ns, v):
    idx = ns.agregar(Battery(bus=_int(v.bat_bus), p_mw=_num(v.bat_p),
                             max_e_mwh=_num(v.bat_maxe, 0.05), soc_percent=_num(v.bat_soc, 50)))
    return f"Batería {idx} agregada."


def _agregar_ext_grid(ns, v):
    idx = ns.agregar(ExternalGrid(bus=_int(v.ext_bus)))
    return f"Red externa {idx} agregada."


def _quitar_elemento(ns, v):
    ns.eliminar((v.rm_type or "line").strip(), _int(v.rm_index))
    return f"Elemento {v.rm_type} {v.rm_index} eliminado."


def _ejecutar_codigo(ns, v):
    ns.aplicar_codigo(v.code_text or "")
    return "Código ejecutado."


def _regenerar_codigo(ns, v):
    # El callback regenera el código desde la red pase lo que pase; este botón
    # existe sólo para disparar ese refresco, así que no hay nada más que hacer.
    return "Código regenerado desde la red actual."


def _guardar_nueva(ns, v):
    rid = ns.guardar((v.save_name or "Mi red").strip())
    return f"Red guardada (id {rid[:8]}…)."


def _sobrescribir(ns, v):
    ns.guardar_cambios()
    return "Cambios guardados sobre la red actual."


def _borrar_guardada(ns, v):
    nombre = ns.nombre_guardada(v.guardada_id) or v.guardada_id
    ns.eliminar_guardada(v.guardada_id)
    return f"Red «{nombre}» borrada."


# Botón -> acción. Agregar un botón al panel es agregar una fila acá.
_ACCIONES = {
    "ed-btn-ejemplo": _cargar_ejemplo,
    "ed-btn-simbench": _cargar_simbench,
    "ed-btn-guardada": _cargar_guardada,
    "ed-btn-bus": _agregar_bus,
    "ed-btn-line": _agregar_linea,
    "ed-btn-load": _agregar_carga,
    "ed-btn-sgen": _agregar_solar,
    "ed-btn-bat": _agregar_bateria,
    "ed-btn-ext": _agregar_ext_grid,
    "ed-btn-rm": _quitar_elemento,
    "ed-btn-code": _ejecutar_codigo,
    "ed-btn-code-refresh": _regenerar_codigo,
    "ed-btn-save": _guardar_nueva,
    "ed-btn-save-changes": _sobrescribir,
    "ed-confirm-borrar": _borrar_guardada,
}

# Acciones que rehacen la topología: invalidan el bus seleccionado.
_REHACEN_TOPOLOGIA = frozenset(
    {"ed-btn-ejemplo", "ed-btn-simbench", "ed-btn-guardada", "ed-btn-rm", "ed-btn-code"}
)

# Borrar la red guardada limpia el desplegable; ninguna otra acción lo toca.
_LIMPIAN_SELECCION = frozenset({"ed-confirm-borrar"})


def register_callbacks(app, services):
    network_service = services["network_service"]

    # El enganche de zoom-mapa, grilla y drag-hook se instala solo desde
    # assets/graph_zoom.js (intervalo autónomo), no desde callbacks de Dash.

    def _opciones_guardadas():
        return [{"label": r["nombre"], "value": r["id"]} for r in network_service.listar_guardadas()]

    @app.callback(
        Output("ed-confirm-borrar", "displayed"),
        Output("ed-confirm-borrar", "message"),
        Input("ed-btn-borrar", "n_clicks"),
        State("ed-guardadas", "value"),
        prevent_initial_call=True,
    )
    def confirmar_borrado(_n, red_id):
        """Pide confirmación nombrando la red: borrarla no tiene vuelta atrás."""
        if not red_id:
            return False, ""
        nombre = network_service.nombre_guardada(red_id) or red_id
        return True, (f"¿Borrar definitivamente la red «{nombre}»?\n\n"
                      f"Se elimina del disco y no se puede deshacer. "
                      f"Los resultados de simulación ya calculados no se tocan.")

    @app.callback(
        Output("ed-graph", "elements"),
        Output("ed-summary", "children"),
        Output("ed-status", "children"),
        Output("ed-guardadas", "options"),
        Output("ed-code", "value"),
        Output("ed-guardadas", "value"),
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
        Input("ed-confirm-borrar", "submit_n_clicks"),
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
                   _borrar, simbench_code, guardada_id,
                   bus_vn, bus_name, line_from, line_to, line_len,
                   load_bus, load_p, load_q, sgen_bus, sgen_p,
                   bat_bus, bat_p, bat_maxe, bat_soc, ext_bus,
                   rm_type, rm_index, code_text, save_name):
        disparador = ctx.triggered_id
        valores = _Form(simbench_code, guardada_id, bus_vn, bus_name, line_from, line_to,
                        line_len, load_bus, load_p, load_q, sgen_bus, sgen_p, bat_bus,
                        bat_p, bat_maxe, bat_soc, ext_bus, rm_type, rm_index, code_text,
                        save_name)
        status = ""
        seleccion = no_update
        accion = _ACCIONES.get(disparador)
        if accion is not None:
            try:
                status = accion(network_service, valores)
                if disparador in _LIMPIAN_SELECCION:
                    seleccion = None
            except NombreDuplicadoError as exc:
                status = f"⚠ {exc} — elegí otro nombre."
            except Exception as exc:  # noqa: BLE001
                status = f"⚠ Error: {exc}"

        if disparador in _REHACEN_TOPOLOGIA:
            network_service.selected_bus = None

        modelo = network_service.get_network()
        modelo.ensure_positions()
        net = modelo.net
        return (net_to_elements(net, editable=True, selected=network_service.selected_bus),
                _resumen(net), status, _opciones_guardadas(), network_service.generar_codigo(),
                seleccion)

    # ---- panel de detalle por bus (estilo mapa) --------------------------
    _SHOW, _HIDE = {"display": "block"}, {"display": "none"}

    def _guardar_posicion(bus_idx: int, pos: dict) -> None:
        """Persiste la posición de un bus solo si de verdad se movió.

        El grafo entrega la posición **renderizada**, que incluye el corrimiento
        anti-superposición de ``net_to_elements``. Hay que descontarlo: si no, un
        simple click sobre un bus apilado lo desplazaba de forma permanente. Y
        como el JS reenvía el ``dragfree`` como ``tap``, un click y un arrastre
        llegan iguales — por eso se compara contra la posición guardada y se
        escribe solo ante un cambio real, que además es lo que evita invalidar
        la caché de simulaciones sin motivo.
        """
        modelo = network_service.get_network()
        gx, gy = geo_desde_pixel(modelo.net, bus_idx, pos["x"], pos["y"])
        actual = modelo.get_bus_position(bus_idx)
        if actual is None or abs(actual[0] - gx) > 1e-4 or abs(actual[1] - gy) > 1e-4:
            modelo.set_bus_position(bus_idx, gx, gy)

    def _refresh_graph():
        modelo = network_service.get_network()
        modelo.ensure_positions()
        return net_to_elements(modelo.net, editable=True, selected=network_service.selected_bus)

    @app.callback(
        Output("ed-main-panel", "style"),
        Output("ed-detail-panel", "style"),
        Output("edd-title", "children"),
        Output("edd-body", "children"),
        Output("edd-status", "children"),
        Output("ed-graph", "elements", allow_duplicate=True),
        Output("ed-code", "value", allow_duplicate=True),
        Output("ed-summary", "children", allow_duplicate=True),
        Input("ed-graph", "tapNode"),
        Input("edd-back", "n_clicks"),
        Input("edd-apply", "n_clicks"),
        Input("edd-delbus", "n_clicks"),
        Input({"role": "detdel", "kind": ALL, "idx": ALL}, "n_clicks"),
        Input({"role": "detadd", "kind": ALL}, "n_clicks"),
        State({"role": "detf", "kind": ALL, "idx": ALL, "field": ALL}, "value"),
        prevent_initial_call=True,
    )
    def detalle(tap_node, _back, _apply, _delbus, _dels, _adds, _field_values):
        disp = ctx.triggered_id
        ns = network_service
        nada = (no_update,) * 8

        def _resumen_actual():
            return _resumen(ns.get_network().net)

        def abrir(bus_idx, status=""):
            det = ns.detalle_bus(bus_idx)
            if det is None:
                return cerrar()
            ns.selected_bus = bus_idx
            titulo = f"Bus {bus_idx} — {det['name'] or 'sin nombre'}"
            return (_HIDE, _SHOW, titulo, _detail_body(det), status,
                    _refresh_graph(), ns.generar_codigo(), _resumen_actual())

        def cerrar():
            ns.selected_bus = None
            return (_SHOW, _HIDE, "", [], "", _refresh_graph(), ns.generar_codigo(), _resumen_actual())

        # Selección o arrastre de un bus en el grafo.
        if disp == "ed-graph":
            if not tap_node:
                return nada
            nid = (tap_node.get("data") or {}).get("id", "")
            pos = tap_node.get("position") or {}
            if not (nid.startswith("b") and nid[1:].isdigit()):
                return nada
            bus_idx = int(nid[1:])
            if "x" in pos:
                _guardar_posicion(bus_idx, pos)
            return abrir(bus_idx)

        if disp == "edd-back":
            return cerrar()

        sel = ns.selected_bus
        if sel is None:
            return nada

        try:
            if disp == "edd-delbus":
                ns.eliminar("bus", sel)
                return cerrar()
            if disp == "edd-apply":
                pos = {}
                for est in (ctx.states_list[0] or []):
                    cid, val = est["id"], est.get("value")
                    if cid["kind"] == "pos":
                        pos[cid["field"]] = val
                    else:
                        ns.editar_campo(cid["kind"], cid["idx"], cid["field"], val)
                if pos:
                    ns.mover_bus(sel, _num(pos.get("x"), 0.0), _num(pos.get("y"), 0.0))
                return abrir(sel, "Cambios aplicados.")
            if isinstance(disp, dict) and disp.get("role") == "detdel":
                ns.quitar_elemento(disp["kind"], disp["idx"])
                return abrir(sel, "Elemento eliminado.")
            if isinstance(disp, dict) and disp.get("role") == "detadd":
                ns.agregar_en_bus(disp["kind"], sel)
                return abrir(sel, "Elemento agregado.")
        except Exception as exc:  # noqa: BLE001
            det = ns.detalle_bus(sel)
            titulo = f"Bus {sel} — {det['name'] if det else ''}"
            return (_HIDE, _SHOW, titulo, _detail_body(det) if det else [], f"⚠ Error: {exc}",
                    _refresh_graph(), ns.generar_codigo(), _resumen_actual())

        return nada
