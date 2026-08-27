"""Las dos fuentes externas se normalizan al mismo huso antes de armar perfiles.

NASA POWER entrega horas en UTC y CAMMESA en hora local argentina. Antes la hora
del día se sacaba cortando el string (``ts[11:13]``) sin mirar el huso, así que
el perfil solar quedaba corrido 3 horas respecto del de demanda: el pico de sol
caía a las 16 h locales.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from domain.profile_builder import ProfileBuilder
from domain.tiempo import ARG_TZ, a_local, desde_utc, hora_del_dia, iso_local


def test_utc_se_convierte_a_hora_local():
    assert hora_del_dia("2023-01-01T15:00:00+00:00") == 12


def test_un_timestamp_local_se_respeta():
    assert hora_del_dia("2023-01-01T15:00:00-03:00") == 15


def test_un_timestamp_sin_huso_se_asume_local():
    """Es lo que entrega CAMMESA y lo que quedó en las cachés viejas."""
    assert hora_del_dia("2023-01-01T15:00:00") == 15


def test_la_z_de_utc_tambien_se_entiende():
    assert hora_del_dia("2023-01-01T15:00:00Z") == 12


def test_un_timestamp_ilegible_devuelve_none():
    assert hora_del_dia("no es una fecha") is None
    assert hora_del_dia(None) is None


def test_nasa_se_guarda_en_hora_local():
    """La clave ``YYYYMMDDHH`` de NASA es UTC: 15 UTC son las 12 en Argentina."""
    assert iso_local(desde_utc(datetime.strptime("2023010115", "%Y%m%d%H"))) == \
        "2023-01-01T12:00:00-03:00"


def test_a_local_no_desplaza_lo_que_ya_es_local():
    dt = datetime(2023, 1, 1, 15, 0, tzinfo=ARG_TZ)

    assert a_local(dt) == dt


# ---- efecto sobre los perfiles --------------------------------------------
class _RepoFalso:
    """Repositorio en memoria que devuelve una serie fija."""

    def __init__(self, serie):
        self._serie = serie

    def cargar(self, *_args, **_kwargs):
        return self._serie


def test_el_pico_solar_cae_al_mediodia_local():
    """Serie en UTC con máximo a las 15 UTC -> pico a las 12 locales."""
    serie = {f"2023-01-01T{h:02d}:00:00+00:00": (100.0 if h == 15 else 10.0) for h in range(24)}
    builder = ProfileBuilder(irradiacion_repo=_RepoFalso(serie))

    perfil = builder.build_solar_profile(horas=24)

    assert perfil.index(max(perfil)) == 12


def test_la_demanda_de_cammesa_esta_aislada_por_defecto():
    """El tipo de consumidor manda: la serie regional de CAMMESA no lo pisa.

    Es el consumo agregado de una región entera, así que aplicarla imponía una
    única curva a toda la red y dejaba sin efecto el tipo de cada carga.
    """
    serie = {f"2023-01-01T{h:02d}:00:00-03:00": (100.0 if h == 3 else 10.0) for h in range(24)}
    builder = ProfileBuilder(demanda_repo=_RepoFalso(serie))

    residencial = builder.build_load_profile("residencial", 24, "LITORAL")
    comercial = builder.build_load_profile("comercial", 24, "LITORAL")

    assert residencial != comercial
    assert residencial.index(max(residencial)) != 3      # no siguió a CAMMESA


def test_el_pico_de_demanda_respeta_la_hora_local_si_se_reactiva_cammesa():
    """Con el flag explícito, la serie vuelve a usarse y su huso se respeta."""
    serie = {f"2023-01-01T{h:02d}:00:00-03:00": (100.0 if h == 20 else 10.0) for h in range(24)}
    builder = ProfileBuilder(demanda_repo=_RepoFalso(serie), usar_demanda_real=True)

    perfil = builder.build_load_profile("residencial", 24, "LITORAL")

    assert perfil.index(max(perfil)) == 20


def test_sin_datos_cacheados_cae_al_perfil_sintetico():
    builder = ProfileBuilder()

    solar = builder.build_solar_profile(horas=24)
    carga = builder.build_load_profile("residencial", horas=24)

    assert max(solar) == pytest.approx(1.0)
    assert solar[0] == 0.0 and solar[23] == 0.0      # de noche no hay sol
    assert max(carga) == pytest.approx(1.0)


def test_el_perfil_se_repite_ciclicamente_mas_alla_de_24_horas():
    builder = ProfileBuilder()

    perfil = builder.build_load_profile("residencial", horas=48)

    assert perfil[:24] == perfil[24:]
