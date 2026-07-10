# -*- coding: utf-8 -*-
"""
data_store.py
Capa de datos de la aplicacion de Mantenimiento HVAC.

Contiene:
  - La base de datos semilla (SEED) de los ~120 equipos reales y los modelos
    de mantenimiento extraidos del manual.
  - Una interfaz abstracta `DataStore` con 3 implementaciones intercambiables:
        LocalStore     -> CSV locales (modo desarrollo / respaldo sin nube)
        SupabaseStore  -> Supabase (Postgres + Storage) - recomendado para nube
        GSheetsStore   -> Google Sheets via st.connection("gsheets")
  - La funcion get_store() elige el backend automaticamente segun lo que
    encuentre en st.secrets, sin que el resto de la app tenga que saberlo.

Todos los backends comparten el MISMO esquema logico (mismas columnas /
mismo formato JSON para listas anidadas), por lo que la logica de la app
(app.py) es identica sin importar que backend este activo.
"""

import json
import os
import random
import string
import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime

import pandas as pd

# ---------------------------------------------------------------------------
# CONSTANTES GLOBALES
# ---------------------------------------------------------------------------
ESTADOS_OPERATIVOS = ["Operativo", "En Falla", "En Mantenimiento", "Fuera de Servicio"]
ESTADOS_ORDEN = ["Abierta", "Completada", "Cancelada"]

COLUMNAS_EQUIPOS = [
    "tag", "categoria", "especificaciones", "modelo", "tiene_vfd",
    "zona", "nivel", "estado_operativo", "ultimo_mantenimiento",
    "proximo_mantenimiento",
]
COLUMNAS_MODELOS = [
    "modelo_id", "nombre", "componentes", "parametros", "umbral_dias",
    "preventivo_json", "correctivo_json",
]
COLUMNAS_ORDENES = [
    "orden_id", "fecha_creacion", "equipos_json", "estado", "tecnico_asignado",
]
COLUMNAS_REPORTES = [
    "reporte_id", "orden_id", "tag_equipo", "categoria", "modelo_id", "modelo_referencia",
    "zona", "nivel", "tecnico", "fecha_servicio", "hora_inicio", "hora_fin",
    "estado_final", "sintomas_detectados", "tareas_completadas", "tareas_totales",
    "checklist_json", "observaciones", "proximo_mantenimiento", "evidencia_urls",
    "fecha_registro",
]

DATA_DIR = "data"
EVIDENCIAS_DIR = os.path.join(DATA_DIR, "evidencias")


def generar_id_orden() -> str:
    sufijo = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"OT-{date.today():%Y%m%d}-{sufijo}"


def calcular_umbral_dias(tareas_preventivo: list) -> int:
    """Regla automatica: si el plan incluye tareas Quincenales o Mensuales,
    el equipo es mas critico -> alerta a los 30 dias. En caso contrario, 90 dias."""
    frecuencias_criticas = {"quincenal", "mensual"}
    for t in tareas_preventivo:
        if t.get("frecuencia", "").strip().lower() in frecuencias_criticas:
            return 30
    return 90


# ---------------------------------------------------------------------------
# SEED: MODELOS DE MANTENIMIENTO (extraidos del Manual)
# ---------------------------------------------------------------------------
def _modelos_seed() -> dict:
    modelos = {
        "carrier_30xw": {
            "nombre": "Carrier 30XW / 30XWH / 30XW-P / 30XWHP (Enfriador de Liquido)",
            "componentes": "Compresor de doble tornillo (06T), evaporador de tubo "
                            "multiple inundado, condensador tipo inundado, valvula "
                            "de expansion electronica (EXV).",
            "parametros": "Refrigerante R-134a, aceite lubricante SW220, presion "
                          "operativa lado de agua hasta 1000 kPa.",
            "preventivo": [
                {"frecuencia": "Mensual", "tarea": "Inspeccion visual de Nivel 1",
                 "procedimiento": "Revisar mirilla indicadora de humedad en busca de "
                                   "perdida de refrigerante y trazas de aceite.",
                 "herramientas": "Inspeccion visual, linterna"},
                {"frecuencia": "Trimestral", "tarea": "Verificacion operativa del circuito",
                 "procedimiento": "Revisar carga de refrigerante, buscar fugas en "
                                   "juntas y comprobar interruptor de flujo.",
                 "herramientas": "Detector de fugas de gas"},
                {"frecuencia": "Semestral", "tarea": "Revision de control e interruptores",
                 "procedimiento": "Inspeccionar la punta del sensor de dispersion "
                                   "termica (flujo) y revisar consumo de "
                                   "interruptores diferenciales.",
                 "herramientas": "Herramientas de limpieza"},
                {"frecuencia": "Anual", "tarea": "Nivel 2: Mantenimiento electrico y agua",
                 "procedimiento": "Reapretar conexiones electricas de potencia/control, "
                                   "limpiar intercambiadores y tomar muestras de aceite "
                                   "para analisis.",
                 "herramientas": "Torquimetro, envase para aceite"},
            ],
            "correctivo": [
                {"sintoma": "Unidad no arranca",
                 "causa": "Falla de suministro electrico o alarma bloqueante activa",
                 "accion": "Comprobar dispositivo de proteccion sobrecorriente, "
                            "restablecer la energia o revisar menu de alarmas."},
                {"sintoma": "Unidad opera continua o excesivamente",
                 "causa": "Baja carga de refrigerante, gas incondensable, EXV "
                          "trabada o contactor soldado",
                 "accion": "Buscar fugas y recargar, purgar, limpiar/reemplazar la "
                            "Valvula de Expansion Electronica o los contactores."},
                {"sintoma": "Alarma 132-03 (Proteccion por Alta Presion)",
                 "causa": "Perdida de flujo de agua en condensador o switch defectuoso",
                 "accion": "Revisar bombas y flujo de agua del condensador, resetear "
                            "switch manualmente."},
                {"sintoma": "Alarma 132-04 / 132-05 (Sobrecorriente o Rotor Bloqueado)",
                 "causa": "Operacion fuera del envolvente del compresor, falla mecanica",
                 "accion": "Detener el circuito; revisar parametro MTA y estado "
                            "mecanico del compresor y la valvula corredera."},
            ],
        },
        "evapco_torres": {
            "nombre": "Torres de Enfriamiento EVAPCO (Series SUN, AT, AXS, UT, USS)",
            "componentes": "Reductor de engranajes, motor del ventilador, sistema de "
                            "distribucion de agua, eliminadores de rocio, sumidero de "
                            "agua fria.",
            "parametros": "Agua de enfriamiento; purga maxima de 3 US GPM por cada "
                          "100 toneladas.",
            "preventivo": [
                {"frecuencia": "Mensual", "tarea": "Limpieza del colador y revision del sumidero",
                 "procedimiento": "Limpiar el colador de la bandeja y comprobar/ajustar "
                                   "la valvula del flotador si es necesario.",
                 "herramientas": "Herramientas de limpieza manual"},
                {"frecuencia": "Mensual", "tarea": "Verificacion del reductor de engranajes",
                 "procedimiento": "Revisar nivel de aceite (con equipo detenido) e "
                                   "inspeccionar ruidos/vibraciones y posibles fugas.",
                 "herramientas": "Aceite lubricante"},
                {"frecuencia": "Trimestral", "tarea": "Limpieza y lavado de bandeja (Pan)",
                 "procedimiento": "Drenar, limpiar y lavar a ras el sumidero de agua "
                                   "fria manteniendo las mallas instaladas.",
                 "herramientas": "Manguera, cepillo de cerdas suaves"},
                {"frecuencia": "Semestral", "tarea": "Mantenimiento electrico y lubricacion",
                 "procedimiento": "Probar el aislamiento (Megger) de las bobinas del "
                                   "motor y lubricar rodamientos del ventilador.",
                 "herramientas": "Megger, pistola de engrase"},
                {"frecuencia": "Anual", "tarea": "Proteccion anticorrosiva y correas",
                 "procedimiento": "Inspeccionar corrosion en poleas, raspar y recubrir "
                                   "con ZRC. Revisar y ajustar tension de correas.",
                 "herramientas": "Recubrimiento ZRC, medidor de tension"},
            ],
            "correctivo": [
                {"sintoma": "Sobreconsumo de amperaje (Overamping)",
                 "causa": "Reduccion de presion estatica, giro incorrecto o tension "
                          "excesiva en la correa",
                 "accion": "Verificar tension de la banda, comprobar nivel de agua y "
                            "corregir cables del motor si la rotacion es inversa."},
                {"sintoma": "Patron de rociado de agua incompleto",
                 "causa": "Boquillas o colador obstruidos",
                 "accion": "Retirar y limpiar boquillas, lavar internamente todo el "
                            "sistema de distribucion de agua."},
                {"sintoma": "Motor trabajando en fase simple (No arranca)",
                 "causa": "Cables conectados incorrectamente o rodamientos "
                          "severamente danados",
                 "accion": "Detener el motor, chequear el diagrama electrico, medir "
                            "voltajes en las tres fases y cambiar rodamientos si "
                            "estan trabados."},
                {"sintoma": "Rejillas de entrada con incrustaciones (Scale)",
                 "causa": "Tratamiento de agua inadecuado, purga insuficiente o "
                          "alta dureza",
                 "accion": "Desmontar rejillas y remojarlas en la bandeja de agua "
                            "fria aprovechando los quimicos del tratamiento de agua."},
            ],
        },
        "systemair_uma": {
            "nombre": "Systemair DV / 39CQM (Unidades de Manejo de Aire - AHU)",
            "componentes": "Ventiladores (Plug Fans / centrifugos), baterias de "
                            "refrigeracion y calefaccion, intercambiador de calor de "
                            "placas/rotativo, banco de filtros tipo panel, compuertas.",
            "parametros": "Agua helada, caliente o refrigerante en bateria de "
                          "expansion directa DX; flujos de aire desde 2,000 a "
                          "100,000 m3/h.",
            "preventivo": [
                {"frecuencia": "Anual", "tarea": "Reemplazo y control de filtros",
                 "procedimiento": "Monitorear la caida de presion y reemplazar los "
                                   "filtros para preservar el valor SFP nominal del "
                                   "diseno (cambio forzado maximo cada 2 anos).",
                 "herramientas": "Filtros nuevos de igual caracteristica (MERV-13 / MERV-8)"},
                {"frecuencia": "Anual", "tarea": "Inspeccion y limpieza de bateria de frio/calor",
                 "procedimiento": "Limpiar superficialmente las aletas con una "
                                   "aspiradora o un soplado suave de aire comprimido.",
                 "herramientas": "Aspiradora, aire comprimido a baja presion"},
                {"frecuencia": "Anual", "tarea": "Mantenimiento de bandejas de condensado",
                 "procedimiento": "Limpiar la bandeja de drenaje (drip tray) y el "
                                   "sifon (water trap) debajo de los serpentines.",
                 "herramientas": "Cepillos, agua limpia"},
                {"frecuencia": "Anual", "tarea": "Inspeccion de ventiladores (Fans) y soportes",
                 "procedimiento": "Limpiar aspas para evitar desbalances por polvo. "
                                   "Chequear rodamientos y soportes antivibracion.",
                 "herramientas": "Aspiradora, llaves inglesas"},
            ],
            "correctivo": [
                {"sintoma": "Vibracion excesiva en el ventilador (Plug fan)",
                 "causa": "Acumulacion de polvo en el rodete o soportes "
                          "amortiguadores rotos",
                 "accion": "Realizar limpieza profunda del rodete. Inspeccionar "
                            "uniones flexibles y reemplazar amortiguadores si estan "
                            "fisurados."},
                {"sintoma": "Bloqueo o averia tecnica detectada (general)",
                 "causa": "Falla electromecanica y/o accionamiento de seguridad termica",
                 "accion": "Configurar panel de control en OFF, aislar breakers con "
                            "candado (tag out), corregir bloqueo y seguir la "
                            "secuencia segura de arranque."},
            ],
        },
        "fancoil_carrier": {
            "nombre": "System Fan Coil 42BHE, BVE06-40",
            "componentes": "Rueda y carcasa del ventilador (blower), serpentin "
                            "(coil), bandeja de drenaje (drain pan), rack para filtro.",
            "parametros": "Agua fria o agua caliente.",
            "preventivo": [
                {"frecuencia": "Trimestral", "tarea": "Mantenimiento mecanico y ventilacion",
                 "procedimiento": "Lubricar rodamientos del motor y ventilador, "
                                   "comprobar/ajustar la tension de la correa y "
                                   "sustituir filtro de aire.",
                 "herramientas": "Aceite/grasa, medidor de tension, filtro nuevo"},
                {"frecuencia": "Anual", "tarea": "Limpieza profunda e inspeccion",
                 "procedimiento": "Inspeccionar y apretar conexiones electricas, "
                                   "limpiar serpentin, rueda del ventilador y bandeja "
                                   "de condensado.",
                 "herramientas": "Destornillador, desengrasante suave, agua"},
            ],
            "correctivo": [
                {"sintoma": "Excesiva condensacion o sudoracion en el equipo",
                 "causa": "Funcionamiento o paso de agua fria con el ventilador detenido",
                 "accion": "Mantener operacion del ventilador en modo continuo o "
                            "instalar una valvula de control de flujo para detener "
                            "el agua."},
            ],
        },
        "lg_vrf": {
            "nombre": "LG Multi V / Equipos Split (Cassette, Conducto, Mural, Consola)",
            "componentes": "Tarjeta PCB, intercambiador de calor (evaporador/"
                            "condensador), filtro de aire, filtro PM1.0, filtro de "
                            "plasma, panel/rejilla frontal.",
            "parametros": "Refrigerante R410A o R32; presiones de prueba hasta "
                          "3.8 MPa (551.1 psi) con nitrogeno seco.",
            "preventivo": [
                {"frecuencia": "Quincenal", "tarea": "Limpieza del filtro de aire",
                 "procedimiento": "Retirar el filtro de la rejilla, usar aspiradora "
                                   "o lavar con agua tibia (menor a 40 C) y secar a "
                                   "la sombra.",
                 "herramientas": "Aspiradora, agua tibia, pano suave"},
                {"frecuencia": "Trimestral", "tarea": "Mantenimiento de filtros de Plasma",
                 "procedimiento": "Extraer el filtro de plasma y limpiarlo con "
                                   "aspiradora o lavarlo con agua templada.",
                 "herramientas": "Aspiradora"},
                {"frecuencia": "Semestral", "tarea": "Limpieza del Filtro PM1.0",
                 "procedimiento": "Remojar en agua tibia por 30 min con detergente "
                                   "suave, enjuagar sin frotar y secar un dia a la sombra.",
                 "herramientas": "Agua tibia, detergente suave"},
                {"frecuencia": "Semestral", "tarea": "Mantenimiento del Sensor PM1.0",
                 "procedimiento": "Retirar tapa de goma de la caja del sensor, "
                                   "limpiar los lentes con un hisopo humedo.",
                 "herramientas": "Hisopos de algodon"},
                {"frecuencia": "Semestral", "tarea": "Filtro de desodorizacion",
                 "procedimiento": "Extraer filtro y dejar secar a la luz solar o luz "
                                   "fluorescente por 3 horas. No lavar con agua.",
                 "herramientas": "Exposicion a luz solar"},
            ],
            "correctivo": [
                {"sintoma": "Fuga de condensacion o goteo",
                 "causa": "Corriente de aire frio enfriando el aire caliente humedo "
                          "de la sala",
                 "accion": "Secar la unidad; asegurar aislamiento adecuado y evitar "
                            "largas operaciones con ventanas abiertas."},
                {"sintoma": "Error 01, 02, 06 (Sensor T. Interior)",
                 "causa": "Sensor de temperatura del aire o del tubo abierto o "
                          "cortocircuitado",
                 "accion": "Verificar las clavijas y medir la resistencia del "
                            "sensor. Si esta defectuoso, reemplazarlo."},
                {"sintoma": "Error 21 (Fallo IPM de Compresor exterior)",
                 "causa": "Fallo en accionamiento IPM del inversor del compresor",
                 "accion": "Inspeccionar componentes de potencia de la tarjeta de "
                            "control exterior y reemplazar placa inversora si persiste."},
                {"sintoma": "Timbre suena 7 veces seguidas",
                 "causa": "Humedad residual interna en filtro PM1.0 tras limpieza",
                 "accion": "Secar el filtro durante mas horas a la sombra. Comprobar "
                            "que no este rota la malla."},
            ],
        },
        "abb_vfd": {
            "nombre": "ABB ACH550-01 (Variador de Frecuencia / Drive de CA)",
            "componentes": "Tarjeta de control, disipador termico, ventilador de "
                            "refrigeracion principal e interno, condensadores de "
                            "bus de CC.",
            "parametros": "Alimentacion CA (208-240 V o 380-480 V), corrientes "
                          "nominales especificas.",
            "preventivo": [
                {"frecuencia": "6 a 12 meses", "tarea": "Comprobacion y limpieza del disipador",
                 "procedimiento": "Cortar tension y aplicar aire comprimido de abajo "
                                   "a arriba, usando en simultaneo una aspiradora.",
                 "herramientas": "Compresor de aire sin humedad, aspiradora"},
                {"frecuencia": "Anual", "tarea": "Reacondicionamiento de condensadores",
                 "procedimiento": "Aplicable si el equipo ha estado almacenado sin "
                                   "uso por mas de un ano antes de iniciar su "
                                   "funcionamiento.",
                 "herramientas": "Procedimiento de Reforming ABB"},
                {"frecuencia": "3 anos", "tarea": "Sustitucion de ventilador de armario",
                 "procedimiento": "Extraer y reemplazar el ventilador interno del "
                                   "armario (en modelos IP54 / Tipo 12) presionando "
                                   "las presillas.",
                 "herramientas": "Ventilador de repuesto (interno)"},
                {"frecuencia": "6 anos", "tarea": "Sustitucion de ventilador principal",
                 "procedimiento": "Prevenir fallo ante ruidos de rodamientos o "
                                   "incrementos de temperatura.",
                 "herramientas": "Destornillador, ventilador principal nuevo"},
            ],
            "correctivo": [
                {"sintoma": "Fallo 1: SOBREINTENSIDAD",
                 "causa": "Carga de motor excesiva, tiempo de aceleracion muy corto",
                 "accion": "Aumentar tiempo de aceleracion en parametros; comprobar "
                            "aislamientos y conexiones del motor."},
                {"sintoma": "Fallo 2: SOBRETENSION CC",
                 "causa": "Picos estaticos en alimentacion de entrada o frenado corto",
                 "accion": "Aumentar tiempo de deceleracion (parametros 2203/2206) "
                            "o revisar chopper de frenado."},
                {"sintoma": "Fallo 3: EXCESO TEMP DISP",
                 "causa": "Obstruccion de aire, polvo en disipador o fallo del ventilador",
                 "accion": "Limpiar aletas del disipador termico, revisar "
                            "operatividad del ventilador."},
                {"sintoma": "Fallo 6: SUBTENSION CC",
                 "causa": "Fase ausente en la red principal, fusible danado",
                 "accion": "Verificar fusibles de la red electrica, medir balance "
                            "de tension entre fases."},
            ],
        },
        "generico": {
            "nombre": "Mantenimiento Preventivo Estandar (PLANTILLA GENERICA TEMPORAL)",
            "componentes": "Este equipo no tiene un manual de fabricante especifico "
                            "cargado en el sistema todavia.",
            "parametros": "Pendiente de definir con el manual real del proveedor.",
            "preventivo": [
                {"frecuencia": "Mensual", "tarea": "Inspeccion visual general",
                 "procedimiento": "Verificar estado fisico del equipo, ausencia de "
                                   "ruidos, vibraciones anomalas y fugas visibles.",
                 "herramientas": "Inspeccion visual"},
                {"frecuencia": "Trimestral", "tarea": "Limpieza de componentes accesibles",
                 "procedimiento": "Limpiar rejillas, filtros, aspas o superficies "
                                   "expuestas segun aplique al tipo de equipo.",
                 "herramientas": "Herramientas de limpieza manual"},
                {"frecuencia": "Semestral", "tarea": "Revision electrica basica",
                 "procedimiento": "Verificar conexiones, medir amperaje de operacion "
                                   "y revisar estado de protecciones termicas.",
                 "herramientas": "Multimetro / pinza amperometrica"},
                {"frecuencia": "Anual", "tarea": "Revision mecanica general",
                 "procedimiento": "Verificar rodamientos, tension de correas o "
                                   "acoples y estado del aislamiento del motor.",
                 "herramientas": "Herramientas basicas de mantenimiento"},
            ],
            "correctivo": [
                {"sintoma": "Pendiente de definir",
                 "causa": "Plantilla generica sin datos de fabricante todavia",
                 "accion": "Actualizar esta seccion en la pestana de Administracion "
                            "una vez que se obtenga el manual del proveedor."},
            ],
        },
    }
    for m in modelos.values():
        m["umbral_dias"] = calcular_umbral_dias(m["preventivo"])
    return modelos


NOTAS_CATEGORIA = {
    "Enfriadores (Chillers)": "Caudal de agua helada: 360 GPM. Caudal de agua de "
        "condensacion: 540 GPM. Eficiencia: 18.95 Btu/Wh. Proteccion: 350A/3P. "
        "Motor RLA: 261A. Peso aproximado: 9,506 lb.",
    "Bombas de Agua Fria": "Variador de frecuencia con bypass. Aisladores de "
        "vibracion tipo resorte.",
    "Bombas de Agua de Condensacion": "Variador de frecuencia con bypass. "
        "Aisladores de vibracion tipo resorte.",
    "Torres de Enfriamiento": "Propela vertical, variador de frecuencia (VFD), "
        "aplicacion marina.",
    "Unidades Manejadoras de Aire (UMA)": "Accesorios principales: variador de "
        "frecuencia, filtro MERV-13, filtro MERV-8, caja de mezcla y luz "
        "ultravioleta. Todas las maquinas son de tipo doble pared.",
    "VRF - Unidades Interiores": "Tipos identificados: cassette 4 vias, fan coil, "
        "piso-techo y pared.",
    "Unidad Recuperadora de Energia (ERV)": "Filtros 30%. Instalacion interior.",
    "Unidad de Precision": "Refrigerante R-410A. Compresor scroll. Flujo hacia abajo.",
}


# ---------------------------------------------------------------------------
# SEED: LISTADO REAL DE EQUIPOS (Plano A2-1-PL-M137)
# ---------------------------------------------------------------------------
def _fila_equipo(tag, categoria, especs, modelo, tiene_vfd=False):
    return {
        "tag": tag, "categoria": categoria, "especificaciones": especs,
        "modelo": modelo, "tiene_vfd": tiene_vfd, "zona": "", "nivel": "",
        "estado_operativo": "Operativo", "ultimo_mantenimiento": "",
        "proximo_mantenimiento": "",
    }


def _equipos_seed() -> list:
    equipos = []

    chillers = {
        "CH-01": "194.8 TR, Tornillo, R134A, 460V-3F-60Hz, 123.3 kW",
        "CH-02": "194.8 TR, Tornillo, R134A, 460V-3F-60Hz, 123.3 kW",
        "CH-03": "194.8 TR, Tornillo, R134A, 460V-3F-60Hz, 123.3 kW",
    }
    for t, e in chillers.items():
        equipos.append(_fila_equipo(t, "Enfriadores (Chillers)", e, "carrier_30xw"))

    bombas_fria = {f"B-{i}": "Agua fria, 600 GPM, 20 HP, 1688 RPM, 460-3-60" for i in (1, 2, 3)}
    for t, e in bombas_fria.items():
        equipos.append(_fila_equipo(t, "Bombas de Agua Fria", e, "generico", True))

    bombas_cond = {f"B-{i}": "Agua de condensacion, 1000 GPM, 25 HP, 1740 RPM, 460-3-60"
                   for i in (4, 5, 6)}
    for t, e in bombas_cond.items():
        equipos.append(_fila_equipo(t, "Bombas de Agua de Condensacion", e, "generico", True))

    torres = {f"CT-{i}": "182.88 Ton, 49,000 CFM, 15 HP, 460-3-60, Propela vertical/marina"
              for i in (1, 2, 3)}
    for t, e in torres.items():
        equipos.append(_fila_equipo(t, "Torres de Enfriamiento", e, "evapco_torres", True))

    uma = {
        "UMA-03": "277.4 MBH, 8,100 CFM, 15 HP, 460V-3F-60Hz",
        "UMA-04": "208.2 MBH, 7,500 CFM, 15 HP, 460V-3F-60Hz",
        "UMA-05": "208.2 MBH, 7,500 CFM, 15 HP, 460V-3F-60Hz",
        "UMA-06": "254.33 MBH, 9,600 CFM, 15 HP, 460V-3F-60Hz",
        "UMA-07": "152.05 MBH, 6,200 CFM, 7.5 HP, 460V-3F-60Hz",
        "UMA-08": "340 MBH, 10,500 CFM, 20 HP, 460V-3F-60Hz",
        "UMA-09": "498 MBH, 20,500 CFM, 30 HP, 460V-3F-60Hz",
        "UMA-10": "285.62 MBH, 11,000 CFM, 15 HP, 460V-3F-60Hz",
        "UMA-11": "285.62 MBH, 11,000 CFM, 15 HP, 460V-3F-60Hz",
        "UMA-12": "285.62 MBH, 11,000 CFM, 15 HP, 460V-3F-60Hz",
        "UMA-13": "341.2 MBH, 11,000 CFM, 15 HP, 460V-3F-60Hz",
        "UMA-14": "164.6 MBH, 14,500 CFM, 20 HP, 460V-3F-60Hz",
        "UMA-15": "226.5 MBH, 14,500 CFM, 20 HP, 460V-3F-60Hz",
        "UMA-16": "359.12 MBH, 17,300 CFM, 25 HP, 460V-3F-60Hz",
        "UMA-17": "433.24 MBH, 6,600 CFM, 7.5 HP, 460V-3F-60Hz",
    }
    for t, e in uma.items():
        equipos.append(_fila_equipo(t, "Unidades Manejadoras de Aire (UMA)", e,
                                      "systemair_uma", True))

    fan_coils = {
        "FC-1a": "65.5 MBH, 2,000 CFM, 277V-1F-60Hz", "FC-1b": "65.5 MBH, 2,000 CFM, 277V-1F-60Hz",
        "FC-2a": "65.5 MBH, 2,000 CFM, 277V-1F-60Hz", "FC-2b": "65.5 MBH, 2,000 CFM, 277V-1F-60Hz",
        "FC-2c": "65.5 MBH, 2,000 CFM, 277V-1F-60Hz", "FC-18": "18.7 MBH, 600 CFM, 277V-1F-60Hz",
        "FC-19": "68.7 MBH, 2,000 CFM, 277V-1F-60Hz", "FC-20": "68.7 MBH, 2,000 CFM, 277V-1F-60Hz",
        "FC-21": "68.7 MBH, 2,000 CFM, 277V-1F-60Hz", "FC-22": "68.7 MBH, 2,000 CFM, 277V-1F-60Hz",
        "FC-23": "68.7 MBH, 2,000 CFM, 277V-1F-60Hz", "FC-24": "68.7 MBH, 2,000 CFM, 277V-1F-60Hz",
        "FC-25": "68.7 MBH, 2,000 CFM, 277V-1F-60Hz", "FC-26": "68.7 MBH, 2,000 CFM, 277V-1F-60Hz",
        "FC-27": "68.7 MBH, 2,000 CFM, 277V-1F-60Hz", "FC-28": "68.7 MBH, 2,000 CFM, 277V-1F-60Hz",
        "FC-29": "35.5 MBH, 600 CFM, 277V-1F-60Hz",
    }
    for t, e in fan_coils.items():
        equipos.append(_fila_equipo(t, "Fan Coils", e, "fancoil_carrier"))

    ext_banos = {
        "EF-01": "Extractor de banos, 300 CFM, 1/4 HP", "EF-02": "Extractor de banos, 75 CFM, 1/4 HP",
        "EF-03": "Extractor de banos, 150 CFM, 1/2 HP", "EF-04": "Extractor de banos, 75 CFM, 1/4 HP",
        "EF-05": "Extractor de banos, 75 CFM, 1/4 HP", "EF-06": "Extractor de banos, 75 CFM, 1/4 HP",
        "EF-07": "Extractor de banos, 75 CFM, 1/4 HP", "EF-10": "Extractor de cocineta, 150 CFM, 1 HP",
        "EF-11": "Extractor de banos - cuarentena, 400 CFM, 3/4 HP",
    }
    for t, e in ext_banos.items():
        equipos.append(_fila_equipo(t, "Extractores de Banos y Cocineta", e, "generico"))

    ext_humo = {"EF-08": "Extractor de humo, 15,000 CFM, 5 HP", "EF-09": "Extractor de humo, 15,000 CFM, 5 HP"}
    for t, e in ext_humo.items():
        equipos.append(_fila_equipo(t, "Extractores de Humo", e, "generico"))

    aire_fresco = {
        "SAF-01": "Aire fresco filtrado, 550 CFM, 1 HP", "SAF-02": "Aire fresco filtrado, 1,250 CFM, 1/3 HP",
        "SAF-03": "Aire fresco filtrado, 700 CFM, 1/2 HP", "SAF-04": "Aire fresco, 1,700 CFM, 1 HP",
        "SAF-05": "Aire fresco, 1,360 CFM, 1 HP",
    }
    for t, e in aire_fresco.items():
        equipos.append(_fila_equipo(t, "Abanicos de Aire Fresco", e, "generico"))

    for i in range(1, 6):
        equipos.append(_fila_equipo(f"INY-0{i}", "Abanicos de Presurizacion",
                                      "Presurizacion, 2,500 CFM, 3/4 HP", "generico"))

    equipos.append(_fila_equipo(
        "ERV", "Unidad Recuperadora de Energia (ERV)",
        "Aire fresco 9,400 CFM / Extraccion 6,500 CFM, 10 HP suministro, "
        "5 HP extraccion, 480-3-60", "generico"))

    vrf_cond = {
        "UC-01": "192,000 Btu/h - Unidad exterior VRF", "UC-02": "241,000 Btu/h - Unidad exterior VRF",
        "UC-03": "264,000 Btu/h - Unidad exterior VRF", "UC-04": "192,000 Btu/h - Unidad exterior VRF",
        "UC-05": "100,000 Btu/h - Unidad exterior VRF", "UC-06": "80,000 Btu/h - Unidad exterior VRF",
        "UC-07": "12,000 Btu/h - Unidad exterior asociada a UI-46",
    }
    for t, e in vrf_cond.items():
        equipos.append(_fila_equipo(t, "VRF - Unidades Condensadoras", e, "lg_vrf"))

    vrf_int = {
        "UI-01": 12000, "UI-02": 12000, "UI-03": 36000, "UI-04": 36000, "UI-05": 36000,
        "UI-06": 36000, "UI-07": 18000, "UI-08": 12000, "UI-09": 36000, "UI-10": 36000,
        "UI-11": 36000, "UI-12": 18000, "UI-13": 36000, "UI-14": 54000, "UI-15": 36000,
        "UI-16": 36000, "UI-17": 12000, "UI-18": 12000, "UI-19": 12000, "UI-20": 12000,
        "UI-21": 12000, "UI-22": 18000, "UI-23": 18000, "UI-24": 18000, "UI-25": 36000,
        "UI-26": 18000, "UI-27": 36000, "UI-28": 36000, "UI-29": 12000, "UI-30": 9000,
        "UI-31": 9000, "UI-32": 9000, "UI-33": 9000, "UI-34": 12000, "UI-35": 28000,
        "UI-36": 36000, "UI-37": 36000, "UI-38": 36000, "UI-39": 36000, "UI-40": 36000,
        "UI-41": 36000, "UI-42": 36000, "UI-43": 36000, "UI-44": 9000, "UI-45": 9000,
    }
    for t, cap in vrf_int.items():
        equipos.append(_fila_equipo(t, "VRF - Unidades Interiores",
                                      f"Cassette 4 vias, {cap:,} Btu/h", "lg_vrf"))
    equipos.append(_fila_equipo(
        "UI-46 / UC-07", "VRF - Unidades Interiores",
        "Piso techo / unidad de expansion directa (garita), 12,000 Btu/h", "lg_vrf"))

    equipos.append(_fila_equipo(
        "CR-1", "Unidad de Precision",
        "40,700 Btu/h total, 38,300 Btu/h sensible, 1,900 CFM, 208V-3F-60Hz, "
        "cuarto de servidores", "generico"))

    return equipos


# ---------------------------------------------------------------------------
# SERIALIZACION COMPARTIDA (usada por los 3 backends por igual)
# ---------------------------------------------------------------------------
def serializar_modelo(modelo_id: str, data: dict) -> dict:
    return {
        "modelo_id": modelo_id,
        "nombre": data["nombre"],
        "componentes": data.get("componentes", ""),
        "parametros": data.get("parametros", ""),
        "umbral_dias": data.get("umbral_dias") or calcular_umbral_dias(data.get("preventivo", [])),
        "preventivo_json": json.dumps(data.get("preventivo", []), ensure_ascii=False),
        "correctivo_json": json.dumps(data.get("correctivo", []), ensure_ascii=False),
    }


def parsear_modelo(row: dict) -> dict:
    def _parse(campo):
        val = row.get(campo, "[]")
        if isinstance(val, list):
            return val
        if val is None or (isinstance(val, float) and pd.isna(val)) or val == "":
            return []
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return []
    return {
        "nombre": row.get("nombre", ""),
        "componentes": row.get("componentes", ""),
        "parametros": row.get("parametros", ""),
        "umbral_dias": int(row.get("umbral_dias") or 90),
        "preventivo": _parse("preventivo_json"),
        "correctivo": _parse("correctivo_json"),
    }


def serializar_orden(orden_id, equipos_tags, estado, tecnico_asignado, fecha_creacion=None):
    return {
        "orden_id": orden_id,
        "fecha_creacion": str(fecha_creacion or date.today()),
        "equipos_json": json.dumps(list(equipos_tags), ensure_ascii=False),
        "estado": estado,
        "tecnico_asignado": tecnico_asignado or "",
    }


def parsear_equipos_orden(row: dict) -> list:
    val = row.get("equipos_json", "[]")
    if isinstance(val, list):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return []


def unir_lista(valores) -> str:
    return " | ".join(v for v in valores if v)


def separar_lista(texto) -> list:
    if not texto or (isinstance(texto, float) and pd.isna(texto)):
        return []
    return [v.strip() for v in str(texto).split("|") if v.strip()]


def serializar_checklist(tareas_marcadas: list) -> str:
    """tareas_marcadas: lista de tuplas (tarea_dict, marcado_bool)."""
    return json.dumps(
        [{"frecuencia": t.get("frecuencia", ""), "tarea": t.get("tarea", ""), "marcado": bool(m)}
         for t, m in tareas_marcadas],
        ensure_ascii=False)


def parsear_checklist(texto) -> list:
    """Devuelve una lista de tuplas (tarea_dict, marcado_bool) reconstruida
    desde el JSON guardado, lista para usarse en pdf_utils."""
    if not texto or (isinstance(texto, float) and pd.isna(texto)):
        return []
    try:
        items = json.loads(texto)
    except (json.JSONDecodeError, TypeError):
        return []
    return [({"frecuencia": it.get("frecuencia", ""), "tarea": it.get("tarea", "")},
              it.get("marcado", False)) for it in items]


# ---------------------------------------------------------------------------
# INTERFAZ ABSTRACTA
# ---------------------------------------------------------------------------
class DataStore(ABC):
    nombre_backend = "abstracto"

    # ---- equipos ----
    @abstractmethod
    def get_equipos(self) -> pd.DataFrame: ...

    @abstractmethod
    def upsert_equipo(self, equipo: dict) -> None: ...

    @abstractmethod
    def agregar_equipo(self, equipo: dict) -> None: ...

    @abstractmethod
    def eliminar_equipo(self, tag: str) -> None: ...

    # ---- modelos ----
    @abstractmethod
    def get_modelos(self) -> dict: ...

    @abstractmethod
    def upsert_modelo(self, modelo_id: str, data: dict) -> None: ...

    # ---- ordenes ----
    @abstractmethod
    def get_ordenes(self) -> pd.DataFrame: ...

    @abstractmethod
    def crear_orden(self, orden_id, equipos_tags, tecnico_asignado="") -> None: ...

    @abstractmethod
    def actualizar_orden(self, orden_id: str, campos: dict) -> None: ...

    # ---- reportes ----
    @abstractmethod
    def get_reportes(self) -> pd.DataFrame: ...

    @abstractmethod
    def guardar_reporte(self, reporte: dict) -> None: ...

    # ---- evidencias ----
    @abstractmethod
    def guardar_evidencia(self, orden_id: str, tag: str, filename: str, file_bytes: bytes) -> str: ...


# ---------------------------------------------------------------------------
# BACKEND 1: LOCAL (CSV) - modo desarrollo / respaldo sin nube
# ---------------------------------------------------------------------------
class LocalStore(DataStore):
    nombre_backend = "Local (CSV)"

    def __init__(self, data_dir=DATA_DIR):
        self.data_dir = data_dir
        self.evidencias_dir = os.path.join(data_dir, "evidencias")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.evidencias_dir, exist_ok=True)
        self._paths = {
            "equipos": os.path.join(self.data_dir, "equipos.csv"),
            "modelos": os.path.join(self.data_dir, "modelos.csv"),
            "ordenes": os.path.join(self.data_dir, "ordenes.csv"),
            "reportes": os.path.join(self.data_dir, "reportes.csv"),
        }
        self._sembrar_si_hace_falta()

    def _sembrar_si_hace_falta(self):
        if not os.path.exists(self._paths["equipos"]):
            pd.DataFrame(_equipos_seed(), columns=COLUMNAS_EQUIPOS).to_csv(
                self._paths["equipos"], index=False)
        if not os.path.exists(self._paths["modelos"]):
            filas = [serializar_modelo(mid, data) for mid, data in _modelos_seed().items()]
            pd.DataFrame(filas, columns=COLUMNAS_MODELOS).to_csv(
                self._paths["modelos"], index=False)
        if not os.path.exists(self._paths["ordenes"]):
            pd.DataFrame(columns=COLUMNAS_ORDENES).to_csv(self._paths["ordenes"], index=False)
        if not os.path.exists(self._paths["reportes"]):
            pd.DataFrame(columns=COLUMNAS_REPORTES).to_csv(self._paths["reportes"], index=False)

    def _leer(self, clave, columnas):
        try:
            df = pd.read_csv(self._paths[clave], dtype=str)
        except (pd.errors.EmptyDataError, FileNotFoundError):
            return pd.DataFrame(columns=columnas)
        for c in columnas:
            if c not in df.columns:
                df[c] = ""
        return df.fillna("")

    def _escribir(self, clave, df):
        df.to_csv(self._paths[clave], index=False)

    # ---- equipos ----
    def get_equipos(self) -> pd.DataFrame:
        df = self._leer("equipos", COLUMNAS_EQUIPOS)
        df["tiene_vfd"] = df["tiene_vfd"].astype(str).str.lower().isin(["true", "1", "1.0"])
        return df

    def upsert_equipo(self, equipo: dict) -> None:
        df = self._leer("equipos", COLUMNAS_EQUIPOS)
        df = df[df["tag"] != equipo["tag"]]
        nueva = {c: equipo.get(c, "") for c in COLUMNAS_EQUIPOS}
        df = pd.concat([df, pd.DataFrame([nueva])], ignore_index=True)
        self._escribir("equipos", df)

    def agregar_equipo(self, equipo: dict) -> None:
        self.upsert_equipo(equipo)

    def eliminar_equipo(self, tag: str) -> None:
        df = self._leer("equipos", COLUMNAS_EQUIPOS)
        df = df[df["tag"] != tag]
        self._escribir("equipos", df)

    # ---- modelos ----
    def get_modelos(self) -> dict:
        df = self._leer("modelos", COLUMNAS_MODELOS)
        return {row["modelo_id"]: parsear_modelo(row) for _, row in df.iterrows()}

    def upsert_modelo(self, modelo_id: str, data: dict) -> None:
        df = self._leer("modelos", COLUMNAS_MODELOS)
        df = df[df["modelo_id"] != modelo_id]
        fila = serializar_modelo(modelo_id, data)
        df = pd.concat([df, pd.DataFrame([fila])], ignore_index=True)
        self._escribir("modelos", df)

    # ---- ordenes ----
    def get_ordenes(self) -> pd.DataFrame:
        return self._leer("ordenes", COLUMNAS_ORDENES)

    def crear_orden(self, orden_id, equipos_tags, tecnico_asignado="") -> None:
        df = self._leer("ordenes", COLUMNAS_ORDENES)
        fila = serializar_orden(orden_id, equipos_tags, "Abierta", tecnico_asignado)
        df = pd.concat([df, pd.DataFrame([fila])], ignore_index=True)
        self._escribir("ordenes", df)

    def actualizar_orden(self, orden_id: str, campos: dict) -> None:
        df = self._leer("ordenes", COLUMNAS_ORDENES)
        for k, v in campos.items():
            df.loc[df["orden_id"] == orden_id, k] = v
        self._escribir("ordenes", df)

    # ---- reportes ----
    def get_reportes(self) -> pd.DataFrame:
        return self._leer("reportes", COLUMNAS_REPORTES)

    def guardar_reporte(self, reporte: dict) -> None:
        df = self._leer("reportes", COLUMNAS_REPORTES)
        fila = {c: reporte.get(c, "") for c in COLUMNAS_REPORTES}
        df = pd.concat([df, pd.DataFrame([fila])], ignore_index=True)
        self._escribir("reportes", df)

    # ---- evidencias ----
    def guardar_evidencia(self, orden_id: str, tag: str, filename: str, file_bytes: bytes) -> str:
        carpeta = os.path.join(self.evidencias_dir, orden_id)
        os.makedirs(carpeta, exist_ok=True)
        tag_limpio = tag.replace(" ", "").replace("/", "-")
        ruta = os.path.join(carpeta, f"{tag_limpio}_{filename}")
        with open(ruta, "wb") as f:
            f.write(file_bytes)
        return ruta


# ---------------------------------------------------------------------------
# BACKEND 2: SUPABASE (Postgres + Storage) - recomendado para nube
# ---------------------------------------------------------------------------
class SupabaseStore(DataStore):
    nombre_backend = "Supabase (nube)"
    BUCKET_EVIDENCIAS = "evidencias"

    def __init__(self, url: str, key: str):
        from supabase import create_client
        self.client = create_client(url, key)
        self._sembrar_si_hace_falta()

    def _tabla(self, nombre):
        return self.client.table(nombre)

    def _sembrar_si_hace_falta(self):
        try:
            existentes = self._tabla("equipos").select("tag").execute().data
        except Exception as e:
            raise RuntimeError(
                "No se pudo leer la tabla 'equipos' en Supabase. Verifica que hayas "
                "ejecutado el script SQL de configuracion inicial (ver guia). "
                f"Detalle: {e}"
            ) from e
        if not existentes:
            self._tabla("equipos").insert(_equipos_seed()).execute()
        existentes_modelos = self._tabla("modelos").select("modelo_id").execute().data
        if not existentes_modelos:
            filas = [serializar_modelo(mid, data) for mid, data in _modelos_seed().items()]
            self._tabla("modelos").insert(filas).execute()

    # ---- equipos ----
    def get_equipos(self) -> pd.DataFrame:
        data = self._tabla("equipos").select("*").execute().data
        df = pd.DataFrame(data, columns=COLUMNAS_EQUIPOS) if data else pd.DataFrame(columns=COLUMNAS_EQUIPOS)
        if not df.empty:
            df["tiene_vfd"] = df["tiene_vfd"].astype(bool)
        return df.fillna("")

    def upsert_equipo(self, equipo: dict) -> None:
        fila = {c: equipo.get(c, "") for c in COLUMNAS_EQUIPOS}
        self._tabla("equipos").upsert(fila, on_conflict="tag").execute()

    def agregar_equipo(self, equipo: dict) -> None:
        self.upsert_equipo(equipo)

    def eliminar_equipo(self, tag: str) -> None:
        self._tabla("equipos").delete().eq("tag", tag).execute()

    # ---- modelos ----
    def get_modelos(self) -> dict:
        data = self._tabla("modelos").select("*").execute().data
        return {row["modelo_id"]: parsear_modelo(row) for row in data}

    def upsert_modelo(self, modelo_id: str, data: dict) -> None:
        fila = serializar_modelo(modelo_id, data)
        self._tabla("modelos").upsert(fila, on_conflict="modelo_id").execute()

    # ---- ordenes ----
    def get_ordenes(self) -> pd.DataFrame:
        data = self._tabla("ordenes").select("*").execute().data
        return pd.DataFrame(data, columns=COLUMNAS_ORDENES) if data else pd.DataFrame(columns=COLUMNAS_ORDENES)

    def crear_orden(self, orden_id, equipos_tags, tecnico_asignado="") -> None:
        fila = serializar_orden(orden_id, equipos_tags, "Abierta", tecnico_asignado)
        self._tabla("ordenes").insert(fila).execute()

    def actualizar_orden(self, orden_id: str, campos: dict) -> None:
        self._tabla("ordenes").update(campos).eq("orden_id", orden_id).execute()

    # ---- reportes ----
    def get_reportes(self) -> pd.DataFrame:
        data = self._tabla("reportes").select("*").execute().data
        return pd.DataFrame(data, columns=COLUMNAS_REPORTES) if data else pd.DataFrame(columns=COLUMNAS_REPORTES)

    def guardar_reporte(self, reporte: dict) -> None:
        fila = {c: reporte.get(c, "") for c in COLUMNAS_REPORTES}
        self._tabla("reportes").insert(fila).execute()

    # ---- evidencias ----
    def guardar_evidencia(self, orden_id: str, tag: str, filename: str, file_bytes: bytes) -> str:
        tag_limpio = tag.replace(" ", "").replace("/", "-")
        ruta = f"{orden_id}/{tag_limpio}_{filename}"
        content_type = "image/png" if filename.lower().endswith("png") else "image/jpeg"
        self.client.storage.from_(self.BUCKET_EVIDENCIAS).upload(
            ruta, file_bytes, {"content-type": content_type, "upsert": "true"})
        return self.client.storage.from_(self.BUCKET_EVIDENCIAS).get_public_url(ruta)


# ---------------------------------------------------------------------------
# BACKEND 3: GOOGLE SHEETS - via st.connection("gsheets")
# ---------------------------------------------------------------------------
class GSheetsStore(DataStore):
    nombre_backend = "Google Sheets (nube)"

    def __init__(self, conn):
        """`conn` es el objeto devuelto por st.connection('gsheets', type=GSheetsConnection)."""
        self.conn = conn
        self._sembrar_si_hace_falta()

    def _leer_hoja(self, nombre, columnas):
        try:
            df = self.conn.read(worksheet=nombre, ttl=0)
        except Exception:
            return pd.DataFrame(columns=columnas)
        if df is None or df.empty:
            return pd.DataFrame(columns=columnas)
        df = df.dropna(how="all")
        for c in columnas:
            if c not in df.columns:
                df[c] = ""
        return df.fillna("")

    def _escribir_hoja(self, nombre, df, columnas):
        df_final = df.reindex(columns=columnas).fillna("")
        try:
            self.conn.update(worksheet=nombre, data=df_final)
        except Exception:
            self.conn.create(worksheet=nombre, data=df_final)

    def _sembrar_si_hace_falta(self):
        equipos = self._leer_hoja("Equipos", COLUMNAS_EQUIPOS)
        if equipos.empty:
            self._escribir_hoja("Equipos", pd.DataFrame(_equipos_seed()), COLUMNAS_EQUIPOS)
        modelos = self._leer_hoja("Modelos", COLUMNAS_MODELOS)
        if modelos.empty:
            filas = [serializar_modelo(mid, data) for mid, data in _modelos_seed().items()]
            self._escribir_hoja("Modelos", pd.DataFrame(filas), COLUMNAS_MODELOS)

    # ---- equipos ----
    def get_equipos(self) -> pd.DataFrame:
        df = self._leer_hoja("Equipos", COLUMNAS_EQUIPOS)
        if not df.empty:
            df["tiene_vfd"] = df["tiene_vfd"].astype(str).str.lower().isin(["true", "1", "1.0"])
        return df

    def upsert_equipo(self, equipo: dict) -> None:
        df = self._leer_hoja("Equipos", COLUMNAS_EQUIPOS)
        df = df[df["tag"] != equipo["tag"]]
        nueva = {c: equipo.get(c, "") for c in COLUMNAS_EQUIPOS}
        df = pd.concat([df, pd.DataFrame([nueva])], ignore_index=True)
        self._escribir_hoja("Equipos", df, COLUMNAS_EQUIPOS)

    def agregar_equipo(self, equipo: dict) -> None:
        self.upsert_equipo(equipo)

    def eliminar_equipo(self, tag: str) -> None:
        df = self._leer_hoja("Equipos", COLUMNAS_EQUIPOS)
        df = df[df["tag"] != tag]
        self._escribir_hoja("Equipos", df, COLUMNAS_EQUIPOS)

    # ---- modelos ----
    def get_modelos(self) -> dict:
        df = self._leer_hoja("Modelos", COLUMNAS_MODELOS)
        return {row["modelo_id"]: parsear_modelo(row) for _, row in df.iterrows()}

    def upsert_modelo(self, modelo_id: str, data: dict) -> None:
        df = self._leer_hoja("Modelos", COLUMNAS_MODELOS)
        df = df[df["modelo_id"] != modelo_id]
        fila = serializar_modelo(modelo_id, data)
        df = pd.concat([df, pd.DataFrame([fila])], ignore_index=True)
        self._escribir_hoja("Modelos", df, COLUMNAS_MODELOS)

    # ---- ordenes ----
    def get_ordenes(self) -> pd.DataFrame:
        return self._leer_hoja("Ordenes", COLUMNAS_ORDENES)

    def crear_orden(self, orden_id, equipos_tags, tecnico_asignado="") -> None:
        df = self._leer_hoja("Ordenes", COLUMNAS_ORDENES)
        fila = serializar_orden(orden_id, equipos_tags, "Abierta", tecnico_asignado)
        df = pd.concat([df, pd.DataFrame([fila])], ignore_index=True)
        self._escribir_hoja("Ordenes", df, COLUMNAS_ORDENES)

    def actualizar_orden(self, orden_id: str, campos: dict) -> None:
        df = self._leer_hoja("Ordenes", COLUMNAS_ORDENES)
        for k, v in campos.items():
            df.loc[df["orden_id"] == orden_id, k] = v
        self._escribir_hoja("Ordenes", df, COLUMNAS_ORDENES)

    # ---- reportes ----
    def get_reportes(self) -> pd.DataFrame:
        return self._leer_hoja("Reportes", COLUMNAS_REPORTES)

    def guardar_reporte(self, reporte: dict) -> None:
        df = self._leer_hoja("Reportes", COLUMNAS_REPORTES)
        fila = {c: reporte.get(c, "") for c in COLUMNAS_REPORTES}
        df = pd.concat([df, pd.DataFrame([fila])], ignore_index=True)
        self._escribir_hoja("Reportes", df, COLUMNAS_REPORTES)

    # ---- evidencias ----
    def guardar_evidencia(self, orden_id: str, tag: str, filename: str, file_bytes: bytes) -> str:
        # Google Sheets no puede almacenar binarios. Se guarda localmente como
        # respaldo y se deja constancia de la limitacion (ver guia: usar Supabase
        # Storage o Google Drive API para persistencia real de fotos en la nube).
        carpeta = os.path.join(EVIDENCIAS_DIR, orden_id)
        os.makedirs(carpeta, exist_ok=True)
        tag_limpio = tag.replace(" ", "").replace("/", "-")
        ruta = os.path.join(carpeta, f"{tag_limpio}_{filename}")
        with open(ruta, "wb") as f:
            f.write(file_bytes)
        return ruta


# ---------------------------------------------------------------------------
# FABRICA: elige el backend segun st.secrets, sin que el resto de la app
# tenga que saberlo.
# ---------------------------------------------------------------------------
def _tiene_secreto(st, *claves):
    """st.secrets lanza excepcion si no existe NINGUN archivo secrets.toml
    (no solo devuelve un dict vacio), por lo que cada verificacion debe
    protegerse individualmente."""
    try:
        nodo = st.secrets
        for clave in claves:
            if clave not in nodo:
                return False
            nodo = nodo[clave]
        return True
    except Exception:
        return False


def diagnosticar_secretos() -> dict:
    """
    Verifica el estado de la configuracion de nube (Supabase / Google
    Sheets) en st.secrets, para poder mostrar en la barra lateral EXACTAMENTE
    por que se esta usando cada backend, en vez de que la app se quede en
    modo Local sin explicar la causa (archivo no encontrado, mal ubicado,
    con error de formato TOML, seccion incompleta, etc.). Se ejecuta en
    cada rerun (no se cachea) para reflejar el estado real del archivo.

    Devuelve un dict: {"modo": ..., "detalle": ...}
    modo puede ser: "sin_secrets", "error_lectura", "supabase_incompleto",
    "supabase_ok", "gsheets_ok", "sin_configuracion_de_nube"
    """
    import streamlit as st
    from streamlit.errors import StreamlitSecretNotFoundError

    # IMPORTANTE: `st.secrets` en si mismo no lanza excepcion al accederlo
    # (es un objeto perezoso) - el error de "no existe secrets.toml" solo
    # aparece cuando de verdad se intenta LEER su contenido (ej. .keys(),
    # "x" in st.secrets). Por eso ambos pasos van en el MISMO try/except:
    # separarlos hacia que el caso "no hay archivo" se confundiera con un
    # error de formato.
    try:
        secretos = st.secrets
        claves_raiz = list(secretos.keys())
    except StreamlitSecretNotFoundError as e:
        # OJO: Streamlit usa esta MISMA clase de excepcion tanto para "no
        # existe ningun archivo secrets.toml" como para "el archivo existe
        # pero tiene un error de sintaxis TOML" - solo el mensaje cambia
        # ("Error parsing secrets file..." en el segundo caso). Hay que
        # distinguirlos por el texto, o un typo en el archivo se reportaria
        # como si la nube simplemente no estuviera configurada.
        if "error parsing secrets file" in str(e).lower():
            return {"modo": "error_lectura",
                    "detalle": f"Se encontro un archivo secrets.toml pero tiene un error de "
                                f"formato TOML y no se pudo leer: {e}. Revisa comillas, "
                                f"corchetes ([supabase]) y que no se hayan pegado caracteres "
                                f"extra al copiar."}
        return {"modo": "sin_secrets",
                "detalle": f"No se encontro ningun archivo secrets.toml (esto es normal si "
                            f"todavia no configuraste la nube). Detalle tecnico: {e}"}
    except Exception as e:
        return {"modo": "error_lectura",
                "detalle": f"Se encontro un archivo secrets.toml pero no se pudo leer: {e}. "
                            f"Revisa que el formato TOML este bien escrito (comillas, corchetes "
                            f"[supabase], sin caracteres raros al copiar y pegar)."}

    if "supabase" in claves_raiz:
        seccion = secretos.get("supabase", {})
        faltantes = [c for c in ("url", "key") if c not in seccion]
        if faltantes:
            return {"modo": "supabase_incompleto",
                    "detalle": f"El archivo secrets.toml tiene la seccion [supabase], pero le "
                                f"falta(n): {', '.join(faltantes)}. Revisa que ambas lineas "
                                f"('url' y 'key') esten escritas dentro de esa seccion."}
        return {"modo": "supabase_ok", "detalle": ""}

    if "connections" in claves_raiz and "gsheets" in secretos.get("connections", {}):
        return {"modo": "gsheets_ok", "detalle": ""}

    return {"modo": "sin_configuracion_de_nube",
            "detalle": f"El archivo secrets.toml se encontro y se pudo leer, pero no tiene una "
                        f"seccion [supabase] ni [connections.gsheets]. Secciones encontradas en "
                        f"el archivo: {', '.join(claves_raiz) if claves_raiz else '(el archivo esta vacio)'}."}


def get_store():
    import streamlit as st

    @st.cache_resource(show_spinner="Conectando a la fuente de datos...")
    def _construir_store():
        """Devuelve (store, mensaje_error_o_None). IMPORTANTE: esta funcion
        esta cacheada (@st.cache_resource), asi que solo se ejecuta UNA VEZ
        por proceso. Por eso NO llama a st.error() aqui directamente: un
        st.error() dentro de una funcion cacheada solo se veria en el primer
        rerun y luego desaparecería en los siguientes, aunque el problema
        siga sin resolverse. El mensaje de error se devuelve como dato y se
        muestra fuera de la funcion cacheada (ver mas abajo), para que sea
        visible en TODOS los reruns mientras el problema persista."""

        if _tiene_secreto(st, "supabase"):
            try:
                url = st.secrets["supabase"]["url"]
                key = st.secrets["supabase"]["key"]
                return SupabaseStore(url, key), None
            except Exception as e:
                return LocalStore(), f"No se pudo conectar a Supabase con las credenciales dadas: {e}"

        if _tiene_secreto(st, "connections", "gsheets"):
            try:
                from streamlit_gsheets import GSheetsConnection
                conn = st.connection("gsheets", type=GSheetsConnection)
                return GSheetsStore(conn), None
            except Exception as e:
                return LocalStore(), f"No se pudo conectar a Google Sheets con las credenciales dadas: {e}"

        return LocalStore(), None

    store, error_conexion = _construir_store()
    if error_conexion:
        st.error(f"⚠️ {error_conexion}\n\nSe esta usando almacenamiento Local (CSV) mientras "
                  f"tanto, para que la app siga funcionando.")
    return store
