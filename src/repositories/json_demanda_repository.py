from pathlib import Path
import json


class JsonDemandaRepository:
    """Caché de demanda horaria de CAMMESA bajo ``data/cache/cammesa/``.

    Los datos se guardan por región del sistema eléctrico argentino. Cada
    archivo ``{region}.json`` es un mapa ``timestamp ISO -> demanda_mw``. Al
    agregar datos nuevos no se duplica lo que ya existe (se mergea por clave).
    """

    def __init__(self, base_dir: str = "data/cache/cammesa"):
        self._dir = Path(base_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, region: str) -> Path:
        return self._dir / f"{region.lower()}.json"

    def guardar(self, region: str, serie: dict[str, float]) -> None:
        """Agrega ``serie`` (timestamp ISO -> MW) al caché de ``region`` sin duplicar."""
        path = self._path(region)
        actual: dict[str, float] = {}
        if path.exists():
            with open(path, encoding="utf-8") as f:
                actual = json.load(f)
        actual.update({str(k): float(v) for k, v in serie.items()})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(actual, f, indent=2, sort_keys=True)

    def cargar(self, region: str) -> dict[str, float]:
        """Devuelve toda la serie cacheada de ``region`` (vacío si no hay datos)."""
        path = self._path(region)
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def existe(self, region: str) -> bool:
        """Indica si hay datos cacheados para ``region``."""
        return self._path(region).exists()

    def listar(self) -> list[str]:
        """Devuelve las regiones con datos cacheados."""
        return [p.stem for p in self._dir.glob("*.json")]
