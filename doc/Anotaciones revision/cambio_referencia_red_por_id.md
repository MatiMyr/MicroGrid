# Cambio pendiente: referenciar la red por id estable en `SimulationResult`

**Archivos:** `src/domain/entities.py` (clase `SimulationResult`), `src/domain/simulation_engine.py` (`_build_result`, `runpp`, `runopp`), `src/app/simulation_service.py` (métodos `run_pp`, `run_opp`, `_run_instante`, `run_periodo`), `src/ui/dashboard.py` (~línea 213), `src/repositories/json_simulation_repository.py` (~línea 82).

## Problema

`SimulationResult` guarda **solo el nombre** de la red, no su id estable:

```python
# entities.py:110
nombre_red: str = ""     # guarda el nombre, NO el id de la red
```

Esto **contradice la decisión de diseño documentada** en `doc/microgrid_arquitectura_archivos.md`, sección *"Id estable vs. nombre editable en el repositorio de redes"*, que dice explícitamente:

> El id estable es lo que `SimulationResult` y cualquier otro dato usan para referenciar "qué red se usó" — **nunca el nombre**.

El id estable ya existe y funciona: `json_net_repository.py` asigna `red_id = uuid.uuid4().hex` (línea 60) y mantiene un índice `{red_id: nombre}`. El problema es que ese id no se propaga hasta el resultado.

De hecho, en el punto donde se llena el campo el id **está disponible pero se descarta**:

```python
# dashboard.py:213
nombre_red=network_service.net_repo.nombre_de(network_service.red_id) or "actual",
```

Ahí se tiene `network_service.red_id` en la mano, pero se lo convierte a nombre y se guarda el nombre.

**Consecuencia:** si el usuario renombra una red, todas las simulaciones viejas quedan con una referencia (el nombre) que ya no coincide con la red en el repositorio. Es justo el escenario frágil que la decisión de diseño buscaba evitar.

## Solución

Agregar a `SimulationResult` un campo `red_id: str` como **referencia estable**, y propagarlo por toda la cadena que hoy propaga `nombre_red`. El nombre se resuelve **al mostrar**, desde el repo, con `net_repo.nombre_de(red_id)`.

- `red_id` = única clave de referencia.
- `nombre_red` = **se elimina**. No debe usarse como clave, y con el invariante de abajo tampoco hace falta como fallback.

### Invariante que habilita esto

Simular una red **implica** que esa red ya está registrada en el `net_repo`. Es decir: antes de correr una simulación se garantiza que existe un `red_id` válido para la red en memoria. Con este invariante, `SimulationResult.red_id` **nunca** es `""`, desaparece el fallback `or "actual"` y todo el special-casing de `red_id is None`.

**Hoy el invariante NO se cumple:** en `network_service.py:41` `self.red_id` arranca en `None` y el Editor permite construir y simular una red en memoria sin guardarla. Establecer el invariante exige que, previo a simular, se auto-registre la red. Eso abre dos decisiones de implementación:

1. **Nombre de auto-registro.** `net_repo.guardar` exige nombre y lanza excepción si colisiona. Al simular el usuario aún no nombró la red → usar un nombre autogenerado (ej. `red_<timestamp>`) o un default editable después.
2. **Evitar registros duplicados al re-simular.** Registrar solo si `red_id is None`; en las siguientes corridas reutilizar el mismo id y usar `net_repo.actualizar(red_id, net)` en vez de crear una red nueva cada vez. Si no, ajustar-y-simular en el Editor llena el repo de redes casi idénticas.

> Nota: `red_id` (qué red nombrada) es **ortogonal** al hash del caché de simulaciones (qué estado eléctrico exacto). Son dos ejes independientes.

## Diff propuesto

**1. `entities.py`** — reemplazar `nombre_red` por `red_id` (~línea 110):

```python
red_id: str = ""          # id estable de la red usada (referencia canónica)
# nombre_red: eliminado — el nombre se resuelve al mostrar con net_repo.nombre_de(red_id)
```

**2. `simulation_engine.py`** — pasar `red_id` por `runpp`, `runopp` y `_build_result`:

```python
# _build_result(...): agregar parámetro red_id: str = ""
return SimulationResult(
    ...
    red_id=red_id,
    nombre_red=nombre_red,
    escenario=escenario,
)
```

**3. `simulation_service.py`** — agregar `red_id` a las firmas de `run_pp`, `run_opp`, `_run_instante` y `run_periodo`, y reenviarlo al runner (donde hoy se pasa `nombre_red`).

**4. `dashboard.py` (~213)** — pasar el id directo (garantizado no nulo por el invariante), en vez de resolver y persistir el nombre:

```python
red_id=network_service.red_id,
```

**5. `json_simulation_repository.py` (~82)** — reemplazar `nombre_red` por `red_id` en el set de metadatos de `listar()`:

```python
campos = {"id", "timestamp", "red_id", "escenario", "run_id", "hour_index"}
```

## Notas

- **Prerrequisito:** implementar primero el auto-registro de la red antes de simular (ver *Invariante* arriba). Sin eso, `red_id` podría llegar `None` y el resto del cambio queda a medias.
- **Compatibilidad hacia atrás:** al deserializar con `SimulationResult(**data)`, los resultados viejos que traían `nombre_red` y no `red_id` tomarán el default `""` para `red_id` e ignorarán la clave sobrante. No rompe la carga, pero esos resultados quedan sin referencia estable (eran previos al invariante). Si hace falta, migrarlos aparte.
- **Para mostrar en el Dashboard:** resolver el nombre con `net_repo.nombre_de(red_id)` en el momento de renderizar.
- Actualizar, si corresponde, la sección *"Id estable vs. nombre editable"* de `doc/microgrid_arquitectura_archivos.md` para reflejar que el campo ya está implementado.
