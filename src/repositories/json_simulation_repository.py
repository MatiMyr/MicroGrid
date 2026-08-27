"""Caché de resultados de simulación, direccionada por contenido.

Dos niveles con responsabilidades separadas a propósito:

- ``data/resultados/{input_hash}.json`` — el **instante**: solo el contenido
  físico que se deriva de las entradas (tensiones, flujos, pérdidas, SoC). Al
  estar direccionado por el hash de sus entradas, dos corridas distintas con las
  mismas entradas comparten legítimamente el archivo.
- ``data/resultados/_corridas/{run_id}.json`` — la **corrida**: sus metadatos
  (red, escenario, modo, momento) y la secuencia ordenada de hashes por hora.

La separación es lo que evita que una corrida nueva le pise los metadatos a una
vieja al reusar un instante cacheado.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from domain.entities import SimulationResult
from repositories.paths import RESULTADOS_DIR

# Versión del esquema del **índice de corrida**, independiente del esquema del
# instante (``domain.entities.SCHEMA_VERSION_INSTANTE``). Compartir un solo
# número obligaba a invalidar los índices por un cambio de física y al revés.
SCHEMA_VERSION_CORRIDA = 1


class JsonSimRepository:
    def __init__(self, base_dir=None):
        self._dir = Path(base_dir) if base_dir else RESULTADOS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._corridas_dir = self._dir / "_corridas"

    # ---- caché por instante (indexada por hash de entrada) ---------------
    def _path(self, input_hash: str) -> Path:
        return self._dir / f"{input_hash}.json"

    def buscar_por_hash(self, input_hash: str) -> Optional[SimulationResult]:
        """Devuelve el instante cacheado, o ``None`` si hay que volver a simular.

        Un ``None`` cubre los tres casos de cache miss —no existe, está escrito
        con un esquema viejo, o el archivo está corrupto— en una sola operación,
        sin la carrera del par ``existe()`` + ``cargar()``.
        """
        path = self._path(input_hash)
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        return SimulationResult.from_cache_dict(data)

    def guardar_por_hash(self, resultado: SimulationResult) -> None:
        """Persiste el contenido físico de un instante bajo su ``input_hash``.

        Solo se guardan los campos de instante: los metadatos de corrida
        (``run_id``, ``hour_index``, ``nombre_red``, …) van al índice de corrida,
        porque el mismo archivo puede pertenecer a muchas corridas a la vez.
        """
        if not resultado.input_hash:
            raise ValueError("El resultado no tiene input_hash: no se puede cachear.")
        path = self._path(resultado.input_hash)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(resultado.to_cache_dict(), f, indent=2)

    # ---- índice de corridas ----------------------------------------------
    def guardar_indice_corrida(
        self,
        run_id: str,
        hashes: list[str],
        nombre_red: str = "",
        escenario: str = "",
        mode: str = "",
        timestamp: str = "",
    ) -> None:
        """Guarda los metadatos de una corrida y su secuencia de instantes.

        El orden importa: dos horas con entradas idénticas comparten el mismo
        archivo cacheado, así que la lista de hashes es lo único que preserva la
        secuencia completa por hora, repeticiones incluidas.
        """
        self._corridas_dir.mkdir(exist_ok=True)
        datos = {
            "schema_version": SCHEMA_VERSION_CORRIDA,
            "run_id": run_id,
            "nombre_red": nombre_red,
            "escenario": escenario,
            "mode": mode,
            "timestamp": timestamp,
            "hashes": list(hashes),
        }
        with open(self._corridas_dir / f"{run_id}.json", "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)

    def _leer_indice_corrida(self, run_id: str) -> Optional[dict]:
        path = self._corridas_dir / f"{run_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                datos = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(datos, dict) or datos.get("schema_version") != SCHEMA_VERSION_CORRIDA:
            return None
        return datos

    def listar_corrida(self, run_id: str) -> list[SimulationResult]:
        """Reconstruye los instantes de una corrida en orden de hora.

        La hora y los metadatos de red salen del índice (la posición en la lista
        de hashes), nunca del archivo del instante. Si algún instante ya no está
        cacheado, la corrida se devuelve vacía en vez de con agujeros que
        desplazarían las horas siguientes.
        """
        datos = self._leer_indice_corrida(run_id)
        if datos is None:
            return []
        resultados: list[SimulationResult] = []
        for hora, h in enumerate(datos.get("hashes", [])):
            instante = self.buscar_por_hash(h)
            if instante is None:
                return []
            instante.run_id = run_id
            instante.hour_index = hora
            instante.nombre_red = datos.get("nombre_red", "")
            instante.escenario = datos.get("escenario", "")
            instante.timestamp = datos.get("timestamp", instante.timestamp)
            resultados.append(instante)
        return resultados

    def listar(self) -> list[dict]:
        """Devuelve los metadatos de cada corrida guardada, de la más nueva a la más vieja."""
        if not self._corridas_dir.exists():
            return []
        corridas = []
        for path in self._corridas_dir.glob("*.json"):
            datos = self._leer_indice_corrida(path.stem)
            if datos is None:
                continue
            corridas.append({
                "run_id": datos.get("run_id", path.stem),
                "nombre_red": datos.get("nombre_red", ""),
                "escenario": datos.get("escenario", ""),
                "mode": datos.get("mode", ""),
                "timestamp": datos.get("timestamp", ""),
                "horas": len(datos.get("hashes", [])),
            })
        return sorted(corridas, key=lambda c: c["timestamp"], reverse=True)

    # ---- mantenimiento ---------------------------------------------------
    def tamanio(self) -> dict:
        """Devuelve ``{instantes, corridas, bytes}`` de la caché en disco."""
        instantes = [p for p in self._dir.glob("*.json")]
        corridas = list(self._corridas_dir.glob("*.json")) if self._corridas_dir.exists() else []
        total = sum(p.stat().st_size for p in instantes + corridas)
        return {"instantes": len(instantes), "corridas": len(corridas), "bytes": total}

    def purgar(self) -> dict:
        """Borra toda la caché de resultados. Devuelve lo que había antes de borrar.

        Los resultados son datos derivados y regenerables: no se pierde nada que
        no se pueda volver a calcular. No toca redes ni cachés de datos externos.
        """
        antes = self.tamanio()
        if self._corridas_dir.exists():
            shutil.rmtree(self._corridas_dir)
        for path in self._dir.glob("*.json"):
            path.unlink(missing_ok=True)
        self._dir.mkdir(parents=True, exist_ok=True)
        return antes
