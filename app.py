from __future__ import annotations

import re
import html
import pandas as pd
import datetime
import urllib.parse
import random
import string
from io import BytesIO
from pathlib import Path as FilePath

import streamlit as st
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, KeepTogether, ListFlowable, ListItem
)

st.set_page_config(page_title="PBB Banfield - Hospital 5501", page_icon="🐾", layout="wide")

BASE_DIR = FilePath(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"

BANFIELD_BLUE = "#003366"
BANFIELD_ORANGE = "#DF4824"
LIGHT_BLUE = "#EAF1F8"
DARK_GREY = "#343A40"
BANFIELD_GREY = "#7F7F7F"

# --- MOTOR DE LECTURA DE CATÁLOGOS MULTI-VERSIÓN ---
df_cat = pd.DataFrame()
for f in ["categorias_productos_2_3.csv", "categorias_productos_2_2.csv", "categorias_productos_2.csv", "categorias_productos.csv"]:
    p = BASE_DIR / f
    if p.is_file():
        try:
            df_cat = pd.read_csv(p)
            break
        except: pass

def get_cat_list(df, category):
    if df is None or df.empty: return ["Otro", "Ninguno"]
    if 'Category' in df.columns:
        mask = df['Category'].str.contains(category, case=False, na=False)
        items = df[mask]['Description'].dropna().tolist()
        return items + ["Otro", "Ninguno"]
    return ["Otro", "Ninguno"]

def get_food_options(df, especie, humedo=False):
    if df is None or df.empty: return ["Otro", "Ninguno"]
    mask_alim = df['Category'].str.contains('Alimento', case=False, na=False)
    mask_esp = df['Category'].str.contains(especie, case=False, na=False) | df['Description'].str.contains(especie, case=False, na=False)
    mask_hum = df['Category'].str.contains('humedo|húmedo|lata|sobre', case=False, na=False) | df['Description'].str.contains('humedo|húmedo|lata|sobre', case=False, na=False)
    
    final_mask = mask_alim & mask_esp & mask_hum if humedo else mask_alim & mask_esp & ~mask_hum
    res = df[final_mask]['Description'].dropna().tolist()
    if not res:
        res = df[mask_alim & mask_hum]['Description'].dropna().tolist() if humedo else df[mask_alim & ~mask_hum]['Description'].dropna().tolist()
    if not res:
        res = df[mask_alim]['Description'].dropna().tolist()
    return res + ["Otro", "Ninguno"]

def get_vaccine_options(df, especie):
    if df is None or df.empty or 'Category' not in df.columns: 
        return ["Otro", "Ninguno"]
    
    cat_buscada = "Vacuna Canina" if especie == "Canino" else "Vacuna Felina"
    mask_exacta = df['Category'].str.strip().str.lower() == cat_buscada.lower()
    res = df[mask_exacta]['Description'].dropna().tolist()
    
    if not res:
        mask_general = df['Category'].str.contains('Vacun', case=False, na=False)
        df_gen = df[mask_general]
        if not df_gen.empty:
            if especie == "Canino":
                mask_desc = df_gen['Description'].str.contains('canin|perro|parvo|distemper|rabia|múltiple|bordetella', case=False, na=False)
            else:
                mask_desc = df_gen['Description'].str.contains('felin|gato|leucemia|rinotraqueitis|calicivirus', case=False, na=False)
            res = df_gen[mask_desc]['Description'].dropna().tolist()
            if not res:
                res = df_gen['Description'].dropna().tolist()
            
    return res + ["Otro", "Ninguno"]

shampoos = get_cat_list(df_cat, 'Shampoo')
piel_pelo = get_cat_list(df_cat, 'Piel y pelo')
desp_int = get_cat_list(df_cat, 'Desparasitante Interno')
desp_ext = get_cat_list(df_cat, 'Desparasitantes')
nutraceuticos_list = get_cat_list(df_cat, 'Vitaminas')
dental_list = get_cat_list(df_cat, 'Cuidado dental')
oftalmico_list = get_cat_list(df_cat, 'Oftalmico')
otico_list = get_cat_list(df_cat, 'Otica')

ced_files = ["cedulas_profesionales_2.csv", "cedulas_profesionales.csv", "196147d8.csv"]
medicos = ["MVZ - Ced. Pendiente", "Otro"]
for f in ced_files:
    path = BASE_DIR / f
    if path.is_file():
        try:
            df_ced = pd.read_csv(path)
            if 'Nombre' in df_ced.columns and 'Cedula Profesional' in df_ced.columns:
                medicos = (df_ced['Nombre'] + " - Ced. " + df_ced['Cedula Profesional'].astype(str)).tolist() + ["Otro"]
                break
        except: pass

# --- CSS DEFINITIVO (INQUEBRANTABLE) ---
st.markdown(
    f"""
    <style>
    .stApp {{ font-family: 'Open Sans', Helvetica, Arial, sans-serif; }}
    
    /* Regla base: Todo en Azul Marino (Modo Claro) */
    h1, h2, h3, h4, .banfield-text {{ 
        color: {BANFIELD_BLUE} !important; 
        font-weight: 700 !important; 
    }}
    
    /* Escudo Blanco para salvar la vida del Logo y el QR en la barra lateral */
    [data-testid="stSidebar"] img {{
        background-color: white !important;
        padding: 12px !important;
        border-radius: 8px !important;
        box-shadow: 0px 4px 6px rgba(0,0,0,0.1);
    }}
    
    /* Cambio estricto a Naranja si detecta Modo Oscuro */
    @media (prefers-color-scheme: dark) {{
        h1, h2, h3, h4, .banfield-text {{ 
            color: {BANFIELD_ORANGE} !important; 
        }}
    }}
    
    /* Estilos del botón principal */
    div.stButton > button[kind="primary"] {{ background-color: {BANFIELD_ORANGE}; color: white; border: 0; font-weight: 700; }}
    div.stButton > button[kind="primary"]:hover {{ background-color: #c93b1b; color: white; }}
    </style>
    """, unsafe_allow_html=True
)

def asset_path(filename: str) -> FilePath | None:
    candidate = ASSETS_DIR / filename
    return candidate if candidate.is_file() else None

def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return cleaned.strip("_")[:70] or "Mascota"

def clean_text(value) -> str:
    if value is None: return ""
    if isinstance(value, (list, tuple)): return ", ".join(str(x) for x in value if x != "Ninguno") if value else ""
    return str(value).strip() if str(value).strip() != "Ninguno" else ""

def ptext(value) -> str:
    val = clean_text(value)
    return html.escape(val).replace("\n", "<br/>") if val else "—"

def ui_header(title, icon_name=None):
    # Ahora usamos <h3> limpio. Las reglas CSS de arriba lo atraparán automáticamente.
    if icon_name and asset_path(icon_name):
        c1, c2 = st.columns([1, 15])
        with c1:
            st.image(str(asset_path(icon_name)), width=40)
        with c2:
            st.markdown(f"<h3 style='margin-top: 5px;'>{title}</h3>", unsafe_allow_html=True)
    else:
        st.markdown(f"<h3>{title}</h3>", unsafe_allow_html=True)

def renderizar_uploader(label, key):
    with st.expander(f"📷 Anexar evidencia fotográfica ({label})"):
        return st.file_uploader("Tomar foto o elegir de la galería", type=['jpg', 'jpeg', 'png'], key=key, accept_multiple_files=True)

def select_con_otro(label, opciones, key_base):
    val = st.selectbox(label, opciones, key=key_base+"_sel")
    if val == "Otro":
        return st.text_input(f"Especifique {label.lower()}", key=key_base+"_txt")
    return val

def multiselect_con_otro(label, opciones, key_base):
    ops = [o for o in opciones if o != "Ninguno"]
    val = st.multiselect(label, ops, key=key_base+"_sel")
    if "Otro" in val:
        otro_val = st.text_input(f"Especifique {label.lower()}", key=key_base+"_txt")
        if otro_val:
            val = [v for v in val if v != "Otro"] + [otro_val]
        else:
            val = [v for v in val if v != "Otro"]
    return val

# --- NUEVO GENERADOR INTELIGENTE (FLUJO CONTINUO Y CABECERAS REPETIBLES) ---
def add_labeled_rows(story_list, grouped_rows, styles, col_widths=None):
    if not grouped_rows: return
    col_widths = col_widths or [210, 300] 
    
    for group_title, items in grouped_rows:
        table_data = []
        table_data.append([Paragraph(f"<font color='{BANFIELD_BLUE}'><b>{html.escape(group_title)}</b></font>", styles["Small"]), ""])
        row_styles = [
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E9F0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("SPAN", (0, 0), (1, 0)),
            ("BACKGROUND", (0, 0), (1, 0), colors.HexColor(LIGHT_BLUE)),
        ]
        
        row_idx = 1
        for label, value in items:
            if isinstance(value, str):
                val_flow = Paragraph(value if value else "—", styles["Small"])
            else:
                val_flow = value
                
            table_data.append([
                Paragraph(f"<b>{html.escape(label)}</b>", styles["Small"]),
                val_flow,
            ])
            row_styles.append(("BACKGROUND", (0, row_idx), (1, row_idx), colors.white))
            row_idx += 1
            
        table = Table(table_data, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
        table.setStyle(TableStyle(row_styles))
        
        story_list.append(table)
        story_list.append(Spacer(1, 3))

def add_info_box(story, title, content, styles):
    box_data = [[Paragraph(f"<b>{title}:</b> {content}", styles["InfoBox"])]]
    t = Table(box_data, colWidths=[510], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FDEFEA")), 
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(BANFIELD_ORANGE)),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(Spacer(1, 2))
    story.append(t)
    story.append(Spacer(1, 5))

def add_section_pdf(story, title, grouped_rows, styles, icon_name=None, notes=None, photo_list=None):
    icon_file = asset_path(icon_name) if icon_name else None
    
    if icon_file:
        img_path_str = str(icon_file).replace('\\', '/')
        header_html = f"<img src='{img_path_str}' width='20' height='20' valign='middle'/>  {html.escape(title)}"
        story.append(Paragraph(header_html, styles["Section"]))
    else:
        story.append(Paragraph(html.escape(title), styles["Section"]))

    if grouped_rows: 
        add_labeled_rows(story, grouped_rows, styles)
    
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
            rows = [photo_elements[i:i+2] for i in range(0, len(photo_elements), 2)]
            if len(rows[-1]) == 1:
                rows[-1].append("") 
                
            foto_table = Table(rows, hAlign="LEFT")
            foto_table.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(foto_table)
            story.append(Spacer(1, 3))

    if notes:
        story.append(Paragraph(f"<b>Notas:</b> {ptext(notes)}", styles["Body"]))
        story.append(Spacer(1, 3))
    
    story.append(Spacer(1, 8))

def generar_resumen_narrativo(d: dict, styles) -> list:
    atencion = []
    def check(label, val, triggers_atencion=["anormal", "positivo", "pulgas", "piojos", "garrapatas", "demasiado", "muy", "grado", "presente"]):
        if not val: return
        val_str = str(val).strip().lower()
        if val_str in ["no evaluado", "pendiente"]:
            return
        for t in triggers_atencion:
            if t in val_str and val_str not in ["ninguno", "ninguno presente", "no presente", "negativo", "vacío", "normal", "excelente", "buena", "perfecto", "dentro de límites normales"]:
                atencion.append(label.lower())
                break
    
    check("condición de peso", d.get("peso"))
    check("enfermedad periodontal", d.get("epo"))
    check("sarro", d.get("sarro"))
    check("pelo y piel", d.get("pelo_piel"))
    check("presencia de ectoparásitos", d.get("ectoparasitos"))
    check("hígado", d.get("hig"))
    check("estómago", d.get("est"))
    check("riñones", d.get("rd"))
    check("próstata o recto", d.get("pros"))
    check("alteración ocular (OD)", d.get("def_od"))
    check("alteración ocular (OI)", d.get("def_oi"))
    check("frecuencia cardiovascular", d.get("f_car"))
    check("soplo", d.get("sop_car"))
    check("leucemia felina", d.get("leu"))
    check("SIDA felino", d.get("sida"))
    check("hemoparásitos", d.get("hemo"))
    check("giardia", d.get("gia"))
    check("tiroides", d.get("tiroides"))
    check("cilindros renales", d.get("sed_cilindros"))
    
    elements = []
    if not atencion:
        p_txt = "Nos complace informarle que la exploración clínica de su mascota fue muy satisfactoria. Todas las constantes vitales y los sistemas corporales evaluados durante este examen semestral se encuentran dentro de parámetros saludables y normales. Sugerimos continuar con su plan de medicina preventiva para mantener este excelente estado de salud."
    else:
        atencion = list(dict.fromkeys(atencion))
        p_txt = "Nos complace informarle que la gran mayoría de los sistemas y constantes fisiológicas de su mascota se encuentran estables. Sin embargo, durante la exploración clínica sistemática hemos detectado algunas áreas de oportunidad que requieren monitoreo o atención médica, específicamente en: <b>"
        if len(atencion) > 1:
            p_txt += ", ".join(atencion[:-1]) + f" y {atencion[-1]}."
        else:
            p_txt += f"{atencion[0]}."
        p_txt += "</b><br/><br/>Le sugerimos apegarse a las recomendaciones terapéuticas y al plan médico detallado en este reporte para garantizar la calidad de vida y el bienestar de su mascota."
        
    elements.append(Paragraph(p_txt, styles["Plan"]))
    return elements

def cover_footer(canvas, doc):
    canvas.saveState()
    page_w, _ = letter
    icons = ["Vacunas.png", "Acaros (2).png", "Dental.png", "Condicion General.png", "Estetoscopio_c.png", "OWP_Puppy.png", "OWP_Gatito.png", "OWP.png"]
    start_x = 40
    available_w = page_w - 80
    spacing = available_w / len(icons)
    for i, ico in enumerate(icons):
        path = asset_path(ico)
        if path:
            cx = start_x + (spacing * i) + (spacing / 2)
            canvas.drawImage(str(path), cx - 20, 20, width=40, height=40, mask='auto', preserveAspectRatio=True)
    canvas.setFillColor(colors.HexColor("#9FA7B5"))
    canvas.circle(page_w/2, 20, 12, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawCentredString(page_w/2, 16, "1")
    canvas.restoreState()

def regular_footer(canvas, doc):
    canvas.saveState()
    page_w, page_h = letter
    b_ico = asset_path("Banfield_ico.png")
    if b_ico:
        canvas.drawImage(str(b_ico), page_w - 70, page_h - 60, width=40, height=40, mask='auto', preserveAspectRatio=True)
    canvas.setStrokeColor(colors.HexColor(BANFIELD_ORANGE))
    canvas.setLineWidth(2)
    canvas.line(40, 32, page_w - 40, 32)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(colors.HexColor(BANFIELD_BLUE))
    canvas.drawString(40, 19, "Banfield Pet Hospital de México")
    canvas.drawRightString(page_w - 40, 19, f"Página {doc.page}")
    canvas.restoreState()

def build_pdf(data: dict) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, rightMargin=40, leftMargin=40,
        topMargin=85, bottomMargin=60, title=f"Reporte PBB - {data['mascota']}"
    )

    base_styles = getSampleStyleSheet()
    styles = {
        "CoverBoxTitle": ParagraphStyle("CBoxT", parent=base_styles["Title"], fontName="Helvetica-Bold", fontSize=20, textColor=colors.HexColor(BANFIELD_BLUE), alignment=TA_CENTER),
        "CoverBoxSub": ParagraphStyle("CBoxS", parent=base_styles["Heading2"], fontName="Helvetica", fontSize=15, textColor=colors.white, alignment=TA_CENTER),
        "CoverData": ParagraphStyle("CData", parent=base_styles["Normal"], fontName="Helvetica-Bold", fontSize=11, leading=16, textColor=colors.HexColor(BANFIELD_BLUE), spaceAfter=15),
        "CoverBody": ParagraphStyle("CBody", parent=base_styles["Normal"], fontName="Helvetica", fontSize=10, leading=14, alignment=TA_LEFT, textColor=colors.HexColor(BANFIELD_BLUE), spaceAfter=8),
        "CoverBullet": ParagraphStyle("CBullet", parent=base_styles["Normal"], fontName="Helvetica", fontSize=10, leading=14, leftIndent=20, textColor=colors.HexColor(BANFIELD_BLUE), spaceAfter=4),
        "Title": ParagraphStyle("BanfieldTitle", parent=base_styles["Title"], fontName="Helvetica-Bold", fontSize=15, textColor=colors.HexColor(BANFIELD_BLUE), alignment=TA_LEFT, spaceAfter=10),
        "Section": ParagraphStyle("BanfieldSection", parent=base_styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, textColor=colors.HexColor(BANFIELD_ORANGE), spaceBefore=6, spaceAfter=4, keepWithNext=True),
        "Body": ParagraphStyle("BanfieldBody", parent=base_styles["BodyText"], fontName="Helvetica", fontSize=10, leading=13, textColor=colors.HexColor(DARK_GREY)),
        "Small": ParagraphStyle("BanfieldSmall", parent=base_styles["BodyText"], fontName="Helvetica", fontSize=10, leading=13, textColor=colors.HexColor(DARK_GREY)),
        "Plan": ParagraphStyle("BanfieldPlan", parent=base_styles["BodyText"], fontName="Helvetica", fontSize=10, leading=14, textColor=colors.HexColor(DARK_GREY)),
        "Bullet": ParagraphStyle("BulletList", parent=base_styles["BodyText"], fontName="Helvetica", fontSize=10, leading=13, textColor=colors.HexColor(DARK_GREY)),
        "InfoBox": ParagraphStyle("InfoBoxText", parent=base_styles["BodyText"], fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor(DARK_GREY))
    }

    story = []
    
    # --- ESPACIADOR NEGATIVO SOLO EN LA CARÁTULA ---
    story.append(Spacer(1, -45))
    
    # ================= CARÁTULA =================
    logo_unam = asset_path("Banfield-Pet-Hospital.png")
    if logo_unam:
        try:
            img = Image(str(logo_unam), width=250, height=65, kind="proportional")
            logo_table = Table([["", img]], colWidths=[270, 250])
            logo_table.setStyle(TableStyle([('ALIGN', (1, 0), (1, 0), 'RIGHT')]))
            story.append(logo_table)
            story.append(Spacer(1, 15))
        except: pass

    pbb_logo = asset_path("PBB.jpg")
    img_pbb = Image(str(pbb_logo), width=170, height=170, kind="proportional") if pbb_logo else ""
    title_p = Paragraph("PLAN DE BIENESTAR BANFIELD ®", styles["CoverBoxTitle"])
    
    box_header = Table([[title_p], [img_pbb]], colWidths=[520])
    box_header.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(box_header)

    subtitle_p = Paragraph("Reporte y hallazgos del Examen Semestral", styles["CoverBoxSub"])
    box_blue = Table([[subtitle_p]], colWidths=[420])
    box_blue.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor(BANFIELD_BLUE)),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    wrapper_blue = Table([[box_blue]], colWidths=[520], hAlign="CENTER")
    wrapper_blue.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
    story.append(wrapper_blue)
    story.append(Spacer(1, 15))
    
    c_data = f"Mascota: {ptext(data['mascota'])} (Especie: {ptext(data['especie'])})<br/>Propietario: {ptext(data['familia'])}<br/>Edad: {ptext(data['edad'])}<br/>Fecha: {ptext(data['fecha'])}"
    story.append(Paragraph(c_data, styles["CoverData"]))
    
    txt_intro = "Esta valoración médica rutinaria es uno de los cimientos de nuestros <b>Planes de Bienestar Banfield ®</b> y forma parte de nuestra filosofía de <b>Medicina Preventiva</b>, la cual se compone de 6 pilares:"
    story.append(Paragraph(txt_intro, styles["CoverBody"]))
    
    for b in ["La vacunación", "La desparasitación", "El cuidado dental", "La nutrición", "La detección temprana de enfermedades asociadas a la raza", "El sano desarrollo de la conducta de su mascota"]:
        story.append(Paragraph(f"• {b}", styles["CoverBullet"]))
        
    story.append(Spacer(1, 10))
    txt_out = "Junto con usted, cumplimos nuestra misión: <b>crear un mundo mejor para las mascotas para poder amarlas más tiempo.</b><br/><br/><b>Gracias por su colaboración.</b>"
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
    add_section_pdf(story, "Constantes Fisiológicas", [("Evaluación Fisiológica", s_constantes)], styles, None, photo_list=data.get('foto_constantes'))

    s1_cond = [
        ("Condición general", f"{ptext(data['cond_gral'])}"),
        ("Condición de peso", f"{ptext(data['peso'])}")
    ]
    s1_nutri = []
    if data['alim_seco'] and clean_text(data['alim_seco']): s1_nutri.append(("Alimento seco", f"{ptext(data['alim_seco'])}"))
    if data['alim_humedo'] and clean_text(data['alim_humedo']): s1_nutri.append(("Alimento húmedo", f"{ptext(data['alim_humedo'])}"))
    if data['nutra'] and clean_text(data['nutra']): s1_nutri.append(("Nutracéuticos", f"{ptext(data['nutra'])}"))

    s1_agrupado = [("Condición Corporal", s1_cond)]
    if s1_nutri: s1_agrupado.append(("Nutrición", s1_nutri))
    add_section_pdf(story, "Sección 1 Condición general", s1_agrupado, styles, "Examen.png", photo_list=data.get('foto_s1'))

    s2_derma = [("Pelo y piel", f"{ptext(data['pelo_piel'])}")]
    
    if data['planos_por_lesion']: 
        s2_derma.append(("Lesiones y planos afectados", "<br/>".join(data['planos_por_lesion'])))
        
    if data["rec_piel"] and clean_text(data["rec_piel"]): s2_derma.append(("Producto dermatológico", f"{ptext(data['rec_piel'])}"))
    if data["shampoo_rec"] and clean_text(data["shampoo_rec"]): s2_derma.append(("Shampoo sugerido", f"{ptext(data['shampoo_rec'])}"))
        
    s2_paras = [("Ectoparásitos", f"{ptext(data['ectoparasitos'])}"), ("Control recetado", f"{ptext(data['c_pulgas'])}")]
    if data['trat_pulgas']:
        plan_str = ptext(data['trat_pulgas']).replace('\n', '<br/>')
        s2_paras.append(("Plan a seguir", plan_str))

    add_section_pdf(story, "Sección 2 Pelo y Piel", [("Dermatología", s2_derma), ("Control Parasitario", s2_paras)], styles, "Pelo y piel.png", data["notas_s2"], photo_list=data.get('foto_s2'))

    s3_abd = [("Hígado", f"{ptext(data['hig'])}"), ("Estómago", f"{ptext(data['est'])}"), ("Bazo", f"{ptext(data['bazo'])}")]
    s3_rin = [("Riñón derecho", f"{ptext(data['rd'])}"), ("Riñón izquierdo", f"{ptext(data['ri'])}")]
    s3_int = [("Intestinos / mesenterio", f"{ptext(data['int_mes'])}"), ("Impresión general", f"{ptext(data['imp_gral'])}")]
    
    add_section_pdf(story, "Sección 3 Palpación abdominal", [
        ("Palpación Abdominal", s3_abd), 
        ("Riñones", s3_rin), 
        ("Intestinos y Anexos", s3_int)
    ], styles, "Estetoscopio_c.png", data["notas_s3"], photo_list=data.get('foto_s3'))

    s4_uro = [
        ("Secreción urogenital", f"{ptext(data['secr_uro'])}"),
        ("Inflamación / infección", f"{ptext(data['infl_uro'])}"),
        ("Bultos / crecimientos", f"{ptext(data['bult_uro'])}"),
        ("Tumores mamarios", f"{ptext(data['tum_mam'])}")
    ]
    add_section_pdf(story, "Sección 4 Examen Urogenital", [("Examen Urogenital", s4_uro)], styles, photo_list=data.get('foto_s4'))

    s5_rect = [
        ("Próstata / recto", f"{ptext(data['pros'])}"),
        ("Tumores / crecimientos", f"{ptext(data['tum_rect'])}"),
        ("Hernias / hinchazón", f"{ptext(data['hern'])}"),
        ("Sacos anales", f"{ptext(data['sacos'])}")
    ]
    add_section_pdf(story, "Sección 5 Examen Rectal", [("Examen Rectal", s5_rect)], styles, photo_list=data.get('foto_s5'))

    s6_dientes = [
        ("Enfermedad Periodontal (EPO)", f"{ptext(data['epo'])}"),
        ("Sarro", f"{ptext(data['sarro'])}"),
        ("Mordida", f"{ptext(data['mord'])}"),
        ("Decoloración dental", f"{ptext(data['decol_d'])}")
    ]
    s6_encias = [
        ("Hinchazón de encías", f"{ptext(data['hinc_e'])}"),
        ("Encías retraídas", f"{ptext(data['retr_e'])}"),
        ("Infección de encías", f"{ptext(data['inf_e'])}"),
        ("Tumores / épulis", f"{ptext(data['epul_e'])}")
    ]
    s6_boca = [
        ("Amígdalas (Inflamación)", f"{ptext(data['inf_a'])}"),
        ("Lengua (Inflamación)", f"{ptext(data['inf_l'])}"),
        ("Nódulos linfáticos", f"{ptext(data['tal_n'])}"),
        ("Consistencia de nódulos", f"{ptext(data['con_n'])}"),
        ("Inflamación de garganta", f"{ptext(data['inf_g'])}"),
        ("Reflejos faríngeos", f"{ptext(data['ref_g'])}")
    ]
    s6_agrupado = [("Dientes y Enfermedad", s6_dientes), ("Encías", s6_encias), ("Amígdalas, Lengua y Garganta", s6_boca)]
    if data["rec_dental"] and clean_text(data["rec_dental"]):
        s6_agrupado.append(("Recomendación Médica", [("Producto(s) sugerido(s)", f"{ptext(data['rec_dental'])}")]))
    
    add_section_pdf(story, "Sección 6 Examen Dental/Oral", s6_agrupado, styles, "Dental.png", data["notas_s6"], photo_list=data.get('foto_s6'))
    add_info_box(story, "Nota Dental", "La Enfermedad Periodontal (EPO) se clasifica en grados. El Grado I indica gingivitis leve, mientras que los Grados II a IV implican pérdida progresiva de la adherencia dental, pérdida ósea y riesgo de infecciones sistémicas.", styles)

    s7_od = [
        ("Conjuntiva OD", f"{ptext(data['conj_od'])}"),
        ("Secreción OD", f"{ptext(data['sec_od'])}"),
        ("Deformidad párpados OD", f"{ptext(data['def_od'])}"),
        ("Tumores/quistes OD", f"{ptext(data['tum_od'])}")
    ]
    s7_oi = [
        ("Conjuntiva OI", f"{ptext(data['conj_oi'])}"),
        ("Secreción OI", f"{ptext(data['sec_oi'])}"),
        ("Deformidad párpados OI", f"{ptext(data['def_oi'])}"),
        ("Tumores/quistes OI", f"{ptext(data['tum_oi'])}")
    ]
    s7_agrupado = [("Oftálmico (Ojo Derecho)", s7_od), ("Oftálmico (Ojo Izquierdo)", s7_oi)]
    if data["rec_oftalmica"] and clean_text(data["rec_oftalmica"]):
        s7_agrupado.append(("Recomendación", [("Producto oftalmológico", f"{ptext(data['rec_oftalmica'])}")]))

    add_section_pdf(story, "Sección 7 Examen Oftálmico", s7_agrupado, styles, photo_list=data.get('foto_s7'))

    s8_od = [
        ("Orejas OD", f"{ptext(data['ore_od'])}"),
        ("Membrana timpánica OD", f"{ptext(data['tim_od'])}"),
        ("Ácaros OD", f"{ptext(data['aca_od'])}"),
        ("Tumores/quistes OD", f"{ptext(data['tum_oido_od'])}"),
        ("Inflamación OD", f"{ptext(data['inf_oido_od'])}"),
        ("Secreción ótica OD", f"{ptext(data['sec_oido_od'])}")
    ]
    s8_oi = [
        ("Orejas OI", f"{ptext(data['ore_oi'])}"),
        ("Membrana timpánica OI", f"{ptext(data['tim_oi'])}"),
        ("Ácaros OI", f"{ptext(data['aca_oi'])}"),
        ("Tumores/quistes OI", f"{ptext(data['tum_oido_oi'])}"),
        ("Inflamación OI", f"{ptext(data['inf_oido_oi'])}"),
        ("Secreción ótica OI", f"{ptext(data['sec_oido_oi'])}")
    ]
    s8_agrupado = [("Otoscópico (Oído Derecho)", s8_od), ("Otoscópico (Oído Izquierdo)", s8_oi)]
    if data["rec_otica"] and clean_text(data["rec_otica"]):
        s8_agrupado.append(("Recomendación", [("Producto otológico", f"{ptext(data['rec_otica'])}")]))

    add_section_pdf(story, "Sección 8 Examen Otoscópico", s8_agrupado, styles, "Orejas.png", photo_list=data.get('foto_s8'))

    s9_col = [("Cuello y cabeza", f"{ptext(data['cue'])}"), ("Espalda", f"{ptext(data['esp'])}"), ("Cola", f"{ptext(data['cola'])}")]
    s9_mie = [
        ("Miembro anterior derecho", f"{ptext(data['mad'])}"),
        ("Miembro anterior izquierdo", f"{ptext(data['mai'])}"),
        ("Miembro posterior derecho", f"{ptext(data['mpd'])}"),
        ("Miembro posterior izquierdo", f"{ptext(data['mpi'])}")
    ]
    add_section_pdf(story, "Sección 9 Examen Musculoesquelético", [("Columna y Anexos", s9_col), ("Miembros", s9_mie)], styles, "Musculoesqueletico.png", photo_list=data.get('foto_s9'))

    s10_gral = [("Estado mental", f"{ptext(data['ment'])}"), ("Nervios craneales", f"{ptext(data['cran'])}")]
    s10_ref = [
        ("Reflejos propioceptivos", f"{ptext(data['prop'])}"),
        ("Reflejos patelares", f"{ptext(data['patel'])}"),
        ("Dolor a la digitopresión", f"{ptext(data['dolor'])}"),
        ("Región del dolor", f"{ptext(data['reg_dolor'])}")
    ]
    add_section_pdf(story, "Sección 10 Examen Neurológico", [("Neurológico General", s10_gral), ("Reflejos y Dolor", s10_ref)], styles, photo_list=data.get('foto_s10'))

    s11_cv = [
        ("Frecuencia cardiovascular", f"{ptext(data['f_car'])}"),
        ("Pulso", f"{ptext(data['pul_car'])}"),
        ("Soplo o sonido anormal", f"{ptext(data['sop_car'])}"),
        ("Ritmo", f"{ptext(data['rit_car'])}"),
        ("TLLC cardiovascular", f"{ptext(data['tllc_car'])}")
    ]
    add_section_pdf(story, "Sección 11 Cardiovascular/Corazón", [("Evaluación Cardiovascular", s11_cv)], styles, "Corazon.png")
    
    s12_pul = [
        ("Craneal derecho", f"{ptext(data['cd'])}"),
        ("Caudal derecho", f"{ptext(data['cad'])}"),
        ("Craneal izquierdo", f"{ptext(data['ci'])}"),
        ("Caudal izquierdo", f"{ptext(data['cai'])}")
    ]
    add_section_pdf(story, "Sección 12 Campos pulmonares", [("Campos Pulmonares", s12_pul)], styles, None, data["notas_s12"])

    if data['especie'] == "Felino":
        s13_items = [("Leucemia felina", f"{ptext(data['leu'])}"), ("SIDA felino", f"{ptext(data['sida'])}")]
    else:
        s13_items = [("Hemoparásitos caninos", f"{ptext(data['hemo'])}")]

    add_section_pdf(story, "Sección 13 Pruebas sanguíneas virales / vectoriales", [("Pruebas Específicas", s13_items)], styles, "5.png")

    s14_items = [
        ("Toxocara", f"{ptext(data['tox'])}"),
        ("Coccidia", f"{ptext(data['coc'])}"),
        ("Nemátodos", f"{ptext(data['nem'])}"),
        ("Giardia", f"{ptext(data['gia'])}"),
        ("Gypilidium", f"{ptext(data['gyp'])}"),
        ("Céstodos", f"{ptext(data['ces'])}")
    ]
    add_section_pdf(story, "Sección 14 Hallazgos en examen de excremento", [("Examen de Excremento", s14_items)], styles)

    s15_hemo = [
        ("Conteo de eritrocitos", f"{ptext(data['eritrocitos'])}"),
        ("Conteo de leucocitos", f"{ptext(data['leucocitos_s'])}"),
        ("Prueba de Tiroides", f"{ptext(data['tiroides'])}"),
        ("Enzimas renales", f"{ptext(data['enz_ren'])}"),
        ("Enzimas hepáticas", f"{ptext(data['enz_hep'])}"),
        ("Enzimas pancreáticas", f"{ptext(data['enz_pan'])}"),
        ("Electrólitos", f"{ptext(data['electrolitos'])}"),
        ("Proteínas séricas", f"{ptext(data['prot_ser'])}")
    ]
    s15_uro = [
        ("Urobilinógeno", f"{ptext(data['uro_urobilinogeno'])}"),
        ("Sangre (Uroanálisis)", f"{ptext(data['uro_sangre'])}"),
        ("Bilirrubina", f"{ptext(data['uro_bilirrubina'])}"),
        ("Cetona", f"{ptext(data['uro_cetona'])}"),
        ("Proteína (Uroanálisis)", f"{ptext(data['uro_proteina'])}"),
        ("pH", f"{ptext(data['uro_ph'])}"),
        ("Gravedad específica", f"{ptext(data['uro_gravedad'])}")
    ]
    s15_sed = [
        ("Sedimento: Eritrocitos", f"{ptext(data['sed_eritrocitos'])}"),
        ("Sedimento: Leucocitos", f"{ptext(data['sed_leucocitos'])}"),
        ("Bacterias", f"{ptext(data['sed_bacterias'])}"),
        ("Cilindros renales", f"{ptext(data['sed_cilindros'])} (Tipo: {ptext(data['tipo_cilindros'])})")
    ]
    add_section_pdf(story, "Sección 15 Análisis de sangre y Uroanálisis", [
        ("Hemograma y Química Sanguínea", s15_hemo), 
        ("Uroanálisis", s15_uro), 
        ("Sedimento Urinario", s15_sed)
    ], styles, "5.png", data["notas_uro"], photo_list=data.get('foto_lab'))

    add_info_box(story, "Nota Preventiva", "Los análisis sanguíneos y el uroanálisis nos permiten establecer una línea base de la función interna de los órganos (como riñones e hígado), ayudándonos a detectar enfermedades sistémicas antes de que presenten síntomas visibles.", styles)

    vac_items = []
    if data["vac_raw_data"]:
        for vac_info in data["vac_raw_data"]:
            vac_items.append(ListItem(Paragraph(html.escape(vac_info), styles["Bullet"]), leftIndent=15, spaceAfter=2))
    
    flow_vac = ListFlowable(vac_items, bulletType='bullet', start='bulletchar') if vac_items else Paragraph("—", styles["Small"])

    s16_items = [
        ("Vacunas aplicadas", flow_vac),
        ("Desparasitante Interno", f"{ptext(data['desp_interno_seleccionado'])}")
    ]

    img_prev = "OWP_Puppy.png" if data['especie'] == "Canino" else "OWP_Gatito.png"
    add_section_pdf(story, "Sección 16 Cuidado preventivo aplicado en esta visita", [("Medicina Preventiva", s16_items)], styles, img_prev)

    story.append(Paragraph("Sección 17 Otras recomendaciones y Comentarios", styles["Section"]))
    plan = data["recomendaciones"].strip() or "Sin recomendaciones registradas."
    plan_table = Table([[Paragraph(ptext(plan).replace("\n", "<br/>"), styles["Plan"])]], colWidths=[510], hAlign="LEFT")
    plan_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(LIGHT_BLUE)),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0DCE9")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(plan_table)
    story.append(Spacer(1, 12))

    # ================= BLOQUE INDIVISIBLE: SECCIÓN 18 + FIRMAS =================
    final_block = []

    icon_file = asset_path("OWP.png")
    if icon_file:
        try:
            img_path_str = str(icon_file).replace('\\', '/')
            header_html = f"<img src='{img_path_str}' width='20' height='20' valign='middle'/>  Sección 18 Resumen del Examen Semestral Banfield"
            final_block.append(Paragraph(header_html, styles["Section"]))
        except Exception:
            final_block.append(Paragraph("Sección 18 Resumen del Examen Semestral Banfield", styles["Section"]))
    else:
        final_block.append(Paragraph("Sección 18 Resumen del Examen Semestral Banfield", styles["Section"]))

    resumen_flowables = generar_resumen_narrativo(data, styles)
    res_table = Table([[resumen_flowables]], colWidths=[510], hAlign="LEFT")
    res_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(LIGHT_BLUE)),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0DCE9")),
        ("LEFTPADDING", (0, 0), (-1, -1), 15),
        ("RIGHTPADDING", (0, 0), (-1, -1), 15),
        ("TOPPADDING", (0, 0), (-1, -1), 15),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 15),
    ]))
    final_block.append(res_table)
    
    # ================= FIRMA Y DIRECCIÓN =================
    firma_str = data["medico"].strip()
    if " - Ced. " in firma_str:
        partes = firma_str.split(" - Ced. ")
        medico_nombre = partes[0]
        medico_cedula = partes[1]
    else:
        medico_nombre = firma_str if firma_str != "Otro" else ""
        medico_cedula = ""

    final_block.append(Spacer(1, 30))
    firma_texto = f"<b>MVZ Responsable:</b> {ptext(medico_nombre)}<br/><b>Cédula Profesional:</b> {ptext(medico_cedula)}"
    final_block.append(Paragraph(firma_texto, styles["Body"]))
    
    final_block.append(Spacer(1, 30))
    address_style = ParagraphStyle("Address", parent=styles["Body"], alignment=TA_LEFT, textColor=colors.HexColor(BANFIELD_BLUE), fontSize=9)
    direccion = "<b>Banfield Pet Hospital México</b><br/>Av. Antonio Delfín Madrigal S/N Col. Cd. Universitaria, Coyoacán C.P. 04510<br/>55-5658-6080"
    final_block.append(Paragraph(direccion, address_style))

    story.append(KeepTogether(final_block))

    doc.build(story, onFirstPage=cover_footer, onLaterPages=regular_footer)
    return buffer.getvalue()

def build_via_text(d: dict) -> str:
    lines = [
        "--- DATOS GENERALES ---",
        f"MASCOTA: {d['mascota']} ({d['especie']})",
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
        "--- SECCION 1 CONDICION GENERAL ---",
        f"CONDICION GENERAL: {d['cond_gral']}",
        f"CONDICION PESO: {d['peso']}",
        f"ALIMENTO SECO: {clean_text(d['alim_seco'])}",
        f"ALIMENTO HUMEDO: {clean_text(d['alim_humedo'])}",
        f"NUTRACEUTICOS: {clean_text(d['nutra'])}",
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
        "--- SECCION 5 EXAMEN RECTAL ---",
        f"PROSTATA/RECTO: {d['pros']}",
        f"TUMORES RECTALES: {d['tum_rect']}",
        f"HERNIAS: {d['hern']}",
        f"SACOS ANALES: {d['sacos']}",
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
        f"PARDPADOS OD: {d['def_od']}",
        f"TUMORES OD: {d['tum_od']}",
        f"CONJUNTIVA OI: {d['conj_oi']}",
        f"SECRECION OI: {d['sec_oi']}",
        f"PARDPADOS OI: {d['def_oi']}",
        f"TUMORES OI: {d['tum_oi']}",
        f"RECOMENDACION OFTALMICA: {clean_text(d['rec_oftalmica'])}",
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
        "--- SECCION 9 MUSCULOESQUELETICO ---",
        f"CUELLO Y CABEZA: {d['cue']}",
        f"ESPALDA: {d['esp']}",
        f"COLA: {d['cola']}",
        f"MIEMBRO ANT DER: {d['mad']}",
        f"MIEMBRO ANT IZQ: {d['mai']}",
        f"MIEMBRO POST DER: {d['mpd']}",
        f"MIEMBRO POST IZQ: {d['mpi']}",
        "--- SECCION 10 NEUROLOGICO ---",
        f"ESTADO MENTAL: {d['ment']}",
        f"NERVIOS CRANEALES: {d['cran']}",
        f"REFLEJOS PROPIOCEPTIVOS: {d['prop']}",
        f"REFLEJOS PATELARES: {d['patel']}",
        f"DOLOR DIGITOPRESION: {d['dolor']} ({d['reg_dolor']})",
        "--- SECCION 11 CARDIOVASCULAR ---",
        f"FRECUENCIA CV: {d['f_car']}",
        f"PULSO CV: {d['pul_car']}",
        f"SOPLO CV: {d['sop_car']}",
        f"RITMO CV: {d['rit_car']}",
        f"TLLC CV: {d['tllc_car']}",
        "--- SECCION 12 CAMPOS PULMONARES ---",
        f"PULMON CRANEAL DER: {d['cd']}",
        f"PULMON CAUDAL DER: {d['cad']}",
        f"PULMON CRANEAL IZQ: {d['ci']}",
        f"PULMON CAUDAL IZQ: {d['cai']}",
        f"NOTAS SECCION 12: {d['notas_s12']}",
        "--- SECCION 13 PRUEBAS SANGUINEAS ---",
        f"PRUEBAS ESPECIFICAS: {d['leu'] if d['especie']=='Felino' else d['hemo']}",
        "--- SECCION 14 EXCREMENTO ---",
        f"TOXOCARA: {d['tox']}",
        f"COCCIDIA: {d['coc']}",
        f"NEMATODOS: {d['nem']}",
        f"GIARDIA: {d['gia']}",
        f"GYPILIDIUM: {d['gyp']}",
        f"CESTODOS: {d['ces']}",
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
        "--- SECCION 17 RECOMENDACIONES ---",
        f"PLAN: {d['recomendaciones']}",
        "--- SECCION 18 RESUMEN ---",
        f"MVZ RESPONSABLE: {d['medico']}"
    ]
    return "\n".join([line for line in lines if line.strip()]).upper()

with st.sidebar:
    logo_unam = asset_path("Banfield-Pet-Hospital.png")
    if logo_unam:
        st.image(str(logo_unam), use_container_width=True)
    st.markdown(f"<h3 style='text-align:center;' class='banfield-text'>UNAM-Banfield</h3>", unsafe_allow_html=True)
    st.caption("Reporte semestral · Plan de Bienestar")
    
    st.header("Datos generales")
    especie = st.radio("Especie", ["Canino", "Felino"])
    mascota = st.text_input("Nombre de la mascota", key="mascota")
    familia = st.text_input("Propietario", key="familia")
    
    st.markdown("<b class='banfield-text'>Edad del Paciente</b>", unsafe_allow_html=True)
    c_a, c_m = st.columns(2)
    anios = c_a.selectbox("Años", [str(i) for i in range(31)], key="anios")
    meses = c_m.selectbox("Meses", [str(i) for i in range(12)], key="meses")
    edad = f"{meses} meses" if anios == "0" else f"{anios} años, {meses} meses"
    
    fecha = st.date_input("Fecha del examen", key="fecha")
    medico = select_con_otro("MVZ Responsable", medicos, "medico")

    # --- PORTAL DE CARGA MÓVIL (CÓDIGO QR) ---
    st.markdown("---")
    st.markdown("<b class='banfield-text'>📱 Portal de Carga Móvil</b>", unsafe_allow_html=True)
    if st.button("Generar Código QR", use_container_width=True):
        if not mascota.strip():
            st.error("Ingresa el nombre del paciente primero.")
        else:
            token = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            url_movil = f"https://tu-hospital-pbb.streamlit.app/movil?paciente={urllib.parse.quote(mascota)}&token={token}"
            qr_api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=180x180&data={urllib.parse.quote(url_movil)}"
            
            st.image(qr_api_url, caption=f"Escanea para sincronizar cámara con {mascota}")
            st.info("El teléfono entrará en Modo Cámara. (La sincronización real requiere integrar Firebase en el próximo paso).")

st.title("Reporte y hallazgos del examen semestral")
tabs = st.tabs(["S1–S2 General y piel", "S3–S5 Abdomen", "S6–S8 Dental y sentidos", "S9–S12 Sistemas", "S13–S15 Pruebas Lab", "S16–S17 Preventivos y Plan"])

data = {"mascota": mascota, "familia": familia, "edad": edad, "fecha": fecha.strftime("%d/%m/%Y"), "medico": medico, "especie": especie}

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
    data["mucosas"] = select_con_otro("Mucosas", ["Rosas y húmedas", "Pálidas", "Congestivas", "Ictéricas", "Otro", "Ninguno"], "mucosas")
    data["spo2"] = c3.text_input("% SpO2", key="spo2")
    data["pam"] = c4.text_input("PAM", key="pam")
    data["foto_constantes"] = renderizar_uploader("Constantes", "foto_constantes")

    ui_header("Sección 1 Condición general", "Examen.png")
    c1, c2 = st.columns(2)
    data["cond_gral"] = c1.selectbox("Condición general", ["Excelente", "Buena", "Necesita mejorar", "No evaluado", "Ninguno"], key="cond_gral")
    data["peso"] = c2.selectbox("Condición de peso", ["Perfecto", "Demasiado delgado", "Muy pesado", "No evaluado", "Ninguno"], key="peso")
    
    c1, c2 = st.columns(2)
    data["alim_seco"] = multiselect_con_otro("Alimento SECO sugerido", alimentos_secos, "alim_seco")
    data["alim_humedo"] = multiselect_con_otro("Alimento HÚMEDO sugerido", alimentos_humedos, "alim_humedo")
    
    data["nutra"] = multiselect_con_otro("Complementos / nutracéuticos", nutraceuticos_list, "nutra")
    data["foto_s1"] = renderizar_uploader("Condición general", "foto_s1")

    ui_header("Sección 2 Pelo y piel", "Pelo y piel.png")
    c1, c2 = st.columns(2)
    data["pelo_piel"] = c1.selectbox("Pelo y piel", ["Parece normal", "Anormal", "No evaluado", "Ninguno"], key="pelo_piel")
    
    data["lesiones_raw"] = c2.multiselect("Lesiones observadas", ["Máculas", "Escamas", "Excoriaciones", "Eritema", "Hiperpigmentación", "Alopecia", "Úlceras"], key="lesiones")
    data["planos_por_lesion"] = []
    
    if data["lesiones_raw"]:
        st.markdown("<small><b>Especifique los planos anatómicos afectados por cada lesión:</b></small>", unsafe_allow_html=True)
        for lesion in data["lesiones_raw"]:
            plano = st.text_input(f"Plano(s) para {lesion} (Dejar vacío si no aplica)", key=f"plano_{lesion}")
            if plano.strip():
                data["planos_por_lesion"].append(f"{lesion} ({plano.strip()})")
            else:
                data["planos_por_lesion"].append(lesion)
                
    data["rec_piel"] = multiselect_con_otro("Producto dermatológico recomendado", piel_pelo, "rec_piel")
    data["shampoo_rec"] = multiselect_con_otro("Shampoo recomendado", shampoos, "shampoo_rec")
    
    c1, c2 = st.columns(2)
    data["ectoparasitos"] = c1.selectbox("Ectoparásitos", ["Ninguno presente", "Pulgas", "Piojos", "Garrapatas", "No evaluado", "Ninguno"], key="ectoparasitos")
    data["c_pulgas"] = c2.selectbox("Control antipulgas", ["Sin pulgas: continuar o iniciar prevención", "Tiene pulgas: se necesita controlar", "Ninguno"], key="c_pulgas")
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
        data["trat_pulgas"] = f"- Mascota: {t_mascota}\n- Casa: {t_casa}\n- Coche: {t_coche}\n- Patio: Rociar cada {t_patio} semana(s)\n- Producto(s): {prod_str}"
        
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
    data["imp_gral"] = st.selectbox("Impresión general", ["Dentro de límites normales", "Anormal", "No evaluado", "Ninguno"], key="imp_gral")
    data["notas_s3"] = st.text_area("Notas de la sección 3", key="notas_s3")
    data["foto_s3"] = renderizar_uploader("Abdomen", "foto_s3")

    ui_header("Sección 4 Examen urogenital")
    c1, c2 = st.columns(2)
    posneg = ["Negativo", "Positivo", "No evaluado", "Ninguno"]
    data["secr_uro"] = c1.selectbox("Secreción urogenital", posneg, key="secr_uro")
    data["infl_uro"] = c2.selectbox("Inflamación / infección urogenital", posneg, key="infl_uro")
    data["bult_uro"] = c1.selectbox("Bultos / crecimientos", posneg, key="bult_uro")
    data["tum_mam"] = c2.selectbox("Tumores mamarios", posneg, key="tum_mam")
    data["foto_s4"] = renderizar_uploader("Urogenital", "foto_s4")

    ui_header("Sección 5 Examen rectal")
    c1, c2 = st.columns(2)
    data["pros"] = c1.selectbox("Próstata / recto", ["Normal", "Anormal", "No evaluado", "Ninguno"], key="pros")
    data["tum_rect"] = c2.selectbox("Tumores / crecimientos", posneg, key="tum_rect")
    data["hern"] = c1.selectbox("Hernias / hinchazón", posneg, key="hern")
    data["sacos"] = c2.selectbox("Sacos anales", ["Vacío", "Normal", "Anormal", "No evaluado", "Ninguno"], key="sacos")
    data["foto_s5"] = renderizar_uploader("Rectal", "foto_s5")

with tabs[2]:
    ui_header("Sección 6 Examen dental / oral", "Dental.png")
    c1, c2 = st.columns(2)
    posneg = ["Negativo", "Positivo", "No evaluado", "Ninguno"]
    data["epo"] = c1.selectbox("Enfermedad Periodontal (EPO)", ["Negativo", "Grado I", "Grado II", "Grado III", "Grado IV", "Ninguno"], key="epo")
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
    
    data["rec_oftalmica"] = multiselect_con_otro("Producto sugerido (Oftálmico)", oftalmico_list, "rec_oftalmica")
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
    data["foto_s9"] = renderizar_uploader("Musculoesquelético", "foto_s9")

    ui_header("Sección 10 Examen neurológico")
    c1, c2 = st.columns(2)
    data["ment"] = c1.selectbox("Estado mental", opn, key="ment")
    data["cran"] = c2.selectbox("Nervios craneales", opn, key="cran")
    data["prop"] = c1.selectbox("Reflejos propioceptivos", opn, key="prop")
    data["patel"] = c2.selectbox("Reflejos patelares", opn, key="patel")
    data["dolor"] = c1.selectbox("Dolor a la digitopresión", ["Negativo", "Positivo", "No evaluado", "Ninguno"], key="dolor")
    data["reg_dolor"] = c2.text_input("Región del dolor (si aplica)", key="reg_dolor")
    data["foto_s10"] = renderizar_uploader("Neurológico", "foto_s10")

    ui_header("Sección 11 Cardiovascular / corazón", "Corazon.png")
    c1, c2 = st.columns(2)
    data["f_car"] = c1.selectbox("Frecuencia CV", opn, key="f_car")
    data["pul_car"] = c2.selectbox("Pulso", opn, key="pul_car")
    data["sop_car"] = c1.selectbox("Soplo/sonido anormal", ["Negativo", "Positivo", "No evaluado", "Ninguno"], key="sop_car")
    data["rit_car"] = c2.selectbox("Ritmo", opn, key="rit_car")
    data["tllc_car"] = c1.selectbox("TLLC CV", opn, key="tllc_car")

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

    ui_header("Sección 14 Hallazgos en examen de excremento")
    c1, c2, c3 = st.columns(3)
    negpos = ["Negativo", "Positivo", "No realizado", "Ninguno"]
    data["tox"] = c1.selectbox("Toxocara", negpos, key="tox")
    data["coc"] = c2.selectbox("Coccidia", negpos, key="coc")
    data["nem"] = c3.selectbox("Nemátodos", negpos, key="nem")
    data["gia"] = c1.selectbox("Giardia", negpos, key="gia")
    data["gyp"] = c2.selectbox("Gypilidium", negpos, key="gyp")
    data["ces"] = c3.selectbox("Céstodos", negpos, key="ces")

    ui_header("Sección 15 Análisis de sangre y Uroanálisis", "5.png")
    st.subheader("Hemograma y Química Sanguínea")
    op_n = ["Normal", "Anormal", "No evaluado", "Ninguno"]
    c1, c2, c3 = st.columns(3)
    data["eritrocitos"] = c1.selectbox("Conteo de eritrocitos", op_n)
    data["leucocitos_s"] = c2.selectbox("Conteo de leucocitos", op_n)
    data["tiroides"] = c3.selectbox("Prueba de Tiroides", ["Normal", "Anormal", "Pendiente", "No evaluado", "Ninguno"])
    
    c1, c2, c3 = st.columns(3)
    data["enz_ren"] = c1.selectbox("Enzimas renales", op_n)
    data["enz_hep"] = c2.selectbox("Enzimas hepáticas", op_n)
    data["enz_pan"] = c3.selectbox("Enzimas pancreáticas", op_n)
    
    c1, c2 = st.columns(2)
    data["electrolitos"] = c1.selectbox("Electrólitos", op_n)
    data["prot_ser"] = c2.selectbox("Proteínas séricas", op_n)

    st.subheader("Uroanálisis")
    c1, c2, c3 = st.columns(3)
    data["uro_urobilinogeno"] = c1.selectbox("Urobilinógeno", op_n)
    data["uro_sangre"] = c2.selectbox("Sangre", op_n)
    data["uro_bilirrubina"] = c3.selectbox("Bilirrubina", op_n)
    
    c1, c2, c3 = st.columns(3)
    data["uro_cetona"] = c1.selectbox("Cetona", op_n)
    data["uro_proteina"] = c2.selectbox("Proteína", op_n)
    data["uro_ph"] = c3.selectbox("pH", op_n)
    data["uro_gravedad"] = c1.selectbox("Gravedad específica", op_n)

    st.subheader("Sedimento urinario")
    c1, c2, c3, c4 = st.columns(4)
    data["sed_eritrocitos"] = c1.selectbox("Eritrocitos (sedimento)", ["No presente", "Presente", "Ninguno"])
    data["sed_leucocitos"] = c2.selectbox("Leucocitos (sedimento)", ["No presente", "Presente", "Ninguno"])
    data["sed_bacterias"] = c3.selectbox("Bacterias", ["No presente", "Presente", "Ninguno"])
    data["sed_cilindros"] = c4.selectbox("Cilindros renales", ["No presente", "Presente", "Ninguno"])
    data["tipo_cilindros"] = st.text_input("Tipo de cilindros (si aplica)")
    data["notas_uro"] = st.text_area("Otras observaciones y hallazgos (Laboratorio)")
    data["foto_lab"] = renderizar_uploader("Laboratorio", "foto_lab")

with tabs[5]:
    img_prev = "OWP_Puppy.png" if data['especie'] == "Canino" else "OWP_Gatito.png"
    ui_header("Sección 16 Cuidado preventivo aplicado en esta visita", img_prev)
    
    vac_sel = st.multiselect("Selecciona las vacunas aplicadas", [v for v in vacunas_filtradas if v != "Ninguno"], key="vacunas")
    if "Otro" in vac_sel:
        otro_v = st.text_input("Especifique otra vacuna", key="vac_otra_txt")
        if otro_v: vac_sel = [v for v in vac_sel if v != "Otro"] + [otro_v]
    
    data["vac_raw_data"] = []
    if vac_sel:
        for i, v in enumerate(vac_sel):
            c1, c2 = st.columns([1, 2])
            fecha_vac = c1.date_input(f"Fecha - {v}", datetime.date.today(), key=f"f_vac_{i}")
            lote = c2.text_input(f"Lote/Marca - {v}", key=f"l_vac_{i}")
            info = f"{v}: Lote {lote} (Aplicada: {fecha_vac.strftime('%d/%m/%Y')})" if lote else f"{v} (Aplicada: {fecha_vac.strftime('%d/%m/%Y')})"
            data["vac_raw_data"].append(info)
            
    data["desp_interno_seleccionado"] = multiselect_con_otro("Desparasitante Interno", desp_int, "desp_interno")

    ui_header("Sección 17 Otras recomendaciones y plan", "Engranes.png")
    data["recomendaciones"] = st.text_area("Instrucciones para el cliente", height=120, key="recomendaciones")

st.markdown("---")
col1, col2 = st.columns([1, 1])

with col1:
    if st.button("Generar reporte PDF", type="primary", use_container_width=True):
        if not data["mascota"].strip():
            st.error("Captura el nombre de la mascota.")
        else:
            try:
                st.session_state["generated_pdf"] = build_pdf(data)
                st.session_state["generated_pdf_name"] = f"PBB_{safe_filename(data['mascota'])}_Reporte.pdf"
                st.success("PDF generado exitosamente. Haz clic abajo para descargar.")
            except Exception as exc: st.error(f"No se pudo generar: {exc}")

with col2:
    if st.button("Generar texto para VIA", use_container_width=True):
        if not data["mascota"].strip(): st.error("Captura el nombre de la mascota.")
        else: st.session_state["via_text"] = build_via_text(data)

if st.session_state.get("generated_pdf"):
    st.download_button("Descargar PDF institucional", data=st.session_state["generated_pdf"], file_name=st.session_state.get("generated_pdf_name", "PBB_Reporte.pdf"), mime="application/pdf", use_container_width=True)

if st.session_state.get("via_text"):
    st.text_area("Copiar en VIA", value=st.session_state["via_text"], height=260)
    st.download_button("Descargar texto VIA (.txt)", data=st.session_state["via_text"], file_name=f"PBB_{safe_filename(data['mascota'])}_VIA.txt", mime="text/plain; charset=utf-8", use_container_width=True)