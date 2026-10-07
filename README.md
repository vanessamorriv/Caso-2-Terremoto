# Caso 2 · Terremoto en Colombia — Red temporal de campamentos (MILP en PuLP)

**Universidad de La Sabana · Diseño y Gestión de la Cadena de Suministro · Prof. Gonzalo Mejía**

**Integrantes:** PENDIENTE (grupo) — nombre 1, nombre 2, nombre 3, nombre 4
**Licencia:** PENDIENTE (grupo) — p. ej. uso académico; indicar si el código se publica con licencia MIT y los datos con CC BY 4.0

Tras el terremoto del 10 de agosto de 2026, el proyecto decide **qué campamentos temporales habilitar** y **cómo asignar** a la
población que perdió su vivienda en el Valle del Cauca y el Eje Cafetero. Las restricciones son la capacidad de cada campamento, un
presupuesto máximo y una distancia de traslado de hasta 180 km por carretera.

> **Resultado central.** Con el presupuesto base ($3.547,5 M) se abren **2 campamentos grandes (Palmira y Tuluá)** y se aloja a
> **5.736 de 18.880 personas (30,4 %)**, a 50,0 km en promedio. El dinero es el recurso que limita la respuesta. La solución
> eficiente deja **Risaralda y Caldas en 0 %** y 15 municipios sin atención. **Variante de equidad recomendada:** un piso municipal
> **β = 2,5 %** cuesta 49 personas, conserva la red (Palmira, Tuluá) y deja **0 municipios sin atención**. Como complemento, el piso
> departamental máximo es **α\* = 29,05 %** (cuesta 250 personas y equilibra los cuatro departamentos, pero deja 10 municipios en 0 %).

---

## 1. Estructura del repositorio

```
caso2/
├── README.md                         ← este archivo
├── requirements.txt                  ← dependencias (pulp>=2.8,<4 y highspy)
├── data/
│   ├── raw/                          ← datos ORIGINALES (no se editan)
│   │   ├── demanda_terremoto.csv           29 municipios afectados (RUD + DANE), construido por el grupo
│   │   ├── candidatos_costos.csv           17 candidatos + 1 reserva, capacidades y costos
│   │   ├── albergados_observados.csv       personas en albergues publicadas por la prensa (con fuente, fecha y URL)
│   │   ├── base_datos_caso2_original.xlsx  libro del grupo con fórmulas y registro de supuestos
│   │   ├── divipola_coordenadas_datosgov.csv  coordenadas DIVIPOLA tal como las entrega datos.gov.co
│   │   ├── osrm/osrm_table_respuestas.csv  58 respuestas originales de OSRM (metros) con su URL
│   │   ├── google_maps/verificacion_google_maps.csv          164 pares consultados en Google Maps el 1-oct-2026 (km y URL)
│   │   ├── google_maps/verificacion_google_maps_140_160km.csv 48 pares OSRM de 140–160 km verificados el 5-oct-2026 (control)
│   │   ├── dane/                           proyecciones de población DANE (PPED 2018-2042 y DCD 2020-2035)
│   │   └── preliminar/                     versiones anteriores (tabla de sensibilidad y notebook sin ejecutar)
│   └── processed/                    ← generado por el notebook 01
│       ├── base_datos_caso2.xlsx           base de datos final: LEEME, fórmulas originales, coordenadas, distancias, verificación,
│       │                                   albergados observados, Fuentes (con URL y verificación), Registro_cambios, Calidad_datos y Diccionario
│       ├── demanda.csv, candidatos.csv, nodos_coordenadas.csv, tasa_albergue_observada.csv
│       ├── distancias_km.csv (29×18, matriz final), distancias_km_osrm.csv, distancias_km_alt_google_140_160.csv (sensibilidad)
│       ├── distancias_largo.csv, resumen_alcance.csv (incluye el criterio de "ciudad cercana" por candidato)
│       ├── parametros.csv, control_poblacion_DANE.csv, metadatos_instancia.json
├── notebooks/
│   ├── 01_datos_coordenadas_distancias.ipynb   construcción y validación de la instancia
│   ├── 02_modelo_milp.ipynb                     formulación, PuLP, resultados, escenarios, sensibilidad, extensión
│   └── src/                                     mismos notebooks en formato .py (fáciles de revisar en Git)
├── results/
│   ├── resultados_modelo.xlsx        ← las tablas de resultados del modelo en un libro (hoja LEEME); la de calidad de datos está en el Excel de datos
│   ├── tablas/                       ← las mismas tablas en CSV (31 archivos, incluye registro_solver.csv y calidad_datos.csv)
│   └── figuras/                      ← 11 figuras PNG
├── docs/
│   ├── formulacion.md                modelo matemático completo (incluye R4' y la lectura sin pequeños como sensibilidades)
│   ├── informe_tecnico.md            informe técnico único (contexto, datos, supuestos, formulación, resultados, escenarios, conclusiones)
│   ├── bibliografia.md               referencias completas con URL y estado de verificación (generado por el notebook 01)
│   ├── diccionario_datos.md          columnas, unidades y tipo (Real/Calculado/Supuesto) (generado por el notebook 01)
│   ├── explicacion_warnings_calidad.docx  qué significa cada WARNING del módulo de calidad y cómo defenderlo
│   ├── registro_correcciones.md      qué se verificó, qué se corrigió y qué queda pendiente
│   ├── uso_ia.md                     declaración de uso de IA por fase
│   └── Caso_2_Terremoto_en_Colombia_enunciado.pdf
└── tools/
    ├── calidad_datos.py              módulo de calidad de datos: pruebas PASS / WARNING / FAIL (objetivo 0 FAIL)
    ├── py2nb.py                      convierte notebooks/src/*.py en .ipynb
    └── verificar_proyecto.py         comprueba archivos, datos, fuentes, solver, re-soluciones independientes y cifras del README
```

## 2. Cómo ejecutarlo

```bash
git clone <url-del-repositorio> && cd caso2
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd notebooks
jupyter nbconvert --to notebook --execute --inplace 01_datos_coordenadas_distancias.ipynb   # ~20 s
jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=7200 02_modelo_milp.ipynb   # ~11 min (652 resoluciones MILP)
cd .. && python tools/verificar_proyecto.py
```

También se puede abrir cada notebook en Jupyter o VS Code y usar *Run All*. **En Google Colab:** suba la carpeta completa (o clónela
con `!git clone`), `%cd caso2/notebooks` y *Run All*: la primera celda del notebook 02 instala `pulp>=2.8,<4` y `highspy` si faltan.
Todas las rutas son relativas a la raíz del repositorio.

- **Versiones probadas:** Python 3.13, **PuLP 3.3.2** (trae CBC) y **highspy 1.15.1** (HiGHS). El código de los notebooks también es
  sintácticamente válido en Python 3.11 (se corrigió un f-string anidado que exigía 3.12); la ejecución completa se probó con 3.13.
- **Versión de PuLP: `pulp>=2.8,<4`.** Se comprobó en un entorno aislado con PuLP 4.0.0 (Python 3.13): `LpVariable` no acepta `cat=`
  ni tiene `.dicts`, y no existen `pulp.PULP_CBC_CMD`, `pulp.LpStatus`, `pulp.LpStatusOptimal` ni `pulp.LpSolutionOptimal`; además
  `listSolvers(onlyAvailable=True)` devuelve una lista vacía (no trae CBC). Se exige ≥ 2.8 porque desde esa versión existe `pulp.HiGHS`.
- **Modo rápido:** en el notebook 02, `RAPIDO = True` omite las cuadrículas largas (curva de presupuesto completa, 144 combinaciones de
  $c_f$, barrido completo de distancia y 5 redes casi óptimas), tarda ≈ 6 min y escribe en `results/rapido/` sin tocar los
  resultados oficiales. Las cifras oficiales salen siempre con `RAPIDO = False`.
- **Solvers:** CBC (incluido en PuLP) para el modelo base, los escenarios y las sensibilidades; **HiGHS** (paquete `highspy`, usado a
  través de PuLP) para los modelos con pisos de equidad, porque CBC no certifica el problema max-min α\* en 10 minutos.
- **Estado del solver:** un resultado solo se acepta si `LpStatus == "Optimal"` **y** `sol_status == LpSolutionOptimal`. PuLP reporta
  "Optimal" incluso cuando el solver se detiene por `timeLimit` con una solución no certificada; en ese caso el notebook se detiene (salvo en las pruebas de factibilidad de pisos, donde una solución entera factible basta como prueba).
  En la última ejecución hubo **652 llamadas: 651 óptimas + 1 infactible a propósito** (la prueba de que el piso de la siguiente décima de punto, 29,1 %, es
  infactible) y 0 cortadas por tiempo (`results/tablas/registro_solver.csv`).
- **No se necesita internet** (salvo para instalar paquetes). Coordenadas, respuestas de OSRM y verificaciones de Google Maps están en `data/raw/`.
- LibreOffice es **opcional**: si está instalado, el notebook 01 recalcula el Excel, guarda los valores de las fórmulas y comprueba
  que ninguna da error.

## 3. Datos y supuestos

| Dato | Valor | Tipo | Fuente |
|---|---|---|---|
| Municipios afectados | 29 (incluye Cali y Pereira), filtro NH ≥ 400 viviendas no habitables | Dato + criterio | F01: UNGRD – RUD, corte 17-sep-2026 (vía datosdelterremoto.org; **no verificada** en esta revisión) |
| Población 2026 | 47/47 municipios verificados | Dato | F02: DANE – PPED 2018-2042 (act. 30-jul-2025) |
| Demanda $d_i$ | $\text{round}(NH_i \times h_i \times f)$, $h_i$ = personas/familia RUD, **f = 10 %** → 18.880 personas | Dato × supuesto | RUD; f como escenario de planeación (F10, ABAG 2017 con Hazus: 11,6 %; 8,3–13,2 % por condado) |
| Tasa de albergue observada | 0,4 % (Cali) a 4,4 % (Dosquebradas) de las personas en NH | Dato (prensa) | F14, F15; tabla en `data/raw/albergados_observados.csv` |
| Candidatos | 17 (+ La Tebaida como reserva); ninguno es uno de los 29 municipios de demanda (pueden tener daños menores: NH < 250); los 17 cumplen el criterio de "ciudad cercana" | Criterio | Filtros S2 (NH < 250) y S7 (< 5 % registrado) |
| Categoría y capacidad | Grande ≥ 200.000 hab. → 3.000; Intermedia ≥ 100.000 → 1.000; Pequeña → 500 | Enunciado + corte propio | F12: DNP, umbral de 100.000 (**no verificada**; respaldo secundario F13) |
| Costo fijo $F_j$ | $K_j \times c_f \times 3 \text{ meses} \times \phi$; $c_f$ = 200.000 COP/plaza-mes; $\phi$ = 0,85 / 1,00 / 1,15 | **Supuesto débil** | Referencia: apoyo UNGRD por hogar-mes (F07, F16). No se encontró una referencia pública de costo por plaza (F18 no trae costos) |
| Costo variable $v$ | **kit de alimentación 29.730 + kit de aseo 29.730 = 59.460 COP**; el modelo usa **60.000** (redondeo declarado, +0,9 %) | Supuesto (precio minorista de prensa, no institucional) + redondeo | F06: El Tiempo, 14-ago-2026 (**no verificada**: 403); corroboración F17 (kits de $15.000 y $30.000) |
| Coordenadas | Cabecera municipal (un punto por municipio) | Dato | F04: DANE – DIVIPOLA (datos.gov.co `gdxc-w37w`) |
| Distancias | Por carretera, 29 × 18 pares: **Google Maps en 164 pares verificados** (franja 160–230 km, controles y rutas de montaña) y OSRM en el resto; los 48 pares OSRM de 140–160 km se verificaron como control | Dato | F09: Google Maps (1-oct y 5-oct-2026) y F05: OSRM/OpenStreetMap (30-sep-2026) |
| Transporte | 500 COP/km·persona, lineal | Enunciado | F08 |
| Presupuesto | 50 % × costo fijo de los 10 candidatos más grandes = **$3.547,5 M** | Enunciado | F08 |
| Escenarios | Reducción de −15 % ($3.015,4 M) y −30 % ($2.483,2 M) | Decisión del grupo | Extremos del rango 15–30 % |

**Calidad de datos** (`tools/calidad_datos.py`): 39 pruebas sobre los datos de entrada con resultado **PASS** (cumple), **WARNING**
(debilidad conocida que se declara) o **FAIL** (rompe un requisito del enunciado o una regla de construcción; el notebook se detiene).
Resultado actual: **27 PASS · 12 WARNING · 0 FAIL** (hoja `Calidad_datos` del Excel y `results/tablas/calidad_datos.csv`). Los WARNING:
datos RUD parciales en 7 municipios; Calarcá (15,3) y Sevilla (9,5) con muchas familias por vivienda no habitable; Argelia y El Cairo con
más del 65 % de la población registrada; 10 candidatos pequeños y la matriz combinada (decisiones adoptadas); Jamundí a 1,6 % del
corte de 200.000; c_f sin fuente; 9 pares de montaña con razón carretera/recta > 2,3; La Dorada alcanza solo 2 municipios; 16 pares a
≤ 3 km del corte de 180 km (ninguna solución reportada usa un arco de más de 173 km); f = 10 % por encima de lo observado; 3 fuentes
no verificadas.

Todas las fuentes, con URL, tipo, uso y estado de verificación, están en la hoja `Fuentes` del Excel y en
[`docs/bibliografia.md`](docs/bibliografia.md); las columnas de cada archivo, en [`docs/diccionario_datos.md`](docs/diccionario_datos.md).

**f = 10 % frente a lo observado.** La tasa de albergue observada (albergados ÷ personas en viviendas no habitables) es Cali 0,4 %,
Armenia 1,0 %, Pereira 2,3 %, Manizales 2,7 % y Dosquebradas 4,4 %. Las fechas **no son comparables** (las cuatro primeras son un corte
del 18-ago, día 8; Dosquebradas es el promedio de 48 días, y el 27-sep quedaban 45 personas). f = 10 % es un **escenario de planeación**,
entre 2,3 y 23,9 veces lo observado; el 11,6 % de ABAG es el porcentaje de desplazados que busca refugio, con demografía de EE. UU.

**Criterio de "ciudad cercana".** El enunciado pide candidatos en ciudades "cercanas". El grupo lo define así: **un candidato es
cercano si al menos un municipio afectado está a ≤ 180 km por carretera** (matriz final). Lo cumplen los 17 candidatos:

| Candidato | Categoría | Municipios afectados a ≤ 180 km | Pares que dependen de Google Maps |
|---|---|---|---|
| Palmira | Grande | 20 | 0 |
| Tuluá | Grande | 29 | 0 |
| Jamundí | Intermedia | 13 | 0 |
| Cartago | Intermedia | 25 | 0 |
| Guadalajara de Buga | Intermedia | 26 | 0 |
| Candelaria | Intermedia | 17 | 0 |
| Yumbo | Intermedia | 18 | 0 |
| Florida | Pequeña | 15 | 0 |
| El Cerrito | Pequeña | 25 | 0 |
| Pradera | Pequeña | 17 | 1 |
| Guacarí | Pequeña | 26 | 0 |
| Ginebra | Pequeña | 24 | 0 |
| Chinchiná | Pequeña | 23 | 0 |
| Supía | Pequeña | 19 | 1 |
| Aguadas | Pequeña | 6 | 0 |
| Pensilvania | Pequeña | 3 | 0 |
| La Dorada | Pequeña | **2** | **2** |

**La Dorada** alcanza solo a Manizales y Villamaría, y depende por completo de dos valores de Google Maps (166 y 165 km); con OSRM
(212,9–213,8 km) no cumpliría el criterio. Detalle por candidato en `data/processed/resumen_alcance.csv`.

**Verificación de distancias.** En los 164 pares consultados el 1-oct, la mediana Google/OSRM es 1,005 y la razón máxima 1,14; 7 pares
cambian de factibilidad a 180 km. **3 de esos 7 están a ≤ 3 km del corte** (Armenia–Pradera 178 km, El Cairo–Buga 181 km,
Caicedonia–Supía 178 km) y Google muestra km enteros desde 100 km, así que su factibilidad es frágil. **Impacto: ninguno** en la base,
−15 % ni −30 % (las asignaciones de esos escenarios no superan 89,1 km), ni en las sensibilidades ni en las fronteras de equidad
(`results/tablas/uso_pares_cambio_factibilidad.csv`). Sí los usan soluciones auxiliares con presupuestos de ×3,5 o más (todos los sitios
abiertos): la cota física de 16.000 plazas llenas depende de los dos valores de Google Maps hacia La Dorada (con solo OSRM sería 15.500). Los **49 pares OSRM entre 140 y 160 km** también se revisaron: uno ya era control
(Buenaventura–Palmira) y los **48 restantes se consultaron en Google Maps el 5-oct-2026** con la misma metodología. Razón Google/OSRM
0,898–1,078 (mediana 1,005), máximo 168 km: **ninguno cambia de factibilidad**. No reemplazan a OSRM en la matriz final (12 consultas
muestran rutas que evitan cierres viales temporales del 5-oct y la fecha difiere de la del 1-oct); con ellos la red base no cambia
(sensibilidad en el notebook 02).

**Limitación de las coordenadas.** Cada municipio se representa con el punto de cabecera de DIVIPOLA, que no siempre es el centro
(en Cali queda ~4 km al sur y en Pereira ~3 km al suroccidente) y no representa la población rural de municipios extensos
(Buenaventura, Dagua, El Cairo, Argelia). El error es pequeño frente a 180 km, pero puede ser de 5–10 % en trayectos cortos.

## 4. Modelo (resumen; detalle en `docs/formulacion.md`)

- **Variables:** $y_j\in\{0,1\}$ (abrir el campamento), $x_{ij}\in\mathbb{Z}_{\ge0}$ (personas de $i$ asignadas a $j$, solo si
  $\delta_{ij}\le180$) y $u_i\ge0$ (personas no atendidas).
- **Objetivo lexicográfico:** (1) maximizar las personas atendidas; (2) entre las redes que logran ese máximo, minimizar el costo
  total (fijo + kits + transporte). Minimizar solo el costo daría la solución trivial de no abrir nada, y exigir atención total es
  infactible (la capacidad total, 16.000, es menor que la demanda, 18.880).
- **Restricciones:** balance de demanda (R1), capacidad con apertura (R2), desigualdad válida (R3), presupuesto sobre el costo total
  (R4), distancia máxima por construcción del conjunto de arcos (R5) y mantenimiento de la cobertura en la etapa 2 (R6). Como
  sensibilidad se resuelve R4' (tope solo sobre costos fijos), que no reemplaza a R4.
- **Extensión propia (equidad):** piso municipal $\sum_j x_{ij}\ge\beta d_i\ \forall i$ (E3, **variante recomendada**) y, como
  complemento, la nueva variable $\alpha$ (cobertura mínima garantizada a cada departamento) con la familia
  $\sum_{i\in I_k}\sum_j x_{ij}\ge\alpha\sum_{i\in I_k}d_i\ \forall k$ (E1–E2). Se calculan $\alpha^*$ y $\beta^*$ resolviendo el MILP
  max-min directamente y se trazan las fronteras eficiencia–equidad.

## 5. Resultados principales

| Indicador | Base | −15 % | −30 % | Extensión (α\* = 29,05 %) |
|---|---|---|---|---|
| Presupuesto | $3.547,5 M | $3.015,4 M | $2.483,2 M | $3.547,5 M |
| Sitios abiertos | Palmira, Tuluá | Palmira, Yumbo, Chinchiná | Palmira, Yumbo | Tuluá, Cartago, Yumbo, Chinchiná |
| Población atendida | **5.736 (30,4 %)** | 4.500 (23,8 %) | 4.000 (21,2 %) | 5.486 (29,1 %) |
| Población no atendida | 13.144 | 14.380 | 14.880 | 13.394 |
| Utilización de la capacidad abierta | 95,6 % (Palmira 100 %, Tuluá 91,2 %) | 100 % | 100 % | 99,7 % |
| Costo fijo / transporte / kits (M COP) | 3.060,0 / 143,3 / 344,2 | 2.475,0 / 64,5 / 270,0 | 2.130,0 / 60,5 / 240,0 | 3.075,0 / 143,3 / 329,2 |
| Kits: alimentación / aseo / redondeo (M COP) | 170,5 / 170,5 / 3,1 | 133,8 / 133,8 / 2,4 | 118,9 / 118,9 / 2,2 | 163,1 / 163,1 / 3,0 |
| Costo total (% del presupuesto) | 3.547,5 M (100 %) | 2.809,5 M (93,2 %) | 2.430,5 M (97,9 %) | 3.547,5 M (100 %) |
| Distancia promedio ponderada / máxima | 50,0 / 89,1 km | 28,7 / 34,4 km | 30,2 / 34,4 km | 52,2 / 117,0 km |
| Atendidos a ≤ 50 / ≤ 100 km | 66,9 % / 100 % | 100 % / 100 % | 100 % / 100 % | 60,9 % / 85,4 % |
| Misma cifra como % de la demanda total (18.880) | 20,3 % / 30,4 % | 23,8 % / 23,8 % | 21,2 % / 21,2 % | 17,7 % / 24,8 % |
| Municipios sin atención | 15 de 29 | 26 | 28 | 10 |
| Cobertura Valle / Quindío / Risaralda / Caldas | 51,0 / 57,6 / 0 / 0 % | 45,2 / 0 / 7,1 / 0 % | 45,2 / 0 / 0 / 0 % | 29,05 / 29,06 / 29,06 / 29,07 % |

**Umbrales de distancia (definidos por el grupo):** 50 km = traslado corto al área metropolitana o a un municipio vecino (≈ 1 h);
100 km = traslado típico dentro del departamento (≈ 2 h); 150 km = traslado interdepartamental o de montaña (≈ 3 h), último umbral
antes del límite; 180 km = límite del enunciado (control).

**Lecturas clave**

1. **El dinero es el recurso escaso.** Se usa el 100 % del presupuesto. Prueba de relajación: +10 % de presupuesto suma 267 personas;
   quitar el límite de distancia suma 0. Palmira queda llena (su capacidad es activa), pero Tuluá tiene 264 plazas libres que no se
   pueden pagar.
2. **¿Es trivial? No.** La red base aparece desde un límite de **90 km** (con 89 km o menos la red cambia a Palmira, Cartago, Yumbo y
   Chinchiná, con 5.500 atendidos); entre 90 y 250 km no cambia, por eso con 120, 150 o 210 km la solución es la misma. Con presupuesto
   creciente (hasta ×4) la red pasa de 1 a 17 sitios; el presupuesto limita el total hasta ×3,0 y desde ×3,5 se abren los 17
   candidatos y manda la capacidad total (16.000 plazas). La distancia de 180 km no es activa en ningún nivel. La segunda mejor red
   distinta atiende a 5.500 (−4,1 %).
3. **Los campamentos grandes ganan** porque su plaza cuesta 510.000 COP, frente a 600.000 en los intermedios y 690.000 en los
   pequeños. Esa ventaja depende del supuesto φ: sin economías de escala la red óptima son 7 sitios pequeños e intermedios.
4. **Recortes:** la respuesta es escalonada porque los campamentos se abren completos. Palmira es la decisión más estable frente a
   recortes (abierta en los cinco niveles), aunque no imprescindible: cerrarla y re-optimizar cuesta 236 personas. Tuluá se pierde con
   −15 % y se reemplaza por sitios más pequeños y cercanos (la distancia promedio baja a 28,7 km). **Con −15 % la equidad es gratuita:**
   la red Tuluá, Cartago, Chinchiná atiende a las mismas 4.500 personas con un piso departamental de 23,82 % y deja 10 municipios en 0 %
   en lugar de 26; si el presupuesto se recorta, conviene ejecutar esa red.
5. **Equidad — se recomienda el piso municipal β.** Sin piso, Pereira (el municipio con más demanda) y todo Risaralda y Caldas quedan
   sin atención. **β = 2,5 %** cuesta 49 personas (5.736 → 5.687), conserva la red Palmira–Tuluá y deja **0 municipios en 0 %**; el
   máximo es β\* = 27,05 %. El piso departamental α es un **complemento**: α\* = 29,05 % (29,0 % con un decimal, truncado; un piso de
   29,1 % es infactible) cuesta 250 personas y equilibra los departamentos, pero no protege municipios: con α = 25 % quedan **22
   municipios en 0 %** y con α\*, 10. El límite de 180 km no es activo ni siquiera con los pisos: sin él, α\* y los atendidos con
   β = 2,5 % son los mismos (los traslados llegan a 171–172 km, cerca del límite).
6. **Sensibilidad:** la fracción $f$ cambia la necesidad (3.777 a 24.546 personas), pero el presupuesto fija cuántos se atienden
   (5.500–5.822 con f entre 5 % y 13 %). Con $B$ fijo en COP, el costo fijo por plaza $c_f$ mueve los atendidos entre 3.000
   ($c_f$ = 400.000) y 9.767 ($c_f$ = 100.000): es el supuesto más débil del modelo.

**Decisiones adoptadas y sus alternativas** (sensibilidad; notebook 02, sección 9.0; `results/tablas/escenarios_presupuesto_alternativo.csv`):

| Lectura | Presupuesto base | Base | −15 % | −30 % |
|---|---|---|---|---|
| Modelo base (17 candidatos, R4) | $3.547,5 M | 5.736 (Palmira, Tuluá) | 4.500 (Palmira, Yumbo, Chinchiná) | 4.000 (Palmira, Yumbo) |
| Sin pequeños, **B conservado** | $3.547,5 M | 5.736 (Palmira, Tuluá) | 4.000 (Palmira, Yumbo) | 4.000 (Palmira, Yumbo) |
| Sin pequeños, **B recalculado** (50 % × 6.060 M) | $3.030,0 M | **4.089** (Palmira, Jamundí, Yumbo) | 4.000 (Palmira, Yumbo) | 3.000 (Palmira) |
| R4': tope solo sobre costos fijos | $3.547,5 M | 6.500 (Palmira, Tuluá, Chinchiná) | 5.000 (Palmira, Cartago, Yumbo) | 4.500 (Palmira, Yumbo, Chinchiná) |

"Sin pequeños la base no cambia" **solo vale con B conservado**; con B recalculado la base baja a 4.089. Con R4' el gasto total supera
$B$ (≈ 111 % en la base) porque kits y transporte quedan fuera del tope.

## 6. Verificación, decisiones metodológicas y pendientes

Lo que se verificó y corrigió está en [`docs/registro_correcciones.md`](docs/registro_correcciones.md).

**Decisiones metodológicas adoptadas** (el enunciado admite dos lecturas; las alternativas quedan como sensibilidad):

| Decisión | Alternativa adoptada | Por qué | Alternativas (sensibilidad) |
|---|---|---|---|
| Candidatos pequeños | **17 candidatos, 10 pequeños** | Solo 7 municipios que no son puntos de demanda tienen ≥ 100.000 habitantes y el enunciado exige ≥ 15 candidatos; además define capacidad para "municipios pequeños" | Sin pequeños, B conservado: 5.736 / 4.000 / 4.000; B recalculado (3.030 M): 4.089 / 4.000 / 3.000 |
| Alcance del presupuesto | **R4: costo total** (fijo + kits + transporte ≤ B) | El enunciado habla de un "presupuesto total" y "máximo disponible"; nunca se gasta más de B | R4' (solo fijos): 6.500 / 5.000 / 4.500, gastando ≈ 111 % de B |
| Distancias | **Matriz combinada**: Google Maps en 164 pares (160–230 km), OSRM en el resto | Google se usa justo donde se decide la factibilidad; corrige el ruteo de OSRM a La Dorada; mediana Google/OSRM = 1,005 | Solo OSRM: 5.733 (misma red); +48 pares Google de 140–160 km: 5.736 |

**Supuestos del grupo que siguen siendo débiles:** $c_f$ y φ ($c_f$ = 200.000 COP/plaza-mes equivale a ≈ 40–53 % del apoyo UNGRD por
persona, con ≈ 2,1 personas por hogar como en el RUD; no hay fuente colombiana de costo por plaza: el Protocolo de alojamientos temporales de la
UNGRD no publica costos, el Manual Esfera no se pudo abrir y una búsqueda breve no halló contratos con costo por plaza); f = 10 % (escenario de planeación, 2,3–23,9 veces lo observado); RUD
de un agregador secundario con registro abierto; un kit de cada tipo por persona para los 3 meses; transporte de ida, pagado una vez.

**Pendiente (grupo):** presentación PDF (fuera del alcance de esta revisión técnica), integrantes y licencia (arriba) y las fases
marcadas PENDIENTE (grupo) en `docs/uso_ia.md`.

## 7. Dependencias

Python ≥ 3.11, `pulp>=2.8,<4` (incluye CBC), `highspy` (HiGHS), `pandas`, `numpy`, `matplotlib`, `openpyxl`, `jupyter`/`nbconvert`.
Opcional: `requests` (para volver a consultar DIVIPOLA y OSRM) y LibreOffice (para recalcular el Excel).
