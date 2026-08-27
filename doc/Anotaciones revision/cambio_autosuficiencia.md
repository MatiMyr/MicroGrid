# Cambio pendiente: recálculo de autosuficiencia

**Archivo:** `src/domain/simulation_engine.py` (método `_build_result`, líneas ~118-121)

## Problema

Hoy la autosuficiencia se calcula como:

```
autosuficiencia = solar / (consumo + pérdidas)
```

La batería no aparece en la fórmula. Como el motor simula **un instante (una hora) por vez**, de noche `solar = 0` → autosuficiencia = 0%, aunque el consumo esté 100% cubierto por una batería cargada con solar durante el día. Resultado incorrecto.

## Solución

Medir la autosuficiencia por lo que **NO** se importa de la red externa. Por conservación de energía:

```
aporte local     = (consumo + pérdidas) - importado de la red
autosuficiencia  = 1 - importado / (consumo + pérdidas)
```

Ventaja: la batería se maneja sola. Descargarla reduce el import (sube la autosuficiencia); cargarla desde la red aparece como import (la penaliza, porque esa energía no es local).

| Situación | Import de red | Autosuficiencia |
|---|---|---|
| Noche, consumo cubierto por batería | 0 | 100% |
| Día, solar cubre consumo + carga batería | 0 | 100% |
| Solar insuficiente, importa de la red | > 0 | < 100% |
| Carga la batería desde la red de noche | > 0 | penaliza |

## Diff propuesto

Reemplazar:

```python
autosufficiency_pct = 0.0
denominator = total_load_mw + total_losses_mw
if denominator > 0:
    autosufficiency_pct = min(solar_generation_mw / denominator * 100.0, 100.0)
```

por:

```python
# Importación desde la red externa (p_mw > 0 = la red alimenta la microgrid).
import_from_grid_mw = max(0.0, SimEngine._col_sum(ext_grid_results, "p_mw"))
autosufficiency_pct = 0.0
denominator = total_load_mw + total_losses_mw
if denominator > 0:
    local_supply_mw = denominator - import_from_grid_mw
    autosufficiency_pct = max(0.0, min(local_supply_mw / denominator * 100.0, 100.0))
```

## Notas

- `res_ext_grid.p_mw` ya se usa en la misma función (línea ~125, para el excedente exportado), el dato está disponible.
- Esto corrige el cálculo **por instante**. La autosuficiencia de un período completo se obtiene agregando las horas en el Dashboard (suma de importado vs. suma de consumo), y la fórmula es consistente en ambos niveles.
- Actualizar la nota de `doc/microgrid_arquitectura_archivos.md` (sección `simulation_engine.py`), que hoy dice `solar / (carga + pérdidas) * 100`.
