from __future__ import annotations

import html
import re

import streamlit as st
from reportlab.platypus import ListFlowable, ListItem, Paragraph, Spacer

from config import (
    DARK_GREY,
    QUICK_RECOMMENDATIONS,
    STATUS_ALERT_TXT,
    STATUS_OK_TXT,
    STATUS_WARN_TXT,
    clean_text,
    ptext,
)

# --- REGLAS CLÍNICAS UNIFICADAS (ÚNICA FUENTE DE VERDAD) ---
CLINICAL_NEUTRAL_WORDS = {
    "—",
    "ninguno",
    "no evaluado",
    "no realizado",
    "no aplica",
    "",
}

CLINICAL_OK_WORDS = {
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
    "4/9 - peso ideal",
    "5/9 - peso ideal",
    "mantener dieta y porción actual (peso ideal)",
    "ninguno presente",
    "no presente",
    "vacío",
    "rosas y húmedas",
    "sin pulgas: continuar o iniciar prevención",
}

# Estados que se pintan en ámbar en la tabla para referencia visual, pero NO alarman en la narrativa S18
CLINICAL_INFO_WARN_WORDS = {
    "pendiente",
    "no palpable",
}

CLINICAL_ALERT_TRIGGERS = (
    "grado iii",
    "grado iv",
    "grado 3",
    "grado 4",
    "grado 5",
    "8/9 - obesidad",
    "9/9 - obesidad",
    "1/9 - delgado",
    "balanopostitis",
    "retenido",
    "aumentada o dolor",
    "nódulos",
    "claudicación",
    "renguea",
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
    "tiene pulgas",
    "ataxia",
)

CLINICAL_WARN_TRIGGERS = (
    "grado i",
    "grado ii",
    "grado 1",
    "grado 2",
    "2/9 - delgado",
    "3/9 - delgado",
    "6/9 - sobrepeso",
    "7/9 - sobrepeso",
    "delgado",
    "bajo peso",
    "sobrepeso",
    "obesidad",
    "secreción",
    "dermatitis",
    "asimétrico",
    "dificultad para levantarse",
    "rigidez",
    "necesita mejorar",
    "demasiado delgado",
    "muy pesado",
    "hinchazón",
    "galactorrea",
    "grado",
    "presente",
)


def evaluate_clinical_status(label: str, raw_val: str) -> str:
    """
    Fuente única de verdad clínica.
    Retorna: 'ok' | 'info_warn' | 'clinical_warn' | 'alert' | 'neutral'.
    """
    if not raw_val:
        return "neutral"
    v = str(raw_val).strip().lower()
    if not v or v in CLINICAL_NEUTRAL_WORDS:
        return "neutral"

    # Evaluación numérica especial para Tonometría PIO (10 a 25 mmHg)
    if "presión intraocular" in label.lower() or "pio" in label.lower():
        m = re.search(r"(\d+(?:\.\d+)?)", v)
        if m:
            pio_val = float(m.group(1))
            return "ok" if 10.0 <= pio_val <= 25.0 else "alert"

    if v in CLINICAL_OK_WORDS:
        return "ok"
    if v in CLINICAL_INFO_WARN_WORDS:
        return "info_warn"
    if any(w in v for w in CLINICAL_ALERT_TRIGGERS):
        return "alert"
    if any(w in v for w in CLINICAL_WARN_TRIGGERS):
        return "clinical_warn"
    return "neutral"


def classify_clinical_value(label: str, raw_val: str) -> str:
    """Clasifica un valor clínico en 'ok', 'warn', 'alert' o 'neutral' para el semáforo del PDF."""
    status = evaluate_clinical_status(label, raw_val)
    if status in ("info_warn", "clinical_warn"):
        return "warn"
    return status


def format_badge_html(value_str: str, status: str) -> str:
    """Devuelve texto enriquecido para ReportLab con color semántico."""
    if value_str == " ":
        return ""
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
        w in str(d.get("peso", "")).lower() for w in ("sobrepeso", "obesidad", "delgado", "bajo peso")
    ):
        st.session_state["rec_chk_peso"] = True
    # 5. Cirugía Preventiva
    if d.get("estado_reproductivo") == "Entero(a)":
        st.session_state["rec_chk_cirugia"] = True

    sync_quick_recommendations_to_textarea()


def aplicar_paciente_sano_defaults():
    """Pre-llena todos los campos clínicos en estado Normal/Negativo (con BCS 5/9 - Peso ideal)."""
    defaults = {
        "mucosas_sel": "Rosas y húmedas",
        "cond_gral": "Excelente",
        "peso": "5/9 - Peso ideal",
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



def extraer_hallazgos_atencion(d: dict) -> list[str]:
    """Auditoría clínica integral de las 15 secciones usando evaluate_clinical_status como única fuente de verdad."""
    atencion = []

    def check(label: str, val):
        if evaluate_clinical_status(label, val) in ("clinical_warn", "alert"):
            atencion.append(label.lower())

    check("coloración de mucosas", d.get("mucosas"))
    check("condición general", d.get("cond_gral"))
    check("condición corporal / peso (BCS)", d.get("peso"))
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

    # Auditoría de Tonometría (PIO 10 - 25 mmHg) mediante la misma fuente de verdad
    if evaluate_clinical_status("presión intraocular (OD)", d.get("pio_od", "")) == "alert":
        atencion.append("presión intraocular (OD)")
    if evaluate_clinical_status("presión intraocular (OI)", d.get("pio_oi", "")) == "alert":
        atencion.append("presión intraocular (OI)")

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
    check("frecuencia cardiaca", d.get("f_car"))
    check("pulso", d.get("pul_car"))
    check("soplo", d.get("sop_car"))
    check("ritmo cardiaco", d.get("rit_car"))
    check("tiempo de llenado capilar", d.get("tllc_car"))
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
        return [Spacer(1, 45)]

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

