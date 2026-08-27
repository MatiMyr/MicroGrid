# Correcciones de agosto de 2026

Resultado de una revisión completa del proyecto. Se distingue de
`doc/Anotaciones revision/`, que documenta cambios **pendientes**: esto es lo que
ya se arregló, con el motivo y cómo quedó verificado.

Los arreglos están cubiertos por `tests/` (81 tests, `pytest tests` desde la raíz).

## Validación de las salidas

Además de fijar el comportamiento de los arreglos, se verificó que lo que el
proyecto **reporta** sea la física correcta, contra referencias independientes
del propio código (`tests/test_validacion_fisica.py`):

| Escenario | Referencia | Resultado |
|---|---|---|
| Línea resistiva de 2 buses, 4 combinaciones de largo/carga | solución analítica cerrada `v2 = (v1 + raiz(v1²-4pR))/2` | tensión y pérdidas coinciden con error relativo ≤ 1e-7 |
| Pérdidas vs. carga | ley cuadrática | razón 4.18 y 4.42 al duplicar (>4 porque baja la tensión) |
| Conservación de potencia activa | `red + solar = consumo + baterías + pérdidas` | residuo ≤ 4e-11 MW en las 5 redes SimBench, la red de ejemplo y las 2 redes guardadas |
| Indicadores del proyecto | lectura directa de las tablas `res_*` de pandapower | identidad exacta (pérdidas, V mín, cargabilidad, excedente) |
| Caída de tensión en red radial | sin generación distribuida, ningún bus supera a su padre | 0 violaciones sobre hasta 1455 tramos por red |
| Tensión mínima horaria | debe ser imagen espejo del perfil de carga | correlación −0.9999 y misma hora pico en las 5 redes |
| Corrida repetida | determinismo y reuso de caché | 0 instantes nuevos, resultados idénticos hora por hora |
| KPIs del Dashboard (`1-LV-urban6`, 24 h) | corrida calculada aparte | coinciden en las 24 horas, más el recorte de hora fuera de rango |

Tres aparentes desviaciones resultaron ser expectativas mal formuladas, no fallas:

1. **La tensión no siempre baja al alejarse del slack.** Con la PV encendida
   sube hacia los nodos con paneles (13/46 tramos en `rural1`, 208/1455 en
   `rural2`). Es la sobretensión por generación distribuida, un fenómeno real de
   redes de BT. Apagando los `sgen`, la monotonía se cumple sin excepción.
2. **La tensión mínima sigue la demanda neta, no la bruta** (correlación −0.87
   contra −0.39). Y ni siquiera la neta agregada alcanza cuando la PV está
   concentrada en un bus: lo que manda es el flujo local del camino al bus más
   débil.
3. **La batería queda en 100 % durante 22 de 24 horas** y sigue consumiendo
   10 kW del flujo sin que el SoC cambie. Es la limitación ya documentada en
   `Anotaciones revision/simplificacion_battery_soc.md` ("potencia no ligada al
   SoC" + "energía sobrante desaparece"): `runpp` trata la batería como
   inyección fija y no conoce `max_e_mwh`. No es una regresión, pero conviene
   tenerlo presente al leer el SoC de una corrida larga.

No se pudo ejercitar el widget del slider de hora desde el navegador headless
(el panel no renderiza y los eventos de teclado no llegan a la página, verificado
con un `input type=number` nativo como control). La selección de hora se validó
llamando directamente al callback del Dashboard.

---

## Críticos

### 1. El signo de la potencia de batería estaba invertido

**Archivos:** `src/domain/simulation_engine.py`, `src/domain/entities.py`

pandapower modela el elemento `storage` con **convención de carga** (ver
`pandapower/create/storage_create.py:69`): `p_mw > 0` significa que la batería
consume de la red (se carga) y `p_mw < 0` que inyecta (se descarga). El proyecto
asumía lo contrario e integraba la energía restando:

```python
e1 = e0 - p_mw * dt_h   # incorrecto
```

Con la red de ejemplo (`p_mw = +0.02`, o sea cargando, y el `ext_grid`
aportando efectivamente esos 0.02 MW) el SoC caía 50 % → 10 % → 0 % y se quedaba
ahí: la batería se vaciaba justo cuando debía llenarse. El error contaminaba el
encadenado de SoC de toda la corrida.

Ahora integra sumando, y `tests/test_bateria_signo.py` ata la convención al
**balance de potencia** en vez de a la documentación, para que una regresión
falle sola.

### 2. El KPI de *curtailment* medía la carga de la batería

**Archivos:** `src/domain/simulation_engine.py`, `src/domain/entities.py`, `src/ui/dashboard.py`

El cálculo era:

```
curtailment = solar - consumo - pérdidas - exportación - carga_de_batería
```

Por conservación de energía eso da idénticamente 0… salvo que, con el signo de
batería invertido (punto 1), `carga_de_batería` valía 0 justo cuando la batería
cargaba. Resultado medido con sol alto: `ext_grid = -0.2903` (exportando),
`storage = +0.02` (cargando) → **curtailment reportado = 0.02 MW**, exactamente
la potencia de carga de la batería disfrazada de solar recortada.

Conceptualmente tampoco había nada que medir: bajo `runpp` el `sgen` es una
inyección fija, así que no existe recorte. Se reemplazó por **excedente
exportado** (`export_surplus_mw = max(0, -Σ res_ext_grid.p_mw)`), que sí es
observable. Medir curtailment real exige `runopp` con `sgen` controlable y
límites de generación.

### 3. Una corrida dejaba la red del Editor mutada

**Archivos:** `src/app/simulation_service.py`, `src/domain/network_model.py`

`run_corrida` escribía `scaling` y `soc_percent` sobre la red viva hora tras
hora, y `pp.runpp` le agregaba las tablas `res_*`. Como el `NetworkModel` es
compartido entre pestañas, después de simular el Editor mostraba la red con el
factor de la **última hora**:

```
ANTES   scaling: [1.0, 1.0]   soc: [50.0]
DESPUÉS scaling: [0.35, 0.35] soc: [0.0]
```

Y «Guardar» persistía eso. Ahora la simulación trabaja sobre
`NetworkModel.copy()` (copia profunda) y la red del Editor queda intacta,
incluidas las tablas de resultado.

### 4. «Ejecutar código» reactivaba elementos fuera de servicio

**Archivo:** `src/app/network_service.py` (`generar_codigo`)

El script generado —que el Editor regenera después de cada acción y presenta
como *"la fuente de verdad de la red"*— no emitía `in_service`, ni los
parámetros de regulación del transformador, ni los interruptores, ni los
índices, ni los límites de OPF. Round-trip sobre `1-LV-rural1--0-no_sw`:

```
ORIGINAL   líneas fuera de servicio: 1 | cargas fuera: 1 | tap_side ['hv']
ROUNDTRIP  líneas fuera de servicio: 0 | cargas fuera: 0 | tap_side [None]
```

Un click en «Ejecutar código» cambiaba la topología eléctrica sin avisar.

Se agregaron: `index` en todas las entidades del dominio (para que los elementos
no se renumeren), `in_service`, el juego completo de `tap_*` más `shift_degree`,
`std_type`, `net.switch`, y un bloque de *ajustes finos* con los límites de OPF
(`min_vm_pu`, `max_loading_percent`, `sn_mva`, …) vía `model.set_field`.

También se cambió el redondeo: era a 6 **decimales**, lo que degradaba los
valores chicos (un `length_km` de 0.0123456789 perdía 4 órdenes de precisión
relativa y eso se propagaba a las pérdidas). Ahora es a 12 **cifras
significativas**, con error relativo constante para cualquier magnitud.

Verificado: el round-trip es idéntico bit a bit (`< 1e-12` en pérdidas, tensión
mínima y potencia de la red externa) en las cuatro redes SimBench cacheadas, con
elementos fuera de servicio y el tap fuera del neutro.

**Limitación conocida:** las columnas de metadatos propias de SimBench
(`subnet`, `voltLvl`, `profile`, `phys_type`) no se emiten. No son eléctricas.

---

## Serios

### 5. Mover un bus invalidaba toda la caché de simulaciones

**Archivos:** `src/app/simulation_service.py`, `src/ui/graph_view.py`, `src/ui/editor.py`

`_hash_instante` serializaba la tabla `bus` completa, columna `geo` incluida, así
que un cambio puramente gráfico tiraba los resultados cacheados. Se separaron
los dos hashes, que tienen propósitos distintos:

- `network_signature` (cartel de desincronización del Dashboard) sigue incluyendo
  **todo**, posición incluida: mover un bus *sí* debe marcar el Dashboard como
  desactualizado.
- `_hash_instante` (clave de caché) excluye `geo`, `coords` y `name`: son
  metadatos de presentación que no cambian la física.

Se agravaba con el jitter anti-superposición: `net_to_elements` desplazaba 9 px
los buses casi coincidentes, y el Editor escribía de vuelta la posición
**renderizada** en cada `tapNode`. Como el JS reenvía el `dragfree` como `tap`,
un simple click sobre un bus apilado lo movía de forma permanente. Ahora el
desplazamiento se calcula en un único lugar (`bus_pixel_offsets`), el Editor lo
descuenta antes de persistir, y solo escribe ante un cambio real.

### 6. Una corrida nueva pisaba los metadatos de la vieja

**Archivo:** `src/repositories/json_simulation_repository.py`

El archivo cacheado estaba indexado por hash de entrada —compartido entre
corridas— pero guardaba adentro `run_id`, `hour_index`, `nombre_red` y
`timestamp`, que son *de una corrida*. Reusar un instante le robaba la identidad
a la corrida anterior, y un *cache hit* reportaba el nombre de red del primero
que lo hubiera calculado.

Ahora hay dos niveles con responsabilidades separadas:

- `data/resultados/{input_hash}.json` — solo el contenido físico del instante.
- `data/resultados/_corridas/{run_id}.json` — metadatos de la corrida y la
  secuencia ordenada de hashes por hora.

La hora y el nombre de red se reconstruyen desde el índice, nunca desde el
instante. Se eliminó el escaneo por `run_id` (ya no podía funcionar) y los
métodos muertos que guardaban por `uuid` en el mismo directorio que la caché.

### 7. Las rutas de datos dependían del directorio de trabajo

**Archivo nuevo:** `src/repositories/paths.py`

Los repositorios usaban `data/redes`, `data/resultados`, etc., relativos al CWD.
Arrancar desde la raíz del repo o desde un IDE creaba un árbol `data/` vacío en
otro lado y las redes guardadas desaparecían del desplegable sin ningún error.
Ahora todo se ancla a `Path(__file__)`, y `base_dir` sigue siendo inyectable
para los tests.

### 8. La caché no tenía versión de esquema

**Archivos:** `src/domain/entities.py`, `src/repositories/json_simulation_repository.py`

`SimulationResult(**data)` rompía con `TypeError` en cuanto cambiara un campo del
dataclass, y las claves `int` volvían como `str` del JSON, con cada consumidor
obligado a acordarse de recastear.

Ahora hay `SCHEMA_VERSION`, un `to_cache_dict`/`from_cache_dict` que normaliza
las claves a `int`, y un único `buscar_por_hash()` que devuelve `None` para los
tres casos de *cache miss* —no existe, esquema viejo, archivo corrupto— sin la
carrera del par `existe()` + `cargar()`.

**Caché purgada** al aplicar estos cambios: 367 instantes y 32 corridas (1.05 MB).
Eran resultados calculados con el signo de batería invertido, o sea físicamente
incorrectos. No se tocaron las redes guardadas ni las cachés de CAMMESA/NASA.

---

## Menores

### 9 y 10. `exec` de código de usuario + entrypoint WSGI

`src/main.py` exportaba `server = app.server` "para despliegue WSGI (gunicorn,
etc.)" mientras `NetworkService.aplicar_codigo` documentaba *"ejecución local
intencional"*. Desplegado, eso es ejecución remota de código sin autenticación.
Además `debug=True` estaba fijo, lo que habilita la consola de Werkzeug.

Se asumió explícitamente el diseño real —herramienta **local y monousuario**—:
se quitó el export WSGI, el modo debug pasó a `MG_DEBUG=1` (nunca por defecto), y
tanto `main.py` como `aplicar_codigo` documentan por qué. El estado global
compartido (que es lo que hace que las dos pestañas editen la misma red) queda
documentado como el otro motivo por el que no se puede servir a varios usuarios.

### 11. `numba` no estaba declarado

pandapower avisaba en cada `runpp` que la ejecución es lenta sin numba. Ahora se
detecta una vez (`importlib.util.find_spec`) y se pasa el flag explícito: con
numba se gana la aceleración, sin numba se corre igual pero sin ensuciar el log
hora tras hora. Queda documentado en `requirements.txt` como opcional
recomendado (no se fija porque su rango de numpy soportado va por detrás).

### 12. Desfase horario entre NASA y CAMMESA

**Archivo nuevo:** `src/domain/tiempo.py`

NASA POWER entrega en UTC y CAMMESA en hora local argentina, y `profile_builder`
sacaba la hora del día cortando el string (`ts[11:13]`) sin mirar el huso: el
perfil solar quedaba corrido 3 horas respecto del de demanda, con el pico de sol
a las 16 h locales. Todo se normaliza ahora a hora local argentina (UTC-3 fijo,
sin horario de verano desde 2009, sin depender de `tzdata`). Los timestamps
viejos sin huso se siguen interpretando como locales, así que la caché ya
descargada no se invalida.

### 13. Fechas de sincronización fijas

El Dashboard pedía siempre `20230101`–`20230107` a NASA. Ahora hay dos campos de
fecha, con la semana equivalente del año pasado por defecto (NASA publica con
meses de demora), y `sync_nasa` valida formato y orden del rango.

### 14. `sync_cammesa` reportaba éxito con 0 registros

Si la API cambiaba de formato, la UI mostraba éxito y la simulación seguía
cayendo al perfil sintético en silencio. Ahora devuelve `ok=False` con el motivo,
cuenta los registros descartados, y el Dashboard traduce el resultado a un
mensaje legible en vez de imprimir el `dict` crudo.

### 15. Caché de resultados sin límite

Se agregaron `tamanio()` y `purgar()` al repositorio, más un botón *Limpiar caché
de resultados* en el panel de sincronización que informa cuánto liberó.

### 16. El tope de horas era solo del navegador

`max=168` estaba en el `dcc.Input` pero `run_corrida` no validaba nada: un valor
escrito a mano colgaba el servidor. Ahora se recorta a `[1, 168]` del lado del
servidor, y un valor no numérico cae al default de 24.

---

# Segunda ronda

Revisión posterior a los arreglos anteriores. Trece hallazgos más, uno de ellos
crítico y preexistente.

## Crítico

### 1. Un `NaN` rompía el Dashboard mientras el cartel decía "✓ Corrida completa"

**Archivos:** `src/domain/simulation_engine.py`, `src/domain/entities.py`, `src/ui/graph_view.py`, `src/ui/dashboard.py`

Reproducido en la app: en el Editor, «+ Bus» (agregar un bus antes de conectarlo)
→ Dashboard → «Correr simulación». El estado anunciaba 24 instantes simulados y
los seis KPI quedaban en `—`, con un `500 INTERNAL SERVER ERROR` en la consola.

La cadena completa:

1. Un bus sin camino al slack da `res_bus.vm_pu = NaN`.
2. Ese `NaN` entra al `dcc.Store`.
3. Dash lo serializa como `null` al mandarlo al navegador.
4. Vuelve al servidor como `None`.
5. `min(volt.values())` → `TypeError: '<' not supported between instances of
   'NoneType' and 'float'`.

Tres disparadores distintos, todos alcanzables desde la UI o desde una red
importada: un bus aislado, una línea fuera de servicio (que deja sin solución
**toda** la sección aguas abajo) y un bus fuera de servicio.

Y tres daños colaterales del mismo `NaN`, independientes del 500: el grafo
pintaba el bus de **rojo crítico** con la etiqueta `nan pu`; `min`/`max` con
`NaN` dependen del orden de iteración (con el bus problemático primero, los KPI
mostraban `nan`); y el JSON de la caché contenía el token `NaN` desnudo, que no
es JSON válido para ningún lector estricto.

**Solución.** Ningún `NaN` sale del motor: `_build_result` aparta los elementos
sin solución en `buses_sin_solucion` / `lineas_sin_solucion` en vez de dejarlos
en los perfiles. El grafo los pinta en gris con la etiqueta "sin conexión" (hay
una entrada nueva en la leyenda), y el estado de la corrida avisa cuántos
quedaron afuera. El Dashboard además filtra valores no numéricos como segunda
defensa. Es **preexistente**: el mismo `min(volt.values())` estaba en `HEAD`.

## Serios

### 2. El SoC por batería del Editor no tenía ningún efecto

El panel de detalle dejaba editar `soc_percent` por batería, pero `run_corrida`
lo pisaba con el único campo «SoC inicial %» del Dashboard: dos baterías
configuradas en 100 % y 10 % arrancaban ambas en 50 %.

**Solución.** Manda el Editor. Se quitó el campo del Dashboard y la primera hora
arranca del SoC que cada batería tiene en la red. Es coherente con el criterio
general: los atributos de los elementos viven en la red, los parámetros de la
corrida en el Dashboard.

### 3. El patrón `valor or default` trataba el 0 como "sin valor"

SoC 0 % → 50 %, latitud 0 → −31.4, longitud 0 → −60.5, horas 0 → 24. Un SoC
inicial de 0 % (batería vacía) es un caso legítimo y se convertía en 50 % en
silencio. Reemplazado por `_valor()`, que sólo cae al default ante `None` o
texto vacío.

### 4. El botón «SimBench» del Dashboard ignoraba el código pedido

Se llamaba `sync_simbench()` sin argumento, así que siempre bajaba
`1-LV-rural1--0-no_sw`. Ahora el panel de sincronización tiene su propio campo de
código y lo pasa.

### 5. El tipo de carga pasó a configurarse por elemento

Con caché de CAMMESA, el desplegable «Tipo de carga» quedaba inerte: residencial,
comercial e industrial devolvían la misma curva, porque `_forma_desde_cammesa`
tenía precedencia.

**Solución** (más amplia que el hallazgo): el tipo de consumidor es ahora un
atributo **de cada carga** (`net.load.perfil_tipo`), editable en el panel de
detalle del Editor. `run_corrida` arma una curva por cada tipo presente en la red
y escala carga por carga con `apply_load_scaling_por_tipo`. Una misma red puede
mezclar viviendas, comercios e industria — lo necesario para mapear un barrio.
El tipo viaja con la red al guardarla, sobrevive al código generado y forma parte
de la clave de caché.

La demanda de CAMMESA quedó **deshabilitada** en la interfaz: su serie es el
consumo agregado de una región entera, así que imponía una única curva a toda la
red y anulaba justamente el tipo de cada carga. El código sigue intacto detrás de
`ProfileBuilder(usar_demanda_real=True)`.

Esto resuelve además el hallazgo **6** (la región era texto libre y un error de
tipeo caía al perfil sintético sin avisar): la región pasó a ser un desplegable
con las regiones válidas, dentro del panel de sincronización.

## Menores

**7.** El slider de hora no se reiniciaba: `db-hora.value` era sólo `Input`. Si
una corrida nueva tenía menos horas, el cursor quedaba en una hora inexistente.
Ahora `correr` lo devuelve a 0.

**8.** `SCHEMA_VERSION` estaba compartida por dos esquemas independientes.
Separada en `SCHEMA_VERSION_INSTANTE` (dominio) y `SCHEMA_VERSION_CORRIDA`
(repositorio).

**9.** *(introducido en la primera ronda)* `es_nulo` tenía código muerto —
`isinstance(valor, bool)` dentro de `if valor is None`, donde siempre da
`False`— y un `import math` por llamada dentro de un `try/except` que no podía
dispararse.

**10.** *(introducido en la primera ronda)* `set_field` creaba columnas nuevas
decidiendo el tipo por el **valor**, contradiciendo su docstring. Ahora un texto
que representa un número crea una columna numérica.

**11.** La UI codificaba `max=168` a mano; ahora usa `SimulationService.MAX_HORAS`.

**12.** `normalize_positions` no hacía nada si todos los buses compartían
coordenada (span 0) y el grafo recibía píxeles como `(-1067, 2057)`. Ahora los
reparte con el layout automático.

**13.** `JsonRedRepository.eliminar` existía sin ninguna pantalla que lo llamara.
Expuesto como botón «🗑 Borrar» junto al desplegable de redes guardadas, con
confirmación que nombra la red. Si se borra la que está abierta, se corta el
vínculo con el repositorio para que «Sobrescribir» no apunte a un id inexistente.

## Verificación

La suite pasó de 81 a **122 tests**. Los nuevos cubren, entre otros, que ningún
`NaN` llegue a los indicadores ni al JSON, que el bus sin solución se pinte en
gris y no en rojo, que cada carga se escale con la curva de su tipo, que el tipo
sobreviva al guardado y al código generado, y el borrado de redes con su efecto
sobre la red abierta.

En la app real se verificó el flujo que rompía (bus aislado → correr): los KPI
ahora pueblan (`0.0013 MW`, `0.971 pu`, `54.6 %`) y el estado agrega *"⚠ 1 bus
sin conexión al nodo slack"*; el bus sale gris en el grafo; el botón SimBench
respeta el código pedido; y el borrado de redes pide confirmación nombrando la
red antes de borrarla.
