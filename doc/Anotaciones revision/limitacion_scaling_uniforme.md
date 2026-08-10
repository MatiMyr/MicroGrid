# Limitación: el scaling se aplica uniforme a toda la red

**Archivos:** `src/domain/network_model.py` (`apply_load_scaling`, `apply_sgen_scaling`, líneas ~122-130) y `src/app/simulation_service.py` (loop de `run_corrida`, líneas ~109-113)

## Problema

Cada hora del loop aplica **un único factor** a *todas* las cargas y otro a *todos* los sgen:

```python
self.net.load["scaling"] = float(factor)   # una sola escritura → toda la columna
self.net.sgen["scaling"] = float(factor)
```

Asignar un escalar a la columna de pandas rellena todas las filas de golpe. No hay un factor por elemento: son 2 escrituras por hora sin importar cuántos elementos tenga la red.

Consecuencia física: **la red se asume espacialmente homogénea**. Todos los paneles reciben la misma irradiación en la misma hora, y todas las cargas el mismo factor.

En una red con distancias grandes esto es incorrecto: dos puntos alejados pueden tener irradiación distinta (nubosidad, hora solar local, orientación) y deberían escalar con perfiles solares diferentes. Hoy no se puede.

## Alcance / a quién afecta

- **Solar (sgen):** redes geográficamente extensas donde la radiación varía entre nodos.
- **Carga (load):** ver `perfiles_carga_no_superponibles.md` (mismo síntoma, causa distinta; se documenta aparte a propósito).

## Dirección de solución (no implementar aún)

Pasar de "un factor global" a "un factor por elemento". Opciones:

- Escritura por índice: `scaling` como `dict {index -> factor}`, escribiendo fila por fila (`net.sgen.at[idx, "scaling"] = ...`), con el perfil resuelto según la posición/zona del nodo.
- O migrar a `pandapower.timeseries` (`ConstControl` + `DataSource`), donde cada elemento tiene su propia serie y el perfil deja de vivir dentro de la red.

## Nota relacionada

El `scaling` se **persiste** con `pp.to_json` (es una columna de la red). Si se guarda la red después de simular, queda con el `scaling` de la última hora en vez de `1.0`. Otro motivo para sacar el perfil de adentro de la red.
