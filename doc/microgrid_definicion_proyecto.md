# Smart Microgrid Argentina — Definición de Proyecto

## 1. Problema y Objetivos

Las distribuidoras eléctricas argentinas carecen de una herramienta open source que simule microgrids de baja tensión con datos locales reales (CAMMESA, NASA POWER, shapefiles de ENERSA/SECHEEP).

**Usuario:** técnico/ingeniero de una empresa distribuidora.  
**Valor:** simulación eléctrica rigurosa (pandapower) + datos argentinos + interfaz web interactiva (Dash), sin costo de licencia.

---

## 2. Alcance

**Dentro:**
- Carga de redes SimBench o shapefiles argentinos (datos.gob.ar)
- Perfiles de demanda horaria por tipo de consumidor, configurable carga por carga
- Generación solar (NASA POWER) y almacenamiento (baterías)
- Flujo de carga (`runpp`) y flujo óptimo (`runopp`)
- Indicadores: pérdidas, tensiones, cargabilidad, autosuficiencia, excedente exportado
- UI Dash con editor gráfico y editor de código embebido
- Caché local con actualización periódica

**Fuera:**
- Autenticación / multiusuario
- Despliegue en nube (meta futura)
- Redes de media/alta tensión
- Análisis de falla (cortocircuito, arco eléctrico)

---

## 3. Requerimientos

### Funcionales (resumen por módulo)

| Módulo         | Qué debe hacer                                                                  |
| -------------- | ------------------------------------------------------------------------------- |
| Red base       | Cargar desde SimBench o shapefile; editar parámetros gráficamente o por código  |
| Demanda        | Perfil residencial / comercial / industrial **por carga**; CAMMESA deshabilitado (ver `correcciones_2026-08.md`) |
| GD Solar       | Agregar paneles (`create_sgen`); dimensionar con irradiación NASA POWER         |
| Almacenamiento | Agregar baterías (`create_storage`) con perfil de operación configurable        |
| Simulación     | Ejecutar `runpp` y `runopp`; mostrar resultados por nodo y línea                |
| Indicadores    | Pérdidas totales, perfil de tensión, cargabilidad, autosuficiencia, excedente exportado |
| Caché          | Actualizar datos externos periódicamente sin intervención manual                |

### No Funcionales

| Atributo | Especificación |
|---|---|
| Rendimiento | `runpp` < 30 s para redes de hasta 500 nodos |
| Disponibilidad | Sesiones continuas de hasta 8 h sin reinicios |
| Escalabilidad | Código Docker-friendly para futura migración a nube |
| Portabilidad | Entorno reproducible con `requirements.txt` |
| Seguridad | Editor de código ejecuta solo en proceso local |
| Trazabilidad | Cada simulación guarda parámetros de entrada y resultados |

---

## 4. Stack Tecnológico

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.10+ |
| Simulación | pandapower, SimBench |
| Geodatos | geopandas |
| UI | Dash + Dash Cytoscape + Plotly |
| Editor de código | `dcc.Textarea` (incluido en Dash) |
| Procesamiento | pandas, requests |
| Exploración | Jupyter |
| Infraestructura | localhost → cloud (TBD) |
| Versiones | Git |

---

## 5. Persistencia

**Decisión:** archivos JSON mediados por el patrón Repository. Ningún módulo accede directamente a los archivos; toda I/O pasa por una interfaz abstracta intercambiable.

**Motivos del formato JSON:**
- `SimulationResult` contiene estructuras anidadas (`node_results`, `line_results`) que no se representan naturalmente en CSV sin aplanar o fragmentar en múltiples archivos.
- pandapower provee serialización nativa con `pp.to_json` / `pp.from_json`; forzar la red a CSV requería un workaround innecesario.
- Un archivo JSON por entidad simplifica la gestión de I/O y es legible a mano para debugging.
- La consistencia del stack pesa más que la ventaja puntual de CSV para datos tabulares simples.

| Repositorio             | Dato                         | Formato       | Ruta                  |
| ----------------------- | ---------------------------- | ------------- | --------------------- |
| `RedRepository`         | Configuraciones de red       | JSON (pp.to_json) | `data/redes/`     |
| `SimulacionRepository`  | Resultados de simulaciones   | JSON          | `data/resultados/`    |
| `DemandaRepository`     | Perfiles horarios CAMMESA    | JSON          | `data/cache/cammesa/` |
| `IrradiacionRepository` | Irradiación solar NASA POWER | JSON          | `data/cache/nasa/`    |

> Para migrar a SQL: reemplazar cada `JsonXxxRepository` por `SqlXxxRepository` con la misma interfaz. El resto del código no se modifica.
