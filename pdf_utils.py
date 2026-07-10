import os
from datetime import datetime
from io import BytesIO
 
from fpdf import FPDF
 
NOMBRE_PROYECTO = "Terminal de Cruceros de Amador"
 
# Se resuelve la carpeta del logo relativa a la ubicacion de ESTE archivo
# (pdf_utils.py) en disco, NO al directorio de trabajo (cwd) del proceso.
# Esto evita un bug muy comun: `streamlit run` puede ejecutarse desde una
# carpeta distinta a la del proyecto, lo que hace que una ruta relativa
# simple como "logo.png" no se encuentre aunque el archivo si este junto a
# app.py. Usar __file__ garantiza que siempre apunte a la carpeta real del
# proyecto, sin importar desde donde se lance el comando.
_CARPETA_PROYECTO = os.path.dirname(os.path.abspath(__file__))
_NOMBRE_LOGO_ESPERADO = "logo.png"
LOGO_PATH_DEFAULT = os.path.join(_CARPETA_PROYECTO, _NOMBRE_LOGO_ESPERADO)
 
_EXTENSIONES_IMAGEN_VALIDAS = (".png", ".jpg", ".jpeg")
 
 
def _nombre_base_sin_extensiones_imagen(nombre_archivo: str) -> str:
    """
    Quita extensiones de imagen conocidas del final del nombre, de forma
    REPETIDA (no solo una vez). Esto es necesario por un caso muy comun en
    Windows: si "Ocultar extensiones para tipos de archivo conocidos" esta
    activado y el usuario renombra una foto a "logo.png" desde el
    Explorador, Windows conserva la extension real oculta y el archivo
    termina llamandose en el disco "logo.png.jpg" o "logo.png.png" (el
    Explorador solo te muestra "logo.png"). Con una sola pasada de
    os.path.splitext(), "logo.png.jpg" deja "logo.png" (no "logo"), por lo
    que no se reconocia. Quitando extensiones repetidamente si hace falta.
    """
    base = nombre_archivo.lower()
    cambiado = True
    while cambiado:
        cambiado = False
        for ext in _EXTENSIONES_IMAGEN_VALIDAS:
            if base.endswith(ext):
                base = base[: -len(ext)]
                cambiado = True
                break
    return base
 
 
def resolver_logo_path() -> str:
    """
    Busca el archivo de logo en la carpeta del proyecto de forma TOLERANTE:
    - Primero intenta la coincidencia exacta "logo.png" (caso normal).
    - Si no la encuentra, busca cualquier archivo cuyo nombre "base" (tras
      quitar extension(es) de imagen del final, incluyendo el caso de doble
      extension oculta de Windows como "logo.png.jpg") sea exactamente
      "logo", en cualquier combinacion de mayusculas/minusculas. El formato
      real se identifica por el contenido del archivo (PIL/fpdf2 no miran
      la extension), asi que cualquier variante funciona igual.
    - Si hay mas de un archivo candidato, se prefiere el que termine en
      ".png" (por ser el nombre esperado), luego ".jpg"/".jpeg", y como
      ultimo criterio el orden alfabetico, para un resultado predecible.
    - Se ejecuta en cada llamada (no se cachea) para reflejar el estado
      real del disco en todo momento.
 
    Devuelve la ruta encontrada, o LOGO_PATH_DEFAULT si no se encontro nada.
    """
    if os.path.exists(LOGO_PATH_DEFAULT):
        return LOGO_PATH_DEFAULT
 
    candidatos = []
    try:
        for nombre_archivo in os.listdir(_CARPETA_PROYECTO):
            ruta_completa = os.path.join(_CARPETA_PROYECTO, nombre_archivo)
            if not os.path.isfile(ruta_completa):
                continue
            if _nombre_base_sin_extensiones_imagen(nombre_archivo) == "logo":
                candidatos.append(nombre_archivo)
    except Exception:
        return LOGO_PATH_DEFAULT
 
    if not candidatos:
        return LOGO_PATH_DEFAULT
 
    def _prioridad(nombre):
        n = nombre.lower()
        if n.endswith(".png"):
            return (0, nombre)
        if n.endswith((".jpg", ".jpeg")):
            return (1, nombre)
        return (2, nombre)
 
    candidatos.sort(key=_prioridad)
    return os.path.join(_CARPETA_PROYECTO, candidatos[0])
 
 
def diagnosticar_logo(logo_path: str = None) -> dict:
    """
    Verifica si el logo corporativo se puede cargar, y por que no si falla,
    para poder mostrar un diagnostico claro en la interfaz (barra lateral)
    en vez de que el logo simplemente no aparezca sin explicacion.
 
    Devuelve un dict:
        ruta_buscada       -> donde se esperaba encontrarlo por defecto
        ruta_encontrada    -> la ruta real usada (puede diferir de la
                               esperada si se encontro por busqueda tolerante,
                               ej. "Logo.PNG" en vez de "logo.png")
        existe, valido, error
        archivos_en_carpeta -> listado de archivos en la carpeta del
                               proyecto, para depurar a simple vista si el
                               logo esperado realmente esta ahi o no.
    """
    ruta_buscada = logo_path or LOGO_PATH_DEFAULT
    ruta_encontrada = logo_path or resolver_logo_path()
 
    try:
        archivos_en_carpeta = sorted(os.listdir(_CARPETA_PROYECTO))
    except Exception:
        archivos_en_carpeta = []
 
    resultado = {
        "ruta_buscada": ruta_buscada,
        "ruta_encontrada": ruta_encontrada,
        "existe": False,
        "valido": False,
        "error": None,
        "archivos_en_carpeta": archivos_en_carpeta,
    }
 
    if not os.path.exists(ruta_encontrada):
        resultado["error"] = (
            f"No se encontro ningun archivo de logo en '{_CARPETA_PROYECTO}'. "
            f"Se esperaba '{_NOMBRE_LOGO_ESPERADO}' (o una variante como "
            f"'Logo.png'/'logo.jpg'). Archivos que SI estan en esa carpeta: "
            f"{', '.join(archivos_en_carpeta) if archivos_en_carpeta else '(ninguno / carpeta vacia)'}."
        )
        return resultado
 
    resultado["existe"] = True
    if ruta_encontrada != ruta_buscada:
        candidatos = [
            f for f in archivos_en_carpeta
            if os.path.isfile(os.path.join(_CARPETA_PROYECTO, f))
            and _nombre_base_sin_extensiones_imagen(f) == "logo"
        ]
        aviso_multiples = ""
        if len(candidatos) > 1:
            aviso_multiples = (
                f" Ojo: hay {len(candidatos)} archivos que parecen ser el logo "
                f"({', '.join(candidatos)}) - probablemente por reintentos "
                f"anteriores. Se esta usando '{os.path.basename(ruta_encontrada)}'; "
                f"borra los demas para evitar confusion."
            )
        resultado["error"] = (
            f"Se encontro '{os.path.basename(ruta_encontrada)}' en vez de "
            f"'{_NOMBRE_LOGO_ESPERADO}' exacto. Esto suele pasar en Windows cuando "
            f"'Ocultar extensiones para tipos de archivo conocidos' esta activado: "
            f"al renombrar una foto a 'logo.png' en el Explorador, Windows conserva "
            f"la extension real oculta y el archivo queda como 'logo.png.jpg' o "
            f"'logo.png.png' en el disco. Funciona igual (se detecta por contenido, "
            f"no por el nombre), no necesitas hacer nada mas.{aviso_multiples}"
        )
    try:
        from PIL import Image as PILImage
        with PILImage.open(ruta_encontrada) as img:
            img.verify()
        resultado["valido"] = True
    except Exception as e:
        resultado["error"] = (
            f"El archivo '{os.path.basename(ruta_encontrada)}' existe pero no se "
            f"pudo leer como imagen valida ({e}). Intenta reexportarlo como PNG "
            f"o JPG estandar desde un editor de imagenes."
        )
    return resultado
 
# Si el cursor pasa de esta coordenada Y (en mm, pagina A4 = 297mm de alto),
# forzamos un salto de pagina manual antes de iniciar un bloque nuevo.
LIMITE_Y_SALTO_PAGINA = 250
 
 
def _limpiar_texto(texto) -> str:
    """Evita errores de codificacion: las fuentes core de fpdf2 (Helvetica)
    solo soportan Latin-1. Cualquier caracter fuera de ese rango se
    reemplaza en vez de lanzar una excepcion."""
    if texto is None:
        return ""
    return str(texto).encode("latin-1", "replace").decode("latin-1")
 
 
def _cargar_imagen(ruta_o_url: str):
    """Devuelve (buffer, ancho_px, alto_px) de una evidencia fotografica, sea
    ruta local o URL remota (ej. Supabase Storage). None si no se puede
    cargar (archivo roto, URL caida, etc.) para no romper el PDF completo
    por una sola foto con problemas."""
    try:
        if ruta_o_url.startswith("http://") or ruta_o_url.startswith("https://"):
            import requests
            resp = requests.get(ruta_o_url, timeout=8)
            resp.raise_for_status()
            buffer = BytesIO(resp.content)
        elif os.path.exists(ruta_o_url):
            with open(ruta_o_url, "rb") as f:
                buffer = BytesIO(f.read())
        else:
            return None
        buffer.seek(0)
        from PIL import Image as PILImage
        with PILImage.open(buffer) as img:
            ancho_px, alto_px = img.size
        buffer.seek(0)
        return buffer, ancho_px, alto_px
    except Exception:
        return None
 
 
# ---------------------------------------------------------------------------
# CLASE PRINCIPAL: encabezado y pie de pagina FIJOS via header()/footer()
# ---------------------------------------------------------------------------
class ReportePDF(FPDF):
    """
    PDF con encabezado corporativo fijo (logo arriba-izquierda + titulo
    arriba-derecha) y pie de pagina con numeracion.
 
    El metodo header() lo ejecuta fpdf2 automaticamente al comenzar cada
    pagina nueva (dentro de add_page()), en un estado de cursor limpio, por
    lo que el logo y el titulo SIEMPRE terminan en la misma posicion sin
    importar cuanto contenido tenga el reporte.
    """
 
    def __init__(self, titulo: str, subtitulo: str = "", logo_path: str = None):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.titulo_reporte = titulo
        self.subtitulo_reporte = subtitulo
        self.logo_path = logo_path if logo_path is not None else resolver_logo_path()
        self.set_auto_page_break(auto=True, margin=20)
        self.alias_nb_pages()
 
    def header(self):
        margen_izq = self.l_margin
        margen_der = self.w - self.r_margin
        y0 = 8
        ANCHO_MAX_LOGO = 32
        ALTO_MAX_LOGO = 20
 
        alto_logo = 0
        if self.logo_path and os.path.exists(self.logo_path):
            try:
                from PIL import Image as PILImage
                with PILImage.open(self.logo_path) as img:
                    ancho_px, alto_px = img.size
                # Se escala el logo para que quepa DENTRO de un recuadro de
                # ANCHO_MAX_LOGO x ALTO_MAX_LOGO manteniendo su proporcion
                # real (igual que "object-fit: contain" en CSS), sin
                # importar si el logo es ancho (tipo banner), cuadrado, o
                # vertical (icono + texto apilado, como un escudo o sello).
                # Antes se fijaba solo el ancho a 32mm sin tope de alto, lo
                # que hacia que un logo vertical se dibujara mucho mas alto
                # de lo previsto y se solapara con el contenido de abajo.
                escala = min(ANCHO_MAX_LOGO / ancho_px, ALTO_MAX_LOGO / alto_px)
                ancho_final = ancho_px * escala
                alto_final = alto_px * escala
                self.image(self.logo_path, x=margen_izq, y=y0, w=ancho_final, h=alto_final)
                alto_logo = alto_final
            except Exception:
                alto_logo = 0  # logo invalido/corrupto: seguimos sin el, no rompemos el PDF
 
        ancho_titulo = 110
        x_titulo = margen_der - ancho_titulo
        self.set_xy(x_titulo, y0)
        self.set_font("Helvetica", "B", 13)
        self.multi_cell(ancho_titulo, 6, _limpiar_texto(self.titulo_reporte), align="R")
        if self.subtitulo_reporte:
            self.set_x(x_titulo)
            self.set_font("Helvetica", "", 9)
            self.multi_cell(ancho_titulo, 5, _limpiar_texto(self.subtitulo_reporte), align="R")
        alto_bloque_titulo = self.get_y() - y0
 
        # La linea divisoria (y por lo tanto donde arranca el contenido) se
        # ubica DESPUES de lo que sea mas alto: el logo o el bloque de
        # titulo. Asi el contenido nunca se solapa, sin importar el tamano
        # o la proporcion real del logo que se use.
        y_linea = y0 + max(alto_logo, alto_bloque_titulo) + 3
        self.set_draw_color(120, 120, 120)
        self.line(margen_izq, y_linea, margen_der, y_linea)
        self.set_y(y_linea + 4)
 
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 5, _limpiar_texto(f"Pagina {self.page_no()}/{{nb}}"), align="C")
        self.set_text_color(0, 0, 0)
 
    def salto_si_necesario(self, espacio_requerido: float = 0):
        """Salto de pagina MANUAL (ademas del automatico de fpdf2): antes de
        iniciar un bloque nuevo (equipo, tabla, seccion larga), si el cursor
        ya esta por debajo de LIMITE_Y_SALTO_PAGINA forzamos una pagina
        nueva, para no dejar un titulo huerfano al fondo de la pagina."""
        if self.get_y() + espacio_requerido > LIMITE_Y_SALTO_PAGINA:
            self.add_page()
 
    @property
    def ancho_util(self):
        return self.w - self.l_margin - self.r_margin
 
 
# ---------------------------------------------------------------------------
# BLOQUES DE CONTENIDO (cada uno usa pdf.table() para datos tabulares reales)
# ---------------------------------------------------------------------------
def _titulo_seccion(pdf: ReportePDF, texto: str):
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 11.5)
    pdf.cell(0, 6.5, _limpiar_texto(texto))
    pdf.ln(7.5)
 
 
def _tabla_datos(pdf: ReportePDF, filas: list, anchos=(1, 2)):
    """Tabla simple de 2 columnas (Campo / Valor). filas: lista de (campo, valor)."""
    datos = [[campo, valor if valor not in (None, "") else "-"] for campo, valor in filas]
    with pdf.table(col_widths=anchos, text_align=("LEFT", "LEFT"),
                    first_row_as_headings=False, line_height=5,
                    padding=1.2) as table:
        for campo, valor in datos:
            row = table.row()
            row.cell(_limpiar_texto(f"{campo}"))
            row.cell(_limpiar_texto(str(valor)))
 
 
def _tabla_checklist(pdf: ReportePDF, tareas_marcadas: list):
    """tareas_marcadas: lista de tuplas (tarea_dict, marcado_bool)."""
    if not tareas_marcadas:
        return
    with pdf.table(col_widths=(3, 1, 1.1), text_align=("LEFT", "CENTER", "CENTER"),
                    line_height=5, padding=1.2) as table:
        header = table.row()
        for titulo in ("Tarea", "Frecuencia", "Estado"):
            header.cell(titulo)
        for tarea, marcado in tareas_marcadas:
            row = table.row()
            row.cell(_limpiar_texto(tarea.get("tarea", "")))
            row.cell(_limpiar_texto(tarea.get("frecuencia", "")))
            row.cell("Completada" if marcado else "Pendiente")
 
 
def _tabla_correctivo(pdf: ReportePDF, correctivo: list):
    if not correctivo:
        return
    with pdf.table(col_widths=(1.4, 1.4, 1.6), text_align="LEFT",
                    line_height=5, padding=1.2) as table:
        header = table.row()
        for titulo in ("Sintoma", "Causa Probable", "Accion Correctiva"):
            header.cell(titulo)
        for fila in correctivo:
            row = table.row()
            row.cell(_limpiar_texto(fila.get("sintoma", "")))
            row.cell(_limpiar_texto(fila.get("causa", "")))
            row.cell(_limpiar_texto(fila.get("accion", "")))
 
 
def _bloque_observaciones(pdf: ReportePDF, texto: str):
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(pdf.ancho_util, 5.5,
                    _limpiar_texto(texto or "Sin observaciones adicionales."), border=1)
 
 
def _bloque_evidencias(pdf: ReportePDF, evidencia_urls: list):
    if not evidencia_urls:
        return
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "I", 8.5)
    pdf.cell(0, 5, _limpiar_texto(f"Evidencia fotografica ({len(evidencia_urls)} archivo(s)):"))
    pdf.ln(6)
 
    margen_izq = pdf.l_margin
    ancho_img = 45
    x_actual = margen_izq
    y_fila = pdf.get_y()
    alto_max_fila = 0
 
    for url in evidencia_urls:
        resultado = _cargar_imagen(url)
        # Altura REAL segun la proporcion de la imagen (corrige el bug de
        # asumir imagenes cuadradas: una foto en modo retrato es mas alta
        # que ancha y necesita mas espacio vertical reservado).
        alto_estimado = ancho_img * (resultado[2] / resultado[1]) if resultado else 20
 
        if x_actual + ancho_img > pdf.w - pdf.r_margin:
            x_actual = margen_izq
            y_fila = y_fila + alto_max_fila + 3
            alto_max_fila = 0
 
        if y_fila + alto_estimado > LIMITE_Y_SALTO_PAGINA:
            pdf.add_page()
            y_fila = pdf.get_y()
            x_actual = margen_izq
            alto_max_fila = 0
 
        if resultado:
            buffer, ancho_px, alto_px = resultado
            try:
                pdf.image(buffer, x=x_actual, y=y_fila, w=ancho_img)
            except Exception:
                pdf.set_xy(x_actual, y_fila)
                pdf.set_font("Helvetica", "", 7)
                pdf.multi_cell(ancho_img, 4, "(no se pudo cargar la imagen)", border=1)
                alto_estimado = max(alto_estimado, 16)
        else:
            pdf.set_xy(x_actual, y_fila)
            pdf.set_font("Helvetica", "", 7)
            pdf.multi_cell(ancho_img, 4, "(imagen no disponible)", border=1)
            alto_estimado = max(alto_estimado, 16)
 
        alto_max_fila = max(alto_max_fila, alto_estimado)
        x_actual += ancho_img + 3
 
    pdf.set_xy(margen_izq, y_fila + alto_max_fila + 3)
 
 
def bloque_reporte_equipo(pdf: ReportePDF, reporte: dict, modelo_info: dict,
                            incluir_guia_fallas: bool = True, incluir_evidencias: bool = True):
    """Dibuja el bloque completo de un equipo dentro de un reporte (usado por
    el reporte individual y por cada seccion del reporte consolidado)."""
 
    pdf.salto_si_necesario(espacio_requerido=40)
    _titulo_seccion(pdf, f"Equipo: {reporte.get('tag_equipo', '')}")
    _tabla_datos(pdf, [
        ("Categoria", reporte.get("categoria", "")),
        ("Zona / Nivel", f"{reporte.get('zona', '-')} / {reporte.get('nivel', '-')}"),
        ("Modelo de referencia", reporte.get("modelo_referencia", "")),
        ("Orden de Trabajo", reporte.get("orden_id", "")),
        ("Tecnico", reporte.get("tecnico", "")),
        ("Fecha de servicio", reporte.get("fecha_servicio", "")),
        ("Hora inicio / fin", f"{reporte.get('hora_inicio', '-')} - {reporte.get('hora_fin', '-')}"),
        ("Estado final", reporte.get("estado_final", "")),
    ] + ([("Fallas detectadas", reporte.get("sintomas_detectados"))]
         if reporte.get("sintomas_detectados") else [])
      + [("Proximo mantenimiento programado", reporte.get("proximo_mantenimiento", ""))])
    pdf.ln(2)
 
    tareas_marcadas = reporte.get("_tareas_marcadas")
    if tareas_marcadas:
        pdf.salto_si_necesario(espacio_requerido=25)
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.cell(0, 5.5, _limpiar_texto(
            f"Checklist preventivo: {reporte.get('tareas_completadas', 0)} de "
            f"{reporte.get('tareas_totales', 0)} tareas completadas"))
        pdf.ln(6)
        _tabla_checklist(pdf, tareas_marcadas)
        pdf.ln(2)
 
    if reporte.get("observaciones"):
        pdf.salto_si_necesario(espacio_requerido=20)
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.cell(0, 5.5, "Observaciones:")
        pdf.ln(5.5)
        _bloque_observaciones(pdf, reporte["observaciones"])
        pdf.ln(2)
 
    if incluir_evidencias and reporte.get("_evidencias_lista"):
        pdf.salto_si_necesario(espacio_requerido=50)
        _bloque_evidencias(pdf, reporte["_evidencias_lista"])
        pdf.ln(2)
 
    if incluir_guia_fallas and modelo_info and modelo_info.get("correctivo"):
        pdf.salto_si_necesario(espacio_requerido=25)
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.cell(0, 5.5, _limpiar_texto(
            f"Guia de fallas de referencia ({modelo_info.get('nombre', '')})"))
        pdf.ln(6)
        _tabla_correctivo(pdf, modelo_info["correctivo"])
 
 
def _bloque_firma(pdf: ReportePDF, nombre_tecnico: str = "", nombre_gestor: str = ""):
    pdf.salto_si_necesario(espacio_requerido=35)
    pdf.ln(6)
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.cell(0, 6, "Firmas de Cierre")
    pdf.ln(9)
 
    margen_izq = pdf.l_margin
    x_der = margen_izq + pdf.ancho_util
    y_firma = pdf.get_y()
    pdf.line(margen_izq, y_firma, margen_izq + 80, y_firma)
    pdf.line(x_der - 80, y_firma, x_der, y_firma)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(margen_izq, y_firma + 1)
    pdf.cell(80, 5, _limpiar_texto(f"Firma Tecnico{': ' + nombre_tecnico if nombre_tecnico else ''}"),
             align="C")
    pdf.set_xy(x_der - 80, y_firma + 1)
    pdf.cell(80, 5, _limpiar_texto(f"Firma Gestor{': ' + nombre_gestor if nombre_gestor else ''}"),
             align="C")
    pdf.set_xy(margen_izq, y_firma + 12)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(pdf.ancho_util, 5, _limpiar_texto(
        f"Generado el {datetime.now():%Y-%m-%d %H:%M} - Sistema de Gestion de Mantenimiento HVAC"),
        align="C")
 
 
# ---------------------------------------------------------------------------
# REPORTE INDIVIDUAL (un equipo / una orden)
# ---------------------------------------------------------------------------
def generar_pdf_individual(reporte: dict, modelo_info: dict, tareas_marcadas: list,
                             evidencias: list = None, logo_path: str = None) -> bytes:
    pdf = ReportePDF("Reporte de Mantenimiento HVAC", NOMBRE_PROYECTO, logo_path)
    pdf.add_page()
 
    reporte = dict(reporte)
    reporte["_tareas_marcadas"] = tareas_marcadas
    reporte["_evidencias_lista"] = evidencias or []
 
    bloque_reporte_equipo(pdf, reporte, modelo_info)
    _bloque_firma(pdf, nombre_tecnico=reporte.get("tecnico", ""))
 
    return bytes(pdf.output())
 
 
# ---------------------------------------------------------------------------
# REPORTE CONSOLIDADO / MASIVO (varias ordenes completadas)
# ---------------------------------------------------------------------------
def generar_pdf_consolidado(reportes_por_orden: list, logo_path: str = None,
                              nombre_gestor: str = "") -> bytes:
    """
    reportes_por_orden: lista de dicts:
        {
            "orden_id": str,
            "reportes": [ { ...campos del reporte..., "_tareas_marcadas": [...],
                             "_evidencias_lista": [...], "_modelo_info": {...} }, ... ],
        }
    """
    total_ordenes = len(reportes_por_orden)
    total_equipos = sum(len(o["reportes"]) for o in reportes_por_orden)
 
    pdf = ReportePDF(
        "Reporte Consolidado de Mantenimiento",
        f"{NOMBRE_PROYECTO}  -  {total_ordenes} orden(es) / {total_equipos} equipo(s)",
        logo_path)
    pdf.add_page()
 
    tecnicos_involucrados = set()
    for orden in reportes_por_orden:
        pdf.salto_si_necesario(espacio_requerido=20)
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_fill_color(235, 235, 235)
        pdf.cell(pdf.ancho_util, 7, _limpiar_texto(f"Orden de Trabajo: {orden['orden_id']}"),
                 border=1, fill=True)
        pdf.ln(9)
 
        for reporte in orden["reportes"]:
            modelo_info = reporte.get("_modelo_info", {})
            bloque_reporte_equipo(pdf, reporte, modelo_info,
                                    incluir_guia_fallas=True, incluir_evidencias=True)
            if reporte.get("tecnico"):
                tecnicos_involucrados.add(reporte["tecnico"])
            pdf.ln(3)
            pdf.set_x(pdf.l_margin)
            pdf.set_draw_color(200, 200, 200)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pdf.ancho_util, pdf.get_y())
            pdf.ln(3)
 
    nombre_tecnico_firma = " / ".join(sorted(tecnicos_involucrados)) if tecnicos_involucrados else ""
    _bloque_firma(pdf, nombre_tecnico=nombre_tecnico_firma, nombre_gestor=nombre_gestor)
 
    return bytes(pdf.output())