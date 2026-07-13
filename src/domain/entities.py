from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class Bus:
    """Nodo eléctrico de la red."""

    index: Optional[int] = None
    vn_kv: float = 0.4
    name: Optional[str] = None
    type: str = "b"
    in_service: bool = True


@dataclass
class Line:
    """Línea entre dos buses."""

    from_bus: int
    to_bus: int
    length_km: float
    std_type: str = "NAYY 4x50 SE"
    name: Optional[str] = None
    df: float = 1.0
    parallel: int = 1
    in_service: bool = True


@dataclass
class Transformer:
    """Transformador de la red."""

    hv_bus: int
    lv_bus: int
    std_type: str = "0.4 MVA 20/0.4 kV"
    name: Optional[str] = None
    tap_pos: float = 0.0
    in_service: bool = True


@dataclass
class Load:
    """Carga conectada a un bus."""

    bus: int
    p_mw: float
    q_mvar: float = 0.0
    name: Optional[str] = None
    scaling: float = 1.0
    in_service: bool = True


@dataclass
class SolarPanel:
    """Panel solar representado como generación distribuida."""

    bus: int
    p_mw: float
    q_mvar: float = 0.0
    name: Optional[str] = None
    scaling: float = 1.0
    in_service: bool = True


@dataclass
class Battery:
    """Batería de almacenamiento conectada a un bus."""

    bus: int
    p_mw: float
    max_e_mwh: float
    q_mvar: float = 0.0
    soc_percent: float = 100.0
    name: Optional[str] = None
    scaling: float = 1.0
    in_service: bool = True


@dataclass
class ExternalGrid:
    """Fuente externa de alimentación para la red."""

    bus: int
    vm_pu: float = 1.0
    va_degree: float = 0.0
    name: Optional[str] = None
    in_service: bool = True


@dataclass
class SimulationResult:
    """Resultado de una simulación sobre una red."""

    mode: str
    total_losses_mw: float
    voltage_profile: Dict[int, float]
    line_loading_pct: Dict[int, float]
    autosufficiency_pct: float
    curtailment_solar_mw: float
    node_results: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    line_results: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    battery_soc_result: Dict[int, float] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    nombre_red: str = ""
    escenario: str = ""
