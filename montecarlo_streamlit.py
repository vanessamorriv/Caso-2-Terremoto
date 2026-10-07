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
# Estética: paleta pastel clara. Rojo (rosado apagado) solo para vulnerabilidad/alertas; verde suave para lo positivo.
# ------------------------------------------------------------------------------------------------------------------
PAL = dict(
    fondo="#F5F6F3", lateral="#F1F0EB", tarjeta="#FFFFFF", borde="#E5E7E2", rejilla="#EEF0EC",
    tinta="#26323A", tinta2="#5E6A70", tenue="#93A0A4",
    acento="#4F8F81",         # verde azulado (teal) suave: botón, selección, series principales
    acento_osc="#3F7A6D",
    acento_suave="#9CC9BE",   # teal pastel: barras del histograma
    acento_fondo="#E4F1EC",
    azul="#6F8FBF", azul_fondo="#E6ECF6",
    rosa="#CF6F66", rosa_fondo="#F8E7E4",
    arena="#C29A55", arena_fondo="#F6EEDF",
    pizarra="#5D7183", pizarra_fondo="#E7ECF0",
    verde="#5E9E77", verde_fondo="#E3F1E8",
)
COLOR_CLASE_SITIO = {"Núcleo": [79, 143, 129], "Sensible": [214, 172, 98], "Ocasional": [146, 168, 204], "Nunca abierto": [206, 202, 194]}
COLOR_CLASE_MUN = {"Robustamente atendido": [104, 168, 128], "Intermedio": [228, 193, 122], "Vulnerable": [211, 112, 102]}
FUENTE = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"

# Íconos de línea (estilo "lucide", trazos de 24 px) para tarjetas, encabezados y menú lateral.
_ICONOS = {
    "personas": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "barras": '<line x1="6" y1="20" x2="6" y2="13"/><line x1="12" y1="20" x2="12" y2="8"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="3" y1="20" x2="21" y2="20"/>',
    "baja": '<polyline points="22 17 13.5 8.5 8.5 13.5 2 7"/><polyline points="16 17 22 17 22 11"/>',
    "sube": '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
    "carpa": '<path d="M3.5 21 12 4l8.5 17"/><path d="M12 4v17"/><path d="M8.5 21 12 14l3.5 7"/><line x1="2" y1="21" x2="22" y2="21"/>',
    "trofeo": '<path d="M8 21h8"/><path d="M12 17v4"/><path d="M7 4h10v5a5 5 0 0 1-10 0V4z"/><path d="M17 5h3v2a3 3 0 0 1-3 3"/><path d="M7 5H4v2a3 3 0 0 0 3 3"/>',
    "mapa": '<polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/>',
    "alerta": '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "dispersion": '<path d="M3 3v18h18"/><circle cx="8" cy="14" r="1.6"/><circle cx="12" cy="9" r="1.6"/><circle cx="17" cy="12" r="1.6"/><circle cx="19" cy="6" r="1.6"/>',
    "casa": '<path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    "capas": '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
    "info": '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
    "ajustes": '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
    "red": '<circle cx="5" cy="6" r="2.2"/><circle cx="19" cy="6" r="2.2"/><circle cx="12" cy="18" r="2.2"/><line x1="6.8" y1="7.3" x2="10.6" y2="16.2"/><line x1="17.2" y1="7.3" x2="13.4" y2="16.2"/><line x1="7.2" y1="6" x2="16.8" y2="6"/>',
    "tabla": '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="9" x2="9" y2="21"/>',
    "check": '<circle cx="12" cy="12" r="10"/><polyline points="8 12.5 11 15.5 16.5 9.5"/>',
}


def icono(nombre, color, tam=20, grosor=1.9):
    return (f"<svg width='{tam}' height='{tam}' viewBox='0 0 24 24' fill='none' stroke='{color}' stroke-width='{grosor}' "
            f"stroke-linecap='round' stroke-linejoin='round'>{_ICONOS[nombre]}</svg>")


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select {{ font-family: {FUENTE}; }}
.stApp {{ background: {PAL['fondo']}; color: {PAL['tinta']}; }}
[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1480px; }}
h1, h2, h3, h4 {{ color: {PAL['tinta']}; font-weight: 600; }}
/* ---------- barra lateral ---------- */
[data-testid="stSidebar"] {{ background: {PAL['lateral']}; border-right: 1px solid {PAL['borde']}; }}
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{ font-size: 0.86rem; color: {PAL['tinta']}; margin: 1.1rem 0 0.15rem 0;
    font-weight: 600; letter-spacing: 0; }}
.mc-marca {{ display: flex; align-items: center; gap: 0.7rem; margin: 0.2rem 0 1.1rem 0; }}
.mc-marca .t {{ font-size: 1.12rem; font-weight: 700; color: {PAL['tinta']}; line-height: 1.15; }}
.mc-marca .s {{ font-size: 0.76rem; color: {PAL['tinta2']}; line-height: 1.25; }}
.mc-nav a {{ display: flex; align-items: center; gap: 0.65rem; padding: 0.48rem 0.7rem; border-radius: 9px; color: {PAL['tinta2']} !important;
    text-decoration: none !important; font-size: 0.88rem; margin-bottom: 2px; }}
.mc-nav a:hover {{ background: #E8E7E1; color: {PAL['tinta']} !important; }}
.mc-nav a.activo {{ background: #E6E5DF; color: {PAL['tinta']} !important; font-weight: 600; border-left: 3px solid {PAL['acento']}; }}
.mc-div {{ border-top: 1px solid {PAL['borde']}; margin: 0.9rem 0 0.2rem 0; }}
[data-testid="stSidebar"] [data-testid="stExpander"] details {{ background: {PAL['tarjeta']}; }}
/* ---------- tarjetas (contenedores con borde) ---------- */
div[data-testid="stVerticalBlockBorderWrapper"] {{ border: 1px solid {PAL['borde']} !important; border-radius: 14px !important;
    background: {PAL['tarjeta']}; box-shadow: 0 1px 3px rgba(38, 50, 58, 0.04); }}
/* ---------- botones y controles ---------- */
.stButton > button, .stDownloadButton > button, [data-testid="stPopover"] button {{ border-radius: 9px; border: 1px solid {PAL['borde']};
    background: {PAL['tarjeta']}; color: {PAL['tinta']}; font-weight: 500; box-shadow: none; }}
.stButton > button[kind="primary"] {{ background: {PAL['acento']}; border-color: {PAL['acento']}; color: #FFFFFF; font-weight: 600; padding: 0.6rem 0; }}
.stButton > button[kind="primary"]:hover {{ background: {PAL['acento_osc']}; border-color: {PAL['acento_osc']}; }}
[data-baseweb="tag"] {{ background: {PAL['acento_fondo']} !important; border-radius: 6px !important; }}
[data-baseweb="tag"] span, [data-baseweb="tag"] svg {{ color: {PAL['tinta']} !important; fill: {PAL['tinta2']} !important; }}
[data-testid="stDataFrame"] {{ border: 1px solid {PAL['borde']}; border-radius: 10px; }}
[data-testid="stExpander"] details {{ border: 1px solid {PAL['borde']}; border-radius: 12px; background: {PAL['tarjeta']}; }}
[data-testid="stAlert"] {{ border-radius: 10px; }}
[data-testid="stCaptionContainer"] {{ color: {PAL['tinta2']}; }}
/* ---------- encabezado ---------- */
.mc-cab {{ position: relative; display: flex; align-items: center; gap: 1.2rem; background: {PAL['tarjeta']}; border: 1px solid {PAL['borde']};
    border-radius: 16px; padding: 1.15rem 1.4rem; overflow: hidden; box-shadow: 0 1px 3px rgba(38, 50, 58, 0.04); margin-bottom: 1rem; }}
.mc-cab .logo {{ flex: 0 0 auto; width: 74px; height: 74px; border-radius: 50%; background: {PAL['arena_fondo']}; display: flex;
    align-items: center; justify-content: center; position: relative; z-index: 1; }}
.mc-cab .txt {{ position: relative; z-index: 1; max-width: 58%; }}
.mc-cab h1 {{ font-size: 1.85rem; font-weight: 700; margin: 0; padding: 0; color: {PAL['tinta']}; letter-spacing: -0.015em; }}
.mc-cab .s1 {{ font-size: 1.02rem; color: {PAL['tinta2']}; margin-top: 0.15rem; }}
.mc-cab .s2 {{ font-size: 0.85rem; color: {PAL['tenue']}; margin-top: 0.2rem; }}
.mc-cab .paisaje {{ position: absolute; right: 0; top: 0; height: 100%; width: 40%; }}
.mc-cab .lema {{ position: absolute; right: 1.6rem; top: 0.9rem; z-index: 1; font-family: Georgia, 'Times New Roman', serif; font-style: italic;
    color: #48655E; font-size: 1.18rem; text-align: right; line-height: 1.1; }}
.mc-cab .lema .bandera {{ display: block; height: 3px; width: 64px; margin: 0.35rem 0 0 auto;
    background: linear-gradient(90deg, #E9C766 0 50%, #7C93C3 50% 75%, #D98A80 75% 100%); border-radius: 2px; }}
.mc-pildora {{ display: inline-block; font-size: 0.72rem; color: {PAL['tinta2']}; background: {PAL['fondo']}; border: 1px solid {PAL['borde']};
    border-radius: 999px; padding: 0.1rem 0.6rem; margin: 0.45rem 0.35rem 0 0; }}
/* ---------- tarjetas KPI ---------- */
.mc-kpi {{ background: {PAL['tarjeta']}; border: 1px solid {PAL['borde']}; border-radius: 14px; padding: 0.85rem 0.95rem 0.8rem 0.95rem;
    box-shadow: 0 1px 3px rgba(38, 50, 58, 0.04); min-height: 138px; }}
.mc-kpi .top {{ display: flex; gap: 0.6rem; align-items: center; }}
.mc-kpi .ic {{ flex: 0 0 auto; width: 38px; height: 38px; border-radius: 11px; display: flex; align-items: center; justify-content: center; }}
.mc-kpi .lb {{ font-size: 0.8rem; color: {PAL['tinta2']}; line-height: 1.2; }}
.mc-kpi .vl {{ font-size: 1.62rem; font-weight: 700; color: {PAL['tinta']}; line-height: 1.2; margin-top: 0.55rem; letter-spacing: -0.01em;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.mc-kpi .nt {{ font-size: 0.75rem; color: {PAL['tenue']}; line-height: 1.3; margin-top: 0.2rem; }}
.mc-kpi.mini {{ min-height: 0; padding: 0.65rem 0.9rem; display: flex; align-items: center; gap: 0.75rem; }}
.mc-kpi.mini .ic {{ width: 34px; height: 34px; border-radius: 10px; }}
.mc-kpi.mini .vl {{ font-size: 1.12rem; margin-top: 0.1rem; }}
/* ---------- encabezados de tarjeta ---------- */
.mc-th {{ display: flex; gap: 0.6rem; align-items: flex-start; margin: 0.1rem 0 0.35rem 0; }}
.mc-th .t {{ font-size: 1rem; font-weight: 600; color: {PAL['tinta']}; line-height: 1.3; }}
.mc-th .s {{ font-size: 0.8rem; color: {PAL['tinta2']}; line-height: 1.3; }}
.mc-seccion {{ margin: 1.6rem 0 0.6rem 0; font-size: 1.08rem; font-weight: 600; color: {PAL['tinta']}; }}
.mc-seccion .s {{ display: block; font-size: 0.82rem; font-weight: 400; color: {PAL['tinta2']}; margin-top: 0.1rem; }}
.mc-stat {{ background: {PAL['fondo']}; border-radius: 10px; padding: 0.7rem 0.75rem; margin-top: 2.4rem; white-space: nowrap; }}
.mc-stat .lb {{ font-size: 0.76rem; color: {PAL['tinta2']}; }}
.mc-stat .vl {{ font-size: 1.2rem; font-weight: 700; color: {PAL['tinta']}; margin-bottom: 0.45rem; }}
.mc-stat .vl2 {{ font-size: 0.8rem; font-weight: 600; color: {PAL['tinta']}; margin-bottom: 0.45rem; }}
/* ---------- leyenda del mapa y tabla de vulnerables ---------- */
.mc-leyenda {{ font-size: 0.8rem; color: {PAL['tinta']}; line-height: 1.5; }}
.mc-leyenda .g {{ font-size: 0.86rem; font-weight: 600; margin: 0.15rem 0 0.3rem 0; }}
.mc-leyenda .n {{ color: {PAL['tinta2']}; font-size: 0.74rem; }}
.mc-leyenda .fila {{ display: flex; align-items: flex-start; gap: 0.5rem; margin-bottom: 0.25rem; }}
.mc-leyenda .sw {{ flex: 0 0 auto; width: 11px; height: 11px; margin-top: 0.22rem; }}
.mc-leyenda .sep {{ border-top: 1px solid {PAL['borde']}; margin: 0.55rem 0; }}
table.mc-tab {{ width: 100%; border-collapse: collapse; font-size: 0.8rem; }}
table.mc-tab th {{ text-align: left; font-weight: 600; color: {PAL['tinta2']}; font-size: 0.74rem; padding: 0.45rem 0.4rem;
    background: {PAL['fondo']}; border-bottom: 1px solid {PAL['borde']}; }}
table.mc-tab td {{ white-space: nowrap; padding: 0.4rem 0.3rem; border-bottom: 1px solid {PAL['rejilla']}; color: {PAL['tinta']}; }}
table.mc-tab td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
table.mc-tab th.num {{ text-align: right; }}
.mc-nivel {{ display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.76rem; font-weight: 500; }}
.mc-nivel i {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; }}
</style>
"""

_PAISAJE = (
    "<svg class='paisaje' viewBox='0 0 600 140' preserveAspectRatio='xMaxYMid slice' xmlns='http://www.w3.org/2000/svg'>"
    "<defs><linearGradient id='mcCielo' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='#DCE8EE'/><stop offset='1' stop-color='#F3F1EA'/></linearGradient>"
    "<linearGradient id='mcFade' x1='0' y1='0' x2='1' y2='0'><stop offset='0' stop-color='#FFFFFF' stop-opacity='1'/>"
    "<stop offset='0.35' stop-color='#FFFFFF' stop-opacity='0'/></linearGradient></defs>"
    "<rect width='600' height='140' fill='url(#mcCielo)'/>"
    "<path d='M0 92 L70 58 L118 78 L190 30 L240 62 L300 22 L350 55 L420 18 L480 52 L540 34 L600 50 L600 140 L0 140Z' fill='#C9D7DE'/>"
    "<path d='M300 22 L316 34 L306 33 L298 40 L290 33 Z M420 18 L436 31 L426 30 L418 37 L410 30 Z' fill='#F4F6F7'/>"
    "<path d='M0 108 L60 84 L130 98 L210 70 L280 92 L350 72 L430 90 L510 68 L600 84 L600 140 L0 140Z' fill='#A9C4BB'/>"
    "<path d='M0 126 L90 104 L170 118 L260 98 L350 116 L440 100 L530 114 L600 104 L600 140 L0 140Z' fill='#86AE9F'/>"
    "<rect width='600' height='140' fill='url(#mcFade)'/></svg>")


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def _escala_divergente(v: float) -> list[int]:
    """0 → rosado (vulnerable), 0,5 → arena claro, 1 → verde suave (robusto)."""
    v = 0.0 if v is None or np.isnan(v) else min(max(v, 0.0), 1.0)
    a, m, b = np.array([211, 112, 102]), np.array([236, 214, 160]), np.array([94, 158, 119])
    rgb = a + (m - a) * (v / 0.5) if v < 0.5 else m + (b - m) * ((v - 0.5) / 0.5)
    return [int(x) for x in rgb]


def _escala_secuencial(v: float, vmax: float) -> list[int]:
    t = 0.0 if vmax <= 0 else min(max(v / vmax, 0.0), 1.0)
    a, b = np.array([222, 236, 232]), np.array([63, 122, 109])
    return [int(x) for x in a + (b - a) * t]


def _fmt(v, tipo):
    if tipo == "pct":
        return f"{100 * v:.1f} %".replace(".", ",")
    if tipo == "cop":
        return f"${v:,.0f}".replace(",", ".")
    return f"{v:.2f}".replace(".", ",")


def _mil(v):
    return f"{v:,.0f}".replace(",", ".")


def _estilo(ch, alto=300):
    """Misma línea visual para todos los gráficos: fondo blanco, rejilla suave, texto gris, sin marco."""
    return (ch.properties(height=alto, background=PAL["tarjeta"], padding={"left": 4, "right": 10, "top": 8, "bottom": 4})
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
        except Exception:   # versiones sin la opción: el CSS mantiene el aspecto claro
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

    def html(txt):
        st.markdown(txt, unsafe_allow_html=True)

    def ancla(nombre):
        html(f"<div id='{nombre}' style='position:relative;top:-70px'></div>")

    def cab_tarjeta(ic, color, titulo, sub=""):
        html(f"<div class='mc-th'>{icono(ic, color, 22)}<div><div class='t'>{titulo}</div>"
             + (f"<div class='s'>{sub}</div>" if sub else "") + "</div></div>")

    def seccion(titulo, sub=""):
        html(f"<div class='mc-seccion'>{titulo}" + (f"<span class='s'>{sub}</span>" if sub else "") + "</div>")

    def kpi(col, ic, color, fondo, etiqueta, valor, nota="", mini=False):
        badge = f"<div class='ic' style='background:{fondo}'>{icono(ic, color, 18 if mini else 20)}</div>"
        if mini:
            col.markdown(f"<div class='mc-kpi mini'>{badge}<div><div class='lb'>{etiqueta}</div><div class='vl'>{valor}</div></div></div>",
                         unsafe_allow_html=True)
        else:
            col.markdown(f"<div class='mc-kpi'><div class='top'>{badge}<div class='lb'>{etiqueta}</div></div>"
                         f"<div class='vl' title='{valor}'>{valor}</div>" + (f"<div class='nt'>{nota}</div>" if nota else "") + "</div>",
                         unsafe_allow_html=True)

    def grafico(ch, alto=300):
        st.altair_chart(_estilo(ch, alto), theme=None, **ANCHO)

    # ---------------- Barra lateral: marca, navegación, datos y configuración ----------------
    with st.sidebar:
        html(f"<div class='mc-marca'><div style='width:46px;height:46px;border-radius:12px;background:{PAL['acento_fondo']};display:flex;"
             f"align-items:center;justify-content:center'>{icono('carpa', PAL['acento'], 26)}</div>"
             "<div><div class='t'>Red de campamentos</div><div class='s'>Caso 2 · Terremoto en Colombia<br/>Robustez basada en datos</div></div></div>"
             f"<div class='mc-nav'><a class='activo' href='#robustez'>{icono('casa', PAL['tinta'], 17)}Análisis de robustez</a>"
             f"<a href='#mapa'>{icono('mapa', PAL['tinta2'], 17)}Mapa y resultados</a>"
             f"<a href='#sensibilidad'>{icono('dispersion', PAL['tinta2'], 17)}Sensibilidad</a>"
             f"<a href='#detalle'>{icono('info', PAL['tinta2'], 17)}Supuestos y detalle</a></div><div class='mc-div'></div>")
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

        st.header("Parámetros de simulación")
        rapido = st.toggle("Modo rápido", value=True, help="Rápido: 25 simulaciones para explorar. Completo: ≥ 300 para reportar.")
        n_sim = st.number_input("Número de simulaciones", min_value=20 if rapido else 300, max_value=60 if rapido else 2000,
                                value=25 if rapido else 300, step=5 if rapido else 50)
        semilla = st.number_input("Semilla aleatoria", min_value=0, max_value=10**9, value=2026, step=1)
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

        st.header("Rangos de parámetros")
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
        ejecutar = st.button("▶  Ejecutar simulación", type="primary", **ANCHO)

    # ---------------- Encabezado ----------------
    ancla("robustez")
    html(f"<div class='mc-cab'>{_PAISAJE}<div class='lema'>Colombia<br/>más resiliente<span class='bandera'></span></div>"
         f"<div class='logo'>{icono('carpa', '#9B7B49', 38, 1.7)}</div>"
         "<div class='txt'><h1>Monte Carlo · Robustez de la red</h1>"
         "<div class='s1'>Campamentos temporales tras el terremoto del 10 de agosto de 2026</div>"
         "<div class='s2'>Evalúa la cobertura, la apertura de campamentos y la sensibilidad ante la incertidumbre en la demanda, "
         "los costos y el tamaño de hogar, con el MILP lexicográfico del notebook 02.</div>"
         "<span class='mc-pildora'>Análisis de robustez, no predicción</span><span class='mc-pildora'>No modifica los resultados oficiales</span>"
         "</div></div>")

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

    def tabla_rangos():
        st.dataframe(pd.DataFrame([dict(Parámetro=PARAMS[k][0], Mínimo=_fmt(lo, PARAMS[k][6]),
                                         Moda=_fmt(mo, PARAMS[k][6]) if dist_ == "triangular" else "—",
                                         Máximo=_fmt(hi, PARAMS[k][6]), Distribución=dist_.capitalize(),
                                         **{"Modelo base": _fmt(PARAMS[k][5], PARAMS[k][6])})
                                    for k, (lo, mo, hi, dist_) in rangos.items()]), hide_index=True, **ANCHO)
        st.caption("Se muestrean de forma independiente. La demanda es d_i = round(NH_i · h_i · factor de hogar · f); los costos fijos "
                   "F_j = K_j · c_f · T · φ_j; el presupuesto sigue la opción elegida; distancias, capacidades y la tarifa de transporte "
                   "son las del proyecto (no son inciertas aquí).")

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
        with st.container(**TARJETA):
            cab_tarjeta("ajustes", PAL["acento"], "Supuestos inciertos", "Rangos y distribuciones que se muestrean en cada simulación")
            tabla_rangos()
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
    cob = validas.cobertura
    cob_ref = ref.get("atendidos", 0) / max(ref.get("demanda", 1), 1)
    top = sitios.sort_values(["frecuencia_apertura", "capacidad_K"], ascending=False).iloc[0]
    red_base = ref.get("red", "")

    # ---------------- Indicadores (KPI) ----------------
    html(f"<div style='font-size:0.8rem;color:{PAL['tinta2']};margin:0 0 0.5rem 0.1rem'>"
         f"<b style='color:{PAL['tinta']}'>{mc['nivel']}</b> · presupuesto "
         f"{'según la regla del enunciado' if mc['regla_B'] == 'enunciado' else 'fijo en COP'} · {n_val} de {len(tabla)} simulaciones válidas "
         f"(optimalidad certificada en las dos etapas) · semilla {mc['semilla']} · {mc['segundos']:.0f} s</div>")
    dif = 100 * (cob.median() - cob_ref)
    flecha = "▲" if dif >= 0 else "▼"
    col_dif = PAL["verde"] if dif >= 0 else PAL["rosa"]
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    kpi(k1, "personas", PAL["verde"], PAL["verde_fondo"], "Cobertura mediana", _fmt(cob.median(), "pct"),
        f"<span style='color:{col_dif};font-weight:600'>{flecha} {abs(dif):.1f} pp</span> vs. referencia".replace(".", ","))
    kpi(k2, "baja", PAL["rosa"], PAL["rosa_fondo"], "P10 cobertura", _fmt(cob.quantile(0.10), "pct"), "Escenario pesimista (10 % de los casos)")
    kpi(k3, "barras", PAL["azul"], PAL["azul_fondo"], "P90 cobertura", _fmt(cob.quantile(0.90), "pct"), "Escenario optimista (90 % de los casos)")
    kpi(k4, "personas", PAL["pizarra"], PAL["pizarra_fondo"], "Personas atendidas (prom.)", _mil(validas.atendidos.mean()),
        f"± {_mil(validas.atendidos.std())} entre simulaciones")
    kpi(k5, "carpa", PAL["arena"], PAL["arena_fondo"], "Campamentos abiertos (prom.)", f"{validas.n_abiertos.mean():.1f}".replace(".", ","),
        f"± {validas.n_abiertos.std():.1f} · de {len(datos['J'])} candidatos".replace(".", ","))
    kpi(k6, "trofeo", "#B9922F", "#F7EFD9", "Campamento más robusto", top.municipio,
        f"Se abre en el {_fmt(top.frecuencia_apertura, 'pct')} de las simulaciones")
    st.write("")
    m1, m2, m3, m4 = st.columns(4)
    kpi(m1, "personas", PAL["verde"], PAL["verde_fondo"], "Cobertura promedio", _fmt(cob.mean(), "pct"), mini=True)
    kpi(m2, "personas", PAL["pizarra"], PAL["pizarra_fondo"], "Personas atendidas P10–P90",
        f"{_mil(validas.atendidos.quantile(.1))} – {_mil(validas.atendidos.quantile(.9))}", mini=True)
    kpi(m3, "capas", PAL["azul"], PAL["azul_fondo"], "Demanda (prom.)", _mil(validas.demanda.mean()), mini=True)
    kpi(m4, "red", PAL["acento"], PAL["acento_fondo"], "Simulaciones con la misma red que la referencia",
        _fmt((validas.red == red_base).mean(), "pct"), mini=True)
    if (tabla.valida == False).any():   # noqa: E712
        st.warning(f"{(~tabla.valida).sum()} simulaciones descartadas (sin optimalidad certificada); ver tabla de resultados.")
    st.write("")

    # ---------------- Fila de gráficos: distribución · apertura · sensibilidad ----------------
    esc_camp = alt.Scale(range=["#A9C9C0", "#79A99C", "#4F8F81", "#3A6F64", "#2A5249", "#1C3832"])
    g1, g2, g3 = st.columns([1.12, 1, 1])
    with g1:
        with st.container(**TARJETA):
            cab_tarjeta("barras", PAL["acento"], "Distribución de la cobertura", f"Resultados de {n_val} simulaciones Monte Carlo")
            a1, a2 = st.columns([2.45, 1])
            with a1:
                h = alt.Chart(validas.assign(cob=100 * validas.cobertura)).mark_bar(color=PAL["acento_suave"], cornerRadiusTopLeft=2,
                                                                                    cornerRadiusTopRight=2, binSpacing=1).encode(
                    x=alt.X("cob:Q", bin=alt.Bin(maxbins=25), title="Cobertura de la demanda (%)"), y=alt.Y("count()", title="Frecuencia"))
                lineas = pd.DataFrame([dict(v=100 * cob.quantile(.1), etq="P10"), dict(v=100 * cob.median(), etq="Mediana"),
                                       dict(v=100 * cob.quantile(.9), etq="P90"), dict(v=100 * cob_ref, etq="Referencia")])
                r_ = alt.Chart(lineas).mark_rule(strokeWidth=1.8).encode(x="v:Q", color=alt.Color("etq:N", title=None, legend=alt.Legend(columns=4, symbolSize=40, labelFontSize=10, columnPadding=6),
                     scale=alt.Scale(domain=["P10", "Mediana", "P90", "Referencia"], range=[PAL["rosa"], PAL["tinta"], PAL["azul"], PAL["arena"]])),
                     strokeDash=alt.condition(alt.datum.etq == "Mediana", alt.value([1, 0]), alt.value([4, 3])))
                grafico(h + r_, alto=250)
            with a2:
                html(f"<div class='mc-stat'><div class='lb'>Mediana</div><div class='vl'>{_fmt(cob.median(), 'pct')}</div>"
                     f"<div class='lb'>P10</div><div class='vl2'>{_fmt(cob.quantile(.1), 'pct')}</div><div class='lb'>P90</div><div class='vl2'>{_fmt(cob.quantile(.9), 'pct')}</div>"
                     f"<div class='lb'>Referencia</div><div class='vl2'>{_fmt(cob_ref, 'pct')}</div></div>")
    with g2:
        with st.container(**TARJETA):
            cab_tarjeta("carpa", PAL["acento"], "Frecuencia de apertura de campamentos", "Proporción de simulaciones en que se abre cada campamento")
            fa = sitios.assign(pct=100 * sitios.frecuencia_apertura).sort_values("pct", ascending=False)
            fa["etq"] = [f"{v:.0f} %" if v > 0 else "" for v in fa.pct]
            base_b = alt.Chart(fa).encode(y=alt.Y("municipio:N", sort=list(fa.municipio), title=None,
                                                  axis=alt.Axis(labelLimit=120)))
            barras = base_b.mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3, height={"band": 0.7}).encode(
                x=alt.X("pct:Q", title="Frecuencia de apertura (%)", scale=alt.Scale(domain=[0, 112]), axis=alt.Axis(values=[0, 20, 40, 60, 80, 100])),
                color=alt.Color("clase:N", title=None, legend=alt.Legend(columns=2, symbolType="square"),
                                scale=alt.Scale(domain=list(COLOR_CLASE_SITIO), range=[_hex(c) for c in COLOR_CLASE_SITIO.values()])),
                tooltip=["municipio", "categoria", "capacidad_K", alt.Tooltip("pct:Q", format=".1f", title="% apertura"), "clase"])
            textos = base_b.mark_text(align="left", dx=4, fontSize=10, color=PAL["tinta2"]).encode(x="pct:Q", text="etq:N")
            umbrales = alt.Chart(pd.DataFrame({"v": [20, 80]})).mark_rule(strokeDash=[3, 3], color=PAL["tenue"], opacity=0.7).encode(x="v:Q")
            grafico(barras + textos + umbrales, alto=max(250, 21 * len(fa)))
            st.caption("Núcleo ≥ 80 % · Sensible 20–80 % · Ocasional < 20 % · Nunca abierto 0 %.")
    with g3:
        with st.container(**TARJETA):
            ancla("sensibilidad")
            cab_tarjeta("dispersion", PAL["acento"], "Sensibilidad de los parámetros", "Correlación de rangos de Spearman con la métrica elegida")
            met = st.radio("Métrica", ["Personas atendidas", "Cobertura"], horizontal=True, label_visibility="collapsed")
            col_met = "atendidos" if met == "Personas atendidas" else "cobertura"
            sens = sensibilidad(tabla, col_met)
            tor = alt.Chart(sens).mark_bar(height={"band": 0.55}, cornerRadius=3).encode(
                x=alt.X("spearman:Q", title="Correlación con " + met.lower(), scale=alt.Scale(domain=[-1, 1])),
                y=alt.Y("parametro:N", sort=alt.EncodingSortField("spearman", op="max", order="descending"), title=None,
                        axis=alt.Axis(labelLimit=210)),
                color=alt.condition(alt.datum.spearman > 0, alt.value(PAL["azul"]), alt.value(PAL["rosa"])),
                tooltip=["parametro", alt.Tooltip("spearman:Q", format=".2f")])
            cero = alt.Chart(pd.DataFrame({"v": [0]})).mark_rule(color=PAL["tenue"]).encode(x="v:Q")
            grafico(tor + cero, alto=205)
            html(f"<div class='mc-leyenda' style='font-size:0.76rem'><span class='sw' style='display:inline-block;background:{PAL['azul']};"
                 f"border-radius:50%;margin-right:5px'></span>al subir el parámetro sube la métrica&nbsp;&nbsp;"
                 f"<span class='sw' style='display:inline-block;background:{PAL['rosa']};border-radius:50%;margin-right:5px'></span>la métrica baja</div>")
            st.caption("Con f y el factor de hogar la cobertura baja aunque las personas atendidas casi no cambien, porque crece la demanda.")

    # ---------------- Fila: mapa · municipios más vulnerables ----------------
    ancla("mapa")
    deptos = sorted(set(datos["dem"].departamento) | set(datos["cand"].departamento))
    mp, vu = st.columns([1.7, 1])
    with mp:
        with st.container(**TARJETA):
            cab_tarjeta("mapa", PAL["acento"], "Mapa de robustez",
                        "Municipios con demanda, campamentos candidatos y conexiones (cabeceras DIVIPOLA del proyecto)")
            f1, f2, f3, f4, f5 = st.columns([1.15, 1, 0.75, 1.15, 0.95])
            var_color = f1.selectbox("Color de municipios", ["Probabilidad de atención", "Cobertura promedio", "Clase de robustez",
                                                             "Demanda promedio"])
            foco = f2.selectbox("Campamento", ["Todos"] + sorted(sitios.municipio))
            fondo_map = f3.selectbox("Fondo", ["Claro", "Calles"])
            umbral = f4.select_slider("Frecuencia mínima", options=[0.10, 0.20, 0.40, 0.60, 0.80], value=0.20,
                                      format_func=lambda v: f"{int(v * 100)} %")
            with f5:
                html("<div style='height:1.75rem'></div>")
                with st.popover("Capas y filtros", **ANCHO):
                    sel_dep = st.multiselect("Departamentos", deptos, default=deptos)
                    clases_sel = st.multiselect("Clasificación de campamentos", list(COLOR_CLASE_SITIO),
                                                default=["Núcleo", "Sensible", "Ocasional"])
                    ver_cand = st.checkbox("Mostrar candidatos", value=True)
                    ver_dem = st.checkbox("Mostrar demanda", value=True)
                    ver_arc = st.checkbox("Mostrar conexiones", value=True)
                    ver_etiquetas = st.checkbox("Etiquetas", value=True)

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
                    a["ancho"] = 1.2 + 5.5 * a.frecuencia
                    a["color"] = [[79, 143, 129, int(60 + 140 * fq)] for fq in a.frecuencia]
                    a["tooltip"] = [f"<b>{nom[i]} → {nom[j]}</b><br/>Frecuencia de uso: {100 * fq:.0f} %<br/>"
                                    f"Personas cuando se usa (media): {fl:,.0f}<br/>Distancia por carretera: {km:,.1f} km".replace(",", ".")
                                    for i, j, fq, fl, km in zip(a.id_demanda, a.id_sitio, a.frecuencia, a.flujo_medio_si_se_usa, a.km)]
                    capas.append(pdk.Layer("LineLayer", a.sort_values("frecuencia"), get_source_position=["o_lon", "o_lat"],
                                           get_target_position=["d_lon", "d_lat"], get_color="color", get_width="ancho",
                                           width_units="'pixels'", width_scale=1, width_min_pixels=1, width_max_pixels=8, pickable=True))
            if ver_dem and len(mu):
                vmax = float(mu.demanda_media.max() or 1)
                if var_color == "Probabilidad de atención":
                    mu["color"] = [_escala_divergente(v) + [230] for v in mu.prob_atencion]
                elif var_color == "Cobertura promedio":
                    mu["color"] = [_escala_divergente(v) + [230] for v in mu.cobertura_media]
                elif var_color == "Clase de robustez":
                    mu["color"] = [COLOR_CLASE_MUN.get(c, [150, 150, 150]) + [230] for c in mu.clase]
                else:
                    mu["color"] = [_escala_secuencial(v, vmax) + [230] for v in mu.demanda_media]
                mu["radio"] = 2500 + 9000 * np.sqrt(mu.demanda_media / vmax)
                mu["tooltip"] = [f"<b>{r.municipio}</b> ({r.departamento})<br/>Demanda promedio: {r.demanda_media:,.0f}<br/>"
                                 f"Atendidos promedio: {r.atendidos_media:,.0f}<br/>Cobertura promedio: {100 * r.cobertura_media:.1f} %<br/>"
                                 f"Probabilidad de recibir atención: {100 * r.prob_atencion:.0f} %<br/>"
                                 f"Probabilidad de quedar sin atención: {100 * r.prob_sin_atencion:.0f} %<br/>Clase: {r.clase}".replace(",", ".")
                                 for r in mu.itertuples()]
                capas.append(pdk.Layer("ScatterplotLayer", mu, get_position=["lon", "lat"], get_fill_color="color", get_radius="radio",
                                       stroked=True, get_line_color=[255, 255, 255, 235], line_width_min_pixels=1.5, pickable=True))
            if ver_cand and len(s_map):
                rad = {3000: 7000, 1000: 5200, 500: 4000}
                s_map["radio"] = [rad.get(int(k), 4000) for k in s_map.capacidad_K]
                s_map["color"] = [COLOR_CLASE_SITIO[c] + [245] for c in s_map.clase]
                s_map["tooltip"] = [f"<b>Campamento: {r.municipio}</b> ({r.departamento})<br/>Categoría: {r.categoria} · capacidad {int(r.capacidad_K):,}<br/>"
                                    f"Frecuencia de apertura: {100 * r.frecuencia_apertura:.0f} %<br/>Ocupación media: {r.ocupacion_media:,.0f} personas<br/>"
                                    f"Clasificación: <b>{r.clase}</b>".replace(",", ".") for r in s_map.itertuples()]
                # triángulo = campamento (carpa), para distinguirlo de los municipios (círculos); tamaño según la capacidad
                lado = {3000: 0.065, 1000: 0.054, 500: 0.045}
                s_map["poligono"] = [[[lo - l, la - 0.8 * l], [lo + l, la - 0.8 * l], [lo, la + 1.05 * l]]
                                     for lo, la, l in zip(s_map.lon, s_map.lat, [lado.get(int(k), 0.045) for k in s_map.capacidad_K])]
                capas.append(pdk.Layer("PolygonLayer", s_map, get_polygon="poligono", get_fill_color="color",
                                       get_line_color=[255, 255, 255, 255], line_width_min_pixels=2, stroked=True, pickable=True))
            if ver_etiquetas:
                etq = []
                if ver_cand and len(s_map):
                    etq += [dict(lon=r.lon, lat=r.lat + 0.095, texto=r.municipio, tam=13) for r in s_map[s_map.clase.isin(["Núcleo", "Sensible"])].itertuples()]
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
                                           get_color=[38, 50, 58, 255], get_alignment_baseline="'center'", font_weight=600,
                                           font_family="'Inter, Helvetica, Arial, sans-serif'",
                                           character_set="'" + "".join(sorted(set(c for c in "".join(chr(k) for k in range(32, 127)) + "".join(e["texto"] for e in etq)
                                                                        if c.isalnum() or c in " .-"))) + "'",
                                           background=True, get_background_color=[255, 255, 255, 225], background_padding=[4, 2]))

            lats = pd.concat([datos["dem"].lat, datos["cand"].lat])
            lons = pd.concat([datos["dem"].lon, datos["cand"].lon])
            # encuadre automático de todos los nodos (aprox. Web Mercator), con 20 % de margen
            dlon = max(float(lons.max() - lons.min()), 0.3)
            dlat = max(float(lats.max() - lats.min()), 0.3)
            zoom0 = float(np.clip(min(np.log2(700 * 360 / (512 * dlon * 1.2)), np.log2(560 * 360 / (512 * dlat * 1.2))), 5, 10))
            vista = pdk.ViewState(latitude=float((lats.max() + lats.min()) / 2), longitude=float((lons.max() + lons.min()) / 2), zoom=zoom0)
            deck = pdk.Deck(layers=capas, initial_view_state=vista,
                            map_provider="carto", map_style="light" if fondo_map == "Claro" else "road",
                            tooltip={"html": "{tooltip}", "style": {"backgroundColor": "white", "color": PAL["tinta"], "fontSize": "12px",
                                                                    "border": f"1px solid {PAL['borde']}", "borderRadius": "8px",
                                                                    "boxShadow": "0 2px 6px rgba(38,50,58,0.08)", "fontFamily": FUENTE}})
            c_map, c_ley = st.columns([3.3, 1])
            with c_map:
                st.pydeck_chart(deck, height=560)
            with c_ley:
                def muestra(rgb, forma="circulo"):
                    if forma == "triangulo":
                        return (f"<svg class='sw' viewBox='0 0 12 12' width='12' height='12'><polygon points='6,1 11.5,11 0.5,11' "
                                f"fill='{_hex(rgb)}'/></svg>")
                    return f"<span class='sw' style='background:{_hex(rgb)};border-radius:50%'></span>"
                ley = "<div class='mc-leyenda'><div class='g'>Leyenda</div>"
                if var_color == "Clase de robustez":
                    ley += "".join(f"<div class='fila'>{muestra(c)}<div>Municipio {k.lower()}</div></div>" for k, c in COLOR_CLASE_MUN.items())
                    ley += "<div class='n'>≥ 80 % de las simulaciones; tamaño = demanda</div>"
                elif var_color == "Demanda promedio":
                    ley += (f"<div class='fila'>{muestra([222, 236, 232])}<div>Demanda baja</div></div>"
                            f"<div class='fila'>{muestra([63, 122, 109])}<div>Demanda alta</div></div>")
                else:
                    ley += (f"<div class='n'>Municipios · {var_color.lower()}</div>"
                            f"<div class='fila'>{muestra(_escala_divergente(1))}<div>100 %</div></div>"
                            f"<div class='fila'>{muestra(_escala_divergente(.5))}<div>50 %</div></div>"
                            f"<div class='fila'>{muestra(_escala_divergente(0))}<div>0 %</div></div>")
                ley += "<div class='sep'></div><div class='n'>Campamentos · tamaño = capacidad</div>"
                ley += "".join(f"<div class='fila'>{muestra(c, 'triangulo')}<div>{k}</div></div>" for k, c in COLOR_CLASE_SITIO.items())
                ley += (f"<div class='sep'></div><div class='fila'><span class='sw' style='height:3px;margin-top:0.5rem;background:{PAL['acento']}'></span>"
                        f"<div>Asignación demanda → campamento<div class='n'>grosor = frecuencia; se muestran las ≥ {int(umbral * 100)} %</div></div></div></div>")
                html(ley)
            st.caption("Las líneas son conexiones directas indicativas (no rutas viales). Robustamente atendido: atención en ≥ 80 % de las "
                       "simulaciones. Vulnerable: sin atención en ≥ 80 %.")
    with vu:
        with st.container(**TARJETA):
            cab_tarjeta("alerta", PAL["rosa"], "Municipios más vulnerables", "Ordenados por menor cobertura mediana entre simulaciones")
            # cobertura de cada municipio en cada simulación (solo para mostrar mediana, P10 y P90 por municipio)
            ids = list(datos["dem"].index)
            cm = pd.DataFrame([[s[i][0] / s[i][1] if s[i][1] > 0 else 0.0 for i in ids] for s in res["atend_mun"]], columns=ids)
            vul = muni.assign(cob_med=cm.median().reindex(muni.index), cob_p10=cm.quantile(.1).reindex(muni.index),
                              cob_p90=cm.quantile(.9).reindex(muni.index))
            vul = vul.sort_values(["cob_med", "cobertura_media", "demanda_media"], ascending=[True, True, False])

            def nivel_riesgo(p):
                if p >= 0.8:
                    return "Muy alta", PAL["rosa"]
                if p >= 0.5:
                    return "Alta", "#DE9A8F"
                if p >= 0.2:
                    return "Media", PAL["arena"]
                return "Baja", PAL["verde"]
            filas_v = []
            for k_, r in enumerate(vul.head(10).itertuples(), 1):
                etq_n, col_n = nivel_riesgo(r.prob_sin_atencion)
                col_c = PAL["rosa"] if r.cob_med < 0.2 else (PAL["tinta"] if r.cob_med < 0.8 else PAL["verde"])
                filas_v.append(f"<tr><td style='color:{PAL['tenue']}'>{k_}</td><td>{r.municipio}<div style='font-size:0.7rem;color:{PAL['tenue']}'>"
                               f"{r.departamento}</div></td>"
                               f"<td class='num' style='color:{col_c};font-weight:600'>{_fmt(r.cob_med, 'pct')}</td>"
                               f"<td class='num' style='color:{PAL['tinta2']}'>{_fmt(r.cob_p10, 'pct')} – {_fmt(r.cob_p90, 'pct')}</td>"
                               f"<td><span class='mc-nivel' style='color:{col_n}'><i style='background:{col_n}'></i>{etq_n}</span></td></tr>")
            html("<table class='mc-tab'><tr><th>#</th><th>Municipio</th><th class='num'>Cob. mediana</th><th class='num'>P10 – P90</th>"
                 "<th>Riesgo</th></tr>" + "".join(filas_v) + "</table>")
            st.caption("Riesgo = probabilidad de quedar sin atención: muy alta ≥ 80 %, alta 50–80 %, media 20–50 %, baja < 20 %.")
            with st.expander("Ver todos los municipios"):
                st.dataframe(muni[["municipio", "departamento", "demanda_media", "cobertura_media", "prob_atencion", "prob_sin_atencion", "clase"]]
                             .sort_values("prob_atencion").round(3), hide_index=True, **ANCHO)

    # ---------------- Detalle: supuestos, comparación, redes, dispersión, tablas ----------------
    ancla("detalle")
    seccion("Supuestos y detalle de la simulación", "Rangos usados, comparación con la referencia, redes frecuentes y tablas completas")
    d1, d2 = st.columns([1.3, 1])
    with d1:
        with st.container(**TARJETA):
            cab_tarjeta("ajustes", PAL["acento"], "Supuestos inciertos", "Rangos y distribuciones que se muestrean en cada simulación")
            tabla_rangos()
    with d2:
        with st.container(**TARJETA):
            cab_tarjeta("check", PAL["acento"], "Comparación con el escenario de referencia", "Mismos parámetros del modelo base resueltos con este código")
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

    e1, e2, e3 = st.columns([1, 1, 1])
    with e1:
        with st.container(**TARJETA):
            cab_tarjeta("red", PAL["acento"], "Redes más frecuentes", "Combinaciones de campamentos abiertos")
            redes = validas.red.value_counts().rename_axis("Red de campamentos").reset_index(name="Simulaciones")
            redes["%"] = (100 * redes.Simulaciones / n_val).round(1)
            redes["Atendidos (media)"] = [validas.loc[validas.red == r, "atendidos"].mean().round(0) for r in redes["Red de campamentos"]]
            st.dataframe(redes.head(8), hide_index=True, **ANCHO)
    with e2:
        with st.container(**TARJETA):
            cab_tarjeta("personas", PAL["acento"], "Atendidos frente a demanda", "Cada punto es una simulación")
            sc = alt.Chart(validas).mark_circle(size=46, opacity=0.85, stroke="white", strokeWidth=0.8).encode(
                x=alt.X("demanda:Q", title="Demanda de la simulación (personas)"), y=alt.Y("atendidos:Q", title="Personas atendidas"),
                color=alt.Color("n_abiertos:O", title="Campamentos", scale=esc_camp),
                tooltip=["sim", "f", "factor_hogar", "c_f", "v_kit", "atendidos", "red"])
            grafico(sc, alto=250)
            st.caption("Si los puntos forman una línea horizontal, el presupuesto (no la demanda) fija cuántas personas se atienden.")
    with e3:
        with st.container(**TARJETA):
            cab_tarjeta("dispersion", PAL["acento"], "Parámetro frente a la métrica", f"Métrica: {met.lower()}")
            p_sel = st.selectbox("Parámetro para el diagrama de dispersión", list(PARAMS), format_func=lambda k: PARAMS[k][0])
            disp = alt.Chart(validas).mark_circle(size=40, opacity=0.85, stroke="white", strokeWidth=0.8).encode(
                x=alt.X(f"{p_sel}:Q", title=PARAMS[p_sel][0], scale=alt.Scale(zero=False)),
                y=alt.Y(f"{col_met}:Q", title=met, scale=alt.Scale(zero=False)),
                color=alt.Color("n_abiertos:O", title="Campamentos", scale=esc_camp))
            grafico(disp, alto=200)

    with st.container(**TARJETA):
        cab_tarjeta("tabla", PAL["acento"], "Tablas de robustez", "Campamentos y coeficientes de sensibilidad")
        t1, t2 = st.columns([1.2, 1])
        with t1:
            st.dataframe(sitios[["municipio", "departamento", "categoria", "capacidad_K", "frecuencia_apertura", "ocupacion_media", "clase"]]
                         .sort_values("frecuencia_apertura", ascending=False).round(3), hide_index=True, **ANCHO)
        with t2:
            st.dataframe(sens.drop(columns="clave").rename(columns={"parametro": "Parámetro", "spearman": "Spearman",
                         "media_tercio_bajo": "Media (tercio bajo)", "media_tercio_alto": "Media (tercio alto)", "diferencia": "Diferencia"}).round(3),
                         hide_index=True, **ANCHO)

    with st.expander("Convergencia (¿son suficientes las simulaciones?)"):
        cv = validas[["sim", "cobertura"]].copy()
        cv["media"] = cv.cobertura.expanding().mean() * 100
        cv["ee"] = cv.cobertura.expanding().std().fillna(0) / np.sqrt(np.arange(1, len(cv) + 1)) * 100
        cv["lo"], cv["hi"] = cv.media - 1.96 * cv.ee, cv.media + 1.96 * cv.ee
        banda = alt.Chart(cv).mark_area(opacity=0.6, color=PAL["acento_fondo"]).encode(x=alt.X("sim:Q", title="Simulación"), y="lo:Q", y2="hi:Q")
        linea = alt.Chart(cv).mark_line(color=PAL["acento"], strokeWidth=2).encode(x="sim:Q", y=alt.Y("media:Q", title="Cobertura media acumulada (%)"))
        grafico(banda + linea, alto=240)
        st.caption(f"Intervalo de 95 % de la media al final: ±{1.96 * cob.std() / np.sqrt(n_val) * 100:.2f} puntos.".replace(".", ","))

    # ---------------- Datos y descargas (no se escribe nada en el proyecto) ----------------
    with st.expander("Resultados por simulación y descargas"):
        st.dataframe(tabla.drop(columns=[c for c in tabla.columns if c.startswith("y_")]), hide_index=True, **ANCHO)
        st.download_button("Descargar simulaciones (CSV)", tabla.to_csv(index=False).encode("utf-8"), "montecarlo_simulaciones.csv", "text/csv")
        st.download_button("Descargar frecuencia de arcos (CSV)", arcos.assign(origen=arcos.id_demanda.map(nom), sitio=arcos.id_sitio.map(nom))
                           .to_csv(index=False).encode("utf-8"), "montecarlo_arcos.csv", "text/csv")
        st.caption("Las descargas se generan en memoria; la app no escribe archivos en la carpeta del proyecto.")


if __name__ == "__main__":
    main()
