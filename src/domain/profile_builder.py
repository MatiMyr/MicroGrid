from __future__ import annotations

import math
from typing import Dict, List, Optional


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
    """

    def __init__(self, demanda_repo=None, irradiacion_repo=None):
        self._demanda_repo = demanda_repo
        self._irradiacion_repo = irradiacion_repo

    # ---- carga -----------------------------------------------------------
    def build_load_profile(
        self, tipo: str = "residencial", horas: int = 24, region: str = "GBA"
    ) -> List[float]:
        """Perfil de carga normalizado (0..1) por hora para un tipo de consumidor.

        Si hay demanda de CAMMESA cacheada para ``region``, usa su forma horaria
        promedio; si no, cae en la forma sintética característica del ``tipo``.
        """
        forma = self._forma_desde_cammesa(region)
        if forma is None:
            forma = _FORMAS_CARGA.get(tipo.lower(), _FORMAS_CARGA["residencial"])
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
            try:
                hora = int(ts[11:13])
            except (ValueError, IndexError):
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
        self, lat: float = -31.4, lon: float = -60.5, horas: int = 24
    ) -> List[float]:
        """Perfil solar normalizado (0..1) por hora.

        Usa la irradiación de NASA cacheada para la ubicación; si no hay datos,
        genera una campana diurna sintética (0 de noche, pico al mediodía).
        """
        forma = self._forma_desde_nasa(lat, lon)
        if forma is None:
            forma = self._campana_solar()
        return [forma[h % 24] for h in range(horas)]

    def _forma_desde_nasa(self, lat: float, lon: float) -> Optional[List[float]]:
        if self._irradiacion_repo is None:
            return None
        serie = self._irradiacion_repo.cargar(lat, lon)
        if not serie:
            return None
        suma = [0.0] * 24
        cuenta = [0] * 24
        for ts, valor in serie.items():
            try:
                hora = int(ts[11:13])
            except (ValueError, IndexError):
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
