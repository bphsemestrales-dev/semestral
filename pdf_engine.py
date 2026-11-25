from __future__ import annotations

import html
from io import BytesIO

import streamlit as st
from PIL import Image as PILImage
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

from clinical_rules import (
    classify_clinical_value,
    format_badge_html,
    generar_resumen_narrativo,
)
from config import (
    BANFIELD_BLUE,
    BANFIELD_GREY,
    BANFIELD_NAVY,
    BANFIELD_ORANGE,
    BANFIELD_ORANGE_LIGHT,
    BORDER_GREY,
    DARK_GREY,
    LIGHT_BLUE,
    SURFACE_GREY,
    asset_path,
    clean_text,
    ptext,
)


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
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(BORDER_GREY)),
                ("INNERGRID", (0, 1), (-1, -1), 0.35, colors.HexColor(BORDER_GREY)),
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
    is_blank: bool = False,
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

    if is_blank:
        note_box = Table(
            [[Paragraph("<b>Notas:</b>", styles["Small"])]],
            colWidths=[510],
            rowHeights=[24],
            hAlign="LEFT",
        )
        note_box.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor(BORDER_GREY)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(note_box)
        story.append(Spacer(1, 3))
    elif notes and clean_text(notes):
        story.append(Paragraph(f"<b>Notas:</b> {ptext(notes)}", styles["Body"]))
        story.append(Spacer(1, 3))

    story.append(Spacer(1, 8))



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
    is_blank = bool(data.get("_is_blank_template"))
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

    if is_blank:
        c_data = (
            f"Mascota: ________________________ (Especie: {ptext(data['especie'])} · "
            f"Sexo: {ptext(data.get('sexo', ''))} · {ptext(data.get('estado_reproductivo', ''))})<br/>"
            "Propietario: ________________________<br/>"
            "Edad: ________________________<br/>"
            "Fecha: ________________________"
        )
    else:
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

    if is_blank:
        s_constantes = [
            ("Peso (kg)", " "),
            ("Frecuencia cardiaca (lpm)", " "),
            ("Frecuencia respiratoria (rpm)", " "),
            ("Temperatura (°C)", " "),
            ("TLLC (segundos)", " "),
            ("Mucosas", " "),
        ]
    else:
        s_constantes = [
            ("Peso", f"{ptext(data['peso_kg'])} kg" if clean_text(data["peso_kg"]) else "—"),
            ("Frecuencia cardiaca", f"{ptext(data['fc'])} lpm" if clean_text(data["fc"]) else "—"),
            ("Frecuencia respiratoria", f"{ptext(data['fr'])} rpm" if clean_text(data["fr"]) else "—"),
            ("Temperatura", f"{ptext(data['temp'])} °C" if clean_text(data["temp"]) else "—"),
            ("TLLC", f"{ptext(data['tllc'])} segundos" if clean_text(data["tllc"]) else "—"),
            ("Mucosas", f"{ptext(data['mucosas'])}"),
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
        is_blank=is_blank,
    )

    s1_cond = [
        ("Condición general", " " if is_blank else f"{ptext(data['cond_gral'])}"),
        ("Condición corporal / peso (BCS 1-9)", " " if is_blank else f"{ptext(data['peso'])}"),
    ]
    s1_nutri = []
    if is_blank:
        s1_nutri = [
            ("Indicación sobre dieta y porción", " "),
            ("Alimento seco sugerido", " "),
            ("Alimento húmedo sugerido", " "),
            ("Nutracéuticos / Complementos", " "),
        ]
    else:
        if clean_text(data.get("plan_nutricional")):
            s1_nutri.append(("Indicación sobre dieta y porción", f"{ptext(data.get('plan_nutricional'))}"))
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
        is_blank=is_blank,
    )

    if is_blank:
        s2_derma = [
            ("Pelo y piel", " "),
            ("Lesiones y planos anatómicos afectados", " "),
            ("Producto dermatológico recomendado", " "),
            ("Shampoo sugerido", " "),
        ]
        s2_paras = [
            ("Ectoparásitos", " "),
            ("Control antipulgas recetado", " "),
            ("Plan de control antipulgas", " "),
        ]
    else:
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
        is_blank=is_blank,
    )

    s3_abd = [
        ("Hígado", " " if is_blank else f"{ptext(data['hig'])}"),
        ("Estómago", " " if is_blank else f"{ptext(data['est'])}"),
        ("Bazo", " " if is_blank else f"{ptext(data['bazo'])}"),
    ]
    s3_rin = [
        ("Riñón derecho", " " if is_blank else f"{ptext(data['rd'])}"),
        ("Riñón izquierdo", " " if is_blank else f"{ptext(data['ri'])}"),
    ]
    s3_int = [
        ("Intestinos / mesenterio", " " if is_blank else f"{ptext(data['int_mes'])}"),
        ("Impresión general", " " if is_blank else f"{ptext(data['imp_gral'])}"),
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
        is_blank=is_blank,
    )

    s4_uro = [
        ("Secreción urogenital", " " if is_blank else f"{ptext(data['secr_uro'])}"),
        ("Inflamación / infección", " " if is_blank else f"{ptext(data['infl_uro'])}"),
        ("Bultos / crecimientos", " " if is_blank else f"{ptext(data['bult_uro'])}"),
        ("Tumores mamarios", " " if is_blank else f"{ptext(data['tum_mam'])}"),
    ]
    # Campos condicionales por Sexo / Estado Reproductivo / Especie
    if data.get("sexo") == "Macho":
        s4_uro.append(("Pene y prepucio", " " if is_blank else f"{ptext(data.get('uro_pene_prepucio'))}"))
        if data.get("estado_reproductivo") == "Entero(a)":
            s4_uro.append(("Testículos y escroto", " " if is_blank else f"{ptext(data.get('uro_testiculos'))}"))
        if data.get("especie") == "Canino":
            s4_uro.append(("Evaluación de próstata", " " if is_blank else f"{ptext(data.get('uro_prostata_macho'))}"))
    elif data.get("sexo") == "Hembra":
        s4_uro.append(("Vulva y área perivulvar", " " if is_blank else f"{ptext(data.get('uro_vulva'))}"))
        if is_blank:
            s4_uro.append(("Cadena mamaria individualizada", " "))
        else:
            cad_mam = ptext(data.get("uro_cadena_mamaria"))
            if clean_text(data.get("uro_detalle_mamas")):
                cad_mam += f" ({ptext(data.get('uro_detalle_mamas'))})"
            s4_uro.append(("Cadena mamaria individualizada", cad_mam))
        if data.get("estado_reproductivo") == "Entero(a)":
            s4_uro.append(("Fecha aprox. de último celo", " " if is_blank else f"{ptext(data.get('uro_ultimo_celo'))}"))

    add_section_pdf(
        story,
        "Sección 4 Examen Urogenital",
        [("Examen Urogenital", s4_uro)],
        styles,
        notes=data.get("notas_s4"),
        photo_list=data.get("foto_s4"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
        is_blank=is_blank,
    )

    s5_rect = [
        ("Próstata / recto", " " if is_blank else f"{ptext(data['pros'])}"),
        ("Tumores / crecimientos", " " if is_blank else f"{ptext(data['tum_rect'])}"),
        ("Hernias / hinchazón", " " if is_blank else f"{ptext(data['hern'])}"),
        ("Sacos anales", " " if is_blank else f"{ptext(data['sacos'])}"),
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
        is_blank=is_blank,
    )

    s6_dientes = [
        ("Enfermedad Periodontal (EPO)", " " if is_blank else f"{ptext(data['epo'])}"),
        ("Sarro", " " if is_blank else f"{ptext(data['sarro'])}"),
        ("Mordida", " " if is_blank else f"{ptext(data['mord'])}"),
        ("Decoloración dental", " " if is_blank else f"{ptext(data['decol_d'])}"),
    ]
    s6_encias = [
        ("Hinchazón de encías", " " if is_blank else f"{ptext(data['hinc_e'])}"),
        ("Encías retraídas", " " if is_blank else f"{ptext(data['retr_e'])}"),
        ("Infección de encías", " " if is_blank else f"{ptext(data['inf_e'])}"),
        ("Tumores / épulis", " " if is_blank else f"{ptext(data['epul_e'])}"),
    ]
    s6_boca = [
        ("Amígdalas (Inflamación)", " " if is_blank else f"{ptext(data['inf_a'])}"),
        ("Amígdalas (Hinchazón)", " " if is_blank else f"{ptext(data['hinc_a'])}"),
        ("Lengua (Inflamación)", " " if is_blank else f"{ptext(data['inf_l'])}"),
        ("Lengua (Decoloración)", " " if is_blank else f"{ptext(data['dec_l'])}"),
        ("Lengua (Hinchazón)", " " if is_blank else f"{ptext(data['hinc_l'])}"),
        ("Nódulos linfáticos", " " if is_blank else f"{ptext(data['tal_n'])}"),
        ("Consistencia de nódulos", " " if is_blank else f"{ptext(data['con_n'])}"),
        ("Inflamación de garganta", " " if is_blank else f"{ptext(data['inf_g'])}"),
        ("Reflejos faríngeos", " " if is_blank else f"{ptext(data['ref_g'])}"),
    ]
    s6_agrupado = [
        ("Dientes y Enfermedad", s6_dientes),
        ("Encías", s6_encias),
        ("Amígdalas, Lengua y Garganta", s6_boca),
    ]
    if is_blank:
        s6_agrupado.append(("Recomendación Médica", [("Producto(s) sugerido(s)", " ")]))
    elif data["rec_dental"] and clean_text(data["rec_dental"]):
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
        is_blank=is_blank,
    )
    add_info_box(
        story,
        "Nota Dental",
        "La Enfermedad Periodontal (EPO) se clasifica en grados. El Grado I indica gingivitis leve, mientras que los Grados II a IV implican pérdida progresiva de la adherencia dental, pérdida ósea y riesgo de infecciones sistémicas.",
        styles,
    )

    if is_blank:
        pio_od_str = " "
        pio_oi_str = " "
    else:
        pio_od_str = f"{ptext(data.get('pio_od'))} mmHg (Ref. 10-25)" if clean_text(data.get("pio_od")) else "—"
        pio_oi_str = f"{ptext(data.get('pio_oi'))} mmHg (Ref. 10-25)" if clean_text(data.get("pio_oi")) else "—"

    s7_od = [
        ("Conjuntiva OD", " " if is_blank else f"{ptext(data['conj_od'])}"),
        ("Secreción OD", " " if is_blank else f"{ptext(data['sec_od'])}"),
        ("Deformidad párpados OD", " " if is_blank else f"{ptext(data['def_od'])}"),
        ("Tumores/quistes OD", " " if is_blank else f"{ptext(data['tum_od'])}"),
        ("Presión Intraocular (PIO) OD [mmHg]", pio_od_str),
    ]
    s7_oi = [
        ("Conjuntiva OI", " " if is_blank else f"{ptext(data['conj_oi'])}"),
        ("Secreción OI", " " if is_blank else f"{ptext(data['sec_oi'])}"),
        ("Deformidad párpados OI", " " if is_blank else f"{ptext(data['def_oi'])}"),
        ("Tumores/quistes OI", " " if is_blank else f"{ptext(data['tum_oi'])}"),
        ("Presión Intraocular (PIO) OI [mmHg]", pio_oi_str),
    ]
    s7_agrupado = [("Oftálmico (Ojo Derecho)", s7_od), ("Oftálmico (Ojo Izquierdo)", s7_oi)]
    if is_blank:
        s7_agrupado.append(("Recomendación", [("Producto oftalmológico", " ")]))
    elif data["rec_oftalmica"] and clean_text(data["rec_oftalmica"]):
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
        is_blank=is_blank,
    )

    s8_od = [
        ("Orejas OD", " " if is_blank else f"{ptext(data['ore_od'])}"),
        ("Membrana timpánica OD", " " if is_blank else f"{ptext(data['tim_od'])}"),
        ("Ácaros OD", " " if is_blank else f"{ptext(data['aca_od'])}"),
        ("Tumores/quistes OD", " " if is_blank else f"{ptext(data['tum_oido_od'])}"),
        ("Inflamación OD", " " if is_blank else f"{ptext(data['inf_oido_od'])}"),
        ("Secreción ótica OD", " " if is_blank else f"{ptext(data['sec_oido_od'])}"),
    ]
    s8_oi = [
        ("Orejas OI", " " if is_blank else f"{ptext(data['ore_oi'])}"),
        ("Membrana timpánica OI", " " if is_blank else f"{ptext(data['tim_oi'])}"),
        ("Ácaros OI", " " if is_blank else f"{ptext(data['aca_oi'])}"),
        ("Tumores/quistes OI", " " if is_blank else f"{ptext(data['tum_oido_oi'])}"),
        ("Inflamación OI", " " if is_blank else f"{ptext(data['inf_oido_oi'])}"),
        ("Secreción ótica OI", " " if is_blank else f"{ptext(data['sec_oido_oi'])}"),
    ]
    s8_agrupado = [("Otoscópico (Oído Derecho)", s8_od), ("Otoscópico (Oído Izquierdo)", s8_oi)]
    if is_blank:
        s8_agrupado.append(("Recomendación", [("Producto otológico", " ")]))
    elif data["rec_otica"] and clean_text(data["rec_otica"]):
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
        is_blank=is_blank,
    )

    s9_col = [
        ("Cuello y cabeza", " " if is_blank else f"{ptext(data['cue'])}"),
        ("Espalda", " " if is_blank else f"{ptext(data['esp'])}"),
        ("Cola", " " if is_blank else f"{ptext(data['cola'])}"),
    ]
    s9_mie = [
        ("Miembro anterior derecho", " " if is_blank else f"{ptext(data['mad'])}"),
        ("Miembro anterior izquierdo", " " if is_blank else f"{ptext(data['mai'])}"),
        ("Miembro posterior derecho", " " if is_blank else f"{ptext(data['mpd'])}"),
        ("Miembro posterior izquierdo", " " if is_blank else f"{ptext(data['mpi'])}"),
    ]
    if is_blank:
        s9_marcha = [
            ("Tipo de marcha", " "),
            ("Miembro(s) afectado(s) (si aplica)", " "),
            ("Grado de claudicación (1 al 5)", " "),
        ]
    else:
        s9_marcha = [("Tipo de marcha", f"{ptext(data.get('tipo_marcha'))}")]
        if data.get("tipo_marcha") in ("Claudicación / Renguea", "Dificultad para levantarse / Rigidez"):
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
        is_blank=is_blank,
    )

    s10_gral = [
        ("Estado mental", " " if is_blank else f"{ptext(data['ment'])}"),
        ("Nervios craneales", " " if is_blank else f"{ptext(data['cran'])}"),
    ]
    s10_ref = [
        ("Reflejos propioceptivos", " " if is_blank else f"{ptext(data['prop'])}"),
        ("Reflejos patelares", " " if is_blank else f"{ptext(data['patel'])}"),
        ("Dolor a la digitopresión", " " if is_blank else f"{ptext(data['dolor'])}"),
        ("Región del dolor", " " if is_blank else f"{ptext(data['reg_dolor'])}"),
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
        is_blank=is_blank,
    )

    s11_cv = [
        ("Frecuencia cardiaca", " " if is_blank else f"{ptext(data['f_car'])}"),
        ("Pulso", " " if is_blank else f"{ptext(data['pul_car'])}"),
        ("Soplo o sonido anormal", " " if is_blank else f"{ptext(data['sop_car'])}"),
        ("Ritmo", " " if is_blank else f"{ptext(data['rit_car'])}"),
        ("Tiempo de Llenado Capilar", " " if is_blank else f"{ptext(data['tllc_car'])}"),
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
        is_blank=is_blank,
    )

    s12_pul = [
        ("Craneal derecho", " " if is_blank else f"{ptext(data['cd'])}"),
        ("Caudal derecho", " " if is_blank else f"{ptext(data['cad'])}"),
        ("Craneal izquierdo", " " if is_blank else f"{ptext(data['ci'])}"),
        ("Caudal izquierdo", " " if is_blank else f"{ptext(data['cai'])}"),
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
        is_blank=is_blank,
    )

    if data["especie"] == "Felino":
        s13_items = [
            ("Leucemia felina", " " if is_blank else f"{ptext(data['leu'])}"),
            ("SIDA felino", " " if is_blank else f"{ptext(data['sida'])}"),
        ]
    else:
        s13_items = [("Hemoparásitos caninos", " " if is_blank else f"{ptext(data['hemo'])}")]

    add_section_pdf(
        story,
        "Sección 13 Pruebas sanguíneas virales / vectoriales",
        [("Pruebas Específicas", s13_items)],
        styles,
        "5.png",
        notes=data.get("notas_s13"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
        is_blank=is_blank,
    )

    s14_items = [
        ("Toxocara", " " if is_blank else f"{ptext(data['tox'])}"),
        ("Coccidia", " " if is_blank else f"{ptext(data['coc'])}"),
        ("Nemátodos", " " if is_blank else f"{ptext(data['nem'])}"),
        ("Giardia", " " if is_blank else f"{ptext(data['gia'])}"),
        ("Dypilidium", " " if is_blank else f"{ptext(data['gyp'])}"),
        ("Céstodos", " " if is_blank else f"{ptext(data['ces'])}"),
    ]
    add_section_pdf(
        story,
        "Sección 14 Hallazgos en examen de excremento",
        [("Examen de Excremento", s14_items)],
        styles,
        notes=data.get("notas_s14"),
        two_column_grid=two_column_grid,
        hide_unassessed=hide_unassessed,
        is_blank=is_blank,
    )

    s15_hemo = [
        ("Conteo de eritrocitos", " " if is_blank else f"{ptext(data['eritrocitos'])}"),
        ("Conteo de leucocitos", " " if is_blank else f"{ptext(data['leucocitos_s'])}"),
        ("Prueba de Tiroides", " " if is_blank else f"{ptext(data['tiroides'])}"),
        ("Enzimas renales", " " if is_blank else f"{ptext(data['enz_ren'])}"),
        ("Enzimas hepáticas", " " if is_blank else f"{ptext(data['enz_hep'])}"),
        ("Enzimas pancreáticas", " " if is_blank else f"{ptext(data['enz_pan'])}"),
        ("Electrólitos", " " if is_blank else f"{ptext(data['electrolitos'])}"),
        ("Proteínas séricas", " " if is_blank else f"{ptext(data['prot_ser'])}"),
    ]
    s15_uro = [
        ("Urobilinógeno", " " if is_blank else f"{ptext(data['uro_urobilinogeno'])}"),
        ("Sangre (Uroanálisis)", " " if is_blank else f"{ptext(data['uro_sangre'])}"),
        ("Bilirrubina", " " if is_blank else f"{ptext(data['uro_bilirrubina'])}"),
        ("Cetona", " " if is_blank else f"{ptext(data['uro_cetona'])}"),
        ("Proteína (Uroanálisis)", " " if is_blank else f"{ptext(data['uro_proteina'])}"),
        ("pH", " " if is_blank else f"{ptext(data['uro_ph'])}"),
        ("Gravedad específica", " " if is_blank else f"{ptext(data['uro_gravedad'])}"),
    ]
    s15_sed = [
        ("Sedimento: Eritrocitos", " " if is_blank else f"{ptext(data['sed_eritrocitos'])}"),
        ("Sedimento: Leucocitos", " " if is_blank else f"{ptext(data['sed_leucocitos'])}"),
        ("Bacterias", " " if is_blank else f"{ptext(data['sed_bacterias'])}"),
        (
            "Cilindros renales",
            " "
            if is_blank
            else f"{ptext(data['sed_cilindros'])} (Tipo: {ptext(data['tipo_cilindros'])})",
        ),
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
        is_blank=is_blank,
    )

    add_info_box(
        story,
        "Nota Preventiva",
        "Los análisis sanguíneos y el uroanálisis nos permiten establecer una línea base de la función interna de los órganos (como riñones e hígado), ayudándonos a detectar enfermedades sistémicas antes de que presenten síntomas visibles.",
        styles,
    )

    if is_blank:
        s16_items = [
            ("Vacunas aplicadas (Biológico, Fecha, Lote y Sitio anatómico)", " "),
            ("Desparasitante Interno", " "),
        ]
    else:
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
        is_blank=is_blank,
    )

    story.append(Paragraph("Sección 17 Otras recomendaciones y Comentarios", styles["Section"]))
    if is_blank:
        plan_cell = Spacer(1, 55)
    else:
        plan = data["recomendaciones"].strip() or "Sin recomendaciones registradas."
        plan_cell = Paragraph(ptext(plan).replace("\n", "<br/>"), styles["Plan"])

    plan_table = Table(
        [[plan_cell]],
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

    if is_blank:
        medico_nombre = " "
        medico_cedula = " "
    else:
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
        f"<b>MVZ Responsable:</b> {'' if is_blank else ptext(medico_nombre)}<br/>"
        f"<b>Cédula Profesional:</b> {'' if is_blank else ptext(medico_cedula)}"
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


@st.cache_data(max_entries=32, show_spinner=False)
def build_blank_pdf(
    especie: str,
    sexo: str,
    estado_reproductivo: str,
    two_column_grid: bool = True,
) -> bytes:
    """
    Genera un reporte PDF 100% EN BLANCO (celdas vacías sin revelar las opciones de los desplegables),
    adaptado dinámicamente a la Especie, Sexo y Estatus Reproductivo seleccionados para que el equipo
    médico revise únicamente qué secciones y parámetros se están evaluando.
    """
    blank_data = {
        "_is_blank_template": True,
        "mascota": " ",
        "familia": " ",
        "edad": " ",
        "fecha": " ",
        "medico": " ",
        "especie": especie,
        "sexo": sexo,
        "estado_reproductivo": estado_reproductivo,
        "peso_kg": " ",
        "fc": " ",
        "fr": " ",
        "temp": " ",
        "tllc": " ",
        "mucosas": " ",
        "cond_gral": " ",
        "peso": " ",
        "plan_nutricional": " ",
        "alim_seco": " ",
        "alim_humedo": " ",
        "nutra": " ",
        "pelo_piel": " ",
        "planos_por_lesion": [],
        "rec_piel": " ",
        "shampoo_rec": " ",
        "ectoparasitos": " ",
        "c_pulgas": " ",
        "trat_pulgas": " ",
        "notas_s2": " ",
        "hig": " ",
        "est": " ",
        "bazo": " ",
        "rd": " ",
        "ri": " ",
        "int_mes": " ",
        "imp_gral": " ",
        "notas_s3": " ",
        "secr_uro": " ",
        "infl_uro": " ",
        "bult_uro": " ",
        "tum_mam": " ",
        "uro_pene_prepucio": " ",
        "uro_testiculos": " ",
        "uro_prostata_macho": " ",
        "uro_vulva": " ",
        "uro_cadena_mamaria": " ",
        "uro_detalle_mamas": " ",
        "uro_ultimo_celo": " ",
        "pros": " ",
        "tum_rect": " ",
        "hern": " ",
        "sacos": " ",
        "epo": " ",
        "sarro": " ",
        "mord": " ",
        "decol_d": " ",
        "hinc_e": " ",
        "retr_e": " ",
        "inf_e": " ",
        "epul_e": " ",
        "inf_a": " ",
        "hinc_a": " ",
        "inf_l": " ",
        "dec_l": " ",
        "hinc_l": " ",
        "tal_n": " ",
        "con_n": " ",
        "inf_g": " ",
        "ref_g": " ",
        "rec_dental": " ",
        "notas_s6": " ",
        "conj_od": " ",
        "sec_od": " ",
        "def_od": " ",
        "tum_od": " ",
        "pio_od": " ",
        "conj_oi": " ",
        "sec_oi": " ",
        "def_oi": " ",
        "tum_oi": " ",
        "pio_oi": " ",
        "rec_oftalmica": " ",
        "ore_od": " ",
        "tim_od": " ",
        "aca_od": " ",
        "tum_oido_od": " ",
        "inf_oido_od": " ",
        "sec_oido_od": " ",
        "ore_oi": " ",
        "tim_oi": " ",
        "aca_oi": " ",
        "tum_oido_oi": " ",
        "inf_oido_oi": " ",
        "sec_oido_oi": " ",
        "rec_otica": " ",
        "cue": " ",
        "esp": " ",
        "cola": " ",
        "mad": " ",
        "mai": " ",
        "mpd": " ",
        "mpi": " ",
        "tipo_marcha": " ",
        "miembro_claudicacion": [],
        "grado_claudicacion": " ",
        "ment": " ",
        "cran": " ",
        "prop": " ",
        "patel": " ",
        "dolor": " ",
        "reg_dolor": " ",
        "f_car": " ",
        "pul_car": " ",
        "sop_car": " ",
        "rit_car": " ",
        "tllc_car": " ",
        "cd": " ",
        "cad": " ",
        "ci": " ",
        "cai": " ",
        "notas_s12": " ",
        "leu": " ",
        "sida": " ",
        "hemo": " ",
        "tox": " ",
        "coc": " ",
        "nem": " ",
        "gia": " ",
        "gyp": " ",
        "ces": " ",
        "eritrocitos": " ",
        "leucocitos_s": " ",
        "tiroides": " ",
        "enz_ren": " ",
        "enz_hep": " ",
        "enz_pan": " ",
        "electrolitos": " ",
        "prot_ser": " ",
        "uro_urobilinogeno": " ",
        "uro_sangre": " ",
        "uro_bilirrubina": " ",
        "uro_cetona": " ",
        "uro_proteina": " ",
        "uro_ph": " ",
        "uro_gravedad": " ",
        "sed_eritrocitos": " ",
        "sed_leucocitos": " ",
        "sed_bacterias": " ",
        "sed_cilindros": " ",
        "tipo_cilindros": " ",
        "notas_uro": " ",
        "vac_raw_data": [],
        "desp_interno_seleccionado": " ",
        "recomendaciones": " ",
    }

    return build_pdf(blank_data, two_column_grid=two_column_grid, hide_unassessed=False)

