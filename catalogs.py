from __future__ import annotations

from pathlib import Path as FilePath

import pandas as pd
import streamlit as st


def _filter_cat_list(df: pd.DataFrame, category: str) -> list[str]:
    if df is None or df.empty:
        return ["Otro", "Ninguno"]
    if "Category" in df.columns:
        mask = df["Category"].str.contains(category, case=False, na=False)
        items = df[mask]["Description"].dropna().astype(str).tolist()
        return items + ["Otro", "Ninguno"]
    return ["Otro", "Ninguno"]


def _filter_food_options(df: pd.DataFrame, especie: str, humedo: bool = False) -> list[str]:
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


def _filter_vaccine_options(df: pd.DataFrame, especie: str) -> list[str]:
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


# --- MOTOR DE LECTURA Y PRE-CÁLCULO DE CATÁLOGOS (SIN REGEX EN RERUNS) ---
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

    precomputed = {
        "shampoos": _filter_cat_list(df_cat, "Shampoo"),
        "piel_pelo": _filter_cat_list(df_cat, "Piel y pelo"),
        "desp_int": _filter_cat_list(df_cat, "Desparasitante Interno"),
        "desp_ext": _filter_cat_list(df_cat, "Desparasitantes"),
        "nutraceuticos": _filter_cat_list(df_cat, "Vitaminas"),
        "dental": _filter_cat_list(df_cat, "Cuidado dental"),
        "oftalmico": _filter_cat_list(df_cat, "Oftalmico"),
        "otico": _filter_cat_list(df_cat, "Otica"),
        "alimentos_secos": {
            "Canino": _filter_food_options(df_cat, "Canino", humedo=False),
            "Felino": _filter_food_options(df_cat, "Felino", humedo=False),
        },
        "alimentos_humedos": {
            "Canino": _filter_food_options(df_cat, "Canino", humedo=True),
            "Felino": _filter_food_options(df_cat, "Felino", humedo=True),
        },
        "vacunas": {
            "Canino": _filter_vaccine_options(df_cat, "Canino"),
            "Felino": _filter_vaccine_options(df_cat, "Felino"),
        },
    }

    return precomputed, medicos, cat_err, med_err

