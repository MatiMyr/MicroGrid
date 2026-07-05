from pathlib import Path
import pandapower as pp


class JsonRedRepository:
    def __init__(self, base_dir: str = "data/redes"):
        self._dir = Path(base_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def guardar(self, nombre: str, red) -> None:
        """Serializa la red pandapower a JSON y la guarda en disco."""
        pp.to_json(red, self._dir / f"{nombre}.json")

    def cargar(self, nombre: str):
        """Lee el JSON y devuelve la red pandapower; lanza FileNotFoundError si no existe."""
        path = self._dir / f"{nombre}.json"
        if not path.exists():
            raise FileNotFoundError(f"Red no encontrada: {path}")
        return pp.from_json(path)

    def listar(self) -> list[str]:
        """Devuelve los nombres de todas las redes guardadas, sin extensión."""
        return [p.stem for p in self._dir.glob("*.json")]
