from __future__ import annotations

import datetime
import hashlib
import html
import random
import string
import threading
from io import BytesIO

import qrcode
import streamlit as st
from PIL import Image as PILImage
from PIL import ImageOps

from config import (
    MAX_ACTIVE_TOKENS,
    MAX_PHOTOS_PER_SECTION,
    MAX_PHOTOS_PER_TOKEN,
    PHOTO_SECTIONS,
    SESSION_TTL_SECONDS,
)


@st.cache_resource
def get_mobile_photo_store_and_lock() -> tuple[dict[str, dict], threading.Lock]:
    """
    Almacén en memoria compartida del servidor Streamlit protegido con Lock.
    Estructura: { token: {"timestamp": datetime, "hashes": set(), "data": { section_key: [ {"name": str, "bytes": bytes, "ts": str, "id": str}, ... ] } } }
    """
    return {}, threading.Lock()


mobile_store, mobile_store_lock = get_mobile_photo_store_and_lock()


def _evict_expired_and_overflow_unlocked(now: datetime.datetime | None = None) -> None:
    """Debe llamarse únicamente con mobile_store_lock adquirido."""
    now = now or datetime.datetime.now()
    tokens_to_delete = [
        token
        for token, session_info in list(mobile_store.items())
        if "timestamp" in session_info
        and (now - session_info["timestamp"]).total_seconds() > SESSION_TTL_SECONDS
    ]
    for token in tokens_to_delete:
        mobile_store.pop(token, None)

    if len(mobile_store) > MAX_ACTIVE_TOKENS:
        sorted_tokens = sorted(
            list(mobile_store.items()),
            key=lambda kv: kv[1].get("timestamp", datetime.datetime.min),
        )
        excess = len(mobile_store) - MAX_ACTIVE_TOKENS
        for tok, _ in sorted_tokens[:excess]:
            mobile_store.pop(tok, None)


def cleanup_old_sessions() -> None:
    """SOLUCIÓN A LA FUGA DE MEMORIA: Elimina tokens expirados (>2h) y aplica límite FIFO de tokens."""
    with mobile_store_lock:
        _evict_expired_and_overflow_unlocked()


def ensure_mobile_token(token: str) -> None:
    """Registra o refresca un token en memoria compartida respetando límites de concurrencia y RAM."""
    now = datetime.datetime.now()
    with mobile_store_lock:
        _evict_expired_and_overflow_unlocked(now)
        if token not in mobile_store:
            if len(mobile_store) >= MAX_ACTIVE_TOKENS:
                oldest_tok = min(
                    list(mobile_store.items()),
                    key=lambda kv: kv[1].get("timestamp", datetime.datetime.min),
                )[0]
                mobile_store.pop(oldest_tok, None)
            mobile_store[token] = {
                "timestamp": now,
                "hashes": set(),
                "data": {},
            }
        else:
            mobile_store[token]["timestamp"] = now
            if "hashes" not in mobile_store[token]:
                mobile_store[token]["hashes"] = set()
            if "data" not in mobile_store[token]:
                mobile_store[token]["data"] = {}


def add_mobile_photos(token: str, sec_key: str, files_to_add: list) -> tuple[int, str | None]:
    """Comprime fotos fuera del lock y las inserta de forma segura respetando topes de RAM."""
    prepared = []
    for f_obj in files_to_add:
        raw_bytes = compress_image(f_obj)
        file_hash = hashlib.md5(raw_bytes).hexdigest()
        prepared.append(
            (
                f"{sec_key}:{file_hash}",
                getattr(f_obj, "name", "foto_movil.jpg"),
                raw_bytes,
                datetime.datetime.now().strftime("%H:%M:%S"),
            )
        )

    guardadas_ahora = 0
    limit_warning = None
    with mobile_store_lock:
        if token not in mobile_store:
            mobile_store[token] = {
                "timestamp": datetime.datetime.now(),
                "hashes": set(),
                "data": {},
            }
        session_entry = mobile_store[token]
        session_entry["timestamp"] = datetime.datetime.now()
        hashes = session_entry.setdefault("hashes", set())
        data_map = session_entry.setdefault("data", {})
        sec_list = data_map.setdefault(sec_key, [])

        total_actual = sum(len(v) for v in data_map.values())
        for dedup_key, fname, raw_bytes, ts in prepared:
            if dedup_key in hashes:
                continue
            if len(sec_list) >= MAX_PHOTOS_PER_SECTION:
                limit_warning = f"Límite alcanzado: máximo {MAX_PHOTOS_PER_SECTION} fotos por sección."
                break
            if total_actual >= MAX_PHOTOS_PER_TOKEN:
                limit_warning = f"Límite alcanzado: máximo {MAX_PHOTOS_PER_TOKEN} fotos por paciente."
                break
            hashes.add(dedup_key)
            sec_list.append(
                {
                    "id": dedup_key,
                    "name": fname or f"foto_{len(sec_list) + 1}.jpg",
                    "bytes": raw_bytes,
                    "ts": ts,
                }
            )
            guardadas_ahora += 1
            total_actual += 1

    return guardadas_ahora, limit_warning


def get_token_photo_count(token: str) -> int:
    if not token:
        return 0
    with mobile_store_lock:
        entry = mobile_store.get(token)
        if not entry:
            return 0
        return sum(len(v) for v in entry.get("data", {}).values())


def get_section_mobile_photos(token: str, sec_key: str) -> list[dict]:
    if not token:
        return []
    with mobile_store_lock:
        entry = mobile_store.get(token)
        if not entry:
            return []
        return list(entry.get("data", {}).get(sec_key, []))


def get_all_token_photos_snapshot(token: str) -> dict[str, list[dict]]:
    if not token:
        return {}
    with mobile_store_lock:
        entry = mobile_store.get(token)
        if not entry:
            return {}
        return {k: list(v) for k, v in entry.get("data", {}).items()}


def delete_mobile_photo(token: str, sec_key: str, photo_id: str) -> None:
    if not token:
        return
    with mobile_store_lock:
        entry = mobile_store.get(token)
        if not entry:
            return
        entry.get("hashes", set()).discard(photo_id)
        sec_list = entry.get("data", {}).get(sec_key, [])
        entry["data"][sec_key] = [item for item in sec_list if item.get("id") != photo_id]


def clear_token_photos(token: str, remove_token: bool = False) -> None:
    if not token:
        return
    with mobile_store_lock:
        if remove_token:
            mobile_store.pop(token, None)
        elif token in mobile_store:
            mobile_store[token]["data"] = {}
            mobile_store[token]["hashes"] = set()


cleanup_old_sessions()


@st.cache_data(max_entries=100, ttl=7200, show_spinner=False)
def compress_image_bytes(raw_bytes: bytes, max_size: tuple[int, int] = (800, 800), quality: int = 70) -> bytes:
    """SOLUCIÓN DE RAM Y ORIENTACIÓN EXIF: Transpone EXIF, redimensiona y comprime fotos una sola vez."""
    try:
        with PILImage.open(BytesIO(raw_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            img.thumbnail(max_size, PILImage.Resampling.LANCZOS)
            output = BytesIO()
            img.save(output, format="JPEG", quality=quality)
            return output.getvalue()
    except Exception:
        return raw_bytes


def compress_image(uploaded_file, max_size: tuple[int, int] = (800, 800), quality: int = 70) -> bytes:
    """Wrapper seguro que extrae bytes inmutables y delega a la función cacheada."""
    if hasattr(uploaded_file, "getvalue"):
        raw_bytes = uploaded_file.getvalue()
    else:
        uploaded_file.seek(0)
        raw_bytes = uploaded_file.read()
    return compress_image_bytes(raw_bytes, max_size=max_size, quality=quality)


@st.cache_data(max_entries=50, show_spinner=False)
def generate_qr_png_bytes(url: str) -> bytes:
    """Genera el código QR localmente en memoria (sin llamadas a servicios externos)."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()



def render_mobile_portal(token_movil: str, paciente_movil: str) -> None:

        ensure_mobile_token(token_movil)

        if "mob_active_sec" not in st.session_state:
            st.session_state["mob_active_sec"] = "foto_s6"  # Dental por defecto
        if "mob_upload_counter" not in st.session_state:
            st.session_state["mob_upload_counter"] = 0

        all_photos_snap = get_all_token_photos_snapshot(token_movil)
        total_enviadas = sum(len(v) for v in all_photos_snap.values())

        st.markdown(
            f"""
            <div class="banfield-hero" style="padding:14px 18px; margin-bottom:10px;">
                <div>
                    <h2 style="font-size:1.25rem !important;">📱 Cámara Clínica · {html.escape(paciente_movil)}</h2>
                    <p style="font-size:0.82rem;">Fotos sincronizadas con la PC: <b>{total_enviadas}/{MAX_PHOTOS_PER_TOKEN}</b> · Token: <code>{html.escape(token_movil)}</code></p>
                </div>
                <div class="banfield-badge">EN VIVO</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("##### 1️⃣ Toca el área que vas a fotografiar:")
        top_keys = ["foto_s6", "foto_s2", "foto_s8", "foto_s7", "foto_s1", "foto_lab"]
        other_keys = [k for k in PHOTO_SECTIONS.keys() if k not in top_keys]

        grid_r1 = st.columns(2)
        grid_r2 = st.columns(2)
        grid_r3 = st.columns(2)
        grid_cols = [grid_r1[0], grid_r1[1], grid_r2[0], grid_r2[1], grid_r3[0], grid_r3[1]]

        for idx_b, k_sec in enumerate(top_keys):
            cnt = len(all_photos_snap.get(k_sec, []))
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
                cnt_o = len(all_photos_snap.get(k_other, []))
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
            guardadas_ahora, limit_warning = add_mobile_photos(token_movil, sec_key, nuevos_archivos)
            if limit_warning:
                st.session_state["mob_limit_warn"] = limit_warning
            else:
                st.session_state.pop("mob_limit_warn", None)

            if guardadas_ahora > 0:
                st.session_state["mob_last_msg"] = (
                    f"✅ ¡{guardadas_ahora} foto(s) guardada(s) y sincronizada(s) con la PC en '{sec_label}'!"
                )
                st.session_state["mob_upload_counter"] += 1
                st.rerun()
            elif limit_warning:
                st.warning(limit_warning)

        if st.session_state.get("mob_limit_warn"):
            st.warning(st.session_state["mob_limit_warn"])

        if st.session_state.get("mob_last_msg"):
            st.success(st.session_state["mob_last_msg"])

        fotos_seccion_actual = get_section_mobile_photos(token_movil, sec_key)
        if fotos_seccion_actual:
            st.markdown(f"**Fotos en {sec_label} ({len(fotos_seccion_actual)}/{MAX_PHOTOS_PER_SECTION}):**")
            cols_act = st.columns(min(3, len(fotos_seccion_actual)))
            for idx_f, item_f in enumerate(fotos_seccion_actual):
                with cols_act[idx_f % len(cols_act)]:
                    st.image(item_f["bytes"], caption=f"#{idx_f+1} · {item_f['ts']}", use_container_width=True)
                    if st.button("🗑️ Borrar", key=f"del_mob_{sec_key}_{idx_f}_{item_f.get('id', '')}", use_container_width=True):
                        delete_mobile_photo(token_movil, sec_key, item_f.get("id", ""))
                        st.session_state["mob_last_msg"] = "Foto eliminada."
                        st.rerun()

        all_photos_snap = get_all_token_photos_snapshot(token_movil)
        total_enviadas = sum(len(v) for v in all_photos_snap.values())
        if total_enviadas > 0:
            with st.expander(f"📂 Ver todas las fotos de la consulta ({total_enviadas} en total)"):
                for s_k, items_list in all_photos_snap.items():
                    if items_list:
                        st.markdown(f"**{PHOTO_SECTIONS.get(s_k, s_k)}** ({len(items_list)} foto[s])")
                        cols_m = st.columns(min(3, len(items_list)))
                        for idx_m, item_m in enumerate(items_list):
                            cols_m[idx_m % len(cols_m)].image(
                                item_m["bytes"], caption=f"{item_m['ts']}", use_container_width=True
                            )
                if st.button("🗑️ Limpiar TODAS las fotos enviadas", use_container_width=True):
                    clear_token_photos(token_movil, remove_token=False)
                    st.session_state["mob_last_msg"] = "Se limpiaron todas las fotos."
                    st.rerun()

        st.stop()


@st.fragment(run_every="5s")
def render_mobile_sync_status_fragment(token: str) -> None:
    """Sondeo ligero cada 5s (solo activo cuando existe un sync_token en uso)."""
    fotos_totales = get_token_photo_count(token)
    col_s1, col_s2 = st.columns(2)
    if col_s1.button("🔄 Sincronizar fotos", use_container_width=True, key=f"sync_btn_{token}"):
        st.rerun(scope="app")
    if col_s2.button("🔑 Nuevo Token", use_container_width=True, key=f"new_tok_btn_{token}"):
        clear_token_photos(token, remove_token=True)
        new_tok = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        st.session_state["sync_token"] = new_tok
        ensure_mobile_token(new_tok)
        st.rerun(scope="app")

    if fotos_totales > 0:
        st.success(f"📸 {fotos_totales} foto(s) recibida(s) desde el celular.")
    else:
        st.caption("Esperando fotos desde el celular...")

