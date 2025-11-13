# app.py — Versión solo para Zipa (con filtro de grados)
# Streamlit 1.37.x
import io, zipfile, unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import altair as alt
import streamlit as st

# ========= CONFIG =========
RUTA_ARCHIVO = "Estudiantes.xlsx"
HOJA0 = 0
HOJA1 = 1
FIGS_DIRS = ["figs", "figs_nacional"]
LOGO_PATH = Path("innova_logo.png")   # en la raíz del Space
# ==========================

# --- Config de página ---
st.set_page_config(
    page_title="Reporte Institucional — Innova Schools Zipa",
    page_icon=str(LOGO_PATH) if LOGO_PATH.exists() else "📊",
    layout="wide",
)

# --- Normalización de texto para sede ---
def _norm(s: str) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s.lower()

TARGET_SEDE_CANON = "Zipa"
TARGET_SEDE_KEYS = {"zipa"}

# --- Encabezado con logo/título ---
def render_header():
    st.markdown(
        """
        <style>
        .hdr-box{
            display:flex; align-items:center; gap:16px;
            padding:6px 8px 14px 8px; margin-bottom:6px;
            border-bottom:1px solid rgba(160,160,160,.25);
        }
        .hdr-title{
            font-weight:800; line-height:1.25; margin:0;
            font-size:clamp(20px, 2.2vw, 28px);
        }
        .hdr-sub{
            margin:4px 0 0 0; opacity:.9; font-size:clamp(14px, 1.4vw, 16px);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns([1, 9], vertical_alignment="center")
    with c1:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), use_container_width=True)
    with c2:
        st.markdown(
            f"""
            <div class="hdr-box">
              <div>
                <h1 class="hdr-title">Reporte Institucional — Innova Schools</h1>
                <p class="hdr-sub">Sede: <b>{TARGET_SEDE_CANON}</b> · Grados 3°, 5°, 7° y 9°</p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

render_header()
st.markdown("<hr style='opacity:.25'>", unsafe_allow_html=True)

# --- Utilidades ---
def bar_chart(df, x_col, y_col, show_labels=False, row_height=36, min_height=180):
    rows = max(3, len(df))
    h = max(min_height, int(row_height) * rows)
    vmax = float(df[x_col].max()) if len(df) else 0.0

    base = alt.Chart(df).properties(width="container", height=h)
    bars = base.mark_bar().encode(
        x=alt.X(x_col, title=None, scale=alt.Scale(domain=(0, max(100.0, vmax * 1.1)))),
        y=alt.Y(y_col, sort="-x", title=None),
        tooltip=[y_col, alt.Tooltip(x_col, format=".2f")],
    )
    if show_labels:
        text = base.mark_text(align="left", baseline="middle", dx=3).encode(
            x=alt.X(x_col, scale=alt.Scale(domain=(0, max(100.0, vmax * 1.1)))),
            y=alt.Y(y_col, sort="-x"),
            text=alt.Text(x_col, format=".1f"),
        )
        return (bars + text).configure_view(stroke=None)
    return bars.configure_view(stroke=None)

def bytes_csv(df):
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    buf.seek(0)
    return buf

@st.cache_data(show_spinner=False)
def load_book(path: str):
    df0 = pd.read_excel(path, sheet_name=HOJA0)
    df1 = pd.read_excel(path, sheet_name=HOJA1)
    df0.columns = [c.strip() for c in df0.columns]
    df1.columns = [c.strip() for c in df1.columns]

    # convertir tipos
    df0["grado"] = pd.to_numeric(df0["grado"], errors="coerce")
    df1["Grado"] = pd.to_numeric(df1["Grado"], errors="coerce")
    for c in ["puntajenacional", "puntajePlantel"]:
        df1[c] = pd.to_numeric(df1[c], errors="coerce")

    # diff = Plantel - Nacional
    df1["diff"] = df1["puntajePlantel"] - df1["puntajenacional"]

    # long format para promedios por grado/área
    dl0 = (
        df0.melt(
            id_vars=["Sede", "grado"],
            value_vars=[
                c for c in df0.columns
                if c not in {"Source.Name", "Sede", "grado", "lista", "nombre", "definitiva"}
            ],
            var_name="prueba",
            value_name="puntaje",
        )
        .dropna(subset=["puntaje"])
    )

    # dimensiones disponibles
    dims = [
        d for d in ["competencia", "componente", "estandar", "evidencia", "tarea"]
        if d in df1.columns
    ]
    return df0, df1, dl0, dims

# --- FUNCIÓN CORREGIDA: Fortalezas / Retos ---
def fortalezas_retos(df1, group_keys, dim, modo, umbral=None, topn=None):
    """
    Clasificación según la regla:
      - diff_mean > 0  → Fortaleza (↑)  (Plantel por encima del nacional)
      - diff_mean < 0  → Reto (↓)       (Plantel por debajo del nacional)
      - diff_mean = 0  → En línea (≈)   (opcional mostrar/ocultar)

    Modo "Umbral": filtra por |diff_mean| >= umbral.
    Modo "Top/Bottom N": muestra las N mayores fortalezas y los N mayores retos,
    evitando duplicados.
    """
    agg = df1.groupby(group_keys + [dim], as_index=False).agg(
        diff_mean=("diff", "mean")
    )

    cols = group_keys + [dim, "diff_mean"]

    if agg.empty:
        return agg.assign(tipo=pd.Series(dtype=object))[cols + ["tipo"]]

    # Clasificación por signo
    agg["tipo"] = np.select(
        [
            agg["diff_mean"] > 0,
            agg["diff_mean"] < 0,
        ],
        [
            "Fortaleza (↑)",
            "Reto (↓)",  # o "Debilidad (↓)" si prefieres ese texto
        ],
        default="En línea (≈)",
    )

    if modo == "Umbral":
        # Filtramos por magnitud de la diferencia
        thr = float(umbral or 0.0)
        sub = agg[np.abs(agg["diff_mean"]) >= thr].copy()
        # Quitamos los que están exactamente en línea si no te interesa verlos
        sub = sub[sub["tipo"] != "En línea (≈)"]
        return sub[cols + ["tipo"]]

    # --- Modo Top/Bottom N ---
    topn = topn or 10

    # Solo fortalezas (>0) -> N mayores
    fortalezas = (
        agg[agg["diff_mean"] > 0]
        .nlargest(topn, "diff_mean")
        .copy()
    )

    # Solo retos (<0) -> N menores
    retos = (
        agg[agg["diff_mean"] < 0]
        .nsmallest(topn, "diff_mean")
        .copy()
    )

    res = pd.concat([fortalezas, retos], ignore_index=True)

    return res[cols + ["tipo"]]

# --- Cargar datos ---
try:
    df0, df1, dl0, dims = load_book(RUTA_ARCHIVO)
except Exception as e:
    st.error(f"❌ Error al cargar datos: {e}")
    st.stop()

# --- Detectar sede "Zipa" ---
sedes_raw = sorted(df0["Sede"].dropna().unique())
norm_to_dataset = {_norm(s): s for s in sedes_raw}
TARGET_SEDE_DATASET = None
for key in TARGET_SEDE_KEYS:
    if key in norm_to_dataset:
        TARGET_SEDE_DATASET = norm_to_dataset[key]
        break
if TARGET_SEDE_DATASET is None:
    st.error("❌ No se encontró la sede 'Zipa' en el archivo.")
    st.stop()

# --- Filtrar todo a Zipa ---
dl0 = dl0[dl0["Sede"] == TARGET_SEDE_DATASET].copy()
df1 = df1[df1["Sede"] == TARGET_SEDE_DATASET].copy()

# --- Listas de áreas y grados disponibles (en Zipa) ---
areas_all = sorted(
    set(dl0["prueba"].dropna().unique()).union(set(df1["area"].dropna().unique()))
)
GRADOS_VALIDOS = {3, 5, 7, 9}
grados_disp = sorted(
    GRADOS_VALIDOS.intersection(
        set(pd.to_numeric(dl0["grado"], errors="coerce").dropna().astype(int))
    )
)

# --- Sidebar ---
with st.sidebar:
    st.markdown("### Modo de selección")
    modo = st.radio("Modo:", ["Top/Bottom N", "Umbral"])
    if modo == "Top/Bottom N":
        topn = st.slider("N por lado", 1, 20, 10)
        umbral = None
    else:
        topn = None
        umbral = st.slider("Umbral (|Plantel−Nac| ≥)", 0.0, 10.0, 3.0, 0.5)

    st.divider()
    st.markdown("### Filtros")
    # Áreas
    areas_sel = st.multiselect(
        "Áreas (vacío = todas)", options=areas_all, default=[]
    )
    # Grado
    if grados_disp:
        grado_opt = st.radio(
            "Grado",
            options=["Todos"] + [str(g) for g in grados_disp],
            horizontal=True,
            index=0,
        )
    else:
        grado_opt = "Todos"
        st.caption("No hay grados 3/5/7/9 disponibles en Zipa.")

# Aplicar filtro de área
dl0_f = dl0 if not areas_sel else dl0[dl0["prueba"].isin(areas_sel)]
df1_f = df1 if not areas_sel else df1[df1["area"].isin(areas_sel)]

# Aplicar filtro de grado (si corresponde)
if grado_opt != "Todos":
    gsel = int(grado_opt)
    dl0_f = dl0_f[
        pd.to_numeric(dl0_f["grado"], errors="coerce").astype("Int64") == gsel
    ]
    df1_f = df1_f[
        pd.to_numeric(df1_f["Grado"], errors="coerce").astype("Int64") == gsel
    ]
    filtro_grado_txt = f" · Grado {gsel}"
else:
    filtro_grado_txt = " · Todos los grados"

# --- Render único ---
st.title(f"Sede: {TARGET_SEDE_CANON}{filtro_grado_txt}")

# Promedios
c1, c2 = st.columns(2)
with c1:
    g_grado = (
        dl0_f.groupby("grado", as_index=False)
        .agg(promedio=("puntaje", "mean"))
        .sort_values("grado")
    )
    st.subheader("Promedio por grado")
    st.altair_chart(bar_chart(g_grado, "promedio", "grado"), use_container_width=True)

with c2:
    g_area = (
        dl0_f.groupby("prueba", as_index=False)
        .agg(promedio=("puntaje", "mean"))
        .sort_values("promedio", ascending=False)
    )
    st.subheader("Promedio por área")
    st.altair_chart(bar_chart(g_area, "promedio", "prueba"), use_container_width=True)

# Fortalezas / Retos por dimensión
for dim in dims:
    with st.expander(
        f"{TARGET_SEDE_CANON}{filtro_grado_txt} · {dim} (Fortalezas/Retos)"
    ):
        tb = fortalezas_retos(df1_f, [], dim, modo, umbral, topn)
        if tb.empty:
            st.info("Sin resultados con el criterio actual.")
        else:
            st.dataframe(tb, use_container_width=True)
            st.download_button(
                "⬇️ CSV",
                data=bytes_csv(tb),
                file_name=f"{TARGET_SEDE_CANON}{'' if grado_opt=='Todos' else f'_G{int(grado_opt)}'}_{dim}.csv",
            )
