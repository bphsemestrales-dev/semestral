from __future__ import annotations

import html
import re
from pathlib import Path as FilePath

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

# Escala BCS ordenada estrictamente del 1 al 9
BCS_OPTIONS = [
    "1/9 - Delgado / Bajo peso",
    "2/9 - Delgado / Bajo peso",
    "3/9 - Delgado / Bajo peso",
    "4/9 - Peso ideal",
    "5/9 - Peso ideal",
    "6/9 - Sobrepeso",
    "7/9 - Sobrepeso",
    "8/9 - Obesidad",
    "9/9 - Obesidad",
    "No evaluado",
    "Ninguno",
]

# Catálogo de secciones que aceptan evidencia fotográfica (PC y Móvil)
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


MAX_PHOTOS_PER_SECTION = 15
MAX_PHOTOS_PER_TOKEN = 40
MAX_ACTIVE_TOKENS = 50
SESSION_TTL_SECONDS = 7200  # 2 horas

CSS_STYLES = f"""
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
"""


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

