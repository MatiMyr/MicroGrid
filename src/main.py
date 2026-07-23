"""Punto de entrada de Smart Microgrid Argentina.

Arma la app Dash con dos pestañas — Editor de red y Dashboard de simulación —
compartiendo una única instancia de los servicios (la red en memoria es la misma
para ambas pestañas).

Ejecutar desde ``src/``:

    python main.py

Luego abrir http://127.0.0.1:8050 en el navegador.
"""
from __future__ import annotations

import dash
from dash import dcc, html

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
    profile_builder = ProfileBuilder(demanda_repo=demanda_repo, irradiacion_repo=irradiacion_repo)
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


def create_app() -> dash.Dash:
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    app.title = "Smart Microgrid Argentina"
    services = build_services()

    app.layout = html.Div(
        [
            html.H2("⚡ Smart Microgrid Argentina",
                    style={"margin": "8px", "color": "#1565c0"}),
            dcc.Tabs(
                [
                    dcc.Tab(label="Editor de red", children=editor.layout()),
                    dcc.Tab(label="Dashboard", children=dashboard.layout()),
                ]
            ),
        ]
    )

    editor.register_callbacks(app, services)
    dashboard.register_callbacks(app, services)
    return app


app = create_app()
server = app.server  # para despliegue WSGI (gunicorn, etc.)


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050)
