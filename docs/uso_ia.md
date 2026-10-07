# Declaración de uso de inteligencia artificial

El enunciado pide declarar el uso que el grupo dio a la IA. Esta declaración cubre **todas las fases técnicas** del proyecto. Las
filas marcadas **PENDIENTE (grupo)** describen fases en las que solo el grupo sabe si usó IA y cómo; deben completarse antes de la
entrega. No se inventó ningún uso que no esté documentado en el repositorio.

**Herramienta usada en las fases documentadas:** Claude (Anthropic), como asistente de programación, revisión técnica y redacción,
en sesiones de trabajo del 30-sep-2026 (consolidación), 1-oct-2026 (auditoría y corrección) y 5-oct-2026 (segunda revisión técnica:
fuentes, escenarios pendientes del profesor, distancias de 140–160 km y documentación).

## 1. Uso por fase

| Fase técnica | ¿Se usó IA? | Para qué | Qué decidió o verificó el grupo |
|---|---|---|---|
| 1. Selección de la zona, municipios afectados y criterios S1–S7 | **PENDIENTE (grupo)** | Completar si se usó IA para buscar fuentes (RUD, DANE) o proponer filtros | La selección de los 29 municipios, los filtros S1–S7 y los umbrales son decisiones del grupo (hoja `Parametros`) |
| 2. Estimación de la demanda ($f$, tamaño de hogar) | **PENDIENTE (grupo)** | Completar si se usó IA para encontrar las referencias ABAG/Hazus o el RUD | $f$ = 10 % y su rango de sensibilidad son decisión del grupo |
| 3. Candidatos, capacidades y costos ($c_f$, φ, kits) | **PENDIENTE (grupo)** | Completar si se usó IA para buscar precios de kits o referencias de costo fijo | $c_f$, φ y el costo del kit son supuestos del grupo; la IA solo recalculó y verificó los valores |
| 4. Coordenadas y distancias | Sí (Claude) | Descargar coordenadas DIVIPOLA y la matriz OSRM; programar la validación (razón carretera/recta, alcance a 180 km); **consultar 164 pares en Google Maps** mediante el navegador integrado de la aplicación (1-oct-2026) y construir la matriz final | El grupo debe revisar por muestreo la hoja `Control_distancias` (cada fila tiene la URL de la consulta) |
| 5. Formulación matemática | Sí (Claude) | Redactar la formulación indexada (conjuntos, parámetros, variables, objetivo lexicográfico, R1–R6, dominios) a partir de las decisiones del grupo, y la extensión de equidad (α, E1–E3) | El grupo debe validar que la formulación representa su caso y poder explicarla en la sustentación |
| 6. Implementación en Python/PuLP | Sí (Claude) | Escribir los notebooks 01 y 02, las funciones indexadas, las pruebas automáticas (T1–T9), la verificación de estado del solver (`LpStatus` + `sol_status`) y `tools/verificar_proyecto.py` | El grupo debe ejecutar los notebooks completos y revisar que entiende cada bloque |
| 7. Resultados, escenarios y sensibilidad | Sí (Claude) | Ejecutar el modelo, generar tablas y figuras, la curva de presupuesto hasta ×4, las pruebas de relajación, el umbral de distancia, las redes casi óptimas y las sensibilidades | Las reducciones de −15 % y −30 % y el criterio de pérdida máxima de 5 % para proponer un piso son decisiones del grupo |
| 8. Auditoría y corrección (1-oct-2026) | Sí (Claude) | Comparar el proyecto con el enunciado, detectar errores e inconsistencias, corregirlos y volver a ejecutar todo (ver `docs/registro_correcciones.md`) | El grupo debe revisar cada corrección y las decisiones marcadas PENDIENTE para el profesor |
| 9. Documentación | Sí (Claude) | Redactar README, `formulacion.md`, `registro_correcciones.md` y este documento | El grupo debe ajustar la redacción final |
| 10. Presentación PDF | **PENDIENTE (grupo)** | Fuera del alcance de esta revisión técnica | — |
| 11. Segunda revisión técnica (5-oct-2026) | Sí (Claude) | Abrir y verificar las fuentes (hoja `Fuentes`, `docs/bibliografia.md`; las que no se pudieron abrir quedan "No verificada"); construir la tabla de albergados observados; **consultar en Google Maps los 48 pares OSRM de 140–160 km** con el navegador integrado de la aplicación; comprobar en un entorno aislado qué falla en PuLP 4.0; programar los escenarios "sin pequeños con B recalculado" y R4', el chequeo de arcos frágiles, el modo rápido, el diccionario de datos y el informe técnico; volver a ejecutar todo y extender `tools/verificar_proyecto.py` | El grupo debe revisar por muestreo `verificacion_google_maps_140_160km.csv` (URL por par) y decidir con el profesor los tres PENDIENTES (candidatos pequeños y B; alcance del presupuesto; matriz combinada) |

## 2. Controles aplicados al trabajo asistido por IA

- Cada valor derivado (demanda, costos, presupuesto, población DANE) se recalcula en el notebook 01 y se compara con los archivos
  originales del grupo; si no coincide, el notebook se detiene.
- Las distancias de OSRM se contrastaron con Google Maps en 164 pares (1-oct) y en los 48 pares de 140–160 km (5-oct); los valores y
  las URL quedan en `data/raw/google_maps/`.
- Cada fuente se marcó como verificada solo si se abrió; las demás (RUD vía datosdelterremoto.org, El Tiempo, CONPES 3819) quedan
  como "No verificada" y no se les atribuyó ninguna cifra nueva.
- El modelo se resolvió con una implementación independiente mínima (`tools/verificar_proyecto.py`) que reproduce el escenario base y
  las lecturas alternativas del presupuesto (sin pequeños con B recalculado; R4').
- Ningún resultado se reporta si el solver (CBC o HiGHS) no certifica optimalidad (`LpStatus` y `sol_status`); el registro de todas las llamadas está en
  `results/tablas/registro_solver.csv`.
- Las cifras del README se comprueban automáticamente contra las tablas exportadas.

## 3. Responsabilidad

La IA no tomó decisiones de modelado sustantivas sin dejarlas explícitas: los supuestos del grupo se conservaron y las decisiones que
dependen del profesor quedaron marcadas como PENDIENTE. El grupo es responsable de revisar, entender y poder defender todo el
contenido entregado.
