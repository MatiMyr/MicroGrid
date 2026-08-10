# Limitación: simplificación del cálculo de SoC de baterías

**Archivo:** `src/domain/simulation_engine.py` (`_battery_soc_result`, líneas ~35-62)

> Lo implementado al momento es una **simplificación inicial** pensada para las primeras versiones. Este documento solo lista los inconvenientes; las soluciones se verán después.

## Raíz del problema

`pp.runpp` es una foto estática y trata a la batería como inyección de potencia fija: **no conoce `max_e_mwh` ni el SoC**. El balance de energía se calcula aparte, después del flujo. Motor eléctrico y contabilidad energética quedan **desacoplados**.

## Inconvenientes

- **Potencia constante toda la hora.** Asume `p_mw` fijo la hora entera; ignora que la batería pueda llenarse/vaciarse a mitad de hora.
- **Solución eléctrica imposible.** Si se llena a media hora, el clamp corrige el SoC pero las tensiones/flujos/pérdidas reportados ya se calcularon asumiendo carga la hora completa.
- **Energía sobrante desaparece.** El clamp descarta el excedente en silencio; no se exporta ni curtaila. Viola el balance de energía.
- **Descarga fantasma.** `runpp` puede descargar una batería casi vacía a plena potencia; el piso en SoC=0 no evita que esa energía inexistente ya se haya contado en el flujo.
- **Eficiencia round-trip = 100%.** Sin pérdidas de carga/descarga (real: ~10-15%). Sin autodescarga.
- **Potencia no ligada al SoC.** Una batería casi vacía puede entregar su potencia nominal sin límite.
- **Impacto en indicadores.** Autosuficiencia y curtailment dependen de estos flujos, así que arrastran el error.
- **Resolución sub-horaria no cura la raíz.** Bajar `dt` reduce la magnitud del error pero mantiene el desacople motor/contabilidad, a mayor costo de cómputo.
