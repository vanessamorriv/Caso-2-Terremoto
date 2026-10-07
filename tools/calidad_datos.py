"""Módulo de calidad de datos del Caso 2 (terremoto en Colombia).

Reúne en UNA tabla las pruebas sobre los datos de entrada del modelo (demanda, candidatos, parámetros, coordenadas,
distancias y fuentes). Cada prueba devuelve:

    PASS     el dato cumple la regla.
    WARNING  el dato es utilizable, pero tiene una debilidad conocida que debe declararse (no detiene nada).
    FAIL     el dato rompe un requisito del enunciado o una regla de construcción: el modelo no debe correrse.

Objetivo del proyecto: 0 FAIL. Los WARNING quedan documentados en la hoja `Calidad_datos` del Excel y en
`results/tablas/calidad_datos.csv`.

Solo lee archivos (data/raw y data/processed); no depende del solver ni de la hora de ejecución, así que el notebook 01
(que la genera), el notebook 02 (que la exige antes de optimizar) y tools/verificar_proyecto.py (que la recalcula y la
compara con el CSV) obtienen exactamente la misma tabla.

Uso:
    from calidad_datos import evaluar, resumen
    tabla = evaluar(ROOT)        # ROOT = raíz del repositorio
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

DEPARTAMENTOS = {"17": "Caldas", "63": "Quindío", "66": "Risaralda", "76": "Valle del Cauca"}
D_MAX = 180
BBOX = dict(lat=(1.5, 7.0), lon=(-78.5, -74.0))
COLUMNAS = ["id", "area", "prueba", "nivel_si_no_cumple", "resultado", "detalle"]


def _redondear(v):
    """Redondeo 'mitad hacia arriba', igual que REDONDEAR de Excel."""
    return int(math.floor(v + 0.5))


def _haversine(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * np.arcsin(np.sqrt(a))


def _es(x, d=0):
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def evaluar(root):
    """Ejecuta todas las pruebas y devuelve un DataFrame con las columnas de COLUMNAS (orden fijo)."""
    root = Path(root)
    raw, proc = root / "data" / "raw", root / "data" / "processed"
    dem = pd.read_csv(proc / "demanda.csv", dtype={"divipola": str})
    cand = pd.read_csv(proc / "candidatos.csv", dtype={"divipola": str})
    dist = pd.read_csv(proc / "distancias_km.csv", index_col=0)
    dosrm = pd.read_csv(proc / "distancias_km_osrm.csv", index_col=0)
    par = pd.read_csv(proc / "parametros.csv").set_index("ID").Valor.astype(float)
    meta = json.load(open(proc / "metadatos_instancia.json", encoding="utf-8"))
    gm = pd.read_csv(raw / "google_maps" / "verificacion_google_maps.csv")
    gm2 = pd.read_csv(raw / "google_maps" / "verificacion_google_maps_140_160km.csv")
    ctrl = pd.read_csv(proc / "control_poblacion_DANE.csv", dtype={"divipola": str})
    alb = pd.read_csv(proc / "tasa_albergue_observada.csv")
    J = cand[cand.rol == "Candidato"]
    filas = []

    def prueba(id_, area, nombre, ok, detalle, nivel="FAIL"):
        """ok=True → PASS; ok=False → `nivel` (FAIL para requisitos, WARNING para debilidades declaradas)."""
        filas.append((id_, area, nombre, nivel, "PASS" if ok else nivel, detalle))

    # ---------------------------------------------------------------- Demanda
    cols_d = ["divipola", "municipio", "departamento", "pob_DANE_2026", "NH_RUD", "familias_RUD", "personas_RUD", "d_f10"]
    nulos = int(dem[cols_d].isna().sum().sum())
    prueba("D01", "Demanda", "Columnas clave completas", nulos == 0, f"{nulos} valores vacíos en {len(cols_d)} columnas clave")
    prueba("D02", "Demanda", "≥ 20 municipios, con Cali y Pereira (enunciado)",
           len(dem) >= 20 and {"Cali", "Pereira"} <= set(dem.municipio), f"{len(dem)} municipios")
    dep_ok = dem.divipola.str.len().eq(5).all() and dem.divipola.is_unique and \
        (dem.divipola.str[:2].map(DEPARTAMENTOS) == dem.departamento).all()
    prueba("D03", "Demanda", "DIVIPOLA único, de 5 dígitos y coherente con el departamento", dep_ok,
           f"departamentos: {', '.join(sorted(dem.departamento.unique()))}")
    prueba("D04", "Demanda", "Solo Valle del Cauca y Eje Cafetero (enunciado)", set(dem.departamento) <= set(DEPARTAMENTOS.values()),
           f"{dem.departamento.nunique()} departamentos")
    prueba("D05", "Demanda", "Filtro S1: NH ≥ 400 en todos los municipios", (dem.NH_RUD >= par["P15"]).all(),
           f"NH mínimo {_es(dem.NH_RUD.min())}")
    h = dem.personas_RUD / dem.familias_RUD
    d_calc = [_redondear(n * hh * par["P20"]) for n, hh in zip(dem.NH_RUD, h)]
    prueba("D06", "Demanda", "d_i = round(NH · h · f) recalculado coincide", list(dem.d_f10) == d_calc and (dem.d_f10 > 0).all(),
           f"demanda base {_es(dem.d_f10.sum())} personas con f = {_es(100 * par['P20'])} %")
    pob_ok = ctrl.coincide_PPED.all()
    prueba("D07", "Demanda", "Población 2026 = DANE PPED (demanda y candidatos)", bool(pob_ok),
           f"{int(ctrl.coincide_PPED.sum())}/{len(ctrl)} municipios coinciden")
    fuera = dem[(h < 1.5) | (h > 5.0)]
    prueba("D08", "Demanda", "Tamaño de hogar RUD entre 1,5 y 5 personas", fuera.empty,
           f"rango {_es(h.min(), 2)}–{_es(h.max(), 2)}" + (f"; fuera: {', '.join(fuera.municipio)}" if len(fuera) else ""), "WARNING")
    ratio = dem.familias_RUD / dem.NH_RUD
    altos = dem[ratio > 8].assign(r=ratio[ratio > 8]).sort_values("r", ascending=False)
    prueba("D09", "Demanda", "Familias registradas por vivienda no habitable ≤ 8", altos.empty,
           "una familia por vivienda puede subestimar la demanda en: "
           + ", ".join(f"{r.municipio} ({_es(r.r, 1)})" for r in altos.itertuples()) if len(altos) else f"máximo {_es(ratio.max(), 1)}",
           "WARNING")
    reg_alto = dem[dem.pct_registrado > 50]
    prueba("D10", "Demanda", "Personas registradas en el RUD ≤ 50 % de la población", reg_alto.empty,
           ", ".join(f"{r.municipio} {_es(r.pct_registrado, 1)} %" for r in reg_alto.itertuples()) or "máximo "
           + _es(dem.pct_registrado.max(), 1) + " %", "WARNING")
    debiles = dem[dem.calidad_dato_RUD != "F"]
    prueba("D11", "Demanda", "Calidad del dato RUD = F (RUD + reporte territorial)", debiles.empty,
           f"{len(debiles)} municipios con dato parcial (P) o solo RUD (R): {', '.join(debiles.municipio)}", "WARNING")

    # ---------------------------------------------------------------- Candidatos
    prueba("C01", "Candidatos", "≥ 15 candidatos (enunciado)", len(J) >= 15, f"{len(J)} candidatos + {int((cand.rol == 'Reserva').sum())} reserva")
    prueba("C02", "Candidatos", "Ningún candidato es un municipio de demanda", not set(cand.divipola) & set(dem.divipola),
           "intersección vacía")
    cap = {"Grande": par["P08"], "Intermedia": par["P09"], "Pequeña": par["P10"]}
    phi = {"Grande": par["P05"], "Intermedia": par["P06"], "Pequeña": par["P07"]}
    cat = np.where(cand.pob_DANE_2026 >= par["P11"], "Grande", np.where(cand.pob_DANE_2026 >= par["P12"], "Intermedia", "Pequeña"))
    prueba("C03", "Candidatos", "Categoría por población y capacidad 3.000 / 1.000 / 500 (enunciado)",
           (cand.categoria == cat).all() and (cand.capacidad_K == cand.categoria.map(cap)).all(),
           f"{int(((cand.categoria == cat) & (cand.capacidad_K == cand.categoria.map(cap))).sum())}/{len(cand)} sitios coherentes (17 candidatos + reserva)")
    f_calc = cand.capacidad_K * par["P01"] * par["P02"] * cand.categoria.map(phi)
    prueba("C04", "Candidatos", "F_j = K_j · c_f · T · φ recalculado coincide", np.allclose(f_calc, cand.costo_fijo_fj),
           f"F = {', '.join(_es(v / 1e6) + ' M' for v in sorted(cand.costo_fijo_fj.unique(), reverse=True))}")
    s_ok = ((J.NH_RUD < par["P13"]) & (J.pct_registrado / 100 < par["P14"])).all()
    prueba("C05", "Candidatos", "Filtros S2 (NH < 250) y S7 (< 5 % registrado)", bool(s_ok),
           f"NH máximo {_es(J.NH_RUD.max())} ({J.loc[J.NH_RUD.idxmax(), 'municipio']}); La Tebaida es reserva por S7")
    peq = J[J.categoria == "Pequeña"]
    prueba("C06", "Candidatos", "Solo ciudades intermedias o grandes (lectura literal del enunciado)", peq.empty,
           f"{len(peq)} candidatos pequeños: decisión adoptada (sin ellos solo hay {len(J) - len(peq)} elegibles y se exigen 15)", "WARNING")
    cortes = [par["P11"], par["P12"]]
    cerca = J[[min(abs(p - c) / c for c in cortes) <= 0.02 for p in J.pob_DANE_2026]]
    prueba("C07", "Candidatos", "Población a más de 2 % de los cortes de categoría", cerca.empty,
           ", ".join(f"{r.municipio} ({_es(r.pob_DANE_2026)} hab.)" for r in cerca.itertuples()) or "ninguno", "WARNING")

    # ---------------------------------------------------------------- Parámetros y presupuesto
    top10 = J.sort_values(["capacidad_K", "id"], ascending=[False, True]).head(10)
    B = par["P17"] * top10.costo_fijo_fj.sum()
    prueba("P01", "Parámetros", "B = 50 % del costo fijo de los 10 mayores (enunciado)", abs(B - meta["presupuesto_base_COP"]) < 1,
           f"B = {_es(B / 1e6, 1)} M COP; −15 % = {_es(B * 0.85 / 1e6, 1)} M; −30 % = {_es(B * 0.7 / 1e6, 1)} M")
    v_ok = meta["costo_kit_alimentacion_COP"] + meta["costo_kit_aseo_COP"] + meta["ajuste_redondeo_kits_COP"] == meta["costo_variable_COP_persona"]
    prueba("P02", "Parámetros", "v = kit de alimentación + kit de aseo + redondeo", bool(v_ok) and (cand.costo_variable_vj == par["P03"]).all(),
           f"{_es(meta['costo_kit_alimentacion_COP'])} + {_es(meta['costo_kit_aseo_COP'])} + {_es(meta['ajuste_redondeo_kits_COP'])} = {_es(par['P03'])} COP")
    prueba("P03", "Parámetros", "Tarifa 500 COP/km·persona y distancia máxima 180 km (enunciado)",
           par["P04"] == 500 and par["P16"] == D_MAX, "coinciden")
    prueba("P04", "Parámetros", "Reducciones dentro del rango 15–30 % (enunciado)", 0.15 <= par["P18"] <= par["P19"] <= 0.30,
           f"{_es(100 * par['P18'])} % y {_es(100 * par['P19'])} %")
    prueba("P05", "Parámetros", "El problema no es trivial: demanda > capacidad total", dem.d_f10.sum() > J.capacidad_K.sum(),
           f"demanda {_es(dem.d_f10.sum())} > capacidad {_es(J.capacidad_K.sum())}")
    prueba("P06", "Parámetros", "c_f y φ con fuente pública", False,
           "supuestos del grupo sin costo público por plaza (F18); ver sensibilidad de c_f", "WARNING")

    # ---------------------------------------------------------------- Coordenadas y distancias
    nodos = pd.read_csv(proc / "nodos_coordenadas.csv")
    co_ok = nodos[["lat", "lon"]].notna().all().all() and nodos.lat.between(*BBOX["lat"]).all() \
        and nodos.lon.between(*BBOX["lon"]).all() and not nodos.duplicated(["lat", "lon"]).any()
    prueba("G01", "Coordenadas", "47 nodos con coordenadas, dentro de la región y sin duplicados", bool(co_ok), f"{len(nodos)} nodos")
    prueba("G02", "Distancias", "Matriz 29 × 18 completa y positiva",
           dist.shape == (len(dem), len(cand)) and dist.notna().all().all() and (dist > 0).all().all(), f"{dist.size} pares")
    ll = nodos.set_index("id")
    lin = pd.DataFrame(_haversine(ll.loc[dist.index, "lat"].values[:, None], ll.loc[dist.index, "lon"].values[:, None],
                                  ll.loc[dist.columns, "lat"].values[None, :], ll.loc[dist.columns, "lon"].values[None, :]),
                       index=dist.index, columns=dist.columns)
    razon = dist / lin
    prueba("G03", "Distancias", "Distancia por carretera ≥ línea recta", bool((razon >= 1).all().all()),
           f"razón mínima {_es(razon.min().min(), 2)}")
    nodos_nom = dict(zip(nodos.id, nodos.municipio))
    altos = razon.stack()[razon.stack() > 2.3].sort_values(ascending=False)
    prueba("G04", "Distancias", "Razón carretera / línea recta ≤ 2,3", altos.empty,
           f"{len(altos)} pares de montaña con razón > 2,3: " + ", ".join(f"{nodos_nom[i]}–{nodos_nom[j]} ({_es(v, 2)})" for (i, j), v in altos.items()),
           "WARNING")
    gm_ok = all(abs(dist.loc[r.id_demanda, r.id_sitio] - r.km_Google_Maps) < 1e-6 for r in gm.itertuples())
    resto = [(i, j) for i in dist.index for j in dist.columns if (i, j) not in set(zip(gm.id_demanda, gm.id_sitio))]
    os_ok = all(abs(dist.loc[i, j] - dosrm.loc[i, j]) < 1e-6 for i, j in resto)
    prueba("G05", "Distancias", "Matriz final = Google Maps en pares verificados y OSRM en el resto", gm_ok and os_ok,
           f"{len(gm)} pares Google Maps + {len(resto)} OSRM")
    prueba("G06", "Distancias", "Una sola fuente de distancias", False,
           "matriz combinada Google Maps/OSRM: decisión adoptada (Google donde se decide la factibilidad; con solo OSRM la red base no cambia)", "WARNING")
    A = dist[J.id] <= D_MAX
    prueba("G07", "Distancias", "Cada municipio tiene ≥ 1 candidato a ≤ 180 km", bool(A.any(axis=1).all()),
           f"mínimo {int(A.sum(axis=1).min())} candidatos por municipio; {int(A.values.sum())} arcos factibles")
    alcance = A.sum(axis=0)
    prueba("G08", "Distancias", "Criterio de ciudad cercana: cada candidato alcanza ≥ 1 municipio", bool((alcance >= 1).all()),
           f"{int((alcance >= 1).sum())}/{len(J)} candidatos")
    justos = alcance[alcance <= 2]
    A_osrm = dosrm[J.id] <= D_MAX
    dep_g = {j: int((A[j] & ~A_osrm[j]).sum()) for j in justos.index}
    prueba("G09", "Distancias", "Cada candidato alcanza ≥ 3 municipios", justos.empty,
           ", ".join(f"{cand.set_index('id').loc[j, 'municipio']} alcanza {int(n)}" + (f" ({dep_g[j]} de ellos solo con Google Maps)" if dep_g[j] else "")
                     for j, n in justos.items()), "WARNING")
    borde = [(i, j) for i in dist.index for j in J.id if abs(dist.loc[i, j] - D_MAX) <= 3]
    nom = dict(zip(nodos.id, nodos.municipio))
    prueba("G10", "Distancias", "Ningún par a ≤ 3 km del corte de 180 km", not borde,
           f"{len(borde)} pares a ≤ 3 km del corte (Google muestra km enteros; OSRM es una ruta estimada): "
           + ", ".join(f"{nom[i]}–{nom[j]} ({_es(dist.loc[i, j], 1)} km)" for i, j in borde), "WARNING")
    cambia2 = int(((gm2.km_OSRM <= D_MAX) != (gm2.km_Google_Maps <= D_MAX)).sum())
    franja = [(i, j) for i in dosrm.index for j in dosrm.columns if 140 <= dosrm.loc[i, j] < 160]
    verif = set(zip(gm.id_demanda, gm.id_sitio)) | set(zip(gm2.id_demanda, gm2.id_sitio))
    prueba("G11", "Distancias", "Pares OSRM de 140–160 km verificados y sin cambio de factibilidad", cambia2 == 0 and all(p in verif for p in franja),
           f"{len(franja)} pares en la franja ({len(gm2)} verificados el 5-oct + {len(franja) - len(gm2)} de control); máximo Google {_es(gm2.km_Google_Maps.max())} km")

    # ---------------------------------------------------------------- Fuentes y supuestos de demanda
    prueba("F01", "Fuentes", "Tasa de albergue observada recalculada", bool(np.allclose(alb.tasa_observada, alb.albergados / alb.personas_en_NH, rtol=0, atol=1e-5)),
           f"{_es(100 * alb.tasa_observada.min(), 1)}–{_es(100 * alb.tasa_observada.max(), 1)} % de las personas en NH")
    prueba("F02", "Fuentes", "f = 10 % dentro del rango observado", par["P20"] <= alb.tasa_observada.max(),
           f"f es {_es(par['P20'] / alb.tasa_observada.max(), 1)}–{_es(par['P20'] / alb.tasa_observada.min(), 1)} veces lo observado: escenario de planeación (ABAG)",
           "WARNING")
    fuentes = pd.read_csv(proc / "fuentes.csv")
    prueba("F03", "Fuentes", "Cada fuente tiene URL y estado de verificación", bool(fuentes.URL.notna().all() and fuentes["Verificación"].notna().all()),
           f"{len(fuentes)} fuentes (F01–F{len(fuentes):02d})")
    nov = fuentes[fuentes["Verificación"].astype(str).str.lower().str.startswith("no verificada")]
    prueba("F04", "Fuentes", "Todas las fuentes abiertas y verificadas", nov.empty,
           f"{len(nov)} no verificadas: {', '.join(nov.ID)} (sus cifras vienen del libro del grupo)", "WARNING")
    return pd.DataFrame(filas, columns=COLUMNAS)


def resumen(tabla):
    """Conteo por resultado, p. ej. {'PASS': 30, 'WARNING': 13, 'FAIL': 0}."""
    c = tabla.resultado.value_counts()
    return {k: int(c.get(k, 0)) for k in ("PASS", "WARNING", "FAIL")}
