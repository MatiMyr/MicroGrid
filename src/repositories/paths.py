"""Ubicación canónica de los datos de runtime del proyecto.

Todos los repositorios anclan sus rutas a este módulo en vez de usar rutas
relativas al directorio de trabajo. Con rutas relativas, arrancar la app desde
la raíz del repo (o desde un IDE) creaba un árbol ``data/`` vacío en otro lado y
las redes guardadas desaparecían del desplegable sin ningún error visible.
"""
from __future__ import annotations

from pathlib import Path

# ``src/repositories/paths.py`` -> ``src/`` -> ``src/data``
SRC_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SRC_DIR / "data"

REDES_DIR = DATA_DIR / "redes"
SIMBENCH_DIR = REDES_DIR / "simbench"
RESULTADOS_DIR = DATA_DIR / "resultados"
CACHE_CAMMESA_DIR = DATA_DIR / "cache" / "cammesa"
CACHE_NASA_DIR = DATA_DIR / "cache" / "nasa"
