"""Épocas del año: las 8 ventanas típicas del perfil solar.

El perfil solar ya no se pide por un rango de fechas arbitrario sino por una
**época del año**: las cuatro estaciones del hemisferio sur más los cuatro
puntos intermedios. Cada época es una ventana de ~3 meses centrada en su fecha
de referencia (solsticios, equinoccios y los puntos medios entre ellos), y la
irradiación que la representa es el promedio hora a hora de esa misma ventana a
lo largo de los últimos años.

Promediar varios años es lo que vuelve al perfil *típico* en vez de la foto de
un año puntual: un invierno anómalamente nublado deja de dominar la forma de la
curva. Y promediar 3 meses en vez de una semana suaviza el clima del día sin
mezclar estaciones: la ventana no llega a tocar la época opuesta.
"""
from __future__ import annotations

from datetime import date, timedelta

# Fecha de referencia (mes, día) de cada época, hemisferio sur.
# Los solsticios y equinoccios caen en su fecha astronómica aproximada; los
# intermedios, en el punto medio entre los dos que los rodean.
EPOCAS: dict[str, tuple[str, tuple[int, int]]] = {
    "verano":             ("Verano",             (12, 21)),
    "verano_otono":       ("Verano–Otoño",       (2, 4)),
    "otono":              ("Otoño",              (3, 21)),
    "otono_invierno":     ("Otoño–Invierno",     (5, 6)),
    "invierno":           ("Invierno",           (6, 21)),
    "invierno_primavera": ("Invierno–Primavera", (8, 7)),
    "primavera":          ("Primavera",          (9, 23)),
    "primavera_verano":   ("Primavera–Verano",   (11, 7)),
}

EPOCA_POR_DEFECTO = "verano"

# Media ventana: 45 días a cada lado del centro son los ~3 meses pedidos.
SEMIVENTANA_DIAS = 45

# Cuántos años hacia atrás se promedian.
ANIOS_PROMEDIO = 3

# NASA POWER publica con varios meses de demora: pedir fechas más recientes que
# esto devuelve huecos. Se descuenta del "hoy" para elegir el año más reciente
# que tiene la ventana completa.
DEMORA_NASA_DIAS = 120


def etiqueta(epoca: str) -> str:
    """Nombre legible de una época (la clave misma si es desconocida)."""
    definicion = EPOCAS.get(epoca)
    return definicion[0] if definicion else str(epoca)


def opciones() -> list[dict]:
    """Opciones para el desplegable de la UI, en orden de estaciones."""
    return [{"label": nombre, "value": clave} for clave, (nombre, _) in EPOCAS.items()]


def ventanas(
    epoca: str, anios: int = ANIOS_PROMEDIO, hoy: date | None = None
) -> list[tuple[str, str]]:
    """Ventanas ``(desde, hasta)`` en formato ``AAAAMMDD`` a promediar.

    Devuelve ``anios`` ventanas de ~3 meses centradas en la fecha de referencia
    de la época, una por año, de la más reciente a la más vieja. La más reciente
    es la última cuya ventana termina antes del horizonte que NASA POWER ya
    publicó, así ninguna llega incompleta.
    """
    if epoca not in EPOCAS:
        raise ValueError(
            f"Época desconocida: {epoca!r} (esperada una de {sorted(EPOCAS)})."
        )
    if anios < 1:
        raise ValueError(f"Hay que promediar al menos un año, se pidieron {anios}.")

    _, (mes, dia) = EPOCAS[epoca]
    limite = (hoy or date.today()) - timedelta(days=DEMORA_NASA_DIAS)

    # Año del centro más reciente cuya ventana entera cae antes del límite.
    anio = limite.year
    while date(anio, mes, dia) + timedelta(days=SEMIVENTANA_DIAS) > limite:
        anio -= 1

    salida = []
    for k in range(anios):
        centro = date(anio - k, mes, dia)
        desde = centro - timedelta(days=SEMIVENTANA_DIAS)
        hasta = centro + timedelta(days=SEMIVENTANA_DIAS)
        salida.append((desde.strftime("%Y%m%d"), hasta.strftime("%Y%m%d")))
    return salida
