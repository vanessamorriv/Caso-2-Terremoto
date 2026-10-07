# Formulación matemática — Caso 2 · Terremoto en Colombia

Modelo de localización con cobertura parcial, capacidad y presupuesto (MILP). Lo implementa `notebooks/02_modelo_milp.ipynb`
(secciones 4, 5 y 10). Los valores vigentes de los resultados están en
`results/tablas/` y en el README.

## Conjuntos e índices

| Símbolo | Significado |
|---|---|
| $i \in I$ | Municipios afectados (puntos de demanda), $\lvert I\rvert = 29$ (incluye Cali y Pereira) |
| $j \in J$ | Sitios candidatos para campamento, $\lvert J\rvert = 17$ (la reserva La Tebaida solo se usa en sensibilidad) |
| $A = \{(i,j)\in I\times J:\ \delta_{ij}\le D^{max}\}$ | Pares origen–campamento permitidos por la distancia máxima (308 de 493) |
| $J_i=\{j:(i,j)\in A\}$, $I_j=\{i:(i,j)\in A\}$ | Sitios alcanzables desde $i$; municipios que puede recibir $j$ |
| $k\in\mathcal K$, $I_k\subseteq I$ | *(Extensión)* Departamentos (Valle del Cauca, Risaralda, Caldas, Quindío) y sus municipios |

## Parámetros

| Símbolo | Significado | Valor |
|---|---|---|
| $d_i$ | Personas de $i$ que requieren alojamiento temporal, $\text{round}(NH_i\,h_i\,f)$ | 18.880 en total con $f=10\,\%$ |
| $K_j$ | Capacidad (enunciado) | 3.000 grande / 1.000 intermedia / 500 pequeña |
| $F_j$ | Costo fijo de operación por 3 meses, $K_j\,c_f\,T\,\phi_j$ | 1.530 / 600 / 345 M COP |
| $v = v^{alim}+v^{aseo}$ | Costo variable de atención: 1 kit de alimentación (29.730) + 1 kit de aseo (29.730) = 59.460 COP por persona; se usa **60.000 COP como redondeo declarado** (+540, +0,9 %) | 60.000 COP |
| $\delta_{ij}$ | Distancia por carretera: Google Maps en 164 pares verificados (1-oct-2026), OSRM/OpenStreetMap en el resto. Los 48 pares OSRM de 140–160 km se verificaron el 5-oct-2026 como control (ninguno cambia de factibilidad; se usan solo como sensibilidad) | km |
| $c_{ij}=500\,\delta_{ij}$ | Costo de transporte por persona (lineal, enunciado) | COP |
| $B$ | Presupuesto = 50 % del costo fijo de los 10 candidatos más grandes | 3.547,5 M COP |
| $D^{max}$ | Distancia máxima de traslado (enunciado) | 180 km |
| $\underline\alpha,\ \beta$ | *(Extensión)* Pisos de equidad departamental y municipal fijados por el decisor | $[0,1]$ |

## Variables y dominios

| Variable | Dominio | Significado |
|---|---|---|
| $y_j$ | $\{0,1\}$ | 1 si se habilita el campamento $j$ |
| $x_{ij}$ | $\mathbb Z_{\ge0}$, $(i,j)\in A$ | Personas de $i$ asignadas a $j$ |
| $u_i$ | $\mathbb R_{\ge0}$ | Personas de $i$ sin atender (holgura explícita; es entera porque $d_i$ y $x_{ij}$ lo son) |
| $\alpha$ | $[0,1]$ | *(Extensión, nueva variable)* Cobertura mínima garantizada a cada departamento |

## Función objetivo (lexicográfica)

$$\text{Etapa 1:}\quad Z_1^*=\max\sum_{(i,j)\in A}x_{ij}$$

$$\text{Etapa 2:}\quad \min\ \sum_j F_j y_j+\sum_{(i,j)\in A}(v+c_{ij})\,x_{ij}\quad\text{s.a. (R1)–(R5) y (R6) } \sum_{(i,j)\in A}x_{ij}\ge Z_1^*$$

**Por qué y cómo evita soluciones triviales.** Con el presupuesto base se atiende a 5.736 de 18.880 personas (≈ 30,4 %) y la capacidad total de los 17
candidatos (16.000) tampoco cubre a las 18.880 personas. Si se minimizara solo el costo, la solución óptima sería no abrir nada
($y=0$, $x=0$); si se exigiera atender a todos ($u=0$), el modelo sería infactible. La jerarquía "primero personas, luego pesos"
refleja la prioridad humanitaria sin fijar un peso arbitrario entre personas y COP; la etapa 2 elige la red más barata entre las que
alcanzan el máximo y con eso favorece traslados cortos. Que la solución no es trivial se comprueba en el notebook: (i) la red base
cambia con el presupuesto (curva hasta ×4), (ii) con la prueba de relajación se identifica la restricción activa en cada nivel,
(iii) se enumeran las cinco mejores redes con cortes *no-good*, y (iv) la red cambia si el límite de distancia baja de 90 km.

## Restricciones

| | Expresión | Explicación |
|---|---|---|
| R1 | $\sum_{j\in J_i}x_{ij}+u_i=d_i\quad\forall i\in I$ | Balance: cada persona queda asignada o se registra como no atendida; nunca se asigna más que la demanda |
| R2 | $\sum_{i\in I_j}x_{ij}\le K_j\,y_j\quad\forall j\in J$ | Capacidad; un campamento cerrado no recibe a nadie |
| R3 | $x_{ij}\le\min(d_i,K_j)\,y_j\quad\forall(i,j)\in A$ | Desigualdad válida (redundante con R1–R2) que ajusta la relajación lineal |
| R4 | $\sum_j F_jy_j+\sum_{(i,j)\in A}(v+c_{ij})x_{ij}\le B$ | Presupuesto total: operación, kits y transporte (modelo base) |
| R5 | $x_{ij}$ existe solo si $\delta_{ij}\le 180$ | Distancia máxima de traslado (por construcción del conjunto $A$; equivale a $x_{ij}=0$ si $\delta_{ij}>180$) |
| R6 | $\sum_{(i,j)\in A}x_{ij}\ge Z_1^*$ | Solo en la etapa 2: conserva la cobertura máxima de la etapa 1 |

**Lectura alternativa del presupuesto (solo sensibilidad, PENDIENTE del profesor).** El enunciado define $B$ con costos fijos
("50 % del costo fijo total de operar los 10 campamentos candidatos más grandes") y no dice si el tope cubre también kits y
transporte. El modelo base usa R4 (costo total), la lectura más conservadora. Como sensibilidad se resuelve

$$\text{(R4')}\qquad \sum_{j} F_j\,y_j \le B,$$

con kits y transporte fuera del tope y el mismo objetivo lexicográfico (en la etapa 2 se minimiza el costo total). R4' **no reemplaza** a
R4. Resultados (notebook 02, sección 9.0): base 6.500 atendidos (Palmira, Tuluá, Chinchiná), −15 % 5.000 (Palmira, Cartago, Yumbo) y
−30 % 4.500 (Palmira, Yumbo, Chinchiná); con R4' el gasto total supera $B$ (≈ 111 % en la base).

**Candidatos pequeños (PENDIENTE del profesor).** Si se excluyen los 10 candidatos pequeños, $J$ queda con 7 sitios y hay dos formas de
fijar $B$: conservarlo (3.547,5 M; la base no cambia) o recalcularlo con la misma regla sobre los elegibles,
$B=0{,}5\sum_{j\in J^{IG}}F_j=0{,}5\times 6.060=3.030$ M (la base baja a 4.089 atendidos: Palmira, Jamundí, Yumbo).

## Extensión: equidad territorial

| | Expresión | Explicación |
|---|---|---|
| E1 | $\sum_{i\in I_k}\sum_{j\in J_i}x_{ij}\ \ge\ \alpha\sum_{i\in I_k}d_i\quad\forall k\in\mathcal K$ | Nueva familia: cada departamento recibe al menos la fracción $\alpha$ de su demanda |
| E2 | $\alpha\ge\underline\alpha$ | Piso de política fijado por el decisor |
| E3 | $\sum_{j\in J_i}x_{ij}\ \ge\ \beta\,d_i\quad\forall i\in I$ | Nueva familia (implementada): piso municipal; con $\beta>0$ ningún municipio queda en 0 % |

1. $\alpha^*=\max\alpha$ s.a. R1–R5 y E1 se resuelve directamente como MILP (HiGHS vía PuLP; CBC no lo certifica en 10 min) y se
   comprueba que el piso de la siguiente décima de punto (29,1 %) es infactible. Resultado: $\alpha^*=$ 29,05 % (se reporta como 29,0 % con un decimal,
   redondeado hacia abajo; un valor redondeado hacia arriba sería infactible).
2. Frontera: para $\underline\alpha\in\{0,5,10,15,20,25\}\,\%\cup\{\alpha^*\}$ se resuelve el modelo lexicográfico con E1–E2. Precio de
   la equidad en $\alpha^*$: 250 personas.
3. Piso municipal: $\beta^*=\max\beta$ s.a. R1–R5 y E3 = 27,05 %; frontera para $\beta\in[0,\beta^*]$.

**Variante recomendada: β (E3); α (E1–E2) como complemento.** El piso departamental puede cumplirse concentrando cupos en pocos
municipios: con $\underline\alpha$ = 25 % quedan 22 municipios en 0 % y con $\alpha^*$, 10. El piso municipal protege a cada municipio:
con β = 2,5 % ningún municipio queda en 0 %, se conserva la red base (Palmira, Tuluá) y el costo es de solo 49 personas (5.736 → 5.687).
Por eso se recomienda β = 2,5 % y se presenta α como complemento para equilibrar departamentos. Ambas familias quedan formuladas e
implementadas.

## Estado del solver

Cada resolución se acepta solo si `LpStatus == "Optimal"` **y** `sol_status == LpSolutionOptimal`. PuLP devuelve `LpStatus =
"Optimal"` también cuando CBC o HiGHS se detienen por `timeLimit` con una solución entera factible (`sol_status =
LpSolutionIntegerFeasible`); esos casos se reportan como "Factible sin prueba de optimalidad" y detienen el notebook. Única excepción: en las pruebas de factibilidad de los pisos de equidad, una solución entera factible basta para probar que el piso es alcanzable. El registro
completo está en `results/tablas/registro_solver.csv`.
