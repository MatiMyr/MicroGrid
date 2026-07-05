from pathlib import Path
import json
import dataclasses

from domain.entities import SimulationResult


class JsonSimRepository:
    def __init__(self, base_dir: str = "data/resultados"):
        self._dir = Path(base_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def guardar(self, resultado: SimulationResult) -> None:
        """Persiste el SimulationResult como JSON en disco."""
        path = self._dir / f"{resultado.id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dataclasses.asdict(resultado), f, indent=2)

    def cargar(self, id_simulacion: str) -> SimulationResult:
        """Lee el JSON y devuelve el SimulationResult; lanza FileNotFoundError si no existe."""
        path = self._dir / f"{id_simulacion}.json"
        if not path.exists():
            raise FileNotFoundError(f"Simulación no encontrada: {path}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return SimulationResult(**data)

    def listar(self) -> list[dict]:
        """Devuelve metadatos (id, timestamp, nombre_red, escenario) de cada simulación guardada."""
        campos = {"id", "timestamp", "nombre_red", "escenario"}
        resultado = []
        for path in self._dir.glob("*.json"):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            resultado.append({k: data[k] for k in campos})
        return resultado

    def eliminar(self, id_simulacion: str) -> None:
        """Elimina el archivo de la simulación; lanza FileNotFoundError si no existe."""
        path = self._dir / f"{id_simulacion}.json"
        if not path.exists():
            raise FileNotFoundError(f"Simulación no encontrada: {path}")
        path.unlink()
