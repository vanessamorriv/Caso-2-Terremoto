# Registro de verificación, correcciones y pendientes

Alcance: todos los archivos del repositorio (CSV, Excel, notebooks, README, formulación, resultados y documentos), contrastados
punto por punto con el enunciado del profesor. Primera consolidación: 30-sep-2026. **Auditoría y corrección completa: 1-oct-2026.**
**Segunda revisión técnica: 5-oct-2026** (sección 0, correcciones A14–A35), **revisión final de coherencia** (sección 0-bis, A36–A43), **módulo de calidad de datos** (sección 0-ter, A44–A45) y **revisión final con decisiones adoptadas** (sección 0-quater, A46–A54, 6-oct-2026).
Se conservaron los datos y la metodología del grupo; cada valor derivado se recalcula y se compara con los archivos originales.

## 0. Segunda revisión técnica (5-oct-2026)

Se volvieron a ejecutar ambos notebooks desde cero (notebook 01 ≈ 20 s; notebook 02 ≈ 11 min, 647 llamadas al solver = 646 óptimas +
1 infactible a propósito, 0 cortadas por tiempo) y `tools/verificar_proyecto.py` termina en "TODO CORRECTO". **De las 26 tablas de
resultados anteriores (sin contar `registro_solver.csv`, que solo cambia en tiempos), 23 son idénticas byte a byte.** Las otras tres
cambian solo por agregados o rótulos: `resumen_kpis.csv` (kits separados, A29), `todos_los_escenarios.csv` y `robustez_aperturas.csv`
(7 escenarios nuevos y 3 rótulos "B conservado"; todas las filas anteriores conservan sus valores). Se agregaron 3 tablas nuevas:
`escenarios_presupuesto_alternativo.csv`, `uso_pares_cambio_factibilidad.csv` y `parametros_revision.csv` (30 en total).

| # | Problema encontrado | Corrección | Efecto en resultados |
|---|---|---|---|
| A14 | 8 archivos `.whl` sueltos en la raíz (≈ 3,4 MB, incluido `pulp-4.0.0`). | Eliminados; `*.whl` y `results/rapido/` agregados a `.gitignore`; el verificador comprueba que no haya `.whl`. | Ninguno. |
| A15 | La hoja `Registro_cambios` del Excel (generada por el notebook 01) seguía diciendo "validado 53/53 contra copia DIVIPOLA", aunque A12 la había retirado. | Frase eliminada del notebook 01 (.py e .ipynb) y del Excel; el verificador busca "53/53" en README, docs, notebooks y todas las hojas del Excel. | Ninguno. |
| A16 | `formulacion.md` decía "el presupuesto alcanza para cerca del 31 % de la demanda". | Se reemplazó por la cifra calculada: 5.736/18.880 ≈ 30,4 %. | Ninguno. |
| A17 | README y verificador decían "633 llamadas, ninguna sin certificar", pero una era infactible. | Se reporta "N óptimas + 1 infactible a propósito"; la prueba intencional se rotula `prueba_infactible_alpha_siguiente_decima` y el notebook se detiene si aparece otra infactible. | Ejecución del 1-oct: 632 + 1. Ejecución actual: **646 + 1** (14 llamadas más por los 7 escenarios nuevos × 2 etapas). |
| A18 | La afirmación sobre PuLP 4.0 no estaba acotada a lo comprobado. | Se probó en un entorno aislado (Python 3.13, wheel `pulp-4.0.0`): `LpVariable` no acepta `cat=` ni tiene `.dicts`; **no existen** `pulp.PULP_CBC_CMD`, `pulp.LpStatus`, `pulp.LpStatusOptimal` ni `pulp.LpSolutionOptimal`; `listSolvers(onlyAvailable=True)` devuelve `[]`. README y notebook 02 citan solo eso. | Ninguno. |
| A19 | Hoja `Fuentes` con 9 fuentes, sin URL ni estado de verificación, IDs desordenados (F09 antes de F06). | Reescrita con columnas ID, Fuente, URL, Tipo, Uso en el proyecto y Verificación; 18 fuentes ordenadas (F01–F18), incluidas ABAG, OPS, DANE, DNP (CONPES 3819, **no verificada**: el sitio bloquea el acceso automatizado; respaldo secundario en Wikipedia), El Nuevo Siglo y El Blog del Ministro. Cada fuente se abrió el 5-oct-2026: El Blog del Ministro sí abrió (pasa a verificada); el RUD vía datosdelterremoto.org y el blog de El Tiempo (403) quedan **no verificados**. Se agregaron UNGRD (comunicado del apoyo y Protocolo de alojamientos) y Valora Analitik como corroboración. Se creó `docs/bibliografia.md` desde la misma tabla. | Ninguno. |
| A20 | "Observado ≈ 2–5 %" sin tabla ni fuente. | `data/raw/albergados_observados.csv` (cifras, fechas, fuente y URL) y `data/processed/tasa_albergue_observada.csv`: tasa = albergados ÷ personas en NH. Cali 0,4 %, Armenia 1,0 %, Pereira 2,3 %, Manizales 2,7 %, Dosquebradas 4,4 % (rango 0,4–4,4 %). Se aclara que las fechas no son comparables y que f = 10 % es un escenario de planeación (2,3 a 23,9 veces lo observado). | Ninguno (la demanda no cambia). |
| A21 | El escenario "solo intermedias y grandes" conservaba B = 3.547,5 M (calculado con los pequeños). | Se agrega la variante con **B recalculado** = 50 % × 6.060 M = 3.030 M; ambas se rotulan "B conservado" y "B recalculado". | Nuevos: base **4.089** (Palmira, Jamundí, Yumbo); −15 % 4.000 (Palmira, Yumbo); −30 % 3.000 (Palmira). Coinciden con la implementación independiente del verificador. |
| A22 | No se había probado la lectura en que el presupuesto cubre solo costos fijos. | R4': $\sum_j F_j y_j \le B$ como **sensibilidad** (objetivo lexicográfico igual); documentada en `formulacion.md` como lectura alternativa. | Nuevos: base 6.500 (Palmira, Tuluá, Chinchiná); −15 % 5.000 (Palmira, Cartago, Yumbo); −30 % 4.500 (Palmira, Yumbo, Chinchiná). Gasto total ≈ 111 % de B en la base. |
| A23 | README y registro decían "sin pequeños la base no cambia" sin condición. | Ahora: solo vale con B conservado; con B recalculado la base baja a 4.089. | Texto. |
| A24 | 49 pares OSRM entre 140 y 160 km sin verificar con Google Maps (la razón Google/OSRM llegó a 1,14). | Uno ya era control (Buenaventura–Palmira); los **48 restantes se consultaron en Google Maps el 5-oct-2026** con la misma metodología (`data/raw/google_maps/verificacion_google_maps_140_160km.csv`, URL por par). Razón 0,898–1,078, mediana 1,005, máximo 168 km: **ninguno cambia de factibilidad**. No reemplazan a OSRM en la matriz final (12 consultas muestran rutas que evitan cierres temporales y la fecha difiere de la del 1-oct); se usan en la matriz alternativa `distancias_km_alt_google_140_160.csv`. | Arcos factibles: 308 (sin cambio). Con la matriz alternativa la red base no cambia (5.736; Palmira, Tuluá). |
| A25 | No se declaraba que 3 de los 7 pares que cambian de factibilidad están a ≤ 3 km del corte. | Se declaran (Armenia–Pradera 178, El Cairo–Buga 181, Caicedonia–Supía 178; Google muestra km enteros desde 100 km) y se agrega la tabla `uso_pares_cambio_factibilidad.csv`; el notebook se detiene si alguno se usa en base, −15 % o −30 %. | Ninguno: no se usan en base, −15 % ni −30 % (asignación más larga 89,1 km) ni en sensibilidades o fronteras de equidad. |
| A26 | El criterio de "ciudad cercana" estaba implícito. | Definido: al menos un municipio afectado a ≤ 180 km por carretera. Se reporta por candidato en `resumen_alcance.csv` (municipios alcanzados y pares que dependen de Google) y en el README. La Dorada alcanza solo a Manizales y Villamaría y depende de dos valores de Google Maps (166 y 165 km). | Ninguno (17 de 17 cumplen). |
| A27 | El piso departamental α se presentaba como la propuesta principal. | β (piso municipal) pasa a ser la **variante recomendada** y α el complemento: con α = 25 % quedan 22 municipios en 0 %; β = 2,5 % los elimina por 49 personas y conserva la red Palmira–Tuluá. No se eliminó ninguna extensión. | Texto y figura 10 (marca de β recomendado); cifras sin cambio. |
| A28 | Los umbrales 50/100/150/180 km solo se declaraban. | Se justifica cada uno en el notebook 02 (sección 6.4) y en el README. | Ninguno. |
| A29 | v = 60.000 era un solo parámetro y los KPI repartían 30.000 + 30.000. | Kit de alimentación (29.730) y kit de aseo (29.730) son parámetros explícitos (`metadatos_instancia.json`, hoja `Parametros` P25–P27 del Excel, notebooks y KPI); 60.000 se declara como redondeo (+540 COP/persona). | El modelo sigue usando v = 60.000. En `resumen_kpis.csv`, kits de alimentación y de aseo de la base pasan de 172,1 M a **170,5 M** cada uno y aparece "ajuste por redondeo" 3,1 M; el costo de atención (344,2 M) y el total no cambian. |
| A30 | El Excel no tenía hoja de lectura ni diccionario de datos. | Hojas `LEEME` (primera) y `Diccionario` (archivo, columna, descripción, unidad, tipo Real/Calculado/Supuesto/Identificador) y `docs/diccionario_datos.md`, generados por el notebook 01 desde la misma tabla; el notebook comprueba que cubran todas las columnas. | Ninguno. |
| A31 | Instalación manual y ejecución larga sin alternativa; un f-string anidado exigía Python ≥ 3.12 aunque el README decía ≥ 3.10. | Celda inicial que instala `pulp>=2.8,<4` y `highspy` si faltan; bandera `RAPIDO` (≈ 6 min, escribe en `results/rapido/`); versiones probadas documentadas (Python 3.13, PuLP 3.3.2, highspy 1.15.1); f-string corregido (sintaxis válida en 3.11). | Ninguno en modo completo. |
| A32 | $c_f$ sin referencia pública. | Búsqueda: el Protocolo de alojamientos temporales de la UNGRD (2024) no publica costos (sí 3,5 m²/persona); el Manual Esfera no se pudo abrir (403) y es una norma de estándares, no de costos; en una búsqueda breve no se hallaron contratos públicos con costo por plaza. **Se mantiene como supuesto débil**, con la sensibilidad de $c_f$ con B fijo (3.000–9.767 atendidos). | Ninguno. |
| A33 | README sin integrantes ni licencia. | Se agregan como PENDIENTE (grupo). Los campos PENDIENTE (grupo) de `uso_ia.md` no se completaron (solo el grupo los conoce); se agregó la fase 11 (esta revisión). | Ninguno. |
| A34 | No había un informe técnico separado de la presentación. | `docs/informe_tecnico.md`: contexto, datos, supuestos, formulación, resultados, escenarios, extensión, conclusiones y pendientes. | Ninguno. |
| A35 | El verificador no cubría fuentes, Excel, escenarios nuevos ni frases desactualizadas. | `tools/verificar_proyecto.py` comprueba además: ausencia de `.whl` y de "53/53"; Fuentes con URL, IDs ordenados, ABAG/OPS/DNP; bibliografía y diccionario; Excel con 0 errores y valores en caché; 308 arcos; 48 pares de 140–160 km; re-solución independiente de B recalculado y R4'; cifras fijas (5.736, 4.500, 4.000, 90/89 km, α\* 29,05 %, β\* 27,05 %, 250, 49, 9.767/3.000, 3.547,5/3.015,4/2.483,2 M) y del README; frases prohibidas. | El Excel recalculado tiene 428 fórmulas, 0 errores. |

## 0-quinquies. Redacción del notebook 02 y textos pendientes (7-oct-2026)

| # | Cambio | Detalle | Efecto en resultados |
|---|---|---|---|
| A55 | Celdas Markdown del notebook 02 reescritas | Se reescribieron las 26 celdas de texto con una redacción más directa y propia del grupo. Se conservan todas las tablas, fórmulas, cifras, escenarios, sensibilidades y la extensión α/β; el código no cambia. | Ninguno |
| A56 | Textos que aún decían "pendiente del profesor" | Notebook 02 (índice, sección 9 y prueba "Solo ciudades intermedias o grandes" de la validación previa), nota de la hoja `Candidatos` del Excel procesado (notebook 01), `docs/informe_tecnico.md` y `docs/uso_ia.md`. Las tres decisiones (17 candidatos, presupuesto sobre el costo total y matriz Google Maps/OSRM) quedan como definitivas. El verificador ahora rechaza esas frases. | Solo cambia el texto del detalle de esa prueba en `validaciones.csv` |

Ejecución: ambos notebooks se volvieron a ejecutar. Los CSV de `data/processed/` y 29 de las 31 tablas de `results/tablas/` son idénticos
byte a byte; `validaciones.csv` cambia solo en el texto indicado y `registro_solver.csv` solo en los tiempos (652 llamadas, mismos
modelos, etapas y estados). `tools/verificar_proyecto.py`: TODO CORRECTO.

## 0-quater. Revisión final y decisiones adoptadas (6-oct-2026)

Las tres lecturas ambiguas del enunciado dejan de estar pendientes: se adoptan **17 candidatos (con 10 pequeños)**, **presupuesto sobre el
costo total (R4)** y **matriz combinada Google Maps/OSRM**; las alternativas quedan como sensibilidad. Una auditoría crítica independiente
encontró además lo siguiente, ya corregido:

| # | Problema encontrado | Corrección | Efecto en resultados |
|---|---|---|---|
| A46 | Se afirmaba que los arcos que cambian de factibilidad no se usan "en ninguna solución", pero el chequeo omitía la curva de presupuesto, el contrafactual y la cuadrícula de $c_f$. Con ×3,5–×4 del presupuesto (y en el contrafactual de La Dorada) se usan Manizales–La Dorada y Villamaría–La Dorada. | El chequeo revisa ahora todas las soluciones (escenarios, sensibilidades, fronteras, curva, contrafactual, $c_f$, α\* por escenario). Se declara que la cota física de 16.000 depende de esos dos valores de Google (con solo OSRM: 15.500). | Ninguno en base, −15 % y −30 %. Nueva fila `cota_fisica_solo_osrm` = 15.500 en `parametros_revision.csv`. |
| A47 | "Con equidad el límite de 180 km sí empieza a importar": no se había comprobado. | Se resuelve sin límite de distancia: α\* sigue en 29,05 % y con β = 2,5 % se atienden 5.687, igual que con el límite. El texto dice ahora que el límite no es activo, aunque los traslados llegan a 171–172 km. | 2 resoluciones más; resultados iguales. |
| A48 | Se decía que Pereira no recibe cupos porque "su campamento más barato está más lejos". Pereira está a 30 km de Cartago y 33 km de Chinchiná. | La causa es el costo: esos sitios son intermedios o pequeños (600.000–690.000 COP por plaza frente a 510.000), y el grande más cercano (Tuluá) está a 117 km. | Texto. |
| A49 | El contrafactual rotulaba "Indispensable" a Palmira y Tuluá, aunque cerrarlas cuesta solo 236 personas (4,1 %); el texto llamaba a Palmira "núcleo robusto". | Rótulo "Abierto en el óptimo: cerrarlo y re-optimizar cuesta…"; Palmira es "la decisión más estable frente a recortes, aunque no imprescindible". | Cambia la columna `explicación` de `contrafactual.csv` (2 filas). |
| A50 | Con −15 % el piso α\* = 23,82 % no cuesta ninguna persona, pero el escenario se reportaba solo con la red de costo mínimo (26 municipios en 0 %). | Se recomienda explícitamente la red equitativa (Tuluá, Cartago, Chinchiná: mismas 4.500 personas, 10 municipios en 0 %) en el notebook, el README y las conclusiones. | Texto. |
| A51 | Los porcentajes dentro de umbrales usaban como base a los atendidos ("100 % a ≤ 100 km") y podían leerse como cobertura total. | Nuevos KPI "% de la demanda total atendida a ≤ X km" (base: 20,3 % a ≤ 50 km y 30,4 % a ≤ 100 km). | 4 filas nuevas en `resumen_kpis.csv` y columnas en `todos_los_escenarios.csv`. |
| A52 | Las tablas de parámetros no definían $c_f$, $T$ ni $\phi_j$ como símbolos; la base de $c_f$ ("40–55 % del apoyo por persona") suponía ≈ 2,1 personas por hogar sin decirlo. | Símbolos con valor y unidad en el notebook 02 y en `formulacion.md`; supuesto de 2,1 personas por hogar (promedio RUD) declarado. Se declaran también el kit único para los 3 meses y el transporte de ida. | Texto. |
| A53 | Textos fijos en el módulo de calidad (C03 "17/17" con 18 filas; G04 "acceso a Pensilvania" con 2 pares que no lo son; G09 y G11 con valores fijos) y en el notebook (fila "α = 25 %" por posición; etiqueta α\*; β guardado como 0,0250001). | Todo se calcula desde los datos. | `parametros_revision.csv`: `beta_recomendado` = 0,025. |
| A54 | El README tipificaba el costo de kits como "Dato" y decía que `resultados_modelo.xlsx` tiene "todas las tablas". | "Supuesto (precio minorista de prensa)"; la tabla de calidad está en el Excel de datos. | Texto. |

Ejecución final: 652 llamadas al solver (651 óptimas + 1 infactible a propósito); 23 de las 26 tablas originales idénticas y las otras con
cambios solo en filas o columnas nuevas o rótulos (`resumen_kpis`, `todos_los_escenarios`, `robustez_aperturas`, `contrafactual`,
`validaciones`).

## 0-ter. Módulo de calidad de datos (6-oct-2026)

| # | Problema encontrado | Corrección | Efecto en resultados |
|---|---|---|---|
| A44 | Las pruebas de datos estaban dispersas (asserts del notebook 01, validación previa del notebook 02, verificador) y no había una tabla única que mostrara las debilidades de los datos. | `tools/calidad_datos.py`: 39 pruebas PASS / WARNING / FAIL sobre demanda, candidatos, parámetros, coordenadas, distancias y fuentes. El notebook 01 la genera (`results/tablas/calidad_datos.csv`, hoja `Calidad_datos` del Excel, `data/processed/fuentes.csv`) y se detiene con un FAIL; el notebook 02 la recalcula, exige que coincida y no optimiza con un FAIL; el verificador la recalcula y la compara con el CSV y el Excel. | **27 PASS, 12 WARNING, 0 FAIL.** Ninguna tabla de resultados cambia (la nueva tabla es la 31). |
| A45 | El módulo mostró dos debilidades no documentadas: Calarcá tiene 15,3 familias registradas por vivienda no habitable (Sevilla 9,5), lo que sugiere que la regla "una familia por vivienda" subestima su demanda; y Argelia y El Cairo tienen registrado más del 65 % de su población en el RUD. Además, **16 pares** (no 3) están a ≤ 3 km del corte de 180 km; "3" era solo entre los 7 que cambian de factibilidad. | Se declaran como WARNING (D09, D10, G10) y se corrige la limitación en el informe y en este registro. No se cambian datos del grupo. | Ninguno: ninguna solución reportada usa un arco de más de 173 km. |

## 0-bis. Revisión final de coherencia (5-oct-2026, tarde)

Una revisión independiente de todo el repositorio contra el enunciado y las tablas no encontró errores en cifras ni en fórmulas; sí
estas inconsistencias de texto, que se corrigieron. Se volvieron a ejecutar ambos notebooks: las tablas de resultados no cambian
(solo el rótulo de una prueba en `validaciones.csv` y el nombre de la prueba infactible en `registro_solver.csv`).

| # | Problema encontrado | Corrección | Efecto en resultados |
|---|---|---|---|
| A36 | README e informe decían que los candidatos están "fuera de los municipios afectados", pero los 17 tienen algunas viviendas no habitables (NH de 3 a 229; filtro S2: NH < 250). | Se precisa la definición del grupo: ningún candidato es uno de los **29 municipios de demanda** (afectados con NH ≥ 400); pueden tener daños menores. Rótulo de la prueba de datos ajustado. | Ninguno (solo el texto de una fila de `validaciones.csv`). |
| A37 | El notebook 02 decía que la asignación más larga (173 km) aparece "con presupuesto ≥ ×3,0"; en `formacion_red.csv` con ×3,0 es 156,1 km y 173 km llega con ×3,5. | Texto generado desde el nivel donde ocurre el máximo; se aclara que desde ×3,0 ya supera 150 km. | Ninguno. |
| A38 | El notebook 02 seguía diciendo "≈ 15 min". | ≈ 11 min (tiempo medido). | Ninguno. |
| A39 | Se describía la prueba infactible como "α\* + 0,1 pp", pero el código prueba la siguiente décima de punto (29,1 %, es decir α\* + 0,049 pp, una prueba más estricta). | Redacción corregida en README, formulación, registro, notebook y verificador; la prueba se rotula `prueba_infactible_alpha_siguiente_decima`. | Ninguno. |
| A40 | Textos desactualizados en el Excel: nota de la hoja `Candidatos` ("distancias OSRM"), fila "Distancias" de `Registro_cambios` ("Matriz OSRM 29×18") y nota de P03 sin mencionar el redondeo. | Corregidos desde el notebook 01. | Ninguno. |
| A41 | Notación: el conjunto A usaba $d_{ij}$ (choca con la demanda $d_i$) y el notebook 01 escribía $f_j$ (choca con la fracción $f$). | $\delta_{ij}$ para distancia y $F_j$ para costo fijo en todos los textos. | Ninguno. |
| A42 | README y formulación decían que todo corte por tiempo detiene el notebook, pero en las pruebas de factibilidad de pisos una solución entera factible basta (es lógicamente correcto). `uso_ia.md` hablaba solo de CBC. | Se documenta la excepción; "el solver (CBC o HiGHS)". | Ninguno. |
| A43 | El verificador aceptaba ≥ 11 figuras y buscaba frases exactas (no detectaba "cerca del **31 %**" en negrita). El diagnóstico del notebook 02 decía "cerca del 31 %" (una cota aproximada) y podía confundirse con el 30,4 % atendido. | Verificador: exactamente 11 figuras, búsqueda sin negritas ni mayúsculas y nuevas frases prohibidas. El diagnóstico dice ahora "cota aproximada de 31 %". | Ninguno. |

## 1. Correcciones de la auditoría del 1-oct-2026

| # | Problema encontrado | Corrección | Efecto en resultados |
|---|---|---|---|
| A1 | `requirements.txt` pedía `pulp>=2.7`. Se comprobó instalando PuLP 4.0.0 que `LpVariable(cat=...)` y `LpVariable.dicts` fallan (el resto se verificó en A18). | `pulp>=2.8,<4` (≥ 2.8 por la interfaz `pulp.HiGHS`) y `highspy`; README actualizado. | Ninguno; el notebook vuelve a ser instalable y ejecutable. |
| A2 | El estado del solver se leía solo con `LpStatus`. PuLP devuelve "Optimal" aunque CBC/HiGHS se detengan por `timeLimit`. **Se reprodujo el problema:** con el presupuesto ×3,0, CBC (1 hilo, 120 s) se cortó y PuLP reportó "Optimal". | Función `estado_solucion` que exige `LpStatus == Optimal` **y** `sol_status == LpSolutionOptimal`; `exigir_optimo` detiene el notebook si no hay certificado; prueba T9; registro de todas las llamadas en `results/tablas/registro_solver.csv`; límite de 600 s. | Ejecución del 1-oct: 633 llamadas = 632 óptimas + 1 infactible a propósito (prueba de que el piso de la siguiente décima, 29,1 %, es infactible); 0 cortadas por tiempo. |
| A3 | Distancias: los 8 pares de control estaban "PENDIENTE" de cotejar con Google Maps. | Se consultaron **164 pares** en Google Maps (1-oct-2026, modo carro, primera ruta): los 139 pares OSRM entre 160 y 230 km, 16 controles y 9 rutas de montaña > 230 km. En esos pares la matriz final usa Google Maps; en el resto, OSRM. Hoja `Control_distancias` completa con URL por par. | Mediana Google/OSRM = 1,005. 7 pares cambian de factibilidad a 180 km. Arcos factibles: 307 → 308. Base: 5.733 → **5.736** atendidos, distancia máxima 93,4 → **89,1 km**, municipios sin atención 14 → **15**. |
| A4 | **La Dorada** figuraba "sin ningún municipio a ≤ 180 km (213,8 km)". | Google Maps da Manizales–La Dorada **166 km** y Villamaría–La Dorada **165 km** por la Ruta 50 (Letras–Fresno–Mariquita–Honda); calculadoras independientes dan 170–172 km. OSRM elegía un rodeo por el sur. | **17 de 17 candidatos son útiles** (antes 16). La Dorada no se abre en la base, pero sí en presupuestos ≥ ×3,5. |
| A5 | α\* se publicaba como "29 %" con 0 decimales (con la matriz anterior α\* = 28,94 %, así que 29 % era infactible), y la columna se llamaba "Extensión α=29 %". | α\* se calcula como **MILP max α directo** (HiGHS, certificado) en lugar de bisección con tolerancia 0,1 pp; se comprueba que el piso de la siguiente décima de punto es infactible; todos los pisos máximos se muestran **truncados hacia abajo** (`pct_abajo`) con 2 decimales. | Con la matriz corregida, **α\* = 29,05 %** (29,1 % es infactible); precio de la equidad 256 → **250** personas. |
| A6 | El piso municipal β estaba "formulado, no implementado". | Familia E3 $\sum_j x_{ij}\ge\beta d_i$ implementada; β\* por MILP directo; frontera β y α\*(β). | β\* = **27,05 %**; con β = 2,5 % ningún municipio queda en 0 % a cambio de 49 personas. |
| A7 | Riesgo de que la solución base parezca trivial; la frase "ni la capacidad ni la distancia son activas" era imprecisa (Palmira está llena: su R2 es activa). | Nuevas secciones 7.2–7.4: curva de presupuesto hasta ×4 con prueba de relajación (B +10 %, K +10 %, sin límite de distancia), barrido de distancia máxima 40–250 km (umbral), cinco mejores redes con cortes *no-good*. Narrativa corregida. | Umbral de distancia: la red base aparece desde **90 km** (antes se citaba ≈ 94 km con OSRM). Presupuesto limita hasta ×3,0; desde ×3,5 se abren los 17 sitios y manda la capacidad total (16.000). La distancia no es activa en ningún nivel. |
| A8 | Sensibilidad de $c_f$ solo con $B$ que escala con $c_f$, lo que da el resultado contraintuitivo "más caro ⇒ más atendidos". | Se agrega la lectura con **$B$ fijo en COP** (72 combinaciones adicionales). | Con $B$ fijo: 9.767 atendidos con $c_f$ = 100.000 y 3.000 con $c_f$ = 400.000. |
| A9 | Faltaba sensibilidad a supuestos débiles. | Nuevos casos: f = 8,3 % y 11,6 % (rango ABAG/Hazus), φ = 1 (sin economías de escala), $c_f$ ±25 % con $B$ fijo, matriz solo OSRM, distancia máxima 120 km. | f ≥ 5 % ⇒ 5.500–5.822 atendidos; φ = 1 cambia la red a 7 sitios pequeños/intermedios; matriz solo OSRM ⇒ misma red (5.733). |
| A10 | Narrativa con valores fijos en el texto (p. ej. "Palmira recibe… de Cali", "2 campamentos grandes", "Tuluá C02", "α = 29 %"). | Todo el texto interpretativo del notebook se genera desde los resultados; README reescrito con las cifras nuevas; `verificar_proyecto.py` revisa 40+ cifras, la versión de PuLP, el registro del solver, la hoja de control y que α\* no se redondee a 29 %. | Coherencia README ↔ CSV ↔ Excel ↔ notebook comprobada automáticamente. |
| A11 | La tabla de redes alternativas se describía como "combinaciones que suman 5.500 plazas" (texto fijo) y el contrafactual decía "entre X y Y" aunque todos los cambios costaban lo mismo. | Texto dinámico; se aclara que todas las alternativas de un solo cambio caen en redes de 5.500 plazas llenas. | — |
| A12 | Afirmación no reproducible "53/53 coordenadas coinciden con la copia DIVIPOLA del proyecto de referencia" (archivo no incluido). | Se retiró; se documenta la limitación de usar la cabecera municipal (sección 5 del notebook 01 y README). | — |
| A13 | `uso_ia.md` cubría solo la consolidación. | Declaración por fase técnica (10 fases); las fases que solo el grupo conoce quedan como PENDIENTE (grupo). | — |

## 2. Lo que se verificó y está correcto

| Elemento | Verificación | Resultado |
|---|---|---|
| Población DANE 2026 | 47 municipios contra PPED 2018-2042 (act. 30-jul-2025) | 47/47 coinciden exactamente |
| Demanda | Tamaño de hogar, personas en NH, $d_i$ con f = 2/5/10/13 %, hogar 3,0 y % registrado | Sin diferencias (redondeo tipo Excel) |
| Requisitos de la instancia | ≥ 20 municipios (29), Cali y Pereira, ≥ 15 candidatos (17, todos útiles), ninguno en municipio afectado | Cumple |
| Candidatos | Categoría, capacidad, costo fijo, costo variable y filtros S2/S7 desde la hoja `Parametros` | Coinciden |
| Presupuesto | 50 % × $7.095 M = $3.547,5 M; −15 % = $3.015,4 M; −30 % = $2.483,2 M | Coincide con Excel y CSV (Excel recalculado con LibreOffice) |
| Re-solución independiente | `tools/verificar_proyecto.py` con una implementación mínima en CBC | Reproduce atendidos, sitios y costo de la base |

## 3. Correcciones de la consolidación del 30-sep-2026 (vigentes)

| # | Antes | Ahora |
|---|---|---|
| C1 | Tabla `sensibilidad_costo_fijo_preliminar.csv` con distancias no documentadas | Recalculada con el MILP (51 de 72 combinaciones coinciden; máx. diferencia 459 personas) |
| C2 | Notebook de coordenadas sin ejecutar, con rutas a la misma carpeta | `01_datos_coordenadas_distancias.ipynb` con rutas relativas, sin internet y con opción de re-consulta |
| C3 | Excel con "Coordenadas y distancias: PENDIENTES" | Hojas `Coordenadas`, `Distancias_km` (final), `Distancias_OSRM`, `Alcance_180km`, `Control_distancias`, `Fuentes`, `Registro_cambios` |
| C4 | Costo variable documentado como 29.730 + 29.730 | Se mantiene 60.000 y se documenta que la suma es 59.460 (+0,9 %) |

## 4. Decisiones metodológicas adoptadas (6-oct-2026)

1. **(a) Candidatos pequeños: se mantienen los 17 (10 pequeños).** La lectura literal ("ciudades intermedias o grandes") deja solo 7
   municipios elegibles y el enunciado exige ≥ 15; además define capacidad para "municipios pequeños". Sensibilidad: sin pequeños, con B
   conservado la base no cambia (5.736) y con B recalculado (3.030 M) baja a 4.089.
2. **(b) Presupuesto sobre el costo total (R4).** Es la lectura de "presupuesto total" y "máximo disponible". Sensibilidad: R4' (solo
   costos fijos) daría 6.500 atendidos gastando ≈ 111 % de B.
3. **(c) Matriz combinada Google Maps/OSRM.** Google se usa en la franja donde se decide la factibilidad (160–230 km) y corrige el ruteo
   de OSRM a La Dorada. Sensibilidad: con solo OSRM la red no cambia (5.733 atendidos; cota física 15.500 en lugar de 16.000).

## 5. Supuestos que siguen siendo débiles

- $c_f$ = 200.000 COP/plaza-mes y φ = 0,85/1,00/1,15: sin fuente colombiana (búsqueda documentada en A32); los resultados son sensibles a ambos.
- f = 10 %: escenario de planeación (ABAG 2017 con Hazus: 11,6 %, 8,3–13,2 % por condado; % de desplazados que busca refugio, demografía de
  EE. UU.), no tasa observada en Colombia (observada 0,4–4,4 % de las personas en NH, con fechas no comparables; A20).
- RUD de un agregador secundario (no verificado en esta revisión) y registro abierto; una familia por vivienda no habitable.
- Un kit de alimentación y uno de aseo por persona para todo el periodo (literal del enunciado); precios minoristas de una fuente no
  verificada (403), corroborados solo en orden de magnitud.
- Distancias sin cierres viales posteriores al sismo; un punto (cabecera) por municipio; 16 pares a ≤ 3 km del corte de 180 km (11 factibles; ninguno usado: la asignación más larga de
  cualquier solución reportada es de 173 km).
