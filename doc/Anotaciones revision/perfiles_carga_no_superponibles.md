# Limitación: perfiles de carga vagos y no superponibles

**Archivos:** `src/domain/profile_builder.py` (`build_load_profile`, `_FORMAS_CARGA`, líneas ~9-54)
y `src/app/simulation_service.py` (`run_corrida` recibe **un** `tipo_carga`, línea ~82)

## Qué tan vaga es la implementación actual

- Los perfiles son **formas sintéticas hardcodeadas** de 24 valores (`residencial`, `comercial`,
  `industrial`) inventadas a mano, no calibradas con datos reales.
- Solo se usan datos reales de CAMMESA si hay caché para la región; si no, cae en la forma
  sintética. En la práctica hoy corre casi siempre con la curva inventada.
- La forma de CAMMESA (`_forma_desde_cammesa`) es un **promedio por hora del día normalizado al
  pico**: aplana estacionalidad, día de semana vs. fin de semana y variación entre días. Es una
  curva "típica" genérica, no la demanda del período que se simula.
- Se repite cíclicamente con `forma[h % 24]`: simular 72 h = el mismo día tres veces.

## Por qué no se pueden superponer distintos perfiles en una misma red

`run_corrida` recibe **un solo** `tipo_carga` y lo aplica con `apply_load_scaling`, que escribe
el mismo factor en **todas** las cargas (ver `limitacion_scaling_uniforme.md`). Es decir:

> toda la red comparte una única curva de carga por corrida.

No hay forma de que, en la misma red, una carga sea residencial y otra industrial con curvas
distintas: el perfil es un parámetro global de la corrida, no un atributo de cada carga.

## Dirección de solución (no implementar aún)

- Asociar un `tipo`/perfil **a cada carga** (atributo del elemento, elegido en el editor).
- Que `run_corrida` construya el factor **por carga** según su tipo y lo escriba por índice, en
  vez de un factor global. Comparte mecanismo con `limitacion_scaling_uniforme.md`, pero la causa
  es distinta (acá: falta modelar el tipo por elemento; allá: la escritura es a columna entera).
- Reemplazar las formas sintéticas por perfiles calibrados (o series reales fechadas de CAMMESA)
  cuando la precisión importe.

## Por qué se documenta aparte del scaling uniforme

Comparten síntoma (una sola curva para todo), pero se atienden por separado:
`limitacion_scaling_uniforme.md` es el **mecanismo** (cómo se escribe el factor); este es el
**modelo de datos** (falta el tipo de consumidor por carga y perfiles realistas).
