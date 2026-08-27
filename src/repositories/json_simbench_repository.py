from pathlib import Path

import pandapower as pp

from repositories.paths import SIMBENCH_DIR


class JsonSimbenchRepository:
    """Caché local de redes base de SimBench bajo ``data/redes/simbench/``.

    Las redes SimBench son de referencia: se identifican por su código de
    benchmark (no por un id/nombre editable por el usuario) y no se sobrescriben
    en runtime. Se serializan con ``pp.to_json`` / ``pp.from_json``, igual que
    ``json_net_repository.py``.
    """

    def __init__(self, base_dir=None):
        self._dir = Path(base_dir) if base_dir else SIMBENCH_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, codigo: str) -> Path:
        # El código de benchmark trae caracteres ('--') seguros para nombre de archivo.
        return self._dir / f"{codigo}.json"

    def existe(self, codigo: str) -> bool:
        """Indica si la red base ``codigo`` ya está cacheada localmente."""
        return self._path(codigo).exists()

    def guardar(self, codigo: str, red) -> None:
        """Persiste una red SimBench nueva traída del paquete.

        No sobrescribe una red ya cacheada: las redes de referencia son
        inmutables en runtime.
        """
        path = self._path(codigo)
        if path.exists():
            return
        pp.to_json(red, path)

    def cargar(self, codigo: str):
        """Devuelve la red base cacheada; lanza ``FileNotFoundError`` si no existe."""
        path = self._path(codigo)
        if not path.exists():
            raise FileNotFoundError(f"Red SimBench no cacheada: {codigo}")
        return pp.from_json(path)

    def listar(self) -> list[str]:
        """Devuelve los códigos de benchmark de todas las redes cacheadas."""
        return [p.stem for p in self._dir.glob("*.json")]
