# Smart Microgrid Argentina

Herramienta open source para simular microgrids de baja tensión con datos
argentinos (SimBench, NASA POWER, CAMMESA). Simulación eléctrica rigurosa con
[pandapower](https://www.pandapower.org/) + interfaz web interactiva en
[Dash](https://dash.plotly.com/).

## Arquitectura

El proyecto sigue cuatro capas (ver `doc/microgrid_arquitectura_archivos.md`):

```
src/
├── ui/            Interfaces Dash (editor.py, dashboard.py, graph_view.py) + main.py
├── app/           Coordinación (network_service, simulation_service, data_sync_service)
├── domain/        Lógica eléctrica (entities, network_model, simulation_engine,
│                  profile_builder, tiempo)
└── repositories/  Persistencia JSON (redes, simbench, resultados, demanda,
                   irradiación) + paths.py
```

Los datos de runtime se guardan bajo `src/data/` (ignorada por git). Las rutas
están ancladas a la ubicación del código, no al directorio de trabajo, así que la
app encuentra siempre los mismos datos sin importar desde dónde se la ejecute:

```
src/data/
├── redes/            redes guardadas por el usuario (id estable + nombre editable)
│   └── simbench/     caché de redes base de SimBench
├── resultados/       instantes de simulación, indexados por hash de sus entradas
│   └── _corridas/    metadatos y secuencia de horas de cada corrida
└── cache/
    ├── cammesa/      demanda horaria de CAMMESA
    └── nasa/         irradiación solar de NASA POWER
```

## Instalación

Requiere Python 3.10+.

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
```

Opcional pero recomendado: `pip install numba` acelera mucho el flujo de potencia
de pandapower. El código detecta si está instalado y ajusta la llamada solo.

## Ejecución

```bash
cd src
python main.py
```

Abrir <http://127.0.0.1:8050> en el navegador.

> **Herramienta local y monousuario, a propósito.** El Editor ejecuta código
> Python del usuario con `exec`, y la red en memoria es una única instancia
> compartida por todo el proceso (es lo que hace que las dos pestañas editen la
> misma red). Por eso la app escucha solo en `127.0.0.1` y no expone un objeto
> WSGI: servirla en red sería ejecución remota de código sin autenticación, y
> dos usuarios se pisarían la red entre sí. El modo debug de Dash se activa con
> `MG_DEBUG=1`, nunca por defecto.

## Tests

```bash
pytest tests
```

Cubren lo que puede romperse en silencio: la convención de signo de las baterías
(atada al balance de potencia, no a la documentación), que una corrida no mute la
red del Editor, la fidelidad del código generado contra las redes SimBench, la
estabilidad de la clave de caché, la normalización horaria, el tipo de consumidor
por carga y que ningún `NaN` llegue a los indicadores. También validan las
salidas contra referencias independientes: una red de dos buses con solución
analítica cerrada y la conservación de potencia en las redes reales.

## Uso

La app tiene dos pestañas que comparten la misma red en memoria:

- **Editor de red** — cargá una red (de ejemplo, de SimBench por código, o una
  guardada), editala por formularios o con código Python, mirá el grafo en vivo
  y guardala con un nombre (o borrala, con confirmación). El código generado
  reconstruye la red **completa** (índices, `in_service`, regulación del trafo,
  interruptores y límites de OPF incluidos), así que ejecutarlo no cambia la
  física de la red.

  Tocando un bus se abre su panel de detalle, donde cada elemento lleva sus
  propios parámetros: el **tipo de consumidor** de cada carga (residencial,
  comercial o industrial) y el **SoC inicial** de cada batería. Son atributos de
  la red, no de la corrida, así que una misma red puede mezclar viviendas,
  comercios e industria — lo necesario para mapear, por ejemplo, un barrio.
- **Dashboard** — corré una simulación horaria (`runpp` o `runopp`) eligiendo
  cantidad de horas y ubicación. Muestra pérdidas, perfil de tensión,
  cargabilidad, autosuficiencia y excedente exportado, con un grafo coloreado
  por estado y un slider para recorrer las horas. El panel *Sincronizar datos
  externos* descarga a mano irradiación (NASA POWER) y redes base (SimBench), y
  permite vaciar la caché de resultados.

  La simulación corre sobre una copia de la red: la que estás editando no se
  toca. Las series externas se normalizan a hora local argentina.

  Los buses que quedan sin camino al nodo slack —aislados, o aguas abajo de algo
  fuera de servicio— no tienen solución eléctrica: quedan fuera de los
  indicadores, se dibujan en gris y la corrida avisa cuántos fueron.

### Funciona sin conexión

`profile_builder.py` genera perfiles sintéticos característicos (una curva por
tipo de consumidor y una campana solar diurna), así la simulación funciona igual
sin datos descargados. Sincronizá la irradiación de NASA POWER para reemplazar
la campana sintética por la serie real de tu ubicación.

> **La demanda de CAMMESA está deshabilitada.** Su serie es el consumo
> **agregado de una región entera**, así que aplicarla imponía una única curva a
> todas las cargas y dejaba sin efecto el tipo de consumidor de cada una. El
> código quedó intacto detrás de `ProfileBuilder(usar_demanda_real=True)`:
> reactivarlo es cambiar ese flag y habilitar el botón del Dashboard, una vez
> que se decida cómo repartir una curva regional entre cargas individuales.

## Diseño destacado

- **Caché de simulaciones por instante**: cada hora se cachea por el hash de sus
  entradas (red sin tablas `res_*`, factores de carga/solar, modo y SoC inicial),
  de modo que ventanas de fechas solapadas reusan instantes ya calculados. La
  clave ignora los campos de presentación (posición y nombres): mover un bus no
  invalida los resultados. Los metadatos de cada corrida viven aparte, en
  `_corridas/`, para que dos corridas puedan compartir instantes sin pisarse.
- **SoC encadenado**: el estado de carga de las baterías resultante de una hora
  (`simulation_engine._battery_soc_result`) alimenta el SoC inicial de la
  siguiente, y se persiste en `SimulationResult.battery_soc_result`. La primera
  hora arranca del SoC que cada batería tiene en la red. El signo sigue la
  convención de pandapower: `p_mw > 0` carga la batería, `p_mw < 0` la descarga.

- **Perfil por elemento, no por corrida**: cada carga lleva su `perfil_tipo` en
  una columna propia de `net.load`, que viaja con la red al guardarla y al
  regenerar el código. La corrida arma una curva por cada tipo presente y escala
  carga por carga.

- **Sin `NaN` fuera del motor**: los elementos que el flujo deja sin solución se
  listan en `buses_sin_solucion` / `lineas_sin_solucion` en vez de quedar como
  `NaN` dentro de los perfiles. Un `NaN` arrastraba mínimos y máximos, se
  escribía en la caché como un token que no es JSON válido y, al volver del
  navegador convertido en `null`, rompía el Dashboard entero.
- **Id estable vs. nombre editable**: cada red guardada tiene un id que nunca
  cambia (clave de referencia) y un nombre editable (etiqueta de UI, con
  validación de colisión).
