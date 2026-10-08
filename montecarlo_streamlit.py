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
# Estética: fondo claro con acentos vivos y elegantes (azul profundo, turquesa, verde, coral y amarillo).
# Coral = vulnerabilidad/alertas; verde = resultados positivos; turquesa/azul = elementos neutros del análisis.
# ------------------------------------------------------------------------------------------------------------------
PAL = dict(
    fondo="#F3F6F9", lateral="#FFFFFF", tarjeta="#FFFFFF", borde="#DFE6EE", rejilla="#E9EEF4",
    tinta="#13263A", tinta2="#3B4D60", tenue="#5D6E80",
    azul="#1D4E89", azul_osc="#163C6A", azul_fondo="#E6EEF8",
    turquesa="#0FA3A3", turquesa_osc="#0B8585", turquesa_fondo="#E0F4F3",
    verde="#2E9E6A", verde_fondo="#E3F4EB",
    coral="#E8604C", coral_fondo="#FDECE8",
    amarillo="#F0B429", amarillo_osc="#B7820F", amarillo_fondo="#FDF4DD",
    gris="#C3CBD5",
)
COLOR_CLASE_SITIO = {"Núcleo": [46, 158, 106], "Sensible": [240, 180, 41], "Ocasional": [76, 125, 201], "Nunca abierto": [195, 203, 213]}
COLOR_CLASE_MUN = {"Robustamente atendido": [46, 158, 106], "Intermedio": [240, 180, 41], "Vulnerable": [232, 96, 76]}
FUENTE = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"

# Íconos de línea (estilo "lucide", lienzo de 24 px).
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
    "foco": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "bombilla": '<path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.3h6c0-1 .4-1.8 1-2.3A7 7 0 0 0 12 2z"/>',
    "reloj": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "descarga": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
}


def icono(nombre, color, tam=20, grosor=1.9):
    return (f"<svg width='{tam}' height='{tam}' viewBox='0 0 24 24' fill='none' stroke='{color}' stroke-width='{grosor}' "
            f"stroke-linecap='round' stroke-linejoin='round' style='flex:0 0 auto'>{_ICONOS[nombre]}</svg>")


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select, label {{ font-family: {FUENTE}; }}
.stApp {{ background: {PAL['fondo']}; color: {PAL['tinta']}; }}
[data-testid="stHeader"] {{ background: rgba(243, 246, 249, 0.85); }}
.block-container {{ padding-top: 1.4rem; padding-bottom: 2.5rem; max-width: 1500px; }}
[data-testid="stVerticalBlock"] {{ gap: 0.85rem; }}
p, li, label, .stMarkdown {{ color: {PAL['tinta']}; }}
[data-testid="stWidgetLabel"] p {{ font-size: 0.8rem !important; font-weight: 600 !important; color: {PAL['tinta2']} !important; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: {PAL['tenue']} !important; font-size: 0.8rem; line-height: 1.45; }}
/* ---------- barra lateral ---------- */
[data-testid="stSidebar"] {{ background: {PAL['lateral']}; border-right: 1px solid {PAL['borde']}; }}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap: 0.6rem; }}
.mc-marca {{ display: flex; align-items: center; gap: 0.75rem; margin: 0 0 1rem 0; padding: 0.85rem; border-radius: 14px;
    background: linear-gradient(135deg, {PAL['azul']} 0%, {PAL['turquesa_osc']} 100%); }}
.mc-marca .t {{ font-size: 1.05rem; font-weight: 700; color: #FFFFFF; line-height: 1.15; }}
.mc-marca .s {{ font-size: 0.74rem; color: #D9ECF2; line-height: 1.3; margin-top: 0.1rem; }}
.mc-marca .lg {{ width: 44px; height: 44px; border-radius: 12px; background: rgba(255,255,255,0.16); display: flex; align-items: center;
    justify-content: center; flex: 0 0 auto; }}
.mc-nav a {{ display: flex; align-items: center; gap: 0.65rem; padding: 0.5rem 0.7rem; border-radius: 10px; color: {PAL['tinta2']} !important;
    text-decoration: none !important; font-size: 0.88rem; font-weight: 500; margin-bottom: 2px; }}
.mc-nav a:hover {{ background: {PAL['azul_fondo']}; color: {PAL['azul']} !important; }}
.mc-nav a.activo {{ background: {PAL['azul_fondo']}; color: {PAL['azul']} !important; font-weight: 700; }}
.mc-lat {{ display: flex; align-items: center; gap: 0.5rem; font-size: 0.74rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.07em;
    color: {PAL['azul']}; margin: 1.1rem 0 0.45rem 0; padding-top: 0.9rem; border-top: 1px solid {PAL['borde']}; }}
.mc-chip-ok {{ display: flex; gap: 0.5rem; align-items: flex-start; font-size: 0.78rem; color: {PAL['tinta']}; background: {PAL['verde_fondo']};
    border: 1px solid #C5E6D3; border-radius: 10px; padding: 0.5rem 0.65rem; line-height: 1.35; }}
.mc-chip-ok code {{ background: transparent; color: {PAL['verde']}; font-size: 0.74rem; padding: 0; }}
[data-testid="stSidebar"] [data-testid="stExpander"] details {{ background: {PAL['fondo']}; border-radius: 10px; }}
[data-testid="stSidebar"] [data-testid="stExpander"] summary p {{ font-size: 0.84rem; font-weight: 600; color: {PAL['tinta']}; }}
/* ---------- tarjetas (contenedores con borde) ---------- */
div[data-testid="stVerticalBlockBorderWrapper"] {{ border: 1px solid {PAL['borde']} !important; border-radius: 16px !important;
    background: {PAL['tarjeta']}; box-shadow: 0 1px 2px rgba(19, 38, 58, 0.04), 0 4px 14px rgba(19, 38, 58, 0.04); }}
/* ---------- botones y controles ---------- */
.stButton > button, .stDownloadButton > button, [data-testid="stPopover"] button {{ border-radius: 10px; border: 1px solid {PAL['borde']};
    background: {PAL['tarjeta']}; color: {PAL['azul']}; font-weight: 600; box-shadow: none; }}
.stDownloadButton > button:hover, [data-testid="stPopover"] button:hover {{ border-color: {PAL['turquesa']}; color: {PAL['turquesa_osc']}; }}
.stButton > button[kind="primary"] {{ background: linear-gradient(135deg, {PAL['azul']} 0%, {PAL['turquesa_osc']} 100%); border: 0;
    color: #FFFFFF; font-weight: 700; padding: 0.65rem 0; box-shadow: 0 4px 12px rgba(29, 78, 137, 0.25); }}
.stButton > button[kind="primary"]:hover {{ filter: brightness(1.06); color: #FFFFFF; }}
.stButton > button[kind="primary"] p, [data-testid="stBaseButton-primary"] p {{ color: #FFFFFF !important; font-weight: 700; }}
[data-baseweb="tag"] {{ background: {PAL['turquesa_fondo']} !important; border-radius: 7px !important; }}
[data-baseweb="tag"] span, [data-baseweb="tag"] svg {{ color: {PAL['turquesa_osc']} !important; fill: {PAL['turquesa_osc']} !important; font-weight: 600; }}
[data-baseweb="select"] > div, [data-baseweb="input"] > div, .stNumberInput input, .stTextInput input {{ border-radius: 9px !important; }}
[data-testid="stDataFrame"] {{ border: 1px solid {PAL['borde']}; border-radius: 12px; overflow: hidden; }}
[data-testid="stExpander"] details {{ border: 1px solid {PAL['borde']}; border-radius: 14px; background: {PAL['tarjeta']}; }}
[data-testid="stExpander"] summary p {{ font-weight: 600; color: {PAL['tinta']}; }}
[data-testid="stAlert"] {{ border-radius: 12px; }}
/* ---------- encabezado ---------- */
.mc-cab {{ display: flex; align-items: stretch; background: {PAL['tarjeta']}; border: 1px solid {PAL['borde']}; border-radius: 18px;
    overflow: hidden; box-shadow: 0 1px 2px rgba(19,38,58,0.04), 0 6px 18px rgba(19,38,58,0.05); }}
.mc-cab .izq {{ flex: 1 1 auto; min-width: 0; display: flex; gap: 1.1rem; align-items: center; padding: 1.25rem 1.5rem; }}
.mc-cab .logo {{ flex: 0 0 auto; width: 68px; height: 68px; border-radius: 18px; display: flex; align-items: center; justify-content: center;
    background: linear-gradient(135deg, {PAL['azul']} 0%, {PAL['turquesa']} 100%); box-shadow: 0 6px 14px rgba(15, 163, 163, 0.25); }}
.mc-cab .txt {{ min-width: 0; }}
.mc-cab .kick {{ font-size: 0.72rem; font-weight: 700; letter-spacing: 0.09em; text-transform: uppercase; color: {PAL['turquesa_osc']}; }}
.mc-cab h1 {{ font-size: 1.75rem; font-weight: 800; margin: 0.1rem 0 0 0; padding: 0; color: {PAL['tinta']}; letter-spacing: -0.02em; line-height: 1.2; }}
.mc-cab .s1 {{ font-size: 0.98rem; color: {PAL['tinta2']}; margin-top: 0.25rem; font-weight: 500; }}
.mc-cab .s2 {{ font-size: 0.84rem; color: {PAL['tenue']}; margin-top: 0.3rem; line-height: 1.45; }}
.mc-cab .der {{ flex: 0 0 300px; position: relative; background: linear-gradient(180deg, #D7E9F5 0%, #EEF6F7 100%); }}
.mc-cab .der svg {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
.mc-cab .lema {{ position: absolute; right: 1.1rem; top: 0.85rem; font-family: Georgia, 'Times New Roman', serif; font-style: italic;
    color: {PAL['azul']}; font-size: 1.12rem; text-align: right; line-height: 1.12; }}
.mc-cab .lema .bandera {{ display: block; height: 4px; width: 66px; margin: 0.4rem 0 0 auto; border-radius: 2px;
    background: linear-gradient(90deg, #F6C744 0 50%, #2F5BA8 50% 75%, #D9473D 75% 100%); }}
@media (max-width: 1360px) {{ .mc-cab .der {{ display: none; }} }}
.mc-pildoras {{ margin-top: 0.55rem; display: flex; flex-wrap: wrap; gap: 0.4rem; }}
.mc-pildora {{ display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.72rem; font-weight: 600; border-radius: 999px; padding: 0.18rem 0.65rem; }}
.mc-meta {{ display: flex; flex-wrap: wrap; gap: 0.45rem; align-items: center; margin: 0.6rem 0 0.45rem 0; font-size: 0.8rem; color: {PAL['tinta2']}; }}
.mc-meta .it {{ display: inline-flex; align-items: center; gap: 0.35rem; background: {PAL['tarjeta']}; border: 1px solid {PAL['borde']};
    border-radius: 999px; padding: 0.22rem 0.7rem; }}
.mc-meta b {{ color: {PAL['tinta']}; }}
/* ---------- tarjetas KPI ---------- */
.mc-kpis {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 0.85rem; margin: 0.15rem 0 0.35rem 0; }}
@media (max-width: 1750px) {{ .mc-kpis {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }} }}
@media (max-width: 900px) {{ .mc-kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
.mc-kpi {{ position: relative; background: {PAL['tarjeta']}; border: 1px solid {PAL['borde']}; border-radius: 16px; padding: 0.95rem 1rem 0.9rem 1rem;
    box-shadow: 0 1px 2px rgba(19,38,58,0.04), 0 4px 14px rgba(19,38,58,0.04); overflow: hidden; min-width: 0; }}
.mc-kpi::before {{ content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--acento); }}
.mc-kpi .top {{ display: flex; gap: 0.6rem; align-items: center; min-width: 0; }}
.mc-kpi .ic {{ flex: 0 0 auto; width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; }}
.mc-kpi .lb {{ font-size: 0.8rem; font-weight: 600; color: {PAL['tinta2']}; line-height: 1.25; min-width: 0; }}
.mc-kpi .vl {{ font-size: 1.75rem; font-weight: 800; color: {PAL['tinta']}; line-height: 1.15; margin-top: 0.6rem; letter-spacing: -0.02em;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.mc-kpi .nt {{ font-size: 0.76rem; color: {PAL['tenue']}; line-height: 1.35; margin-top: 0.3rem; }}
.mc-kpis.mini {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
@media (max-width: 1350px) {{ .mc-kpis.mini {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
.mc-kpi.mini {{ display: flex; gap: 0.75rem; align-items: center; padding: 0.75rem 0.95rem; }}
.mc-kpi.mini .vl {{ font-size: 1.2rem; margin-top: 0.12rem; }}
.mc-delta {{ display: inline-flex; align-items: center; gap: 0.2rem; font-weight: 700; border-radius: 999px; padding: 0.05rem 0.45rem; font-size: 0.74rem; }}
/* ---------- hallazgos ---------- */
.mc-hall {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.85rem; margin: 0.35rem 0 0.2rem 0; }}
@media (max-width: 1100px) {{ .mc-hall {{ grid-template-columns: 1fr; }} }}
.mc-hall .h {{ display: flex; gap: 0.7rem; align-items: flex-start; background: {PAL['tarjeta']}; border: 1px solid {PAL['borde']}; border-radius: 14px;
    padding: 0.8rem 0.95rem; min-width: 0; }}
.mc-hall .h .ic {{ flex: 0 0 auto; width: 32px; height: 32px; border-radius: 9px; display: flex; align-items: center; justify-content: center; }}
.mc-hall .h .t {{ font-size: 0.74rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: {PAL['tenue']}; }}
.mc-hall .h .d {{ font-size: 0.88rem; color: {PAL['tinta']}; line-height: 1.4; margin-top: 0.1rem; }}
/* ---------- encabezados de tarjeta y secciones ---------- */
.mc-th {{ display: flex; gap: 0.7rem; align-items: center; margin: 0 0 0.25rem 0; }}
.mc-th .ic {{ flex: 0 0 auto; width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; }}
.mc-th .t {{ font-size: 1.02rem; font-weight: 700; color: {PAL['tinta']}; line-height: 1.25; }}
.mc-th .s {{ font-size: 0.8rem; color: {PAL['tenue']}; line-height: 1.35; margin-top: 0.05rem; }}
.mc-seccion {{ display: flex; align-items: center; gap: 0.6rem; margin: 1.3rem 0 0.1rem 0; }}
.mc-seccion .t {{ font-size: 1.18rem; font-weight: 800; color: {PAL['tinta']}; letter-spacing: -0.01em; white-space: nowrap; }}
.mc-seccion .linea {{ flex: 1 1 auto; height: 1px; background: {PAL['borde']}; }}
.mc-seccion .s {{ font-size: 0.8rem; color: {PAL['tenue']}; white-space: nowrap; }}
.mc-stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.5rem; margin: 0.35rem 0 0.2rem 0; }}
.mc-stats .c {{ border-radius: 11px; padding: 0.5rem 0.65rem; min-width: 0; }}
.mc-stats .c .lb {{ font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; }}
.mc-stats .c .vl {{ font-size: 1.05rem; font-weight: 800; color: {PAL['tinta']}; white-space: nowrap; }}
/* ---------- leyenda del mapa ---------- */
.mc-leyenda {{ font-size: 0.8rem; color: {PAL['tinta']}; line-height: 1.45; background: {PAL['fondo']}; border-radius: 12px; padding: 0.8rem 0.85rem; }}
.mc-leyenda .g {{ font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: {PAL['azul']}; margin: 0 0 0.35rem 0; }}
.mc-leyenda .n {{ color: {PAL['tenue']}; font-size: 0.74rem; margin-bottom: 0.25rem; }}
.mc-leyenda .fila {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.22rem; }}
.mc-leyenda .sw {{ flex: 0 0 auto; width: 12px; height: 12px; }}
.mc-leyenda .sep {{ border-top: 1px solid {PAL['borde']}; margin: 0.6rem 0; }}
.mc-grad {{ height: 8px; border-radius: 4px; margin: 0.3rem 0 0.15rem 0; }}
.mc-grad-et {{ display: flex; justify-content: space-between; font-size: 0.7rem; color: {PAL['tenue']}; }}
/* ---------- tablas ---------- */
.mc-tabw {{ border: 1px solid {PAL['borde']}; border-radius: 12px; overflow: auto; background: {PAL['tarjeta']}; margin-bottom: 0.55rem; }}
.mc-tabw table {{ margin: 0 !important; }}
table.mc-tab {{ width: 100%; border-collapse: separate; border-spacing: 0; font-size: 0.83rem; border: 0 !important; }}
table.mc-tab th, table.mc-tab td {{ border: 0 !important; }}
table.mc-tab thead th {{ position: sticky; top: 0; z-index: 1; text-align: left; font-weight: 700; color: {PAL['azul']}; font-size: 0.72rem;
    text-transform: uppercase; letter-spacing: 0.05em; padding: 0.6rem 0.75rem; background: {PAL['azul_fondo']}; border-bottom: 1px solid #CFDCEB;
    white-space: nowrap; border-bottom: 1px solid #CFDCEB !important; }}
table.mc-tab td {{ padding: 0.5rem 0.7rem; border-bottom: 1px solid {PAL['rejilla']} !important; color: {PAL['tinta']}; vertical-align: middle;
    line-height: 1.35; }}
table.mc-tab tbody tr:last-child td {{ border-bottom: 0 !important; }}
table.mc-tab tbody tr:nth-child(even) td {{ background: #FAFCFD; }}
table.mc-tab tbody tr:hover td {{ background: {PAL['turquesa_fondo']}; }}
table.mc-tab .r {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
table.mc-tab .c {{ text-align: center; white-space: nowrap; }}
table.mc-tab .nw {{ white-space: nowrap; }}
table.mc-tab .sub {{ display: block; font-size: 0.72rem; color: {PAL['tenue']}; }}
table.mc-tab .fuerte {{ font-weight: 700; }}
.mc-badge {{ display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.74rem; font-weight: 700; border-radius: 999px; padding: 0.14rem 0.6rem;
    white-space: nowrap; }}
.mc-badge i {{ display: inline-block; width: 7px; height: 7px; border-radius: 50%; }}
.mc-barra {{ display: flex; align-items: center; gap: 0.5rem; justify-content: flex-end; }}
.mc-barra .b {{ width: 70px; height: 6px; border-radius: 3px; background: {PAL['rejilla']}; overflow: hidden; flex: 0 0 auto; }}
.mc-barra .b span {{ display: block; height: 100%; border-radius: 3px; }}
</style>
"""

_PAISAJE = (
    "<svg viewBox='0 0 300 150' preserveAspectRatio='xMidYMax slice' xmlns='http://www.w3.org/2000/svg'>"
    "<circle cx='60' cy='40' r='14' fill='#FBE3A2' opacity='0.9'/><g transform='translate(0 24)'>"
    "<path d='M0 104 L38 74 L66 90 L112 44 L142 70 L176 36 L206 64 L248 30 L276 56 L300 46 L300 150 L0 150Z' fill='#9DB8D4'/>"
    "<path d='M112 44 L124 55 L116 54 L110 60 L104 54 Z M176 36 L188 48 L180 47 L174 53 L168 47 Z M248 30 L260 42 L252 41 L246 47 L240 41 Z' fill='#FFFFFF'/>"
    "<path d='M0 118 L44 96 L92 110 L146 82 L196 104 L246 86 L300 98 L300 150 L0 150Z' fill='#5FB7AE'/>"
    "<path d='M0 134 L60 116 L120 128 L182 112 L240 126 L300 116 L300 150 L0 150Z' fill='#2E9E8A'/>"
    "<path d='M150 150 L166 128 L182 150 Z' fill='#F0B429'/><path d='M166 128 L166 150' stroke='#B7820F' stroke-width='1.2'/></g>"
    "</svg>")


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def _escala_divergente(v: float) -> list[int]:
    """0 → coral (vulnerable), 0,5 → amarillo claro, 1 → verde (robusto)."""
    v = 0.0 if v is None or np.isnan(v) else min(max(v, 0.0), 1.0)
    a, m, b = np.array([232, 96, 76]), np.array([245, 205, 110]), np.array([46, 158, 106])
    rgb = a + (m - a) * (v / 0.5) if v < 0.5 else m + (b - m) * ((v - 0.5) / 0.5)
    return [int(x) for x in rgb]


def _escala_secuencial(v: float, vmax: float) -> list[int]:
    t = 0.0 if vmax <= 0 else min(max(v / vmax, 0.0), 1.0)
    a, b = np.array([198, 232, 230]), np.array([29, 78, 137])
    return [int(x) for x in a + (b - a) * t]


def _fmt(v, tipo):
    if tipo == "pct":
        return f"{100 * v:.1f} %".replace(".", ",")
    if tipo == "cop":
        return f"${v:,.0f}".replace(",", ".")
    return f"{v:.2f}".replace(".", ",")


def _mil(v):
    return f"{v:,.0f}".replace(",", ".")


def _dec(v, d=1):
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _badge(texto, color, fondo):
    return f"<span class='mc-badge' style='color:{color};background:{fondo}'><i style='background:{color}'></i>{texto}</span>"


def _barra_pct(v, color):
    """Porcentaje con mini barra de progreso (v en 0–1)."""
    v = 0.0 if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
    return (f"<div class='mc-barra'><span>{_fmt(v, 'pct')}</span><div class='b'><span style='width:{max(min(v, 1), 0) * 100:.0f}%;"
            f"background:{color}'></span></div></div>")


def _tabla_html(encabezados, filas, alin, alto_max=None):
    """Tabla HTML con el estilo del tablero. `alin`: 'l', 'r' o 'c' por columna; las celdas ya vienen formateadas."""
    cls = {"l": "", "r": "r", "c": "c"}
    th = "".join(f"<th class='{cls[a]}'>{h}</th>" for h, a in zip(encabezados, alin))
    tr = "".join("<tr>" + "".join(f"<td class='{cls[a]}'>{c}</td>" for c, a in zip(f, alin)) + "</tr>" for f in filas)
    estilo = f" style='max-height:{alto_max}px'" if alto_max else ""
    return f"<div class='mc-tabw'{estilo}><table class='mc-tab'><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>"


_BADGE_SITIO = {"Núcleo": (PAL["verde"], PAL["verde_fondo"]), "Sensible": (PAL["amarillo_osc"], PAL["amarillo_fondo"]),
                "Ocasional": (PAL["azul"], PAL["azul_fondo"]), "Nunca abierto": (PAL["tenue"], "#EEF1F5")}
_BADGE_MUN = {"Robustamente atendido": (PAL["verde"], PAL["verde_fondo"]), "Intermedio": (PAL["amarillo_osc"], PAL["amarillo_fondo"]),
              "Vulnerable": (PAL["coral"], PAL["coral_fondo"])}


def _estilo(ch, alto=300):
    """Misma línea visual para todos los gráficos."""
    return (ch.properties(height=alto, background=PAL["tarjeta"], padding={"left": 4, "right": 12, "top": 6, "bottom": 4})
            .configure(font=FUENTE)
            .configure_view(strokeWidth=0)
            .configure_axis(gridColor=PAL["rejilla"], gridWidth=1, domainColor="#C9D3DE", tickColor="#C9D3DE",
                            labelColor=PAL["tinta2"], titleColor=PAL["tinta2"], labelFontSize=11, titleFontSize=11.5,
                            titleFontWeight=600, titlePadding=10, labelPadding=5)
            .configure_legend(labelColor=PAL["tinta2"], titleColor=PAL["tinta2"], labelFontSize=11, titleFontSize=11,
                              titleFontWeight=600, symbolSize=80, orient="top", direction="horizontal", padding=2, labelLimit=180)
            .configure_text(font=FUENTE))


def _tema_claro(st):
    """Fuerza el tema claro de Streamlit (aunque el sistema operativo use modo oscuro) con la paleta de la app."""
    for k, v in {"theme.base": "light", "theme.primaryColor": PAL["turquesa"], "theme.backgroundColor": PAL["fondo"],
                 "theme.secondaryBackgroundColor": "#EEF2F6", "theme.textColor": PAL["tinta"]}.items():
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
        html(f"<div id='{nombre}' style='position:relative;top:-80px;height:0'></div>")

    def cab_tarjeta(ic, color, fondo, titulo, sub=""):
        html(f"<div class='mc-th'><div class='ic' style='background:{fondo}'>{icono(ic, color, 19)}</div><div><div class='t'>{titulo}</div>"
             + (f"<div class='s'>{sub}</div>" if sub else "") + "</div></div>")

    def seccion(titulo, sub=""):
        html(f"<div class='mc-seccion'><span class='t'>{titulo}</span><span class='linea'></span>"
             + (f"<span class='s'>{sub}</span>" if sub else "") + "</div>")

    def tarjeta_kpi(ic, color, fondo, etiqueta, valor, nota=""):
        return (f"<div class='mc-kpi' style='--acento:{color}'><div class='top'><div class='ic' style='background:{fondo}'>{icono(ic, color, 19)}</div>"
                f"<div class='lb'>{etiqueta}</div></div><div class='vl' title='{valor}'>{valor}</div>"
                + (f"<div class='nt'>{nota}</div>" if nota else "") + "</div>")

    def tarjeta_mini(ic, color, fondo, etiqueta, valor):
        return (f"<div class='mc-kpi mini' style='--acento:{color}'><div class='ic' style='background:{fondo}'>{icono(ic, color, 17)}</div>"
                f"<div style='min-width:0'><div class='lb'>{etiqueta}</div><div class='vl'>{valor}</div></div></div>")

    def grafico(ch, alto=300):
        st.altair_chart(_estilo(ch, alto), theme=None, **ANCHO)

    # ---------------- Barra lateral: marca, navegación, datos y configuración ----------------
    with st.sidebar:
        html(f"<div class='mc-marca'><div class='lg'>{icono('carpa', '#FFFFFF', 26)}</div>"
             "<div><div class='t'>Red de campamentos</div><div class='s'>Caso 2 · Terremoto en Colombia<br/>Robustez basada en datos</div></div></div>"
             f"<div class='mc-nav'><a class='activo' href='#robustez'>{icono('casa', PAL['azul'], 17)}Análisis de robustez</a>"
             f"<a href='#graficos'>{icono('barras', PAL['tinta2'], 17)}Distribución y sensibilidad</a>"
             f"<a href='#mapa'>{icono('mapa', PAL['tinta2'], 17)}Mapa de robustez</a>"
             f"<a href='#detalle'>{icono('info', PAL['tinta2'], 17)}Supuestos y detalle</a></div>")
        html(f"<div class='mc-lat'>{icono('capas', PAL['azul'], 15)}Datos del proyecto</div>")
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
        html(f"<div class='mc-chip-ok'>{icono('check', PAL['verde'], 16)}<div>Proyecto <code>{raiz.name}</code><br/>"
             f"{len(datos['dem'])} municipios · {len(datos['J'])} candidatos</div></div>")

        html(f"<div class='mc-lat'>{icono('ajustes', PAL['azul'], 15)}Parámetros de simulación</div>")
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

        html(f"<div class='mc-lat'>{icono('dispersion', PAL['azul'], 15)}Rangos de parámetros</div>")
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
    html(f"<div class='mc-cab'><div class='izq'><div class='logo'>{icono('carpa', '#FFFFFF', 36, 1.8)}</div><div class='txt'>"
         "<div class='kick'>Caso 2 · Terremoto en Colombia · 10-ago-2026</div>"
         "<h1>Monte Carlo · Robustez de la red de campamentos</h1>"
         "<div class='s1'>¿Sigue siendo buena la red recomendada si los supuestos del modelo cambian?</div>"
         "<div class='s2'>Cada simulación sortea la fracción f, el tamaño de hogar, el costo fijo c_f y el costo de kits, recalcula demanda, "
         "costos y presupuesto, y vuelve a resolver el MILP lexicográfico del notebook 02.</div>"
         f"<div class='mc-pildoras'><span class='mc-pildora' style='color:{PAL['turquesa_osc']};background:{PAL['turquesa_fondo']}'>"
         "Análisis de robustez, no predicción</span>"
         f"<span class='mc-pildora' style='color:{PAL['azul']};background:{PAL['azul_fondo']}'>No modifica los resultados oficiales</span>"
         f"<span class='mc-pildora' style='color:{PAL['verde']};background:{PAL['verde_fondo']}'>Optimalidad certificada en cada simulación</span>"
         "</div></div></div>"
         f"<div class='der'>{_PAISAJE}<div class='lema'>Colombia<br/>más resiliente<span class='bandera'></span></div></div></div>")

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
        filas = []
        for k, (lo, mo, hi, dist_) in rangos.items():
            t_ = PARAMS[k][6]
            col_d = (PAL["azul"], PAL["azul_fondo"]) if dist_ == "triangular" else (PAL["turquesa_osc"], PAL["turquesa_fondo"])
            filas.append([f"<span class='fuerte'>{PARAMS[k][0]}</span>", _fmt(lo, t_), _fmt(mo, t_) if dist_ == "triangular" else "—",
                          _fmt(hi, t_), _badge(dist_.capitalize(), *col_d), f"<span class='fuerte'>{_fmt(PARAMS[k][5], t_)}</span>"])
        html(_tabla_html(["Parámetro", "Mínimo", "Moda", "Máximo", "Distribución", "Modelo base"], filas, ["l", "r", "r", "r", "c", "r"]))
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
        st.write("")
        with st.container(**TARJETA):
            cab_tarjeta("ajustes", PAL["azul"], PAL["azul_fondo"], "Supuestos inciertos", "Rangos y distribuciones que se muestrean en cada simulación")
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

    # ---------------- Barra de contexto de la corrida ----------------
    html("<div class='mc-meta'>"
         f"<span class='it'>{icono('foco', PAL['azul'], 14)}Escenario <b>{mc['nivel']}</b></span>"
         f"<span class='it'>{icono('capas', PAL['azul'], 14)}Presupuesto <b>{'regla del enunciado' if mc['regla_B'] == 'enunciado' else 'fijo en COP'}</b></span>"
         f"<span class='it'>{icono('check', PAL['verde'], 14)}<b>{n_val} de {len(tabla)}</b> simulaciones válidas</span>"
         f"<span class='it'>{icono('ajustes', PAL['azul'], 14)}Semilla <b>{mc['semilla']}</b></span>"
         f"<span class='it'>{icono('reloj', PAL['azul'], 14)}<b>{mc['segundos']:.0f} s</b> de cálculo</span></div>")

    # ---------------- Indicadores (KPI) ----------------
    dif = 100 * (cob.median() - cob_ref)
    d_col, d_fondo = (PAL["verde"], PAL["verde_fondo"]) if dif >= 0 else (PAL["coral"], PAL["coral_fondo"])
    delta = (f"<span class='mc-delta' style='color:{d_col};background:{d_fondo}'>{'▲' if dif >= 0 else '▼'} {_dec(abs(dif))} pp</span>"
             f" frente a la referencia ({_fmt(cob_ref, 'pct')})")
    html("<div class='mc-kpis'>"
         + tarjeta_kpi("personas", PAL["turquesa"], PAL["turquesa_fondo"], "Cobertura mediana", _fmt(cob.median(), "pct"), delta)
         + tarjeta_kpi("baja", PAL["coral"], PAL["coral_fondo"], "P10 de cobertura", _fmt(cob.quantile(0.10), "pct"),
                       "Escenario pesimista: 10 % de los casos queda por debajo")
         + tarjeta_kpi("sube", PAL["verde"], PAL["verde_fondo"], "P90 de cobertura", _fmt(cob.quantile(0.90), "pct"),
                       "Escenario optimista: 90 % de los casos queda por debajo")
         + tarjeta_kpi("personas", PAL["azul"], PAL["azul_fondo"], "Personas atendidas (promedio)", _mil(validas.atendidos.mean()),
                       f"± {_mil(validas.atendidos.std())} entre simulaciones")
         + tarjeta_kpi("carpa", PAL["amarillo_osc"], PAL["amarillo_fondo"], "Campamentos abiertos (promedio)", _dec(validas.n_abiertos.mean()),
                       f"± {_dec(validas.n_abiertos.std())} · de {len(datos['J'])} candidatos")
         + tarjeta_kpi("trofeo", PAL["amarillo_osc"], PAL["amarillo_fondo"], "Campamento más robusto", top.municipio,
                       f"Se abre en el {_fmt(top.frecuencia_apertura, 'pct')} de las simulaciones")
         + "</div>")
    st.write("")
    html("<div class='mc-kpis mini'>"
         + tarjeta_mini("personas", PAL["turquesa"], PAL["turquesa_fondo"], "Cobertura promedio", _fmt(cob.mean(), "pct"))
         + tarjeta_mini("personas", PAL["azul"], PAL["azul_fondo"], "Personas atendidas P10 – P90",
                        f"{_mil(validas.atendidos.quantile(.1))} – {_mil(validas.atendidos.quantile(.9))}")
         + tarjeta_mini("capas", PAL["azul"], PAL["azul_fondo"], "Demanda promedio (personas)", _mil(validas.demanda.mean()))
         + tarjeta_mini("red", PAL["verde"], PAL["verde_fondo"], "Simulaciones con la misma red que la referencia",
                        _fmt((validas.red == red_base).mean(), "pct"))
         + "</div>")
    if (tabla.valida == False).any():   # noqa: E712
        st.warning(f"{(~tabla.valida).sum()} simulaciones descartadas (sin optimalidad certificada); ver tabla de resultados.")

    # ---------------- Hallazgos clave (solo datos ya calculados) ----------------
    red_top = validas.red.value_counts()
    n_vul = int((muni.clase == "Vulnerable").sum())
    n_rob = int((muni.clase == "Robustamente atendido").sum())
    sens_at = sensibilidad(tabla, "atendidos")
    p_top = sens_at.iloc[0]
    html("<div class='mc-hall'>"
         f"<div class='h'><div class='ic' style='background:{PAL['verde_fondo']}'>{icono('red', PAL['verde'], 17)}</div><div style='min-width:0'>"
         f"<div class='t'>Red más frecuente</div><div class='d'><b>{red_top.index[0]}</b> en el {_fmt(red_top.iloc[0] / n_val, 'pct')} de las simulaciones</div></div></div>"
         f"<div class='h'><div class='ic' style='background:{PAL['coral_fondo']}'>{icono('alerta', PAL['coral'], 17)}</div><div style='min-width:0'>"
         f"<div class='t'>Territorios</div><div class='d'><b style='color:{PAL['coral']}'>{n_vul} municipios vulnerables</b> y "
         f"<b style='color:{PAL['verde']}'>{n_rob} robustamente atendidos</b> de {len(muni)}</div></div></div>"
         f"<div class='h'><div class='ic' style='background:{PAL['azul_fondo']}'>{icono('bombilla', PAL['azul'], 17)}</div><div style='min-width:0'>"
         f"<div class='t'>Parámetro más influyente</div><div class='d'><b>{p_top.parametro}</b> sobre las personas atendidas "
         f"(ρ = {_dec(p_top.spearman, 2)})</div></div></div>"
         "</div>")

    # ---------------- Fila de gráficos: distribución · sensibilidad ----------------
    ancla("graficos")
    seccion("Distribución y sensibilidad", "Cómo varía el resultado y qué supuesto lo mueve")
    esc_camp = alt.Scale(range=["#9ED8D5", "#3FB8B3", "#0F8F8F", "#1D4E89", "#13345C", "#0B1F38"])
    g1, g3 = st.columns([1.25, 1])
    with g1:
        with st.container(**TARJETA):
            cab_tarjeta("barras", PAL["turquesa_osc"], PAL["turquesa_fondo"], "Distribución de la cobertura",
                        f"Porcentaje de la demanda atendida en cada una de las {n_val} simulaciones")
            stats_ = [("P10", cob.quantile(.1), PAL["coral"], PAL["coral_fondo"]), ("Mediana", cob.median(), PAL["azul"], PAL["azul_fondo"]),
                      ("P90", cob.quantile(.9), PAL["verde"], PAL["verde_fondo"]), ("Referencia", cob_ref, PAL["amarillo_osc"], PAL["amarillo_fondo"])]
            html("<div class='mc-stats'>" + "".join(f"<div class='c' style='background:{fo}'><div class='lb' style='color:{co}'>{n_}</div>"
                                                    f"<div class='vl'>{_fmt(v_, 'pct')}</div></div>" for n_, v_, co, fo in stats_) + "</div>")
            h = alt.Chart(validas.assign(cob=100 * validas.cobertura)).mark_bar(color=PAL["turquesa"], opacity=0.82, cornerRadiusTopLeft=3,
                                                                                cornerRadiusTopRight=3, binSpacing=2).encode(
                x=alt.X("cob:Q", bin=alt.Bin(maxbins=25), title="Cobertura de la demanda (%)"),
                y=alt.Y("count()", title="Simulaciones"),
                tooltip=[alt.Tooltip("cob:Q", bin=alt.Bin(maxbins=25), title="Cobertura (%)"), alt.Tooltip("count()", title="Simulaciones")])
            lineas = pd.DataFrame([dict(v=100 * v_, etq=n_) for n_, v_, _c, _f in stats_])
            r_ = alt.Chart(lineas).mark_rule(strokeWidth=2.2).encode(
                x="v:Q", color=alt.Color("etq:N", title=None, legend=alt.Legend(columns=4, symbolType="stroke", symbolStrokeWidth=3),
                                         scale=alt.Scale(domain=[s_[0] for s_ in stats_], range=[s_[2] for s_ in stats_])),
                strokeDash=alt.condition(alt.datum.etq == "Mediana", alt.value([1, 0]), alt.value([5, 3])),
                tooltip=[alt.Tooltip("etq:N", title="Línea"), alt.Tooltip("v:Q", format=".1f", title="Cobertura (%)")])
            grafico(h + r_, alto=255)
    with g3:
        with st.container(**TARJETA):
            cab_tarjeta("dispersion", PAL["azul"], PAL["azul_fondo"], "Sensibilidad de los parámetros",
                        "Correlación de rangos de Spearman (ρ) con la métrica elegida")
            met = st.radio("Métrica", ["Personas atendidas", "Cobertura"], horizontal=True, label_visibility="collapsed")
            col_met = "atendidos" if met == "Personas atendidas" else "cobertura"
            sens = sensibilidad(tabla, col_met)
            sens_g = sens.assign(signo=np.where(sens.spearman >= 0, "Sube la métrica", "Baja la métrica"),
                                 etq=[_dec(v, 2) for v in sens.spearman], pos=np.where(sens.spearman >= 0, sens.spearman + 0.04, sens.spearman - 0.04),
                                 alin=np.where(sens.spearman >= 0, "left", "right"))
            orden = list(sens.parametro)
            base_s = alt.Chart(sens_g).encode(y=alt.Y("parametro:N", sort=orden, title=None, axis=alt.Axis(labelLimit=230, labelFontSize=11.5)))
            tor = base_s.mark_bar(height={"band": 0.58}, cornerRadius=4).encode(
                x=alt.X("spearman:Q", title=f"ρ de Spearman con {met.lower()}", scale=alt.Scale(domain=[-1.15, 1.15]),
                        axis=alt.Axis(values=[-1, -0.5, 0, 0.5, 1])),
                color=alt.Color("signo:N", title=None, scale=alt.Scale(domain=["Sube la métrica", "Baja la métrica"],
                                                                       range=[PAL["azul"], PAL["coral"]])),
                tooltip=[alt.Tooltip("parametro:N", title="Parámetro"), alt.Tooltip("spearman:Q", format=".2f", title="ρ"),
                         alt.Tooltip("signo:N", title="Efecto")])
            txt_pos = base_s.transform_filter(alt.datum.spearman >= 0).mark_text(align="left", fontSize=11, fontWeight=700, color=PAL["tinta"]).encode(
                x="pos:Q", text="etq:N")
            txt_neg = base_s.transform_filter(alt.datum.spearman < 0).mark_text(align="right", fontSize=11, fontWeight=700, color=PAL["tinta"]).encode(
                x="pos:Q", text="etq:N")
            cero = alt.Chart(pd.DataFrame({"v": [0]})).mark_rule(color="#8C9AAB", strokeWidth=1.2).encode(x="v:Q")
            grafico(tor + txt_pos + txt_neg + cero, alto=228)
            st.caption("Con f y el factor de hogar la cobertura baja aunque las personas atendidas casi no cambien, porque crece la demanda.")

    # ---------------- Fila: apertura · vulnerables ----------------
    a_c, v_c = st.columns([1, 1.12])
    with a_c:
        with st.container(**TARJETA):
            cab_tarjeta("carpa", PAL["verde"], PAL["verde_fondo"], "Frecuencia de apertura de campamentos",
                        "Porcentaje de simulaciones en que se abre cada candidato")
            fa = sitios.assign(pct=100 * sitios.frecuencia_apertura).sort_values(["pct", "capacidad_K"], ascending=False)
            fa["etq"] = [f"{v:.0f} %" if v > 0 else "0 %" for v in fa.pct]
            base_b = alt.Chart(fa).encode(y=alt.Y("municipio:N", sort=list(fa.municipio), title=None, axis=alt.Axis(labelLimit=150, labelFontSize=11)))
            fondo_b = base_b.mark_bar(height={"band": 0.62}, cornerRadius=4, color="#EEF2F6").encode(x=alt.datum(100))
            barras = base_b.mark_bar(height={"band": 0.62}, cornerRadius=4).encode(
                x=alt.X("pct:Q", title="Frecuencia de apertura (%)", scale=alt.Scale(domain=[0, 114]),
                        axis=alt.Axis(values=[0, 20, 40, 60, 80, 100])),
                color=alt.Color("clase:N", title=None, legend=alt.Legend(columns=4, symbolType="square"),
                                scale=alt.Scale(domain=list(COLOR_CLASE_SITIO), range=[_hex(c) for c in COLOR_CLASE_SITIO.values()])),
                tooltip=[alt.Tooltip("municipio:N", title="Candidato"), alt.Tooltip("categoria:N", title="Categoría"),
                         alt.Tooltip("capacidad_K:Q", title="Capacidad", format=","), alt.Tooltip("pct:Q", format=".1f", title="% apertura"),
                         alt.Tooltip("clase:N", title="Clase")])
            textos = base_b.mark_text(align="left", dx=5, fontSize=10.5, fontWeight=600, color=PAL["tinta2"]).encode(x="pct:Q", text="etq:N")
            umbrales = alt.Chart(pd.DataFrame({"v": [20, 80], "t": ["20 %", "80 %"]}))
            reglas = umbrales.mark_rule(strokeDash=[4, 3], color="#8C9AAB").encode(x="v:Q")
            grafico(fondo_b + barras + textos + reglas, alto=max(320, 24 * len(fa)))
            st.caption("Núcleo ≥ 80 % · Sensible 20–80 % · Ocasional < 20 % · Nunca abierto 0 %. Líneas punteadas: umbrales de 20 % y 80 %.")
    with v_c:
        with st.container(**TARJETA):
            cab_tarjeta("alerta", PAL["coral"], PAL["coral_fondo"], "Municipios más vulnerables",
                        "Ordenados por menor cobertura mediana entre simulaciones")
            # cobertura de cada municipio en cada simulación (solo para mostrar mediana, P10 y P90 por municipio)
            ids = list(datos["dem"].index)
            cm = pd.DataFrame([[s[i][0] / s[i][1] if s[i][1] > 0 else 0.0 for i in ids] for s in res["atend_mun"]], columns=ids)
            vul = muni.assign(cob_med=cm.median().reindex(muni.index), cob_p10=cm.quantile(.1).reindex(muni.index),
                              cob_p90=cm.quantile(.9).reindex(muni.index))
            vul = vul.sort_values(["cob_med", "cobertura_media", "demanda_media"], ascending=[True, True, False])

            def nivel_riesgo(p):
                if p >= 0.8:
                    return "Muy alto", PAL["coral"], PAL["coral_fondo"]
                if p >= 0.5:
                    return "Alto", "#C9542F", "#FCE7DD"
                if p >= 0.2:
                    return "Medio", PAL["amarillo_osc"], PAL["amarillo_fondo"]
                return "Bajo", PAL["verde"], PAL["verde_fondo"]
            filas_v = []
            for r in vul.head(9).itertuples():
                etq_n, col_n, fon_n = nivel_riesgo(r.prob_sin_atencion)
                col_c = PAL["coral"] if r.cob_med < 0.2 else (PAL["tinta"] if r.cob_med < 0.8 else PAL["verde"])
                filas_v.append([f"<span class='fuerte nw'>{r.municipio}</span><span class='sub'>{r.departamento}</span>",
                                _mil(r.demanda_media),
                                f"<span style='color:{col_c};font-weight:700'>{_fmt(r.cob_med, 'pct')}</span>",
                                f"<span style='color:{PAL['tinta2']}'>{_fmt(r.cob_p10, 'pct')} – {_fmt(r.cob_p90, 'pct')}</span>",
                                _badge(etq_n, col_n, fon_n)])
            html(_tabla_html(["Municipio", "Demanda", "Cob. mediana", "P10 – P90", "Riesgo"], filas_v,
                             ["l", "r", "r", "r", "c"], alto_max=470))
            st.caption("Riesgo = probabilidad de quedar sin atención: muy alto ≥ 80 %, alto 50–80 %, medio 20–50 %, bajo < 20 %. "
                       "Demanda = promedio entre simulaciones.")
            with st.expander("Ver todos los municipios"):
                filas_m = [[f"<span class='fuerte nw'>{r.municipio}</span><span class='sub'>{r.departamento}</span>", _mil(r.demanda_media),
                            _barra_pct(r.cobertura_media, PAL["turquesa"]), _fmt(r.prob_atencion, "pct"),
                            _fmt(r.prob_sin_atencion, "pct"), _badge(r.clase, *_BADGE_MUN.get(r.clase, (PAL["tenue"], "#EEF1F5")))]
                           for r in muni.sort_values("prob_atencion").itertuples()]
                html(_tabla_html(["Municipio", "Demanda", "Cobertura media", "P(atención)", "P(sin atención)", "Clase"],
                                 filas_m, ["l", "r", "r", "r", "r", "c"], alto_max=460))

    # ---------------- Mapa ----------------
    ancla("mapa")
    seccion("Mapa de robustez", "Municipios, campamentos candidatos y conexiones más usadas")
    deptos = sorted(set(datos["dem"].departamento) | set(datos["cand"].departamento))
    with st.container(**TARJETA):
        cab_tarjeta("mapa", PAL["turquesa_osc"], PAL["turquesa_fondo"], "Red de atención en las simulaciones",
                    "Coordenadas: cabeceras DIVIPOLA del proyecto · las líneas son conexiones directas indicativas, no rutas viales")
        f1, f2, f3, f4, f5 = st.columns([1.35, 1.05, 0.8, 1.25, 0.9])
        var_color = f1.selectbox("Color de municipios", ["Probabilidad de atención", "Cobertura promedio", "Clase de robustez",
                                                         "Demanda promedio"])
        foco = f2.selectbox("Campamento", ["Todos"] + sorted(sitios.municipio))
        fondo_map = f3.selectbox("Fondo", ["Claro", "Calles"])
        umbral = f4.select_slider("Frecuencia mínima de conexión", options=[0.10, 0.20, 0.40, 0.60, 0.80], value=0.20,
                                  format_func=lambda v: f"{int(v * 100)} %")
        with f5:
            html("<div style='height:1.85rem'></div>")
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
        n_arcos = 0
        if ver_arc and len(arcos):
            a = arcos[arcos.frecuencia >= umbral - 1e-9].copy()
            a = a[a.id_demanda.map(datos["dem"].departamento).isin(sel_dep) | a.id_sitio.map(datos["cand"].departamento).isin(sel_dep)]
            a = a[a.id_sitio.isin(s_map.index)]
            if foco != "Todos":
                a = a[a.id_sitio.map(nom) == foco]
            n_arcos = len(a)
            if len(a):
                a["o_lon"] = a.id_demanda.map(datos["dem"].lon)
                a["o_lat"] = a.id_demanda.map(datos["dem"].lat)
                a["d_lon"] = a.id_sitio.map(datos["cand"].lon)
                a["d_lat"] = a.id_sitio.map(datos["cand"].lat)
                a["ancho"] = 1.5 + 6 * a.frecuencia
                a["color"] = [[15, 143, 143, int(70 + 150 * fq)] for fq in a.frecuencia]
                a["tooltip"] = [f"<b>{nom[i]} → {nom[j]}</b><br/>Frecuencia de uso: {100 * fq:.0f} %<br/>"
                                f"Personas cuando se usa (media): {fl:,.0f}<br/>Distancia por carretera: {km:,.1f} km".replace(",", ".")
                                for i, j, fq, fl, km in zip(a.id_demanda, a.id_sitio, a.frecuencia, a.flujo_medio_si_se_usa, a.km)]
                capas.append(pdk.Layer("LineLayer", a.sort_values("frecuencia"), get_source_position=["o_lon", "o_lat"],
                                       get_target_position=["d_lon", "d_lat"], get_color="color", get_width="ancho",
                                       width_units="'pixels'", width_scale=1, width_min_pixels=1, width_max_pixels=8, pickable=True))
        if ver_dem and len(mu):
            vmax = float(mu.demanda_media.max() or 1)
            if var_color == "Probabilidad de atención":
                mu["color"] = [_escala_divergente(v) + [235] for v in mu.prob_atencion]
            elif var_color == "Cobertura promedio":
                mu["color"] = [_escala_divergente(v) + [235] for v in mu.cobertura_media]
            elif var_color == "Clase de robustez":
                mu["color"] = [COLOR_CLASE_MUN.get(c, [150, 150, 150]) + [235] for c in mu.clase]
            else:
                mu["color"] = [_escala_secuencial(v, vmax) + [235] for v in mu.demanda_media]
            mu["radio"] = 2500 + 9000 * np.sqrt(mu.demanda_media / vmax)
            mu["tooltip"] = [f"<b>{r.municipio}</b> ({r.departamento})<br/>Demanda promedio: {r.demanda_media:,.0f}<br/>"
                             f"Atendidos promedio: {r.atendidos_media:,.0f}<br/>Cobertura promedio: {100 * r.cobertura_media:.1f} %<br/>"
                             f"Probabilidad de recibir atención: {100 * r.prob_atencion:.0f} %<br/>"
                             f"Probabilidad de quedar sin atención: {100 * r.prob_sin_atencion:.0f} %<br/>Clase: {r.clase}".replace(",", ".")
                             for r in mu.itertuples()]
            capas.append(pdk.Layer("ScatterplotLayer", mu, get_position=["lon", "lat"], get_fill_color="color", get_radius="radio",
                                   stroked=True, get_line_color=[255, 255, 255, 255], line_width_min_pixels=1.8, pickable=True))
        if ver_cand and len(s_map):
            s_map["color"] = [COLOR_CLASE_SITIO[c] + [250] for c in s_map.clase]
            s_map["tooltip"] = [f"<b>Campamento: {r.municipio}</b> ({r.departamento})<br/>Categoría: {r.categoria} · capacidad {int(r.capacidad_K):,}<br/>"
                                f"Frecuencia de apertura: {100 * r.frecuencia_apertura:.0f} %<br/>Ocupación media: {r.ocupacion_media:,.0f} personas<br/>"
                                f"Clasificación: <b>{r.clase}</b>".replace(",", ".") for r in s_map.itertuples()]
            # triángulo = campamento (carpa), con contorno azul profundo para distinguirlo de los municipios (círculos)
            lado = {3000: 0.07, 1000: 0.058, 500: 0.048}
            s_map["poligono"] = [[[lo - l, la - 0.8 * l], [lo + l, la - 0.8 * l], [lo, la + 1.05 * l]]
                                 for lo, la, l in zip(s_map.lon, s_map.lat, [lado.get(int(k), 0.048) for k in s_map.capacidad_K])]
            capas.append(pdk.Layer("PolygonLayer", s_map, get_polygon="poligono", get_fill_color="color",
                                   get_line_color=[19, 38, 58, 255], line_width_min_pixels=1.6, stroked=True, pickable=True))
        if ver_etiquetas:
            etq = []
            if ver_cand and len(s_map):
                etq += [dict(lon=r.lon, lat=r.lat + 0.1, texto=r.municipio, tam=13) for r in s_map[s_map.clase.isin(["Núcleo", "Sensible"])].itertuples()]
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
                                       get_color=[19, 38, 58, 255], get_alignment_baseline="'center'", font_weight=700,
                                       font_family="'Inter, Helvetica, Arial, sans-serif'",
                                       character_set="'" + "".join(sorted(set(c for c in "".join(chr(k) for k in range(32, 127)) + "".join(e["texto"] for e in etq)
                                                                    if c.isalnum() or c in " .-"))) + "'",
                                       background=True, get_background_color=[255, 255, 255, 235], background_padding=[5, 2],
                                       get_border_color=[223, 230, 238, 255], get_border_width=1))

        # encuadre sobre lo que se está mostrando (si no hay nada visible, sobre todos los nodos del proyecto)
        vis_lat = ([mu.lat] if ver_dem and len(mu) else []) + ([s_map.lat] if ver_cand and len(s_map) else [])
        vis_lon = ([mu.lon] if ver_dem and len(mu) else []) + ([s_map.lon] if ver_cand and len(s_map) else [])
        lats = pd.concat(vis_lat) if vis_lat else pd.concat([datos["dem"].lat, datos["cand"].lat])
        lons = pd.concat(vis_lon) if vis_lon else pd.concat([datos["dem"].lon, datos["cand"].lon])
        # encuadre automático de todos los nodos (aprox. Web Mercator), con 20 % de margen
        dlon = max(float(lons.max() - lons.min()), 0.3)
        dlat = max(float(lats.max() - lats.min()), 0.3)
        zoom0 = float(np.clip(min(np.log2(820 * 360 / (512 * dlon * 1.2)), np.log2(580 * 360 / (512 * dlat * 1.2))), 5, 10))
        vista = pdk.ViewState(latitude=float((lats.max() + lats.min()) / 2), longitude=float((lons.max() + lons.min()) / 2), zoom=zoom0)
        deck = pdk.Deck(layers=capas, initial_view_state=vista,
                        map_provider="carto", map_style="light" if fondo_map == "Claro" else "road",
                        tooltip={"html": "{tooltip}", "style": {"backgroundColor": "white", "color": PAL["tinta"], "fontSize": "12px",
                                                                "border": f"1px solid {PAL['borde']}", "borderRadius": "10px", "padding": "8px 10px",
                                                                "boxShadow": "0 4px 14px rgba(19,38,58,0.12)", "fontFamily": FUENTE}})
        c_map, c_ley = st.columns([3.4, 1])
        with c_map:
            st.pydeck_chart(deck, height=580)
        with c_ley:
            def muestra(rgb, forma="circulo"):
                if forma == "triangulo":
                    return (f"<svg class='sw' viewBox='0 0 12 12' width='13' height='13'><polygon points='6,1 11.5,11 0.5,11' "
                            f"fill='{_hex(rgb)}' stroke='#13263A' stroke-width='0.9'/></svg>")
                return f"<span class='sw' style='background:{_hex(rgb)};border-radius:50%;box-shadow:0 0 0 1.5px #fff, 0 0 0 2.4px #DFE6EE'></span>"
            ley = "<div class='mc-leyenda'><div class='g'>Municipios</div>"
            if var_color == "Clase de robustez":
                ley += "".join(f"<div class='fila'>{muestra(c)}<div>{k}</div></div>" for k, c in COLOR_CLASE_MUN.items())
                ley += "<div class='n'>Clase según ≥ 80 % de las simulaciones · tamaño = demanda</div>"
            elif var_color == "Demanda promedio":
                ley += ("<div class='n'>Tamaño y color = demanda promedio</div><div class='mc-grad' style='background:linear-gradient(90deg,"
                        f"{_hex([198, 232, 230])},{_hex([29, 78, 137])})'></div><div class='mc-grad-et'><span>baja</span><span>alta</span></div>")
            else:
                ley += (f"<div class='n'>{var_color} · tamaño = demanda</div><div class='mc-grad' style='background:linear-gradient(90deg,"
                        f"{_hex(_escala_divergente(0))},{_hex(_escala_divergente(.5))},{_hex(_escala_divergente(1))})'></div>"
                        "<div class='mc-grad-et'><span>0 %</span><span>50 %</span><span>100 %</span></div>")
            ley += "<div class='sep'></div><div class='g'>Campamentos</div><div class='n'>Triángulos · tamaño = capacidad</div>"
            ley += "".join(f"<div class='fila'>{muestra(c, 'triangulo')}<div>{k}</div></div>" for k, c in COLOR_CLASE_SITIO.items())
            ley += (f"<div class='sep'></div><div class='g'>Conexiones</div><div class='fila'><span class='sw' style='height:4px;width:22px;"
                    f"border-radius:2px;background:{PAL['turquesa']}'></span><div>Demanda → campamento</div></div>"
                    f"<div class='n'>Grosor y opacidad = frecuencia de uso · se muestran las de frecuencia ≥ {int(umbral * 100)} % "
                    f"({n_arcos} conexiones)</div></div>")
            html(ley)
        st.caption("Robustamente atendido: recibe atención en ≥ 80 % de las simulaciones. Vulnerable: queda sin atención en ≥ 80 %. "
                   "Pase el cursor sobre el mapa para ver el detalle de cada elemento.")

    # ---------------- Detalle: supuestos, comparación, redes, dispersión, tablas ----------------
    ancla("detalle")
    seccion("Supuestos y detalle de la simulación", "Rangos usados, referencia, redes frecuentes y tablas completas")
    with st.container(**TARJETA):
        cab_tarjeta("ajustes", PAL["azul"], PAL["azul_fondo"], "Supuestos inciertos", "Rangos y distribuciones que se muestrean en cada simulación")
        tabla_rangos()
    with st.container(**TARJETA):
        cab_tarjeta("check", PAL["verde"], PAL["verde_fondo"], "Comparación con el escenario de referencia",
                    "Mismos parámetros del modelo base resueltos con este código")
        filas_cmp = [("Personas atendidas", ref.get("atendidos"), validas.atendidos.mean(), validas.atendidos.quantile(.1),
                      validas.atendidos.quantile(.9), _mil),
                     ("Cobertura (%)", 100 * ref.get("atendidos", 0) / max(ref.get("demanda", 1), 1), 100 * cob.mean(),
                      100 * cob.quantile(.1), 100 * cob.quantile(.9), lambda v: _dec(v)),
                     ("Demanda", ref.get("demanda"), validas.demanda.mean(), validas.demanda.quantile(.1), validas.demanda.quantile(.9), _mil),
                     ("Campamentos abiertos", len(ref.get("abiertos", [])), validas.n_abiertos.mean(), validas.n_abiertos.quantile(.1),
                      validas.n_abiertos.quantile(.9), lambda v: _dec(v))]
        html(_tabla_html(["Indicador", "Referencia", "Monte Carlo (media)", "P10", "P90"],
                         [[f"<span class='fuerte'>{n_}</span>", f"<span class='fuerte' style='color:{PAL['azul']}'>{f_(r_)}</span>",
                           f"<span class='fuerte'>{f_(m_)}</span>", f_(p1_), f_(p9_)]
                          for n_, r_, m_, p1_, p9_, f_ in filas_cmp], ["l", "r", "r", "r", "r"]))
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

    with st.container(**TARJETA):
        cab_tarjeta("red", PAL["turquesa_osc"], PAL["turquesa_fondo"], "Redes más frecuentes", "Combinaciones de campamentos abiertos")
        redes = validas.red.value_counts().rename_axis("Red de campamentos").reset_index(name="Simulaciones")
        redes["%"] = (100 * redes.Simulaciones / n_val).round(1)
        redes["Atendidos (media)"] = [validas.loc[validas.red == r, "atendidos"].mean().round(0) for r in redes["Red de campamentos"]]
        filas_r = [[f"<span class='fuerte'>{r['Red de campamentos']}</span>" + (" " + _badge("Referencia", PAL["azul"], PAL["azul_fondo"])
                                                                                if r["Red de campamentos"] == red_base else ""),
                    _mil(r["Simulaciones"]), _barra_pct(r["%"] / 100, PAL["turquesa"]), _mil(r["Atendidos (media)"])]
                   for _, r in redes.head(8).iterrows()]
        html(_tabla_html(["Red de campamentos", "Simulaciones", "% del total", "Atendidos (media)"], filas_r, ["l", "r", "r", "r"]))
    e2, p1 = st.columns([1, 1])
    with e2:
        with st.container(**TARJETA):
            cab_tarjeta("personas", PAL["azul"], PAL["azul_fondo"], "Atendidos frente a demanda", "Cada punto es una simulación")
            sc = alt.Chart(validas).mark_circle(size=60, opacity=0.85, stroke="white", strokeWidth=1).encode(
                x=alt.X("demanda:Q", title="Demanda de la simulación (personas)"), y=alt.Y("atendidos:Q", title="Personas atendidas"),
                color=alt.Color("n_abiertos:O", title="Campamentos abiertos", scale=esc_camp),
                tooltip=[alt.Tooltip("sim:Q", title="Simulación"), alt.Tooltip("demanda:Q", format=",.0f", title="Demanda"),
                         alt.Tooltip("atendidos:Q", format=",.0f", title="Atendidos"), alt.Tooltip("f:Q", format=".3f"),
                         alt.Tooltip("factor_hogar:Q", format=".2f", title="Factor hogar"), alt.Tooltip("c_f:Q", format=",.0f"),
                         alt.Tooltip("v_kit:Q", format=",.0f", title="v"), alt.Tooltip("red:N", title="Red")])
            grafico(sc, alto=250)
            st.caption("Si los puntos forman una línea horizontal, el presupuesto (no la demanda) fija cuántas personas se atienden.")

    with p1:
        with st.container(**TARJETA):
            cab_tarjeta("dispersion", PAL["azul"], PAL["azul_fondo"], "Parámetro frente a la métrica", f"Métrica: {met.lower()}")
            p_sel = st.selectbox("Parámetro para el diagrama de dispersión", list(PARAMS), format_func=lambda k: PARAMS[k][0])
            disp = alt.Chart(validas).mark_circle(size=55, opacity=0.85, stroke="white", strokeWidth=1).encode(
                x=alt.X(f"{p_sel}:Q", title=PARAMS[p_sel][0], scale=alt.Scale(zero=False)),
                y=alt.Y(f"{col_met}:Q", title=met, scale=alt.Scale(zero=False)),
                color=alt.Color("n_abiertos:O", title="Campamentos abiertos", scale=esc_camp),
                tooltip=[alt.Tooltip("sim:Q", title="Simulación"), alt.Tooltip(f"{p_sel}:Q", format=",.3f", title=PARAMS[p_sel][0]),
                         alt.Tooltip(f"{col_met}:Q", format=",.3f", title=met), alt.Tooltip("red:N", title="Red")])
            grafico(disp, alto=235)
    with st.container(**TARJETA):
        cab_tarjeta("tabla", PAL["azul"], PAL["azul_fondo"], "Coeficientes de sensibilidad", f"Métrica: {met.lower()} · tercios del parámetro")
        es_cob = col_met == "cobertura"
        fm = (lambda v: _fmt(v, "pct")) if es_cob else _mil
        fd = (lambda v: ("+" if v >= 0 else "−") + _dec(abs(100 * v)) + " pp") if es_cob else (lambda v: ("+" if v >= 0 else "−") + _mil(abs(v)))
        filas_s = [[f"<span class='fuerte'>{r.parametro}</span>",
                    _badge(_dec(r.spearman, 2), *((PAL["azul"], PAL["azul_fondo"]) if r.spearman >= 0 else (PAL["coral"], PAL["coral_fondo"]))),
                    fm(r.media_tercio_bajo), fm(r.media_tercio_alto),
                    f"<span style='font-weight:700;color:{PAL['azul'] if r.diferencia >= 0 else PAL['coral']}'>{fd(r.diferencia)}</span>"]
                   for r in sens.itertuples()]
        html(_tabla_html(["Parámetro", "<span style='text-transform:none'>ρ</span> de Spearman", "Media (tercio bajo)", "Media (tercio alto)", "Diferencia"], filas_s, ["l", "c", "r", "r", "r"]))
        st.caption("Media de la métrica cuando el parámetro está en su tercio más bajo y en su tercio más alto.")

    with st.container(**TARJETA):
        cab_tarjeta("carpa", PAL["verde"], PAL["verde_fondo"], "Robustez de cada campamento", "Frecuencia de apertura y ocupación media")
        filas_c = [[f"<span class='fuerte'>{r.municipio}</span>", r.departamento, r.categoria, _mil(r.capacidad_K),
                    _barra_pct(r.frecuencia_apertura, _hex(COLOR_CLASE_SITIO.get(r.clase, [150, 150, 150]))), _mil(r.ocupacion_media),
                    _badge(r.clase, *_BADGE_SITIO.get(r.clase, (PAL["tenue"], "#EEF1F5")))]
                   for r in sitios.sort_values(["frecuencia_apertura", "capacidad_K"], ascending=False).itertuples()]
        html(_tabla_html(["Campamento", "Departamento", "Categoría", "Capacidad", "Frecuencia de apertura", "Ocupación media", "Clase"],
                         filas_c, ["l", "l", "l", "r", "r", "r", "c"], alto_max=440))

    with st.expander("Convergencia (¿son suficientes las simulaciones?)"):
        cv = validas[["sim", "cobertura"]].copy()
        cv["media"] = cv.cobertura.expanding().mean() * 100
        cv["ee"] = cv.cobertura.expanding().std().fillna(0) / np.sqrt(np.arange(1, len(cv) + 1)) * 100
        cv["lo"], cv["hi"] = cv.media - 1.96 * cv.ee, cv.media + 1.96 * cv.ee
        banda = alt.Chart(cv).mark_area(opacity=0.55, color=PAL["turquesa_fondo"]).encode(x=alt.X("sim:Q", title="Simulación"), y="lo:Q", y2="hi:Q")
        linea = alt.Chart(cv).mark_line(color=PAL["azul"], strokeWidth=2.4).encode(
            x="sim:Q", y=alt.Y("media:Q", title="Cobertura media acumulada (%)"),
            tooltip=[alt.Tooltip("sim:Q", title="Simulación"), alt.Tooltip("media:Q", format=".2f", title="Media (%)")])
        grafico(banda + linea, alto=240)
        st.caption(f"Intervalo de 95 % de la media al final: ±{_dec(1.96 * cob.std() / np.sqrt(n_val) * 100, 2)} puntos porcentuales.")

    # ---------------- Datos y descargas (no se escribe nada en el proyecto) ----------------
    with st.expander("Resultados por simulación y descargas"):
        cc = st.column_config
        st.dataframe(tabla.drop(columns=[c for c in tabla.columns if c.startswith("y_")]), hide_index=True, height=360, **ANCHO,
                     column_config={"sim": cc.NumberColumn("Sim.", format="%d"), "f": cc.NumberColumn("f", format="%.3f"),
                                    "factor_hogar": cc.NumberColumn("Factor hogar", format="%.2f"),
                                    "c_f": cc.NumberColumn("c_f (COP)", format="$%.0f"), "v_kit": cc.NumberColumn("v (COP)", format="$%.0f"),
                                    "demanda": cc.NumberColumn("Demanda", format="%d"), "presupuesto": cc.NumberColumn("Presupuesto (COP)", format="$%.0f"),
                                    "valida": cc.CheckboxColumn("Válida"), "estado": cc.TextColumn("Estado"),
                                    "segundos": cc.NumberColumn("Segundos", format="%.2f"), "atendidos": cc.NumberColumn("Atendidos", format="%d"),
                                    "cobertura": cc.ProgressColumn("Cobertura", format="%.3f", min_value=0.0, max_value=1.0),
                                    "n_abiertos": cc.NumberColumn("Campamentos", format="%d"), "red": cc.TextColumn("Red", width="large"),
                                    "costo_total": cc.NumberColumn("Costo total (COP)", format="$%.0f"),
                                    "uso_presupuesto": cc.NumberColumn("Uso del presupuesto", format="%.3f")})
        b1, b2, _b3 = st.columns([1, 1, 2])
        b1.download_button("⬇ Simulaciones (CSV)", tabla.to_csv(index=False).encode("utf-8"), "montecarlo_simulaciones.csv", "text/csv", **ANCHO)
        b2.download_button("⬇ Frecuencia de arcos (CSV)", arcos.assign(origen=arcos.id_demanda.map(nom), sitio=arcos.id_sitio.map(nom))
                           .to_csv(index=False).encode("utf-8"), "montecarlo_arcos.csv", "text/csv", **ANCHO)
        st.caption("Las descargas se generan en memoria; la app no escribe archivos en la carpeta del proyecto.")


if __name__ == "__main__":
    main()
