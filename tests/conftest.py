"""Configuración común de los tests.

Los módulos del proyecto se importan como ``domain.x`` / ``app.x`` asumiendo que
``src/`` está en el path (la app se ejecuta con ``cd src && python main.py``), así
que acá se agrega ``src/`` al ``sys.path`` para poder correr ``pytest`` desde la
raíz del repositorio.
"""
from __future__ import annotations

import logging
import sys
import warnings
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# pandapower es ruidoso (avisos de numba, de conversión de tipos, etc.) y acá no
# aporta nada.
warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)


@pytest.fixture
def sim_repo(tmp_path):
    """Repositorio de resultados aislado en un directorio temporal."""
    from repositories.json_simulation_repository import JsonSimRepository

    return JsonSimRepository(tmp_path / "resultados")


@pytest.fixture
def network_service():
    """Servicio de red con la red de ejemplo (3 buses, 2 cargas, 1 solar, 1 batería)."""
    from app.network_service import NetworkService

    return NetworkService()


@pytest.fixture
def simulation_service(network_service, sim_repo):
    from app.simulation_service import SimulationService
    from domain.profile_builder import ProfileBuilder

    return SimulationService(
        network_service=network_service,
        sim_repo=sim_repo,
        profile_builder=ProfileBuilder(),
    )
