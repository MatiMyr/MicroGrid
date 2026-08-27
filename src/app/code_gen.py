"""Generación del script Python que reconstruye una red desde cero.

Vive aparte de ``NetworkService`` porque no es lógica de servicio sino un
**emisor de código**: una función por tabla de pandapower, todas con la misma
forma (reciben el ``DataFrame`` y devuelven las líneas del script), más un
puñado de helpers que traducen una celda a su literal Python.

El contrato lo describe ``NetworkService.generar_codigo``, que es la puerta de
entrada; acá está el cómo.
"""
from __future__ import annotations

import math

import pandas.api.types as ptypes

# Columnas eléctricamente relevantes que las entidades del dominio no reciben
# por constructor. Se emiten aparte con ``model.set_field`` para que el
# round-trip no pierda límites de OPF ni parámetros avanzados.
EXTRAS = {
    "bus": ["min_vm_pu", "max_vm_pu"],
    "line": ["std_type", "max_loading_percent"],
    "trafo": ["std_type", "max_loading_percent"],
    "load": ["sn_mva", "const_z_p_percent", "const_i_p_percent",
             "const_z_q_percent", "const_i_q_percent", "type", "controllable",
             "max_p_mw", "min_p_mw", "max_q_mvar", "min_q_mvar"],
    "sgen": ["sn_mva", "type", "current_source", "controllable",
             "max_p_mw", "min_p_mw", "max_q_mvar", "min_q_mvar"],
    "storage": ["sn_mva", "type", "min_e_mwh", "controllable", "max_p_mw", "min_p_mw"],
    "ext_grid": ["slack_weight", "controllable",
                 "max_p_mw", "min_p_mw", "max_q_mvar", "min_q_mvar"],
}

_ENCABEZADO = [
    "# Este código reconstruye la red. Es la fuente de verdad:",
    "# editá valores/nombres, borrá una línea para quitar un elemento,",
    "# o agregá elementos nuevos. «Ejecutar código» aplica todo.",
    "model = NetworkModel()",
    "net = model.net",
    "",
]


# ---- celda -> literal Python -------------------------------------------
def es_nulo(valor) -> bool:
    """``True`` para ``None`` y para ``NaN`` (numpy.float64 hereda de float)."""
    return valor is None or (isinstance(valor, float) and math.isnan(valor))


def fmt(valor: float) -> float:
    """Recorta a 12 cifras **significativas**, no a 12 decimales.

    Redondear a una cantidad fija de decimales degrada los valores chicos: un
    ``length_km`` de 0.0123456789 perdía 4 órdenes de precisión relativa, y esa
    diferencia se propaga a las pérdidas de la simulación. Con cifras
    significativas el error relativo es el mismo para cualquier magnitud, y el
    número sigue siendo legible.
    """
    return float("%.12g" % float(valor))


def _num(df, idx, col, default=0.0):
    """Valor numérico de una celda, o ``default`` si falta o no es un número."""
    if col not in df.columns:
        return default
    try:
        valor = float(df.at[idx, col])
    except (TypeError, ValueError):
        return default
    return default if valor != valor else fmt(valor)  # NaN -> default


def _txt(df, idx, col) -> str:
    """Repr de una columna de texto: ``'hv'`` o ``None``."""
    if col not in df.columns:
        return "None"
    valor = df.at[idx, col]
    if valor is None or es_nulo(valor) or str(valor) == "nan":
        return "None"
    return repr(str(valor))


def _opt_num(df, idx, col) -> str:
    """Repr de una columna numérica opcional: ``2.5`` o ``None``."""
    if col not in df.columns:
        return "None"
    try:
        valor = float(df.at[idx, col])
    except (TypeError, ValueError):
        return "None"
    return "None" if valor != valor else repr(fmt(valor))


def _flag(df, idx, col, default=True) -> str:
    """Repr de una columna booleana, con ``default`` cuando falta o es nula."""
    if col not in df.columns:
        return repr(default)
    valor = df.at[idx, col]
    if es_nulo(valor):
        return repr(default)
    return repr(bool(valor))


def _nom(df, idx) -> str:
    return _txt(df, idx, "name")


def _literal_extra(df, col, valor) -> str:
    """Literal de una celda de ``EXTRAS``, respetando el dtype de la columna.

    El tipo lo decide el dtype, no el valor: ``numpy.bool_`` no es ``bool`` de
    Python, y escribir ``1.0`` en una columna booleana la corrompe.
    """
    if ptypes.is_bool_dtype(df[col]):
        return repr(bool(valor))
    if isinstance(valor, str):
        return repr(valor)
    try:
        return repr(fmt(valor))
    except (TypeError, ValueError):
        return repr(str(valor))


# ---- un emisor por tabla ------------------------------------------------
# Todos devuelven las líneas de su sección, ya con el renglón en blanco final,
# o una lista vacía cuando la tabla no tiene filas. Buses y posiciones son la
# excepción (``siempre=True``): su encabezado sale aunque la red esté vacía,
# porque son las dos secciones que el usuario espera encontrar para escribir.
def _seccion(titulo: str, filas: list[str], siempre: bool = False) -> list[str]:
    return [titulo, *filas, ""] if filas or siempre else []


def _buses(net) -> list[str]:
    df = net.bus
    return _seccion("# --- Buses ---", [
        f"model.add_bus(Bus(index={int(i)}, vn_kv={_num(df, i, 'vn_kv', 0.4)}, "
        f"name={_nom(df, i)}, type={_txt(df, i, 'type')}, "
        f"in_service={_flag(df, i, 'in_service')}))"
        for i in df.index
    ], siempre=True)


def _posiciones(model) -> list[str]:
    return _seccion("# --- Posiciones (x, y): editables y arrastrables en el grafo ---", [
        f"model.set_bus_position({int(i)}, {x}, {y})"
        for i, (x, y) in model.bus_positions().items()
    ], siempre=True)


def _ext_grids(net) -> list[str]:
    df = net.ext_grid
    return _seccion("# --- Red externa ---", [
        f"model.add_ext_grid(ExternalGrid(index={int(i)}, "
        f"bus={int(df.at[i, 'bus'])}, "
        f"vm_pu={_num(df, i, 'vm_pu', 1.0)}, "
        f"va_degree={_num(df, i, 'va_degree')}, "
        f"name={_nom(df, i)}, "
        f"in_service={_flag(df, i, 'in_service')}))"
        for i in df.index
    ])


def _lineas(net) -> list[str]:
    # ``create_line_from_parameters`` (y no ``create_line``) para que la red se
    # reconstruya sin depender de que su ``std_type`` esté en la librería.
    df = net.line
    return _seccion("# --- Líneas ---", [
        f"pp.create_line_from_parameters(net, index={int(i)}, "
        f"from_bus={int(df.at[i, 'from_bus'])}, to_bus={int(df.at[i, 'to_bus'])}, "
        f"length_km={_num(df, i, 'length_km', 0.1)}, "
        f"r_ohm_per_km={_num(df, i, 'r_ohm_per_km')}, x_ohm_per_km={_num(df, i, 'x_ohm_per_km')}, "
        f"c_nf_per_km={_num(df, i, 'c_nf_per_km')}, g_us_per_km={_num(df, i, 'g_us_per_km')}, "
        f"max_i_ka={_num(df, i, 'max_i_ka', 1.0)}, "
        f"parallel={int(_num(df, i, 'parallel', 1))}, df={_num(df, i, 'df', 1.0)}, "
        f"type={_txt(df, i, 'type')}, in_service={_flag(df, i, 'in_service')}, "
        f"name={_nom(df, i)})"
        for i in df.index
    ])


def _trafos(net) -> list[str]:
    df = net.trafo
    return _seccion("# --- Transformadores (incluye la regulación del tap) ---", [
        f"pp.create_transformer_from_parameters(net, index={int(i)}, "
        f"hv_bus={int(df.at[i, 'hv_bus'])}, lv_bus={int(df.at[i, 'lv_bus'])}, "
        f"sn_mva={_num(df, i, 'sn_mva', 0.4)}, vn_hv_kv={_num(df, i, 'vn_hv_kv', 20.0)}, "
        f"vn_lv_kv={_num(df, i, 'vn_lv_kv', 0.4)}, vkr_percent={_num(df, i, 'vkr_percent', 1.0)}, "
        f"vk_percent={_num(df, i, 'vk_percent', 4.0)}, pfe_kw={_num(df, i, 'pfe_kw')}, "
        f"i0_percent={_num(df, i, 'i0_percent')}, shift_degree={_num(df, i, 'shift_degree')}, "
        f"tap_side={_txt(df, i, 'tap_side')}, tap_neutral={_opt_num(df, i, 'tap_neutral')}, "
        f"tap_min={_opt_num(df, i, 'tap_min')}, tap_max={_opt_num(df, i, 'tap_max')}, "
        f"tap_step_percent={_opt_num(df, i, 'tap_step_percent')}, "
        f"tap_step_degree={_opt_num(df, i, 'tap_step_degree')}, "
        f"tap_pos={_opt_num(df, i, 'tap_pos')}, "
        f"tap_changer_type={_txt(df, i, 'tap_changer_type')}, "
        f"vector_group={_txt(df, i, 'vector_group')}, "
        f"parallel={int(_num(df, i, 'parallel', 1))}, df={_num(df, i, 'df', 1.0)}, "
        f"in_service={_flag(df, i, 'in_service')}, name={_nom(df, i)})"
        for i in df.index
    ])


def _cargas(net, model) -> list[str]:
    df = net.load
    return _seccion("# --- Cargas (perfil_tipo elige la curva horaria de cada una) ---", [
        f"model.add_load(Load(index={int(i)}, bus={int(df.at[i, 'bus'])}, "
        f"p_mw={_num(df, i, 'p_mw')}, q_mvar={_num(df, i, 'q_mvar')}, "
        f"scaling={_num(df, i, 'scaling', 1.0)}, "
        f"perfil_tipo={model.tipo_de_carga(i)!r}, "
        f"in_service={_flag(df, i, 'in_service')}, name={_nom(df, i)}))"
        for i in df.index
    ])


def _solar(net) -> list[str]:
    df = net.sgen
    return _seccion("# --- Solar ---", [
        f"model.add_solar_panel(SolarPanel(index={int(i)}, bus={int(df.at[i, 'bus'])}, "
        f"p_mw={_num(df, i, 'p_mw')}, q_mvar={_num(df, i, 'q_mvar')}, "
        f"scaling={_num(df, i, 'scaling', 1.0)}, "
        f"in_service={_flag(df, i, 'in_service')}, name={_nom(df, i)}))"
        for i in df.index
    ])


def _baterias(net) -> list[str]:
    df = net.storage
    return _seccion("# --- Baterías (p_mw > 0 = carga, p_mw < 0 = descarga) ---", [
        f"model.add_battery(Battery(index={int(i)}, bus={int(df.at[i, 'bus'])}, "
        f"p_mw={_num(df, i, 'p_mw')}, max_e_mwh={_num(df, i, 'max_e_mwh', 0.05)}, "
        f"q_mvar={_num(df, i, 'q_mvar')}, soc_percent={_num(df, i, 'soc_percent', 50.0)}, "
        f"scaling={_num(df, i, 'scaling', 1.0)}, "
        f"in_service={_flag(df, i, 'in_service')}, name={_nom(df, i)}))"
        for i in df.index
    ])


def _switches(net) -> list[str]:
    df = net.switch
    return _seccion("# --- Interruptores ---", [
        f"pp.create_switch(net, index={int(i)}, bus={int(df.at[i, 'bus'])}, "
        f"element={int(df.at[i, 'element'])}, et={_txt(df, i, 'et')}, "
        f"closed={_flag(df, i, 'closed')}, type={_txt(df, i, 'type')}, "
        f"z_ohm={_num(df, i, 'z_ohm')}, name={_nom(df, i)})"
        for i in df.index
    ])


def _ajustes_finos(net) -> list[str]:
    filas: list[str] = []
    for tabla, columnas in EXTRAS.items():
        df = getattr(net, tabla, None)
        if df is None or not len(df):
            continue
        for i in df.index:
            for col in columnas:
                if col not in df.columns:
                    continue
                valor = df.at[i, col]
                if es_nulo(valor) or valor is None or str(valor) == "nan":
                    continue
                literal = _literal_extra(df, col, valor)
                filas.append(f"model.set_field({tabla!r}, {int(i)}, {col!r}, {literal})")
    return _seccion("# --- Ajustes finos: límites de OPF y parámetros avanzados ---", filas)


def generar_codigo(model) -> str:
    """Arma el script completo que reconstruye ``model`` desde cero."""
    model.ensure_positions()
    net = model.net
    lineas = [
        *_ENCABEZADO,
        *_buses(net),
        *_posiciones(model),
        *_ext_grids(net),
        *_lineas(net),
        *_trafos(net),
        *_cargas(net, model),
        *_solar(net),
        *_baterias(net),
        *_switches(net),
        *_ajustes_finos(net),
    ]
    return "\n".join(lineas).rstrip() + "\n"
