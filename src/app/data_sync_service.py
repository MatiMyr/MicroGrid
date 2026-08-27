from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

import requests

from domain import epocas as epocas_mod
from domain.tiempo import a_local, desde_utc, iso_local

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
    def _descargar_rango(self, lat: float, lon: float, start: str, end: str) -> dict:
        """Pide a NASA POWER un rango ``AAAAMMDD`` y devuelve la serie horaria.

        Devuelve ``{"ok": True, "serie": {...}}`` o ``{"ok": False, "error": ...}``:
        no toca el caché, de eso se ocupa quien lo llama.
        """
        for etiqueta, valor in (("start", start), ("end", end)):
            try:
                datetime.strptime(str(valor), "%Y%m%d")
            except ValueError:
                return {"ok": False, "error": f"Fecha {etiqueta} inválida: {valor!r} "
                                              f"(se espera AAAAMMDD)."}
        if str(start) > str(end):
            return {"ok": False, "error": f"El rango está invertido: {start} > {end}."}

        params = {
            "parameters": "ALLSKY_SFC_SW_DWN",
            "community": "RE",
            "latitude": lat,
            "longitude": lon,
            "start": start,
            "end": end,
            "format": "JSON",
            # Sin esto NASA POWER responde en LST (hora solar local, centrada en
            # el mediodía solar del punto): el código de abajo la interpretaba
            # como UTC y le restaba 3 h, corriendo todo el perfil solar unas
            # cuatro horas hacia la mañana. Pedirlo en UTC hace que la
            # conversión a hora argentina sea la correcta.
            "time-standard": "UTC",
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
            # clave: YYYYMMDDHH en UTC ; valor: W/m2 (-999 = faltante)
            if valor is None or float(valor) <= -900:
                valor = 0.0
            try:
                utc = datetime.strptime(clave, "%Y%m%d%H")
            except ValueError:
                continue
            # NASA POWER entrega horas UTC: se guarda en hora local argentina,
            # que es el huso en el que la simulación arma sus perfiles horarios.
            serie[iso_local(desde_utc(utc))] = float(valor)
        return {"ok": True, "serie": serie}

    def sync_nasa(
        self,
        lat: float,
        lon: float,
        epoca: str = epocas_mod.EPOCA_POR_DEFECTO,
        anios: int = epocas_mod.ANIOS_PROMEDIO,
    ) -> dict:
        """Descarga la irradiación típica de una ubicación para una época del año.

        Baja una ventana de ~3 meses centrada en la época por cada uno de los
        últimos ``anios`` años y las guarda juntas en el caché de esa
        ubicación/época: el promedio hora a hora de todas ellas es lo que después
        le da forma al perfil solar.

        Las ventanas se piden **en paralelo**: NASA POWER tarda del orden de tres
        minutos en servir 91 días horarios, así que en serie la primera corrida
        de cada época bloqueaba la UI casi diez. Son pedidos independientes a la
        misma API y el costo es un hilo por año.

        Basta con que una ventana llegue para considerar la descarga exitosa; si
        fallan todas se informa el error de la última sin propagar la excepción.
        """
        try:
            rangos = epocas_mod.ventanas(epoca, anios)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        with ThreadPoolExecutor(max_workers=len(rangos)) as pool:
            respuestas = list(pool.map(
                lambda r: self._descargar_rango(lat, lon, r[0], r[1]), rangos))

        serie: dict[str, float] = {}
        ventanas_ok = 0
        ultimo_error = ""
        for r in respuestas:
            if r.get("ok"):
                serie.update(r["serie"])
                ventanas_ok += 1
            else:
                ultimo_error = r.get("error", "error desconocido")

        if not serie:
            return {"ok": False, "registros": 0, "epoca": epoca,
                    "error": ultimo_error or "La respuesta de NASA POWER no trajo horas utilizables."}

        self.irradiacion_repo.guardar(lat, lon, serie, epoca)
        return {"ok": True, "registros": len(serie), "epoca": epoca,
                "anios": ventanas_ok, "anios_pedidos": len(rangos)}

    def asegurar_irradiacion(
        self,
        lat: float,
        lon: float,
        epoca: str = epocas_mod.EPOCA_POR_DEFECTO,
        anios: int = epocas_mod.ANIOS_PROMEDIO,
    ) -> dict:
        """Descarga la irradiación sólo si no está cacheada para ese punto y época.

        Igual que ``sync_simbench``, evita golpear la API en cada corrida: el
        caché se indexa por lat/lon/época, así que una vez bajada la serie se
        reutiliza. Para volver a descargarla hay que borrar el archivo del punto.
        """
        if self.irradiacion_repo.existe(lat, lon, epoca):
            return {"ok": True, "cacheada": True, "epoca": epoca}
        r = self.sync_nasa(lat, lon, epoca, anios)
        r["cacheada"] = False
        return r

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

        if not isinstance(registros, list):
            return {"ok": False, "error": "Respuesta inesperada de CAMMESA (no es una lista).",
                    "registros": 0}

        serie: dict[str, float] = {}
        descartados = 0
        for item in registros:
            if not isinstance(item, dict):
                descartados += 1
                continue
            fecha = item.get("fecha")
            dem = item.get("dem")
            if fecha is None or dem is None:
                descartados += 1
                continue
            try:
                # CAMMESA publica en hora local argentina; si el timestamp no
                # trae huso se interpreta como tal, no como UTC.
                ts = iso_local(a_local(datetime.fromisoformat(str(fecha).replace("Z", "+00:00"))))
            except ValueError:
                descartados += 1
                continue
            try:
                serie[ts] = float(dem)
            except (TypeError, ValueError):
                descartados += 1

        if not serie:
            # Sin esto la UI mostraba "éxito" cuando la API cambiaba de formato,
            # y la simulación seguía cayendo al perfil sintético en silencio.
            return {"ok": False, "registros": 0, "descartados": descartados,
                    "error": f"CAMMESA respondió {len(registros)} registros pero ninguno "
                             f"tenía los campos 'fecha'/'dem' esperados."}
        self.demanda_repo.guardar(region, serie)
        return {"ok": True, "registros": len(serie), "descartados": descartados}

    # ---- sincronización completa ----------------------------------------
    def sync_all(
        self,
        lat: float = -31.4,
        lon: float = -60.5,
        epoca: str = epocas_mod.EPOCA_POR_DEFECTO,
        region: str = "LITORAL",
        codigo_simbench: str = "1-LV-rural1--0-no_sw",
    ) -> dict:
        """Dispara la sincronización de las tres fuentes y devuelve un resumen."""
        return {
            "simbench": self.sync_simbench(codigo_simbench),
            "nasa": self.sync_nasa(lat, lon, epoca),
            "cammesa": self.sync_cammesa(region),
        }
