# Diccionario de datos

Generado por `notebooks/01_datos_coordenadas_distancias.ipynb` (misma tabla que la hoja `Diccionario` de
`data/processed/base_datos_caso2.xlsx`). **Tipo:** Real = dato de fuente o del enunciado; Calculado = derivado; Supuesto = decisión del
grupo; Identificador = clave o texto descriptivo. Los IDs de fuente (F01…) remiten a `docs/bibliografia.md`.

## `data/processed/demanda.csv`

| Columna | Descripción | Unidad | Tipo |
|---|---|---|---|
| `id` | Identificador del punto de demanda (D + DIVIPOLA) | — | Identificador |
| `divipola` | Código DIVIPOLA del municipio | — | Identificador |
| `municipio` | Nombre del municipio afectado | — | Identificador |
| `departamento` | Departamento | — | Identificador |
| `lat` | Latitud de la cabecera municipal (F04) | grados | Real |
| `lon` | Longitud de la cabecera municipal (F04) | grados | Real |
| `pob_DANE_2026` | Población proyectada 2026 (F02) | habitantes | Real |
| `NH_RUD` | Viviendas no habitables registradas en el RUD (F01) | viviendas | Real |
| `familias_RUD` | Familias registradas en el RUD (F01) | familias | Real |
| `personas_RUD` | Personas registradas en el RUD (F01) | personas | Real |
| `hogar_RUD` | Tamaño de hogar h_i = personas_RUD / familias_RUD | personas/familia | Calculado |
| `personas_en_NH` | Personas en viviendas no habitables = round(NH_RUD · h_i) (una familia por vivienda) | personas | Calculado |
| `d_f02` | Demanda con f = 2 %: round(NH_RUD · h_i · 0,02) | personas | Calculado |
| `d_f05` | Demanda con f = 5 % | personas | Calculado |
| `d_f10` | Demanda BASE d_i con f = 10 % (supuesto de planeación, F10) | personas | Calculado |
| `d_f13` | Demanda con f = 13 % | personas | Calculado |
| `d_f10_hogar3` | Demanda con f = 10 % y hogar de 3,0 personas (sensibilidad) | personas | Calculado |
| `pct_registrado` | Personas registradas en el RUD / población DANE × 100 | % | Calculado |
| `calidad_dato_RUD` | Calidad del dato: F fuerte, P parcial, R solo RUD (criterio del grupo) | — | Supuesto |

## `data/processed/candidatos.csv`

| Columna | Descripción | Unidad | Tipo |
|---|---|---|---|
| `id` | Identificador del sitio (C01–C17 candidatos, R01 reserva) | — | Identificador |
| `divipola` | Código DIVIPOLA | — | Identificador |
| `municipio` | Municipio del sitio | — | Identificador |
| `departamento` | Departamento | — | Identificador |
| `rol` | Candidato o Reserva (La Tebaida no cumple S7) | — | Supuesto |
| `pob_DANE_2026` | Población proyectada 2026 (F02) | habitantes | Real |
| `NH_RUD` | Viviendas no habitables en el municipio del sitio (F01) | viviendas | Real |
| `personas_RUD` | Personas registradas en el RUD (F01) | personas | Real |
| `pct_registrado` | Personas registradas / población × 100 | % | Calculado |
| `categoria` | Grande (≥ 200.000 hab.), Intermedia (≥ 100.000) o Pequeña (cortes P11–P12) | — | Calculado |
| `capacidad_K` | Capacidad K_j según categoría (enunciado: 3.000 / 1.000 / 500) | personas | Real |
| `factor_escala` | Factor φ de economías de escala: 0,85 / 1,00 / 1,15 | — | Supuesto |
| `costo_fijo_por_plaza_T` | c_f · T · φ = costo fijo por plaza en 3 meses | COP/plaza | Calculado |
| `costo_fijo_fj` | Costo fijo F_j = K_j · c_f · T · φ (c_f = 200.000 COP/plaza-mes, supuesto) | COP | Calculado |
| `costo_variable_vj` | Costo variable v = 60.000 (redondeo de 29.730 + 29.730) | COP/persona | Supuesto |
| `filtros_S2_S7` | Cumple NH < 250 y % registrado < 5 % (criterio del grupo) | — | Calculado |
| `lat` | Latitud de la cabecera (F04) | grados | Real |
| `lon` | Longitud de la cabecera (F04) | grados | Real |

## `data/processed/distancias_largo.csv`

| Columna | Descripción | Unidad | Tipo |
|---|---|---|---|
| `id_demanda` | Punto de demanda | — | Identificador |
| `id_sitio` | Sitio | — | Identificador |
| `km` | Distancia por carretera de la matriz final (Google Maps en 164 pares, OSRM en el resto) | km | Real |
| `km_OSRM` | Distancia OSRM original (F05) | km | Real |
| `fuente_km` | Fuente del valor km (Google Maps u OSRM) | — | Identificador |
| `municipio_origen` | Municipio afectado | — | Identificador |
| `sitio_destino` | Municipio del sitio | — | Identificador |
| `km_linea_recta` | Distancia haversine entre cabeceras | km | Calculado |
| `razon_carretera_recta` | km / km_linea_recta | — | Calculado |
| `factible_180km` | 1 si km ≤ 180 (enunciado) | 0/1 | Calculado |
| `costo_transporte_persona_COP` | 500 · km (enunciado) | COP/persona | Calculado |
| `fuente` | Descripción de la fuente y fecha de consulta | — | Identificador |

## `data/processed/tasa_albergue_observada.csv`

| Columna | Descripción | Unidad | Tipo |
|---|---|---|---|
| `municipio` | Municipio | — | Identificador |
| `departamento` | Departamento | — | Identificador |
| `albergados` | Personas en albergues reportadas por la prensa (F14, F15) | personas | Real |
| `fecha_dato` | Fecha o periodo del dato | fecha | Real |
| `dias_desde_sismo` | Días desde el 10-ago-2026 | días | Calculado |
| `tipo_dato` | Corte puntual o promedio del periodo | — | Real |
| `personas_en_NH` | Personas en viviendas no habitables (demanda.csv) | personas | Calculado |
| `tasa_observada` | albergados / personas_en_NH | fracción | Calculado |
| `veces_f_base` | f base (0,10) / tasa_observada | veces | Calculado |
| `fuente_id` | ID en la hoja Fuentes | — | Identificador |
| `fuente` | Medio y fecha | — | Identificador |
| `url` | Enlace | — | Identificador |
| `verificacion` | Estado de verificación | — | Identificador |
| `nota` | Observaciones | — | Identificador |

## `results/tablas/calidad_datos.csv`

| Columna | Descripción | Unidad | Tipo |
|---|---|---|---|
| `id` | Código de la prueba (D demanda, C candidatos, P parámetros, G coordenadas y distancias, F fuentes) | — | Identificador |
| `area` | Grupo de datos revisado | — | Identificador |
| `prueba` | Regla que se comprueba | — | Identificador |
| `nivel_si_no_cumple` | FAIL si rompe un requisito; WARNING si es una debilidad declarada | — | Supuesto |
| `resultado` | PASS, WARNING o FAIL | — | Calculado |
| `detalle` | Evidencia de la prueba | — | Calculado |
