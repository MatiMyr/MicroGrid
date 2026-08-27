from __future__ import annotations

import math
from typing import Dict, List, Optional

from domain.epocas import EPOCA_POR_DEFECTO
from domain.tiempo import hora_del_dia


# Formas horarias características (factor 0..1 por hora del día, 24 valores).
# Sirven como fallback cuando no hay datos reales cacheados de CAMMESA.
_FORMAS_CARGA: Dict[str, List[float]] = {
    "residencial": [
        0.40, 0.35, 0.32, 0.30, 0.30, 0.35, 0.45, 0.60,
        0.65, 0.60, 0.55, 0.55, 0.60, 0.58, 0.55, 0.55,
        0.60, 0.70, 0.85, 1.00, 0.95, 0.80, 0.60, 0.48,
    ],
    "comercial": [
        0.30, 0.28, 0.27, 0.27, 0.28, 0.32, 0.45, 0.65,
        0.85, 0.95, 1.00, 1.00, 0.95, 0.98, 1.00, 0.98,
        0.92, 0.85, 0.75, 0.65, 0.55, 0.45, 0.38, 0.32,
    ],
    "industrial": [
        0.70, 0.68, 0.67, 0.67, 0.68, 0.72, 0.80, 0.90,
        0.98, 1.00, 1.00, 0.98, 0.95, 0.98, 1.00, 0.98,
        0.95, 0.90, 0.85, 0.82, 0.80, 0.78, 0.75, 0.72,
    ],
}


class ProfileBuilder:
    """Construye perfiles horarios de carga y de generación solar.

    Toma la demanda de CAMMESA (via ``JsonDemandaRepository``) y la irradiación
    de NASA POWER (via ``JsonIrradiacionRepository``) y las convierte en curvas
    horarias normalizadas (factor 0..1) listas para escalar cada elemento de la
    red hora a hora. Cuando no hay datos reales cacheados usa formas sintéticas
    características, de modo que la simulación funciona igual sin conexión.

    La hora del día de cada muestra se resuelve con ``domain.tiempo``, que
    normaliza a hora local argentina. Las dos fuentes vienen en husos distintos
    (NASA en UTC, CAMMESA en local): sin normalizar, el perfil solar quedaba
    corrido 3 horas respecto del de demanda.

    .. note::
       **La demanda de CAMMESA está aislada a propósito.** Su serie es la
       demanda *agregada de una región entera*, así que aplicarla a la red
       imponía una única curva a todas las cargas y dejaba sin efecto el tipo de
       consumidor de cada una — justo lo contrario de poder mezclar viviendas,
       comercios e industria en la misma red. El código queda intacto detrás de
       ``usar_demanda_real``: reactivarlo es cambiar ese flag y volver a habilitar
       el botón en el Dashboard, una vez que se decida cómo repartir una curva
       regional entre cargas individuales.
    """

    def __init__(self, demanda_repo=None, irradiacion_repo=None, usar_demanda_real: bool = False):
        self._demanda_repo = demanda_repo
        self._irradiacion_repo = irradiacion_repo
        # Interruptor explícito de la demanda de CAMMESA (ver la nota de clase).
        self._usar_demanda_real = usar_demanda_real

    # ---- carga -----------------------------------------------------------
    def build_load_profile(
        self, tipo: str = "residencial", horas: int = 24, region: Optional[str] = None
    ) -> List[float]:
        """Perfil de carga normalizado (0..1) por hora para un tipo de consumidor.

        Usa la forma sintética característica del ``tipo``. La demanda de CAMMESA
        solo se consulta si el constructor recibió ``usar_demanda_real=True`` y se
        pasa una ``region``; hoy nada la activa (ver la nota de clase).
        """
        forma = None
        if self._usar_demanda_real and region:
            forma = self._forma_desde_cammesa(region)
        if forma is None:
            forma = _FORMAS_CARGA.get(str(tipo).lower(), _FORMAS_CARGA["residencial"])
        return [forma[h % 24] for h in range(horas)]

    def _forma_desde_cammesa(self, region: str) -> Optional[List[float]]:
        if self._demanda_repo is None:
            return None
        serie = self._demanda_repo.cargar(region)
        if not serie:
            return None
        # Promedio de demanda por hora del día, normalizado al pico.
        suma = [0.0] * 24
        cuenta = [0] * 24
        for ts, valor in serie.items():
            hora = hora_del_dia(ts)
            if hora is None:
                continue
            suma[hora] += float(valor)
            cuenta[hora] += 1
        promedio = [suma[h] / cuenta[h] if cuenta[h] else 0.0 for h in range(24)]
        pico = max(promedio)
        if pico <= 0:
            return None
        return [v / pico for v in promedio]

    # ---- solar -----------------------------------------------------------
    def build_solar_profile(
        self,
        lat: float = -31.4,
        lon: float = -60.5,
        horas: int = 24,
        epoca: str = EPOCA_POR_DEFECTO,
        usar_nasa: bool = True,
    ) -> List[float]:
        """Perfil solar típico normalizado (0..1) por hora, para una época del año.

        Con ``usar_nasa`` usa la irradiación de NASA cacheada para esa ubicación
        y época —las ventanas de ~3 meses de los últimos años— y la promedia
        hora a hora del día: el resultado es el día típico de esa época, no el
        de una fecha puntual.

        Con ``usar_nasa=False`` —el modo básico del Dashboard— ni siquiera mira
        el caché: devuelve directamente la campana diurna sintética. Es el
        camino sin descargas ni ubicación, para ver el comportamiento de la red
        sin depender de una API externa. También es el respaldo cuando se pidió
        NASA pero no hay datos.
        """
        forma = self._forma_desde_nasa(lat, lon, epoca) if usar_nasa else None
        if forma is None:
            forma = self._campana_solar()
        return [forma[h % 24] for h in range(horas)]

    def _forma_desde_nasa(
        self, lat: float, lon: float, epoca: str = EPOCA_POR_DEFECTO
    ) -> Optional[List[float]]:
        if self._irradiacion_repo is None:
            return None
        serie = self._irradiacion_repo.cargar(lat, lon, epoca)
        if not serie:
            return None
        suma = [0.0] * 24
        cuenta = [0] * 24
        for ts, valor in serie.items():
            hora = hora_del_dia(ts)
            if hora is None:
                continue
            suma[hora] += max(0.0, float(valor))
            cuenta[hora] += 1
        promedio = [suma[h] / cuenta[h] if cuenta[h] else 0.0 for h in range(24)]
        pico = max(promedio)
        if pico <= 0:
            return None
        return [v / pico for v in promedio]

    @staticmethod
    def _campana_solar() -> List[float]:
        """Campana diurna: 0 antes de las 6 y después de las 20, pico a las 13."""
        forma = []
        for h in range(24):
            if 6 <= h <= 20:
                # media campana centrada en 13 h, ancho ~ 7 h
                valor = math.exp(-((h - 13) ** 2) / (2 * 3.5 ** 2))
            else:
                valor = 0.0
            forma.append(round(valor, 4))
        pico = max(forma) or 1.0
        return [v / pico for v in forma]
