from __future__ import annotations

import datetime
import random
import string
import sys
import urllib.parse
from io import BytesIO
from pathlib import Path as FilePath

import streamlit as st

# Asegurar resolución de módulos locales tanto en ejecución local como en Streamlit Cloud
_APP_DIR = str(FilePath(__file__).resolve().parent)
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from catalogs import load_catalogs
from clinical_rules import (
    aplicar_paciente_sano_defaults,
    auto_suggest_quick_recommendations,
    classify_clinical_value,
    evaluate_clinical_status,
    extraer_hallazgos_atencion,
    sync_quick_recommendations_to_textarea,
)
from config import (
    ASSETS_DIR,
    BANFIELD_BLUE,
    BANFIELD_ORANGE,
    BASE_DIR,
    BCS_OPTIONS,
    CSS_STYLES,
    MAX_ACTIVE_TOKENS,
    MAX_PHOTOS_PER_SECTION,
    MAX_PHOTOS_PER_TOKEN,
    PHOTO_SECTIONS,
    QUICK_RECOMMENDATIONS,
    asset_path,
    clean_text,
    ptext,
    safe_filename,
)
from mobile_portal import (
    add_mobile_photos,
    cleanup_old_sessions,
    clear_token_photos,
    compress_image,
    compress_image_bytes,
    ensure_mobile_token,
    generate_qr_png_bytes,
    get_section_mobile_photos,
    get_token_photo_count,
    mobile_store,
    render_mobile_portal,
    render_mobile_sync_status_fragment,
)
from pdf_engine import build_blank_pdf, build_pdf
from via_export import build_via_text

st.set_page_config(
    page_title="Semestral Banfield",
    page_icon="🐾",
    layout="wide",
    initial_sidebar_state="expanded",
)

cleanup_old_sessions()
st.markdown(CSS_STYLES, unsafe_allow_html=True)

# ==============================================================================
# 📱 MODO CÁMARA MÓVIL (QR)
# ==============================================================================
qp = st.query_params
if qp.get("movil") == "1" and qp.get("token"):
    render_mobile_portal(
        token_movil=str(qp.get("token")).strip(),
        paciente_movil=str(qp.get("paciente", "Paciente")).strip(),
    )

# ==============================================================================
# 🖥️ APLICACIÓN PRINCIPAL DE CONSULTORIO (MODO PC / TABLET)
# ==============================================================================
catalogs_cache, medicos, catalog_err_msg, medicos_err_msg = load_catalogs(str(BASE_DIR))

shampoos = list(catalogs_cache["shampoos"])
piel_pelo = list(catalogs_cache["piel_pelo"])
desp_int = list(catalogs_cache["desp_int"])
desp_ext = list(catalogs_cache["desp_ext"])
nutraceuticos_list = list(catalogs_cache["nutraceuticos"])
dental_list = list(catalogs_cache["dental"])
oftalmico_list = list(catalogs_cache["oftalmico"])
otico_list = list(catalogs_cache["otico"])


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
    fotos_moviles = get_section_mobile_photos(token_actual, key) if token_actual else []
    patient_sid = st.session_state.get("patient_session_id", 0)

    badge_movil = f" · 📱 {len(fotos_moviles)} desde móvil" if fotos_moviles else ""
    with st.expander(f"📷 Anexar evidencia fotográfica ({label}){badge_movil}", expanded=bool(fotos_moviles)):
        pc_files = st.file_uploader(
            "Tomar foto o elegir de la galería",
            type=["jpg", "jpeg", "png"],
            key=f"{key}_{patient_sid}",
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



# ================= UTILIDADES DE SESIÓN Y FRAGMENTO QR =================
st.session_state.setdefault("patient_session_id", 0)


def reset_consulta_actual() -> None:
    """Limpia el formulario completo, rota uploaders de PC y libera el token móvil en RAM."""
    old_token = st.session_state.get("sync_token")
    if old_token:
        clear_token_photos(old_token, remove_token=True)

    next_sid = st.session_state.get("patient_session_id", 0) + 1
    preserved = {
        "patient_session_id": next_sid,
        "modo_compacto_toggle": st.session_state.get("modo_compacto_toggle", True),
        "base_app_url_input": st.session_state.get("base_app_url_input", "https://semestral.streamlit.app/"),
    }
    st.session_state.clear()
    for k, v in preserved.items():
        st.session_state[k] = v




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

    # Mostrar errores de catálogos directamente desde el retorno de load_catalogs()
    if catalog_err_msg:
        st.error(f"⚠️ Alerta Catálogos: {catalog_err_msg}")
    if medicos_err_msg:
        st.warning(f"⚠️ Alerta Médicos: {medicos_err_msg}")

    if st.button(
        "⚡ Pre-llenar Paciente Sano (Normal)",
        type="primary",
        use_container_width=True,
        help="Establece todos los parámetros físicos y de laboratorio en Normal/Negativo para que solo modifiques los hallazgos anormales.",
    ):
        aplicar_paciente_sano_defaults()
        st.toast("Parámetros clínicos establecidos en Normal/Negativo.", icon="✅")

    if st.button(
        "🧹 Nuevo Paciente / Limpiar Consulta",
        use_container_width=True,
        help="Reinicia todos los campos del formulario, limpia fotos de PC y libera la sesión móvil QR de la memoria.",
    ):
        reset_consulta_actual()
        st.rerun()

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
        help="Genera el PDF 100% vacío (sin mostrar opciones de los menús desplegables), adaptado dinámicamente a la Especie, Sexo y Estatus reproductivo seleccionados.",
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
        key="base_app_url_input",
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
            ensure_mobile_token(token)

    if st.session_state.get("sync_token") and mascota.strip():
        token = st.session_state["sync_token"]
        url_movil = (
            f"{base_app_url}/?movil=1&paciente={urllib.parse.quote(mascota)}&token={token}"
        )
        qr_png = generate_qr_png_bytes(url_movil)
        st.image(qr_png, caption=f"Escanea para sincronizar cámara con {mascota} (Token: {token})", width=180)
        render_mobile_sync_status_fragment(token)


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

alimentos_secos = list(catalogs_cache["alimentos_secos"].get(especie, ["Otro", "Ninguno"]))
alimentos_humedos = list(catalogs_cache["alimentos_humedos"].get(especie, ["Otro", "Ninguno"]))
vacunas_filtradas = list(catalogs_cache["vacunas"].get(especie, ["Otro", "Ninguno"]))

with tabs[0]:
    ui_header("Constantes Fisiológicas", "Estetoscopio_c.png")
    c1, c2, c3 = st.columns(3)
    data["peso_kg"] = c1.text_input("Peso (kg)", key="peso_kg")
    data["fc"] = c2.text_input("Frecuencia cardiaca (lpm)", key="fc")
    data["fr"] = c3.text_input("Frecuencia respiratoria (rpm)", key="fr")

    c1, c2, c3 = st.columns(3)
    data["temp"] = c1.text_input("Temperatura (°C)", key="temp")
    data["tllc"] = c2.text_input("TLLC (segundos)", key="tllc")
    with c3:
        data["mucosas"] = select_con_otro(
            "Mucosas",
            ["Rosas y húmedas", "Pálidas", "Congestivas", "Ictéricas", "Otro", "Ninguno"],
            "mucosas",
        )
    data["notas_constantes"] = st.text_area("Notas de constantes fisiológicas", height=68, key="notas_constantes")
    data["foto_constantes"] = renderizar_uploader("Constantes", "foto_constantes")

    ui_header("Sección 1 Condición general", "Examen.png")
    c1, c2 = st.columns(2)
    data["cond_gral"] = c1.selectbox(
        "Condición general",
        ["Excelente", "Buena", "Necesita mejorar", "No evaluado", "Ninguno"],
        key="cond_gral",
    )
    data["peso"] = c2.selectbox(
        "Condición corporal / peso (Escala BCS 1 al 9)",
        BCS_OPTIONS,
        index=4,  # Preseleccionado en "5/9 - Peso ideal"
        key="peso",
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
    data["f_car"] = c1.selectbox("Frecuencia cardiaca", opn, key="f_car")
    data["pul_car"] = c2.selectbox("Pulso", opn, key="pul_car")
    data["sop_car"] = c1.selectbox("Soplo/sonido anormal", ["Negativo", "Positivo", "No evaluado", "Ninguno"], key="sop_car")
    data["rit_car"] = c2.selectbox("Ritmo", opn, key="rit_car")
    data["tllc_car"] = c1.selectbox("Tiempo de Llenado Capilar", opn, key="tllc_car")
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
