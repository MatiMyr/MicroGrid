"""Manejo de tiempo local argentino para las series de datos externos.

Las dos fuentes externas del proyecto vienen en husos distintos: NASA POWER
entrega sus timestamps horarios en **UTC**, y CAMMESA en **hora local
argentina**. Antes, ambas series se guardaban tal como llegaban y la hora del día
se extraía cortando el string (``ts[11:13]``), sin mirar el huso. Resultado: el
perfil solar quedaba corrido 3 horas respecto del de demanda, y el pico de sol
aparecía a las 16 h locales en vez del mediodía.

Todo lo que se persiste en la caché se normaliza a hora local argentina, que es
el huso en el que se interpretan los perfiles horarios de la simulación.

Se usa un offset fijo de UTC-3 en vez de ``zoneinfo``: Argentina no aplica
horario de verano desde 2009, así que el offset es constante para todo el rango
de datos que maneja el proyecto, y evita depender del paquete ``tzdata`` (que en
Windows hace falta porque el sistema no trae base de datos de husos).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

# Hora oficial argentina: UTC-3 fijo, sin horario de verano.
ARG_TZ = timezone(timedelta(hours=-3))


def a_local(dt: datetime) -> datetime:
    """Lleva un ``datetime`` a hora local argentina.

    Un ``datetime`` sin huso se interpreta como **ya local**: es lo que entrega
    CAMMESA y lo que quedó guardado en las cachés viejas del proyecto.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ARG_TZ)
    return dt.astimezone(ARG_TZ)


def desde_utc(dt: datetime) -> datetime:
    """Interpreta un ``datetime`` sin huso como UTC y lo pasa a hora local."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ARG_TZ)


def iso_local(dt: datetime) -> str:
    """Serializa a ISO 8601 en hora local argentina (con el offset explícito)."""
    return a_local(dt).isoformat()


def hora_del_dia(timestamp: str) -> Optional[int]:
    """Devuelve la hora local (0-23) de un timestamp ISO, o ``None`` si no parsea.

    Acepta tanto los timestamps nuevos (con offset explícito) como los viejos sin
    huso que puedan quedar en la caché, para no invalidar lo ya descargado.
    """
    try:
        dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return a_local(dt).hour
