# Limitación: simplificación del cálculo de SoC de baterías

**Archivo:** `src/domain/simulation_engine.py` (`_battery_soc_result`, líneas ~44-77)

> Lo implementado al momento es una **simplificación inicial** pensada para las primeras versiones. Este documento solo lista los inconvenientes; las soluciones se verán después.

> **Corregido en agosto de 2026 — convención de signo.** Una versión previa de este documento y del código afirmaba que en `res_storage.p_mw` *positivo = descarga*. Es al revés. pandapower modela el `storage` con **convención de carga** (ver `pandapower/create/storage_create.py`): `p_mw > 0` significa que la batería **consume** de la red (se carga) y `p_mw < 0` que **inyecta** (se descarga). El código integraba la energía restando (`e1 = e0 - p·dt`), así que el SoC se movía al revés: una batería cargando se vaciaba y llegaba a 0 % en dos horas. Ahora integra sumando (`e1 = e0 + p·dt`) y el test `tests/test_bateria_signo.py` ata el signo al balance de potencia, no a la documentación.
>
> Los inconvenientes de abajo siguen vigentes: son limitaciones del modelo, independientes del signo.

## Raíz del problema

`pp.runpp` es una foto estática y trata a la batería como inyección de potencia fija: **no conoce `max_e_mwh` ni el SoC**. El balance de energía se calcula aparte, después del flujo. Motor eléctrico y contabilidad energética quedan **desacoplados**.

## Inconvenientes

- **Potencia constante toda la hora.** Asume `p_mw` fijo la hora entera; ignora que la batería pueda llenarse/vaciarse a mitad de hora.
- **Solución eléctrica imposible.** Si se llena a media hora, el clamp corrige el SoC pero las tensiones/flujos/pérdidas reportados ya se calcularon asumiendo carga la hora completa.
- **Energía sobrante desaparece.** El clamp descarta el excedente en silencio; no se exporta ni se recorta. Viola el balance de energía.
- **Descarga fantasma.** `runpp` puede descargar una batería casi vacía a plena potencia; el piso en SoC=0 no evita que esa energía inexistente ya se haya contado en el flujo.
- **Eficiencia round-trip = 100%.** Sin pérdidas de carga/descarga (real: ~10-15%). Sin autodescarga.
- **Potencia no ligada al SoC.** Una batería casi vacía puede entregar su potencia nominal sin límite.
- **Impacto en indicadores.** Autosuficiencia y excedente exportado dependen de estos flujos, así que arrastran el error.
- **Resolución sub-horaria no cura la raíz.** Bajar `dt` reduce la magnitud del error pero mantiene el desacople motor/contabilidad, a mayor costo de cómputo.
