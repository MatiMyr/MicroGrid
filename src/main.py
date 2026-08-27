"""Punto de entrada de Smart Microgrid Argentina.

Arma la app Dash con dos pestañas — Editor de red y Dashboard de simulación —
compartiendo una única instancia de los servicios (la red en memoria es la misma
para ambas pestañas).

Ejecutar desde ``src/``:

    python main.py

Luego abrir http://127.0.0.1:8050 en el navegador.

Herramienta **local y monousuario**, a propósito
------------------------------------------------
Dos decisiones de diseño lo vuelven un requisito, no una preferencia:

1. El Editor ejecuta código Python del usuario con ``exec``
   (``NetworkService.aplicar_codigo``). Expuesto en red, eso es ejecución
   remota de código arbitraria y sin autenticación.
2. El estado —la red en memoria— es una única instancia compartida por todo el
   proceso. Es lo que hace que las dos pestañas editen la misma red, y también
   lo que impide atender a dos usuarios a la vez: se pisarían la red entre sí,
   y con varios workers cada uno tendría una red distinta.

Por eso la app escucha sólo en ``127.0.0.1`` y no se exporta un objeto WSGI
para gunicorn: servirla detrás de un servidor de producción sería contradecir
los dos puntos de arriba. Para habilitar multiusuario primero hay que aislar el
estado por sesión y sacar (o encerrar) el ``exec``.
"""
from __future__ import annotations

import os

import dash
from dash import Input, Output, dcc, html

from app.data_sync_service import DataSyncService
from app.network_service import NetworkService
from app.simulation_service import SimulationService
from domain.profile_builder import ProfileBuilder
from repositories.json_demanda_repository import JsonDemandaRepository
from repositories.json_irradiacion_repository import JsonIrradiacionRepository
from repositories.json_simbench_repository import JsonSimbenchRepository
from ui import dashboard, editor


def build_services() -> dict:
    """Crea los servicios compartiendo los repos de caché entre todos.

    El ``ProfileBuilder`` (que lee la caché) y el ``DataSyncService`` (que la
    escribe) usan las mismas instancias de repositorio, así lo que sincroniza el
    Dashboard queda disponible para la próxima simulación.
    """
    demanda_repo = JsonDemandaRepository()
    irradiacion_repo = JsonIrradiacionRepository()
    simbench_repo = JsonSimbenchRepository()

    network_service = NetworkService(simbench_repo=simbench_repo)
    # ``usar_demanda_real=False``: la demanda de CAMMESA queda aislada. Su serie
    # es el consumo agregado de una región entera, así que aplicarla imponía una
    # única curva a todas las cargas y anulaba el tipo de consumidor de cada una.
    # El repositorio se sigue inyectando para poder reactivarla con un solo flag.
    profile_builder = ProfileBuilder(
        demanda_repo=demanda_repo, irradiacion_repo=irradiacion_repo, usar_demanda_real=False
    )
    simulation_service = SimulationService(
        network_service=network_service, profile_builder=profile_builder
    )
    data_sync_service = DataSyncService(
        demanda_repo=demanda_repo,
        irradiacion_repo=irradiacion_repo,
        simbench_repo=simbench_repo,
    )
    return {
        "network_service": network_service,
        "simulation_service": simulation_service,
        "data_sync_service": data_sync_service,
    }


# Restaura el tema guardado antes del primer render (evita el parpadeo).
_INDEX = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <script>
          (function () {
            try {
              var t = localStorage.getItem('mg-theme');
              if (t) { document.documentElement.setAttribute('data-theme', t); }
            } catch (e) {}
          })();
        </script>
    </head>
    <body>
        {%app_entry%}
        <footer>{%config%}{%scripts%}{%renderer%}</footer>
    </body>
</html>"""


def _header():
    return html.Div(
        [
            html.Div(
                [
                    html.Div("⚡", className="logo"),
                    html.Div([
                        html.H1("Smart Microgrid Argentina"),
                        html.P("Simulación de microgrids de baja tensión · datos argentinos",
                               className="sub"),
                    ]),
                ],
                className="app-brand",
            ),
            html.Button("🌙  Oscuro", id="theme-toggle", className="theme-toggle", n_clicks=0),
        ],
        className="app-header",
    )


def create_app() -> dash.Dash:
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    app.title = "Smart Microgrid Argentina"
    app.index_string = _INDEX
    services = build_services()

    app.layout = html.Div(
        [
            _header(),
            html.Div(
                dcc.Tabs(
                    className="tab-bar", parent_className="tab-parent",
                    children=[
                        dcc.Tab(label="Editor de red", children=editor.layout(),
                                className="custom-tab", selected_className="custom-tab--selected"),
                        dcc.Tab(label="Dashboard", children=dashboard.layout(),
                                className="custom-tab", selected_className="custom-tab--selected"),
                    ],
                ),
                className="app-tabs",
            ),
        ]
    )

    app.clientside_callback(
        """
        function(n) {
            if (!n) { return window.dash_clientside.no_update; }
            var root = document.documentElement;
            var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            root.setAttribute('data-theme', next);
            try { localStorage.setItem('mg-theme', next); } catch (e) {}
            return next === 'dark' ? '☀\\uFE0F  Claro' : '🌙  Oscuro';
        }
        """,
        Output("theme-toggle", "children"),
        Input("theme-toggle", "n_clicks"),
        prevent_initial_call=True,
    )

    editor.register_callbacks(app, services)
    dashboard.register_callbacks(app, services)
    return app


app = create_app()


if __name__ == "__main__":
    # El modo debug de Dash levanta la consola interactiva de Werkzeug, que
    # ejecuta código arbitrario desde el navegador: se activa a pedido con
    # ``MG_DEBUG=1``, nunca por defecto.
    debug = os.environ.get("MG_DEBUG") == "1"
    app.run(debug=debug, host="127.0.0.1", port=8050)
