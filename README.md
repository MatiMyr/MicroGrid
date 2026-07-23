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
├── domain/        Lógica eléctrica (entities, network_model, simulation_engine, profile_builder)
└── repositories/  Persistencia JSON (redes, simbench, resultados, demanda, irradiación)
```

Los datos de runtime se guardan bajo `data/` (ignorada por git):

```
data/
├── redes/            redes guardadas por el usuario (id estable + nombre editable)
│   └── simbench/     caché de redes base de SimBench
├── resultados/       resultados de simulación (uno por instante, indexado por hash)
│   └── _corridas/    índice de instantes por corrida
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

## Ejecución

```bash
cd src
python main.py
```

Abrir <http://127.0.0.1:8050> en el navegador.

## Uso

La app tiene dos pestañas que comparten la misma red en memoria:

- **Editor de red** — cargá una red (de ejemplo, de SimBench por código, o una
  guardada), editala por formularios o con código Python, mirá el grafo en vivo
  y guardala con un nombre.
- **Dashboard** — corré una simulación horaria (`runpp` o `runopp`) eligiendo
  cantidad de horas, tipo de consumidor, región y ubicación. Muestra pérdidas,
  perfil de tensión, cargabilidad, autosuficiencia y curtailment, con un grafo
  coloreado por estado y un slider para recorrer las horas. El panel *Sincronizar
  datos externos* descarga a mano irradiación (NASA POWER), demanda (CAMMESA) y
  redes base (SimBench).

### Funciona sin conexión

Si no hay datos cacheados de CAMMESA/NASA, `profile_builder.py` genera perfiles
sintéticos característicos (curva residencial/comercial/industrial y campana
solar diurna), así la simulación funciona igual. Sincronizá los datos externos
para reemplazarlos por series reales.

## Diseño destacado

- **Caché de simulaciones por instante**: cada hora se cachea por el hash de sus
  entradas (red sin tablas `res_*`, factores de carga/solar, modo y SoC inicial),
  de modo que ventanas de fechas solapadas reusan instantes ya calculados.
- **SoC encadenado**: el estado de carga de las baterías resultante de una hora
  (`simulation_engine._battery_soc_result`) alimenta el SoC inicial de la
  siguiente, y se persiste en `SimulationResult.battery_soc_result`.
- **Id estable vs. nombre editable**: cada red guardada tiene un id que nunca
  cambia (clave de referencia) y un nombre editable (etiqueta de UI, con
  validación de colisión).
