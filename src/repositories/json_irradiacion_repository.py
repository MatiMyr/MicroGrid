from pathlib import Path
import json


class JsonIrradiacionRepository:
    """Caché de irradiación solar de NASA POWER bajo ``data/cache/nasa/``.

    Los datos se organizan por ubicación geográfica. Cada archivo
    ``{lat}_{lon}.json`` es un mapa ``timestamp ISO -> irradiancia (W/m2)``.
    """

    def __init__(self, base_dir: str = "data/cache/nasa"):
        self._dir = Path(base_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _clave(lat: float, lon: float) -> str:
        return f"{round(float(lat), 3)}_{round(float(lon), 3)}"

    def _path(self, lat: float, lon: float) -> Path:
        return self._dir / f"{self._clave(lat, lon)}.json"

    def guardar(self, lat: float, lon: float, serie: dict[str, float]) -> None:
        """Agrega la serie de irradiación de una ubicación al caché sin duplicar."""
        path = self._path(lat, lon)
        actual: dict[str, float] = {}
        if path.exists():
            with open(path, encoding="utf-8") as f:
                actual = json.load(f)
        actual.update({str(k): float(v) for k, v in serie.items()})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(actual, f, indent=2, sort_keys=True)

    def cargar(self, lat: float, lon: float) -> dict[str, float]:
        """Devuelve la serie de irradiación cacheada de una ubicación (vacío si no hay)."""
        path = self._path(lat, lon)
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def existe(self, lat: float, lon: float) -> bool:
        """Indica si hay datos cacheados para una ubicación."""
        return self._path(lat, lon).exists()

    def listar(self) -> list[str]:
        """Devuelve las claves de ubicación con datos cacheados."""
        return [p.stem for p in self._dir.glob("*.json")]
