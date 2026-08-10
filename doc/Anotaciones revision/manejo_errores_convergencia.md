# Cambio pendiente: manejo de errores de convergencia (runpp / runopp)

**Archivo:** `src/domain/simulation_engine.py` (`runpp`, `runopp`, líneas ~14-27)

## Problema

Hoy `runopp`, si falla, **cae silenciosamente a `runpp`** y devuelve el resultado como si fuera un óptimo (`mode="opp"`). Además, si `runpp` **no converge**, nadie lo chequea: `_build_result` lee tablas `res_*` vacías o con una solución vieja y produce indicadores basura que parecen válidos. Dos fallas distintas quedan ocultas.

pandapower señala la no-convergencia lanzando `LoadflowNotConverged` o dejando `net["converged"] = False`. Hoy no se mira ninguno de los dos.

## Solución elegida

### `runpp` — si no converge, mensaje con el posible error
No hacer fallback. Detectar la no-convergencia y mostrar un mensaje que **sugiera la causa probable**. Implica definir un pequeño sistema de detección de errores por síntomas, p. ej.:

| Síntoma detectable en la red | Causa probable a informar |
|---|---|
| No hay `ext_grid` | Falta nodo slack / referencia de tensión |
| Buses sin camino al slack | Buses en isla (desconectados) |
| Cargabilidad/tensiones al límite antes de fallar | Colapso de tensión por sobrecarga |
| `std_type` incompatibles o faltantes | Parámetros de línea/trafo mal definidos |

El mensaje debe ser accionable: no solo "no convergió", sino la causa sospechada, para que sirva como ayuda de edición de la red.

### `runopp` — si falla, error explicativo + recomendación
No caer a `runpp`. Mostrar un error que explique **por qué** falla el flujo óptimo y recomiende correr `runpp` en su lugar.

Por qué falla `runopp` habitualmente: el OPF necesita más datos que el flujo simple —costos de generación, y límites (de tensión, de potencia, de cargabilidad) bien definidos. Si la red no los tiene o son inconsistentes, el óptimo no tiene problema que resolver y falla. `runpp` no necesita nada de eso, por eso suele converger donde `runopp` no.

## Notas

- La decisión "fallback o error" no debería vivir enterrada en el motor: el motor debería reportar honestamente qué pasó (convergió/no, óptimo/flujo) y dejar que la capa de arriba decida.
- Conviene una excepción de dominio propia (p. ej. `SimulacionNoConvergeError`) que suba hasta la UI con el mensaje, en vez de devolver un resultado inválido.
- Quitar el `mode="opp"` engañoso: hoy marca "opp" aunque por dentro haya corrido `runpp`.
