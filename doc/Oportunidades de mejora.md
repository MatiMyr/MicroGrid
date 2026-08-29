# Oportunidades de mejora

Ideas de mejora identificadas pero **no priorizadas**: no bloquean el uso del
proyecto y se dejan para más adelante.

Se distinguen de `doc/Anotaciones revision/`, que documenta cambios pendientes y
limitaciones que sí afectan la corrección de los resultados.

---

## 1. Reemplazar el `dcc.Textarea` por un editor de código real

**Archivo:** `src/ui/editor.py` (acordeón *Editor de código Python*, `dcc.Textarea(id="ed-code", ...)`)

### Situación actual

El editor de código embebido es un `dcc.Textarea` con estilo propio
(`textarea.code` en `src/assets/app.css`: fuente monoespaciada, `tab-size: 4`).
Funciona —el usuario edita el script que devuelve `NetworkService.generar_codigo()`
y lo aplica con «Ejecutar código»— pero es una caja de texto plana.

### Qué falta

- Resaltado de sintaxis.
- Números de línea. Hoy, cuando `aplicar_codigo` falla con un `SyntaxError:
  line N`, no hay forma de ubicar la línea N en el textarea.
- Indentación automática, plegado de bloques, paréntesis emparejados,
  buscar/reemplazar, autocompletado.
- **La tecla Tab mueve el foco al siguiente control en vez de indentar.** En
  Python, donde la indentación es sintaxis, esto obliga a indentar con barra
  espaciadora.

### Por qué no se implementa ahora

Las dos opciones que figuraban en el stack del proyecto no son viables (revisado
contra PyPI en agosto de 2026):

| Paquete | Estado |
|---|---|
| `dash-codemirror` | **No existe en PyPI.** Nunca fue un paquete real. |
| `dash-ace` | Existe (v0.2.1) pero su última publicación es de **enero de 2020**, de la época de Dash 1.x. |

Los componentes custom de Dash empaquetan su propio build de React y se registran
contra la API de componentes de la versión con la que se compilaron. Montar uno de
2020 sobre el **Dash 4.4.1** del proyecto es un riesgo de compatibilidad real.

Lo que sigue mantenido hoy (`dash-mantine-components`) ofrece resaltado de código
**para mostrar**, no para editar; no cubre este caso.

### Direcciones posibles (no implementar aún)

- **Opción barata:** un callback clientside que capture la tecla Tab e inserte
  cuatro espacios. Resuelve la molestia más concreta sin agregar dependencias.
- **Opción completa:** escribir un componente Dash propio sobre CodeMirror 6 o
  Monaco, compilado contra la versión de Dash en uso. Es trabajo de front-end
  ajeno al dominio eléctrico del proyecto.

### Prioridad

**Baja.** El editor de código es una vía secundaria de edición: el flujo
principal (formularios y panel de detalle por bus) no depende de él. El valor del
proyecto está en la simulación eléctrica y en los datos argentinos, no en la
ergonomía del textarea.
