# -*- coding: utf-8 -*-
"""
app.py - Sistema de Gestion de Mantenimiento HVAC (Terminal de Cruceros de Amador)

Modo Gestor  (URL sin parametros): dashboard, filtros, ordenes de trabajo,
                                     administracion (CRUD) y reportes PDF masivos.
Modo Proveedor (URL con ?orden=OT-XXXX): checklist movil para el tecnico externo.
"""

import json
import os
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from data_store import (
    ESTADOS_OPERATIVOS, NOTAS_CATEGORIA, get_store, generar_id_orden,
    parsear_equipos_orden, unir_lista, separar_lista, serializar_checklist,
    parsear_checklist, diagnosticar_secretos,
)
from pdf_utils import (generar_pdf_individual, generar_pdf_consolidado, diagnosticar_logo)

st.set_page_config(
    page_title="Mantenimiento HVAC - Terminal de Cruceros de Amador",
    page_icon="🛠️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# UTILIDADES COMPARTIDAS
# ---------------------------------------------------------------------------
def _parse_fecha(valor):
    if not valor or (isinstance(valor, float) and pd.isna(valor)):
        return None
    try:
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def enriquecer_equipos(df_equipos: pd.DataFrame, modelos: dict) -> pd.DataFrame:
    """Agrega columnas derivadas: umbral_dias, dias_desde_ultimo, estado_alerta."""
    df = df_equipos.copy()

    def umbral(modelo_id):
        return modelos.get(modelo_id, {}).get("umbral_dias", 90)

    def dias_desde(fecha_str):
        f = _parse_fecha(fecha_str)
        return (date.today() - f).days if f else None

    def alerta(row):
        dias = row["dias_desde_ultimo"]
        if pd.isna(dias):
            return "Sin registro"
        return "Vencido" if dias > row["umbral_dias"] else "Al dia"

    df["umbral_dias"] = df["modelo"].apply(umbral)
    df["dias_desde_ultimo"] = df["ultimo_mantenimiento"].apply(dias_desde)
    df["estado_alerta"] = df.apply(alerta, axis=1)
    return df


def construir_link_orden(orden_id: str) -> str:
    base = st.session_state.get("url_base_app", "").strip().rstrip("/")
    if base:
        return f"{base}/?orden={orden_id}"
    return f"?orden={orden_id}"


def estilo_alerta_equipos(row):
    if row.get("estado_alerta") == "Vencido":
        return ["background-color: #ffd6d6"] * len(row)
    if row.get("estado_alerta") == "Sin registro":
        return ["background-color: #fff3cd"] * len(row)
    return [""] * len(row)


def estilo_proximo_mant(row):
    f = _parse_fecha(row.get("proximo_mantenimiento"))
    if f is None:
        return [""] * len(row)
    dias = (f - date.today()).days
    if dias < 0:
        return ["background-color: #ffd6d6"] * len(row)
    if dias <= 7:
        return ["background-color: #ffe8b3"] * len(row)
    return [""] * len(row)


# ===========================================================================
# MODO PROVEEDOR
# ===========================================================================
def render_modo_proveedor(store, orden_id: str):
    st.title("🔧 Checklist de Mantenimiento - Modo Proveedor")

    df_ordenes = store.get_ordenes()
    fila_orden = df_ordenes[df_ordenes["orden_id"] == orden_id]
    if fila_orden.empty:
        st.error(f"⚠️ No se encontro ninguna Orden de Trabajo con el codigo **{orden_id}**. "
                 "Verifica el enlace con tu gestor.")
        return

    orden = fila_orden.iloc[0]
    equipos_tags = parsear_equipos_orden(orden.to_dict())
    df_equipos = store.get_equipos()
    modelos = store.get_modelos()
    df_reportes = store.get_reportes()

    st.info(f"**Orden:** {orden_id}  |  **Estado:** {orden['estado']}  |  "
            f"**Equipos asignados:** {len(equipos_tags)}")

    if orden["estado"] == "Completada":
        st.success("✅ Esta orden ya fue marcada como Completada. Aun puedes revisar o "
                    "reenviar el reporte de un equipo si es necesario.")

    tabs = st.tabs([f"🔧 {tag}" for tag in equipos_tags])

    for tag, tab in zip(equipos_tags, tabs):
        with tab:
            fila_equipo = df_equipos[df_equipos["tag"] == tag]
            if fila_equipo.empty:
                st.error(f"El equipo {tag} ya no existe en la base de datos.")
                continue
            equipo = fila_equipo.iloc[0]
            modelo_info = modelos.get(equipo["modelo"], modelos.get("generico"))

            ya_enviado = df_reportes[(df_reportes["orden_id"] == orden_id) &
                                       (df_reportes["tag_equipo"] == tag)]
            if not ya_enviado.empty:
                st.success(f"Ya se envio un reporte para **{tag}** el "
                           f"{ya_enviado.iloc[-1]['fecha_servicio']}. Puedes volver a "
                           "enviarlo si necesitas corregir algo.")

            st.markdown(f"**Categoria:** {equipo['categoria']}  \n"
                        f"**Especificaciones:** {equipo['especificaciones']}  \n"
                        f"**Modelo de referencia:** {modelo_info['nombre']}")
            if equipo["zona"] or equipo["nivel"]:
                st.caption(f"📍 Zona: {equipo['zona'] or '-'}  |  Nivel: {equipo['nivel'] or '-'}")

            st.markdown("#### ✅ Checklist de Mantenimiento Preventivo")
            tareas_marcadas = []
            for i, tarea in enumerate(modelo_info["preventivo"]):
                key = f"prov_chk_{orden_id}_{tag}_{i}"
                col_chk, col_txt = st.columns([0.08, 0.92])
                with col_chk:
                    marcado = st.checkbox(f"Completada: {tarea['tarea']}", key=key,
                                            label_visibility="collapsed")
                with col_txt:
                    st.markdown(f"**[{tarea['frecuencia']}] {tarea['tarea']}**")
                    st.caption(tarea["procedimiento"])
                tareas_marcadas.append((tarea, marcado))

            if equipo["tiene_vfd"] and "abb_vfd" in modelos:
                st.markdown(f"#### 🔌 Componente Adicional: {modelos['abb_vfd']['nombre']}")
                for i, tarea in enumerate(modelos["abb_vfd"]["preventivo"]):
                    key = f"prov_chkvfd_{orden_id}_{tag}_{i}"
                    col_chk, col_txt = st.columns([0.08, 0.92])
                    with col_chk:
                        marcado = st.checkbox(f"Completada: {tarea['tarea']}", key=key,
                                                label_visibility="collapsed")
                    with col_txt:
                        st.markdown(f"**[{tarea['frecuencia']}] {tarea['tarea']}**")
                        st.caption(tarea["procedimiento"])
                    tareas_marcadas.append((tarea, marcado))

            st.markdown("#### 🕐 Datos del Servicio")
            col1, col2, col3 = st.columns(3)
            with col1:
                hora_inicio = st.time_input("Hora de inicio", key=f"hi_{orden_id}_{tag}")
            with col2:
                hora_fin = st.time_input("Hora de finalizacion", key=f"hf_{orden_id}_{tag}")
            with col3:
                estado_final = st.selectbox("Estado final del equipo", ESTADOS_OPERATIVOS,
                                              key=f"ef_{orden_id}_{tag}")

            sintomas_opciones = [f["sintoma"] for f in modelo_info.get("correctivo", [])]
            sintomas_detectados = st.multiselect(
                "¿Se detecto alguna falla de la guia? (opcional)", sintomas_opciones,
                key=f"sint_{orden_id}_{tag}")

            observaciones = st.text_area("Observaciones", key=f"obs_{orden_id}_{tag}",
                                           placeholder="Notas, repuestos usados, hallazgos...")

            proximo_mant = st.date_input(
                "📅 Siguiente mantenimiento programado (obligatorio)", value=None,
                key=f"prox_{orden_id}_{tag}", min_value=date.today())

            with st.expander("📷 Evidencia fotografica (opcional)"):
                foto_camara = st.camera_input("Tomar foto", key=f"cam_{orden_id}_{tag}")
                fotos_galeria = st.file_uploader(
                    "O subir desde galeria", type=["jpg", "jpeg", "png"],
                    accept_multiple_files=True, key=f"gal_{orden_id}_{tag}")

            if st.button(f"💾 Guardar reporte de {tag}", key=f"submit_{orden_id}_{tag}",
                          type="primary"):
                if proximo_mant is None:
                    st.error("⚠️ Debes seleccionar la fecha del siguiente mantenimiento "
                             "programado antes de guardar.")
                else:
                    completadas = sum(1 for _, m in tareas_marcadas if m)
                    evidencia_paths = []
                    imagenes = []
                    if foto_camara is not None:
                        imagenes.append(("captura.jpg", foto_camara.getvalue()))
                    for f in (fotos_galeria or []):
                        imagenes.append((f.name, f.getvalue()))
                    for nombre, contenido in imagenes:
                        ts = datetime.now().strftime("%Y%m%d%H%M%S")
                        ruta = store.guardar_evidencia(orden_id, tag, f"{ts}_{nombre}", contenido)
                        evidencia_paths.append(ruta)

                    reporte = {
                        "reporte_id": f"{orden_id}_{tag}_{datetime.now():%H%M%S}".replace(" ", ""),
                        "orden_id": orden_id, "tag_equipo": tag, "categoria": equipo["categoria"],
                        "modelo_id": equipo["modelo"], "modelo_referencia": modelo_info["nombre"],
                        "zona": equipo["zona"], "nivel": equipo["nivel"],
                        "tecnico": orden.get("tecnico_asignado", "") or "Tecnico Proveedor",
                        "fecha_servicio": str(date.today()),
                        "hora_inicio": hora_inicio.strftime("%H:%M"),
                        "hora_fin": hora_fin.strftime("%H:%M"),
                        "estado_final": estado_final,
                        "sintomas_detectados": unir_lista(sintomas_detectados),
                        "tareas_completadas": completadas,
                        "tareas_totales": len(tareas_marcadas),
                        "checklist_json": serializar_checklist(tareas_marcadas),
                        "observaciones": observaciones,
                        "proximo_mantenimiento": str(proximo_mant),
                        "evidencia_urls": unir_lista(evidencia_paths),
                        "fecha_registro": str(datetime.now()),
                    }
                    store.guardar_reporte(reporte)
                    store.upsert_equipo({
                        **equipo.to_dict(),
                        "estado_operativo": estado_final,
                        "ultimo_mantenimiento": str(date.today()),
                        "proximo_mantenimiento": str(proximo_mant),
                    })

                    # Si ya todos los equipos de la orden tienen reporte, marcar Completada
                    df_reportes_actualizado = store.get_reportes()
                    tags_con_reporte = set(
                        df_reportes_actualizado[df_reportes_actualizado["orden_id"] == orden_id]["tag_equipo"])
                    if set(equipos_tags).issubset(tags_con_reporte):
                        store.actualizar_orden(orden_id, {"estado": "Completada"})

                    st.success(f"✅ Reporte de {tag} guardado correctamente.")
                    st.rerun()


# ===========================================================================
# MODO GESTOR
# ===========================================================================
def guardar_cambios_equipos(store, df_mostrar: pd.DataFrame, df_editado: pd.DataFrame,
                              df_equipos_enr: pd.DataFrame):
    """
    Compara df_mostrar (estado original mostrado en el editor) contra df_editado
    (lo que devolvio st.data_editor) fila por fila, por posicion, y guarda solo
    los equipos que realmente cambiaron en 'tag', 'categoria', 'zona' o 'nivel'.

    Maneja el caso especial de renombrar el 'tag' (llave primaria): elimina el
    registro viejo y crea uno nuevo, preservando el resto de sus campos
    (modelo, tiene_vfd, estado_operativo, ultimo_mantenimiento, proximo_mantenimiento).

    Devuelve (cantidad_actualizados, lista_de_errores).
    """
    tags_originales = df_mostrar["tag"].tolist()
    df_editado_plano = df_editado.reset_index(drop=True)

    tags_nuevos = df_editado_plano["tag"].astype(str).str.strip().tolist()
    duplicados_en_lote = {t for t in tags_nuevos if t and tags_nuevos.count(t) > 1}
    tags_existentes_fuera_del_filtro = set(df_equipos_enr["tag"]) - set(tags_originales)

    actualizados = 0
    errores = []

    for i, tag_original in enumerate(tags_originales):
        fila_nueva = df_editado_plano.iloc[i]
        tag_nuevo = str(fila_nueva["tag"]).strip()
        cambio = (
            tag_nuevo != tag_original
            or str(fila_nueva["categoria"]) != str(df_mostrar.iloc[i]["categoria"])
            or str(fila_nueva["zona"]) != str(df_mostrar.iloc[i]["zona"])
            or str(fila_nueva["nivel"]) != str(df_mostrar.iloc[i]["nivel"])
        )
        if not cambio:
            continue

        if not tag_nuevo:
            errores.append(f"'{tag_original}': el Tag no puede quedar vacio. Cambio ignorado.")
            continue
        if tag_nuevo in duplicados_en_lote:
            errores.append(f"'{tag_original}': el nuevo Tag '{tag_nuevo}' esta duplicado "
                            "en la tabla. Cambio ignorado.")
            continue
        if tag_nuevo != tag_original and tag_nuevo in tags_existentes_fuera_del_filtro:
            errores.append(f"'{tag_original}': ya existe otro equipo con el Tag "
                            f"'{tag_nuevo}'. Cambio ignorado.")
            continue

        registro_original = df_equipos_enr[df_equipos_enr["tag"] == tag_original]
        if registro_original.empty:
            errores.append(f"'{tag_original}': ya no existe en la base de datos. Cambio ignorado.")
            continue
        registro_completo = registro_original.iloc[0].to_dict()

        registro_actualizado = {
            **registro_completo,
            "tag": tag_nuevo,
            "categoria": fila_nueva["categoria"],
            "zona": fila_nueva["zona"],
            "nivel": fila_nueva["nivel"],
        }
        # Solo dejamos las columnas reales del esquema de equipos (se cuelan
        # columnas calculadas como umbral_dias/estado_alerta al copiar el dict).
        registro_actualizado = {k: registro_actualizado.get(k, "") for k in
                                 ["tag", "categoria", "especificaciones", "modelo",
                                  "tiene_vfd", "zona", "nivel", "estado_operativo",
                                  "ultimo_mantenimiento", "proximo_mantenimiento"]}

        if tag_nuevo != tag_original:
            store.eliminar_equipo(tag_original)
        store.upsert_equipo(registro_actualizado)
        actualizados += 1

    return actualizados, errores


def render_dashboard(df_equipos_enr: pd.DataFrame, df_reportes: pd.DataFrame):
    st.subheader("📊 Tablero de Control")

    hoy = date.today()
    reportes_mes = df_reportes[df_reportes["fecha_servicio"].apply(
        lambda f: (_parse_fecha(f).month == hoy.month and _parse_fecha(f).year == hoy.year)
        if _parse_fecha(f) else False)]
    programados = df_equipos_enr[df_equipos_enr["proximo_mantenimiento"].apply(
        lambda f: _parse_fecha(f) is not None and _parse_fecha(f) >= hoy)]
    vencidos = df_equipos_enr[df_equipos_enr["estado_alerta"] == "Vencido"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mantenimientos este mes", len(reportes_mes))
    c2.metric("Mantenimientos programados", len(programados))
    c3.metric("Equipos vencidos", len(vencidos), delta=None,
              delta_color="inverse")
    c4.metric("Equipos totales", len(df_equipos_enr))

    col_izq, col_der = st.columns([1.3, 1])

    with col_izq:
        st.markdown("##### ⚠️ Equipos vencidos (requieren atencion)")
        if vencidos.empty:
            st.caption("No hay equipos vencidos. ✅")
        else:
            cols_mostrar = ["tag", "categoria", "zona", "nivel", "dias_desde_ultimo",
                             "umbral_dias", "estado_operativo"]
            st.dataframe(
                vencidos[cols_mostrar].sort_values("dias_desde_ultimo", ascending=False)
                    .style.apply(estilo_alerta_equipos, axis=1),
                width="stretch", hide_index=True)

    with col_der:
        st.markdown("##### 🔥 Fallas mas comunes detectadas")
        todas_fallas = []
        for texto in df_reportes["sintomas_detectados"]:
            todas_fallas.extend(separar_lista(texto))
        if not todas_fallas:
            st.caption("Aun no se han registrado fallas en los reportes.")
        else:
            conteo = pd.Series(todas_fallas).value_counts().head(10).sort_values()
            fig = px.bar(x=conteo.values, y=conteo.index, orientation="h",
                          labels={"x": "Ocurrencias", "y": ""})
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig)

    st.markdown("##### 🗓️ Proximos mantenimientos programados (vista tipo calendario)")
    prox = df_equipos_enr[df_equipos_enr["proximo_mantenimiento"].apply(
        lambda f: _parse_fecha(f) is not None)].copy()
    if prox.empty:
        st.caption("Ningun equipo tiene una fecha de proximo mantenimiento registrada todavia.")
    else:
        prox = prox.sort_values("proximo_mantenimiento")
        st.dataframe(
            prox[["proximo_mantenimiento", "tag", "categoria", "zona", "nivel", "estado_operativo"]]
                .style.apply(estilo_proximo_mant, axis=1),
            width="stretch", hide_index=True)
        prox["mes"] = prox["proximo_mantenimiento"].apply(lambda f: _parse_fecha(f).strftime("%Y-%m"))
        resumen_mes = prox.groupby("mes").size().reset_index(name="cantidad")
        fig2 = px.bar(resumen_mes, x="mes", y="cantidad",
                       labels={"mes": "Mes", "cantidad": "Mantenimientos programados"})
        fig2.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig2)


def render_ordenes(store, df_equipos_filtrado: pd.DataFrame):
    st.subheader("🗂️ Gestion de Ordenes de Trabajo")

    col_izq, col_der = st.columns([1.2, 1])
    with col_izq:
        st.markdown("##### Crear nueva Orden de Trabajo")
        st.caption("Selecciona equipos de la lista filtrada en la barra lateral.")
        equipos_disponibles = df_equipos_filtrado["tag"].tolist()
        seleccionados = st.multiselect("Equipos a incluir en la orden", equipos_disponibles)
        tecnico_asignado = st.text_input("Proveedor / tecnico asignado (opcional)",
                                           placeholder="Ej: Refrigeracion ACME S.A.")
        if st.button("➕ Crear Orden de Trabajo", type="primary", disabled=not seleccionados):
            nuevo_id = generar_id_orden()
            store.crear_orden(nuevo_id, seleccionados, tecnico_asignado=tecnico_asignado)
            st.success(f"Orden **{nuevo_id}** creada con {len(seleccionados)} equipo(s).")
            st.session_state["ultima_orden_creada"] = nuevo_id
            st.rerun()

    with col_der:
        st.markdown("##### 🔗 Configuracion de enlaces")
        if "url_base_app" not in st.session_state:
            try:
                st.session_state["url_base_app"] = st.secrets.get("app_url", "")
            except Exception:
                st.session_state["url_base_app"] = ""
        st.text_input(
            "URL base de la app desplegada (una vez que la publiques)",
            key="url_base_app",
            placeholder="https://tu-app.streamlit.app",
            help="Pegala aqui una vez para poder generar enlaces completos para el proveedor. "
                 "Tambien puedes definirla de forma permanente en secrets.toml como app_url.")

    if st.session_state.get("ultima_orden_creada"):
        oid = st.session_state["ultima_orden_creada"]
        st.info(f"Enlace para compartir con el proveedor de la orden **{oid}**:")
        st.code(construir_link_orden(oid), language=None)

    st.markdown("---")
    st.markdown("##### Ordenes existentes")
    df_ordenes = store.get_ordenes()
    df_reportes = store.get_reportes()
    if df_ordenes.empty:
        st.caption("Aun no se ha creado ninguna orden de trabajo.")
        return

    for _, orden in df_ordenes.sort_values("fecha_creacion", ascending=False).iterrows():
        equipos_orden = parsear_equipos_orden(orden.to_dict())
        reportes_orden = df_reportes[df_reportes["orden_id"] == orden["orden_id"]]
        completados = reportes_orden["tag_equipo"].nunique()
        icono = {"Abierta": "🟡", "Completada": "🟢", "Cancelada": "⚪"}.get(orden["estado"], "🟡")
        with st.expander(f"{icono} {orden['orden_id']}  —  {orden['estado']}  "
                          f"({completados}/{len(equipos_orden)} equipos completados)"):
            st.markdown(f"**Fecha de creacion:** {orden['fecha_creacion']}  \n"
                        f"**Proveedor/tecnico asignado:** {orden.get('tecnico_asignado') or '-'}  \n"
                        f"**Equipos:** {', '.join(equipos_orden)}")
            st.code(construir_link_orden(orden["orden_id"]), language=None)
            colb1, colb2 = st.columns(2)
            with colb1:
                if orden["estado"] != "Completada" and st.button(
                        "Marcar como Completada", key=f"complete_{orden['orden_id']}"):
                    store.actualizar_orden(orden["orden_id"], {"estado": "Completada"})
                    st.rerun()
            with colb2:
                if orden["estado"] != "Cancelada" and st.button(
                        "Cancelar orden", key=f"cancel_{orden['orden_id']}"):
                    store.actualizar_orden(orden["orden_id"], {"estado": "Cancelada"})
                    st.rerun()

            if not reportes_orden.empty:
                st.markdown("**Reportes individuales recibidos:**")
                modelos_cache = store.get_modelos()
                for _, rep in reportes_orden.iterrows():
                    rep_dict = rep.to_dict()
                    rep_dict["_tareas_marcadas"] = parsear_checklist(rep_dict.get("checklist_json", ""))
                    rep_dict["_evidencias_lista"] = separar_lista(rep_dict.get("evidencia_urls", ""))
                    modelo_info_rep = modelos_cache.get(rep_dict.get("modelo_id", ""), {})
                    col_info, col_btn = st.columns([3, 1])
                    with col_info:
                        st.caption(f"🔧 **{rep_dict['tag_equipo']}** — {rep_dict['estado_final']} — "
                                   f"{rep_dict['tareas_completadas']}/{rep_dict['tareas_totales']} "
                                   f"tareas — {rep_dict['fecha_servicio']}")
                    with col_btn:
                        pdf_individual = generar_pdf_individual(
                            rep_dict, modelo_info_rep, rep_dict["_tareas_marcadas"],
                            evidencias=rep_dict["_evidencias_lista"])
                        st.download_button(
                            "⬇️ PDF", data=pdf_individual,
                            file_name=f"Reporte_{rep_dict['tag_equipo'].replace(' ', '').replace('/', '-')}_{rep_dict['fecha_servicio']}.pdf",
                            mime="application/pdf", key=f"pdf_ind_{orden['orden_id']}_{rep_dict['tag_equipo']}_{rep_dict.get('reporte_id','')}")

    # ---- Reportes PDF masivos ----
    st.markdown("---")
    st.markdown("##### 📦 Reporte PDF Consolidado (varias ordenes completadas)")
    ordenes_completadas = df_ordenes[df_ordenes["estado"] == "Completada"]["orden_id"].tolist()
    if not ordenes_completadas:
        st.caption("Aun no hay ordenes completadas para consolidar.")
        return

    seleccion_pdf = st.multiselect("Selecciona las ordenes a incluir en el PDF consolidado",
                                     ordenes_completadas)
    nombre_gestor = st.text_input("Nombre del gestor que firma el reporte", key="nombre_gestor_pdf")
    if st.button("📄 Generar PDF Consolidado", disabled=not seleccion_pdf):
        modelos = store.get_modelos()
        reportes_por_orden = []
        for oid in seleccion_pdf:
            reportes_orden = df_reportes[df_reportes["orden_id"] == oid]
            lista_reportes = []
            for _, r in reportes_orden.iterrows():
                r = r.to_dict()
                r["_tareas_marcadas"] = parsear_checklist(r.get("checklist_json", ""))
                r["_evidencias_lista"] = separar_lista(r.get("evidencia_urls", ""))
                r["_modelo_info"] = modelos.get(r.get("modelo_id", ""), {})
                lista_reportes.append(r)
            reportes_por_orden.append({"orden_id": oid, "reportes": lista_reportes})

        pdf_bytes = generar_pdf_consolidado(reportes_por_orden, nombre_gestor=nombre_gestor)
        st.session_state["pdf_consolidado"] = pdf_bytes
        st.session_state["pdf_consolidado_nombre"] = f"Reporte_Consolidado_{date.today()}.pdf"

    if st.session_state.get("pdf_consolidado"):
        st.download_button("⬇️ Descargar PDF Consolidado", data=st.session_state["pdf_consolidado"],
                             file_name=st.session_state["pdf_consolidado_nombre"],
                             mime="application/pdf")


def render_administracion(store):
    st.subheader("🛠️ Administracion (CRUD de Modelos y Equipos)")

    sub1, sub2, sub3, sub4 = st.tabs(
        ["✏️ Editar tareas de un modelo", "➕ Crear modelo nuevo",
         "🔁 Reasignar modelo a un equipo", "🆕 Agregar equipo nuevo"])

    modelos = store.get_modelos()

    # --- Editar modelo existente ---
    with sub1:
        modelo_id = st.selectbox("Modelo a editar", list(modelos.keys()),
                                   format_func=lambda k: f"{k} — {modelos[k]['nombre']}",
                                   key="crud_editar_modelo_id")
        data = modelos[modelo_id]
        nombre = st.text_input("Nombre del modelo", value=data["nombre"], key="crud_nombre")
        componentes = st.text_area("Componentes principales", value=data["componentes"],
                                     key="crud_componentes")
        parametros = st.text_area("Parametros clave", value=data["parametros"], key="crud_parametros")

        st.markdown("**Tareas de Mantenimiento Preventivo**")
        df_prev = pd.DataFrame(data["preventivo"]) if data["preventivo"] else \
            pd.DataFrame(columns=["frecuencia", "tarea", "procedimiento", "herramientas"])
        df_prev_editado = st.data_editor(df_prev, num_rows="dynamic", key="crud_editor_preventivo",
                                           width="stretch")

        st.markdown("**Guia de Fallas (Correctivo)**")
        df_corr = pd.DataFrame(data["correctivo"]) if data["correctivo"] else \
            pd.DataFrame(columns=["sintoma", "causa", "accion"])
        df_corr_editado = st.data_editor(df_corr, num_rows="dynamic", key="crud_editor_correctivo",
                                           width="stretch")

        if st.button("💾 Guardar cambios en este modelo", type="primary", key="crud_guardar_modelo"):
            nuevo_data = {
                "nombre": nombre, "componentes": componentes, "parametros": parametros,
                "preventivo": df_prev_editado.fillna("").to_dict("records"),
                "correctivo": df_corr_editado.fillna("").to_dict("records"),
            }
            store.upsert_modelo(modelo_id, nuevo_data)
            st.success(f"Modelo '{modelo_id}' actualizado correctamente.")
            st.rerun()

    # --- Crear modelo nuevo ---
    with sub2:
        nuevo_id = st.text_input("Identificador unico del modelo (sin espacios)",
                                   placeholder="ej: liebert_cr1", key="crud_nuevo_id")
        nuevo_nombre = st.text_input("Nombre visible del modelo",
                                       placeholder="ej: Liebert CRV (Unidad de Precision)",
                                       key="crud_nuevo_nombre")
        nuevo_componentes = st.text_area("Componentes principales", key="crud_nuevo_componentes")
        nuevo_parametros = st.text_area("Parametros clave", key="crud_nuevo_parametros")
        st.caption("Agrega al menos una tarea preventiva antes de guardar (usa el boton '+' de la tabla).")
        df_prev_nuevo = st.data_editor(
            pd.DataFrame(columns=["frecuencia", "tarea", "procedimiento", "herramientas"]),
            num_rows="dynamic", key="crud_editor_preventivo_nuevo", width="stretch")
        df_corr_nuevo = st.data_editor(
            pd.DataFrame(columns=["sintoma", "causa", "accion"]),
            num_rows="dynamic", key="crud_editor_correctivo_nuevo", width="stretch")

        if st.button("➕ Crear modelo", type="primary", key="crud_crear_modelo"):
            if not nuevo_id or not nuevo_nombre:
                st.error("El identificador y el nombre son obligatorios.")
            elif nuevo_id in modelos:
                st.error(f"Ya existe un modelo con el identificador '{nuevo_id}'.")
            else:
                nuevo_data = {
                    "nombre": nuevo_nombre, "componentes": nuevo_componentes,
                    "parametros": nuevo_parametros,
                    "preventivo": df_prev_nuevo.fillna("").to_dict("records"),
                    "correctivo": df_corr_nuevo.fillna("").to_dict("records"),
                }
                store.upsert_modelo(nuevo_id, nuevo_data)
                st.success(f"Modelo '{nuevo_id}' creado correctamente.")
                st.rerun()

    # --- Reasignar modelo a un equipo ---
    with sub3:
        df_equipos = store.get_equipos()
        tag_sel = st.selectbox("Equipo", df_equipos["tag"].tolist(), key="crud_reasignar_tag")
        fila = df_equipos[df_equipos["tag"] == tag_sel].iloc[0]
        st.caption(f"Modelo actual: **{fila['modelo']}** — "
                   f"{modelos.get(fila['modelo'], {}).get('nombre', '(desconocido)')}")
        nuevo_modelo = st.selectbox(
            "Nuevo modelo a asignar", list(modelos.keys()),
            format_func=lambda k: f"{k} — {modelos[k]['nombre']}",
            index=list(modelos.keys()).index(fila["modelo"]) if fila["modelo"] in modelos else 0,
            key="crud_reasignar_modelo")
        tiene_vfd = st.checkbox("Este equipo tiene Variador de Frecuencia (VFD) como accesorio",
                                  value=bool(fila["tiene_vfd"]), key="crud_reasignar_vfd")
        if st.button("💾 Guardar reasignacion", type="primary", key="crud_guardar_reasignacion"):
            store.upsert_equipo({**fila.to_dict(), "modelo": nuevo_modelo, "tiene_vfd": tiene_vfd})
            st.success(f"'{tag_sel}' reasignado al modelo '{nuevo_modelo}'.")
            st.rerun()

    # --- Agregar equipo nuevo ---
    with sub4:
        nuevo_tag = st.text_input("Tag / codigo del equipo nuevo", placeholder="ej: CH-04",
                                    key="crud_nuevo_tag")
        categorias_existentes = sorted(store.get_equipos()["categoria"].unique().tolist())
        categoria_sel = st.selectbox("Categoria", categorias_existentes + ["+ Nueva categoria"],
                                       key="crud_nueva_categoria_sel")
        if categoria_sel == "+ Nueva categoria":
            categoria_sel = st.text_input("Nombre de la nueva categoria", key="crud_categoria_libre")
        especs = st.text_area("Especificaciones tecnicas", key="crud_nuevo_especs")
        modelo_nuevo_equipo = st.selectbox(
            "Modelo de mantenimiento", list(modelos.keys()),
            format_func=lambda k: f"{k} — {modelos[k]['nombre']}", key="crud_nuevo_equipo_modelo")
        tiene_vfd_nuevo = st.checkbox("Tiene Variador de Frecuencia (VFD)", key="crud_nuevo_equipo_vfd")

        if st.button("🆕 Agregar equipo", type="primary", key="crud_agregar_equipo"):
            df_equipos_actual = store.get_equipos()
            if not nuevo_tag:
                st.error("El tag del equipo es obligatorio.")
            elif nuevo_tag in df_equipos_actual["tag"].values:
                st.error(f"Ya existe un equipo con el tag '{nuevo_tag}'.")
            else:
                store.agregar_equipo({
                    "tag": nuevo_tag, "categoria": categoria_sel, "especificaciones": especs,
                    "modelo": modelo_nuevo_equipo, "tiene_vfd": tiene_vfd_nuevo,
                    "zona": "", "nivel": "", "estado_operativo": "Operativo",
                    "ultimo_mantenimiento": "", "proximo_mantenimiento": "",
                })
                st.success(f"Equipo '{nuevo_tag}' agregado correctamente.")
                st.rerun()


def render_modo_gestor(store):
    st.title("🛠️ Panel de Gestion de Mantenimiento HVAC")
    st.caption("Terminal de Cruceros de Amador")

    modelos = store.get_modelos()
    df_equipos = store.get_equipos()
    df_equipos_enr = enriquecer_equipos(df_equipos, modelos)
    df_reportes = store.get_reportes()

    with st.sidebar:
        st.markdown(f"**Fuente de datos:** `{store.nombre_backend}`")
        if store.nombre_backend == "Local (CSV)":
            diag_secretos = diagnosticar_secretos()
            if diag_secretos["modo"] == "sin_secrets":
                st.caption("☁️ Nube: no configurada todavia (no se encontro ningun "
                           "archivo secrets.toml). Esto es normal si aun no la activaste.")
            else:
                with st.expander("☁️ Nube: se esperaba usarla, pero se sigue usando Local"):
                    st.caption(diag_secretos["detalle"])
        st.markdown("---")

        diag_logo = diagnosticar_logo()
        if diag_logo["valido"] and diag_logo["ruta_encontrada"] == diag_logo["ruta_buscada"]:
            st.caption(f"🖼️ Logo corporativo: ✅ detectado en `{diag_logo['ruta_encontrada']}`")
        elif diag_logo["valido"]:
            with st.expander("🖼️ Logo corporativo: ✅ detectado (con nombre distinto al esperado)"):
                st.caption(f"Se esta usando: `{diag_logo['ruta_encontrada']}`")
                st.caption(diag_logo["error"])
        else:
            with st.expander("🖼️ Logo corporativo: ⚠️ no detectado (los PDF se veran sin logo)"):
                st.caption(diag_logo["error"])
                st.caption(f"Carpeta revisada: `{os.path.dirname(diag_logo['ruta_buscada'])}`")
                if diag_logo["archivos_en_carpeta"]:
                    st.caption("Archivos que SI estan en esa carpeta:")
                    st.code("\n".join(diag_logo["archivos_en_carpeta"]), language=None)
        st.markdown("---")
        st.subheader("🔎 Buscador y Filtros")
        texto_busqueda = st.text_input("Buscar por Tag", placeholder="ej: CH-01, UMA-05...")

        niveles = sorted([n for n in df_equipos_enr["nivel"].unique() if n])
        nivel_sel = st.multiselect("Nivel / Piso", niveles)

        categorias = sorted(df_equipos_enr["categoria"].unique())
        categoria_sel = st.multiselect("Tipo de Equipo", categorias)

        estado_sel = st.multiselect("Estado Operativo", ESTADOS_OPERATIVOS)

    df_filtrado = df_equipos_enr.copy()
    if texto_busqueda:
        df_filtrado = df_filtrado[df_filtrado["tag"].str.contains(texto_busqueda, case=False)]
    if nivel_sel:
        df_filtrado = df_filtrado[df_filtrado["nivel"].isin(nivel_sel)]
    if categoria_sel:
        df_filtrado = df_filtrado[df_filtrado["categoria"].isin(categoria_sel)]
    if estado_sel:
        df_filtrado = df_filtrado[df_filtrado["estado_operativo"].isin(estado_sel)]

    tab_dash, tab_equipos, tab_ordenes, tab_admin = st.tabs(
        ["📊 Dashboard", "📋 Equipos", "🗂️ Ordenes de Trabajo", "🛠️ Administracion"])

    with tab_dash:
        render_dashboard(df_equipos_enr, df_reportes)

    with tab_equipos:
        st.subheader(f"📋 Listado de Equipos ({len(df_filtrado)} de {len(df_equipos_enr)})")
        st.caption("Puedes editar directamente **Tag**, **Categoria**, **Zona** y **Nivel**. "
                   "El resto de columnas es de solo lectura (se administra desde las otras pestanas).")

        cols_mostrar = ["tag", "categoria", "zona", "nivel", "estado_operativo",
                         "modelo", "tiene_vfd", "ultimo_mantenimiento",
                         "proximo_mantenimiento", "estado_alerta"]
        columnas_editables = ["tag", "categoria", "zona", "nivel"]
        columnas_solo_lectura = [c for c in cols_mostrar if c not in columnas_editables]

        # Se guarda el orden y los tags originales ANTES de mostrar el editor, para
        # poder detectar cambios por posicion incluso si el usuario edita el propio
        # tag (la llave primaria de la tabla).
        df_mostrar = df_filtrado[cols_mostrar].reset_index(drop=True)
        tags_originales = df_mostrar["tag"].tolist()

        df_editado = st.data_editor(
            df_mostrar.style.apply(estilo_alerta_equipos, axis=1),
            column_config={
                "tag": st.column_config.TextColumn("Tag", required=True),
                "categoria": st.column_config.TextColumn("Categoria"),
                "zona": st.column_config.TextColumn("Zona"),
                "nivel": st.column_config.TextColumn("Nivel"),
            },
            disabled=columnas_solo_lectura,
            num_rows="fixed",
            hide_index=True,
            width="stretch",
            key="editor_equipos",
        )

        if st.button("💾 Guardar cambios de equipos", type="primary"):
            actualizados, errores = guardar_cambios_equipos(store, df_mostrar, df_editado, df_equipos_enr)

            if actualizados:
                st.success(f"✅ {actualizados} equipo(s) actualizado(s) correctamente.")
            for err in errores:
                st.error(f"⚠️ {err}")
            if actualizados or errores:
                st.rerun()
            else:
                st.info("No se detectaron cambios para guardar.")

    with tab_ordenes:
        render_ordenes(store, df_filtrado)

    with tab_admin:
        render_administracion(store)


# ===========================================================================
# PUNTO DE ENTRADA
# ===========================================================================
store = get_store()
orden_param = st.query_params.get("orden")
if orden_param:
    render_modo_proveedor(store, orden_param)
else:
    render_modo_gestor(store)
