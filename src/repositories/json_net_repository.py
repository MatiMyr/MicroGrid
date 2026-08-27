from pathlib import Path
import json
import uuid

import pandapower as pp

from repositories.paths import REDES_DIR


class NombreDuplicadoError(Exception):
    """Se intentó guardar una red con un nombre que ya está en uso."""


class JsonRedRepository:
    """Guarda y recupera configuraciones de red bajo ``data/redes/``.

    Cada red tiene dos identificadores con roles distintos:

    - **Id estable**: se asigna una sola vez al guardar por primera vez y nunca
      cambia. Es lo que ``SimulationResult`` y cualquier otro dato usan para
      referenciar "qué red se usó" — nunca el nombre.
    - **Nombre editable**: la etiqueta que el usuario ve y puede cambiar. Se usa
      para la UI y para validar colisiones (dos redes no pueden mostrarse con el
      mismo nombre), pero no es la clave interna de referencia.

    En disco cada red vive en ``{id}.json`` (la red serializada con
    ``pp.to_json``) y el mapa ``id -> nombre`` en ``_index.json``.
    """

    def __init__(self, base_dir=None):
        self._dir = Path(base_dir) if base_dir else REDES_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "_index.json"

    # ---- índice id -> nombre --------------------------------------------
    def _leer_index(self) -> dict[str, str]:
        if not self._index_path.exists():
            return {}
        with open(self._index_path, encoding="utf-8") as f:
            return json.load(f)

    def _escribir_index(self, index: dict[str, str]) -> None:
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    def _id_por_nombre(self, nombre: str) -> str | None:
        for red_id, nom in self._leer_index().items():
            if nom == nombre:
                return red_id
        return None

    # ---- API pública -----------------------------------------------------
    def guardar(self, nombre: str, red) -> str:
        """Guarda una red nueva bajo un id estable recién asignado.

        Lanza ``NombreDuplicadoError`` si ``nombre`` ya existe, en vez de
        sobrescribir en silencio. Devuelve el id estable asignado.
        """
        index = self._leer_index()
        if nombre in index.values():
            raise NombreDuplicadoError(f"Ya existe una red con el nombre '{nombre}'")
        red_id = uuid.uuid4().hex
        pp.to_json(red, self._dir / f"{red_id}.json")
        index[red_id] = nombre
        self._escribir_index(index)
        return red_id

    def actualizar(self, red_id: str, red) -> None:
        """Sobrescribe la topología de una red ya existente (mismo id/nombre)."""
        if red_id not in self._leer_index():
            raise FileNotFoundError(f"Red no encontrada: {red_id}")
        pp.to_json(red, self._dir / f"{red_id}.json")

    def renombrar(self, red_id: str, nuevo_nombre: str) -> None:
        """Cambia el nombre editable de una red. El id no se toca.

        Lanza ``NombreDuplicadoError`` si otro red distinto ya usa ese nombre.
        """
        index = self._leer_index()
        if red_id not in index:
            raise FileNotFoundError(f"Red no encontrada: {red_id}")
        for otro_id, nom in index.items():
            if nom == nuevo_nombre and otro_id != red_id:
                raise NombreDuplicadoError(f"Ya existe una red con el nombre '{nuevo_nombre}'")
        index[red_id] = nuevo_nombre
        self._escribir_index(index)

    def cargar(self, red_id: str):
        """Lee la red por su id estable; lanza ``FileNotFoundError`` si no existe."""
        path = self._dir / f"{red_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Red no encontrada: {red_id}")
        return pp.from_json(path)

    def cargar_por_nombre(self, nombre: str):
        """Conveniencia para la UI: carga una red por su nombre visible."""
        red_id = self._id_por_nombre(nombre)
        if red_id is None:
            raise FileNotFoundError(f"Red no encontrada: {nombre}")
        return self.cargar(red_id)

    def nombre_de(self, red_id: str) -> str | None:
        """Devuelve el nombre editable asociado a un id, o ``None``."""
        return self._leer_index().get(red_id)

    def listar(self) -> list[dict]:
        """Devuelve ``[{id, nombre}, ...]`` para todas las redes guardadas."""
        return [{"id": red_id, "nombre": nom} for red_id, nom in self._leer_index().items()]

    def eliminar(self, red_id: str) -> None:
        """Elimina una red y su entrada del índice."""
        index = self._leer_index()
        if red_id not in index:
            raise FileNotFoundError(f"Red no encontrada: {red_id}")
        (self._dir / f"{red_id}.json").unlink(missing_ok=True)
        del index[red_id]
        self._escribir_index(index)
