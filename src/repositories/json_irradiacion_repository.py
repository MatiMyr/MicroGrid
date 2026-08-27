from pathlib import Path
import json

from domain.epocas import EPOCA_POR_DEFECTO
from repositories.paths import CACHE_NASA_DIR


class JsonIrradiacionRepository:
    """Caché de irradiación solar de NASA POWER bajo ``data/cache/nasa/``.

    Los datos se organizan por ubicación **y época del año**. Cada archivo
    ``{lat}_{lon}_{epoca}.json`` es un mapa ``timestamp ISO -> irradiancia
    (W/m2)`` con las ventanas de ~3 meses de los últimos años ya descargadas.

    La época forma parte de la clave a propósito: el perfil solar de un invierno
    y el de un verano son series distintas para el mismo punto, y mezclarlas en
    un único archivo daría un promedio anual que no representa a ninguna.
    """

    def __init__(self, base_dir=None):
        self._dir = Path(base_dir) if base_dir else CACHE_NASA_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _clave(lat: float, lon: float, epoca: str = EPOCA_POR_DEFECTO) -> str:
        return f"{round(float(lat), 3)}_{round(float(lon), 3)}_{epoca}"

    def _path(self, lat: float, lon: float, epoca: str = EPOCA_POR_DEFECTO) -> Path:
        return self._dir / f"{self._clave(lat, lon, epoca)}.json"

    def guardar(
        self, lat: float, lon: float, serie: dict[str, float],
        epoca: str = EPOCA_POR_DEFECTO,
    ) -> None:
        """Agrega la serie de una ubicación/época al caché sin duplicar."""
        path = self._path(lat, lon, epoca)
        actual: dict[str, float] = {}
        if path.exists():
            with open(path, encoding="utf-8") as f:
                actual = json.load(f)
        actual.update({str(k): float(v) for k, v in serie.items()})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(actual, f, indent=2, sort_keys=True)

    def cargar(
        self, lat: float, lon: float, epoca: str = EPOCA_POR_DEFECTO
    ) -> dict[str, float]:
        """Devuelve la serie cacheada de una ubicación/época (vacío si no hay)."""
        path = self._path(lat, lon, epoca)
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def existe(self, lat: float, lon: float, epoca: str = EPOCA_POR_DEFECTO) -> bool:
        """Indica si hay datos cacheados para una ubicación/época."""
        return self._path(lat, lon, epoca).exists()

    def listar(self) -> list[str]:
        """Devuelve las claves ``lat_lon_epoca`` con datos cacheados."""
        return [p.stem for p in self._dir.glob("*.json")]
