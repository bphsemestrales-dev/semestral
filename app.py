from __future__ import annotations

import datetime
import html
import hashlib
import random
import re
import string
import urllib.parse
from io import BytesIO
from pathlib import Path as FilePath

# --- LIBRERÍA PARA OPTIMIZAR FOTOS (Evita sobrecarga de RAM) ---
from PIL import Image as PILImage

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

st.set_page_config(
    page_title="Semestral Banfield",
    page_icon="🐾",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = FilePath(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"

# --- PALETA OFICIAL BANFIELD PET HOSPITAL ---
BANFIELD_BLUE = "#003366"        # Azul Institucional de tu carátula original
BANFIELD_NAVY = "#002F6C"        # Pantone 294 C
BANFIELD_ORANGE = "#DF4824"      # Naranja Institucional Banfield
BANFIELD_ORANGE_LIGHT = "#FDEFEA"
LIGHT_BLUE = "#EAF1F8"
SURFACE_GREY = "#F4F6F9"
BORDER_GREY = "#DCE3EC"
DARK_GREY = "#343A40"
BANFIELD_GREY = "#7F7F7F"

# Colores de Semáforo Clínico (Triage Visual en tablas de resultados)
STATUS_OK_TXT = "#1B5E20"
STATUS_WARN_TXT = "#E65100"
STATUS_ALERT_TXT = "#B71C1C"

# Catálogo de secciones que aceptan evidencia fotográfica (PC y Móvil)
# Ordenado ergonómicamente en móvil pero manteniendo todas las llaves intactas
PHOTO_SECTIONS = {
    "foto_s6": "🦷 S6 · Dental / Oral",
    "foto_s2": "🐕 S2 · Pelo y Piel",
    "foto_s8": "👂 S8 · Oídos (Otoscópico)",
    "foto_s7": "👁️ S7 · Ojos (Oftálmico)",
    "foto_s1": "⚖️ S1 · Condición General",
    "foto_lab": "🧪 S15 · Laboratorio Clínico",
    "foto_constantes": "🩺 Constantes Fisiológicas",
    "foto_s3": "🔍 S3 · Palpación Abdominal",
    "foto_s4": "🧬 S4 · Examen Urogenital",
    "foto_s5": "🩺 S5 · Examen Rectal",
    "foto_s9": "🦴 S9 · Musculoesquelético",
    "foto_s10": "🧠 S10 · Examen Neurológico",
}

# Catálogo de Recomendaciones Clínicas Rápidas (Sección 17 - Cero lenguaje de ventas)
QUICK_RECOMMENDATIONS = {
    "rec_chk_dental": (
        "🦷 Salud Dental",
        "Sugerimos programar una limpieza dental profunda bajo anestesia y radiografías dentales para evaluar raíces por debajo de la encía y prevenir infecciones.",
    ),
    "rec_chk_marcha": (
        "🦴 Articulaciones / Marcha",
        "Recomendamos tomar radiografías de evaluación en extremidades y espalda debido a la molestia o rigidez al caminar, valorando protectores articulares.",
    ),
    "rec_chk_oidos_piel": (
        "👂 Oídos / Piel",
        "Sugerimos citología ótica o cutánea para identificar el microorganismo causante de la comezón o secreción y dar el tratamiento exacto.",
    ),
    "rec_chk_peso": (
        "⚖️ Peso y Nutrición",
        "Ajustar la porción de alimento y fomentar ejercicio diario para cuidar articulaciones y función cardiaca.",
    ),
    "rec_chk_cirugia": (
        "🏥 Cirugía Preventiva",
        "Recomendamos programar cirugía de esterilización/castración preventiva para evitar infecciones uterinas o afecciones prostáticas.",
    ),
    "rec_chk_monitoreo": (
        "🧪 Monitoreo de Medicamentos",
        "Sugerimos análisis de sangre y orina periódicos para asegurar que hígado y riñón procesen adecuadamente los tratamientos continuos.",
    ),
}


# --- PUENTE DE SINCRONIZACIÓN MÓVIL EN TIEMPO REAL (CON LIMPIEZA AUTOMÁTICA) ---
@st.cache_resource
def get_mobile_photo_store() -> dict[str, dict]:
    """
    Almacén en memoria compartida del servidor Streamlit.
    Estructura: { token: {"timestamp": datetime, "hashes": set(), "data": { section_key: [ {"name": str, "bytes": bytes, "ts": str, "id": str}, ... ] } } }
    """
    return {}


mobile_store = get_mobile_photo_store()


def cleanup_old_sessions():
    """SOLUCIÓN A LA FUGA DE MEMORIA: Elimina sesiones (tokens) de más de 2 horas de antigüedad."""
    now = datetime.datetime.now()
    tokens_to_delete = []
    for token, session_info in mobile_store.items():
        if "timestamp" in session_info:
            age = now - session_info["timestamp"]
            if age.total_seconds() > 7200:  # 7200 segundos = 2 horas
                tokens_to_delete.append(token)

    for token in tokens_to_delete:
        del mobile_store[token]


cleanup_old_sessions()


def compress_image(uploaded_file, max_size=(800, 800), quality=70) -> bytes:
    """SOLUCIÓN DE RAM PARA REPORTLAB: Comprime y redimensiona fotos pesadas de celulares."""
    try:
        uploaded_file.seek(0)
        img = PILImage.open(uploaded_file)
        img = img.convert("RGB")
        img.thumbnail(max_size, PILImage.Resampling.LANCZOS)

        output = BytesIO()
        img.save(output, format="JPEG", quality=quality)
        return output.getvalue()
    except Exception:
        uploaded_file.seek(0)
        return uploaded_file.read()


# --- MOTOR DE LECTURA DE CATÁLOGOS CON AVISOS DE ERROR (SIN SILENCIAMIENTO) ---
@st.cache_data(show_spinner=False)
def load_catalogs(base_dir_str: str):
    base = FilePath(base_dir_str)
    df_cat = pd.DataFrame()
    cat_err = None
    med_err = None

    catalog_files = [
        "categorias_productos_2_3.csv",
        "categorias_productos_2_2.csv",
        "categorias_productos_2.csv",
        "categorias_productos.csv",
    ]
    catalog_loaded = False
    for f in catalog_files:
        p = base / f
        if p.is_file():
            try:
                df_cat = pd.read_csv(p)
                catalog_loaded = True
                cat_err = None
                break
            except Exception as e:
                cat_err = f"Error al leer {f}: {e}"

    if not catalog_loaded and df_cat.empty and not cat_err:
        cat_err = "No se encontró ningún archivo de categorías de productos."

    ced_files = ["cedulas_profesionales_2.csv", "cedulas_profesionales.csv", "196147d8.csv"]
    medicos = ["MVZ - Ced. Pendiente", "Otro"]
    ced_loaded = False
    for f in ced_files:
        path = base / f
        if path.is_file():
            try:
                df_ced = pd.read_csv(path)
                if "Nombre" in df_ced.columns and "Cedula Profesional" in df_ced.columns:
                    medicos = (
                        df_ced["Nombre"].astype(str).str.strip()
                        + " - Ced. "
                        + df_ced["Cedula Profesional"].astype(str).str.strip()
                    ).tolist() + ["Otro"]
                    ced_loaded = True
                    med_err = None
                    break
            except Exception as e:
                med_err = f"Error al leer {f}: {e}"

    if not ced_loaded and not med_err:
        med_err = "No se encontró un catálogo de cédulas válido."

    return df_cat, medicos, cat_err, med_err


df_cat, medicos, catalog_err_msg, medicos_err_msg = load_catalogs(str(BASE_DIR))
if catalog_err_msg:
    st.session_state["catalog_error"] = catalog_err_msg
if medicos_err_msg:
    st.session_state["medicos_error"] = medicos_err_msg


def get_cat_list(df: pd.DataFrame, category: str) -> list[str]:
    if df is None or df.empty:
        return ["Otro", "Ninguno"]
    if "Category" in df.columns:
        mask = df["Category"].str.contains(category, case=False, na=False)
        items = df[mask]["Description"].dropna().astype(str).tolist()
        return items + ["Otro", "Ninguno"]
    return ["Otro", "Ninguno"]


def get_food_options(df: pd.DataFrame, especie: str, humedo: bool = False) -> list[str]:
    base_ideal = ["Mantener dieta y porción actual (peso ideal)"]
    if df is None or df.empty or "Category" not in df.columns:
        return base_ideal + ["Otro", "Ninguno"]
    mask_alim = df["Category"].str.contains("Alimento", case=False, na=False)
    mask_esp = df["Category"].str.contains(especie, case=False, na=False) | df[
        "Description"
    ].str.contains(especie, case=False, na=False)
    mask_hum = df["Category"].str.contains(
        "humedo|húmedo|lata|sobre", case=False, na=False
    ) | df["Description"].str.contains("humedo|húmedo|lata|sobre", case=False, na=False)

    final_mask = (
        mask_alim & mask_esp & mask_hum if humedo else mask_alim & mask_esp & ~mask_hum
    )
    res = df[final_mask]["Description"].dropna().astype(str).tolist()
    if not res:
        res = (
            df[mask_alim & mask_hum]["Description"].dropna().astype(str).tolist()
            if humedo
            else df[mask_alim & ~mask_hum]["Description"].dropna().astype(str).tolist()
        )
    if not res:
        res = df[mask_alim]["Description"].dropna().astype(str).tolist()
    return base_ideal + res + ["Otro", "Ninguno"]


def get_vaccine_options(df: pd.DataFrame, especie: str) -> list[str]:
    if df is None or df.empty or "Category" not in df.columns:
        return ["Otro", "Ninguno"]

    cat_buscada = "Vacuna Canina" if especie == "Canino" else "Vacuna Felina"
    mask_exacta = df["Category"].str.strip().str.lower() == cat_buscada.lower()
    res = df[mask_exacta]["Description"].dropna().astype(str).tolist()

    if not res:
        mask_general = df["Category"].str.contains("Vacun", case=False, na=False)
        df_gen = df[mask_general]
        if not df_gen.empty:
            if especie == "Canino":
                mask_desc = df_gen["Description"].str.contains(
                    "canin|perro|parvo|distemper|rabia|múltiple|bordetella",
                    case=False,
                    na=False,
                )
            else:
                mask_desc = df_gen["Description"].str.contains(
                    "felin|gato|leucemia|rinotraqueitis|calicivirus",
                    case=False,
                    na=False,
                )
            res = df_gen[mask_desc]["Description"].dropna().astype(str).tolist()
            if not res:
                res = df_gen["Description"].dropna().astype(str).tolist()

    return res + ["Otro", "Ninguno"]


shampoos = get_cat_list(df_cat, "Shampoo")
piel_pelo = get_cat_list(df_cat, "Piel y pelo")
desp_int = get_cat_list(df_cat, "Desparasitante Interno")
desp_ext = get_cat_list(df_cat, "Desparasitantes")
nutraceuticos_list = get_cat_list(df_cat, "Vitaminas")
dental_list = get_cat_list(df_cat, "Cuidado dental")
oftalmico_list = get_cat_list(df_cat, "Oftalmico")
otico_list = get_cat_list(df_cat, "Otica")

# --- ESTILOS CSS CORPORATIVOS BANFIELD ---
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap');
    .stApp {{
        font-family: 'Open Sans', Helvetica, Arial, sans-serif;
    }}
    h1, h2, h3, h4, .banfield-text {{
        color: {BANFIELD_BLUE} !important;
        font-weight: 700 !important;
    }}
    .banfield-hero {{
        background: linear-gradient(135deg, {BANFIELD_BLUE} 0%, #00469B 100%);
        color: white;
        padding: 18px 24px;
        border-radius: 12px;
        border-bottom: 4px solid {BANFIELD_ORANGE};
        margin-bottom: 18px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 4px 12px rgba(0, 47, 108, 0.12);
    }}
    .banfield-hero h2 {{
        color: white !important;
        margin: 0 !important;
        font-size: 1.45rem !important;
    }}
    .banfield-hero p {{
        color: #DCE8F7;
        margin: 4px 0 0 0;
        font-size: 0.9rem;
    }}
    .banfield-badge {{
        background-color: {BANFIELD_ORANGE};
        color: white;
        padding: 6px 14px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }}
    .section-card-header {{
        background-color: {LIGHT_BLUE};
        border-left: 5px solid {BANFIELD_ORANGE};
        padding: 10px 16px;
        border-radius: 6px;
        margin-top: 14px;
        margin-bottom: 12px;
    }}
    /* Escudo Blanco para salvar la vida del Logo y el QR en la barra lateral */
    [data-testid="stSidebar"] img {{
        background-color: white !important;
        padding: 12px !important;
        border-radius: 8px !important;
        box-shadow: 0px 4px 6px rgba(0,0,0,0.1);
    }}
    @media (prefers-color-scheme: dark) {{
        h1, h2, h3, h4, .banfield-text {{
            color: {BANFIELD_ORANGE} !important;
        }}
        .section-card-header {{
            background-color: rgba(255, 255, 255, 0.06);
        }}
    }}
    div.stButton > button[kind="primary"] {{
        background-color: {BANFIELD_ORANGE};
        color: white;
        border: 0;
        font-weight: 700;
        border-radius: 8px;
    }}
    div.stButton > button[kind="primary"]:hover {{
        background-color: #c93b1b;
        color: white;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


def asset_path(filename: str) -> FilePath | None:
    if not filename:
        return None
    candidate = ASSETS_DIR / filename
    if candidate.is_file():
        return candidate
    candidate_root = BASE_DIR / filename
    return candidate_root if candidate_root.is_file() else None


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return cleaned.strip("_")[:70] or "Mascota"


def clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(x) for x in value if x and str(x) != "Ninguno")
    s = str(value).strip()
    return "" if s in ("Ninguno", "") else s


def ptext(value) -> str:
    val = clean_text(value)
    return html.escape(val).replace("\n", "<br/>") if val else "—"


# ==============================================================================
# 📱 MODO CÁMARA MÓVIL REDISEÑADO (ERGONÓMICO, 1 TOQUE, AUTO-GUARDADO A LA PC)
# ==============================================================================
qp = st.query_params
if qp.get("movil") == "1" and qp.get("token"):
    token_movil = str(qp.get("token")).strip()
    paciente_movil = str(qp.get("paciente", "Paciente")).strip()

    if token_movil not in mobile_store:
        mobile_store[token_movil] = {
            "timestamp": datetime.datetime.now(),
            "hashes": set(),
            "data": {},
        }
    else:
        mobile_store[token_movil]["timestamp"] = datetime.datetime.now()
        if "hashes" not in mobile_store[token_movil]:
            mobile_store[token_movil]["hashes"] = set()

    if "mob_active_sec" not in st.session_state:
        st.session_state["mob_active_sec"] = "foto_s6"  # Dental por defecto
    if "mob_upload_counter" not in st.session_state:
        st.session_state["mob_upload_counter"] = 0

    total_enviadas = sum(len(v) for v in mobile_store[token_movil]["data"].values())

    st.markdown(
        f"""
        <div class="banfield-hero" style="padding:14px 18px; margin-bottom:10px;">
            <div>
                <h2 style="font-size:1.25rem !important;">📱 Cámara Clínica · {html.escape(paciente_movil)}</h2>
                <p style="font-size:0.82rem;">Fotos sincronizadas con la PC: <b>{total_enviadas}</b> · Token: <code>{html.escape(token_movil)}</code></p>
            </div>
            <div class="banfield-badge">EN VIVO</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # PASO 1: Botones grandes táctiles para las 6 áreas más fotografiadas + selector rápido del resto
    st.markdown("##### 1️⃣ Toca el área que vas a fotografiar:")
    top_keys = ["foto_s6", "foto_s2", "foto_s8", "foto_s7", "foto_s1", "foto_lab"]
    other_keys = [k for k in PHOTO_SECTIONS.keys() if k not in top_keys]

    grid_r1 = st.columns(2)
    grid_r2 = st.columns(2)
    grid_r3 = st.columns(2)
    grid_cols = [grid_r1[0], grid_r1[1], grid_r2[0], grid_r2[1], grid_r3[0], grid_r3[1]]

    for idx_b, k_sec in enumerate(top_keys):
        cnt = len(mobile_store[token_movil]["data"].get(k_sec, []))
        cnt_str = f" ({cnt} 📸)" if cnt > 0 else ""
        is_active = st.session_state["mob_active_sec"] == k_sec
        if grid_cols[idx_b].button(
            f"{PHOTO_SECTIONS[k_sec]}{cnt_str}",
            key=f"btn_mob_{k_sec}",
            type="primary" if is_active else "secondary",
            use_container_width=True,
        ):
            st.session_state["mob_active_sec"] = k_sec
            st.rerun()

    with st.expander("➕ Otras secciones (Constantes, Abdomen, Urogenital, Ortopédico, Neuro)"):
        o_cols = st.columns(2)
        for idx_o, k_other in enumerate(other_keys):
            cnt_o = len(mobile_store[token_movil]["data"].get(k_other, []))
            cnt_o_str = f" ({cnt_o} 📸)" if cnt_o > 0 else ""
            is_act_o = st.session_state["mob_active_sec"] == k_other
            if o_cols[idx_o % 2].button(
                f"{PHOTO_SECTIONS[k_other]}{cnt_o_str}",
                key=f"btn_mob_{k_other}",
                type="primary" if is_act_o else "secondary",
                use_container_width=True,
            ):
                st.session_state["mob_active_sec"] = k_other
                st.rerun()

    sec_key = st.session_state["mob_active_sec"]
    sec_label = PHOTO_SECTIONS[sec_key]

    st.markdown(
        f"""
        <div class='section-card-header' style='margin-top:8px; margin-bottom:10px;'>
            <b>📍 Capturando en: {html.escape(sec_label)}</b><br/>
            <small>Al tomar o elegir la foto se envía <b>automáticamente</b> a la PC (sin botones extra).</small>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # PASO 2: Captura directa con auto-envío inmediato
    up_key = f"mob_auto_up_{sec_key}_{st.session_state['mob_upload_counter']}"
    up_pics = st.file_uploader(
        f"📸 Toca aquí para abrir Cámara HD o Galería ({sec_label})",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key=up_key,
    )

    with st.expander("🎥 ¿Prefieres usar el visor de cámara integrado en navegador?"):
        cam_pic = st.camera_input(
            f"Visor web ({sec_label})",
            key=f"mob_cam_{sec_key}_{st.session_state['mob_upload_counter']}",
        )

    nuevos_archivos = []
    if up_pics:
        nuevos_archivos.extend(up_pics)
    if cam_pic is not None:
        nuevos_archivos.append(cam_pic)

    if nuevos_archivos:
        sec_list = mobile_store[token_movil]["data"].setdefault(sec_key, [])
        guardadas_ahora = 0
        for f_obj in nuevos_archivos:
            raw_bytes = compress_image(f_obj)
            file_hash = hashlib.md5(raw_bytes).hexdigest()
            dedup_key = f"{sec_key}:{file_hash}"
            if dedup_key not in mobile_store[token_movil]["hashes"]:
                mobile_store[token_movil]["hashes"].add(dedup_key)
                sec_list.append(
                    {
                        "id": dedup_key,
                        "name": getattr(f_obj, "name", f"foto_{len(sec_list)+1}.jpg"),
                        "bytes": raw_bytes,
                        "ts": datetime.datetime.now().strftime("%H:%M:%S"),
                    }
                )
                guardadas_ahora += 1

        if guardadas_ahora > 0:
            st.session_state["mob_last_msg"] = (
                f"✅ ¡{guardadas_ahora} foto(s) guardada(s) y sincronizada(s) con la PC en '{sec_label}'!"
            )
            st.session_state["mob_upload_counter"] += 1
            st.rerun()

    if st.session_state.get("mob_last_msg"):
        st.success(st.session_state["mob_last_msg"])

    # Galería de la sección actual y resumen general con botón de borrado individual
    fotos_seccion_actual = mobile_store[token_movil]["data"].get(sec_key, [])
    if fotos_seccion_actual:
        st.markdown(f"**Fotos en {sec_label} ({len(fotos_seccion_actual)}):**")
        cols_act = st.columns(min(3, len(fotos_seccion_actual)))
        for idx_f, item_f in enumerate(list(fotos_seccion_actual)):
            with cols_act[idx_f % len(cols_act)]:
                st.image(item_f["bytes"], caption=f"#{idx_f+1} · {item_f['ts']}", use_container_width=True)
                if st.button("🗑️ Borrar", key=f"del_mob_{sec_key}_{idx_f}", use_container_width=True):
                    mobile_store[token_movil]["hashes"].discard(item_f.get("id", ""))
                    mobile_store[token_movil]["data"][sec_key].pop(idx_f)
                    st.session_state["mob_last_msg"] = "Foto eliminada."
                    st.rerun()

    total_enviadas = sum(len(v) for v in mobile_store[token_movil]["data"].values())
    if total_enviadas > 0:
        with st.expander(f"📂 Ver todas las fotos de la consulta ({total_enviadas} en total)"):
            for s_k, items_list in mobile_store[token_movil]["data"].items():
                if items_list:
                    st.markdown(f"**{PHOTO_SECTIONS.get(s_k, s_k)}** ({len(items_list)} foto[s])")
                    cols_m = st.columns(min(3, len(items_list)))
                    for idx_m, item_m in enumerate(items_list):
                        cols_m[idx_m % len(cols_m)].image(
                            item_m["bytes"], caption=f"{item_m['ts']}", use_container_width=True
                        )
            if st.button("🗑️ Limpiar TODAS las fotos enviadas", use_container_width=True):
                mobile_store[token_movil]["data"] = {}
                mobile_store[token_movil]["hashes"] = set()
                st.session_state["mob_last_msg"] = "Se limpiaron todas las fotos."
                st.rerun()

    st.stop()


# ==============================================================================
# 🖥️ APLICACIÓN PRINCIPAL DE CONSULTORIO (MODO PC / TABLET)
# ==============================================================================

def classify_clinical_value(label: str, raw_val: str) -> str:
    """Clasifica un valor clínico en 'ok', 'warn', 'alert' o 'neutral' para el semáforo del PDF."""
    if not raw_val:
        return "neutral"
    v = str(raw_val).strip().lower()
    if "[  ]" in v or "____" in v:
        return "neutral"
    if v in ("—", "ninguno", "no evaluado", "no realizado", "no aplica", ""):
        return "neutral"

    # Evaluación numérica especial para Tonometría PIO (10 a 25 mmHg)
    if "presión intraocular" in label.lower() or "pio" in label.lower():
        m = re.search(r"(\d+(?:\.\d+)?)", v)
        if m:
            pio_val = float(m.group(1))
            if 10.0 <= pio_val <= 25.0:
                return "ok"
            return "alert"

    if v in (
        "normal",
        "normal / coordinada",
        "normales descendidos",
        "normal (sin nódulos)",
        "parece normal",
        "dentro de límites normales",
        "negativo",
        "excelente",
        "buena",
        "perfecto",
        "4-5: peso ideal",
        "4/9: peso ideal",
        "5/9: peso ideal",
        "mantener dieta y porción actual (peso ideal)",
        "ninguno presente",
        "no presente",
        "vacío",
        "rosas y húmedas",
        "sin pulgas: continuar o iniciar prevención",
    ):
        return "ok"
    if any(
        w in v
        for w in (
            "grado iii",
            "grado iv",
            "grado 3",
            "grado 4",
            "grado 5",
            "8-9: obesidad",
            "8/9:",
            "9/9:",
            "1/9:",
            "balanopostitis",
            "retenido",
            "aumentada o dolor",
            "nódulos",
            "claudicación",
            "positivo",
            "anormal",
            "pulgas",
            "garrapatas",
            "piojos",
            "infección",
            "tumores",
            "úlceras",
            "ictéricas",
            "congestivas",
            "pálidas",
        )
    ):
        return "alert"
    if any(
        w in v
        for w in (
            "grado i",
            "grado ii",
            "grado 1",
            "grado 2",
            "1-3: delgado",
            "2/9:",
            "3/9:",
            "6-7: sobrepeso",
            "6/9:",
            "7/9:",
            "secreción",
            "dermatitis",
            "asimétrico",
            "dificultad para levantarse",
            "rigidez",
            "necesita mejorar",
            "demasiado delgado",
            "muy pesado",
            "pendiente",
            "no palpable",
            "presente",
        )
    ):
        return "warn"
    return "neutral"


def format_badge_html(value_str: str, status: str) -> str:
    """Devuelve texto enriquecido para ReportLab con color semántico."""
    escaped = html.escape(value_str).replace("\n", "<br/>") if value_str else "—"
    if status == "ok":
        return f"<font color='{STATUS_OK_TXT}'><b>●</b> {escaped}</font>"
    if status == "warn":
        return f"<font color='{STATUS_WARN_TXT}'><b>▲ {escaped}</b></font>"
    if status == "alert":
        return f"<font color='{STATUS_ALERT_TXT}'><b>■ {escaped}</b></font>"
    return f"<font color='{DARK_GREY}'>{escaped}</font>"


def sync_quick_recommendations_to_textarea():
    """
    Concatena automáticamente las Recomendaciones Clínicas Rápidas marcadas dentro
    del st.text_area("Instrucciones para el cliente"), preservando cualquier texto libre
    adicional que el médico haya escrito manualmente.
    """
    current_text = st.session_state.get("recomendaciones", "") or ""
    # Separar las líneas que son de casillas rápidas vs texto libre del médico
    all_quick_texts = {txt for _, txt in QUICK_RECOMMENDATIONS.values()}
    custom_lines = []
    for line in current_text.splitlines():
        cleaned_line = line.strip().lstrip("•- ").strip()
        if cleaned_line and cleaned_line not in all_quick_texts:
            custom_lines.append(line)

    selected_quick_lines = []
    for chk_key, (_, rec_text) in QUICK_RECOMMENDATIONS.items():
        if st.session_state.get(chk_key, False):
            selected_quick_lines.append(f"• {rec_text}")

    final_blocks = selected_quick_lines + custom_lines
    st.session_state["recomendaciones"] = "\n".join(final_blocks).strip()


def auto_suggest_quick_recommendations(d: dict):
    """Marca automáticamente las casillas de Sección 17 que correspondan a los hallazgos clínicos del paciente."""
    # 1. Salud Dental
    if d.get("epo") not in ("Negativo", "Ninguno", "No evaluado", None) or d.get("sarro") == "Positivo":
        st.session_state["rec_chk_dental"] = True
    # 2. Articulaciones / Marcha
    if d.get("tipo_marcha") in ("Claudicación / Renguea", "Dificultad para levantarse / Rigidez") or any(
        d.get(k) == "Anormal" for k in ("cue", "esp", "cola", "mad", "mai", "mpd", "mpi")
    ):
        st.session_state["rec_chk_marcha"] = True
    # 3. Oídos / Piel
    if (
        d.get("pelo_piel") == "Anormal"
        or d.get("planos_por_lesion")
        or d.get("sec_oido_od") == "Positivo"
        or d.get("sec_oido_oi") == "Positivo"
        or any(d.get(k) == "Anormal" for k in ("ore_od", "ore_oi", "inf_oido_od", "inf_oido_oi", "aca_od", "aca_oi"))
    ):
        st.session_state["rec_chk_oidos_piel"] = True
    # 4. Peso y Nutrición
    if any(
        w in str(d.get("bcs_escala", "")).lower() for w in ("sobrepeso", "obesidad", "delgado", "bajo peso")
    ) or d.get("peso") in ("Demasiado delgado", "Muy pesado"):
        st.session_state["rec_chk_peso"] = True
    # 5. Cirugía Preventiva
    if d.get("estado_reproductivo") == "Entero(a)":
        st.session_state["rec_chk_cirugia"] = True

    sync_quick_recommendations_to_textarea()


def aplicar_paciente_sano_defaults():
    """Pre-llena todos los campos clínicos (incluyendo los nuevos del Dr. Fausto) en estado Normal/Negativo."""
    defaults = {
        "mucosas_sel": "Rosas y húmedas",
        "cond_gral": "Excelente",
        "peso": "Perfecto",
        "bcs_escala": "4-5: Peso ideal",
        "plan_nutricional": "Mantener dieta y porción actual (peso ideal)",
        "pelo_piel": "Parece normal",
        "ectoparasitos": "Ninguno presente",
        "c_pulgas": "Sin pulgas: continuar o iniciar prevención",
        "hig": "Dentro de límites normales",
        "est": "Dentro de límites normales",
        "bazo": "Dentro de límites normales",
        "rd": "Dentro de límites normales",
        "ri": "Dentro de límites normales",
        "int_mes": "Dentro de límites normales",
        "imp_gral": "Dentro de límites normales",
        # Sección 4 Urogenital (General + Condicionales Macho/Hembra)
        "secr_uro": "Negativo",
        "infl_uro": "Negativo",
        "bult_uro": "Negativo",
        "tum_mam": "Negativo",
        "uro_pene_prepucio": "Normal",
        "uro_testiculos": "Normales descendidos",
        "uro_prostata_macho": "Normal",
        "uro_vulva": "Normal",
        "uro_cadena_mamaria": "Normal (sin nódulos)",
        # Sección 5 Rectal
        "pros": "Normal",
        "tum_rect": "Negativo",
        "hern": "Negativo",
        "sacos": "Normal",
        # Sección 6 Dental
        "epo": "Negativo",
        "sarro": "Negativo",
        "mord": "Normal",
        "decol_d": "Negativo",
        "hinc_e": "Negativo",
        "retr_e": "Negativo",
        "inf_e": "Negativo",
        "epul_e": "Negativo",
        "inf_a": "Negativo",
        "hinc_a": "Negativo",
        "inf_l": "Negativo",
        "dec_l": "Negativo",
        "hinc_l": "Negativo",
        "tal_n": "Normal",
        "con_n": "Normal",
        "inf_g": "Negativo",
        "ref_g": "Normal",
        # Sección 7 Oftálmico
        "conj_od": "Negativo",
        "sec_od": "Negativo",
        "def_od": "Negativo",
        "tum_od": "Negativo",
        "conj_oi": "Negativo",
        "sec_oi": "Negativo",
        "def_oi": "Negativo",
        "tum_oi": "Negativo",
        # Sección 8 Otoscópico
        "ore_od": "Normal",
        "tim_od": "Normal",
        "aca_od": "Normal",
        "tum_oido_od": "Normal",
        "inf_oido_od": "Normal",
        "sec_oido_od": "Negativo",
        "ore_oi": "Normal",
        "tim_oi": "Normal",
        "aca_oi": "Normal",
        "tum_oido_oi": "Normal",
        "inf_oido_oi": "Normal",
        "sec_oido_oi": "Negativo",
        # Sección 9 Musculoesquelético + Marcha
        "cue": "Normal",
        "esp": "Normal",
        "cola": "Normal",
        "mad": "Normal",
        "mai": "Normal",
        "mpd": "Normal",
        "mpi": "Normal",
        "tipo_marcha": "Normal / coordinada",
        # Sección 10 Neurológico
        "ment": "Normal",
        "cran": "Normal",
        "prop": "Normal",
        "patel": "Normal",
        "dolor": "Negativo",
        # Sección 11 y 12 Cardio-Respiratorio
        "f_car": "Normal",
        "pul_car": "Normal",
        "sop_car": "Negativo",
        "rit_car": "Normal",
        "tllc_car": "Normal",
        "cd": "Normal",
        "cad": "Normal",
        "ci": "Normal",
        "cai": "Normal",
        # Sección 14 y 15 Laboratorio
        "tox": "Negativo",
        "coc": "Negativo",
        "nem": "Negativo",
        "gia": "Negativo",
        "gyp": "Negativo",
        "ces": "Negativo",
        "eritrocitos": "Normal",
        "leucocitos_s": "Normal",
        "tiroides": "Normal",
        "enz_ren": "Normal",
        "enz_hep": "Normal",
        "enz_pan": "Normal",
        "electrolitos": "Normal",
        "prot_ser": "Normal",
        "uro_urobilinogeno": "Normal",
        "uro_sangre": "Normal",
        "uro_bilirrubina": "Normal",
        "uro_cetona": "Normal",
        "uro_proteina": "Normal",
        "uro_ph": "Normal",
        "uro_gravedad": "Normal",
        "sed_eritrocitos": "No presente",
        "sed_leucocitos": "No presente",
        "sed_bacterias": "No presente",
        "sed_cilindros": "No presente",
    }
    for k, v in defaults.items():
        st.session_state[k] = v


def ui_header(title: str, icon_name: str | None = None):
    icon_p = asset_path(icon_name) if icon_name else None
    if icon_p:
        c1, c2 = st.columns([1, 18])
        with c1:
            st.image(str(icon_p), width=38)
        with c2:
            st.markdown(
                f"<div class='section-card-header'><h3 style='margin:0; font-size:1.15rem;'>{title}</h3></div>",
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            f"<div class='section-card-header'><h3 style='margin:0; font-size:1.15rem;'>{title}</h3></div>",
            unsafe_allow_html=True,
        )


def renderizar_uploader(label: str, key: str) -> list:
    """Combina archivos subidos en la PC + fotos enviadas por el celular mediante el QR."""
    token_actual = st.session_state.get("sync_token", "")
    fotos_moviles = []
    if token_actual and token_actual in mobile_store:
        fotos_moviles = mobile_store[token_actual].get("data", {}).get(key, [])

    badge_movil = f" · 📱 {len(fotos_moviles)} desde móvil" if fotos_moviles else ""
    with st.expander(f"📷 Anexar evidencia fotográfica ({label}){badge_movil}", expanded=bool(fotos_moviles)):
        pc_files = st.file_uploader(
            "Tomar foto o elegir de la galería",
            type=["jpg", "jpeg", "png"],
            key=key,
            accept_multiple_files=True,
        )
        combined = []
        if pc_files:
            for pf in pc_files:
                comp_bytes = compress_image(pf)
                bio_pc = BytesIO(comp_bytes)
                bio_pc.name = getattr(pf, "name", "foto_pc.jpg")
                combined.append(bio_pc)
        if fotos_moviles:
            st.caption(f"📱 **{len(fotos_moviles)} foto(s) recibida(s) desde el Portal Móvil QR:**")
            cols_prev = st.columns(min(4, len(fotos_moviles)))
            for idx_p, item_p in enumerate(fotos_moviles):
                cols_prev[idx_p % len(cols_prev)].image(
                    item_p["bytes"],
                    caption=f"{item_p['name']} ({item_p['ts']})",
                    use_container_width=True,
                )
                bio = BytesIO(item_p["bytes"])
                bio.name = item_p["name"]
                combined.append(bio)
        return combined


def select_con_otro(label: str, opciones: list[str], key_base: str) -> str:
    val = st.selectbox(label, opciones, key=key_base + "_sel")
    if val == "Otro":
        return st.text_input(f"Especifique {label.lower()}", key=key_base + "_txt")
    return val


def multiselect_con_otro(label: str, opciones: list[str], key_base: str) -> list[str]:
    ops = [o for o in opciones if o != "Ninguno"]
    val = st.multiselect(label, ops, key=key_base + "_sel")
    if "Otro" in val:
        otro_val = st.text_input(f"Especifique {label.lower()}", key=key_base + "_txt")
        if otro_val and otro_val.strip():
            val = [v for v in val if v != "Otro"] + [otro_val.strip()]
        else:
            val = [v for v in val if v != "Otro"]
    return val


# --- MOTOR DE TABLAS COMPACTAS Y SEMÁFORO CLÍNICO EN PDF ---
def add_labeled_rows(
    story_list: list,
    grouped_rows: list,
    styles: dict,
    two_column_grid: bool = True,
    hide_unassessed: bool = False,
):
    if not grouped_rows:
        return

    for group_title, items in grouped_rows:
        filtered_items = []
        for label, value in items:
            if hide_unassessed and isinstance(value, str):
                v_clean = value.strip().lower()
                if v_clean in ("—", "ninguno", "no evaluado", "no realizado", "no aplica", ""):
                    continue
            filtered_items.append((label, value))

        if not filtered_items:
            continue

        has_complex_flowable = any(
            not isinstance(v, str) or len(str(v)) > 48 or "<br/>" in str(v)
            for _, v in filtered_items
        )
        use_grid = two_column_grid and not has_complex_flowable and len(filtered_items) >= 4

        if use_grid:
            col_widths = [125, 130, 125, 130]
            table_data = [
                [
                    Paragraph(
                        f"<font color='{BANFIELD_BLUE}'><b>{html.escape(group_title)}</b></font>",
                        styles["GroupHeader"],
                    ),
                    "",
                    "",
                    "",
                ]
            ]
            row_styles = [
                ("SPAN", (0, 0), (3, 0)),
                ("BACKGROUND", (0, 0), (3, 0), colors.HexColor(LIGHT_BLUE)),
                ("LINEBELOW", (0, 0), (3, 0), 1, colors.HexColor(BANFIELD_BLUE)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("INNERGRID", (0, 1), (-1, -1), 0.35, colors.HexColor(BORDER_GREY)),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(BORDER_GREY)),
            ]

            paired = [filtered_items[i : i + 2] for i in range(0, len(filtered_items), 2)]
            for r_idx, pair in enumerate(paired, start=1):
                lbl1, val1 = pair[0]
                st1 = classify_clinical_value(lbl1, val1)
                p_lbl1 = Paragraph(f"<b>{html.escape(lbl1)}</b>", styles["Small"])
                p_val1 = Paragraph(format_badge_html(val1, st1), styles["Small"])

                if len(pair) == 2:
                    lbl2, val2 = pair[1]
                    st2 = classify_clinical_value(lbl2, val2)
                    p_lbl2 = Paragraph(f"<b>{html.escape(lbl2)}</b>", styles["Small"])
                    p_val2 = Paragraph(format_badge_html(val2, st2), styles["Small"])
                else:
                    p_lbl2, p_val2 = Paragraph("", styles["Small"]), Paragraph("", styles["Small"])

                table_data.append([p_lbl1, p_val1, p_lbl2, p_val2])
                bg = colors.white if r_idx % 2 == 1 else colors.HexColor("#FAFBFD")
                row_styles.append(("BACKGROUND", (0, r_idx), (3, r_idx), bg))

            table = Table(table_data, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
            table.setStyle(TableStyle(row_styles))
            story_list.append(table)
            story_list.append(Spacer(1, 4))
        else:
            col_widths = [210, 300]
            table_data = [
                [
                    Paragraph(
                        f"<font color='{BANFIELD_BLUE}'><b>{html.escape(group_title)}</b></font>",
                        styles["GroupHeader"],
                    ),
                    "",
                ]
            ]
            row_styles = [
                ("SPAN", (0, 0), (1, 0)),
                ("BACKGROUND", (0, 0), (1, 0), colors.HexColor(LIGHT_BLUE)),
                ("LINEBELOW", (0, 0), (1, 0), 1, colors.HexColor(BANFIELD_BLUE)),
                ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor("#E5E9F0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
            for r_idx, (label, value) in enumerate(filtered_items, start=1):
                if isinstance(value, str):
                    st_val = classify_clinical_value(label, value)
                    if "<br/>" in value:
                        val_flow = Paragraph(value, styles["Small"])
                    else:
                        val_flow = Paragraph(format_badge_html(value, st_val), styles["Small"])
                else:
                    val_flow = value

                table_data.append(
                    [
                        Paragraph(f"<b>{html.escape(label)}</b>", styles["Small"]),
                        val_flow,
                    ]
                )
                bg = colors.white if r_idx % 2 == 1 else colors.HexColor("#FAFBFD")
                row_styles.append(("BACKGROUND", (0, r_idx), (1, r_idx), bg))

            table = Table(table_data, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
            table.setStyle(TableStyle(row_styles))
            story_list.append(table)
            story_list.append(Spacer(1, 3))


def add_info_box(story: list, title: str, content: str, styles: dict):
    box_data = [[Paragraph(f"<b>{title}:</b> {content}", styles["InfoBox"])]]
    t = Table(box_data, colWidths=[510], hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FDEFEA")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(BANFIELD_ORANGE)),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(Spacer(1, 2))
    story.append(t)
    story.append(Spacer(1, 5))


def add_section_pdf(
    story: list,
    title: str,
    grouped_rows: list,
    styles: dict,
    icon_name: str | None = None,
    notes: str | None = None,
    photo_list: list | None = None,
    two_column_grid: bool = True,
    hide_unassessed: bool = False,
):
    icon_file = asset_path(icon_name) if icon_name else None

    if icon_file:
        img_path_str = str(icon_file).replace("\\", "/")
        header_html = f"<img src='{img_path_str}' width='20' height='20' valign='middle'/>  {html.escape(title)}"
        story.append(Paragraph(header_html, styles["Section"]))
    else:
        story.append(Paragraph(html.escape(title), styles["Section"]))

    if grouped_rows:
        add_labeled_rows(
            story,
            grouped_rows,
            styles,
            two_column_grid=two_column_grid,
            hide_unassessed=hide_unassessed,
        )

    if photo_list:
        photo_elements = []
        for p in photo_list:
            try:
                p.seek(0)
                img = Image(p, width=245, height=180, kind="proportional")
                photo_elements.append(img)
            except Exception:
                pass

        if photo_elements:
            rows = [photo_elements[i : i + 2] for i in range(0, len(photo_elements), 2)]
            if len(rows[-1]) == 1:
                rows[-1].append("")

            foto_table = Table(rows, hAlign="LEFT")
            foto_table.setStyle(
                TableStyle(
                    [
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(foto_table)
            story.append(Spacer(1, 3))

    if notes and clean_text(notes):
        story.append(Paragraph(f"<b>Notas:</b> {ptext(notes)}", styles["Body"]))
        story.append(Spacer(1, 3))

    story.append(Spacer(1, 8))


def extraer_hallazgos_atencion(d: dict) -> list[str]:
    """Auditoría clínica integral de las 15 secciones (incluyendo BCS, Urogenital por sexo, PIO y Marcha)."""
    atencion = []
    triggers = [
        "anormal",
        "positivo",
        "pulgas",
        "piojos",
        "garrapatas",
        "demasiado",
        "muy pesado",
        "necesita mejorar",
        "grado",
        "presente",
        "pálidas",
        "congestivas",
        "ictéricas",
        "tiene pulgas",
        "delgado",
        "bajo peso",
        "sobrepeso",
        "obesidad",
        "secreción",
        "balanopostitis",
        "retenido",
        "asimétrico",
        "aumentada o dolor",
        "dermatitis",
        "hinchazón",
        "nódulos",
        "galactorrea",
        "claudicación",
        "renguea",
        "dificultad para levantarse",
        "rigidez",
        "ataxia",
    ]
    safe_words = {
        "ninguno",
        "ninguno presente",
        "no presente",
        "negativo",
        "vacío",
        "normal",
        "normal / coordinada",
        "normales descendidos",
        "normal (sin nódulos)",
        "parece normal",
        "excelente",
        "buena",
        "perfecto",
        "4-5: peso ideal",
        "4/9: peso ideal",
        "5/9: peso ideal",
        "mantener dieta y porción actual (peso ideal)",
        "dentro de límites normales",
        "rosas y húmedas",
        "sin pulgas: continuar o iniciar prevención",
        "no evaluado",
        "no realizado",
        "no aplica",
        "no palpable",
        "pendiente",
    }

    def check(label: str, val):
        if not val:
            return
        val_str = str(val).strip().lower()
        if val_str in safe_words:
            return
        for t in triggers:
            if t in val_str:
                atencion.append(label.lower())
                break

    check("coloración de mucosas", d.get("mucosas"))
    check("condición general", d.get("cond_gral"))
    check("condición de peso", d.get("peso"))
    check("condición corporal (BCS)", d.get("bcs_escala"))
    check("pelo y piel", d.get("pelo_piel"))
    if d.get("planos_por_lesion"):
        atencion.append("lesiones dermatológicas")
    check("presencia de ectoparásitos", d.get("ectoparasitos"))
    check("control de pulgas", d.get("c_pulgas"))
    check("hígado", d.get("hig"))
    check("estómago", d.get("est"))
    check("bazo", d.get("bazo"))
    check("riñones", d.get("rd"))
    check("riñones", d.get("ri"))
    check("intestinos o mesenterio", d.get("int_mes"))
    # Sección 4 Urogenital (General + Específico por sexo)
    check("tracto urogenital", d.get("secr_uro"))
    check("tracto urogenital", d.get("infl_uro"))
    check("bultos urogenitales", d.get("bult_uro"))
    check("glándulas mamarias", d.get("tum_mam"))
    if d.get("sexo") == "Macho":
        check("pene y prepucio", d.get("uro_pene_prepucio"))
        if d.get("estado_reproductivo") == "Entero(a)":
            check("testículos y escroto", d.get("uro_testiculos"))
        if d.get("especie") == "Canino":
            check("próstata", d.get("uro_prostata_macho"))
    elif d.get("sexo") == "Hembra":
        check("vulva y área perivulvar", d.get("uro_vulva"))
        check("cadena mamaria", d.get("uro_cadena_mamaria"))

    check("próstata o recto", d.get("pros"))
    check("región rectal", d.get("tum_rect"))
    check("hernias", d.get("hern"))
    check("sacos anales", d.get("sacos"))
    check("enfermedad periodontal", d.get("epo"))
    check("sarro", d.get("sarro"))
    check("mordida", d.get("mord"))
    check("encías", d.get("hinc_e"))
    check("encías", d.get("retr_e"))
    check("encías", d.get("inf_e"))
    check("épulis o masas orales", d.get("epul_e"))
    check("amígdalas", d.get("inf_a"))
    check("amígdalas", d.get("hinc_a"))
    check("lengua", d.get("inf_l"))
    check("nódulos linfáticos", d.get("tal_n"))
    check("nódulos linfáticos", d.get("con_n"))
    for k_od in ("conj_od", "sec_od", "def_od", "tum_od"):
        check("alteración ocular (OD)", d.get(k_od))
    for k_oi in ("conj_oi", "sec_oi", "def_oi", "tum_oi"):
        check("alteración ocular (OI)", d.get(k_oi))

    # Auditoría de Tonometría (PIO 10 - 25 mmHg)
    for eye_lbl, pio_key in (("presión intraocular (OD)", "pio_od"), ("presión intraocular (OI)", "pio_oi")):
        pio_raw = clean_text(d.get(pio_key, ""))
        if pio_raw:
            m_pio = re.search(r"(\d+(?:\.\d+)?)", pio_raw)
            if m_pio:
                val_pio = float(m_pio.group(1))
                if val_pio < 10.0 or val_pio > 25.0:
                    atencion.append(eye_lbl)

    for k_oto in (
        "ore_od",
        "tim_od",
        "aca_od",
        "tum_oido_od",
        "inf_oido_od",
        "sec_oido_od",
        "ore_oi",
        "tim_oi",
        "aca_oi",
        "tum_oido_oi",
        "inf_oido_oi",
        "sec_oido_oi",
    ):
        check("examen otoscópico", d.get(k_oto))
    for k_msk in ("cue", "esp", "cola", "mad", "mai", "mpd", "mpi"):
        check("sistema musculoesquelético", d.get(k_msk))
    check("evaluación de la marcha", d.get("tipo_marcha"))
    for k_neuro in ("ment", "cran", "prop", "patel", "dolor"):
        check("examen neurológico", d.get(k_neuro))
    check("frecuencia cardiovascular", d.get("f_car"))
    check("pulso", d.get("pul_car"))
    check("soplo", d.get("sop_car"))
    check("ritmo cardiaco", d.get("rit_car"))
    for k_pul in ("cd", "cad", "ci", "cai"):
        check("campos pulmonares", d.get(k_pul))
    check("leucemia felina", d.get("leu"))
    check("SIDA felino", d.get("sida"))
    check("hemoparásitos", d.get("hemo"))
    for k_cop in ("tox", "coc", "nem", "gia", "gyp", "ces"):
        check("examen coproparasitoscópico", d.get(k_cop))
    for k_lab in ("eritrocitos", "leucocitos_s", "tiroides", "enz_ren", "enz_hep", "enz_pan", "electrolitos", "prot_ser"):
        check("análisis sanguíneo", d.get(k_lab))
    for k_uro in (
        "uro_urobilinogeno",
        "uro_sangre",
        "uro_bilirrubina",
        "uro_cetona",
        "uro_proteina",
        "uro_ph",
        "uro_gravedad",
        "sed_eritrocitos",
        "sed_leucocitos",
        "sed_bacterias",
        "sed_cilindros",
    ):
        check("uroanálisis / sedimento", d.get(k_uro))

    return list(dict.fromkeys(atencion))


def generar_resumen_narrativo(d: dict, styles: dict) -> list:
    if d.get("_is_blank_template"):
        p_txt = (
            "<b>Dictamen general del Examen Semestral (Generado automáticamente por el sistema según hallazgos):</b><br/><br/>"
            "[  ] <b>Exploración satisfactoria:</b> Todas las constantes vitales y sistemas evaluados se encuentran dentro de parámetros saludables y normales.<br/><br/>"
            "[  ] <b>Áreas que requieren monitoreo o atención médica específica:</b><br/>"
            "____________________________________________________________________________________________________________<br/>"
            "____________________________________________________________________________________________________________"
        )
        return [Paragraph(p_txt, styles["Plan"])]

    atencion = extraer_hallazgos_atencion(d)
    elements = []
    if not atencion:
        p_txt = (
            "Nos complace informarle que la exploración clínica de su mascota fue muy satisfactoria. "
            "Todas las constantes vitales y los sistemas corporales evaluados durante este examen semestral "
            "se encuentran dentro de parámetros saludables y normales. Sugerimos continuar con su plan de "
            "medicina preventiva para mantener este excelente estado de salud."
        )
    else:
        p_txt = (
            "Nos complace informarle que la gran mayoría de los sistemas y constantes fisiológicas de su mascota "
            "se encuentran estables. Sin embargo, durante la exploración clínica sistemática hemos detectado algunas "
            "áreas de oportunidad que requieren monitoreo o atención médica, específicamente en: <b>"
        )
        if len(atencion) > 1:
            p_txt += ", ".join(atencion[:-1]) + f" y {atencion[-1]}."
        else:
            p_txt += f"{atencion[0]}."
        p_txt += (
            "</b><br/><br/>Le sugerimos apegarse a las recomendaciones terapéuticas y al plan médico detallado "
            "en este reporte para garantizar la calidad de vida y el bienestar de su mascota."
        )

    elements.append(Paragraph(p_txt, styles["Plan"]))
    return elements


def cover_footer(canvas, doc):
    canvas.saveState()
    page_w, _ = letter
    icons = [
        "Vacunas.png",
        "Acaros (2).png",
        "Dental.png",
        "Condicion General.png",
        "Estetoscopio_c.png",
        "OWP_Puppy.png",
        "OWP_Gatito.png",
        "OWP.png",
    ]
    start_x = 40
    available_w = page_w - 80
    spacing = available_w / len(icons)
    for i, ico in enumerate(icons):
        path = asset_path(ico)
        if path:
            cx = start_x + (spacing * i) + (spacing / 2)
            canvas.drawImage(
                str(path),
                cx - 20,
                20,
                width=40,
                height=40,
                mask="auto",
                preserveAspectRatio=True,
            )
    canvas.setFillColor(colors.HexColor("#9FA7B5"))
    canvas.circle(page_w / 2, 20, 12, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawCentredString(page_w / 2, 16, "1")
    canvas.restoreState()


def regular_footer(canvas, doc):
    canvas.saveState()
    page_w, page_h = letter
    b_ico = asset_path("Banfield_ico.png")
    if b_ico:
        canvas.drawImage(
            str(b_ico),
            page_w - 70,
            page_h - 60,
            width=40,
            height=40,
            mask="auto",
            preserveAspectRatio=True,
        )
    canvas.setStrokeColor(colors.HexColor(BANFIELD_ORANGE))
    canvas.setLineWidth(2)
    canvas.line(40, 32, page_w - 40, 32)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(colors.HexColor(BANFIELD_BLUE))
    canvas.drawString(40, 19, "Banfield Pet Hospital de México")
    canvas.drawRightString(page_w - 40, 19, f"Página {doc.page}")
    canvas.restoreState()


def build_pdf(data: dict, two_column_grid: bool = True, hide_unassessed: bool = False) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=85,
        bottomMargin=60,
        title=f"Reporte PBB - {data['mascota']}",
    )

    base_styles = getSampleStyleSheet()
    styles = {
        "CoverBoxTitle": ParagraphStyle(
            "CBoxT",
            parent=base_styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            textColor=colors.HexColor(BANFIELD_BLUE),
            alignment=TA_CENTER,
        ),
        "CoverBoxSub": ParagraphStyle(
            "CBoxS",
            parent=base_styles["Heading2"],
            fontName="Helvetica",
            fontSize=15,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "CoverData": ParagraphStyle(
            "CData",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=16,
            textColor=colors.HexColor(BANFIELD_BLUE),
            spaceAfter=15,
        ),
        "CoverBody": ParagraphStyle(
            "CBody",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            alignment=TA_LEFT,
            textColor=colors.HexColor(BANFIELD_BLUE),
            spaceAfter=8,
        ),
        "CoverBullet": ParagraphStyle(
            "CBullet",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            leftIndent=20,
            textColor=colors.HexColor(BANFIELD_BLUE),
            spaceAfter=4,
        ),
        "Title": ParagraphStyle(
            "BanfieldTitle",
            parent=base_styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=15,
            textColor=colors.HexColor(BANFIELD_BLUE),
            alignment=TA_LEFT,
            spaceAfter=10,
        ),
        "Section": ParagraphStyle(
            "BanfieldSection",
            parent=base_styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=colors.HexColor(BANFIELD_ORANGE),
            spaceBefore=6,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "GroupHeader": ParagraphStyle(
            "BanfieldGroupHeader",
            parent=base_styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor(BANFIELD_BLUE),
        ),
        "Body": ParagraphStyle(
            "BanfieldBody",
            parent=base_styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor(DARK_GREY),
        ),
        "Small": ParagraphStyle(
            "BanfieldSmall",
            parent=base_styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor(DARK_GREY),
        ),
        "Plan": ParagraphStyle(
            "BanfieldPlan",
            parent=base_styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor(DARK_GREY),
        ),
        "Bullet": ParagraphStyle(
            "BulletList",
            parent=base_styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor(DARK_GREY),
        ),
        "InfoBox": ParagraphStyle(
            "InfoBoxText",
            parent=base_styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor(DARK_GREY),
        ),
    }

    story = []

    # --- ESPACIADOR NEGATIVO SOLO EN LA CARÁTULA (DISEÑO ORIGINAL PRESERVADO) ---
    story.append(Spacer(1, -45))

    # ================= CARÁTULA ORIGINAL CON IMAGEN PBB AL CENTRO =================
    logo_unam = asset_path("Banfield-Pet-Hospital.png")
    if logo_unam:
        try:
            img = Image(str(logo_unam), width=250, height=65, kind="proportional")
            logo_table = Table([["", img]], colWidths=[270, 250])
            logo_table.setStyle(TableStyle([("ALIGN", (1, 0), (1, 0), "RIGHT")]))
            story.append(logo_table)
            story.append(Spacer(1, 15))
        except Exception:
            pass

    pbb_logo = asset_path("PBB.jpg")
    img_pbb = (
        Image(str(pbb_logo), width=170, height=170, kind="proportional")
        if pbb_logo
        else ""
    )
    title_p = Paragraph("PLAN DE BIENESTAR BANFIELD ®", styles["CoverBoxTitle"])

    box_header = Table([[title_p], [img_pbb]], colWidths=[520])
    box_header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(box_header)

    subtitle_p = Paragraph("Reporte y hallazgos del Examen Semestral", styles["CoverBoxSub"])
    box_blue = Table([[subtitle_p]], colWidths=[420])
    box_blue.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(BANFIELD_BLUE)),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    wrapper_blue = Table([[box_blue]], colWidths=[520], hAlign="CENTER")
    wrapper_blue.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story.append(wrapper_blue)
    story.append(Spacer(1, 15))

    c_data = (
        f"Mascota: {ptext(data['mascota'])} (Especie: {ptext(data['especie'])} · "
        f"Sexo: {ptext(data.get('sexo', ''))} · {ptext(data.get('estado_reproductivo', ''))})<br/>"
        f"Propietario: {ptext(data['familia'])}<br/>"
        f"Edad: {ptext(data['edad'])}<br/>"
        f"Fecha: {ptext(data['fecha'])}"
    )
    story.append(Paragraph(c_data, styles["CoverData"]))

    txt_intro = (
        "Esta valoración médica rutinaria es uno de los cimientos de nuestros "
        "<b>Planes de Bienestar Banfield ®</b> y forma parte de nuestra filosofía de "
        "<b>Medicina Preventiva</b>, la cual se compone de 6 pilares:"
    )
    story.append(Paragraph(txt_intro, styles["CoverBody"]))

    for b in [
        "La vacunación",
        "La desparasitación",
        "El cuidado dental",
        "La nutrición",
        "La detección temprana de enfermedades asociadas a la raza",
        "El sano desarrollo de la conducta de su mascota",
    ]:
        story.append(Paragraph(f"• {b}", styles["CoverBullet"]))

    story.append(Spacer(1, 10))
    txt_out = (
        "Junto con usted, cumplimos nuestra misión: "
        "<b>crear un mundo mejor para las mascotas para poder amarlas más tiempo.</b>"
        "<br/><br/><b>Gracias por su colaboración.</b>"
    )
    story.append(Paragraph(txt_out, styles["CoverBody"]))
    story.append(PageBreak())

    # ================= RESULTADOS CLÍNICOS =================
    story.append(Paragraph("RESULTADOS DEL EXAMEN FÍSICO", styles["Title"]))

    s_constantes = [
        ("Peso", f"{ptext(data['peso_kg'])} kg"),
        ("Frecuencia cardiaca", f"{ptext(data['fc'])} lpm"),
        ("Frecuencia respiratoria", f"{ptext(data['fr'])} rpm"),
        ("Temperatura", f"{ptext(data['temp'])} °C"),
        ("TLLC", f"{ptext(data['tllc'])} segundos"),
        ("Mucosas", f"{ptext(data['mucosas'])}"),
        ("SpO2", f"{ptext(data['spo2'])}"),
        ("PAM", f"{ptext(data['pam'])}"),
    ]
    add_section_pdf(
        story,
        "Constantes Fisiológicas",
        [("Evaluación Fisiológica", s_constantes)],
        styles,
        None,
        notes=data.get("notas_constantes"),
        photo_list=data.get("foto_constantes"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    s1_cond = [
        ("Condición general", f"{ptext(data['cond_gral'])}"),
        ("Condición de peso", f"{ptext(data['peso'])}"),
        ("Condición Corporal (BCS 1-9)", f"{ptext(data.get('bcs_escala'))}"),
    ]
    s1_nutri = []
    if clean_text(data.get("plan_nutricional")):
        s1_nutri.append(("Indicaciones de dieta / porción", f"{ptext(data.get('plan_nutricional'))}"))
    if data["alim_seco"] and clean_text(data["alim_seco"]):
        s1_nutri.append(("Alimento seco", f"{ptext(data['alim_seco'])}"))
    if data["alim_humedo"] and clean_text(data["alim_humedo"]):
        s1_nutri.append(("Alimento húmedo", f"{ptext(data['alim_humedo'])}"))
    if data["nutra"] and clean_text(data["nutra"]):
        s1_nutri.append(("Nutracéuticos", f"{ptext(data['nutra'])}"))

    s1_agrupado = [("Condición Corporal", s1_cond)]
    if s1_nutri:
        s1_agrupado.append(("Nutrición", s1_nutri))
    add_section_pdf(
        story,
        "Sección 1 Condición general",
        s1_agrupado,
        styles,
        "Examen.png",
        notes=data.get("notas_s1"),
        photo_list=data.get("foto_s1"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    s2_derma = [("Pelo y piel", f"{ptext(data['pelo_piel'])}")]
    if data["planos_por_lesion"]:
        s2_derma.append(("Lesiones y planos afectados", "<br/>".join(data["planos_por_lesion"])))
    if data["rec_piel"] and clean_text(data["rec_piel"]):
        s2_derma.append(("Producto dermatológico", f"{ptext(data['rec_piel'])}"))
    if data["shampoo_rec"] and clean_text(data["shampoo_rec"]):
        s2_derma.append(("Shampoo sugerido", f"{ptext(data['shampoo_rec'])}"))

    s2_paras = [
        ("Ectoparásitos", f"{ptext(data['ectoparasitos'])}"),
        ("Control recetado", f"{ptext(data['c_pulgas'])}"),
    ]
    if data["trat_pulgas"]:
        plan_str = ptext(data["trat_pulgas"]).replace("\n", "<br/>")
        s2_paras.append(("Plan a seguir", plan_str))

    add_section_pdf(
        story,
        "Sección 2 Pelo y Piel",
        [("Dermatología", s2_derma), ("Control Parasitario", s2_paras)],
        styles,
        "Pelo y piel.png",
        data["notas_s2"],
        photo_list=data.get("foto_s2"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    s3_abd = [
        ("Hígado", f"{ptext(data['hig'])}"),
        ("Estómago", f"{ptext(data['est'])}"),
        ("Bazo", f"{ptext(data['bazo'])}"),
    ]
    s3_rin = [
        ("Riñón derecho", f"{ptext(data['rd'])}"),
        ("Riñón izquierdo", f"{ptext(data['ri'])}"),
    ]
    s3_int = [
        ("Intestinos / mesenterio", f"{ptext(data['int_mes'])}"),
        ("Impresión general", f"{ptext(data['imp_gral'])}"),
    ]
    add_section_pdf(
        story,
        "Sección 3 Palpación abdominal",
        [
            ("Palpación Abdominal", s3_abd),
            ("Riñones", s3_rin),
            ("Intestinos y Anexos", s3_int),
        ],
        styles,
        "Estetoscopio_c.png",
        data["notas_s3"],
        photo_list=data.get("foto_s3"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    s4_uro = [
        ("Secreción urogenital", f"{ptext(data['secr_uro'])}"),
        ("Inflamación / infección", f"{ptext(data['infl_uro'])}"),
        ("Bultos / crecimientos", f"{ptext(data['bult_uro'])}"),
        ("Tumores mamarios", f"{ptext(data['tum_mam'])}"),
    ]
    # Campos condicionales por Sexo / Estado Reproductivo / Especie
    if data.get("sexo") == "Macho":
        s4_uro.append(("Pene y prepucio", f"{ptext(data.get('uro_pene_prepucio'))}"))
        if data.get("estado_reproductivo") == "Entero(a)":
            s4_uro.append(("Testículos y escroto", f"{ptext(data.get('uro_testiculos'))}"))
        if data.get("especie") == "Canino":
            s4_uro.append(("Evaluación de próstata", f"{ptext(data.get('uro_prostata_macho'))}"))
    elif data.get("sexo") == "Hembra":
        s4_uro.append(("Vulva y área perivulvar", f"{ptext(data.get('uro_vulva'))}"))
        cad_mam = ptext(data.get("uro_cadena_mamaria"))
        if clean_text(data.get("uro_detalle_mamas")):
            cad_mam += f" ({ptext(data.get('uro_detalle_mamas'))})"
        s4_uro.append(("Cadena mamaria individualizada", cad_mam))
        if data.get("estado_reproductivo") == "Entero(a)":
            s4_uro.append(("Fecha aprox. de último celo", f"{ptext(data.get('uro_ultimo_celo'))}"))

    add_section_pdf(
        story,
        "Sección 4 Examen Urogenital",
        [("Examen Urogenital", s4_uro)],
        styles,
        notes=data.get("notas_s4"),
        photo_list=data.get("foto_s4"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    s5_rect = [
        ("Próstata / recto", f"{ptext(data['pros'])}"),
        ("Tumores / crecimientos", f"{ptext(data['tum_rect'])}"),
        ("Hernias / hinchazón", f"{ptext(data['hern'])}"),
        ("Sacos anales", f"{ptext(data['sacos'])}"),
    ]
    add_section_pdf(
        story,
        "Sección 5 Examen Rectal",
        [("Examen Rectal", s5_rect)],
        styles,
        notes=data.get("notas_s5"),
        photo_list=data.get("foto_s5"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    s6_dientes = [
        ("Enfermedad Periodontal (EPO)", f"{ptext(data['epo'])}"),
        ("Sarro", f"{ptext(data['sarro'])}"),
        ("Mordida", f"{ptext(data['mord'])}"),
        ("Decoloración dental", f"{ptext(data['decol_d'])}"),
    ]
    s6_encias = [
        ("Hinchazón de encías", f"{ptext(data['hinc_e'])}"),
        ("Encías retraídas", f"{ptext(data['retr_e'])}"),
        ("Infección de encías", f"{ptext(data['inf_e'])}"),
        ("Tumores / épulis", f"{ptext(data['epul_e'])}"),
    ]
    s6_boca = [
        ("Amígdalas (Inflamación)", f"{ptext(data['inf_a'])}"),
        ("Amígdalas (Hinchazón)", f"{ptext(data['hinc_a'])}"),
        ("Lengua (Inflamación)", f"{ptext(data['inf_l'])}"),
        ("Lengua (Decoloración)", f"{ptext(data['dec_l'])}"),
        ("Lengua (Hinchazón)", f"{ptext(data['hinc_l'])}"),
        ("Nódulos linfáticos", f"{ptext(data['tal_n'])}"),
        ("Consistencia de nódulos", f"{ptext(data['con_n'])}"),
        ("Inflamación de garganta", f"{ptext(data['inf_g'])}"),
        ("Reflejos faríngeos", f"{ptext(data['ref_g'])}"),
    ]
    s6_agrupado = [
        ("Dientes y Enfermedad", s6_dientes),
        ("Encías", s6_encias),
        ("Amígdalas, Lengua y Garganta", s6_boca),
    ]
    if data["rec_dental"] and clean_text(data["rec_dental"]):
        s6_agrupado.append(
            ("Recomendación Médica", [("Producto(s) sugerido(s)", f"{ptext(data['rec_dental'])}")])
        )

    add_section_pdf(
        story,
        "Sección 6 Examen Dental/Oral",
        s6_agrupado,
        styles,
        "Dental.png",
        data["notas_s6"],
        photo_list=data.get("foto_s6"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )
    add_info_box(
        story,
        "Nota Dental",
        "La Enfermedad Periodontal (EPO) se clasifica en grados. El Grado I indica gingivitis leve, mientras que los Grados II a IV implican pérdida progresiva de la adherencia dental, pérdida ósea y riesgo de infecciones sistémicas.",
        styles,
    )

    pio_od_str = f"{ptext(data.get('pio_od'))} mmHg (Ref. 10-25)" if clean_text(data.get("pio_od")) else "—"
    pio_oi_str = f"{ptext(data.get('pio_oi'))} mmHg (Ref. 10-25)" if clean_text(data.get("pio_oi")) else "—"

    s7_od = [
        ("Conjuntiva OD", f"{ptext(data['conj_od'])}"),
        ("Secreción OD", f"{ptext(data['sec_od'])}"),
        ("Deformidad párpados OD", f"{ptext(data['def_od'])}"),
        ("Tumores/quistes OD", f"{ptext(data['tum_od'])}"),
        ("Presión Intraocular (PIO) OD", pio_od_str),
    ]
    s7_oi = [
        ("Conjuntiva OI", f"{ptext(data['conj_oi'])}"),
        ("Secreción OI", f"{ptext(data['sec_oi'])}"),
        ("Deformidad párpados OI", f"{ptext(data['def_oi'])}"),
        ("Tumores/quistes OI", f"{ptext(data['tum_oi'])}"),
        ("Presión Intraocular (PIO) OI", pio_oi_str),
    ]
    s7_agrupado = [("Oftálmico (Ojo Derecho)", s7_od), ("Oftálmico (Ojo Izquierdo)", s7_oi)]
    if data["rec_oftalmica"] and clean_text(data["rec_oftalmica"]):
        s7_agrupado.append(
            ("Recomendación", [("Producto oftalmológico", f"{ptext(data['rec_oftalmica'])}")])
        )
    add_section_pdf(
        story,
        "Sección 7 Examen Oftálmico",
        s7_agrupado,
        styles,
        notes=data.get("notas_s7"),
        photo_list=data.get("foto_s7"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    s8_od = [
        ("Orejas OD", f"{ptext(data['ore_od'])}"),
        ("Membrana timpánica OD", f"{ptext(data['tim_od'])}"),
        ("Ácaros OD", f"{ptext(data['aca_od'])}"),
        ("Tumores/quistes OD", f"{ptext(data['tum_oido_od'])}"),
        ("Inflamación OD", f"{ptext(data['inf_oido_od'])}"),
        ("Secreción ótica OD", f"{ptext(data['sec_oido_od'])}"),
    ]
    s8_oi = [
        ("Orejas OI", f"{ptext(data['ore_oi'])}"),
        ("Membrana timpánica OI", f"{ptext(data['tim_oi'])}"),
        ("Ácaros OI", f"{ptext(data['aca_oi'])}"),
        ("Tumores/quistes OI", f"{ptext(data['tum_oido_oi'])}"),
        ("Inflamación OI", f"{ptext(data['inf_oido_oi'])}"),
        ("Secreción ótica OI", f"{ptext(data['sec_oido_oi'])}"),
    ]
    s8_agrupado = [("Otoscópico (Oído Derecho)", s8_od), ("Otoscópico (Oído Izquierdo)", s8_oi)]
    if data["rec_otica"] and clean_text(data["rec_otica"]):
        s8_agrupado.append(
            ("Recomendación", [("Producto otológico", f"{ptext(data['rec_otica'])}")])
        )
    add_section_pdf(
        story,
        "Sección 8 Examen Otoscópico",
        s8_agrupado,
        styles,
        "Orejas.png",
        notes=data.get("notas_s8"),
        photo_list=data.get("foto_s8"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    s9_col = [
        ("Cuello y cabeza", f"{ptext(data['cue'])}"),
        ("Espalda", f"{ptext(data['esp'])}"),
        ("Cola", f"{ptext(data['cola'])}"),
    ]
    s9_mie = [
        ("Miembro anterior derecho", f"{ptext(data['mad'])}"),
        ("Miembro anterior izquierdo", f"{ptext(data['mai'])}"),
        ("Miembro posterior derecho", f"{ptext(data['mpd'])}"),
        ("Miembro posterior izquierdo", f"{ptext(data['mpi'])}"),
    ]
    s9_marcha = [("Tipo de marcha", f"{ptext(data.get('tipo_marcha'))}")]
    if any(
        w in str(data.get("tipo_marcha", ""))
        for w in ("Claudicación / Renguea", "Dificultad para levantarse / Rigidez")
    ):
        if clean_text(data.get("miembro_claudicacion")):
            s9_marcha.append(("Miembro(s) afectado(s)", f"{ptext(data.get('miembro_claudicacion'))}"))
        if clean_text(data.get("grado_claudicacion")):
            s9_marcha.append(("Grado de claudicación (1-5)", f"{ptext(data.get('grado_claudicacion'))}"))

    s9_agrupado = [
        ("Columna y Anexos", s9_col),
        ("Miembros", s9_mie),
        ("Evaluación de la Marcha y Claudicación", s9_marcha),
    ]
    add_section_pdf(
        story,
        "Sección 9 Examen Musculoesquelético",
        s9_agrupado,
        styles,
        "Musculoesqueletico.png",
        notes=data.get("notas_s9"),
        photo_list=data.get("foto_s9"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    s10_gral = [
        ("Estado mental", f"{ptext(data['ment'])}"),
        ("Nervios craneales", f"{ptext(data['cran'])}"),
    ]
    s10_ref = [
        ("Reflejos propioceptivos", f"{ptext(data['prop'])}"),
        ("Reflejos patelares", f"{ptext(data['patel'])}"),
        ("Dolor a la digitopresión", f"{ptext(data['dolor'])}"),
        ("Región del dolor", f"{ptext(data['reg_dolor'])}"),
    ]
    add_section_pdf(
        story,
        "Sección 10 Examen Neurológico",
        [("Neurológico General", s10_gral), ("Reflejos y Dolor", s10_ref)],
        styles,
        notes=data.get("notas_s10"),
        photo_list=data.get("foto_s10"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    s11_cv = [
        ("Frecuencia cardiovascular", f"{ptext(data['f_car'])}"),
        ("Pulso", f"{ptext(data['pul_car'])}"),
        ("Soplo o sonido anormal", f"{ptext(data['sop_car'])}"),
        ("Ritmo", f"{ptext(data['rit_car'])}"),
        ("TLLC cardiovascular", f"{ptext(data['tllc_car'])}"),
    ]
    add_section_pdf(
        story,
        "Sección 11 Cardiovascular/Corazón",
        [("Evaluación Cardiovascular", s11_cv)],
        styles,
        "Corazon.png",
        notes=data.get("notas_s11"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    s12_pul = [
        ("Craneal derecho", f"{ptext(data['cd'])}"),
        ("Caudal derecho", f"{ptext(data['cad'])}"),
        ("Craneal izquierdo", f"{ptext(data['ci'])}"),
        ("Caudal izquierdo", f"{ptext(data['cai'])}"),
    ]
    add_section_pdf(
        story,
        "Sección 12 Campos pulmonares",
        [("Campos Pulmonares", s12_pul)],
        styles,
        None,
        data["notas_s12"],
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    if data["especie"] == "Felino":
        s13_items = [
            ("Leucemia felina", f"{ptext(data['leu'])}"),
            ("SIDA felino", f"{ptext(data['sida'])}"),
        ]
    else:
        s13_items = [("Hemoparásitos caninos", f"{ptext(data['hemo'])}")]

    add_section_pdf(
        story,
        "Sección 13 Pruebas sanguíneas virales / vectoriales",
        [("Pruebas Específicas", s13_items)],
        styles,
        "5.png",
        notes=data.get("notas_s13"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    s14_items = [
        ("Toxocara", f"{ptext(data['tox'])}"),
        ("Coccidia", f"{ptext(data['coc'])}"),
        ("Nemátodos", f"{ptext(data['nem'])}"),
        ("Giardia", f"{ptext(data['gia'])}"),
        ("Dypilidium", f"{ptext(data['gyp'])}"),
        ("Céstodos", f"{ptext(data['ces'])}"),
    ]
    add_section_pdf(
        story,
        "Sección 14 Hallazgos en examen de excremento",
        [("Examen de Excremento", s14_items)],
        styles,
        notes=data.get("notas_s14"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    s15_hemo = [
        ("Conteo de eritrocitos", f"{ptext(data['eritrocitos'])}"),
        ("Conteo de leucocitos", f"{ptext(data['leucocitos_s'])}"),
        ("Prueba de Tiroides", f"{ptext(data['tiroides'])}"),
        ("Enzimas renales", f"{ptext(data['enz_ren'])}"),
        ("Enzimas hepáticas", f"{ptext(data['enz_hep'])}"),
        ("Enzimas pancreáticas", f"{ptext(data['enz_pan'])}"),
        ("Electrólitos", f"{ptext(data['electrolitos'])}"),
        ("Proteínas séricas", f"{ptext(data['prot_ser'])}"),
    ]
    s15_uro = [
        ("Urobilinógeno", f"{ptext(data['uro_urobilinogeno'])}"),
        ("Sangre (Uroanálisis)", f"{ptext(data['uro_sangre'])}"),
        ("Bilirrubina", f"{ptext(data['uro_bilirrubina'])}"),
        ("Cetona", f"{ptext(data['uro_cetona'])}"),
        ("Proteína (Uroanálisis)", f"{ptext(data['uro_proteina'])}"),
        ("pH", f"{ptext(data['uro_ph'])}"),
        ("Gravedad específica", f"{ptext(data['uro_gravedad'])}"),
    ]
    s15_sed = [
        ("Sedimento: Eritrocitos", f"{ptext(data['sed_eritrocitos'])}"),
        ("Sedimento: Leucocitos", f"{ptext(data['sed_leucocitos'])}"),
        ("Bacterias", f"{ptext(data['sed_bacterias'])}"),
        ("Cilindros renales", f"{ptext(data['sed_cilindros'])} (Tipo: {ptext(data['tipo_cilindros'])})"),
    ]
    add_section_pdf(
        story,
        "Sección 15 Análisis de sangre y Uroanálisis",
        [
            ("Hemograma y Química Sanguínea", s15_hemo),
            ("Uroanálisis", s15_uro),
            ("Sedimento Urinario", s15_sed),
        ],
        styles,
        "5.png",
        data["notas_uro"],
        photo_list=data.get("foto_lab"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
    )

    add_info_box(
        story,
        "Nota Preventiva",
        "Los análisis sanguíneos y el uroanálisis nos permiten establecer una línea base de la función interna de los órganos (como riñones e hígado), ayudándonos a detectar enfermedades sistémicas antes de que presenten síntomas visibles.",
        styles,
    )

    vac_items = []
    if data["vac_raw_data"]:
        for vac_info in data["vac_raw_data"]:
            vac_items.append(
                ListItem(
                    Paragraph(html.escape(vac_info), styles["Bullet"]),
                    leftIndent=15,
                    spaceAfter=2,
                )
            )
    flow_vac = (
        ListFlowable(vac_items, bulletType="bullet", start="bulletchar")
        if vac_items
        else Paragraph("—", styles["Small"])
    )

    s16_items = [
        ("Vacunas aplicadas", flow_vac),
        ("Desparasitante Interno", f"{ptext(data['desp_interno_seleccionado'])}"),
    ]
    img_prev = "OWP_Puppy.png" if data["especie"] == "Canino" else "OWP_Gatito.png"
    add_section_pdf(
        story,
        "Sección 16 Cuidado preventivo aplicado en esta visita",
        [("Medicina Preventiva", s16_items)],
        styles,
        img_prev,
        notes=data.get("notas_s16"),
        two_column_grid=False,
        hide_unassessed=False,
    )

    story.append(Paragraph("Sección 17 Otras recomendaciones y Comentarios", styles["Section"]))
    plan = data["recomendaciones"].strip() or "Sin recomendaciones registradas."
    plan_table = Table(
        [[Paragraph(ptext(plan).replace("\n", "<br/>"), styles["Plan"])]],
        colWidths=[510],
        hAlign="LEFT",
    )
    plan_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(LIGHT_BLUE)),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0DCE9")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(plan_table)
    story.append(Spacer(1, 12))

    # ================= BLOQUE INDIVISIBLE: SECCIÓN 18 + FIRMAS =================
    final_block = []
    icon_file = asset_path("OWP.png")
    if icon_file:
        try:
            img_path_str = str(icon_file).replace("\\", "/")
            header_html = f"<img src='{img_path_str}' width='20' height='20' valign='middle'/>  Sección 18 Resumen del Examen Semestral Banfield"
            final_block.append(Paragraph(header_html, styles["Section"]))
        except Exception:
            final_block.append(
                Paragraph("Sección 18 Resumen del Examen Semestral Banfield", styles["Section"])
            )
    else:
        final_block.append(
            Paragraph("Sección 18 Resumen del Examen Semestral Banfield", styles["Section"])
        )

    resumen_flowables = generar_resumen_narrativo(data, styles)
    res_table = Table([[resumen_flowables]], colWidths=[510], hAlign="LEFT")
    res_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(LIGHT_BLUE)),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0DCE9")),
                ("LEFTPADDING", (0, 0), (-1, -1), 15),
                ("RIGHTPADDING", (0, 0), (-1, -1), 15),
                ("TOPPADDING", (0, 0), (-1, -1), 15),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 15),
            ]
        )
    )
    final_block.append(res_table)

    firma_str = data["medico"].strip()
    if " - Ced. " in firma_str:
        partes = firma_str.split(" - Ced. ")
        medico_nombre = partes[0]
        medico_cedula = partes[1]
    else:
        medico_nombre = firma_str if firma_str != "Otro" else ""
        medico_cedula = ""

    final_block.append(Spacer(1, 30))
    firma_texto = (
        f"<b>MVZ Responsable:</b> {ptext(medico_nombre)}<br/>"
        f"<b>Cédula Profesional:</b> {ptext(medico_cedula)}"
    )
    final_block.append(Paragraph(firma_texto, styles["Body"]))

    final_block.append(Spacer(1, 30))
    address_style = ParagraphStyle(
        "Address",
        parent=styles["Body"],
        alignment=TA_LEFT,
        textColor=colors.HexColor(BANFIELD_BLUE),
        fontSize=9,
    )
    direccion = (
        "<b>Banfield Pet Hospital México</b><br/>"
        "Av. Antonio Delfín Madrigal S/N Col. Cd. Universitaria, Coyoacán C.P. 04510<br/>"
        "55-5658-6080"
    )
    final_block.append(Paragraph(direccion, address_style))

    story.append(KeepTogether(final_block))

    doc.build(story, onFirstPage=cover_footer, onLaterPages=regular_footer)
    return buffer.getvalue()


def build_blank_pdf(
    especie: str,
    sexo: str,
    estado_reproductivo: str,
    two_column_grid: bool = True,
) -> bytes:
    """
    Genera un reporte PDF 100% EN BLANCO (sin contestar) pero dinámicamente adaptado
    a la Especie (Canino/Felino), Sexo (Macho/Hembra) y Estatus Reproductivo seleccionados,
    mostrando todos los campos clínicos, escalas y casillas para revisión del equipo médico.
    """
    LINE_BLANK = "________________________"
    NOTE_BLANK = "____________________________________________________________________________________"

    blank_data = {
        "_is_blank_template": True,
        "mascota": "________________________",
        "familia": "________________________",
        "edad": "___________",
        "fecha": "____ / ____ / 202___",
        "medico": "________________________________ - Ced. ________________",
        "especie": especie,
        "sexo": sexo,
        "estado_reproductivo": estado_reproductivo,
        # Constantes
        "peso_kg": "________",
        "fc": "________",
        "fr": "________",
        "temp": "________",
        "tllc": "________",
        "mucosas": "[  ] Rosas y húmedas  [  ] Pálidas  [  ] Congestivas  [  ] Ictéricas",
        "spo2": "________ %",
        "pam": "________ mmHg",
        "notas_constantes": NOTE_BLANK,
        # Sección 1
        "cond_gral": "[  ] Excelente   [  ] Buena   [  ] Necesita mejorar",
        "peso": "[  ] Perfecto   [  ] Demasiado delgado   [  ] Muy pesado",
        "bcs_escala": "[  ] 1-3: Delgado/Bajo peso  [  ] 4-5: Peso ideal  [  ] 6-7: Sobrepeso  [  ] 8-9: Obesidad  ( ___ / 9 )",
        "plan_nutricional": "[  ] Mantener dieta y porción actual (peso ideal)   [  ] Ajustar porción / dieta: ______________",
        "alim_seco": LINE_BLANK,
        "alim_humedo": LINE_BLANK,
        "nutra": LINE_BLANK,
        "notas_s1": NOTE_BLANK,
        # Sección 2
        "pelo_piel": "[  ] Parece normal   [  ] Anormal",
        "planos_por_lesion": [
            "[  ] Máculas  [  ] Escamas  [  ] Excoriaciones  [  ] Eritema  [  ] Hiperpigmentación  [  ] Alopecia  [  ] Úlceras",
            "Planos anatómicos afectados: ________________________________________________________",
        ],
        "rec_piel": LINE_BLANK,
        "shampoo_rec": LINE_BLANK,
        "ectoparasitos": "[  ] Ninguno presente   [  ] Pulgas   [  ] Piojos   [  ] Garrapatas",
        "c_pulgas": "[  ] Sin pulgas: continuar prevención   [  ] Tiene pulgas: controlar",
        "trat_pulgas": "Mascota: ____________ | Casa: ____________ | Coche: ____________ | Patio: c/___ sem | Prod: ____________",
        "notas_s2": NOTE_BLANK,
        # Sección 3
        "hig": "[  ] Normal  [  ] Anormal  [  ] No palpable",
        "est": "[  ] Normal  [  ] Anormal  [  ] No palpable",
        "bazo": "[  ] Normal  [  ] Anormal  [  ] No palpable",
        "rd": "[  ] Normal  [  ] Anormal  [  ] No palpable",
        "ri": "[  ] Normal  [  ] Anormal  [  ] No palpable",
        "int_mes": "[  ] Normal  [  ] Anormal  [  ] No palpable",
        "imp_gral": "[  ] Dentro de límites normales   [  ] Anormal",
        "notas_s3": NOTE_BLANK,
        # Sección 4 Urogenital (General + Condicionales según Sexo/Estatus/Especie)
        "secr_uro": "[  ] Negativo   [  ] Positivo",
        "infl_uro": "[  ] Negativo   [  ] Positivo",
        "bult_uro": "[  ] Negativo   [  ] Positivo",
        "tum_mam": "[  ] Negativo   [  ] Positivo",
        "uro_pene_prepucio": "[  ] Normal   [  ] Secreción   [  ] Balanopostitis",
        "uro_testiculos": "[  ] Normales descendidos   [  ] Retenido   [  ] Asimétrico",
        "uro_prostata_macho": "[  ] Normal   [  ] Aumentada o dolor   [  ] No palpable",
        "uro_vulva": "[  ] Normal   [  ] Secreción   [  ] Dermatitis",
        "uro_cadena_mamaria": "[  ] Normal (sin nódulos)   [  ] Nódulos Der   [  ] Nódulos Izq   [  ] Bilateral",
        "uro_detalle_mamas": "Glándulas (M1-M5): __________________",
        "uro_ultimo_celo": "___________________________",
        "notas_s4": NOTE_BLANK,
        # Sección 5
        "pros": "[  ] Normal   [  ] Anormal",
        "tum_rect": "[  ] Negativo   [  ] Positivo",
        "hern": "[  ] Negativo   [  ] Positivo",
        "sacos": "[  ] Vacío   [  ] Normal   [  ] Anormal",
        "notas_s5": NOTE_BLANK,
        # Sección 6
        "epo": "[  ] Negativo   [  ] Grado I   [  ] Grado II   [  ] Grado III   [  ] Grado IV",
        "sarro": "[  ] Negativo   [  ] Positivo",
        "mord": "[  ] Normal   [  ] Anormal",
        "decol_d": "[  ] Negativo   [  ] Positivo",
        "hinc_e": "[  ] Negativo   [  ] Positivo",
        "retr_e": "[  ] Negativo   [  ] Positivo",
        "inf_e": "[  ] Negativo   [  ] Positivo",
        "epul_e": "[  ] Negativo   [  ] Positivo",
        "inf_a": "[  ] Negativo   [  ] Positivo",
        "hinc_a": "[  ] Negativo   [  ] Positivo",
        "inf_l": "[  ] Negativo   [  ] Positivo",
        "dec_l": "[  ] Negativo   [  ] Positivo",
        "hinc_l": "[  ] Negativo   [  ] Positivo",
        "tal_n": "[  ] Normal   [  ] Anormal",
        "con_n": "[  ] Normal   [  ] Anormal",
        "inf_g": "[  ] Negativo   [  ] Positivo",
        "ref_g": "[  ] Normal   [  ] Anormal",
        "rec_dental": LINE_BLANK,
        "notas_s6": NOTE_BLANK,
        # Sección 7
        "conj_od": "[  ] Negativo   [  ] Positivo",
        "sec_od": "[  ] Negativo   [  ] Positivo",
        "def_od": "[  ] Negativo   [  ] Positivo",
        "tum_od": "[  ] Negativo   [  ] Positivo",
        "pio_od": "________",
        "conj_oi": "[  ] Negativo   [  ] Positivo",
        "sec_oi": "[  ] Negativo   [  ] Positivo",
        "def_oi": "[  ] Negativo   [  ] Positivo",
        "tum_oi": "[  ] Negativo   [  ] Positivo",
        "pio_oi": "________",
        "rec_oftalmica": LINE_BLANK,
        "notas_s7": NOTE_BLANK,
        # Sección 8
        "ore_od": "[  ] Normal   [  ] Anormal",
        "tim_od": "[  ] Normal   [  ] Anormal",
        "aca_od": "[  ] Normal   [  ] Anormal",
        "tum_oido_od": "[  ] Normal   [  ] Anormal",
        "inf_oido_od": "[  ] Normal   [  ] Anormal",
        "sec_oido_od": "[  ] Negativo   [  ] Positivo",
        "ore_oi": "[  ] Normal   [  ] Anormal",
        "tim_oi": "[  ] Normal   [  ] Anormal",
        "aca_oi": "[  ] Normal   [  ] Anormal",
        "tum_oido_oi": "[  ] Normal   [  ] Anormal",
        "inf_oido_oi": "[  ] Normal   [  ] Anormal",
        "sec_oido_oi": "[  ] Negativo   [  ] Positivo",
        "rec_otica": LINE_BLANK,
        "notas_s8": NOTE_BLANK,
        # Sección 9
        "cue": "[  ] Normal   [  ] Anormal",
        "esp": "[  ] Normal   [  ] Anormal",
        "cola": "[  ] Normal   [  ] Anormal",
        "mad": "[  ] Normal   [  ] Anormal",
        "mai": "[  ] Normal   [  ] Anormal",
        "mpd": "[  ] Normal   [  ] Anormal",
        "mpi": "[  ] Normal   [  ] Anormal",
        "tipo_marcha": "[  ] Normal / coordinada   [  ] Claudicación / Renguea   [  ] Dificultad para levantarse / Rigidez",
        "miembro_claudicacion": ["[  ] AD   [  ] AI   [  ] PD   [  ] PI   (En caso de claudicación/rigidez)"],
        "grado_claudicacion": "[  ] Grado 1   [  ] Grado 2   [  ] Grado 3   [  ] Grado 4   [  ] Grado 5",
        "notas_s9": NOTE_BLANK,
        # Sección 10
        "ment": "[  ] Normal   [  ] Anormal",
        "cran": "[  ] Normal   [  ] Anormal",
        "prop": "[  ] Normal   [  ] Anormal",
        "patel": "[  ] Normal   [  ] Anormal",
        "dolor": "[  ] Negativo   [  ] Positivo",
        "reg_dolor": LINE_BLANK,
        "notas_s10": NOTE_BLANK,
        # Sección 11
        "f_car": "[  ] Normal   [  ] Anormal",
        "pul_car": "[  ] Normal   [  ] Anormal",
        "sop_car": "[  ] Negativo   [  ] Positivo",
        "rit_car": "[  ] Normal   [  ] Anormal",
        "tllc_car": "[  ] Normal   [  ] Anormal",
        "notas_s11": NOTE_BLANK,
        # Sección 12
        "cd": "[  ] Normal   [  ] Anormal",
        "cad": "[  ] Normal   [  ] Anormal",
        "ci": "[  ] Normal   [  ] Anormal",
        "cai": "[  ] Normal   [  ] Anormal",
        "notas_s12": NOTE_BLANK,
        # Sección 13
        "leu": "[  ] Negativo   [  ] Positivo   [  ] No realizado",
        "sida": "[  ] Negativo   [  ] Positivo   [  ] No realizado",
        "hemo": "[  ] Negativo   [  ] Positivo   [  ] No realizado",
        "notas_s13": NOTE_BLANK,
        # Sección 14
        "tox": "[  ] Neg   [  ] Pos",
        "coc": "[  ] Neg   [  ] Pos",
        "nem": "[  ] Neg   [  ] Pos",
        "gia": "[  ] Neg   [  ] Pos",
        "gyp": "[  ] Neg   [  ] Pos",
        "ces": "[  ] Neg   [  ] Pos",
        "notas_s14": NOTE_BLANK,
        # Sección 15
        "eritrocitos": "[  ] Normal   [  ] Anormal",
        "leucocitos_s": "[  ] Normal   [  ] Anormal",
        "tiroides": "[  ] Normal   [  ] Anormal   [  ] Pendiente",
        "enz_ren": "[  ] Normal   [  ] Anormal",
        "enz_hep": "[  ] Normal   [  ] Anormal",
        "enz_pan": "[  ] Normal   [  ] Anormal",
        "electrolitos": "[  ] Normal   [  ] Anormal",
        "prot_ser": "[  ] Normal   [  ] Anormal",
        "uro_urobilinogeno": "[  ] Normal   [  ] Anormal",
        "uro_sangre": "[  ] Normal   [  ] Anormal",
        "uro_bilirrubina": "[  ] Normal   [  ] Anormal",
        "uro_cetona": "[  ] Normal   [  ] Anormal",
        "uro_proteina": "[  ] Normal   [  ] Anormal",
        "uro_ph": "________",
        "uro_gravedad": "________",
        "sed_eritrocitos": "[  ] No presente   [  ] Presente",
        "sed_leucocitos": "[  ] No presente   [  ] Presente",
        "sed_bacterias": "[  ] No presente   [  ] Presente",
        "sed_cilindros": "[  ] No presente   [  ] Presente",
        "tipo_cilindros": "________________",
        "notas_uro": NOTE_BLANK,
        # Sección 16
        "vac_raw_data": [
            "1) Biológico: ___________________ | Lote: ___________ | Fecha: ___/___/___ | Sitio: [ ] MPD [ ] MPI [ ] MAD [ ] MAI [ ] Interescapular",
            "2) Biológico: ___________________ | Lote: ___________ | Fecha: ___/___/___ | Sitio: [ ] MPD [ ] MPI [ ] MAD [ ] MAI [ ] Interescapular",
            "3) Biológico: ___________________ | Lote: ___________ | Fecha: ___/___/___ | Sitio: [ ] MPD [ ] MPI [ ] MAD [ ] MAI [ ] Interescapular",
        ],
        "desp_interno_seleccionado": LINE_BLANK,
        "notas_s16": NOTE_BLANK,
        # Sección 17
        "recomendaciones": (
            "[  ] Salud Dental: Sugerimos programar una limpieza dental profunda bajo anestesia y radiografías dentales para evaluar raíces por debajo de la encía y prevenir infecciones.\n"
            "[  ] Articulaciones / Marcha: Recomendamos tomar radiografías de evaluación en extremidades y espalda debido a la molestia o rigidez al caminar, valorando protectores articulares.\n"
            "[  ] Oídos / Piel: Sugerimos citología ótica o cutánea para identificar el microorganismo causante de la comezón o secreción y dar el tratamiento exacto.\n"
            "[  ] Peso y Nutrición: Ajustar la porción de alimento y fomentar ejercicio diario para cuidar articulaciones y función cardiaca.\n"
            "[  ] Cirugía Preventiva: Recomendamos programar cirugía de esterilización/castración preventiva para evitar infecciones uterinas o afecciones prostáticas.\n"
            "[  ] Monitoreo de Medicamentos: Sugerimos análisis de sangre y orina periódicos para asegurar que hígado y riñón procesen adecuadamente los tratamientos continuos.\n\n"
            "Otras indicaciones médicas:\n"
            f"{NOTE_BLANK}\n{NOTE_BLANK}"
        ),
    }

    pdf_bytes = build_pdf(blank_data, two_column_grid=two_column_grid, hide_unassessed=False)
    return pdf_bytes


def build_via_text(d: dict) -> str:
    especificas_str = (
        f"LEUCEMIA: {d['leu']} | SIDA FELINO: {d['sida']}"
        if d["especie"] == "Felino"
        else f"HEMOPARASITOS: {d['hemo']}"
    )

    uro_sexo_lines = []
    if d.get("sexo") == "Macho":
        uro_sexo_lines.append(f"PENE Y PREPUCIO: {d.get('uro_pene_prepucio', '')}")
        if d.get("estado_reproductivo") == "Entero(a)":
            uro_sexo_lines.append(f"TESTICULOS Y ESCROTO: {d.get('uro_testiculos', '')}")
        if d.get("especie") == "Canino":
            uro_sexo_lines.append(f"PROSTATA (UROGENITAL): {d.get('uro_prostata_macho', '')}")
    elif d.get("sexo") == "Hembra":
        uro_sexo_lines.append(f"VULVA Y AREA PERIVULVAR: {d.get('uro_vulva', '')}")
        uro_sexo_lines.append(
            f"CADENA MAMARIA: {d.get('uro_cadena_mamaria', '')} {d.get('uro_detalle_mamas', '')}".strip()
        )
        if d.get("estado_reproductivo") == "Entero(a)":
            uro_sexo_lines.append(f"ULTIMO CELO: {d.get('uro_ultimo_celo', '')}")

    lines = [
        "--- DATOS GENERALES ---",
        f"MASCOTA: {d['mascota']} ({d['especie']} | SEXO: {d.get('sexo', '')} | {d.get('estado_reproductivo', '')})",
        f"PROPIETARIO: {d['familia']}",
        f"EDAD: {d['edad']}",
        f"FECHA: {d['fecha']}",
        "--- CONSTANTES FISIOLOGICAS ---",
        f"PESO: {d['peso_kg']} KG",
        f"FC: {d['fc']} LPM",
        f"FR: {d['fr']} RPM",
        f"TEMP: {d['temp']} C",
        f"TLLC: {d['tllc']} S",
        f"MUCOSAS: {d['mucosas']}",
        f"SPO2: {d['spo2']}",
        f"PAM: {d['pam']}",
        f"NOTAS CONSTANTES: {d.get('notas_constantes', '')}",
        "--- SECCION 1 CONDICION GENERAL ---",
        f"CONDICION GENERAL: {d['cond_gral']}",
        f"CONDICION PESO: {d['peso']}",
        f"CONDICION CORPORAL (BCS 1-9): {d.get('bcs_escala', '')}",
        f"INDICACION NUTRICIONAL: {d.get('plan_nutricional', '')}",
        f"ALIMENTO SECO: {clean_text(d['alim_seco'])}",
        f"ALIMENTO HUMEDO: {clean_text(d['alim_humedo'])}",
        f"NUTRACEUTICOS: {clean_text(d['nutra'])}",
        f"NOTAS SECCION 1: {d.get('notas_s1', '')}",
        "--- SECCION 2 PELO Y PIEL ---",
        f"ESTADO GENERAL: {d['pelo_piel']}",
        f"LESIONES Y PLANOS AFECTADOS: {'; '.join(d['planos_por_lesion']) if d['planos_por_lesion'] else ''}",
        f"PRODUCTO DERMATOLOGICO: {clean_text(d['rec_piel'])}",
        f"SHAMPOO SUGERIDO: {clean_text(d['shampoo_rec'])}",
        f"ECTOPARASITOS: {d['ectoparasitos']}",
        f"CONTROL ANTIPULGAS: {d['c_pulgas']}",
        f"PLAN ANTIPULGAS: {d['trat_pulgas'].replace(chr(10), '; ')}",
        f"NOTAS SECCION 2: {d['notas_s2']}",
        "--- SECCION 3 PALPACION ABDOMINAL ---",
        f"HIGADO: {d['hig']}",
        f"ESTOMAGO: {d['est']}",
        f"BAZO: {d['bazo']}",
        f"RINON DERECHO: {d['rd']}",
        f"RINON IZQUIERDO: {d['ri']}",
        f"INTESTINOS: {d['int_mes']}",
        f"IMPRESION ABDOMINAL: {d['imp_gral']}",
        f"NOTAS SECCION 3: {d['notas_s3']}",
        "--- SECCION 4 EXAMEN UROGENITAL ---",
        f"SECRECION: {d['secr_uro']}",
        f"INFLAMACION/INFECCION: {d['infl_uro']}",
        f"BULTOS: {d['bult_uro']}",
        f"TUMORES MAMARIOS: {d['tum_mam']}",
        *uro_sexo_lines,
        f"NOTAS SECCION 4: {d.get('notas_s4', '')}",
        "--- SECCION 5 EXAMEN RECTAL ---",
        f"PROSTATA/RECTO: {d['pros']}",
        f"TUMORES RECTALES: {d['tum_rect']}",
        f"HERNIAS: {d['hern']}",
        f"SACOS ANALES: {d['sacos']}",
        f"NOTAS SECCION 5: {d.get('notas_s5', '')}",
        "--- SECCION 6 EXAMEN DENTAL ---",
        f"ENFERMEDAD PERIODONTAL (EPO): {d['epo']}",
        f"SARRO: {d['sarro']}",
        f"MORDIDA: {d['mord']}",
        f"DECOLORACION: {d['decol_d']}",
        f"HINCHAZON ENCIAS: {d['hinc_e']}",
        f"ENCIAS RETRAIDAS: {d['retr_e']}",
        f"INFECCION ENCIAS: {d['inf_e']}",
        f"EPULIS: {d['epul_e']}",
        f"AMIGDALAS INFLAMADAS: {d['inf_a']}",
        f"AMIGDALAS HINCHADAS: {d['hinc_a']}",
        f"LENGUA INFLAMADA: {d['inf_l']}",
        f"LENGUA DECOLORADA: {d['dec_l']}",
        f"LENGUA HINCHADA: {d['hinc_l']}",
        f"NODULOS TALLA: {d['tal_n']}",
        f"NODULOS CONSISTENCIA: {d['con_n']}",
        f"GARGANTA INFLAMADA: {d['inf_g']}",
        f"REFLEJOS GARGANTA: {d['ref_g']}",
        f"RECOMENDACION DENTAL: {clean_text(d['rec_dental'])}",
        f"NOTAS SECCION 6: {d['notas_s6']}",
        "--- SECCION 7 EXAMEN OFTALMICO ---",
        f"CONJUNTIVA OD: {d['conj_od']}",
        f"SECRECION OD: {d['sec_od']}",
        f"PARPADOS OD: {d['def_od']}",
        f"TUMORES OD: {d['tum_od']}",
        f"PIO OD (MMHG): {d.get('pio_od', '')}",
        f"CONJUNTIVA OI: {d['conj_oi']}",
        f"SECRECION OI: {d['sec_oi']}",
        f"PARPADOS OI: {d['def_oi']}",
        f"TUMORES OI: {d['tum_oi']}",
        f"PIO OI (MMHG): {d.get('pio_oi', '')}",
        f"RECOMENDACION OFTALMICA: {clean_text(d['rec_oftalmica'])}",
        f"NOTAS SECCION 7: {d.get('notas_s7', '')}",
        "--- SECCION 8 EXAMEN OTOSCOPICO ---",
        f"OREJAS OD: {d['ore_od']}",
        f"TIMPANO OD: {d['tim_od']}",
        f"ACAROS OD: {d['aca_od']}",
        f"TUMORES OIDO OD: {d['tum_oido_od']}",
        f"INFLAMACION OIDO OD: {d['inf_oido_od']}",
        f"SECRECION OIDO OD: {d['sec_oido_od']}",
        f"OREJAS OI: {d['ore_oi']}",
        f"TIMPANO OI: {d['tim_oi']}",
        f"ACAROS OI: {d['aca_oi']}",
        f"TUMORES OIDO OI: {d['tum_oido_oi']}",
        f"INFLAMACION OIDO OI: {d['inf_oido_oi']}",
        f"SECRECION OIDO OI: {d['sec_oido_oi']}",
        f"RECOMENDACION OTICA: {clean_text(d['rec_otica'])}",
        f"NOTAS SECCION 8: {d.get('notas_s8', '')}",
        "--- SECCION 9 MUSCULOESQUELETICO ---",
        f"CUELLO Y CABEZA: {d['cue']}",
        f"ESPALDA: {d['esp']}",
        f"COLA: {d['cola']}",
        f"MIEMBRO ANT DER: {d['mad']}",
        f"MIEMBRO ANT IZQ: {d['mai']}",
        f"MIEMBRO POST DER: {d['mpd']}",
        f"MIEMBRO POST IZQ: {d['mpi']}",
        f"TIPO DE MARCHA: {d.get('tipo_marcha', '')}",
        f"MIEMBRO CLAUDICACION: {clean_text(d.get('miembro_claudicacion', ''))} | GRADO: {d.get('grado_claudicacion', '')}",
        f"NOTAS SECCION 9: {d.get('notas_s9', '')}",
        "--- SECCION 10 NEUROLOGICO ---",
        f"ESTADO MENTAL: {d['ment']}",
        f"NERVIOS CRANEALES: {d['cran']}",
        f"REFLEJOS PROPIOCEPTIVOS: {d['prop']}",
        f"REFLEJOS PATELARES: {d['patel']}",
        f"DOLOR DIGITOPRESION: {d['dolor']} ({d['reg_dolor']})",
        f"NOTAS SECCION 10: {d.get('notas_s10', '')}",
        "--- SECCION 11 CARDIOVASCULAR ---",
        f"FRECUENCIA CV: {d['f_car']}",
        f"PULSO CV: {d['pul_car']}",
        f"SOPLO CV: {d['sop_car']}",
        f"RITMO CV: {d['rit_car']}",
        f"TLLC CV: {d['tllc_car']}",
        f"NOTAS SECCION 11: {d.get('notas_s11', '')}",
        "--- SECCION 12 CAMPOS PULMONARES ---",
        f"PULMON CRANEAL DER: {d['cd']}",
        f"PULMON CAUDAL DER: {d['cad']}",
        f"PULMON CRANEAL IZQ: {d['ci']}",
        f"PULMON CAUDAL IZQ: {d['cai']}",
        f"NOTAS SECCION 12: {d['notas_s12']}",
        "--- SECCION 13 PRUEBAS SANGUINEAS ---",
        f"PRUEBAS ESPECIFICAS: {especificas_str}",
        f"NOTAS SECCION 13: {d.get('notas_s13', '')}",
        "--- SECCION 14 EXCREMENTO ---",
        f"TOXOCARA: {d['tox']}",
        f"COCCIDIA: {d['coc']}",
        f"NEMATODOS: {d['nem']}",
        f"GIARDIA: {d['gia']}",
        f"DYPILIDIUM: {d['gyp']}",
        f"CESTODOS: {d['ces']}",
        f"NOTAS SECCION 14: {d.get('notas_s14', '')}",
        "--- SECCION 15 LABORATORIO (SANGRE Y UROANALISIS) ---",
        f"ERITROCITOS SANGRE: {d['eritrocitos']}",
        f"LEUCOCITOS SANGRE: {d['leucocitos_s']}",
        f"ENZIMAS RENALES: {d['enz_ren']}",
        f"ENZIMAS HEPATICAS: {d['enz_hep']}",
        f"ENZIMAS PANCREATICAS: {d['enz_pan']}",
        f"ELECTROLITOS: {d['electrolitos']}",
        f"PROTEINAS SERICAS: {d['prot_ser']}",
        f"TIROIDES: {d['tiroides']}",
        f"UROBILINOGENO: {d['uro_urobilinogeno']}",
        f"SANGRE URO: {d['uro_sangre']}",
        f"BILIRRUBINA: {d['uro_bilirrubina']}",
        f"CETONA: {d['uro_cetona']}",
        f"PROTEINA URO: {d['uro_proteina']}",
        f"PH: {d['uro_ph']}",
        f"GRAVEDAD ESPECIFICA: {d['uro_gravedad']}",
        f"SEDIMENTO ERITROCITOS: {d['sed_eritrocitos']}",
        f"SEDIMENTO LEUCOCITOS: {d['sed_leucocitos']}",
        f"BACTERIAS: {d['sed_bacterias']}",
        f"CILINDROS RENALES: {d['sed_cilindros']} TIPO: {d['tipo_cilindros']}",
        f"NOTAS LAB: {d['notas_uro']}",
        "--- SECCION 16 PREVENTIVO ---",
        f"PREVENTIVOS APLICADOS: {'; '.join(d['vac_raw_data'])}",
        f"DESPARASITANTE INTERNO: {clean_text(d['desp_interno_seleccionado'])}",
        f"NOTAS SECCION 16: {d.get('notas_s16', '')}",
        "--- SECCION 17 RECOMENDACIONES ---",
        f"PLAN: {d['recomendaciones']}",
        "--- SECCION 18 RESUMEN ---",
        f"MVZ RESPONSABLE: {d['medico']}",
    ]
    return "\n".join([line for line in lines if line.strip()]).upper()


# ================= BARRA LATERAL (IDENTIDAD, ALERTAS Y PORTAL MÓVIL) =================
with st.sidebar:
    logo_unam = asset_path("Banfield-Pet-Hospital.png")
    if logo_unam:
        st.image(str(logo_unam), use_container_width=True)
    st.markdown(
        "<h3 style='text-align:center;' class='banfield-text'>UNAM-Banfield</h3>",
        unsafe_allow_html=True,
    )
    st.caption("Reporte semestral · Plan de Bienestar")

    # Mostrar errores de catálogos si existen (Evita silenciamiento)
    if st.session_state.get("catalog_error"):
        st.error(f"⚠️ Alerta Catálogos: {st.session_state['catalog_error']}")
    if st.session_state.get("medicos_error"):
        st.warning(f"⚠️ Alerta Médicos: {st.session_state['medicos_error']}")

    if st.button(
        "⚡ Pre-llenar Paciente Sano (Normal)",
        type="primary",
        use_container_width=True,
        help="Establece todos los parámetros físicos y de laboratorio en Normal/Negativo para que solo modifiques los hallazgos anormales.",
    ):
        aplicar_paciente_sano_defaults()
        st.toast("Parámetros clínicos establecidos en Normal/Negativo.", icon="✅")

    st.header("Datos generales")
    especie = st.radio("Especie", ["Canino", "Felino"], horizontal=True)
    c_sex, c_rep = st.columns(2)
    sexo = c_sex.selectbox("Sexo", ["Macho", "Hembra"], key="sexo")
    estado_reproductivo = c_rep.selectbox(
        "Estatus reproductivo",
        ["Castrado / Esterilizada", "Entero(a)"],
        key="estado_reproductivo",
    )

    if st.button(
        "🖨️ Generar Formato EN BLANCO (Según Especie y Sexo)",
        use_container_width=True,
        help="Genera el PDF vacío sin contestar pero adaptado dinámicamente a la Especie, Sexo y Estatus reproductivo seleccionados (ideal para revisión del equipo médico o llenado manual).",
    ):
        try:
            est_slug = "Entero" if "Entero" in estado_reproductivo else "Castrado"
            st.session_state["blank_pdf"] = build_blank_pdf(
                especie=especie,
                sexo=sexo,
                estado_reproductivo=estado_reproductivo,
                two_column_grid=st.session_state.get("modo_compacto_toggle", True),
            )
            st.session_state["blank_pdf_name"] = f"PBB_Formato_En_Blanco_{especie}_{sexo}_{est_slug}.pdf"
            st.toast(f"Formato en blanco generado para {especie} {sexo} ({estado_reproductivo}).", icon="🖨️")
        except Exception as exc:
            st.error(f"Error al generar formato en blanco: {exc}")

    if st.session_state.get("blank_pdf"):
        st.download_button(
            f"⬇️ Descargar Machote Vacío ({especie} · {sexo})",
            data=st.session_state["blank_pdf"],
            file_name=st.session_state.get("blank_pdf_name", "PBB_Formato_En_Blanco.pdf"),
            mime="application/pdf",
            use_container_width=True,
            key="dl_blank_sidebar",
        )

    mascota = st.text_input("Nombre de la mascota", key="mascota")
    familia = st.text_input("Propietario", key="familia")

    st.markdown("<b class='banfield-text'>Edad del Paciente</b>", unsafe_allow_html=True)
    c_a, c_m = st.columns(2)
    anios = c_a.selectbox("Años", [str(i) for i in range(31)], key="anios")
    meses = c_m.selectbox("Meses", [str(i) for i in range(12)], key="meses")
    edad = f"{meses} meses" if anios == "0" else f"{anios} años, {meses} meses"

    fecha = st.date_input("Fecha del examen", key="fecha")
    medico = select_con_otro("MVZ Responsable", medicos, "medico")

    st.markdown("---")
    st.markdown("<b class='banfield-text'>⚙️ Opciones de Tabla en PDF</b>", unsafe_allow_html=True)
    modo_compacto = st.toggle(
        "Tablas compactas (2 col)",
        value=True,
        key="modo_compacto_toggle",
        help="Muestra parámetros en cuadrícula de doble columna con semáforo clínico.",
    )
    ocultar_no_eval = st.toggle(
        "Ocultar 'No evaluado / Ninguno'",
        value=False,
        help="Omite en el PDF las filas marcadas como 'No evaluado' o 'Ninguno'.",
    )

    # --- PORTAL DE CARGA MÓVIL (CÓDIGO QR FUNCIONAL EN TIEMPO REAL) ---
    st.markdown("---")
    st.markdown("<b class='banfield-text'>📱 Portal de Carga Móvil</b>", unsafe_allow_html=True)
    base_app_url = st.text_input(
        "URL pública de tu app Streamlit",
        value="https://semestral.streamlit.app/",
        help="Esta URL se usará para generar el Código QR.",
    ).rstrip("/")

    if st.button("Generar Código QR", use_container_width=True):
        if not mascota.strip():
            st.error("Ingresa el nombre del paciente primero.")
        else:
            if not st.session_state.get("sync_token"):
                st.session_state["sync_token"] = "".join(
                    random.choices(string.ascii_uppercase + string.digits, k=6)
                )
            token = st.session_state["sync_token"]
            mobile_store.setdefault(
                token,
                {"timestamp": datetime.datetime.now(), "hashes": set(), "data": {}},
            )

    if st.session_state.get("sync_token") and mascota.strip():
        token = st.session_state["sync_token"]
        url_movil = (
            f"{base_app_url}/?movil=1&paciente={urllib.parse.quote(mascota)}&token={token}"
        )
        qr_api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=180x180&data={urllib.parse.quote(url_movil)}"
        st.image(qr_api_url, caption=f"Escanea para sincronizar cámara con {mascota} (Token: {token})")

        fotos_totales = sum(len(v) for v in mobile_store.get(token, {}).get("data", {}).values())
        col_s1, col_s2 = st.columns(2)
        if col_s1.button("🔄 Sincronizar fotos", use_container_width=True):
            st.rerun()
        if col_s2.button("🔑 Nuevo Token", use_container_width=True):
            st.session_state["sync_token"] = "".join(
                random.choices(string.ascii_uppercase + string.digits, k=6)
            )
            st.rerun()

        if fotos_totales > 0:
            st.success(f"📸 {fotos_totales} foto(s) recibida(s) desde el celular.")
        else:
            st.caption("Esperando fotos desde el celular...")


# ================= ENCABEZADO PRINCIPAL (HERO BANFIELD) =================
st.markdown(
    f"""
    <div class="banfield-hero">
        <div>
            <h2>Reporte y hallazgos del examen semestral</h2>
            <p>Plan de Bienestar Banfield ® · Hospital Veterinario UNAM-Banfield</p>
        </div>
        <div class="banfield-badge">{especie.upper()} · {sexo.upper()} ({estado_reproductivo.upper()})</div>
    </div>
    """,
    unsafe_allow_html=True,
)

tabs = st.tabs(
    [
        "S1–S2 General y piel",
        "S3–S5 Abdomen",
        "S6–S8 Dental y sentidos",
        "S9–S12 Sistemas",
        "S13–S15 Pruebas Lab",
        "S16–S17 Preventivos y Plan",
    ]
)

data = {
    "mascota": mascota,
    "familia": familia,
    "edad": edad,
    "fecha": fecha.strftime("%d/%m/%Y"),
    "medico": medico,
    "especie": especie,
    "sexo": sexo,
    "estado_reproductivo": estado_reproductivo,
}

alimentos_secos = get_food_options(df_cat, especie, humedo=False)
alimentos_humedos = get_food_options(df_cat, especie, humedo=True)
vacunas_filtradas = get_vaccine_options(df_cat, especie)

with tabs[0]:
    ui_header("Constantes Fisiológicas", "Estetoscopio_c.png")
    c1, c2, c3, c4 = st.columns(4)
    data["peso_kg"] = c1.text_input("Peso (kg)", key="peso_kg")
    data["fc"] = c2.text_input("Frecuencia cardiaca (lpm)", key="fc")
    data["fr"] = c3.text_input("Frecuencia respiratoria (rpm)", key="fr")
    data["temp"] = c4.text_input("Temperatura (°C)", key="temp")

    c1, c2, c3, c4 = st.columns(4)
    data["tllc"] = c1.text_input("TLLC (segundos)", key="tllc")
    with c2:
        data["mucosas"] = select_con_otro(
            "Mucosas",
            ["Rosas y húmedas", "Pálidas", "Congestivas", "Ictéricas", "Otro", "Ninguno"],
            "mucosas",
        )
    data["spo2"] = c3.text_input("% SpO2", key="spo2")
    data["pam"] = c4.text_input("PAM", key="pam")
    data["notas_constantes"] = st.text_area("Notas de constantes fisiológicas", height=68, key="notas_constantes")
    data["foto_constantes"] = renderizar_uploader("Constantes", "foto_constantes")

    ui_header("Sección 1 Condición general", "Examen.png")
    c1, c2, c3 = st.columns(3)
    data["cond_gral"] = c1.selectbox(
        "Condición general",
        ["Excelente", "Buena", "Necesita mejorar", "No evaluado", "Ninguno"],
        key="cond_gral",
    )
    data["peso"] = c2.selectbox(
        "Condición de peso",
        ["Perfecto", "Demasiado delgado", "Muy pesado", "No evaluado", "Ninguno"],
        key="peso",
    )
    data["bcs_escala"] = c3.selectbox(
        "Condición Corporal (Escala BCS 1 al 9)",
        [
            "4-5: Peso ideal",
            "1-3: Delgado / Bajo peso",
            "6-7: Sobrepeso",
            "8-9: Obesidad",
            "1/9: Delgado severo",
            "2/9: Delgado",
            "3/9: Bajo peso ligero",
            "4/9: Peso ideal",
            "5/9: Peso ideal",
            "6/9: Sobrepeso ligero",
            "7/9: Sobrepeso marcado",
            "8/9: Obesidad",
            "9/9: Obesidad mórbida",
            "No evaluado",
            "Ninguno",
        ],
        key="bcs_escala",
    )

    data["plan_nutricional"] = st.selectbox(
        "Indicación nutricional sobre dieta y porción",
        [
            "Mantener dieta y porción actual (peso ideal)",
            "Ajustar porción para reducción gradual de peso",
            "Aumentar aporte calórico / recuperación de peso",
            "Transición a dieta terapéutica específica",
            "No evaluado",
            "Ninguno",
        ],
        key="plan_nutricional",
    )

    c1, c2 = st.columns(2)
    with c1:
        data["alim_seco"] = multiselect_con_otro("Alimento SECO sugerido", alimentos_secos, "alim_seco")
    with c2:
        data["alim_humedo"] = multiselect_con_otro("Alimento HÚMEDO sugerido", alimentos_humedos, "alim_humedo")

    data["nutra"] = multiselect_con_otro("Complementos / nutracéuticos", nutraceuticos_list, "nutra")
    data["notas_s1"] = st.text_area("Notas de la sección 1 (Condición general y nutrición)", height=68, key="notas_s1")
    data["foto_s1"] = renderizar_uploader("Condición general", "foto_s1")

    ui_header("Sección 2 Pelo y piel", "Pelo y piel.png")
    c1, c2 = st.columns(2)
    data["pelo_piel"] = c1.selectbox(
        "Pelo y piel",
        ["Parece normal", "Anormal", "No evaluado", "Ninguno"],
        key="pelo_piel",
    )
    data["lesiones_raw"] = c2.multiselect(
        "Lesiones observadas",
        ["Máculas", "Escamas", "Excoriaciones", "Eritema", "Hiperpigmentación", "Alopecia", "Úlceras"],
        key="lesiones",
    )
    data["planos_por_lesion"] = []

    if data["lesiones_raw"]:
        st.markdown("<small><b>Especifique los planos anatómicos afectados por cada lesión:</b></small>", unsafe_allow_html=True)
        for lesion in data["lesiones_raw"]:
            plano = st.text_input(
                f"Plano(s) para {lesion} (Dejar vacío si no aplica)", key=f"plano_{lesion}"
            )
            if plano.strip():
                data["planos_por_lesion"].append(f"{lesion} ({plano.strip()})")
            else:
                data["planos_por_lesion"].append(lesion)

    data["rec_piel"] = multiselect_con_otro("Producto dermatológico recomendado", piel_pelo, "rec_piel")
    data["shampoo_rec"] = multiselect_con_otro("Shampoo recomendado", shampoos, "shampoo_rec")

    c1, c2 = st.columns(2)
    data["ectoparasitos"] = c1.selectbox(
        "Ectoparásitos",
        ["Ninguno presente", "Pulgas", "Piojos", "Garrapatas", "No evaluado", "Ninguno"],
        key="ectoparasitos",
    )
    data["c_pulgas"] = c2.selectbox(
        "Control antipulgas",
        ["Sin pulgas: continuar o iniciar prevención", "Tiene pulgas: se necesita controlar", "Ninguno"],
        key="c_pulgas",
    )
    data["trat_pulgas"] = ""
    if data["c_pulgas"] == "Tiene pulgas: se necesita controlar":
        st.subheader("Detalle de control antipulgas")
        c1, c2, c3, c4 = st.columns(4)
        t_mascota = c1.selectbox("En la mascota", ["Baño", "Baño por inmersión", "Atomizador"], key="t_mascota")
        t_casa = c2.selectbox("En casa", ["Aspirar", "Bomba", "Atomizador local"], key="t_casa")
        t_coche = c3.selectbox("En el coche", ["Atomizador local", "Aspirar"], key="t_coche")
        t_patio = c4.number_input("Patio: rociar cada X semanas", min_value=1, value=1, key="t_patio")
        producto_recetado = multiselect_con_otro("Producto recetado (Dermatológico)", desp_ext, "desp_externo")

        prod_str = ", ".join(producto_recetado) if isinstance(producto_recetado, list) else producto_recetado
        data["trat_pulgas"] = (
            f"- Mascota: {t_mascota}\n- Casa: {t_casa}\n- Coche: {t_coche}\n"
            f"- Patio: Rociar cada {t_patio} semana(s)\n- Producto(s): {prod_str}"
        )

    data["notas_s2"] = st.text_area("Notas de la sección 2", key="notas_s2")
    data["foto_s2"] = renderizar_uploader("Pelo y Piel", "foto_s2")

with tabs[1]:
    ui_header("Sección 3 Palpación abdominal", "Estetoscopio_c.png")
    opts_abd = ["Dentro de límites normales", "Anormal", "No palpable", "No evaluado", "Ninguno"]
    c1, c2, c3 = st.columns(3)
    data["hig"] = c1.selectbox("Hígado", opts_abd, key="hig")
    data["est"] = c2.selectbox("Estómago", opts_abd, key="est")
    data["bazo"] = c3.selectbox("Bazo", opts_abd, key="bazo")
    data["rd"] = c1.selectbox("Riñón derecho", opts_abd, key="rd")
    data["ri"] = c2.selectbox("Riñón izquierdo", opts_abd, key="ri")
    data["int_mes"] = c3.selectbox("Intestinos / mesenterio", opts_abd, key="int_mes")
    data["imp_gral"] = st.selectbox(
        "Impresión general",
        ["Dentro de límites normales", "Anormal", "No evaluado", "Ninguno"],
        key="imp_gral",
    )
    data["notas_s3"] = st.text_area("Notas de la sección 3", key="notas_s3")
    data["foto_s3"] = renderizar_uploader("Abdomen", "foto_s3")

    ui_header("Sección 4 Examen urogenital")
    c1, c2 = st.columns(2)
    posneg = ["Negativo", "Positivo", "No evaluado", "Ninguno"]
    data["secr_uro"] = c1.selectbox("Secreción urogenital", posneg, key="secr_uro")
    data["infl_uro"] = c2.selectbox("Inflamación / infección urogenital", posneg, key="infl_uro")
    data["bult_uro"] = c1.selectbox("Bultos / crecimientos", posneg, key="bult_uro")
    data["tum_mam"] = c2.selectbox("Tumores mamarios", posneg, key="tum_mam")

    # --- CAMPOS CONDICIONALES DE SECCIÓN 4 SEGÚN SEXO, ESTATUS REPRODUCTIVO Y ESPECIE ---
    st.markdown(f"**Evaluación reproductiva específica ({sexo} · {estado_reproductivo} · {especie}):**")
    if sexo == "Macho":
        cm1, cm2, cm3 = st.columns(3)
        data["uro_pene_prepucio"] = cm1.selectbox(
            "Pene y prepucio",
            ["Normal", "Secreción", "Balanopostitis", "No evaluado", "Ninguno"],
            key="uro_pene_prepucio",
        )
        if estado_reproductivo == "Entero(a)":
            data["uro_testiculos"] = cm2.selectbox(
                "Testículos y escroto",
                ["Normales descendidos", "Retenido", "Asimétrico", "No evaluado", "Ninguno"],
                key="uro_testiculos",
            )
        else:
            data["uro_testiculos"] = "No aplica"

        if especie == "Canino":
            data["uro_prostata_macho"] = cm3.selectbox(
                "Evaluación de próstata",
                ["Normal", "Aumentada o dolor", "No palpable", "No evaluado", "Ninguno"],
                key="uro_prostata_macho",
            )
        else:
            data["uro_prostata_macho"] = "No aplica"
    else:
        ch1, ch2 = st.columns(2)
        data["uro_vulva"] = ch1.selectbox(
            "Vulva y área perivulvar",
            ["Normal", "Secreción", "Dermatitis", "No evaluado", "Ninguno"],
            key="uro_vulva",
        )
        data["uro_cadena_mamaria"] = ch2.selectbox(
            "Cadena mamaria individualizada",
            [
                "Normal (sin nódulos)",
                "Anormal / Nódulos en cadena derecha (M1-M5)",
                "Anormal / Nódulos en cadena izquierda (M1-M5)",
                "Anormal / Nódulos bilaterales",
                "Secreción / Galactorrea",
                "No evaluado",
                "Ninguno",
            ],
            key="uro_cadena_mamaria",
        )
        data["uro_detalle_mamas"] = st.text_input(
            "Detalle de glándulas mamarias específicas (si aplica, ej. M4 derecha 0.5 cm)",
            key="uro_detalle_mamas",
        )
        if estado_reproductivo == "Entero(a)":
            data["uro_ultimo_celo"] = st.text_input(
                "Fecha aproximada de último celo",
                placeholder="Ej. Hace 2 meses / Enero 2026 / No reportado",
                key="uro_ultimo_celo",
            )
        else:
            data["uro_ultimo_celo"] = "No aplica"

    data["notas_s4"] = st.text_area("Notas de la sección 4 (Urogenital)", height=68, key="notas_s4")
    data["foto_s4"] = renderizar_uploader("Urogenital", "foto_s4")

    ui_header("Sección 5 Examen rectal")
    c1, c2 = st.columns(2)
    data["pros"] = c1.selectbox("Próstata / recto", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="pros")
    data["tum_rect"] = c2.selectbox("Tumores / crecimientos", posneg, key="tum_rect")
    data["hern"] = c1.selectbox("Hernias / hinchazón", posneg, key="hern")
    data["sacos"] = c2.selectbox("Sacos anales", ["Vacío", "Normal", "Anormal", "No evaluado", "Ninguno"], key="sacos")
    data["notas_s5"] = st.text_area("Notas de la sección 5 (Rectal)", height=68, key="notas_s5")
    data["foto_s5"] = renderizar_uploader("Rectal", "foto_s5")

with tabs[2]:
    ui_header("Sección 6 Examen dental / oral", "Dental.png")
    c1, c2 = st.columns(2)
    posneg = ["Negativo", "Positivo", "No evaluado", "Ninguno"]
    data["epo"] = c1.selectbox(
        "Enfermedad Periodontal (EPO)",
        ["Negativo", "Grado I", "Grado II", "Grado III", "Grado IV", "Ninguno"],
        key="epo",
    )
    data["sarro"] = c2.selectbox("Sarro", posneg, key="sarro")

    c1, c2 = st.columns(2)
    data["mord"] = c1.selectbox("Mordida", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="mord")
    data["decol_d"] = c2.selectbox("Decoloración dental", posneg, key="decol_d")
    data["hinc_e"] = c1.selectbox("Hinchazón / inflamación de encías", posneg, key="hinc_e")
    data["retr_e"] = c2.selectbox("Encías retraídas", posneg, key="retr_e")
    data["inf_e"] = c1.selectbox("Infección de encías", posneg, key="inf_e")
    data["epul_e"] = c2.selectbox("Tumores / épulis", posneg, key="epul_e")
    data["inf_a"] = c1.selectbox("Inflamación de amígdalas", posneg, key="inf_a")
    data["hinc_a"] = c2.selectbox("Hinchazón de amígdalas", posneg, key="hinc_a")
    data["inf_l"] = c1.selectbox("Inflamación de lengua", posneg, key="inf_l")
    data["dec_l"] = c2.selectbox("Decoloración de lengua", posneg, key="dec_l")
    data["hinc_l"] = c1.selectbox("Hinchazón de lengua", posneg, key="hinc_l")
    data["tal_n"] = c2.selectbox("Talla de nódulos linfáticos", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="tal_n")
    data["con_n"] = c1.selectbox("Consistencia de nódulos", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="con_n")
    data["inf_g"] = c2.selectbox("Inflamación de garganta", posneg, key="inf_g")
    data["ref_g"] = c1.selectbox("Reflejos", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="ref_g")
    data["rec_dental"] = multiselect_con_otro("Producto sugerido (Cuidado Dental)", dental_list, "rec_dental")
    data["notas_s6"] = st.text_area("Notas de la sección 6", key="notas_s6")
    data["foto_s6"] = renderizar_uploader("Dental", "foto_s6")

    ui_header("Sección 7 Examen oftálmico")
    st.markdown("#### Ojo Derecho (OD)")
    c1, c2 = st.columns(2)
    data["conj_od"] = c1.selectbox("Conjuntiva OD", posneg, key="conj_od")
    data["sec_od"] = c2.selectbox("Secreción OD", posneg, key="sec_od")
    data["def_od"] = c1.selectbox("Deformidad párpados OD", posneg, key="def_od")
    data["tum_od"] = c2.selectbox("Tumores/quistes OD", posneg, key="tum_od")

    st.markdown("#### Ojo Izquierdo (OI)")
    c3, c4 = st.columns(2)
    data["conj_oi"] = c3.selectbox("Conjuntiva OI", posneg, key="conj_oi")
    data["sec_oi"] = c4.selectbox("Secreción OI", posneg, key="sec_oi")
    data["def_oi"] = c3.selectbox("Deformidad párpados OI", posneg, key="def_oi")
    data["tum_oi"] = c4.selectbox("Tumores/quistes OI", posneg, key="tum_oi")

    st.markdown("#### Tonometría (Presión Intraocular - PIO)")
    st.caption("ℹ️ **Rango de referencia clínico:** 10 a 25 mmHg (manteniendo simetría entre ambos ojos).")
    cp1, cp2 = st.columns(2)
    data["pio_od"] = cp1.text_input("Presión Ojo Derecho (OD) [mmHg]", placeholder="Ej. 16", key="pio_od")
    data["pio_oi"] = cp2.text_input("Presión Ojo Izquierdo (OI) [mmHg]", placeholder="Ej. 17", key="pio_oi")

    data["rec_oftalmica"] = multiselect_con_otro("Producto sugerido (Oftálmico)", oftalmico_list, "rec_oftalmica")
    data["notas_s7"] = st.text_area("Notas de la sección 7 (Oftálmico)", height=68, key="notas_s7")
    data["foto_s7"] = renderizar_uploader("Oftálmico", "foto_s7")

    ui_header("Sección 8 Examen otoscópico", "Orejas.png")
    st.markdown("#### Oído Derecho (OD)")
    c1, c2 = st.columns(2)
    data["ore_od"] = c1.selectbox("Orejas OD", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="ore_od")
    data["tim_od"] = c2.selectbox("Membrana timpánica OD", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="tim_od")
    data["aca_od"] = c1.selectbox("Ácaros OD", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="aca_od")
    data["tum_oido_od"] = c2.selectbox("Tumores/quistes OD", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="tum_oido_od")
    data["inf_oido_od"] = c1.selectbox("Inflamación OD", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="inf_oido_od")
    data["sec_oido_od"] = c2.selectbox("Secreción ótica OD", posneg, key="sec_oido_od")

    st.markdown("#### Oído Izquierdo (OI)")
    c3, c4 = st.columns(2)
    data["ore_oi"] = c3.selectbox("Orejas OI", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="ore_oi")
    data["tim_oi"] = c4.selectbox("Membrana timpánica OI", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="tim_oi")
    data["aca_oi"] = c3.selectbox("Ácaros OI", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="aca_oi")
    data["tum_oido_oi"] = c4.selectbox("Tumores/quistes OI", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="tum_oido_oi")
    data["inf_oido_oi"] = c3.selectbox("Inflamación OI", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="inf_oido_oi")
    data["sec_oido_oi"] = c4.selectbox("Secreción ótica OI", posneg, key="sec_oido_oi")

    data["rec_otica"] = multiselect_con_otro("Producto sugerido (Ótico)", otico_list, "rec_otica")
    data["notas_s8"] = st.text_area("Notas de la sección 8 (Otoscópico)", height=68, key="notas_s8")
    data["foto_s8"] = renderizar_uploader("Otoscópico", "foto_s8")

with tabs[3]:
    ui_header("Sección 9 Examen musculoesquelético", "Musculoesqueletico.png")
    opn = ["Normal", "Anormal", "No evaluado", "Ninguno"]
    c1, c2 = st.columns(2)
    data["cue"] = c1.selectbox("Cuello y cabeza", opn, key="cue")
    data["esp"] = c2.selectbox("Espalda", opn, key="esp")
    data["cola"] = c1.selectbox("Cola", opn, key="cola")
    data["mad"] = c2.selectbox("Miembro anterior derecho", opn, key="mad")
    data["mai"] = c1.selectbox("Miembro anterior izquierdo", opn, key="mai")
    data["mpd"] = c2.selectbox("Miembro posterior derecho", opn, key="mpd")
    data["mpi"] = c1.selectbox("Miembro posterior izquierdo", opn, key="mpi")

    st.markdown("#### Evaluación de la Marcha y Claudicación")
    data["tipo_marcha"] = st.selectbox(
        "Tipo de marcha",
        [
            "Normal / coordinada",
            "Claudicación / Renguea",
            "Dificultad para levantarse / Rigidez",
            "No evaluado",
            "Ninguno",
        ],
        key="tipo_marcha",
    )
    if data["tipo_marcha"] in ("Claudicación / Renguea", "Dificultad para levantarse / Rigidez"):
        cm_m1, cm_m2 = st.columns(2)
        data["miembro_claudicacion"] = cm_m1.multiselect(
            "Miembro(s) afectado(s)",
            ["AD", "AI", "PD", "PI"],
            key="miembro_claudicacion",
        )
        data["grado_claudicacion"] = cm_m2.selectbox(
            "Grado de claudicación (1 al 5)",
            ["Grado 1", "Grado 2", "Grado 3", "Grado 4", "Grado 5"],
            key="grado_claudicacion",
        )
    else:
        data["miembro_claudicacion"] = []
        data["grado_claudicacion"] = ""

    data["notas_s9"] = st.text_area("Notas de la sección 9 (Musculoesquelético y marcha)", height=68, key="notas_s9")
    data["foto_s9"] = renderizar_uploader("Musculoesquelético", "foto_s9")

    ui_header("Sección 10 Examen neurológico")
    c1, c2 = st.columns(2)
    data["ment"] = c1.selectbox("Estado mental", opn, key="ment")
    data["cran"] = c2.selectbox("Nervios craneales", opn, key="cran")
    data["prop"] = c1.selectbox("Reflejos propioceptivos", opn, key="prop")
    data["patel"] = c2.selectbox("Reflejos patelares", opn, key="patel")
    data["dolor"] = c1.selectbox("Dolor a la digitopresión", ["Negativo", "Positivo", "No evaluado", "Ninguno"], key="dolor")
    data["reg_dolor"] = c2.text_input("Región del dolor (si aplica)", key="reg_dolor")
    data["notas_s10"] = st.text_area("Notas de la sección 10 (Neurológico)", height=68, key="notas_s10")
    data["foto_s10"] = renderizar_uploader("Neurológico", "foto_s10")

    ui_header("Sección 11 Cardiovascular / corazón", "Corazon.png")
    c1, c2 = st.columns(2)
    data["f_car"] = c1.selectbox("Frecuencia CV", opn, key="f_car")
    data["pul_car"] = c2.selectbox("Pulso", opn, key="pul_car")
    data["sop_car"] = c1.selectbox("Soplo/sonido anormal", ["Negativo", "Positivo", "No evaluado", "Ninguno"], key="sop_car")
    data["rit_car"] = c2.selectbox("Ritmo", opn, key="rit_car")
    data["tllc_car"] = c1.selectbox("TLLC CV", opn, key="tllc_car")
    data["notas_s11"] = st.text_area("Notas de la sección 11 (Cardiovascular)", height=68, key="notas_s11")

    ui_header("Sección 12 Campos pulmonares")
    c1, c2 = st.columns(2)
    data["cd"] = c1.selectbox("Craneal derecho", opn, key="cd")
    data["cad"] = c2.selectbox("Caudal derecho", opn, key="cad")
    data["ci"] = c1.selectbox("Craneal izquierdo", opn, key="ci")
    data["cai"] = c2.selectbox("Caudal izquierdo", opn, key="cai")
    data["notas_s12"] = st.text_area("Notas de la sección 12", key="notas_s12")

with tabs[4]:
    ui_header("Sección 13 Pruebas sanguíneas virales / vectoriales", "5.png")
    c1, c2 = st.columns(2)
    op_p = ["Negativo", "Positivo", "No aplica", "No realizado", "Ninguno"]
    if especie == "Felino":
        data["leu"] = c1.selectbox("Leucemia felina", op_p, key="leu")
        data["sida"] = c2.selectbox("SIDA felino", op_p, key="sida")
        data["hemo"] = "No aplica"
    else:
        data["hemo"] = c1.selectbox("Hemoparásitos caninos", op_p, key="hemo")
        data["leu"] = "No aplica"
        data["sida"] = "No aplica"
    data["notas_s13"] = st.text_area("Notas de la sección 13 (Pruebas virales / vectoriales)", height=68, key="notas_s13")

    ui_header("Sección 14 Hallazgos en examen de excremento")
    c1, c2, c3 = st.columns(3)
    negpos = ["Negativo", "Positivo", "No realizado", "Ninguno"]
    data["tox"] = c1.selectbox("Toxocara", negpos, key="tox")
    data["coc"] = c2.selectbox("Coccidia", negpos, key="coc")
    data["nem"] = c3.selectbox("Nemátodos", negpos, key="nem")
    data["gia"] = c1.selectbox("Giardia", negpos, key="gia")
    data["gyp"] = c2.selectbox("Dypilidium", negpos, key="gyp")
    data["ces"] = c3.selectbox("Céstodos", negpos, key="ces")
    data["notas_s14"] = st.text_area("Notas de la sección 14 (Examen coproparasitoscópico)", height=68, key="notas_s14")

    ui_header("Sección 15 Análisis de sangre y Uroanálisis", "5.png")
    st.subheader("Hemograma y Química Sanguínea")
    op_n = ["Normal", "Anormal", "No evaluado", "Ninguno"]
    c1, c2, c3 = st.columns(3)
    data["eritrocitos"] = c1.selectbox("Conteo de eritrocitos", op_n, key="eritrocitos")
    data["leucocitos_s"] = c2.selectbox("Conteo de leucocitos", op_n, key="leucocitos_s")
    data["tiroides"] = c3.selectbox(
        "Prueba de Tiroides",
        ["Normal", "Anormal", "Pendiente", "No evaluado", "Ninguno"],
        key="tiroides",
    )

    c1, c2, c3 = st.columns(3)
    data["enz_ren"] = c1.selectbox("Enzimas renales", op_n, key="enz_ren")
    data["enz_hep"] = c2.selectbox("Enzimas hepáticas", op_n, key="enz_hep")
    data["enz_pan"] = c3.selectbox("Enzimas pancreáticas", op_n, key="enz_pan")

    c1, c2 = st.columns(2)
    data["electrolitos"] = c1.selectbox("Electrólitos", op_n, key="electrolitos")
    data["prot_ser"] = c2.selectbox("Proteínas séricas", op_n, key="prot_ser")

    st.subheader("Uroanálisis")
    c1, c2, c3 = st.columns(3)
    data["uro_urobilinogeno"] = c1.selectbox("Urobilinógeno", op_n, key="uro_urobilinogeno")
    data["uro_sangre"] = c2.selectbox("Sangre", op_n, key="uro_sangre")
    data["uro_bilirrubina"] = c3.selectbox("Bilirrubina", op_n, key="uro_bilirrubina")

    c1, c2, c3 = st.columns(3)
    data["uro_cetona"] = c1.selectbox("Cetona", op_n, key="uro_cetona")
    data["uro_proteina"] = c2.selectbox("Proteína", op_n, key="uro_proteina")
    data["uro_ph"] = c3.selectbox("pH", op_n, key="uro_ph")
    data["uro_gravedad"] = c1.selectbox("Gravedad específica", op_n, key="uro_gravedad")

    st.subheader("Sedimento urinario")
    c1, c2, c3, c4 = st.columns(4)
    data["sed_eritrocitos"] = c1.selectbox("Eritrocitos (sedimento)", ["No presente", "Presente", "Ninguno"], key="sed_eritrocitos")
    data["sed_leucocitos"] = c2.selectbox("Leucocitos (sedimento)", ["No presente", "Presente", "Ninguno"], key="sed_leucocitos")
    data["sed_bacterias"] = c3.selectbox("Bacterias", ["No presente", "Presente", "Ninguno"], key="sed_bacterias")
    data["sed_cilindros"] = c4.selectbox("Cilindros renales", ["No presente", "Presente", "Ninguno"], key="sed_cilindros")
    data["tipo_cilindros"] = st.text_input("Tipo de cilindros (si aplica)", key="tipo_cilindros")
    data["notas_uro"] = st.text_area("Otras observaciones y hallazgos (Laboratorio)", key="notas_uro")
    data["foto_lab"] = renderizar_uploader("Laboratorio", "foto_lab")

with tabs[5]:
    img_prev = "OWP_Puppy.png" if data["especie"] == "Canino" else "OWP_Gatito.png"
    ui_header("Sección 16 Cuidado preventivo aplicado en esta visita", img_prev)

    vac_sel = st.multiselect(
        "Selecciona las vacunas aplicadas",
        [v for v in vacunas_filtradas if v != "Ninguno"],
        key="vacunas",
    )
    if "Otro" in vac_sel:
        otro_v = st.text_input("Especifique otra vacuna", key="vac_otra_txt")
        if otro_v and otro_v.strip():
            vac_sel = [v for v in vac_sel if v != "Otro"] + [otro_v.strip()]
        else:
            vac_sel = [v for v in vac_sel if v != "Otro"]

    sitios_anatomicos_opts = [
        "MPD (Miembro Posterior Derecho)",
        "MPI (Miembro Posterior Izquierdo)",
        "MAD (Miembro Anterior Derecho)",
        "MAI (Miembro Anterior Izquierdo)",
        "Interescapular",
        "Otro",
    ]

    data["vac_raw_data"] = []
    if vac_sel:
        for i, v in enumerate(vac_sel):
            c1, c2, c3 = st.columns([1, 1.4, 1.6])
            fecha_vac = c1.date_input(f"Fecha - {v}", datetime.date.today(), key=f"f_vac_{i}")
            lote = c2.text_input(f"Lote/Marca - {v}", key=f"l_vac_{i}")
            sitio_sel = c3.selectbox(
                f"Sitio anatómico - {v}",
                sitios_anatomicos_opts,
                key=f"s_vac_{i}",
            )
            if sitio_sel == "Otro":
                sitio_otro = st.text_input(
                    f"Especifique sitio anatómico para {v}",
                    key=f"s_vac_otro_{i}",
                )
                sitio_final = sitio_otro.strip() if sitio_otro.strip() else "Otro"
            else:
                sitio_final = sitio_sel

            partes_vac = []
            if lote:
                partes_vac.append(f"Lote {lote}")
            partes_vac.append(f"Sitio: {sitio_final}")
            partes_vac.append(f"Aplicada: {fecha_vac.strftime('%d/%m/%Y')}")
            info = f"{v} ({' · '.join(partes_vac)})"
            data["vac_raw_data"].append(info)

    data["desp_interno_seleccionado"] = multiselect_con_otro("Desparasitante Interno", desp_int, "desp_interno")
    data["notas_s16"] = st.text_area("Notas de la sección 16 (Medicina preventiva)", height=68, key="notas_s16")

    ui_header("Sección 17 Otras recomendaciones y plan", "Engranes.png")

    with st.expander("📋 Recomendaciones Clínicas Rápidas (Selecciona para insertar en el plan)", expanded=True):
        st.caption(
            "Marca una o varias recomendaciones médicas frecuentes (redactadas en lenguaje claro y empático para el tutor). "
            "Se insertarán automáticamente en la caja de abajo y podrás editarlas libremente."
        )
        if st.button(
            "✨ Auto-marcar recomendaciones según hallazgos del examen",
            use_container_width=True,
            help="Revisa automáticamente si detectaste sarro/EPO, claudicación, sobrepeso, problemas en piel/oídos o si el paciente es entero(a).",
        ):
            auto_suggest_quick_recommendations(data)
            st.rerun()

        rc1, rc2 = st.columns(2)
        quick_items = list(QUICK_RECOMMENDATIONS.items())
        for idx_q, (chk_k, (chk_title, chk_desc)) in enumerate(quick_items):
            target_col = rc1 if idx_q % 2 == 0 else rc2
            target_col.checkbox(
                f"**{chk_title}**: {chk_desc}",
                key=chk_k,
                on_change=sync_quick_recommendations_to_textarea,
            )

    data["recomendaciones"] = st.text_area("Instrucciones para el cliente", height=140, key="recomendaciones")

    ui_header("Vista Previa · Sección 18 Resumen Semestral", "OWP.png")
    hallazgos_detectados = extraer_hallazgos_atencion(data)
    if not hallazgos_detectados:
        st.success("✓ Paciente sin hallazgos anormales detectados hasta el momento.")
    else:
        st.warning(
            f"⚠️ Áreas detectadas que se incluirán en el resumen de la Sección 18: "
            f"**{', '.join(hallazgos_detectados)}**."
        )

st.markdown("---")
col1, col2, col3 = st.columns([1, 1, 1])

with col1:
    if st.button("Generar reporte PDF", type="primary", use_container_width=True):
        if not data["mascota"].strip():
            st.error("Captura el nombre de la mascota.")
        else:
            try:
                st.session_state["generated_pdf"] = build_pdf(
                    data,
                    two_column_grid=modo_compacto,
                    hide_unassessed=ocultar_no_eval,
                )
                st.session_state["generated_pdf_name"] = f"PBB_{safe_filename(data['mascota'])}_Reporte.pdf"
                st.success("PDF generado exitosamente. Haz clic abajo para descargar.")
            except Exception as exc:
                st.error(f"No se pudo generar: {exc}")

with col2:
    if st.button("🖨️ Generar PDF EN BLANCO (Según Especie/Sexo)", use_container_width=True):
        try:
            est_slug = "Entero" if "Entero" in estado_reproductivo else "Castrado"
            st.session_state["blank_pdf"] = build_blank_pdf(
                especie=especie,
                sexo=sexo,
                estado_reproductivo=estado_reproductivo,
                two_column_grid=modo_compacto,
            )
            st.session_state["blank_pdf_name"] = f"PBB_Formato_En_Blanco_{especie}_{sexo}_{est_slug}.pdf"
            st.success(f"Formato en blanco generado para {especie} · {sexo} ({estado_reproductivo}).")
        except Exception as exc:
            st.error(f"No se pudo generar formato en blanco: {exc}")

with col3:
    if st.button("Generar texto para VIA", use_container_width=True):
        if not data["mascota"].strip():
            st.error("Captura el nombre de la mascota.")
        else:
            st.session_state["via_text"] = build_via_text(data)

if st.session_state.get("generated_pdf"):
    st.download_button(
        "Descargar PDF institucional",
        data=st.session_state["generated_pdf"],
        file_name=st.session_state.get("generated_pdf_name", "PBB_Reporte.pdf"),
        mime="application/pdf",
        use_container_width=True,
    )

if st.session_state.get("blank_pdf"):
    st.download_button(
        f"🖨️ Descargar Formato EN BLANCO ({especie} · {sexo} · {estado_reproductivo})",
        data=st.session_state["blank_pdf"],
        file_name=st.session_state.get("blank_pdf_name", "PBB_Formato_En_Blanco.pdf"),
        mime="application/pdf",
        use_container_width=True,
        key="dl_blank_bottom",
    )

if st.session_state.get("via_text"):
    st.text_area("Copiar en VIA", value=st.session_state["via_text"], height=260)
    st.download_button(
        "Descargar texto VIA (.txt)",
        data=st.session_state["via_text"],
        file_name=f"PBB_{safe_filename(data['mascota'])}_VIA.txt",
        mime="text/plain; charset=utf-8",
        use_container_width=True,
    )
