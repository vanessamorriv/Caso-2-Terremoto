"""Caso 2 · Terremoto en Colombia — Simulación Monte Carlo de robustez (Streamlit).

Ejecutar desde la raíz del repositorio (o desde cualquier carpeta, indicando la ruta del proyecto en la barra lateral):

    streamlit run montecarlo_streamlit.py

Qué hace
--------
Repite el MILP lexicográfico del notebook 02 (máx. personas atendidas → mín. costo, con R1–R5 y presupuesto sobre el costo
total) para muchas combinaciones de cuatro parámetros inciertos (fracción f, factor de tamaño de hogar, costo fijo por
plaza c_f y costo de kits v), y resume qué tan estable es la red de campamentos.

Es un ANÁLISIS DE ROBUSTEZ frente a parámetros estimados o asumidos, no una predicción: no asigna probabilidades "reales"
a los escenarios, solo explora el rango plausible de cada supuesto.

Garantías
---------
- Solo LEE archivos de data/processed/ (y, si existe, results/tablas/resumen_kpis.csv para comparar). No escribe nada en
  el proyecto; los resultados viven en memoria (st.session_state) y se pueden descargar como CSV desde la app.
- Usa las coordenadas, distancias, capacidades y parámetros que ya están en el proyecto. No inventa datos.
- Cada simulación exige que CBC certifique optimalidad en las dos etapas (LpStatus = Optimal y sol_status = óptimo);
  las que no, se descartan y se cuentan.

Dependencias: streamlit, pandas, numpy, pulp (<4), altair y pydeck (estos dos vienen con streamlit).
"""
from __future__ import annotations

import json
import math
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

# ------------------------------------------------------------------------------------------------------------------
# 1. Lectura de datos del proyecto (solo lectura)
# ------------------------------------------------------------------------------------------------------------------
ARCHIVOS = {
    "demanda": "data/processed/demanda.csv",
    "candidatos": "data/processed/candidatos.csv",
    "distancias": "data/processed/distancias_km.csv",
    "parametros": "data/processed/parametros.csv",
    "metadatos": "data/processed/metadatos_instancia.json",
}
OFICIAL_KPI = "results/tablas/resumen_kpis.csv"
ANCHO: dict = {"use_container_width": True}   # opcional: solo para comparar con el resultado oficial


def buscar_raiz(preferida: str | None = None) -> Path | None:
    """Devuelve la carpeta que contiene data/processed/ con todos los archivos requeridos."""
    candidatas = []
    if preferida:
        candidatas.append(Path(preferida).expanduser())
    aqui = Path(__file__).resolve().parent
    candidatas += [aqui, Path.cwd(), aqui / "caso2_terremoto_colombia", Path.cwd() / "caso2_terremoto_colombia",
                   aqui.parent, Path.cwd().parent]
    for c in candidatas:
        if all((c / rel).is_file() for rel in ARCHIVOS.values()):
            return c.resolve()
    return None


def archivos_faltantes(raiz: Path) -> list[str]:
    return [rel for rel in ARCHIVOS.values() if not (raiz / rel).is_file()]


def cargar_datos(raiz: Path) -> dict:
    """Lee los archivos del proyecto. Lanza FileNotFoundError / ValueError con un mensaje claro si algo falta."""
    faltan = archivos_faltantes(raiz)
    if faltan:
        raise FileNotFoundError("Faltan archivos del proyecto: " + ", ".join(faltan))
    dem = pd.read_csv(raiz / ARCHIVOS["demanda"], dtype={"divipola": str}).set_index("id")
    cand = pd.read_csv(raiz / ARCHIVOS["candidatos"], dtype={"divipola": str}).set_index("id")
    dist = pd.read_csv(raiz / ARCHIVOS["distancias"], index_col=0)
    par = pd.read_csv(raiz / ARCHIVOS["parametros"]).set_index("ID")["Valor"].astype(float)
    with open(raiz / ARCHIVOS["metadatos"], encoding="utf-8") as fh:
        meta = json.load(fh)

    req_dem = {"municipio", "departamento", "lat", "lon", "NH_RUD", "familias_RUD", "personas_RUD", "d_f10"}
    req_cand = {"municipio", "departamento", "rol", "categoria", "capacidad_K", "costo_fijo_fj", "lat", "lon"}
    req_par = {"P01", "P02", "P03", "P05", "P06", "P07", "P16", "P17", "P18", "P19", "P20"}
    if not req_dem <= set(dem.columns):
        raise ValueError(f"demanda.csv sin columnas: {sorted(req_dem - set(dem.columns))}")
    if not req_cand <= set(cand.columns):
        raise ValueError(f"candidatos.csv sin columnas: {sorted(req_cand - set(cand.columns))}")
    if not req_par <= set(par.index):
        raise ValueError(f"parametros.csv sin parámetros: {sorted(req_par - set(par.index))}")
    J = list(cand.index[cand.rol == "Candidato"])
    if not set(dem.index) <= set(dist.index) or not set(J) <= set(dist.columns):
        raise ValueError("La matriz de distancias no cubre todos los municipios y candidatos")

    oficial = None
    if (raiz / OFICIAL_KPI).is_file():
        try:
            k = pd.read_csv(raiz / OFICIAL_KPI).set_index("indicador")
            oficial = {"atendidos": float(k.loc["Población atendida", "Base"]), "sitios": str(k.loc["Sitios abiertos", "Base"]),
                       "cobertura": float(k.loc["% atendida", "Base"])}
        except Exception:   # el archivo es opcional
            oficial = None
    return dict(dem=dem, cand=cand, dist=dist, par=par, meta=meta, J=J, oficial=oficial, raiz=raiz)


# ------------------------------------------------------------------------------------------------------------------
# 2. Instancia y MILP (misma lógica que el notebook 02)
# ------------------------------------------------------------------------------------------------------------------
PHI_KEYS = {"Grande": "P05", "Intermedia": "P06", "Pequeña": "P07"}
ESCALA = 1e6   # costos en millones de COP dentro del modelo (estabilidad numérica), igual que el notebook 02


def redondear(v: float) -> int:
    """Redondeo 'mitad hacia arriba', como ROUND de Excel y el notebook 01."""
    return int(math.floor(v + 0.5))


def crear_instancia(datos: dict, f: float, factor_hogar: float, c_f: float, v_kit: float,
                    reduccion: float = 0.0, regla_B: str = "enunciado") -> dict:
    """Recalcula demanda, costos y presupuesto con la lógica del modelo base.

    d_i = round(NH_i · h_i · factor_hogar · f), con h_i = personas_RUD / familias_RUD.
    F_j = K_j · c_f · T · φ_cat(j).
    B   = P17 (50 %) · Σ F_j de los 10 candidatos de mayor capacidad · (1 − reducción)   (regla del enunciado), o
          B fijo en COP = presupuesto base del proyecto · (1 − reducción) (lectura "el dinero disponible no cambia").
    """
    dem, cand, dist, par, meta, J = (datos[k] for k in ("dem", "cand", "dist", "par", "meta", "J"))
    h = dem.personas_RUD / dem.familias_RUD
    d = {i: redondear(dem.loc[i, "NH_RUD"] * h[i] * factor_hogar * f) for i in dem.index}
    F = {j: float(cand.loc[j, "capacidad_K"]) * c_f * par["P02"] * par[PHI_KEYS[cand.loc[j, "categoria"]]] for j in J}
    if regla_B == "enunciado":
        top10 = cand.loc[J].assign(_id=J).sort_values(["capacidad_K", "_id"], ascending=[False, True]).head(10).index
        B = par["P17"] * sum(F[j] for j in top10) * (1 - reduccion)
    else:
        B = float(meta["presupuesto_base_COP"]) * (1 - reduccion)
    tarifa, dmax = float(meta["tarifa_COP_km_persona"]), float(meta["distancia_max_km"])
    A = [(i, j) for i in dem.index for j in J if dist.loc[i, j] <= dmax]
    return dict(I=list(dem.index), J=J, d=d, K={j: int(cand.loc[j, "capacidad_K"]) for j in J}, F=F, v=float(v_kit),
                c={(i, j): tarifa * float(dist.loc[i, j]) for (i, j) in A}, A=A, B=B, dist=dist)


def resolver(inst: dict, limite_s: int = 120) -> dict:
    """MILP lexicográfico: etapa 1 máx. Σx; etapa 2 mín. costo total con Σx ≥ Z1*. R1–R5 como en el notebook 02."""
    import pulp

    I, J, d, K, F, v, c, A, B = (inst[k] for k in ("I", "J", "d", "K", "F", "v", "c", "A", "B"))
    Ji = {i: [] for i in I}
    Ij = {j: [] for j in J}
    for (i, j) in A:
        Ji[i].append(j)
        Ij[j].append(i)
    m = pulp.LpProblem("montecarlo", pulp.LpMaximize)
    y = {j: pulp.LpVariable(f"y_{j}", cat="Binary") for j in J}
    x = {a: pulp.LpVariable(f"x_{a[0]}_{a[1]}", lowBound=0, cat="Integer") for a in A}
    u = {i: pulp.LpVariable(f"u_{i}", lowBound=0) for i in I}
    atendidos = pulp.lpSum(x.values())
    costo = pulp.lpSum(F[j] / ESCALA * y[j] for j in J) + pulp.lpSum((v + c[a]) / ESCALA * x[a] for a in A)
    for i in I:                                                          # R1 balance de demanda
        m += pulp.lpSum(x[(i, j)] for j in Ji[i]) + u[i] == d[i]
    for j in J:                                                          # R2 capacidad y apertura
        m += pulp.lpSum(x[(i, j)] for i in Ij[j]) <= K[j] * y[j]
    for (i, j) in A:                                                     # R3 desigualdad válida
        m += x[(i, j)] <= min(d[i], K[j]) * y[j]
    m += costo <= B / ESCALA                                             # R4 presupuesto (costo total)
    # R5: x solo existe para arcos con distancia ≤ 180 km (conjunto A)
    solver = pulp.PULP_CBC_CMD(msg=False, gapRel=0, timeLimit=limite_s, threads=1)

    def certificado():
        return m.status == pulp.LpStatusOptimal and m.sol_status == pulp.LpSolutionOptimal

    m.setObjective(atendidos)
    m.sense = pulp.LpMaximize
    m.solve(solver)
    if not certificado():
        return dict(ok=False, estado=f"etapa 1: {pulp.LpStatus[m.status]} (sol_status {m.sol_status})")
    Z1 = int(round(pulp.value(atendidos)))
    m += atendidos >= Z1                                                 # R6 mantener cobertura
    m.setObjective(costo)
    m.sense = pulp.LpMinimize
    m.solve(solver)
    if not certificado():
        return dict(ok=False, estado=f"etapa 2: {pulp.LpStatus[m.status]} (sol_status {m.sol_status})")
    flujos = {a: int(round(x[a].value() or 0)) for a in A}
    flujos = {a: q for a, q in flujos.items() if q > 0}
    abiertos = sorted(j for j in J if (y[j].value() or 0) > 0.5)
    costo_fijo = sum(F[j] for j in abiertos)
    costo_total = costo_fijo + sum((v + c[a]) * q for a, q in flujos.items())
    # Comprobaciones de consistencia (equivalen a T1–T5 del notebook)
    assert sum(flujos.values()) == Z1
    assert all(sum(q for (i, j), q in flujos.items() if j == jj) <= K[jj] for jj in abiertos)
    assert costo_total <= B * (1 + 1e-9) + 1
    return dict(ok=True, estado="Optimal", atendidos=Z1, abiertos=abiertos, flujos=flujos,
                costo_total=costo_total, costo_fijo=costo_fijo)


# ------------------------------------------------------------------------------------------------------------------
# 3. Muestreo (hipercubo latino con distribuciones triangulares o uniformes)
# ------------------------------------------------------------------------------------------------------------------
PARAMS = {   # nombre: (etiqueta, mínimo, moda, máximo, distribución, valor del modelo base, formato)
    "f": ("Fracción que requiere campamento f", 0.02, 0.10, 0.13, "triangular", 0.10, "pct"),
    "factor_hogar": ("Factor de tamaño de hogar", 1.00, None, 1.42, "uniforme", 1.00, "num"),
    "c_f": ("Costo fijo por plaza-mes c_f (COP)", 100_000, 200_000, 400_000, "triangular", 200_000, "cop"),
    "v_kit": ("Costo de kits por persona v (COP)", 30_000, 60_000, 70_000, "triangular", 60_000, "cop"),
}


def inv_triangular(u: np.ndarray, a: float, c: float, b: float) -> np.ndarray:
    fc = (c - a) / (b - a)
    return np.where(u < fc, a + np.sqrt(u * (b - a) * (c - a)), b - np.sqrt((1 - u) * (b - a) * (b - c)))


def muestrear(n: int, semilla: int, rangos: dict, metodo: str = "lhs") -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    cols = {}
    for k, (a, c, b, dist_) in rangos.items():
        if metodo == "lhs":   # un valor por estrato de probabilidad, en orden aleatorio
            u = (rng.permutation(n) + rng.random(n)) / n
        else:
            u = rng.random(n)
        cols[k] = inv_triangular(u, a, c, b) if dist_ == "triangular" else a + u * (b - a)
    return pd.DataFrame(cols)


def simular(datos: dict, muestras: pd.DataFrame, reduccion: float, regla_B: str, limite_s: int, progreso=None) -> dict:
    """Ejecuta el MILP para cada fila de `muestras` y guarda todo en memoria."""
    filas, flujos_sim, atend_mun = [], [], []
    for k, r in enumerate(muestras.itertuples(index=False)):
        inst = crear_instancia(datos, r.f, r.factor_hogar, r.c_f, r.v_kit, reduccion, regla_B)
        t0 = time.time()
        try:
            sol = resolver(inst, limite_s)
        except Exception as e:   # un fallo del solver no debe tumbar la app
            sol = dict(ok=False, estado=f"error: {e}")
        demanda = sum(inst["d"].values())
        fila = dict(sim=k + 1, f=r.f, factor_hogar=r.factor_hogar, c_f=r.c_f, v_kit=r.v_kit, demanda=demanda,
                    presupuesto=inst["B"], valida=sol["ok"], estado=sol["estado"], segundos=round(time.time() - t0, 2))
        if sol["ok"]:
            fila.update(atendidos=sol["atendidos"], cobertura=sol["atendidos"] / max(demanda, 1),
                        n_abiertos=len(sol["abiertos"]), red=", ".join(datos["cand"].loc[sol["abiertos"], "municipio"]),
                        costo_total=sol["costo_total"], uso_presupuesto=sol["costo_total"] / inst["B"])
            flujos_sim.append(sol["flujos"])
            por_mun = Counter()
            for (i, _j), q in sol["flujos"].items():
                por_mun[i] += q
            atend_mun.append({i: (por_mun.get(i, 0), inst["d"][i]) for i in inst["I"]})
            for j in datos["J"]:
                fila[f"y_{j}"] = int(j in sol["abiertos"])
        filas.append(fila)
        if progreso:
            progreso(k + 1, len(muestras))
    return dict(tabla=pd.DataFrame(filas), flujos=flujos_sim, atend_mun=atend_mun)


# ------------------------------------------------------------------------------------------------------------------
# 4. Resúmenes de robustez
# ------------------------------------------------------------------------------------------------------------------
def clasificar_sitio(fr: float) -> str:
    if fr >= 0.8:
        return "Núcleo"
    if fr >= 0.2:
        return "Sensible"
    if fr > 0:
        return "Ocasional"
    return "Nunca abierto"


def resumen_sitios(datos: dict, res: dict) -> pd.DataFrame:
    t = res["tabla"][res["tabla"].valida]
    cand = datos["cand"].loc[datos["J"]]
    out = cand[["municipio", "departamento", "categoria", "capacidad_K", "lat", "lon"]].copy()
    out["frecuencia_apertura"] = [t[f"y_{j}"].mean() if len(t) else 0.0 for j in datos["J"]]
    usos = Counter()
    for fl in res["flujos"]:
        for (i, j), q in fl.items():
            usos[j] += q
    out["ocupacion_media"] = [usos[j] / max(len(t), 1) for j in datos["J"]]
    out["clase"] = out.frecuencia_apertura.apply(clasificar_sitio)
    return out


def resumen_municipios(datos: dict, res: dict) -> pd.DataFrame:
    dem = datos["dem"]
    n = len(res["atend_mun"])
    out = dem[["municipio", "departamento", "lat", "lon"]].copy()
    if n == 0:
        for c in ("demanda_media", "atendidos_media", "cobertura_media", "prob_atencion", "prob_sin_atencion"):
            out[c] = np.nan
        out["clase"] = "Sin datos"
        return out
    a = np.array([[s[i][0] for i in dem.index] for s in res["atend_mun"]], dtype=float)
    d = np.array([[s[i][1] for i in dem.index] for s in res["atend_mun"]], dtype=float)
    out["demanda_media"] = d.mean(axis=0)
    out["atendidos_media"] = a.mean(axis=0)
    out["cobertura_media"] = np.where(d > 0, a / np.maximum(d, 1), 0).mean(axis=0)
    out["prob_atencion"] = (a > 0).mean(axis=0)
    out["prob_sin_atencion"] = 1 - out["prob_atencion"]
    out["clase"] = np.select([out.prob_atencion >= 0.8, out.prob_sin_atencion >= 0.8],
                             ["Robustamente atendido", "Vulnerable"], "Intermedio")
    return out


def resumen_arcos(datos: dict, res: dict) -> pd.DataFrame:
    n = len(res["flujos"])
    cnt, tot = Counter(), Counter()
    for fl in res["flujos"]:
        for a, q in fl.items():
            cnt[a] += 1
            tot[a] += q
    filas = [dict(id_demanda=i, id_sitio=j, frecuencia=cnt[(i, j)] / n, flujo_medio_si_se_usa=tot[(i, j)] / cnt[(i, j)],
                  km=float(datos["dist"].loc[i, j])) for (i, j) in cnt] if n else []
    return pd.DataFrame(filas, columns=["id_demanda", "id_sitio", "frecuencia", "flujo_medio_si_se_usa", "km"])


def sensibilidad(tabla: pd.DataFrame, metrica: str) -> pd.DataFrame:
    """Correlación de rangos de Spearman entre cada parámetro y la métrica (robusta a no linealidades monótonas)."""
    t = tabla[tabla.valida]
    filas = []
    for k, (etq, *_r) in PARAMS.items():
        if t[k].nunique() > 1 and t[metrica].nunique() > 1:
            rho = t[k].rank().corr(t[metrica].rank())
        else:
            rho = 0.0
        lo, hi = t[k].quantile([1 / 3, 2 / 3])
        bajo, alto = t.loc[t[k] <= lo, metrica].mean(), t.loc[t[k] >= hi, metrica].mean()
        filas.append(dict(parametro=etq, clave=k, spearman=rho, media_tercio_bajo=bajo, media_tercio_alto=alto,
                          diferencia=alto - bajo))
    return pd.DataFrame(filas).sort_values("spearman", key=lambda s: s.abs(), ascending=False)


# ------------------------------------------------------------------------------------------------------------------
# 5. Interfaz Streamlit
# ------------------------------------------------------------------------------------------------------------------
# Paleta (clara y neutra). Rojo solo para vulnerabilidad/alertas; verde suave solo para resultados positivos.
# ------------------------------------------------------------------------------------------------------------------
PAL = dict(
    fondo="#F7F6F3", lateral="#F0EEE9", tarjeta="#FFFFFF", borde="#E4E0D8", rejilla="#ECE9E3",
    tinta="#2E3338", tinta2="#5F656B", tenue="#8A8F94",
    acento="#56697C",        # azul grisáceo: botones, líneas y series neutras
    acento_suave="#A9B6C2",  # azul grisáceo claro
    taupe="#B9AD9C", taupe_suave="#E6E0D6",
    verde="#3F7D5A",         # verde salvia oscuro (positivo)
    ambar="#B8862E",         # ocre apagado (intermedio)
    rojo="#B04A3F",          # rojo apagado (vulnerable / alerta)
)
COLOR_CLASE_SITIO = {"Núcleo": [63, 125, 90], "Sensible": [184, 134, 46], "Ocasional": [91, 132, 168], "Nunca abierto": [189, 184, 176]}
COLOR_CLASE_MUN = {"Robustamente atendido": [63, 125, 90], "Intermedio": [201, 180, 138], "Vulnerable": [176, 74, 63]}
FUENTE = "Inter, 'Source Sans 3', 'Segoe UI', Helvetica, Arial, sans-serif"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select {{ font-family: {FUENTE}; }}
.stApp {{ background: {PAL['fondo']}; color: {PAL['tinta']}; }}
[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1380px; }}
h1, h2, h3, h4 {{ color: {PAL['tinta']}; font-weight: 600; letter-spacing: -0.01em; }}
[data-testid="stSidebar"] {{ background: {PAL['lateral']}; border-right: 1px solid {PAL['borde']}; }}
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{ font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em;
    color: {PAL['tinta2']}; margin-top: 1.1rem; margin-bottom: 0.2rem; font-weight: 600; }}
/* tarjetas */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{ border-radius: 10px; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-color: {PAL['borde']} !important; background: {PAL['tarjeta']};
    box-shadow: 0 1px 2px rgba(46, 51, 56, 0.04); }}
[data-testid="stMetric"] {{ background: {PAL['tarjeta']}; border: 1px solid {PAL['borde']}; border-radius: 10px;
    padding: 0.85rem 1rem 0.75rem 1rem; box-shadow: 0 1px 2px rgba(46, 51, 56, 0.04); min-height: 104px; }}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] div {{ overflow: visible !important; }}
[data-testid="stMetricLabel"] p {{ white-space: normal !important; overflow: visible !important; text-overflow: clip !important; line-height: 1.25;
    font-size: 0.78rem !important; color: {PAL['tinta2']}; text-transform: uppercase; letter-spacing: 0.04em; }}
[data-testid="stMetricValue"] {{ font-size: 1.55rem !important; font-weight: 600; color: {PAL['tinta']}; }}
[data-testid="stMetricDelta"] {{ font-size: 0.8rem; }}
[data-testid="stMetricDelta"] svg {{ display: none; }}
/* botones */
.stButton > button, .stDownloadButton > button {{ border-radius: 8px; border: 1px solid {PAL['borde']}; background: {PAL['tarjeta']};
    color: {PAL['tinta']}; font-weight: 500; box-shadow: none; }}
.stButton > button[kind="primary"] {{ background: {PAL['acento']}; border-color: {PAL['acento']}; color: #FFFFFF; }}
.stButton > button[kind="primary"]:hover {{ background: #4A5B6C; border-color: #4A5B6C; }}
/* etiquetas de selección múltiple: discretas */
[data-baseweb="tag"] {{ background: {PAL['taupe_suave']} !important; border-radius: 6px !important; }}
[data-baseweb="tag"] span, [data-baseweb="tag"] svg {{ color: {PAL['tinta']} !important; fill: {PAL['tinta2']} !important; }}
/* tablas, expanders y avisos */
[data-testid="stDataFrame"] {{ border: 1px solid {PAL['borde']}; border-radius: 8px; }}
[data-testid="stExpander"] details {{ border: 1px solid {PAL['borde']}; border-radius: 10px; background: {PAL['tarjeta']}; }}
[data-testid="stAlert"] {{ border-radius: 8px; }}
.mc-titulo {{ font-size: 1.65rem; font-weight: 600; color: {PAL['tinta']}; margin: 0 0 0.15rem 0; letter-spacing: -0.015em; }}
.mc-sub {{ color: {PAL['tinta2']}; font-size: 0.95rem; margin-bottom: 0.4rem; }}
.mc-etiqueta {{ display: inline-block; font-size: 0.72rem; color: {PAL['tinta2']}; background: {PAL['taupe_suave']};
    border-radius: 999px; padding: 0.12rem 0.6rem; margin-right: 0.35rem; }}
.mc-seccion {{ margin: 2.1rem 0 0.7rem 0; padding-bottom: 0.35rem; border-bottom: 1px solid {PAL['borde']}; }}
.mc-seccion .t {{ font-size: 1.12rem; font-weight: 600; color: {PAL['tinta']}; }}
.mc-seccion .s {{ font-size: 0.85rem; color: {PAL['tinta2']}; margin-top: 0.1rem; }}
.mc-graf {{ font-size: 0.92rem; font-weight: 600; color: {PAL['tinta']}; margin: 0.1rem 0 0.2rem 0; }}
.mc-leyenda {{ font-size: 0.84rem; color: {PAL['tinta']}; line-height: 1.55; }}
.mc-leyenda .g {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: {PAL['tinta2']}; font-weight: 600;
    margin: 0.2rem 0 0.25rem 0; }}
.mc-leyenda .n {{ color: {PAL['tinta2']}; font-size: 0.78rem; }}
.mc-leyenda .sw {{ display: inline-block; width: 11px; height: 11px; margin-right: 7px; vertical-align: -1px; }}
.mc-leyenda .sep {{ border-top: 1px solid {PAL['borde']}; margin: 0.65rem 0; }}
</style>
"""


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def _escala_divergente(v: float) -> list[int]:
    """0 → rojo apagado (vulnerable), 0,5 → neutro claro, 1 → verde salvia (robusto)."""
    v = 0.0 if v is None or np.isnan(v) else min(max(v, 0.0), 1.0)
    a, m, b = np.array([176, 74, 63]), np.array([226, 221, 211]), np.array([63, 125, 90])
    rgb = a + (m - a) * (v / 0.5) if v < 0.5 else m + (b - m) * ((v - 0.5) / 0.5)
    return [int(x) for x in rgb]


def _escala_secuencial(v: float, vmax: float) -> list[int]:
    t = 0.0 if vmax <= 0 else min(max(v / vmax, 0.0), 1.0)
    a, b = np.array([226, 229, 232]), np.array([62, 82, 102])
    return [int(x) for x in a + (b - a) * t]


def _fmt(v, tipo):
    if tipo == "pct":
        return f"{100 * v:.1f} %".replace(".", ",")
    if tipo == "cop":
        return f"${v:,.0f}".replace(",", ".")
    return f"{v:.2f}".replace(".", ",")


def _estilo(ch, alto=300):
    """Misma línea visual para todos los gráficos: fondo blanco, rejilla suave, texto gris oscuro, sin marco."""
    return (ch.properties(height=alto, background=PAL["tarjeta"], padding={"left": 6, "right": 12, "top": 10, "bottom": 6})
            .configure(font=FUENTE)
            .configure_view(strokeWidth=0)
            .configure_axis(gridColor=PAL["rejilla"], gridWidth=1, domainColor=PAL["borde"], tickColor=PAL["borde"],
                            labelColor=PAL["tinta2"], titleColor=PAL["tinta2"], labelFontSize=11, titleFontSize=11,
                            titleFontWeight=500, titlePadding=8, labelPadding=4)
            .configure_legend(labelColor=PAL["tinta2"], titleColor=PAL["tinta2"], labelFontSize=11, titleFontSize=11,
                              titleFontWeight=500, symbolSize=70, orient="top", direction="horizontal", padding=2))


def _tema_claro(st):
    """Fuerza el tema claro de Streamlit (aunque el sistema operativo use modo oscuro) con la paleta de la app."""
    for k, v in {"theme.base": "light", "theme.primaryColor": PAL["acento"], "theme.backgroundColor": PAL["fondo"],
                 "theme.secondaryBackgroundColor": PAL["lateral"], "theme.textColor": PAL["tinta"]}.items():
        try:
            st._config.set_option(k, v)
        except Exception:   # versiones sin la opción: el CSS de abajo mantiene el aspecto claro
            pass


def main():
    import altair as alt
    import pydeck as pdk
    import streamlit as st

    global ANCHO   # ancho completo, compatible con versiones nuevas (width="stretch") y antiguas (use_container_width)
    try:
        ver = tuple(int(x) for x in st.__version__.split(".")[:2])
    except ValueError:
        ver = (0, 0)
    ANCHO = {"width": "stretch"} if ver >= (1, 46) else {"use_container_width": True}
    TARJETA = {"border": True} if ver >= (1, 29) else {}

    _tema_claro(st)
    st.set_page_config(page_title="Monte Carlo · Caso 2 Terremoto", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    def seccion(titulo, sub=""):
        st.markdown(f"<div class='mc-seccion'><div class='t'>{titulo}</div>" + (f"<div class='s'>{sub}</div>" if sub else "") + "</div>",
                    unsafe_allow_html=True)

    def subtitulo(txt):
        st.markdown(f"<div class='mc-graf'>{txt}</div>", unsafe_allow_html=True)

    def grafico(ch, alto=300):
        st.altair_chart(_estilo(ch, alto), theme=None, **ANCHO)

    st.markdown("<div class='mc-titulo'>Robustez de la red de campamentos</div>"
                "<div class='mc-sub'>Caso 2 · Terremoto en Colombia · simulación Monte Carlo sobre el MILP lexicográfico del notebook 02</div>"
                "<span class='mc-etiqueta'>Análisis de robustez, no predicción</span>"
                "<span class='mc-etiqueta'>No modifica los resultados oficiales</span>", unsafe_allow_html=True)

    # ---------------- Barra lateral: datos y configuración ----------------
    with st.sidebar:
        st.header("Datos del proyecto")
        ruta = st.text_input("Carpeta del proyecto (opcional)", value="",
                             help="Raíz del repositorio (la que contiene data/processed/). Si se deja vacía, se busca junto a este archivo.")
        raiz = buscar_raiz(ruta or None)
        if ruta and raiz is not None and Path(ruta).expanduser().resolve() != raiz:
            st.warning("La carpeta indicada no tiene los archivos del proyecto; se usa la encontrada automáticamente.")
        if raiz is None:
            st.error("No se encontraron los archivos del proyecto. Se necesitan:\n\n" + "\n".join(f"- `{r}`" for r in ARCHIVOS.values())
                     + "\n\nEjecute la app desde la raíz del repositorio o indique la carpeta arriba.")
            st.stop()
        try:
            datos = cargar_datos(raiz)
        except Exception as e:
            st.error(f"No se pudieron leer los datos del proyecto: {e}")
            st.stop()
        st.caption(f"✓ Proyecto `{raiz.name}` · {len(datos['dem'])} municipios · {len(datos['J'])} candidatos")

        st.header("Simulación")
        rapido = st.toggle("Modo rápido", value=True, help="Rápido: 25 simulaciones para explorar. Completo: ≥ 300 para reportar.")
        n_sim = st.number_input("Número de simulaciones", min_value=20 if rapido else 300, max_value=60 if rapido else 2000,
                                value=25 if rapido else 300, step=5 if rapido else 50)
        semilla = st.number_input("Semilla", min_value=0, max_value=10**9, value=2026, step=1)
        metodo = st.radio("Muestreo", ["Hipercubo latino", "Monte Carlo simple"], horizontal=True,
                          help="El hipercubo latino cubre mejor cada rango con pocas simulaciones.")
        nivel = st.selectbox("Nivel de presupuesto", ["Base", "Reducción −15 %", "Reducción −30 %"])
        reduccion = {"Base": 0.0, "Reducción −15 %": float(datos["par"]["P18"]), "Reducción −30 %": float(datos["par"]["P19"])}[nivel]
        regla = st.radio("Presupuesto B", ["Regla del enunciado (escala con c_f)", "Fijo en COP (no depende de c_f)"],
                         help="La regla del enunciado (B = 50 % del costo fijo de los 10 mayores) hace que B crezca con c_f, "
                              "y entonces c_f casi no cambia los atendidos. Con B fijo se mide el efecto real de que operar "
                              "sea más caro o más barato con el mismo dinero.")
        regla_B = "enunciado" if regla.startswith("Regla") else "fijo"
        limite_s = st.number_input("Límite por resolución (s)", min_value=10, max_value=600, value=120, step=10)

        st.header("Rangos (mín · moda · máx)")
        rangos = {}
        for k, (etq, a, c, b, dist_, base, tipo) in PARAMS.items():
            with st.expander(etq, expanded=False):
                if tipo == "pct":
                    lo, hi = st.slider("Rango (%)", 0.5, 25.0, (100 * a, 100 * b), 0.1, key=f"r_{k}")
                    lo, hi = lo / 100, hi / 100
                    moda = st.slider("Moda (%)", lo * 100, hi * 100, min(max(100 * c, lo * 100), hi * 100), 0.1, key=f"m_{k}") / 100
                elif tipo == "num":
                    lo, hi = st.slider("Rango", 0.8, 2.0, (a, b), 0.01, key=f"r_{k}")
                    moda = None
                else:
                    paso = 10_000 if k == "c_f" else 1_000
                    tope = 600_000 if k == "c_f" else 120_000
                    lo, hi = st.slider("Rango (COP)", 0, tope, (int(a), int(b)), paso, key=f"r_{k}")
                    moda = st.slider("Moda (COP)", lo, hi, int(min(max(c, lo), hi)), paso, key=f"m_{k}")
                dist_sel = st.selectbox("Distribución", ["triangular", "uniforme"], index=0 if dist_ == "triangular" else 1, key=f"d_{k}")
                if dist_sel == "triangular" and moda is None:
                    moda = (lo + hi) / 2
                rangos[k] = (lo, moda if moda is not None else lo, hi, dist_sel)
                st.caption(f"Valor del modelo base: {_fmt(base, tipo)}")
        st.write("")
        ejecutar = st.button("Ejecutar simulación", type="primary", **ANCHO)

    # ---------------- Tabla de rangos usados ----------------
    seccion("Supuestos inciertos", "Rangos y distribuciones que se muestrean en cada simulación")
    with st.container(**TARJETA):
        st.dataframe(pd.DataFrame([dict(Parámetro=PARAMS[k][0], Mínimo=_fmt(lo, PARAMS[k][6]),
                                         Moda=_fmt(mo, PARAMS[k][6]) if dist_ == "triangular" else "—",
                                         Máximo=_fmt(hi, PARAMS[k][6]), Distribución=dist_.capitalize(),
                                         **{"Modelo base": _fmt(PARAMS[k][5], PARAMS[k][6])})
                                    for k, (lo, mo, hi, dist_) in rangos.items()]), hide_index=True, **ANCHO)
        st.caption("Se muestrean de forma independiente. La demanda es d_i = round(NH_i · h_i · factor de hogar · f); los costos fijos "
                   "F_j = K_j · c_f · T · φ_j; el presupuesto sigue la opción elegida; distancias, capacidades y la tarifa de transporte "
                   "son las del proyecto (no son inciertas aquí).")

    # ---------------- Escenario de referencia con el mismo código ----------------
    @st.cache_data(show_spinner=False)
    def referencia(raiz_txt: str, reduccion_: float, regla_: str):
        d_ = cargar_datos(Path(raiz_txt))
        base = {k: v[5] for k, v in PARAMS.items()}
        inst = crear_instancia(d_, base["f"], base["factor_hogar"], base["c_f"], base["v_kit"], reduccion_, regla_)
        sol = resolver(inst)
        sol["demanda"] = sum(inst["d"].values())
        sol["red"] = ", ".join(d_["cand"].loc[sol.get("abiertos", []), "municipio"]) if sol["ok"] else ""
        return sol

    if ejecutar:
        muestras = muestrear(int(n_sim), int(semilla), rangos, "lhs" if metodo.startswith("Hiper") else "mc")
        barra = st.progress(0.0, text="Resolviendo…")
        t0 = time.time()
        res = simular(datos, muestras, reduccion, regla_B, int(limite_s),
                      progreso=lambda k, n: barra.progress(k / n, text=f"Simulación {k} de {n}"))
        barra.empty()
        st.session_state["mc"] = dict(res=res, nivel=nivel, reduccion=reduccion, regla_B=regla_B, segundos=time.time() - t0, rangos=rangos,
                                      semilla=int(semilla), n=int(n_sim), raiz=str(raiz))

    if "mc" not in st.session_state:
        st.info("Configure los rangos en la barra lateral y pulse **Ejecutar simulación**. En modo rápido (25 simulaciones) "
                "tarda alrededor de un minuto; el modo completo (≥ 300) es el que conviene reportar.")
        st.stop()

    mc = st.session_state["mc"]
    if mc["raiz"] != str(raiz):
        st.warning("Los resultados mostrados corresponden a otra carpeta de proyecto; vuelva a ejecutar.")
    res = mc["res"]
    tabla = res["tabla"]
    validas = tabla[tabla.valida]
    n_val = len(validas)
    ref = referencia(str(raiz), mc["reduccion"], mc["regla_B"])
    if n_val == 0:
        st.error("Ninguna simulación terminó con optimalidad certificada. Aumente el límite de tiempo.")
        st.dataframe(tabla[["sim", "estado"]])
        st.stop()

    sitios = resumen_sitios(datos, res)
    muni = resumen_municipios(datos, res)
    arcos = resumen_arcos(datos, res)
    nom = {**datos["dem"].municipio.to_dict(), **datos["cand"].municipio.to_dict()}

    # ---------------- Indicadores ----------------
    seccion(f"Resultados · {mc['nivel']} · presupuesto {'según la regla del enunciado' if mc['regla_B'] == 'enunciado' else 'fijo en COP'}",
            f"{n_val} de {len(tabla)} simulaciones válidas (optimalidad certificada en las dos etapas) · semilla {mc['semilla']} · "
            f"{mc['segundos']:.0f} s · cobertura = personas atendidas ÷ demanda de esa simulación")
    cob = validas.cobertura
    top = sitios.sort_values(["frecuencia_apertura", "capacidad_K"], ascending=False).iloc[0]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cobertura promedio", _fmt(cob.mean(), "pct"))
    c2.metric("Cobertura mediana", _fmt(cob.median(), "pct"))
    c3.metric("P10", _fmt(cob.quantile(0.10), "pct"))
    c4.metric("P90", _fmt(cob.quantile(0.90), "pct"))
    c5.metric("Campamentos abiertos (prom.)", f"{validas.n_abiertos.mean():.1f}".replace(".", ","))
    d1, d2, d3, d4, d5 = st.columns(5)
    d1.metric("Campamento más robusto", top.municipio, f"abierto en {_fmt(top.frecuencia_apertura, 'pct')}", delta_color="off")
    d2.metric("Personas atendidas (prom.)", f"{validas.atendidos.mean():,.0f}".replace(",", "."))
    d3.metric("Personas atendidas P10–P90", f"{validas.atendidos.quantile(.1):,.0f} – {validas.atendidos.quantile(.9):,.0f}".replace(",", "."))
    d4.metric("Demanda (prom.)", f"{validas.demanda.mean():,.0f}".replace(",", "."))
    red_base = ref.get("red", "")
    d5.metric("Simulaciones con la misma red que la referencia", _fmt((validas.red == red_base).mean(), "pct"))
    if (tabla.valida == False).any():   # noqa: E712
        st.warning(f"{(~tabla.valida).sum()} simulaciones descartadas (sin optimalidad certificada); ver tabla de resultados.")

    # ---------------- Comparación con el escenario base ----------------
    seccion("Comparación con el escenario de referencia", "Mismos parámetros del modelo base resueltos con este código")
    with st.container(**TARJETA):
        filas_cmp = [dict(Indicador="Personas atendidas", Referencia=ref.get("atendidos"), **{"Monte Carlo (media)": validas.atendidos.mean(),
                          "P10": validas.atendidos.quantile(.1), "P90": validas.atendidos.quantile(.9)}),
                     dict(Indicador="Cobertura (%)", Referencia=100 * ref.get("atendidos", 0) / max(ref.get("demanda", 1), 1),
                          **{"Monte Carlo (media)": 100 * cob.mean(), "P10": 100 * cob.quantile(.1), "P90": 100 * cob.quantile(.9)}),
                     dict(Indicador="Demanda", Referencia=ref.get("demanda"), **{"Monte Carlo (media)": validas.demanda.mean(),
                          "P10": validas.demanda.quantile(.1), "P90": validas.demanda.quantile(.9)}),
                     dict(Indicador="Campamentos abiertos", Referencia=len(ref.get("abiertos", [])), **{"Monte Carlo (media)": validas.n_abiertos.mean(),
                          "P10": validas.n_abiertos.quantile(.1), "P90": validas.n_abiertos.quantile(.9)})]
        st.dataframe(pd.DataFrame(filas_cmp).round(1), hide_index=True, **ANCHO)
        texto_ref = (f"Referencia = los mismos parámetros del modelo base (f = 10 %, hogar × 1, c_f = 200.000, v = 60.000) resueltos con este "
                     f"mismo código: {ref.get('atendidos', '—')} personas con {red_base or '—'}.")
        of = datos.get("oficial")
        if of and mc["nivel"] == "Base" and mc["regla_B"] == "enunciado":
            coincide = int(of["atendidos"]) == ref.get("atendidos") and sorted(of["sitios"].split(", ")) == sorted(red_base.split(", "))
            texto_ref += (f" Resultado oficial (results/tablas/resumen_kpis.csv): {int(of['atendidos'])} personas con {of['sitios']} — "
                          + ("**coincide**." if coincide else "**no coincide: revise los datos.**"))
        st.caption(texto_ref)
        st.caption(f"Probabilidad de atender al menos tantas personas como la referencia: "
                   f"{_fmt((validas.atendidos >= ref.get('atendidos', np.inf)).mean(), 'pct')}.")

    # ---------------- Distribuciones ----------------
    seccion("Distribución de resultados")
    esc_camp = alt.Scale(range=["#9FB0BF", "#6F8396", "#4E6175", "#34465A", "#22303F", "#151E28"])
    g1, g2 = st.columns(2)
    with g1:
        with st.container(**TARJETA):
            subtitulo("Distribución de la cobertura")
            h = alt.Chart(validas.assign(cob=100 * validas.cobertura)).mark_bar(color=PAL["acento_suave"], cornerRadiusTopLeft=2,
                                                                                cornerRadiusTopRight=2, binSpacing=2).encode(
                x=alt.X("cob:Q", bin=alt.Bin(maxbins=25), title="Cobertura (% de la demanda)"), y=alt.Y("count()", title="Simulaciones"))
            lineas = pd.DataFrame([dict(v=100 * cob.quantile(.1), etq="P10"), dict(v=100 * cob.quantile(.9), etq="P90"),
                                   dict(v=100 * ref.get("atendidos", 0) / max(ref.get("demanda", 1), 1), etq="Referencia")])
            r_ = alt.Chart(lineas).mark_rule(strokeWidth=2).encode(x="v:Q", color=alt.Color("etq:N", title=None,
                 scale=alt.Scale(domain=["P10", "P90", "Referencia"], range=[PAL["taupe"], PAL["taupe"], PAL["tinta"]])),
                 strokeDash=alt.condition(alt.datum.etq == "Referencia", alt.value([1, 0]), alt.value([4, 3])))
            grafico(h + r_)
    with g2:
        with st.container(**TARJETA):
            subtitulo("Personas atendidas frente a la demanda de cada simulación")
            sc = alt.Chart(validas).mark_circle(size=46, opacity=0.8, stroke="white", strokeWidth=0.8).encode(
                x=alt.X("demanda:Q", title="Demanda de la simulación (personas)"), y=alt.Y("atendidos:Q", title="Personas atendidas"),
                color=alt.Color("n_abiertos:O", title="Campamentos", scale=esc_camp),
                tooltip=["sim", "f", "factor_hogar", "c_f", "v_kit", "atendidos", "red"])
            grafico(sc)
            st.caption("Si los puntos forman una línea horizontal, el presupuesto (no la demanda) fija cuántas personas se atienden.")

    f1, f2 = st.columns([1.15, 1])
    with f1:
        with st.container(**TARJETA):
            subtitulo("Frecuencia de apertura por campamento")
            fa = sitios.assign(pct=100 * sitios.frecuencia_apertura).sort_values("pct", ascending=False)
            barras = alt.Chart(fa).mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3, height={"band": 0.72}).encode(
                x=alt.X("pct:Q", title="% de simulaciones en que se abre", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("municipio:N", sort="-x", title=None),
                color=alt.Color("clase:N", title="Clasificación", scale=alt.Scale(domain=list(COLOR_CLASE_SITIO),
                                                                                 range=[_hex(c) for c in COLOR_CLASE_SITIO.values()])),
                tooltip=["municipio", "categoria", "capacidad_K", alt.Tooltip("pct:Q", format=".1f", title="% apertura"), "clase"])
            umbrales = alt.Chart(pd.DataFrame({"v": [20, 80]})).mark_rule(strokeDash=[4, 3], color=PAL["tenue"]).encode(x="v:Q")
            grafico(barras + umbrales, alto=max(300, 24 * len(fa)))
            st.caption("Núcleo ≥ 80 % · Sensible 20–80 % · Ocasional < 20 % · Nunca abierto 0 %.")
    with f2:
        with st.container(**TARJETA):
            subtitulo("Redes más frecuentes")
            redes = validas.red.value_counts().rename_axis("Red de campamentos").reset_index(name="Simulaciones")
            redes["%"] = (100 * redes.Simulaciones / n_val).round(1)
            redes["Atendidos (media)"] = [validas.loc[validas.red == r, "atendidos"].mean().round(0) for r in redes["Red de campamentos"]]
            st.dataframe(redes.head(8), hide_index=True, **ANCHO)

    # ---------------- Sensibilidad ----------------
    seccion("Sensibilidad de los parámetros", "Qué supuesto mueve más el resultado")
    met = st.radio("Métrica", ["Personas atendidas", "Cobertura"], horizontal=True)
    col_met = "atendidos" if met == "Personas atendidas" else "cobertura"
    sens = sensibilidad(tabla, col_met)
    s1, s2 = st.columns([1, 1])
    with s1:
        with st.container(**TARJETA):
            subtitulo("Correlación de rangos (Spearman)")
            tor = alt.Chart(sens).mark_bar(height={"band": 0.6}, cornerRadius=2).encode(
                x=alt.X("spearman:Q", title="Correlación de rangos de Spearman", scale=alt.Scale(domain=[-1, 1])),
                y=alt.Y("parametro:N", sort=alt.EncodingSortField("spearman", op="max", order="descending"), title=None),
                color=alt.condition(alt.datum.spearman > 0, alt.value(PAL["acento"]), alt.value(PAL["taupe"])),
                tooltip=["parametro", alt.Tooltip("spearman:Q", format=".2f")])
            cero = alt.Chart(pd.DataFrame({"v": [0]})).mark_rule(color=PAL["tenue"]).encode(x="v:Q")
            grafico(tor + cero, alto=240)
            st.caption("Positivo (azul grisáceo): al subir el parámetro sube la métrica; negativo (taupe): baja. Con f y el factor de "
                       "hogar la cobertura baja aunque las personas atendidas casi no cambien, porque crece la demanda.")
    with s2:
        with st.container(**TARJETA):
            p_sel = st.selectbox("Parámetro para el diagrama de dispersión", list(PARAMS), format_func=lambda k: PARAMS[k][0])
            disp = alt.Chart(validas).mark_circle(size=40, opacity=0.8, stroke="white", strokeWidth=0.8).encode(
                x=alt.X(f"{p_sel}:Q", title=PARAMS[p_sel][0], scale=alt.Scale(zero=False)),
                y=alt.Y(f"{col_met}:Q", title=met, scale=alt.Scale(zero=False)),
                color=alt.Color("n_abiertos:O", title="Campamentos", scale=esc_camp))
            grafico(disp, alto=240)
    with st.container(**TARJETA):
        st.dataframe(sens.drop(columns="clave").rename(columns={"parametro": "Parámetro", "spearman": "Spearman",
                     "media_tercio_bajo": "Media (tercio bajo)", "media_tercio_alto": "Media (tercio alto)", "diferencia": "Diferencia"}).round(3),
                     hide_index=True, **ANCHO)

    with st.expander("Convergencia (¿son suficientes las simulaciones?)"):
        cv = validas[["sim", "cobertura"]].copy()
        cv["media"] = cv.cobertura.expanding().mean() * 100
        cv["ee"] = cv.cobertura.expanding().std().fillna(0) / np.sqrt(np.arange(1, len(cv) + 1)) * 100
        cv["lo"], cv["hi"] = cv.media - 1.96 * cv.ee, cv.media + 1.96 * cv.ee
        banda = alt.Chart(cv).mark_area(opacity=0.45, color=PAL["taupe_suave"]).encode(x=alt.X("sim:Q", title="Simulación"), y="lo:Q", y2="hi:Q")
        linea = alt.Chart(cv).mark_line(color=PAL["acento"], strokeWidth=2).encode(x="sim:Q", y=alt.Y("media:Q", title="Cobertura media acumulada (%)"))
        grafico(banda + linea, alto=260)
        st.caption(f"Intervalo de 95 % de la media al final: ±{1.96 * cob.std() / np.sqrt(n_val) * 100:.2f} puntos.".replace(".", ","))

    # ---------------- Mapa ----------------
    seccion("Mapa de robustez de la red",
            "Coordenadas: cabeceras DIVIPOLA del proyecto. Las líneas son conexiones directas indicativas (no rutas viales); "
            "su grosor es la frecuencia de uso del arco: simulaciones con x_ij > 0 ÷ simulaciones válidas.")
    deptos = sorted(set(datos["dem"].departamento) | set(datos["cand"].departamento))
    with st.container(**TARJETA):
        m1, m2, m3, m4 = st.columns([1.3, 1.3, 1.1, 0.9])
        with m1:
            sel_dep = st.multiselect("Departamento", deptos, default=deptos)
            umbral = st.select_slider("Frecuencia mínima de conexión", options=[0.10, 0.20, 0.40, 0.60, 0.80], value=0.20,
                                      format_func=lambda v: f"{int(v * 100)} %")
        with m2:
            clases_sel = st.multiselect("Clasificación de campamentos", list(COLOR_CLASE_SITIO), default=["Núcleo", "Sensible", "Ocasional"])
            foco = st.selectbox("Conexiones de un campamento", ["Todos"] + sorted(sitios.municipio))
        with m3:
            var_color = st.selectbox("Color de los municipios", ["Probabilidad de atención", "Cobertura promedio", "Clase de robustez",
                                                                 "Demanda promedio"])
            ver_etiquetas = st.checkbox("Etiquetas", value=True)
        with m4:
            ver_cand = st.checkbox("Mostrar candidatos", value=True)
            ver_dem = st.checkbox("Mostrar demanda", value=True)
            ver_arc = st.checkbox("Mostrar conexiones", value=True)

    capas = []
    s_map = sitios[sitios.departamento.isin(sel_dep) & sitios.clase.isin(clases_sel)].copy()
    mu = muni[muni.departamento.isin(sel_dep)].copy()
    if ver_arc and len(arcos):
        a = arcos[arcos.frecuencia >= umbral - 1e-9].copy()
        a = a[a.id_demanda.map(datos["dem"].departamento).isin(sel_dep) | a.id_sitio.map(datos["cand"].departamento).isin(sel_dep)]
        a = a[a.id_sitio.isin(s_map.index)]
        if foco != "Todos":
            a = a[a.id_sitio.map(nom) == foco]
        if len(a):
            a["o_lon"] = a.id_demanda.map(datos["dem"].lon)
            a["o_lat"] = a.id_demanda.map(datos["dem"].lat)
            a["d_lon"] = a.id_sitio.map(datos["cand"].lon)
            a["d_lat"] = a.id_sitio.map(datos["cand"].lat)
            a["ancho"] = 1.2 + 6 * a.frecuencia
            a["color"] = [[78, 99, 120, int(55 + 135 * fq)] for fq in a.frecuencia]
            a["tooltip"] = [f"<b>{nom[i]} → {nom[j]}</b><br/>Frecuencia de uso: {100 * fq:.0f} %<br/>"
                            f"Personas cuando se usa (media): {fl:,.0f}<br/>Distancia por carretera: {km:,.1f} km".replace(",", ".")
                            for i, j, fq, fl, km in zip(a.id_demanda, a.id_sitio, a.frecuencia, a.flujo_medio_si_se_usa, a.km)]
            capas.append(pdk.Layer("LineLayer", a.sort_values("frecuencia"), get_source_position=["o_lon", "o_lat"],
                                   get_target_position=["d_lon", "d_lat"], get_color="color", get_width="ancho",
                                   width_units="'pixels'", width_scale=1, width_min_pixels=1, width_max_pixels=8, pickable=True))
    if ver_dem and len(mu):
        vmax = float(mu.demanda_media.max() or 1)
        if var_color == "Probabilidad de atención":
            mu["color"] = [_escala_divergente(v) + [225] for v in mu.prob_atencion]
        elif var_color == "Cobertura promedio":
            mu["color"] = [_escala_divergente(v) + [225] for v in mu.cobertura_media]
        elif var_color == "Clase de robustez":
            mu["color"] = [COLOR_CLASE_MUN.get(c, [150, 150, 150]) + [225] for c in mu.clase]
        else:
            mu["color"] = [_escala_secuencial(v, vmax) + [225] for v in mu.demanda_media]
        mu["radio"] = 2500 + 9000 * np.sqrt(mu.demanda_media / vmax)
        mu["tooltip"] = [f"<b>{r.municipio}</b> ({r.departamento})<br/>Demanda promedio: {r.demanda_media:,.0f}<br/>"
                         f"Atendidos promedio: {r.atendidos_media:,.0f}<br/>Cobertura promedio: {100 * r.cobertura_media:.1f} %<br/>"
                         f"Probabilidad de recibir atención: {100 * r.prob_atencion:.0f} %<br/>"
                         f"Probabilidad de quedar sin atención: {100 * r.prob_sin_atencion:.0f} %<br/>Clase: {r.clase}".replace(",", ".")
                         for r in mu.itertuples()]
        capas.append(pdk.Layer("ScatterplotLayer", mu, get_position=["lon", "lat"], get_fill_color="color", get_radius="radio",
                               stroked=True, get_line_color=[255, 255, 255, 230], line_width_min_pixels=1.5, pickable=True))
    if ver_cand and len(s_map):
        rad = {3000: 7000, 1000: 5200, 500: 4000}
        s_map["radio"] = [rad.get(int(k), 4000) for k in s_map.capacidad_K]
        s_map["color"] = [COLOR_CLASE_SITIO[c] + [240] for c in s_map.clase]
        s_map["tooltip"] = [f"<b>Campamento: {r.municipio}</b> ({r.departamento})<br/>Categoría: {r.categoria} · capacidad {int(r.capacidad_K):,}<br/>"
                            f"Frecuencia de apertura: {100 * r.frecuencia_apertura:.0f} %<br/>Ocupación media: {r.ocupacion_media:,.0f} personas<br/>"
                            f"Clasificación: <b>{r.clase}</b>".replace(",", ".") for r in s_map.itertuples()]
        # cuadrado = campamento (polígono pequeño alrededor de la cabecera), para distinguirlo de los municipios (círculos)
        lado = {3000: 0.055, 1000: 0.045, 500: 0.037}
        s_map["poligono"] = [[[lo - l, la - l], [lo + l, la - l], [lo + l, la + l], [lo - l, la + l]]
                             for lo, la, l in zip(s_map.lon, s_map.lat, [lado.get(int(k), 0.037) for k in s_map.capacidad_K])]
        capas.append(pdk.Layer("PolygonLayer", s_map, get_polygon="poligono", get_fill_color="color",
                               get_line_color=[255, 255, 255, 255], line_width_min_pixels=2, stroked=True, pickable=True))
    if ver_etiquetas:
        etq = []
        if ver_cand and len(s_map):
            etq += [dict(lon=r.lon, lat=r.lat + 0.075, texto=r.municipio, tam=13) for r in s_map[s_map.clase.isin(["Núcleo", "Sensible"])].itertuples()]
        if ver_dem and len(mu):
            # los municipios de mayor demanda, saltando los que quedarían encima de una etiqueta ya puesta (< 0,15°)
            puestos = [(e["lon"], e["lat"]) for e in etq]
            for r in mu.nlargest(8, "demanda_media").itertuples():
                if len([1 for (lo_, la_) in puestos]) >= len(etq) + 5:
                    break
                if all(abs(r.lon - lo_) > 0.15 or abs(r.lat - 0.07 - la_) > 0.1 for lo_, la_ in puestos):
                    etq.append(dict(lon=r.lon, lat=r.lat - 0.07, texto=r.municipio, tam=11))
                    puestos.append((r.lon, r.lat - 0.07))
        if etq:
            capas.append(pdk.Layer("TextLayer", pd.DataFrame(etq), get_position=["lon", "lat"], get_text="texto", get_size="tam",
                                   get_color=[46, 51, 56, 255], get_alignment_baseline="'center'", font_weight=500,
                                   font_family="'Inter, Helvetica, Arial, sans-serif'",
                                   character_set="'" + "".join(sorted(set(c for c in "".join(chr(k) for k in range(32, 127)) + "".join(e["texto"] for e in etq)
                                                                if c.isalnum() or c in " .-"))) + "'",
                                   background=True, get_background_color=[255, 255, 255, 215], background_padding=[4, 2]))

    lats = pd.concat([datos["dem"].lat, datos["cand"].lat])
    lons = pd.concat([datos["dem"].lon, datos["cand"].lon])
    # zoom que encuadra todos los nodos (aprox. Web Mercator: 360° = 512 px a zoom 0 en un mapa de ~900 px)
    dlon = max(float(lons.max() - lons.min()), 0.3)
    dlat = max(float(lats.max() - lats.min()), 0.3)
    # encuadre: ~760 px de ancho y 640 px de alto, con 20 % de margen
    zoom0 = float(np.clip(min(np.log2(760 * 360 / (512 * dlon * 1.2)), np.log2(640 * 360 / (512 * dlat * 1.2))), 5, 10))
    vista = pdk.ViewState(latitude=float((lats.max() + lats.min()) / 2), longitude=float((lons.max() + lons.min()) / 2), zoom=zoom0)
    deck = pdk.Deck(layers=capas, initial_view_state=vista,
                    map_provider="carto", map_style="light",
                    tooltip={"html": "{tooltip}", "style": {"backgroundColor": "white", "color": PAL["tinta"], "fontSize": "12px",
                                                            "border": f"1px solid {PAL['borde']}", "borderRadius": "6px",
                                                            "boxShadow": "0 2px 6px rgba(46,51,56,0.08)", "fontFamily": FUENTE}})
    mapa_col, leyenda_col = st.columns([4, 1])
    with mapa_col:
        with st.container(**TARJETA):
            st.pydeck_chart(deck, height=640)
    with leyenda_col:
        def muestra(rgb, forma="circulo"):
            radio = "50%" if forma == "circulo" else "2px"
            return f"<span class='sw' style='background:{_hex(rgb)};border-radius:{radio}'></span>"
        html = ("<div class='mc-leyenda'><div class='g'>Campamentos</div><div class='n'>Cuadrados · tamaño = capacidad</div>"
                + "<br/>".join(f"{muestra(c, 'cuadrado')}{k}" for k, c in COLOR_CLASE_SITIO.items()))
        html += "<div class='sep'></div><div class='g'>Municipios</div>"
        if var_color == "Clase de robustez":
            html += "<div class='n'>Círculos · tamaño = demanda</div>" + "<br/>".join(f"{muestra(c)}{k}" for k, c in COLOR_CLASE_MUN.items())
        elif var_color == "Demanda promedio":
            html += "<div class='n'>Tamaño y color = demanda</div>" + f"{muestra([226, 229, 232])}baja<br/>{muestra([62, 82, 102])}alta"
        else:
            html += (f"<div class='n'>{var_color}</div>{muestra(_escala_divergente(0))}0 %<br/>"
                     f"{muestra(_escala_divergente(.5))}50 %<br/>{muestra(_escala_divergente(1))}100 %")
        html += ("<div class='sep'></div><div class='g'>Conexiones</div><div class='n'>Grosor y opacidad = frecuencia de uso<br/>"
                 f"Se muestran las de frecuencia ≥ {int(umbral * 100)} %</div></div>")
        with st.container(**TARJETA):
            st.markdown(html, unsafe_allow_html=True)
            st.caption("Robustamente atendido: atención en ≥ 80 % de las simulaciones. Vulnerable: sin atención en ≥ 80 %.")

    t1, t2 = st.columns(2)
    with t1:
        with st.container(**TARJETA):
            subtitulo("Campamentos")
            st.dataframe(sitios[["municipio", "departamento", "categoria", "capacidad_K", "frecuencia_apertura", "ocupacion_media", "clase"]]
                         .sort_values("frecuencia_apertura", ascending=False).round(3), hide_index=True, **ANCHO)
    with t2:
        with st.container(**TARJETA):
            subtitulo("Municipios")
            st.dataframe(muni[["municipio", "departamento", "demanda_media", "cobertura_media", "prob_atencion", "prob_sin_atencion", "clase"]]
                         .sort_values("prob_atencion").round(3), hide_index=True, **ANCHO)

    # ---------------- Datos y descargas (no se escribe nada en el proyecto) ----------------
    st.write("")
    with st.expander("Resultados por simulación y descargas"):
        st.dataframe(tabla.drop(columns=[c for c in tabla.columns if c.startswith("y_")]), hide_index=True, **ANCHO)
        st.download_button("Descargar simulaciones (CSV)", tabla.to_csv(index=False).encode("utf-8"), "montecarlo_simulaciones.csv", "text/csv")
        st.download_button("Descargar frecuencia de arcos (CSV)", arcos.assign(origen=arcos.id_demanda.map(nom), sitio=arcos.id_sitio.map(nom))
                           .to_csv(index=False).encode("utf-8"), "montecarlo_arcos.csv", "text/csv")
        st.caption("Las descargas se generan en memoria; la app no escribe archivos en la carpeta del proyecto.")


if __name__ == "__main__":
    main()
