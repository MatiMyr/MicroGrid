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

    # ---- caché por instante (indexada por hash de entrada) ---------------
    def existe(self, input_hash: str) -> bool:
        """Indica si el instante con ese hash de entrada ya fue simulado."""
        return (self._dir / f"{input_hash}.json").exists()

    def guardar_por_hash(self, resultado: SimulationResult) -> None:
        """Persiste un instante indexado por su ``input_hash`` (acceso directo)."""
        path = self._dir / f"{resultado.input_hash}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dataclasses.asdict(resultado), f, indent=2)

    def cargar_por_hash(self, input_hash: str) -> SimulationResult:
        """Lee un instante cacheado por su hash; lanza ``FileNotFoundError`` si no existe."""
        path = self._dir / f"{input_hash}.json"
        if not path.exists():
            raise FileNotFoundError(f"Instante no cacheado: {input_hash}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return SimulationResult(**data)

    def guardar_indice_corrida(self, run_id: str, hashes: list[str]) -> None:
        """Guarda el orden de instantes (hashes) de una corrida.

        Necesario porque dos horas con entradas idénticas comparten el mismo
        archivo cacheado; el índice preserva la secuencia completa por hora para
        reconstruir la corrida en el Dashboard sin perder horas repetidas.
        """
        idx_dir = self._dir / "_corridas"
        idx_dir.mkdir(exist_ok=True)
        with open(idx_dir / f"{run_id}.json", "w", encoding="utf-8") as f:
            json.dump(hashes, f, indent=2)

    def listar_corrida(self, run_id: str) -> list[SimulationResult]:
        """Reconstruye los instantes de una corrida en orden de hora.

        Usa el índice de la corrida si existe (preservando horas repetidas); si
        no, cae en un escaneo por ``run_id`` ordenado por hora.
        """
        idx_path = self._dir / "_corridas" / f"{run_id}.json"
        if idx_path.exists():
            with open(idx_path, encoding="utf-8") as f:
                hashes = json.load(f)
            return [self.cargar_por_hash(h) for h in hashes if self.existe(h)]

        instantes = []
        for path in self._dir.glob("*.json"):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("run_id") == run_id:
                instantes.append(SimulationResult(**data))
        return sorted(instantes, key=lambda r: r.hour_index)

    def listar(self) -> list[dict]:
        """Devuelve metadatos de cada simulación guardada."""
        campos = {"id", "timestamp", "nombre_red", "escenario", "run_id", "hour_index"}
        resultado = []
        for path in self._dir.glob("*.json"):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            resultado.append({k: data.get(k) for k in campos})
        return resultado

    def eliminar(self, id_simulacion: str) -> None:
        """Elimina el archivo de la simulación; lanza FileNotFoundError si no existe."""
        path = self._dir / f"{id_simulacion}.json"
        if not path.exists():
            raise FileNotFoundError(f"Simulación no encontrada: {path}")
        path.unlink()
