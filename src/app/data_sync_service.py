from __future__ import annotations

from datetime import datetime
from typing import Optional

import requests

from repositories.json_demanda_repository import JsonDemandaRepository
from repositories.json_irradiacion_repository import JsonIrradiacionRepository
from repositories.json_simbench_repository import JsonSimbenchRepository


# Regiones de demanda de CAMMESA (id_region de su API pública).
CAMMESA_REGIONES = {
    "GBA": 1002,
    "LITORAL": 1005,
    "CENTRO": 1007,
    "NEA": 1008,
    "NOA": 1009,
    "CUYO": 1010,
    "COMAHUE": 1011,
    "PATAGONIA": 1012,
}

NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
CAMMESA_DEMANDA_URL = "https://api.cammesa.com/demanda-svc/demanda/RegionDemanda"


class DataSyncService:
    """Mantiene actualizados los datos externos (CAMMESA, NASA, SimBench).

    Se conecta a las fuentes externas, descarga lo que aún no está en el caché
    local y lo persiste en los repositorios correspondientes. Puede correrse
    automáticamente según un horario o dispararse a mano desde la UI. Cada método
    devuelve la cantidad de registros nuevos guardados y nunca lanza por errores
    de red: informa el problema en el valor de retorno para no bloquear la UI.
    """

    def __init__(
        self,
        demanda_repo: Optional[JsonDemandaRepository] = None,
        irradiacion_repo: Optional[JsonIrradiacionRepository] = None,
        simbench_repo: Optional[JsonSimbenchRepository] = None,
        timeout: int = 30,
    ):
        self.demanda_repo = demanda_repo or JsonDemandaRepository()
        self.irradiacion_repo = irradiacion_repo or JsonIrradiacionRepository()
        self.simbench_repo = simbench_repo or JsonSimbenchRepository()
        self.timeout = timeout

    # ---- SimBench --------------------------------------------------------
    def sync_simbench(self, codigo: str = "1-LV-rural1--0-no_sw") -> dict:
        """Trae del paquete SimBench la red base ``codigo`` si no está cacheada."""
        if self.simbench_repo.existe(codigo):
            return {"ok": True, "cacheada": True, "codigo": codigo}
        try:
            import simbench as sb

            net = sb.get_simbench_net(codigo)
            self.simbench_repo.guardar(codigo, net)
            return {"ok": True, "cacheada": False, "codigo": codigo}
        except Exception as exc:  # noqa: BLE001 - se reporta, no se propaga
            return {"ok": False, "error": str(exc), "codigo": codigo}

    # ---- NASA POWER ------------------------------------------------------
    def sync_nasa(
        self, lat: float, lon: float, start: str, end: str
    ) -> dict:
        """Descarga irradiación horaria de NASA POWER para una ubicación/período.

        ``start`` y ``end`` en formato ``YYYYMMDD``. Guarda la serie
        ``timestamp ISO -> W/m2`` en el repositorio de irradiación.
        """
        params = {
            "parameters": "ALLSKY_SFC_SW_DWN",
            "community": "RE",
            "latitude": lat,
            "longitude": lon,
            "start": start,
            "end": end,
            "format": "JSON",
        }
        try:
            resp = requests.get(NASA_POWER_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            crudo = data["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

        serie: dict[str, float] = {}
        for clave, valor in crudo.items():
            # clave: YYYYMMDDHH ; valor: W/m2 (-999 = faltante)
            if valor is None or float(valor) <= -900:
                valor = 0.0
            try:
                ts = datetime.strptime(clave, "%Y%m%d%H").isoformat()
            except ValueError:
                continue
            serie[ts] = float(valor)

        self.irradiacion_repo.guardar(lat, lon, serie)
        return {"ok": True, "registros": len(serie)}

    # ---- CAMMESA ---------------------------------------------------------
    def sync_cammesa(self, region: str = "GBA") -> dict:
        """Descarga la demanda de CAMMESA para una región y la cachea.

        Usa la API pública de demanda de CAMMESA. Ante cualquier error de red o
        formato devuelve ``ok=False`` sin propagar la excepción.
        """
        id_region = CAMMESA_REGIONES.get(region.upper())
        if id_region is None:
            return {"ok": False, "error": f"Región desconocida: {region}"}
        try:
            resp = requests.get(
                CAMMESA_DEMANDA_URL,
                params={"id_region": id_region},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            registros = resp.json()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

        serie: dict[str, float] = {}
        for item in registros:
            fecha = item.get("fecha")
            dem = item.get("dem")
            if fecha is None or dem is None:
                continue
            try:
                ts = datetime.fromisoformat(str(fecha).replace("Z", "+00:00")).isoformat()
            except ValueError:
                ts = str(fecha)
            serie[ts] = float(dem)

        if serie:
            self.demanda_repo.guardar(region, serie)
        return {"ok": True, "registros": len(serie)}

    # ---- sincronización completa ----------------------------------------
    def sync_all(
        self,
        lat: float = -31.4,
        lon: float = -60.5,
        start: str = "20230101",
        end: str = "20230107",
        region: str = "LITORAL",
        codigo_simbench: str = "1-LV-rural1--0-no_sw",
    ) -> dict:
        """Dispara la sincronización de las tres fuentes y devuelve un resumen."""
        return {
            "simbench": self.sync_simbench(codigo_simbench),
            "nasa": self.sync_nasa(lat, lon, start, end),
            "cammesa": self.sync_cammesa(region),
        }
