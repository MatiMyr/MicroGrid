# Smart Microgrid Argentina — Arquitectura de Archivos

## Estructura de carpetas

```
mimicrogrid/
├── ui/
│   ├── dashboard.py
│   ├── editor.py
│   ├── graph_view.py
│   ├── widgets.py
│   └── theme.py
├── app/
│   ├── network_service.py
│   ├── code_gen.py
│   ├── simulation_service.py
│   └── data_sync_service.py
├── domain/
│   ├── entities.py
│   ├── network_model.py
│   ├── simulation_engine.py
│   ├── profile_builder.py
│   ├── epocas.py
│   └── tiempo.py
├── repositories/
│   ├── paths.py
│   ├── json_net_repository.py
│   ├── json_simbench_repository.py
│   ├── json_simulation_repository.py
│   ├── json_demanda_repository.py
│   └── json_irradiacion_repository.py
└── main.py
```

### Datos en disco

```
data/
├── redes/              ← json_net_repository.py
│   └── simbench/       ← json_simbench_repository.py
├── resultados/         ← json_simulation_repository.py
└── cache/
    ├── cammesa/        ← json_demanda_repository.py
    └── nasa/           ← json_irradiacion_repository.py
```

---

## Capas

Las carpetas están organizadas en cuatro capas conceptuales. Cada capa tiene una naturaleza distinta:

| Capa | Carpeta | Naturaleza |
|---|---|---|
| UI | `ui/` | Interfaces visuales. Muestran datos y capturan acciones del usuario. |
| Aplicación | `app/` | Coordinación. Orquestan el trabajo entre dominio y datos. |
| Dominio | `domain/` | Lógica de negocio. Aquí vive el conocimiento eléctrico del sistema. |
| Repositorios | `repositories/` | Acceso a datos. Traducen entre el formato del dominio y el formato de almacenamiento. |

---

## Tipos de conexión entre archivos

| Tipo | Descripción |
|---|---|
| **Solicita** | Un archivo llama a otro y le pide que haga algo |
| **Retorna** | Un archivo devuelve el resultado de lo que le pidieron |
| **Lee** | Un archivo consulta datos del repositorio sin pedirle que procese nada |
| **Escribe** | Un archivo deposita datos en el repositorio para que los persista |
| **HTTP externo** | Un archivo hace una solicitud a una fuente de datos externa |

No todos los tipos aplican a todas las capas:

| Capa | Tipos que usa |
|---|---|
| UI | Solicita, Retorna |
| Aplicación | Solicita, Retorna, Lee, Escribe, HTTP externo |
| Dominio | Solicita, Retorna, Lee, Escribe |
| Repositorios | Retorna, Lee, Escribe |
| Fuentes externas | HTTP externo |

---

## Archivos

### `ui/` — Interfaces visuales

---

#### `dashboard.py`
**Módulo conceptual:** Dashboard

Muestra los resultados de la simulación: tensiones por nodo, pérdidas, cargabilidad, autosuficiencia y excedente exportado. Visualiza la red como grafo interactivo con nodos y líneas coloreados según su estado. Permite ver y comparar simulaciones anteriores. Incluye los callbacks de Dash propios: le pide los resultados al Servicio Simulación y los datos de red al Servicio Red, y actualiza los gráficos cuando llegan.

| Tipo | Archivo | Descripción |
|---|---|---|
| Solicita | `network_service.py` | Le pide cargar una red nueva o aplicar los cambios que hizo el usuario en el Editor |
| Solicita | `simulation_service.py` | Le pide correr una simulación con la red y el escenario que configuró el usuario |
| Solicita | `data_sync_service.py` | Le indica que actualice los datos de CAMMESA y NASA cuando el usuario lo pide manualmente |
| Retorna | `network_service.py` | Recibe la red lista para mostrar |
| Retorna | `simulation_service.py` | Recibe los resultados: tensiones, pérdidas, cargabilidad y el resto de los indicadores |
| Solicita | `graph_view.py` | Le pide traducir la red a nodos y aristas, coloreados con los resultados de la corrida |
| Solicita | `widgets.py` | Le pide los campos de formulario y la leyenda del grafo |
| Solicita | `theme.py` | Le pide aplicar el template del proyecto a cada gráfico |
| Solicita | `epocas.py` | Le pide las opciones del desplegable de época del año |

---

#### `editor.py`
**Módulo conceptual:** Editor de red

Ofrece dos modos de edición: gráfico con botones para agregar o quitar elementos, y código Python directo con un editor integrado. Muestra la red en tiempo real mientras el usuario edita. Incluye los callbacks de Dash propios: envía los cambios al Servicio Red y recibe el estado actualizado de la red para mostrarlo.

| Tipo | Archivo | Descripción |
|---|---|---|
| Solicita | `network_service.py` | Le envía los cambios que hizo el usuario en la red para que los aplique |
| Retorna | `network_service.py` | Recibe el estado actualizado de la red para mostrarlo |
| Solicita | `graph_view.py` | Le pide traducir la red en edición a nodos y aristas, y convertir a coordenadas la posición de un bus arrastrado |
| Solicita | `widgets.py` | Le pide los campos de formulario y la leyenda del grafo |

---

#### `graph_view.py`
**Módulo conceptual:** Vista Grafo

Traduce una red de pandapower a la lista de nodos y aristas que consume Dash Cytoscape, y define la hoja de estilos del grafo. Lo comparten el Editor (vista en vivo mientras se edita) y el Dashboard (la misma vista, coloreada con los resultados de la simulación): tener una sola traducción es lo que garantiza que las dos pestañas dibujen la misma red.

Notas de implementación:
- Los elementos conectados a un bus (cargas, solar, baterías, red externa) se muestran como *badges* sobre el nodo del bus, no como nodos aparte, para que el grafo escale a redes grandes.
- Los buses que caen en coordenadas casi coincidentes se separan con un desplazamiento determinista. Es **sólo visual**: `geo_desde_pixel` se lo descuenta antes de que el Editor persista la posición, para que un simple click sobre un bus apilado no lo mueva de verdad.
- Un elemento que la simulación dejó **sin solución** (aislado, o aguas abajo de algo fuera de servicio) no figura en los perfiles de tensión y cargabilidad. Se dibuja en gris de "sin dato", nunca en el rojo de tensión crítica; la distinción entre "todavía no se simuló" y "se simuló y no hubo solución" la da la presencia de los perfiles.

| Tipo | Archivo | Descripción |
|---|---|---|
| Retorna | `dashboard.py` | Le entrega los nodos y aristas ya coloreados según los resultados de la corrida |
| Retorna | `editor.py` | Le entrega los nodos y aristas de la red en edición, con el bus seleccionado marcado |

---

#### `widgets.py`
**Módulo conceptual:** Componentes Compartidos

Los componentes de UI que el Editor y el Dashboard usan igual: el campo de formulario con su etiqueta y la leyenda del grafo. Sólo vive acá lo que las dos pestañas comparten; los helpers propios de una (el panel de detalle del Editor, los KPIs del Dashboard) se quedan en su módulo.

Notas de implementación:
- La leyenda es una sola función con un interruptor (`leyenda(con_estado=...)`). El estado de tensión —sana, alerta, crítica— sólo tiene sentido después de simular, así que es exclusivo del Dashboard: en el Editor la red todavía no tiene tensiones.

| Tipo | Archivo | Descripción |
|---|---|---|
| Retorna | `dashboard.py` | Le entrega los campos de formulario y la leyenda con estado de tensión |
| Retorna | `editor.py` | Le entrega los campos de formulario y la leyenda sin estado de tensión |

---

#### `theme.py`
**Módulo conceptual:** Tema de Gráficos

La paleta y el template de estilo de los gráficos de Plotly. Los colores vienen de una paleta validada para daltonismo, y los fondos son transparentes con tinta y grilla neutras: el mismo `Figure` se lee bien en tema claro y en oscuro, así que cambiar de tema no obliga a volver a renderizar los gráficos.

| Tipo | Archivo | Descripción |
|---|---|---|
| Retorna | `dashboard.py` | Le entrega la figura con el template del proyecto aplicado |

---

### `app/` — Coordinación

---

#### `network_service.py`
**Módulo conceptual:** Servicio Red

Es el responsable de tener siempre una red lista para simular. Sabe cómo cargar una red desde tres fuentes distintas: SimBench, un shapefile argentino o código Python del usuario. Cuando el usuario hace un cambio en el Editor, aplica ese cambio sobre la red que ya está cargada. Delega la construcción real de la red en `network_model.py`: él decide qué construir, pero no toca pandapower directamente, y delega en `code_gen.py` la emisión del script que reconstruye la red. Puede guardar y recuperar configuraciones de red a través del repositorio.

| Tipo | Archivo | Descripción |
|---|---|---|
| Solicita | `network_model.py` | Le dice qué red construir y qué elementos agregar o quitar |
| Solicita | `code_gen.py` | Le pide el script Python que reconstruye la red actual desde cero |
| Solicita | `json_net_repository.py` | Le pide guardar la configuración actual o recuperar una guardada antes |
| Solicita | SimBench / datos.gob.ar | Le pide la red base cuando el usuario elige cargar desde SimBench o desde un shapefile argentino |
| Retorna | `dashboard.py` | Le devuelve la red lista para mostrar en el Dashboard y en el Editor |
| Retorna | `editor.py` | Le devuelve el estado actualizado de la red para que lo muestre |
| Retorna | `network_model.py` | Recibe la red lista para simular |
| Retorna | `json_net_repository.py` | Recibe la topología y los parámetros eléctricos guardados |

---

#### `code_gen.py`
**Módulo conceptual:** Generador de Código

Emite el script Python que reconstruye la red actual desde cero: es lo que el Editor muestra en su pestaña de código y lo que vuelve a ejecutar cuando el usuario aprieta «Ejecutar código». Una función por tabla de pandapower, todas con la misma forma, más los helpers que traducen una celda a su literal Python. Vive aparte de `network_service.py` porque no es coordinación sino traducción de red a texto.

Notas de implementación:
- El script tiene que ser **fiel**, porque se regenera después de cada acción del Editor y se vuelve a aplicar con un botón: emite el índice de cada elemento (para que no se renumeren al reconstruir), `in_service`, la regulación del transformador, los interruptores y los límites de OPF.
- Líneas y transformadores se emiten con `create_*_from_parameters` y sus valores eléctricos reales, para que cualquier red se reconstruya sin depender de que su `std_type` esté en la librería de tipos.
- Los números se recortan a 12 cifras **significativas**, no a 12 decimales: redondear a decimales fijos degradaba los valores chicos (un `length_km` de 0.0123456789 perdía cuatro órdenes de precisión relativa) y esa diferencia se propaga a las pérdidas de la simulación.
- Limitación conocida: las columnas de metadatos propias de SimBench (`subnet`, `voltLvl`, `profile`, `phys_type`, …) no se emiten. No son eléctricas y no afectan el resultado.

| Tipo | Archivo | Descripción |
|---|---|---|
| Retorna | `network_service.py` | Le devuelve el script listo para que el Editor lo muestre |

---

#### `simulation_service.py`
**Módulo conceptual:** Servicio Simulación

Coordina todo lo que tiene que pasar para correr una simulación: busca los datos de carga y sol, se los da a `profile_builder.py`, junta todo y se lo entrega a `simulation_engine.py`. Una vez que tiene los resultados, los guarda en el repositorio para poder compararlos después. No sabe cómo simular ni cómo leer archivos: su único trabajo es coordinar a los demás.

| Tipo     | Archivo                         | Descripción                                                                                             |
| -------- | ------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Solicita | `simulation_engine.py`          | Le entrega la red y los perfiles de carga y solar, y le pide que corra la simulación                    |
| Solicita | `profile_builder.py`            | Le pide construir los perfiles de carga y solar para el período y la zona a simular                     |
| Retorna  | `dashboard.py`                  | Le devuelve los resultados: tensiones, pérdidas, cargabilidad y el resto de los indicadores             |
| Retorna  | `simulation_engine.py`          | Recibe los resultados calculados: tensiones, flujos, pérdidas e indicadores de desempeño                |
| Retorna  | `profile_builder.py`            | Recibe los perfiles horarios listos: cuánta energía consume y genera cada nodo hora a hora              |
| Escribe  | `json_simulation_repository.py` | Guarda cada resultado por instante, indexado por su hash                                                |
| Lee      | `json_simulation_repository.py` | Busca por hash si ya existe el resultado de un instante para no resimularlo (ver cache de simulaciones) |


---

#### `data_sync_service.py`
**Módulo conceptual:** Sincronizador de Datos

Mantiene actualizados los datos externos sin que el usuario tenga que hacerlo manualmente. Se conecta a CAMMESA y descarga los datos de demanda del mercado eléctrico argentino que aún no están en el caché local. Consulta la API de NASA para obtener los datos de irradiación solar de la zona que se está simulando. Trae del paquete SimBench las redes base que todavía no están en el caché local. Una vez que tiene los datos nuevos, los guarda en los repositorios correspondientes. Puede correrse automáticamente según un horario o ser disparado a mano desde la UI.

| Tipo | Archivo | Descripción |
|---|---|---|
| Escribe | `json_demanda_repository.py` | Guarda los datos nuevos de CAMMESA que acaba de descargar |
| Escribe | `json_irradiacion_repository.py` | Guarda los datos nuevos de irradiación solar que acaba de descargar |
| Escribe | `json_simbench_repository.py` | Guarda las redes SimBench nuevas que acaba de traer del paquete |
| HTTP externo | CAMMESA | Descarga los datos de demanda horaria del mercado eléctrico argentino |
| HTTP externo | NASA POWER API | Pide los datos de irradiación solar para las coordenadas de la zona que se simula |
| Paquete Python | SimBench | Obtiene las redes base de referencia instaladas localmente |

---

### `domain/` — Lógica eléctrica

---

#### `entities.py`
**Módulo conceptual:** Entidades del Dominio

Define los objetos del dominio eléctrico que viajan por todo el sistema: `Bus`, `Line`, `Transformer`, `Load`, `SolarPanel`, `Battery`, `ExternalGrid` y `SimulationResult`. Son estructuras de datos puras, sin lógica de simulación ni acceso a archivos.

Notas de implementación:
- `Battery` incluye el campo `scaling: float = 1.0` para consistencia con `Load` y `SolarPanel`.
- `SimulationResult` contiene estructuras anidadas (`node_results`, `line_results`, `battery_soc_result`) que se serializan a JSON.

---

#### `network_model.py`
**Módulo conceptual:** Modelo Red

Es el único archivo de todo el proyecto que habla directamente con pandapower. Sabe cómo crear buses, líneas, cargas, paneles solares y baterías. Recibe instrucciones en términos eléctricos y las traduce a llamadas de pandapower. Cuando la red viene de un shapefile argentino, usa geopandas para transformar la geometría en elementos de pandapower. Puede ajustar los parámetros de la red con valores reales argentinos que lee del repositorio.

Notas de implementación:
- `std.add_basic_std_types` se llama únicamente en el constructor, y solo cuando se crea una red nueva (no cuando se recibe un `net` externo ya construido).
- Los métodos `remove_*` individuales se reemplazan por un único `remove_element(element_type, index)`. `remove_bus` se mantiene separado por su comportamiento especial (`drop_elements=True`).

| Tipo    | Archivo                  | Descripción                                                            |
| ------- | ------------------------ | ---------------------------------------------------------------------- |
| Retorna | `network_service.py`     | Le entrega la red lista para simular                                   |


---

#### `simulation_engine.py`
**Módulo conceptual:** Motor Simulación

Recibe una red ya construida con sus perfiles de carga y generación, y corre la simulación eléctrica. Puede correr dos tipos de simulación: flujo de carga (cómo fluye la energía dada una configuración) y flujo óptimo (cuál es la mejor forma de despachar considerando restricciones). Calcula los indicadores de desempeño: pérdidas totales, rango de tensiones, cargabilidad máxima, cobertura local de demanda y energía solar perdida por restricciones.

Notas de implementación:
- El helper `_col_sum(df, col)` provee acceso seguro a columnas de DataFrames de resultados, reemplazando el uso incorrecto de `DataFrame.get()`.
- `export_surplus_mw` mide la potencia que la microgrid **inyecta** a la red externa: `max(0, -sum(res_ext_grid.p_mw))`.

  Reemplaza al viejo `curtailment_solar_mw` (agosto de 2026). Aquel intentaba deducir el recorte solar restándole al `sgen` el consumo, las pérdidas, la exportación y la carga de baterías. No podía funcionar: bajo `runpp` el `sgen` es una **inyección fija**, así que no existe recorte que medir — por conservación de energía el resultado daba siempre 0, y cuando la batería cargaba (con el signo invertido de `res_storage`) devolvía justo la potencia de carga de la batería disfrazada de solar recortada. Medir curtailment de verdad exige `runopp` con `sgen` controlable y límites de generación; hasta entonces, el excedente exportado es la magnitud análoga que sí es observable.
- `autosufficiency_pct` incluye pérdidas en el denominador: `solar / (carga + pérdidas) * 100`.

| Tipo    | Archivo                         | Descripción                                                                      |
| ------- | ------------------------------- | -------------------------------------------------------------------------------- |
| Retorna | `simulation_service.py`         | Le devuelve los resultados calculados: tensiones, flujos, pérdidas e indicadores |

---

#### `profile_builder.py`
**Módulo conceptual:** Constructor Perfiles

Construye curvas horarias normalizadas (0..1) por tipo de consumidor —residencial, comercial e industrial, cada uno con su forma característica— y una curva de generación solar a partir de la irradiación de NASA POWER. El resultado son los factores hora a hora con los que `simulation_service.py` escala cada elemento de la red.

El tipo de consumidor es un atributo **de cada carga** (`net.load.perfil_tipo`), no un parámetro de la corrida: la corrida arma una curva por cada tipo presente y escala carga por carga, de modo que una misma red puede mezclar viviendas, comercios e industria.

> **La demanda de CAMMESA está deshabilitada** (agosto de 2026). Su serie es el consumo agregado de una región entera, así que aplicarla imponía una única curva a todas las cargas y anulaba el tipo de cada una. El código sigue disponible detrás de `ProfileBuilder(usar_demanda_real=True)`; ver `doc/correcciones_2026-08.md`.

| Tipo    | Archivo                          | Descripción                                                                                    |
| ------- | -------------------------------- | ---------------------------------------------------------------------------------------------- |
| Retorna | `simulation_service.py`          | Le entrega los perfiles horarios listos: cuánta energía consume y genera cada nodo hora a hora |
| Lee     | `json_demanda_repository.py`     | *(deshabilitado)* Leería el historial de demanda de CAMMESA; hoy los perfiles de carga son sintéticos por tipo |
| Lee     | `json_irradiacion_repository.py` | Lee la serie de irradiación solar de NASA para construir los perfiles de generación            |

---

#### `epocas.py`
**Módulo conceptual:** Épocas del Año

Define las ocho ventanas típicas del año —las cuatro estaciones del hemisferio sur más los cuatro puntos intermedios— con las que se pide el perfil solar. Cada época es una ventana de unos tres meses centrada en su fecha de referencia: solsticios, equinoccios y los puntos medios entre ellos.

Notas de implementación:
- Promediar varios años es lo que vuelve al perfil *típico* en vez de la foto de un año puntual: un invierno anómalamente nublado deja de dominar la forma de la curva. Y promediar tres meses en vez de una semana suaviza el clima del día sin mezclar estaciones — la ventana no llega a tocar la época opuesta.
- NASA POWER publica con varios meses de demora, así que el año más reciente que se promedia es el último cuya ventana entera cae antes de ese horizonte; si no, llegaría incompleta.

| Tipo | Archivo | Descripción |
|---|---|---|
| Retorna | `data_sync_service.py` | Le entrega los rangos de fechas a descargar para la época pedida |
| Retorna | `dashboard.py` | Le entrega las opciones y etiquetas del desplegable de época |

---

#### `tiempo.py`
**Módulo conceptual:** Tiempo Local

Normaliza a hora local argentina todo lo que se persiste en el caché. Las dos fuentes externas vienen en husos distintos —NASA POWER entrega UTC y CAMMESA hora local—, y antes ambas se guardaban tal como llegaban, con la hora del día extraída cortando el string sin mirar el huso. Resultado: el perfil solar quedaba corrido tres horas respecto del de demanda y el pico de sol aparecía a las 16 h en vez del mediodía.

Notas de implementación:
- Usa un offset fijo de UTC−3 en vez de `zoneinfo`: Argentina no aplica horario de verano desde 2009, así que el offset es constante para todo el rango de datos del proyecto, y evita depender del paquete `tzdata` (necesario en Windows, donde el sistema no trae base de husos).

| Tipo | Archivo | Descripción |
|---|---|---|
| Retorna | `data_sync_service.py` | Le devuelve los timestamps ya convertidos a hora local argentina |
| Retorna | `profile_builder.py` | Le devuelve la hora del día de cada registro de las series cacheadas |

---

### `repositories/` — Acceso a datos

Los repositorios son la única parte del sistema que sabe cómo están guardados los datos en disco. Reciben objetos del dominio, los traducen a JSON para guardarlos, y traducen JSON a objetos del dominio cuando los devuelven. El resto del sistema nunca lee ni escribe archivos directamente.

> **Migración futura:** para pasar a SQL basta con crear una versión `sql_xxx_repository.py` de cada uno que implemente los mismos métodos. El resto del código no se toca.

---

#### `paths.py`
**Módulo conceptual:** Rutas de Datos

La ubicación canónica de los datos de runtime. Todos los repositorios anclan sus rutas acá en vez de usar rutas relativas al directorio de trabajo: con rutas relativas, arrancar la app desde la raíz del repo (o desde un IDE) creaba un árbol `data/` vacío en otro lado y las redes guardadas desaparecían del desplegable sin ningún error visible.

| Tipo | Archivo | Descripción |
|---|---|---|
| Retorna | Todos los repositorios | Les entrega la ruta absoluta de su carpeta de datos |

---

#### `json_net_repository.py`
**Módulo conceptual:** Red Repo

Guarda y recupera configuraciones de red en archivos JSON bajo `data/redes/`. Cada red tiene un id estable (asignado una sola vez, nunca cambia) y un nombre editable por el usuario para mostrar en la UI — ver [id estable vs. nombre editable](#id-estable-vs-nombre-editable-en-el-repositorio-de-redes). Cada red se serializa con `pp.to_json` y se deserializa con `pp.from_json`, preservando toda la topología y los parámetros eléctricos sin transformaciones adicionales. Si se intenta guardar con un nombre que ya existe, lanza una excepción en vez de sobrescribir en silencio (ver [colisión de nombres](#colision-de-nombres-en-el-repositorio-de-redes)). También provee los parámetros eléctricos de referencia que `network_model.py` usa para ajustar redes benchmark con datos reales.

| Tipo    | Archivo              | Descripción                                     |
| ------- | -------------------- | ----------------------------------------------- |
| Escribe | `network_service.py` | Guarda los datos de la red cargada en el editor |
| Lee     | `network_service.py` | Obtiene del repo una red guardada previamente   |

---

#### `json_simbench_repository.py`
**Módulo conceptual:** SimBench Repo

Cachea localmente en archivos JSON bajo `data/redes/simbench/` las redes base traídas de SimBench, para no volver a descargarlas cada vez que se necesitan como punto de partida de una simulación. Actúa como caché de la [fuente externa SimBench](#simbench--datosgobar): cuando alguien pide una red base por su código, devuelve la versión ya guardada; cuando `data_sync_service.py` trae una red nueva desde el paquete SimBench, la persiste. Cada red se serializa con `pp.to_json` y se deserializa con `pp.from_json`, preservando la topología y los parámetros eléctricos sin transformaciones adicionales — igual que `json_net_repository.py`. A diferencia de este último, las redes SimBench son de referencia: se identifican por su código de benchmark (no por un id/nombre editable por el usuario) y no se sobrescriben en runtime.

| Tipo    | Archivo                | Descripción                                                             |
| ------- | ---------------------- | ----------------------------------------------------------------------- |
| Lee     | `network_service.py`   | Obtiene la red base de SimBench cacheada como punto de partida          |
| Escribe | `data_sync_service.py` | Recibe y persiste las redes SimBench nuevas descargadas del paquete     |

---

#### `json_simulation_repository.py`
**Módulo conceptual:** Simulación Repo

Guarda los resultados de cada simulación en archivos JSON bajo `data/resultados/`, uno por instante (no por corrida completa), indexado por su hash de entrada en vez de un id random — así verificar si un instante ya fue simulado es un acceso directo (`{hash}.json`), no un escaneo del directorio. El formato JSON permite persistir la estructura anidada de `SimulationResult` (con `node_results` y `line_results`) en un solo archivo sin aplanar. Una corrida de varios días se reconstruye juntando los instantes que comparten red y período; no se guarda como una unidad separada. Ver [[#Cache de simulaciones por instante]] para el detalle de la clave.

| Tipo    | Archivo                 | Descripción                                                         |
| ------- | ----------------------- | ------------------------------------------------------------------- |
| Escribe | `simulation_service.py` | Provee resultados luego de correr simulación para persistirlas.     |
| Lee     | `simulation_service.py` | Lee resultados cuando se solicita simular un escenario ya simulado. |

---

#### `json_demanda_repository.py`
**Módulo conceptual:** Demanda Repo

Guarda y lee los datos de demanda horaria de CAMMESA en archivos JSON bajo `data/cache/cammesa/`. Cuando alguien le pide datos de un período, devuelve lo que tiene en el caché. Cuando `data_sync_service.py` trae datos nuevos, los agrega sin duplicar lo que ya existe.

| Tipo    | Archivo                 | Descripción                                                         |
| ------- | ----------------------- | ------------------------------------------------------------------- |
| Lee     | `profile_builder.py`    | Provee el historial de demanda para construir los perfiles de carga |
| Escribe | `data_sync_service.py`  | Recibe y persiste los datos nuevos descargados de CAMMESA           |

---

#### `json_irradiacion_repository.py`
**Módulo conceptual:** Irradiación Repo

Guarda y lee los datos de irradiación solar de NASA POWER en archivos JSON bajo `data/cache/nasa/`. Los datos se organizan por ubicación geográfica **y época del año** (`{lat}_{lon}_{epoca}.json`): cada archivo junta las ventanas de ~3 meses de los últimos años centradas en esa época, y el `ProfileBuilder` las promedia hora a hora para obtener el día solar típico. Las 8 épocas —las cuatro estaciones del hemisferio sur más sus intermedios— se definen en `domain/epocas.py`.

| Tipo    | Archivo                 | Descripción                                                                    |
| ------- | ----------------------- | ------------------------------------------------------------------------------ |
| Lee     | `profile_builder.py`    | Provee la serie de irradiación solar para construir los perfiles de generación |
| Escribe | `data_sync_service.py`  | Recibe y persiste los datos nuevos descargados de NASA POWER                   |

---

### `main.py` — Punto de entrada

Arma la app de Dash con sus dos pestañas y crea **una sola instancia** de cada servicio, compartida por ambas: es lo que hace que el Editor y el Dashboard trabajen sobre la misma red en memoria. Los repositorios de caché también se comparten, así lo que sincroniza el Dashboard queda disponible para la próxima simulación.

Notas de implementación:
- La herramienta es **local y monousuario a propósito**, y son dos decisiones de diseño las que lo vuelven un requisito y no una preferencia. Primero, el Editor ejecuta código Python del usuario con `exec`: expuesto en red, eso es ejecución remota de código arbitraria y sin autenticación. Segundo, el estado —la red en memoria— es una única instancia compartida por todo el proceso, que es justamente lo que permite que las dos pestañas editen la misma red, y también lo que impide atender a dos usuarios a la vez.
- Por eso la app escucha sólo en `127.0.0.1` y no se exporta un objeto WSGI para gunicorn. Para habilitar multiusuario primero hay que aislar el estado por sesión y sacar (o encerrar) el `exec`.
- El modo debug de Dash levanta la consola interactiva de Werkzeug, que ejecuta código arbitrario desde el navegador: se activa a pedido con `MG_DEBUG=1`, nunca por defecto.

---

### Fuentes externas
No son archivos del proyecto. Son servicios externos que `data_sync_service.py` y `network_service.py` consultan para obtener datos.

---

#### SimBench / datos.gob.ar
Fuente de topologías de red base. SimBench provee redes de baja tensión urbana de referencia que se instalan como paquete Python. datos.gob.ar provee shapefiles con la geometría real de las redes de distribución de ENERSA, SECHEEP y EC SAPEM.

#### CAMMESA
Sitio del mercado eléctrico mayorista desde donde `data_sync_service.py` descarga los datos de demanda horaria. Provee datos de despacho y demanda para todo el sistema eléctrico argentino en formato XLS o CSV.

#### NASA POWER API
API desde donde `data_sync_service.py` descarga los datos de irradiación solar. Se consulta con coordenadas GPS y rango de fechas, y devuelve la serie de irradiación hora a hora. Es gratuita y no requiere autenticación.

---

## Decisiones de diseño

### Los callbacks de Dash viven dentro de `dashboard.py` y `editor.py`

En Dash, los callbacks son funciones que reaccionan a eventos de la UI y conectan componentes con servicios. La opción inicial era concentrarlos en un `callbacks.py` separado, pero se descartó porque los callbacks son funcionalidad específica de cada interfaz: los del Dashboard responden a eventos de visualización y los del Editor responden a eventos de edición. Separarlos en un archivo aparte solo añade indirección sin aportar claridad. Cada archivo de UI es responsable de sus propios callbacks.

### Persistencia en JSON en lugar de CSV

Los archivos JSON reemplazan a los CSV en todos los repositorios. Los motivos:
- `SimulationResult` contiene estructuras anidadas (`node_results`, `line_results`) que no se representan naturalmente en CSV sin aplanar o fragmentar en múltiples archivos.
- pandapower provee serialización nativa con `pp.to_json` / `pp.from_json`; forzar la red a CSV requería un workaround innecesario.
- Un archivo JSON por entidad simplifica la gestión de I/O y es legible a mano para debugging.
- La consistencia del stack pesa más que la ventaja puntual de CSV para datos tabulares simples.

La interfaz abstracta del patrón Repository se mantiene. La migración futura a SQL sigue siendo válida: reemplazar `JsonXxxRepository` por `SqlXxxRepository` sin modificar el resto del código.

### Cache de simulaciones por instante

`json_simulation_repository.py` cachea cada simulación (una hora/instante puntual) por separado, no por corrida completa (ej: 7 días), para poder reusar resultados en ventanas de fechas solapadas.

**Clave de cache por instante:** `hash(red sin tablas res_*, carga[H], solar[H], tipo de corrida, SoC inicial por batería[H])`.

Motivos:
- Un `pandapowerNet` incluye tablas de resultado (`res_bus`, `res_load`, etc.) que cambian si la red ya fue simulada antes; se excluyen del hash porque no son parte del input.
- La serialización de la red debe ser canónica (orden de claves fijo, floats redondeados) para que la misma red siempre hashee igual, sin importar el orden en que se construyó.
- `pp.runpp` no tiene memoria entre corridas: el estado de carga (SoC) de una batería no se actualiza solo de una hora a la siguiente. Por eso el SoC inicial de cada instante es parte explícita del hash, y no un dato implícito en la red o el perfil.
- El SoC del primer instante de una corrida nueva lo define el usuario (o el default de `Battery.soc_percent`); el de cada instante siguiente lo calcula automáticamente el sistema a partir del `res_storage.p_mw` del instante anterior.
- Con esto, simular "días 3-6" reusa del cache los instantes cuyo SoC de partida coincide con el resultado real de haber simulado "días 1-2" antes, y resimula (y cachea aparte) si se pide un SoC de partida distinto.

**Dónde vive el cálculo del SoC resultante:** en `simulation_engine.py`, no en `simulation_service.py`. Calcular el SoC a partir de `res_storage.p_mw` es conocimiento eléctrico del dominio (mismo tipo de cálculo que ya hace `_build_result` con `autosufficiency_pct` o `export_surplus_mw`), no orquestación. `simulation_service.py` se limita a encadenar el loop: corre el instante H, toma el SoC resultante que le devuelve el dominio, se lo pasa como input al instante H+1. El SoC resultante se persiste en `SimulationResult.battery_soc_result` para poder retomar la cadena desde un instante cacheado sin necesitar la corrida en memoria.

Pendiente de implementar: el loop que encadena el SoC entre instantes, y el índice que agrupa los `SimulationResult` de una corrida para el Dashboard.

### Colisión de nombres en el repositorio de redes

Las redes se acceden por el nombre que el usuario les asignó (con un nombre default sugerido al guardar, que puede cambiar). Si el nombre elegido ya existe —tanto al guardar desde el Editor como al importar un JSON local— `json_net_repository.py` no sobrescribe en silencio: lanza una excepción y se le vuelve a pedir un nombre distinto. Esto evita perder una red guardada por una colisión accidental de nombres, algo más probable una vez que se agregue la importación de archivos de otros usuarios.

Al importar un JSON local, el archivo debe pasar primero por `pp.from_json` para validar que sea una red pandapower válida antes de guardarlo (con `pp.to_json`) bajo el nombre elegido — no se copia el archivo tal cual a `data/redes/`.

### Id estable vs. nombre editable en el repositorio de redes

El nombre de una red es editable por el usuario, así que no puede ser la clave que otras partes del sistema usan para referenciarla. Si `SimulationResult` (u otro dato) guardara el nombre tal cual, renombrar una red obligaría a actualizar esa referencia en todas las simulaciones que la usaron — costoso y frágil, y fácil de dejar referencias rotas.

Por eso cada red tiene dos identificadores con roles distintos:
- **Id estable:** se asigna una sola vez al guardar la red por primera vez, y nunca cambia. Es lo que `SimulationResult` y cualquier otro dato usan para referenciar "qué red se usó" — nunca el nombre.
- **Nombre editable:** la etiqueta que el usuario ve y puede cambiar en el Editor y el Dashboard. Renombrar una red solo actualiza el nombre asociado a su id, en un único lugar — ninguna simulación previa necesita tocarse.

El nombre sigue siendo relevante para la UI y para la validación de colisión (dos redes no pueden mostrarse con el mismo nombre), pero deja de ser la clave interna de referencia entre archivos.
