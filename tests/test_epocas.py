"""Épocas del año: ventanas a descargar, caché por época y perfil promediado."""
import threading
from datetime import date, datetime, timedelta

import pytest

from app.data_sync_service import DataSyncService
from domain import epocas
from domain.profile_builder import ProfileBuilder
from repositories.json_irradiacion_repository import JsonIrradiacionRepository


HOY = date(2026, 8, 27)


def _a_fecha(txt: str) -> date:
    return datetime.strptime(txt, "%Y%m%d").date()


# ---- definición de las épocas ---------------------------------------------
def test_hay_ocho_epocas_las_cuatro_estaciones_y_sus_intermedios():
    assert len(epocas.EPOCAS) == 8
    assert [c for c in epocas.EPOCAS] == [
        "verano", "verano_otono", "otono", "otono_invierno",
        "invierno", "invierno_primavera", "primavera", "primavera_verano",
    ]


def test_una_epoca_desconocida_no_pasa_en_silencio():
    with pytest.raises(ValueError):
        epocas.ventanas("otoninverno", hoy=HOY)


# ---- ventanas a descargar --------------------------------------------------
@pytest.mark.parametrize("epoca", list(epocas.EPOCAS))
def test_cada_ventana_cubre_tres_meses(epoca):
    for desde, hasta in epocas.ventanas(epoca, hoy=HOY):
        dias = (_a_fecha(hasta) - _a_fecha(desde)).days
        assert 85 <= dias <= 95        # ~3 meses


@pytest.mark.parametrize("epoca", list(epocas.EPOCAS))
def test_se_promedian_varios_anios_uno_por_ventana(epoca):
    ventanas = epocas.ventanas(epoca, anios=3, hoy=HOY)

    assert len(ventanas) == 3
    centros = [_a_fecha(d) + timedelta(days=epocas.SEMIVENTANA_DIAS) for d, _ in ventanas]
    # Una ventana por año, de la más reciente a la más vieja.
    assert [c.year for c in centros] == sorted({c.year for c in centros}, reverse=True)
    assert all((c.month, c.day) == epocas.EPOCAS[epoca][1] for c in centros)


@pytest.mark.parametrize("epoca", list(epocas.EPOCAS))
def test_ninguna_ventana_entra_en_el_tramo_que_nasa_no_publico(epoca):
    """NASA POWER tiene meses de demora: pedir fechas recientes devuelve huecos."""
    limite = HOY - timedelta(days=epocas.DEMORA_NASA_DIAS)

    for _, hasta in epocas.ventanas(epoca, hoy=HOY):
        assert _a_fecha(hasta) <= limite


def test_epocas_opuestas_no_se_solapan():
    """La ventana de verano no llega a tocar la de invierno: son días distintos."""
    def dias(epoca):
        d, h = epocas.ventanas(epoca, anios=1, hoy=HOY)[0]
        ini, fin = _a_fecha(d), _a_fecha(h)
        return {(ini + timedelta(days=k)).timetuple().tm_yday
                for k in range((fin - ini).days + 1)}

    assert not dias("verano") & dias("invierno")


# ---- caché por ubicación Y época ------------------------------------------
def test_la_epoca_forma_parte_de_la_clave_del_cache(tmp_path):
    """Verano e invierno del mismo punto son series distintas, no una mezclada."""
    repo = JsonIrradiacionRepository(base_dir=tmp_path)

    repo.guardar(-31.4, -60.5, {"2025-01-01T12:00:00-03:00": 900.0}, "verano")
    repo.guardar(-31.4, -60.5, {"2025-06-01T12:00:00-03:00": 300.0}, "invierno")

    assert repo.cargar(-31.4, -60.5, "verano") == {"2025-01-01T12:00:00-03:00": 900.0}
    assert repo.cargar(-31.4, -60.5, "invierno") == {"2025-06-01T12:00:00-03:00": 300.0}
    assert repo.existe(-31.4, -60.5, "verano")
    assert not repo.existe(-31.4, -60.5, "otono")


def test_el_perfil_solar_sale_de_la_epoca_pedida(tmp_path):
    """Mismo punto, distinta época -> distinto perfil."""
    repo = JsonIrradiacionRepository(base_dir=tmp_path)
    # Verano: pico a las 13. Invierno: pico a las 11.
    repo.guardar(-31.4, -60.5,
                 {f"2025-01-01T{h:02d}:00:00-03:00": (100.0 if h == 13 else 1.0)
                  for h in range(24)}, "verano")
    repo.guardar(-31.4, -60.5,
                 {f"2025-06-01T{h:02d}:00:00-03:00": (100.0 if h == 11 else 1.0)
                  for h in range(24)}, "invierno")
    builder = ProfileBuilder(irradiacion_repo=repo)

    verano = builder.build_solar_profile(-31.4, -60.5, 24, "verano")
    invierno = builder.build_solar_profile(-31.4, -60.5, 24, "invierno")

    assert verano.index(max(verano)) == 13
    assert invierno.index(max(invierno)) == 11


def test_el_perfil_promedia_los_anios_en_vez_de_seguir_a_uno(tmp_path):
    """Un año anómalo no manda: la forma es el promedio de los tres."""
    repo = JsonIrradiacionRepository(base_dir=tmp_path)
    serie = {}
    for anio, pico in ((2023, 12), (2024, 12), (2025, 9)):     # 2025 fue la anomalía
        for h in range(24):
            serie[f"{anio}-01-01T{h:02d}:00:00-03:00"] = 100.0 if h == pico else 1.0
    repo.guardar(-31.4, -60.5, serie, "verano")

    perfil = ProfileBuilder(irradiacion_repo=repo).build_solar_profile(
        -31.4, -60.5, 24, "verano")

    assert perfil.index(max(perfil)) == 12          # ganan los dos años normales
    assert perfil[9] > perfil[8]                    # pero la anomalía deja huella


# ---- descarga: una llamada por año, todo en un solo archivo ----------------
class _SyncEspia(DataSyncService):
    """Reemplaza la llamada a NASA por una serie sintética y anota los rangos."""

    def __init__(self, repo, fallar=()):
        super().__init__(irradiacion_repo=repo)
        self.pedidos = []
        self._fallar = set(fallar)
        self._lock = threading.Lock()

    def _descargar_rango(self, lat, lon, start, end):
        with self._lock:                       # se llaman en paralelo, un hilo por año
            self.pedidos.append((start, end))
        if start in self._fallar:
            return {"ok": False, "error": "boom"}
        return {"ok": True, "serie": {f"{start[:4]}-01-01T12:00:00-03:00": 500.0}}


def test_sync_nasa_baja_una_ventana_por_anio_y_las_junta(tmp_path):
    repo = JsonIrradiacionRepository(base_dir=tmp_path)
    svc = _SyncEspia(repo)

    r = svc.sync_nasa(-31.4, -60.5, "invierno", anios=3)

    assert r["ok"] and r["anios"] == 3 and r["epoca"] == "invierno"
    assert sorted(svc.pedidos) == sorted(epocas.ventanas("invierno", anios=3))
    assert len(repo.cargar(-31.4, -60.5, "invierno")) == 3


def test_si_falla_un_anio_se_usa_lo_que_llego(tmp_path):
    """La API se cae para un año: la época sigue siendo utilizable con el resto."""
    repo = JsonIrradiacionRepository(base_dir=tmp_path)
    primera = epocas.ventanas("verano", anios=3)[0][0]
    svc = _SyncEspia(repo, fallar={primera})

    r = svc.sync_nasa(-31.4, -60.5, "verano", anios=3)

    assert r["ok"] and r["anios"] == 2 and r["anios_pedidos"] == 3


def test_asegurar_irradiacion_no_vuelve_a_bajar_lo_cacheado(tmp_path):
    repo = JsonIrradiacionRepository(base_dir=tmp_path)
    svc = _SyncEspia(repo)

    primera = svc.asegurar_irradiacion(-31.4, -60.5, "otono")
    segunda = svc.asegurar_irradiacion(-31.4, -60.5, "otono")
    otra = svc.asegurar_irradiacion(-31.4, -60.5, "primavera")

    assert primera["cacheada"] is False
    assert segunda["cacheada"] is True
    assert otra["cacheada"] is False          # otra época sí se baja
    assert len(svc.pedidos) == 2 * epocas.ANIOS_PROMEDIO


# ---- huso horario de la fuente ---------------------------------------------
def test_la_irradiacion_se_pide_en_utc_no_en_hora_solar(monkeypatch, tmp_path):
    """El endpoint horario responde en LST salvo que se pida UTC explícitamente.

    Sin el parámetro, NASA devuelve hora solar local —centrada en el mediodía
    solar del punto— y el conversor a hora argentina le restaba 3 h igual, con
    lo que el perfil solar quedaba corrido unas cuatro horas a la mañana: el
    pico caía a las 9 en vez de las 13.
    """
    capturado = {}

    class _Resp:
        @staticmethod
        def raise_for_status():
            pass

        @staticmethod
        def json():
            return {"properties": {"parameter": {"ALLSKY_SFC_SW_DWN": {"2025061615": 500.0}}}}

    def _get(url, params=None, timeout=None):
        capturado.update(params or {})
        return _Resp()

    monkeypatch.setattr("app.data_sync_service.requests.get", _get)
    svc = DataSyncService(irradiacion_repo=JsonIrradiacionRepository(base_dir=tmp_path))

    r = svc._descargar_rango(-31.4, -60.5, "20250615", "20250617")

    assert capturado["time-standard"] == "UTC"
    # 15 UTC son las 12 en Argentina: la conversión sigue siendo la de siempre.
    assert list(r["serie"]) == ["2025-06-16T12:00:00-03:00"]


# ---- modo básico: campana sintética, sin tocar NASA ------------------------
def test_sin_configuracion_avanzada_no_se_mira_el_cache(tmp_path):
    """El modo básico ignora la irradiación real aunque esté descargada."""
    repo = JsonIrradiacionRepository(base_dir=tmp_path)
    # Serie con un pico a las 9: si el perfil la usara, se notaría.
    repo.guardar(-31.4, -60.5,
                 {f"2025-06-01T{h:02d}:00:00-03:00": (100.0 if h == 9 else 1.0)
                  for h in range(24)}, "invierno")
    builder = ProfileBuilder(irradiacion_repo=repo)

    basico = builder.build_solar_profile(-31.4, -60.5, 24, "invierno", usar_nasa=False)
    avanzado = builder.build_solar_profile(-31.4, -60.5, 24, "invierno", usar_nasa=True)

    assert avanzado.index(max(avanzado)) == 9        # sigue a los datos reales
    assert basico.index(max(basico)) == 13           # campana sintética
    assert basico == builder._campana_solar()


def test_el_modo_basico_no_depende_de_haber_descargado_nada():
    """Sin repositorio de irradiación siquiera, el perfil básico funciona."""
    perfil = ProfileBuilder().build_solar_profile(usar_nasa=False)

    assert len(perfil) == 24
    assert max(perfil) == pytest.approx(1.0)
    assert perfil[0] == 0.0 and perfil[23] == 0.0
