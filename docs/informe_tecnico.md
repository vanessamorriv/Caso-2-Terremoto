# Informe técnico — Caso 2 · Terremoto en Colombia (10-ago-2026)

**Red temporal de campamentos: localización y asignación con un MILP en PuLP**
Universidad de La Sabana · Diseño y Gestión de la Cadena de Suministro · Prof. Gonzalo Mejía
Integrantes: PENDIENTE (grupo) · Versión: 5-oct-2026

Este informe resume la parte técnica del proyecto por si se pide separado de la presentación. Todas las cifras salen de
`results/tablas/` (notebook 02) y `data/processed/` (notebook 01); `tools/verificar_proyecto.py` comprueba que coincidan.

## 1. Contexto

El 10 de agosto de 2026 un sismo de magnitud 7,4 y ≈ 103 km de profundidad se sintió en 16 departamentos y causó afectaciones en 12
(OPS, informe de situación 2; F11). Las autoridades deben habilitar campamentos temporales para la población cuya vivienda no puede
ocuparse. El problema del grupo: con un presupuesto fijo, **qué campamentos abrir y cómo asignar a las personas**, respetando la
capacidad de cada sitio y un traslado máximo de 180 km por carretera, en el Valle del Cauca y el Eje Cafetero.

## 2. Datos

| Componente | Construcción | Fuente |
|---|---|---|
| 29 municipios afectados (incluye Cali y Pereira) | Viviendas no habitables (NH) ≥ 400 en el RUD | F01 (RUD, corte 17-sep-2026, vía agregador; no verificada en línea) |
| Población 2026 | 47/47 municipios coinciden con el archivo del DANE | F02 |
| Demanda $d_i$ | round(NH × hogar RUD × f), f = 10 % → **18.880 personas** | F01 + supuesto (F10) |
| 17 candidatos + 1 reserva | Ninguno es uno de los 29 municipios de demanda (pueden tener daños menores); NH < 250 y < 5 % de la población registrada; los 17 cumplen el criterio de "ciudad cercana" (≥ 1 municipio afectado a ≤ 180 km) | Criterio del grupo |
| Capacidad | 3.000 / 1.000 / 500 por categoría (grande ≥ 200.000 hab.; intermedia ≥ 100.000) | F08 (enunciado); umbral de 100.000: F12 (no verificada) y F13 |
| Costo fijo $F_j$ | $K_j \cdot c_f \cdot 3 \cdot \phi$ = 1.530 / 600 / 345 M COP | Supuesto ($c_f$ = 200.000 COP/plaza-mes) |
| Costo variable | Kit de alimentación 29.730 + kit de aseo 29.730 = 59.460 COP; se usa **60.000** (redondeo declarado) | F06 (no verificada, 403) y F17 |
| Coordenadas | Cabecera municipal DIVIPOLA | F04 |
| Distancias | Google Maps en 164 pares verificados (franja 160–230 km, controles y rutas de montaña), OSRM en el resto; 48 pares de 140–160 km verificados como control | F09, F05 |
| Presupuesto | 50 % × costo fijo de los 10 mayores candidatos = **3.547,5 M COP**; −15 %: 3.015,4 M; −30 %: 2.483,2 M | F08 |

Referencias completas en `docs/bibliografia.md`; columnas, unidades y tipo de dato en `docs/diccionario_datos.md`.

## 3. Supuestos y su justificación

- **f = 10 %** de las personas en viviendas no habitables necesita campamento. Es un escenario de planeación cercano al 11,6 % que
  estima ABAG (2017, metodología Hazus) para desplazados que buscan refugio (8,3–13,2 % por condado; demografía de EE. UU.). Lo observado
  en este sismo es menor: Cali 0,4 %, Armenia 1,0 %, Pereira 2,3 %, Manizales 2,7 % y Dosquebradas 4,4 % (F14, F15), con fechas no
  comparables. Por eso se reporta la sensibilidad con f = 2, 5, 8,3, 11,6 y 13 %.
- **$c_f$ = 200.000 COP/plaza-mes y φ = 0,85 / 1,00 / 1,15** (economías de escala): supuestos débiles. La única referencia pública
  hallada es el apoyo económico de la UNGRD por hogar-mes (F07, F16); el protocolo de alojamientos de la UNGRD no publica costos (F18).
- **Un kit de cada tipo por persona** para todo el periodo (literal del enunciado).
- **Un punto por municipio** (cabecera) y distancias de la red vial sin cierres posteriores al sismo.

## 4. Formulación (detalle en `docs/formulacion.md`)

Conjuntos $I$ (29 municipios), $J$ (17 candidatos), $A=\{(i,j):\delta_{ij}\le 180\}$ (308 arcos). Variables $y_j\in\{0,1\}$,
$x_{ij}\in\mathbb Z_{\ge0}$, $u_i\ge0$.

- **Objetivo lexicográfico:** (1) $\max\sum x_{ij}$; (2) entre las soluciones con ese máximo, $\min \sum_j F_jy_j+\sum(v+500\,\delta_{ij})x_{ij}$.
  Minimizar solo costo daría "no abrir nada" y exigir atención total es infactible (capacidad 16.000 < demanda 18.880).
- **R1** balance $\sum_j x_{ij}+u_i=d_i$; **R2** capacidad $\sum_i x_{ij}\le K_jy_j$; **R3** desigualdad válida $x_{ij}\le\min(d_i,K_j)y_j$;
  **R4** presupuesto sobre el costo total $\le B$; **R5** distancia máxima (por construcción de $A$); **R6** conserva $Z_1^*$ en la etapa 2.
- **Extensión (equidad):** E3 piso municipal $\sum_j x_{ij}\ge\beta d_i$ (**variante recomendada**) y, como complemento, la nueva
  variable $\alpha$ con E1 $\sum_{i\in I_k}\sum_j x_{ij}\ge\alpha\sum_{i\in I_k}d_i$ por departamento y E2 $\alpha\ge\underline\alpha$.
- **Sensibilidades de interpretación (no cambian el modelo base):** R4' $\sum_j F_jy_j\le B$ y la exclusión de candidatos pequeños.

Implementación indexada en PuLP (diccionarios y ciclos); CBC para el modelo y escenarios, HiGHS para los pisos de equidad. Cada
resultado exige `LpStatus = Optimal` y `sol_status = LpSolutionOptimal`: 647 llamadas, 646 óptimas + 1 infactible a propósito.

## 5. Resultados del escenario base

- **Sitios abiertos:** Palmira (3.000 plazas, 100 % ocupado) y Tuluá (3.000 plazas, 91,2 %).
- **Atendidos:** 5.736 de 18.880 personas (30,4 %); 13.144 sin campamento; 15 municipios sin atención; Risaralda y Caldas en 0 %.
- **Costos:** fijo 3.060,0 M + transporte 143,3 M + kits 344,2 M (alimentación 170,5 + aseo 170,5 + redondeo 3,1) = **3.547,5 M**
  (100 % del presupuesto).
- **Distancias:** promedio ponderado 50,0 km, máximo 89,1 km; 66,9 % de los atendidos a ≤ 50 km y 100 % a ≤ 100 km. Umbrales: 50 km
  (traslado corto, ≈ 1 h), 100 km (dentro del departamento, ≈ 2 h), 150 km (interdepartamental o de montaña, ≈ 3 h), 180 km (límite).
- **Qué determina la solución:** el presupuesto. +10 % de presupuesto suma 267 personas; quitar el límite de distancia suma 0; Palmira
  está llena pero Tuluá tiene 264 plazas que no se pueden pagar. La red base aparece desde un límite de 90 km (con 89 km cambia) y no
  cambia entre 90 y 250 km. La segunda mejor red distinta atiende a 5.500 (−4,1 %). Los campamentos grandes ganan porque su plaza cuesta
  510.000 COP frente a 600.000 y 690.000, ventaja que depende de φ.

## 6. Escenarios

| | Base | −15 % | −30 % |
|---|---|---|---|
| Presupuesto | 3.547,5 M | 3.015,4 M | 2.483,2 M |
| Sitios | Palmira, Tuluá | Palmira, Yumbo, Chinchiná | Palmira, Yumbo |
| Atendidos | 5.736 (30,4 %) | 4.500 (23,8 %) | 4.000 (21,2 %) |
| Presupuesto usado | 100 % | 93,2 % | 97,9 % |
| Distancia promedio / máxima | 50,0 / 89,1 km | 28,7 / 34,4 km | 30,2 / 34,4 km |

**Estable:** Palmira se abre en los tres. **Cambia:** Tuluá sale con −15 % y entra un par de sitios más pequeños y cercanos. La
respuesta es escalonada porque los campamentos se abren completos: con −15 % quedan 205,9 M sin usar porque no alcanzan para otro sitio.

**Lecturas pendientes del profesor** (sección 9.0 del notebook 02):

| Lectura | Base | −15 % | −30 % |
|---|---|---|---|
| Sin pequeños, B conservado (3.547,5 M) | 5.736 | 4.000 | 4.000 |
| Sin pequeños, B recalculado (3.030 M) | 4.089 (Palmira, Jamundí, Yumbo) | 4.000 (Palmira, Yumbo) | 3.000 (Palmira) |
| R4': tope solo sobre costos fijos | 6.500 (Palmira, Tuluá, Chinchiná) | 5.000 (Palmira, Cartago, Yumbo) | 4.500 (Palmira, Yumbo, Chinchiná) |

**Sensibilidad:** f entre 5 % y 13 % mueve la necesidad, pero los atendidos quedan en 5.500–5.822; con B fijo en COP, $c_f$ de
100.000 a 400.000 mueve los atendidos de 9.767 a 3.000; sin economías de escala (φ = 1) la red pasa a 7 sitios pequeños e intermedios;
con solo OSRM o con los 48 pares adicionales de Google Maps la red base no cambia. Los 7 pares que cambian de factibilidad entre OSRM y
Google (3 a ≤ 3 km del corte) no se usan en ningún escenario reportado.

## 7. Extensión: equidad territorial

- **Piso municipal β (recomendado):** β = 2,5 % cuesta 49 personas (5.736 → 5.687), conserva la red Palmira–Tuluá y deja 0 municipios
  sin atención; el máximo factible es β\* = 27,05 %.
- **Piso departamental α (complemento):** α\* = 29,05 % (29,1 % es infactible) cuesta 250 personas y equilibra los cuatro
  departamentos (≈ 29 % cada uno), pero no protege municipios: con α = 25 % quedan 22 municipios en 0 % y con α\*, 10.

## 8. Conclusiones

1. Con el presupuesto base se aloja al 30,4 % de la necesidad estimada; el dinero, no la distancia, es el recurso que manda.
2. Palmira es la decisión robusta; Tuluá depende del presupuesto.
3. Un recorte de 15 % cuesta 1.236 personas (−21,5 %) por el efecto escalonado de abrir campamentos completos.
4. La solución eficiente es territorialmente inequitativa; un piso municipal pequeño (β = 2,5 %) corrige los ceros a un costo bajo.
5. Los resultados dependen sobre todo de $c_f$ (supuesto débil) y de dos lecturas del enunciado que debe confirmar el profesor.

## 9. Limitaciones y pendientes

- **PENDIENTES (profesor):** (a) candidatos pequeños y definición de B si se rechazan; (b) alcance del presupuesto (R4 o R4');
  (c) aceptación de la matriz combinada Google Maps/OSRM.
- Supuestos débiles: $c_f$ y φ; f = 10 %; RUD de un agregador secundario con registro abierto; precios de kits de una fuente no verificada.
- Un solo periodo; un punto por municipio; distancias sin cierres posteriores al sismo; 16 pares quedan a ≤ 3 km del corte de 180 km (11 de ellos factibles), aunque ninguna solución reportada usa un arco de más de 173 km.
- Calidad de datos (`results/tablas/calidad_datos.csv`): 27 PASS, 12 WARNING, 0 FAIL; los WARNING son estas mismas debilidades declaradas.
