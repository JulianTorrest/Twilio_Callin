import streamlit as st
import pandas as pd
from twilio.rest import Client
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import urllib.parse
import plotly.express as px

# --- CONFIGURACION DE PAGINA ---
st.set_page_config(page_title="Camacol Dialer Pro v4.5 - Enhanced", layout="wide")

st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 10px; border-radius: 10px; border: 1px solid #e1e4e8; }
    .client-card { background-color: #f0f2f6; padding: 15px; border-radius: 15px; border-left: 8px solid #003366; margin-bottom: 15px; }
    .log-box { font-family: monospace; font-size: 0.8rem; background: #1e1e1e; color: #4af626; padding: 10px; border-radius: 5px; height: 180px; overflow-y: auto; }
    .latency-green { height: 10px; width: 10px; background-color: #28a745; border-radius: 50%; display: inline-block; }
    .latency-red { height: 10px; width: 10px; background-color: #dc3545; border-radius: 50%; display: inline-block; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. CONEXIONES ---
try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets.get("TWILIO_NUMBER", "+17068069672")
    function_url = st.secrets["TWILIO_FUNCTION_URL"]
    forms_base_url = st.secrets.get("MS_FORMS_URL", "https://forms.office.com/r/tu_codigo")
    URL_SHEET_INFORME = st.secrets.get("GSHEET_URL")
    URL_SHEET_CONTACTOS = st.secrets.get("GSHEET_CONTACTOS_URL")
    GDRIVE_LOGS_FOLDER_ID = st.secrets.get("GDRIVE_LOGS_FOLDER_ID")
    CEDULAS_AUTORIZADAS = ["1121871773", "87654321", "12345678"]
    
    # Mapeo de números celulares de agentes para Hybrid Click-to-Call
    NUMEROS_CELULAR_AGENTES = dict(st.secrets.get("numeros_celular_agentes", {}))
    
    client = Client(account_sid, auth_token)
    
    # Conexión a Google Sheets usando gspread con Service Account
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    gc = gspread.authorize(creds)
    
    # Extraer IDs de los sheets (NO abrirlos todavía para evitar rate limit)
    sheet_id_informe = URL_SHEET_INFORME.split('/d/')[1].split('/')[0]
    sheet_id_contactos = URL_SHEET_CONTACTOS.split('/d/')[1].split('/')[0]
except Exception as e:
    st.error(f"Error de configuración: {e}")
    st.stop()

# --- SISTEMA DE RATE LIMITING PARA GOOGLE SHEETS API ---
class RateLimiter:
    """Control de rate limiting para Google Sheets API
    
    Límites de Google Sheets API:
    - 100 requests por 100 segundos por usuario
    - ~60 escrituras por minuto
    
    Este sistema monitorea las operaciones y agrega delays automáticos
    cuando se acerca al 90% del límite.
    """
    def __init__(self, max_requests_per_minute=50, warning_threshold=0.9):
        self.max_requests = max_requests_per_minute
        self.warning_threshold = warning_threshold
        self.request_times = []
        self.warning_shown = False
    
    def check_and_wait(self, operation_type="read"):
        """Verifica el rate limit y espera si es necesario
        
        Args:
            operation_type: 'read' o 'write'
        """
        now = time.time()
        
        # Limpiar requests antiguos (más de 60 segundos)
        self.request_times = [t for t in self.request_times if now - t < 60]
        
        # Calcular uso actual
        current_usage = len(self.request_times)
        usage_percentage = current_usage / self.max_requests
        
        # Si estamos al 90% o más del límite
        if usage_percentage >= self.warning_threshold:
            wait_time = 3  # Esperar 3 segundos
            if not self.warning_shown:
                print(f"[RATE LIMIT] ⚠️ Uso al {usage_percentage*100:.1f}% ({current_usage}/{self.max_requests})")
                print(f"[RATE LIMIT] Aplicando delay de {wait_time}s para evitar quota exceeded")
                self.warning_shown = True
            time.sleep(wait_time)
        elif usage_percentage >= 0.7:  # Al 70% empezar a reducir velocidad
            time.sleep(1)
            self.warning_shown = False
        else:
            self.warning_shown = False
        
        # Registrar esta operación
        self.request_times.append(now)
        
        # Log de debug
        if current_usage % 10 == 0 and current_usage > 0:
            print(f"[RATE LIMIT] Operaciones en último minuto: {current_usage}/{self.max_requests}")
    
    def reset(self):
        """Resetear el contador"""
        self.request_times = []
        self.warning_shown = False

# Inicializar rate limiter global con límite más conservador
if 'rate_limiter' not in st.session_state:
    st.session_state.rate_limiter = RateLimiter(max_requests_per_minute=30, warning_threshold=0.8)

rate_limiter = st.session_state.rate_limiter

# --- FUNCIONES LAZY LOADING PARA SPREADSHEETS ---
def get_spreadsheet_informe():
    """Abre el spreadsheet de Informe con lazy loading y caché"""
    if 'spreadsheet_informe' not in st.session_state:
        rate_limiter.check_and_wait(operation_type="read")
        st.session_state.spreadsheet_informe = gc.open_by_key(sheet_id_informe)
        print(f"[DEBUG] Spreadsheet Informe abierto: {sheet_id_informe}")
    return st.session_state.spreadsheet_informe

def get_spreadsheet_contactos():
    """Abre el spreadsheet de Contactos con lazy loading y caché"""
    if 'spreadsheet_contactos' not in st.session_state:
        rate_limiter.check_and_wait(operation_type="read")
        st.session_state.spreadsheet_contactos = gc.open_by_key(sheet_id_contactos)
        print(f"[DEBUG] Spreadsheet Contactos abierto: {sheet_id_contactos}")
    return st.session_state.spreadsheet_contactos

# --- 2. FUNCIONES HELPER PARA GOOGLE SHEETS ---
def read_sheet(worksheet_name="0"):
    """Lee datos de Google Sheets usando gspread"""
    try:
        rate_limiter.check_and_wait(operation_type="read")
        spreadsheet = get_spreadsheet_informe()
        worksheet = spreadsheet.get_worksheet(int(worksheet_name)) if worksheet_name.isdigit() else spreadsheet.worksheet(worksheet_name)
        data = worksheet.get_all_values()
        if len(data) > 0:
            return pd.DataFrame(data[1:], columns=data[0])
        return pd.DataFrame()
    except Exception as e:
        print(f"Error leyendo sheet: {e}")
        return pd.DataFrame()

def update_sheet(df, worksheet_name="0", sheet_url=None):
    """Escribe datos a Google Sheets usando gspread
    
    Args:
        df: DataFrame a escribir
        worksheet_name: Nombre o índice del worksheet (default "0")
        sheet_url: URL del Google Sheet (opcional, usa spreadsheet por defecto)
    """
    try:
        # Verificar rate limit antes de escribir
        rate_limiter.check_and_wait(operation_type="write")
        
        # Determinar qué spreadsheet usar
        if sheet_url:
            # Abrir el spreadsheet específico desde la URL
            rate_limiter.check_and_wait(operation_type="read")
            target_spreadsheet = gc.open_by_url(sheet_url)
        else:
            # Usar el spreadsheet por defecto (Informe)
            target_spreadsheet = get_spreadsheet_informe()
        
        # Obtener el worksheet
        worksheet = target_spreadsheet.get_worksheet(int(worksheet_name)) if worksheet_name.isdigit() else target_spreadsheet.worksheet(worksheet_name)
        
        # Limpiar y actualizar (estas son 2 operaciones)
        rate_limiter.check_and_wait(operation_type="write")
        worksheet.clear()
        rate_limiter.check_and_wait(operation_type="write")
        worksheet.update([df.columns.values.tolist()] + df.values.tolist())
        return True
    except Exception as e:
        print(f"Error escribiendo sheet: {e}")
        import traceback
        print(traceback.format_exc())
        return False

def cargar_contactos_agente(cedula_agente):
    """Carga contactos desde Google Sheets filtrados por cedula_agente"""
    try:
        # Leer todos los contactos del Sheet con rate limiting
        rate_limiter.check_and_wait(operation_type="read")
        spreadsheet_contactos = get_spreadsheet_contactos()
        worksheet = spreadsheet_contactos.get_worksheet(0)
        data = worksheet.get_all_values()
        
        # Crear DataFrame vacío con columnas necesarias
        columnas_requeridas = ['nombre', 'codigo_pais', 'telefono', 'cedula_agente', 'estado', 'observacion', 
                              'fecha_llamada', 'duracion_seg', 'sid_llamada', 'proxima_llamada', 'agente_id']
        
        if len(data) <= 1:
            print(f"[DEBUG] Sheet de contactos vacío o solo tiene encabezados")
            # Retornar DataFrame vacío pero con las columnas necesarias
            return pd.DataFrame(columns=columnas_requeridas)
        
        # Crear DataFrame con los datos del sheet
        df_todos = pd.DataFrame(data[1:], columns=data[0])
        print(f"[DEBUG] Total contactos en sheet: {len(df_todos)}")
        
        # Verificar que existe la columna cedula_agente
        if 'cedula_agente' not in df_todos.columns:
            print(f"[ERROR] El sheet no tiene la columna 'cedula_agente'")
            return pd.DataFrame(columns=columnas_requeridas)
        
        # Filtrar por cedula_agente
        df_agente = df_todos[df_todos['cedula_agente'].astype(str) == str(cedula_agente)].copy()
        print(f"[DEBUG] Contactos para agente {cedula_agente}: {len(df_agente)}")
        
        if df_agente.empty:
            print(f"[DEBUG] No hay contactos asignados al agente {cedula_agente}")
            return pd.DataFrame(columns=columnas_requeridas)
        
        # Agregar columnas necesarias para el sistema si no existen
        for col in ['estado', 'observacion', 'fecha_llamada', 'duracion_seg', 'sid_llamada', 'proxima_llamada', 'agente_id']:
            if col not in df_agente.columns:
                df_agente[col] = ''
        
        # Si el campo estado está vacío, asignar 'Pendiente' para el filtro de la UI
        # Esto permite que contactos sin gestionar aparezcan en "Pendientes"
        df_agente['estado'] = df_agente['estado'].fillna('').replace('', 'Pendiente')
        
        # Asignar agente_id
        df_agente['agente_id'] = cedula_agente
        
        return df_agente
    except Exception as e:
        print(f"[ERROR] Error cargando contactos: {e}")
        import traceback
        print(traceback.format_exc())
        # Retornar DataFrame vacío con columnas en caso de error
        columnas_requeridas = ['nombre', 'codigo_pais', 'telefono', 'cedula_agente', 'estado', 'observacion', 
                              'fecha_llamada', 'duracion_seg', 'sid_llamada', 'proxima_llamada', 'agente_id']
        return pd.DataFrame(columns=columnas_requeridas)

def guardar_en_sheet_informe(contacto, telefono, estado, nota, duracion_seg, sid_llamada=''):
    """Guarda un registro en el Sheet Informe
    
    Args:
        contacto: Diccionario con datos del contacto
        telefono: Número de teléfono
        estado: Estado de la llamada ('Llamado', 'No Contesto', etc.)
        nota: Observaciones del agente
        duracion_seg: Duración en segundos
        sid_llamada: SID de la llamada de Twilio (opcional)
    
    Returns:
        bool: True si se guardó exitosamente, False en caso contrario
    """
    try:
        t_fin = datetime.now()
        
        # Preparar fila para Sheet Informe
        fila_informe = pd.DataFrame({
            'agente_id': [st.session_state.agente_id],
            'nombre': [contacto['nombre']],
            'telefono': [telefono],
            'estado': [estado],
            'observacion': [nota],
            'duracion_seg': [duracion_seg],
            'fecha_llamada': [t_fin.strftime("%Y-%m-%d %H:%M:%S")],
            'sid_llamada': [sid_llamada],
            'url_grabacion': [''],
            'precio_llamada': ['0'],
            'duracion_facturada': ['0'],
            'estado_respuesta': ['paused' if estado == 'Grabación Pausada' else 'unknown'],
            'codigo_error': ['']
        })
        
        # Leer Sheet Informe actual (con caché)
        if 'df_informe_cache' not in st.session_state or st.session_state.get('informe_cache_time', 0) < time.time() - 30:
            df_informe_actual = read_sheet("0")
            st.session_state.df_informe_cache = df_informe_actual
            st.session_state.informe_cache_time = time.time()
        else:
            df_informe_actual = st.session_state.df_informe_cache
        
        # Agregar nuevo registro
        if df_informe_actual.empty:
            df_informe_actualizado = fila_informe.copy()
        else:
            df_informe_actualizado = pd.concat([df_informe_actual, fila_informe], ignore_index=True)
        
        # Guardar en Sheet Informe
        if update_sheet(df_informe_actualizado, "0"):
            # Actualizar caché
            st.session_state.df_informe_cache = df_informe_actualizado
            st.session_state.informe_cache_time = time.time()
            return True
        return False
    except Exception as e:
        print(f"[ERROR] Error guardando en Sheet Informe: {e}")
        return False

def guardar_logs_en_drive():
    """Guarda los logs en un archivo de texto en Google Drive"""
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaInMemoryUpload
        from io import BytesIO
        
        # Crear contenido del log
        log_content = "\n".join(st.session_state.logs)
        
        # Crear nombre de archivo con timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"log_agente_{st.session_state.agente_id}_{timestamp}.txt"
        
        # Construir servicio de Drive
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Crear metadata del archivo
        file_metadata = {
            'name': filename,
            'parents': [GDRIVE_LOGS_FOLDER_ID]
        }
        
        # Crear media upload
        media = MediaInMemoryUpload(
            log_content.encode('utf-8'),
            mimetype='text/plain',
            resumable=True
        )
        
        # Subir archivo
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, webViewLink'
        ).execute()
        
        print(f"[DEBUG] Logs guardados en Drive: {file.get('name')} (ID: {file.get('id')})")
        print(f"[DEBUG] Link: {file.get('webViewLink')}")
        return True
    except Exception as e:
        print(f"[ERROR] Error guardando logs en Drive: {e}")
        import traceback
        print(traceback.format_exc())
        return False

# --- 3. AUDITORIA AUTOMATICA ---
if 'logs' not in st.session_state: st.session_state.logs = []

def add_log(mensaje, tipo="INFO"):
    t_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{t_stamp} | {st.session_state.get('agente_id', 'SYS')} | {tipo} | {mensaje}"
    st.session_state.logs.append(entry)
    # Imprimir en consola de Streamlit Cloud para debugging
    print(f"[LOG] {entry}")

# --- 3. CONTROL DE ACCESO Y ESTADO ---
if 'agente_id' not in st.session_state:
    with st.form("login"):
        ced = st.text_input("Cédula:", type="password").strip()
        if st.form_submit_button("Entrar"):
            if ced in CEDULAS_AUTORIZADAS:
                # Obtener número celular del agente desde secrets
                numero_celular = NUMEROS_CELULAR_AGENTES.get(ced)
                
                if not numero_celular:
                    st.error(f"⚠️ No se encontró número celular configurado para la cédula {ced}. Contacta al administrador.")
                    st.stop()
                
                st.session_state.agente_id = ced
                st.session_state.numero_celular_agente = numero_celular
                add_log(f"LOGIN_EXITOSO - Número: {numero_celular}", "AUTH")
                
                # Cargar contactos automáticamente al iniciar sesión
                with st.spinner("Cargando tus contactos asignados..."):
                    st.session_state.df_contactos = cargar_contactos_agente(ced)
                    if not st.session_state.df_contactos.empty:
                        add_log(f"CONTACTOS_CARGADOS: {len(st.session_state.df_contactos)} contactos", "DATA")
                    else:
                        add_log("SIN_CONTACTOS_ASIGNADOS", "DATA")
                st.rerun()
    st.stop()

# Inicialización explícita de estados (Mantenemos cada uno de tus estados)
if 'df_contactos' not in st.session_state: st.session_state.df_contactos = None
if 'en_pausa' not in st.session_state: st.session_state.en_pausa = False
if 'draft_notas' not in st.session_state: st.session_state.draft_notas = {}
if 'meta_diaria' not in st.session_state: st.session_state.meta_diaria = 50
if 'llamada_activa_sid' not in st.session_state: st.session_state.llamada_activa_sid = None
if 't_inicio_dt' not in st.session_state: st.session_state.t_inicio_dt = None
if 'grabacion_pausada' not in st.session_state: st.session_state.grabacion_pausada = False
if 'pagina_actual' not in st.session_state: st.session_state.pagina_actual = 0
if 'numero_celular_agente' not in st.session_state: st.session_state.numero_celular_agente = None
if 'webrtc_activo' not in st.session_state: st.session_state.webrtc_activo = False
if 'webrtc_numero' not in st.session_state: st.session_state.webrtc_numero = None
if 'webrtc_nombre' not in st.session_state: st.session_state.webrtc_nombre = None
if 'webrtc_call_sid' not in st.session_state: st.session_state.webrtc_call_sid = None

# --- 4. SIDEBAR (FUNCIONALIDADES COMPLETAS) ---
with st.sidebar:
    st.header(f"Agente: {st.session_state.agente_id}")
    if st.session_state.numero_celular_agente:
        st.caption(f"📱 Celular: {st.session_state.numero_celular_agente}")
    
    if not st.session_state.en_pausa:
        if st.button("☕ Iniciar Pausa"):
            st.session_state.en_pausa = True
            st.session_state.pausa_inicio = datetime.now()
            add_log("INICIO_PAUSA", "ESTADO")
            st.rerun()
    else:
        st.warning("EN PAUSA")
        if st.button("✅ Volver"):
            st.session_state.en_pausa = False
            add_log("FIN_PAUSA", "ESTADO")
            st.rerun()

    st.divider()
    # Botón para recargar contactos desde Google Sheets
    if st.button("🔄 Recargar Contactos"):
        with st.spinner("Recargando contactos..."):
            st.session_state.df_contactos = cargar_contactos_agente(st.session_state.agente_id)
            if not st.session_state.df_contactos.empty:
                add_log(f"CONTACTOS_RECARGADOS: {len(st.session_state.df_contactos)} contactos", "DATA")
                st.success(f"✅ {len(st.session_state.df_contactos)} contactos cargados")
            else:
                st.warning("⚠️ No hay contactos asignados a tu cédula")
            time.sleep(1)
            st.rerun()

    if st.session_state.df_contactos is not None and not st.session_state.df_contactos.empty and 'estado' in st.session_state.df_contactos.columns:
        df_pend = st.session_state.df_contactos[st.session_state.df_contactos['estado'].isin(['Pendiente', 'No Contesto'])]
        st.download_button("📥 Descargar Pendientes", df_pend.to_csv(index=False).encode('utf-8-sig'), "pendientes.csv")

    # Botón para guardar logs
    if st.button("💾 Guardar Logs"):
        if guardar_logs_en_drive():
            st.success("✅ Logs guardados en Drive")
        else:
            st.error("❌ Error guardando logs")
    
    if st.button("Cerrar Sesión"):
        # Guardar logs deshabilitado para evitar quota de Drive
        # Si necesitas guardar logs, usa el botón "💾 Guardar Logs" antes de cerrar sesión
        add_log("LOGOUT", "AUTH")
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()

# --- 5. MODULO DE METRICAS Y DASHBOARDS ---
st.title("Dialer Pro Camacol")

# --- CONTADORES Y BARRAS DE PROGRESO ---
if st.session_state.df_contactos is not None:
    df = st.session_state.df_contactos
    
    # Contadores por categoría
    col1, col2, col3, col4 = st.columns(4)
    total_pendientes = len(df[df['estado'] == 'Pendiente'])
    total_no_contestaron = len(df[df['estado'] == 'No Contesto'])
    total_programadas = len(df[df['estado'] == 'Programada'])
    total_llamados = len(df[df['estado'] == 'Llamado'])
    
    col1.metric("⏳ Pendientes", total_pendientes)
    col2.metric("📵 No Contestaron", total_no_contestaron)
    col3.metric("📅 Programadas", total_programadas)
    col4.metric("✅ Llamados", total_llamados)
    
    # Barras de progreso
    st.divider()
    prog_col1, prog_col2 = st.columns([3, 1])
    
    with prog_col1:
        # Barra de progreso total
        total_contactos = len(df)
        total_gestionados = total_llamados + total_no_contestaron
        progreso_total = (total_gestionados / total_contactos * 100) if total_contactos > 0 else 0
        st.write(f"**Progreso Total: {total_gestionados}/{total_contactos} ({progreso_total:.1f}%)**")
        st.progress(progreso_total / 100)
        
        # Barra de progreso diario
        if 'meta_diaria' not in st.session_state:
            st.session_state.meta_diaria = 50
        
        # Contar llamadas del día actual
        hoy = datetime.now().strftime("%Y-%m-%d")
        llamadas_hoy = len(df[(df['fecha_llamada'].astype(str).str.contains(hoy, na=False))])
        progreso_diario = (llamadas_hoy / st.session_state.meta_diaria * 100) if st.session_state.meta_diaria > 0 else 0
        st.write(f"**Progreso Diario: {llamadas_hoy}/{st.session_state.meta_diaria} ({progreso_diario:.1f}%)**")
        st.progress(min(progreso_diario / 100, 1.0))
    
    with prog_col2:
        st.write("**Meta Diaria**")
        nueva_meta = st.number_input("Llamadas/día:", min_value=1, max_value=500, value=st.session_state.meta_diaria, step=5, key="input_meta")
        if nueva_meta != st.session_state.meta_diaria:
            st.session_state.meta_diaria = nueva_meta
            st.rerun()
    
    st.divider()

try:
    # Leemos con gspread
    df_historico = read_sheet("0")
except:
    df_historico = pd.DataFrame()

tab_op, tab_met, tab_sup, tab_aud, tab_pruebas = st.tabs(["📞 Operación", "📊 Mis Métricas", "👤 Supervisor", "📜 Auditoría", "🧪 Pruebas"])

with tab_met:
    st.subheader("Rendimiento del Agente")
    if not df_historico.empty:
        # Aseguramos que la columna agente_id existe para filtrar
        if 'agente_id' in df_historico.columns:
            df_agente = df_historico[df_historico['agente_id'].astype(str) == str(st.session_state.agente_id)]
            if not df_agente.empty:
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Gestionados", len(df_agente))
                m2.metric("Efectividad", f"{(len(df_agente[df_agente['estado']=='Llamado'])/len(df_agente)*100):.1f}%")
                m3.metric("Promedio Duración", f"{pd.to_numeric(df_agente['duracion_seg'], errors='coerce').mean():.1f}s")
                st.plotly_chart(px.pie(df_agente, names='estado', title="Distribución de Estados"), use_container_width=True)
            else:
                st.info(f"No hay registros en el Sheet para el agente {st.session_state.agente_id}.")
        else:
            st.error("La columna 'agente_id' no se encuentra en el Sheet de informe.")
    else:
        st.warning("No hay datos en el Sheet de informe.")

with tab_sup:
    if st.session_state.agente_id == "12345678":
        st.subheader("Panel de Control Gerencial")
        if not df_historico.empty:
            st.write("Resumen por Agente Humano:")
            resumen_sup = df_historico.groupby(['agente_id', 'estado']).size().unstack(fill_value=0)
            st.dataframe(resumen_sup, use_container_width=True)
            st.plotly_chart(px.bar(df_historico, x='agente_id', color='estado', title="Productividad por Cédula"), use_container_width=True)
    else:
        st.error("Acceso restringido a Supervisores.")

with tab_aud:
    st.markdown(f"<div class='log-box'>{'<br>'.join(st.session_state.logs[::-1])}</div>", unsafe_allow_html=True)

# --- TAB DE PRUEBAS ---
with tab_pruebas:
    st.subheader("🧪 Módulo de Pruebas de Llamadas")
    st.write("Prueba la calidad de las llamadas con Click-to-Call")
    
    col_test1, col_test2 = st.columns(2)
    
    with col_test1:
        st.write("**Configuración de Llamada de Prueba**")
        numero_destino = st.text_input("📱 Número Destino (a quién llamar):", value="+57", key="test_destino")
        numero_origen = st.text_input("📞 Número Origen (tu número):", value="+57", key="test_origen")
        
        st.info("""**Cómo funciona:**
        1. Twilio llama primero al **Número Destino**
        2. Si contesta, Twilio llama al **Número Origen** (tú)
        3. Cuando contestas, se conectan ambas llamadas
        4. Al destino le aparece el Número Origen en el Caller ID
        """)
    
    with col_test2:
        st.write("**Iniciar Prueba**")
        
        if 'test_call_sid' not in st.session_state:
            st.session_state.test_call_sid = None
        
        if st.session_state.test_call_sid is None:
            if st.button("🚀 INICIAR LLAMADA DE PRUEBA", type="primary"):
                if len(numero_destino) > 5 and len(numero_origen) > 5:
                    try:
                        # Crear TwiML que conecta las dos llamadas
                        twiml_test = f"""
                        <?xml version="1.0" encoding="UTF-8"?>
                        <Response>
                            <Say language="es-MX">Conectando llamada de prueba</Say>
                            <Dial callerId="{numero_origen}">
                                <Number>{numero_origen}</Number>
                            </Dial>
                        </Response>
                        """
                        
                        # Crear llamada al destino primero
                        call = client.calls.create(
                            twiml=twiml_test,
                            to=numero_destino,
                            from_=twilio_number
                        )
                        
                        st.session_state.test_call_sid = call.sid
                        st.success(f"✅ Llamada iniciada: {call.sid}")
                        st.info(f"📞 Llamando a {numero_destino}...")
                        add_log(f"TEST_CALL: {numero_destino} → {numero_origen}", "PRUEBA")
                        time.sleep(2)
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al iniciar llamada: {e}")
                else:
                    st.warning("⚠️ Ingresa números válidos con código de país (+57...)")
        else:
            # Monitorear llamada de prueba
            try:
                test_call = client.calls(st.session_state.test_call_sid).fetch()
                st.info(f"📊 Estado: {test_call.status}")
                
                if test_call.status in ['completed', 'failed', 'busy', 'no-answer', 'canceled']:
                    st.success(f"✅ Llamada finalizada: {test_call.status}")
                    if st.button("🔄 Nueva Prueba"):
                        st.session_state.test_call_sid = None
                        st.rerun()
                else:
                    st.write("⏳ Llamada en curso...")
                    time.sleep(3)
                    st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")
                st.session_state.test_call_sid = None

# --- 6. OPERACIÓN CON WEBRTC (BLOQUE EXPANDIDO Y REFORZADO) ---
with tab_op:
    # Componente WebRTC de Twilio Client
    if 'webrtc_token' not in st.session_state:
        st.session_state.webrtc_token = None
    
    # JavaScript para Twilio Device (WebRTC) - SDK v1.15.1
    # Leer el SDK de Twilio desde el archivo local
    try:
        with open('twilio.min.js', 'r', encoding='utf-8') as f:
            twilio_sdk_content = f.read()
    except Exception as e:
        st.error(f"Error cargando SDK de Twilio: {e}")
        twilio_sdk_content = "console.error('No se pudo cargar el SDK de Twilio');"
    
    twilio_webrtc_component = f"""
    <div id="twilio-device-status" style="padding: 10px; background: #f0f0f0; border-radius: 5px; margin-bottom: 10px;">
        <span id="device-status">🔴 Inicializando audio...</span>
    </div>
    
    <script>
    {twilio_sdk_content}
    console.log('✅ Twilio SDK cargado desde archivo local');
    setTimeout(initTwilioDevice, 100);
    </script>
    <script>
        var device;
        var currentConnection;
        
        // Función para actualizar estado
        window.updateStatus = function(message) {{
            var statusEl = document.getElementById('device-status');
            if (statusEl) {{
                statusEl.innerHTML = message;
                console.log('Status:', message);
            }}
        }};
        
        // Función para obtener token y configurar device
        async function initTwilioDevice() {{
            var statusEl = document.getElementById('device-status');
            if (!statusEl) {{
                console.error('Elemento device-status no encontrado');
                setTimeout(initTwilioDevice, 200);
                return;
            }}
            
            // Verificar que Twilio esté disponible
            if (typeof Twilio === 'undefined') {{
                console.log('⏳ Esperando a que Twilio se cargue...');
                setTimeout(initTwilioDevice, 200);
                return;
            }}
            
            try {{
                updateStatus('🟡 Conectando con Twilio...');
                
                // Obtener token
                const tokenUrl = `{function_url}/token?identity={st.session_state.agente_id}`;
                console.log('🔍 URL del token:', tokenUrl);
                
                const response = await fetch(tokenUrl);
                console.log('📡 Respuesta del token:', response.status);
                
                if (!response.ok) {{
                    const errorText = await response.text();
                    console.error('❌ Error en respuesta:', errorText);
                    throw new Error(`Error ${{response.status}}: ${{errorText}}`);
                }}
                
                const data = await response.json();
                console.log('✅ Token obtenido exitosamente');
                
                // Crear Device con SDK v2.x
                updateStatus('🟡 Configurando dispositivo...');
                device = new Twilio.Device(data.token, {{
                    codecPreferences: [Twilio.Device.CodecName.Opus, Twilio.Device.CodecName.PCMU],
                    logLevel: 1,
                    edge: 'ashburn'
                }});
                
                // Event listeners
                device.on('registered', function() {{
                    console.log('✅ Twilio Device registrado y listo');
                    updateStatus('🟢 Audio listo - WebRTC conectado');
                }});
                
                device.on('error', function(error) {{
                    console.error('❌ Error Twilio Device:', error);
                    updateStatus('🔴 Error: ' + (error.message || 'Error desconocido'));
                }});
                
                device.on('incoming', function(call) {{
                    console.log('📞 Llamada entrante');
                    call.accept();
                }});
                
                // Registrar Device
                updateStatus('🟡 Registrando dispositivo...');
                await device.register();
                console.log('✅ Dispositivo registrado');
                
            }} catch(error) {{
                console.error('❌ Error inicializando Twilio:', error);
                updateStatus('🔴 Error: ' + error.message);
            }}
        }}
        
        // Función para hacer llamadas WebRTC
        function llamarWebRTC(numero) {{
            if (!device) {{
                alert('⚠️ WebRTC no está inicializado. Espera a que aparezca "Audio listo"');
                return;
            }}
            
            console.log('Iniciando llamada WebRTC a:', numero);
            
            try {{
                const params = {{
                    To: numero
                }};
                
                currentConnection = device.connect(params);
                
                currentConnection.on('accept', function() {{
                    console.log('Llamada conectada');
                }});
                
                currentConnection.on('disconnect', function() {{
                    console.log('Llamada finalizada');
                    currentConnection = null;
                }});
                
                currentConnection.on('error', function(error) {{
                    console.error('Error en llamada:', error);
                    alert('❌ Error: ' + error.message);
                }});
                
            }} catch(error) {{
                console.error('Error iniciando llamada:', error);
                alert('❌ Error: ' + error.message);
            }}
        }}
        
        function colgarWebRTC() {{
            if (currentConnection) {{
                currentConnection.disconnect();
            }}
        }}
    </script>
    """
    
    import streamlit.components.v1 as components
    components.html(twilio_webrtc_component, height=50)

with tab_op:
    if st.session_state.df_contactos is not None:
        search = st.text_input("🔍 Buscar Cliente:").lower()
        df = st.session_state.df_contactos
        
        opc = st.radio("Ver:", ["Pendientes", "No Contestaron", "Programadas"], horizontal=True)
        # Lógica de mapeo de pestaña a estado del DF
        f_est = "Pendiente" if "Pendientes" in opc else "No Contesto" if "No Contestaron" in opc else "Programada"
        
        # Filtrado riguroso
        df_work = df[df['estado'] == f_est]
        if search:
            # Buscar en nombre o en teléfono (sin código de país, ej: 300xxxxxxx)
            df_work = df_work[
                df_work['nombre'].str.lower().str.contains(search, na=False) | 
                df_work['telefono'].astype(str).str.contains(search, na=False) |
                df_work['telefono'].astype(str).str.replace('+57', '', regex=False).str.contains(search, na=False)
            ]
        
        # Paginación: 30 contactos por página
        CONTACTOS_POR_PAGINA = 30
        total_contactos = len(df_work)
        total_paginas = (total_contactos - 1) // CONTACTOS_POR_PAGINA + 1 if total_contactos > 0 else 1
        
        # Resetear página si cambia el filtro
        if 'ultimo_filtro' not in st.session_state:
            st.session_state.ultimo_filtro = f_est
        if st.session_state.ultimo_filtro != f_est:
            st.session_state.pagina_actual = 0
            st.session_state.ultimo_filtro = f_est
        
        # Asegurar que la página actual esté en rango
        if st.session_state.pagina_actual >= total_paginas:
            st.session_state.pagina_actual = max(0, total_paginas - 1)
        
        # Mostrar controles de paginación si hay más de 30 contactos
        if total_contactos > CONTACTOS_POR_PAGINA:
            col_pag1, col_pag2, col_pag3 = st.columns([1, 2, 1])
            with col_pag1:
                if st.button("⬅️ Anterior", disabled=st.session_state.pagina_actual == 0):
                    st.session_state.pagina_actual -= 1
                    st.rerun()
            with col_pag2:
                st.write(f"**Página {st.session_state.pagina_actual + 1} de {total_paginas}** ({total_contactos} contactos)")
            with col_pag3:
                if st.button("Siguiente ➡️", disabled=st.session_state.pagina_actual >= total_paginas - 1):
                    st.session_state.pagina_actual += 1
                    st.rerun()
        
        # Obtener contactos de la página actual
        inicio = st.session_state.pagina_actual * CONTACTOS_POR_PAGINA
        fin = inicio + CONTACTOS_POR_PAGINA
        df_work = df_work.iloc[inicio:fin]

        if not df_work.empty:
            # Mostrar TODOS los contactos de la página (hasta 30)
            st.write(f"**Mostrando {len(df_work)} contactos:**")
            
            # Iterar sobre TODOS los contactos de la página
            for idx in df_work.index:
                c = df_work.loc[idx]
                # Construir número completo desde CSV (codigo_pais + telefono)
                if 'codigo_pais' in c.index and pd.notna(c['codigo_pais']):
                    tel = f"+{str(c['codigo_pais']).replace('+', '')}{str(c['telefono'])}"
                else:
                    tel = str(c['telefono']) if str(c['telefono']).startswith('+') else f"+{str(c['telefono'])}"

                # Crear un expander para cada contacto
                with st.expander(f"📞 {c['nombre']} - {tel}", expanded=False):
                    col1, col2 = st.columns([2,1])
                    with col1:
                        st.markdown(f"<div class='client-card'><h3>{c['nombre']}</h3><p>Tel: {tel}</p></div>", unsafe_allow_html=True)
                        val_n = st.session_state.draft_notas.get(idx, c['observacion'])
                        nota = st.text_area("Notas:", value=val_n, key=f"n_{idx}")
                        st.session_state.draft_notas[idx] = nota

                    with col2:
                        if not st.session_state.en_pausa:
                            # Verificar si hay llamada activa (Conference o WebRTC)
                            llamada_activa = st.session_state.llamada_activa_sid is not None or st.session_state.webrtc_activo
                            
                            if not llamada_activa:
                                # Botón único de llamada con Conference Call (ACTIVO)
                                if st.button("📞 LLAMAR (Conference Call)", type="primary", use_container_width=True, key=f"call_{idx}"):
                                    try:
                                        # Crear conference call: Twilio llama primero al agente, luego al cliente
                                        # El cliente verá el número del agente como Caller ID
                                         
                                        # Paso 1: Llamar al agente primero
                                        print(f"[DEBUG] Iniciando conference call - Llamando a agente: {st.session_state.numero_celular_agente}")
                                 
                                        # Crear TwiML para la conferencia con grabación y transcripción
                                        twiml_conference = f"""<?xml version="1.0" encoding="UTF-8"?>
                                        <Response>
                                            <Dial>
                                                <Conference 
                                                    startConferenceOnEnter="true"
                                                    endConferenceOnExit="true"
                                                    record="record-from-start"
                                                    recordingStatusCallback="{function_url}/recording-status"
                                                    trim="trim-silence"
                                                    transcribe="true"
                                                    transcribeCallback="{function_url}/transcription-callback"
                                                    waitUrl=""
                                                    beep="false"
                                                >Room_{st.session_state.agente_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}</Conference>
                                            </Dial>
                                        </Response>"""
                                        
                                        # Llamar al agente
                                        call_agente = client.calls.create(
                                            twiml=twiml_conference,
                                            to=st.session_state.numero_celular_agente,
                                            from_=twilio_number,
                                            status_callback=f"{function_url}/status",
                                            status_callback_event=['initiated', 'ringing', 'answered', 'completed']
                                        )
                                        
                                        # Esperar 2 segundos para que el agente conteste
                                        time.sleep(2)
                                        
                                        # Paso 2: Llamar al cliente usando número del agente como Caller ID
                                        print(f"[DEBUG] Llamando a cliente: {tel} con Caller ID: {st.session_state.numero_celular_agente}")
                                        
                                        call_cliente = client.calls.create(
                                            twiml=twiml_conference,
                                            to=tel,
                                            from_=st.session_state.numero_celular_agente,  # Número del agente (verificado)
                                            machine_detection='Enable',
                                            status_callback=f"{function_url}/status",
                                            status_callback_event=['initiated', 'ringing', 'answered', 'completed']
                                        )
                                        
                                        # Guardar el SID de la llamada del cliente (para tracking)
                                        st.session_state.llamada_activa_sid = call_cliente.sid
                                        st.session_state.t_inicio_dt = datetime.now()
                                        
                                        add_log(f"CONFERENCE_CALL_START: {c['nombre']} - Agente: {call_agente.sid}, Cliente: {call_cliente.sid}", "TWILIO")
                                        st.success(f"✅ Llamada iniciada - Contestar tu celular primero")
                                        time.sleep(1)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error al iniciar llamada: {e}")
                                        print(f"[ERROR] Error en conference call: {e}")
                                        import traceback
                                        print(traceback.format_exc())
                                # ============================================================
                                # BOTÓN ALTERNATIVO: WebRTC (HABILITADO)
                                # ============================================================
                                
                                # --- OPCIÓN 1: Botón Server-Side (COMENTADO - No sirve para audio bidireccional) ---
                                # if st.button("📞 LLAMAR (Server)", use_container_width=True, key=f"call_server_{idx}"):
                                #     try:
                                #         call = client.calls.create(
                                #             url=function_url, 
                                #             to=tel, 
                                #             from_=twilio_number, 
                                #             machine_detection='Enable', 
                                #             record=True
                                #         )
                                #         st.session_state.llamada_activa_sid = call.sid
                                #         st.session_state.t_inicio_dt = datetime.now()
                                #         add_log(f"CALL_START_SERVER: {c['nombre']}", "TWILIO")
                                #         st.rerun()
                                #     except Exception as e:
                                #         st.error(f"Error al iniciar llamada: {e}")
                                
                                # --- OPCIÓN 2: Botón WebRTC (Llamada desde navegador) - HABILITADO ---
                                if st.button("🎧 LLAMAR (WebRTC)", use_container_width=True, key=f"call_webrtc_{idx}"):
                                    # Marcar WebRTC como activo
                                    st.session_state.webrtc_activo = True
                                    st.session_state.webrtc_numero = tel
                                    st.session_state.webrtc_nombre = c['nombre']
                                    st.session_state.t_inicio_dt = datetime.now()
                                    add_log(f"WEBRTC_START: {c['nombre']} - {tel}", "TWILIO")
                                    st.success("✅ Iniciando WebRTC - Permite el micrófono")
                                    time.sleep(1)
                                    st.rerun()
                                
                                # Mostrar botón HTML para iniciar llamada JavaScript
                                if st.session_state.webrtc_activo and st.session_state.webrtc_numero == tel:
                                    st.markdown(f"""
                                    <button onclick="llamarWebRTC('{tel}')" style="
                                        background: #FF6B6B;
                                        color: white;
                                        border: none;
                                        padding: 10px 20px;
                                        border-radius: 5px;
                                        cursor: pointer;
                                        font-size: 16px;
                                        width: 100%;
                                        margin-top: 10px;
                                    ">📞 CONECTAR AUDIO</button>
                                    """, unsafe_allow_html=True)
                                # ============================================================
                                
                                # Opción de reprogramar
                                st.divider()
                                st.write("**📅 Reprogramar Llamada**")
                                fecha_prog = st.date_input("Fecha:", value=datetime.now().date(), key=f"fecha_{idx}")
                                hora_prog = st.time_input("Hora:", value=datetime.now().time(), key=f"hora_{idx}")
                                 
                                if st.button("✅ Programar", key=f"prog_{idx}"):
                                    # Combinar fecha y hora
                                    fecha_hora_prog = datetime.combine(fecha_prog, hora_prog)
                                    st.session_state.df_contactos.at[idx, 'estado'] = 'Programada'
                                    st.session_state.df_contactos.at[idx, 'proxima_llamada'] = fecha_hora_prog.strftime("%Y-%m-%d %H:%M:%S")
                                    st.session_state.df_contactos.at[idx, 'observacion'] = nota
                                    st.session_state.df_contactos.at[idx, 'agente_id'] = st.session_state.agente_id
                                    add_log(f"PROGRAMADA: {c['nombre']} para {fecha_hora_prog.strftime('%Y-%m-%d %H:%M')}", "ACCION")
                                    st.success(f"✅ Llamada programada para {fecha_hora_prog.strftime('%Y-%m-%d %H:%M')}")
                                    time.sleep(1)
                                    st.rerun()
                            else:
                                # --- MONITOR DINÁMICO ---
                                
                                # Verificar si es llamada WebRTC
                                if st.session_state.webrtc_activo:
                                    # Monitor para WebRTC
                                    tiempo_transcurrido = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                                    minutos = tiempo_transcurrido // 60
                                    segundos = tiempo_transcurrido % 60
                                    st.markdown(f"### ⏱️ Tiempo: {minutos:02d}:{segundos:02d}")
                                    st.info(f"🎧 Llamada WebRTC activa con {st.session_state.webrtc_nombre}")
                                    
                                    # Buscar el SID de llamada WebRTC si no lo tenemos
                                    if st.session_state.webrtc_call_sid is None:
                                        try:
                                            # Buscar llamadas activas al número del cliente
                                            calls = client.calls.list(
                                                to=tel,
                                                status='in-progress',
                                                limit=1
                                            )
                                            if calls:
                                                st.session_state.webrtc_call_sid = calls[0].sid
                                                print(f"[DEBUG] WebRTC Call SID encontrado: {calls[0].sid}")
                                                st.success(f"🔗 Llamada conectada: {calls[0].sid[:8]}...")
                                        except Exception as e:
                                            print(f"[ERROR] Error buscando SID de llamada WebRTC: {e}")
                                    
                                    # Botones en columnas (similar a Conference Call)
                                    btn_webrtc_col1, btn_webrtc_col2 = st.columns(2)
                                    
                                    finalizar_webrtc = False
                                    pausar_webrtc = False
                                    
                                    with btn_webrtc_col1:
                                        finalizar_webrtc = st.button("✅ FINALIZAR WebRTC", type="primary")
                                    
                                    with btn_webrtc_col2:
                                        if not st.session_state.grabacion_pausada:
                                            pausar_webrtc = st.button("⏸️ PAUSAR GRABACIÓN")
                                        else:
                                            st.info("🔴 Grabación pausada")
                                    
                                    # Manejar pausa de grabación en WebRTC
                                    if pausar_webrtc:
                                        # Calcular duración hasta el momento
                                        dur_pausa = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                                        
                                        # Pausar la grabación en Twilio si tenemos el SID
                                        if st.session_state.webrtc_call_sid:
                                            try:
                                                recordings = client.recordings.list(call_sid=st.session_state.webrtc_call_sid, limit=1)
                                                if recordings:
                                                    client.recordings(recordings[0].sid).update(status='paused')
                                                    st.success("⏸️ Grabación pausada en Twilio")
                                            except Exception as e:
                                                print(f"[ERROR] Error pausando grabación WebRTC: {e}")
                                        
                                        # Guardar en Sheet Informe con estado "Grabación Pausada"
                                        if guardar_en_sheet_informe(c, tel, "Grabación Pausada", nota, dur_pausa, st.session_state.webrtc_call_sid or ''):
                                            st.session_state.grabacion_pausada = True
                                            add_log(f"WEBRTC_GRABACION_PAUSADA: {c['nombre']} - {dur_pausa}s", "ACCION")
                                            st.success("✅ Grabación pausada y guardada en Sheet Informe")
                                        else:
                                            st.error("❌ Error guardando en Sheet Informe")
                                        time.sleep(1)
                                        st.rerun()
                                    
                                    # Manejar finalización de WebRTC
                                    if finalizar_webrtc:
                                        # Guardar gestión
                                        t_fin = datetime.now()
                                        dur = int((t_fin - st.session_state.t_inicio_dt).total_seconds())
                                        
                                        # Actualizar DataFrame local
                                        st.session_state.df_contactos.at[idx, 'estado'] = 'Llamado'
                                        st.session_state.df_contactos.at[idx, 'observacion'] = nota
                                        st.session_state.df_contactos.at[idx, 'duracion_seg'] = dur
                                        st.session_state.df_contactos.at[idx, 'agente_id'] = st.session_state.agente_id
                                        st.session_state.df_contactos.at[idx, 'fecha_llamada'] = t_fin.strftime("%Y-%m-%d %H:%M:%S")
                                        
                                        # Guardar en Sheet Informe
                                        if guardar_en_sheet_informe(c, tel, "Llamado", nota, dur, ''):
                                            st.success("✅ Guardado en Sheet Informe")
                                        
                                        add_log(f"WEBRTC_END: {st.session_state.webrtc_nombre} - {dur}s", "TWILIO")
                                        
                                        # Limpiar estado WebRTC
                                        st.session_state.webrtc_activo = False
                                        st.session_state.webrtc_numero = None
                                        st.session_state.webrtc_nombre = None
                                        st.session_state.webrtc_call_sid = None
                                        st.session_state.grabacion_pausada = False
                                        
                                        st.success("✅ Llamada WebRTC finalizada")
                                        time.sleep(1)
                                        st.rerun()
                                    
                                    # Botón HTML para colgar desde JavaScript
                                    st.markdown("""
                                    <button onclick="colgarWebRTC()" style="
                                        background: #FF4444;
                                        color: white;
                                        border: none;
                                        padding: 10px 20px;
                                        border-radius: 5px;
                                        cursor: pointer;
                                        font-size: 16px;
                                        width: 100%;
                                        margin-top: 10px;
                                    ">📞 Colgar Audio</button>
                                    """, unsafe_allow_html=True)
                                    
                                    # Auto-refresh para actualizar cronómetro
                                    time.sleep(1)
                                    st.rerun()
                                
                                # Monitor para Conference Call
                                try:
                                    print(f"[DEBUG] Iniciando monitoreo de llamada Conference...")
                                    
                                    # CRONÓMETRO EN TIEMPO REAL
                                    tiempo_transcurrido = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                                    minutos = tiempo_transcurrido // 60
                                    segundos = tiempo_transcurrido % 60
                                    st.markdown(f"### ⏱️ Tiempo: {minutos:02d}:{segundos:02d}")
                                    
                                    # 1. Consultar estado real en Twilio
                                    print(f"[DEBUG] Consultando estado de llamada: {st.session_state.llamada_activa_sid}")
                                    remote = client.calls(st.session_state.llamada_activa_sid).fetch()
                                    print(f"[DEBUG] Estado Twilio obtenido: {remote.status}")
                                    st.info(f"📞 Estado Twilio: {remote.status}")
                                    
                                    # 2. Definir condiciones de terminación
                                    call_ended_by_system = remote.status in ['completed', 'no-answer', 'busy', 'failed', 'canceled']
                                    print(f"[DEBUG] call_ended_by_system = {call_ended_by_system}")
                                    
                                    # 3. Detectar si contestó máquina y colgar automáticamente
                                    answered_by = str(remote.answered_by) if hasattr(remote, 'answered_by') and remote.answered_by else 'unknown'
                                    es_maquina = answered_by in ['machine_start', 'fax']
                                    
                                    # Colgar automáticamente si es máquina
                                    if es_maquina and not call_ended_by_system:
                                        st.warning(f"🤖 Máquina/Buzón detectado: {answered_by} - Finalizando automáticamente...")
                                        try:
                                            # Colgar la llamada automáticamente
                                            client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                                            print(f"[DEBUG] Llamada finalizada automáticamente por detección de máquina")
                                            st.info("📞 Llamada finalizada automáticamente")
                                            # Marcar como terminada por el sistema
                                            call_ended_by_system = True
                                            time.sleep(2)
                                            st.rerun()
                                        except Exception as e:
                                            print(f"[ERROR] Error finalizando llamada automáticamente: {e}")
                                            st.error(f"Error: {e}")
                                    
                                    # 4. Mostrar botones durante llamada activa
                                    finalizar_manual = False
                                    pausar_grabacion = False
                                    
                                    if not call_ended_by_system:
                                        # Mostrar botones en columnas
                                        btn_col1, btn_col2 = st.columns(2)
                                        with btn_col1:
                                            finalizar_manual = st.button("✅ FINALIZAR GESTIÓN", type="primary")
                                        with btn_col2:
                                            if not st.session_state.grabacion_pausada:
                                                pausar_grabacion = st.button("⏸️ PAUSAR GRABACIÓN")
                                            else:
                                                st.info("🔴 Grabación pausada")
                                        
                                        # Manejar pausa de grabación
                                        if pausar_grabacion:
                                            try:
                                                # Pausar la grabación en Twilio
                                                recordings = client.recordings.list(call_sid=st.session_state.llamada_activa_sid, limit=1)
                                                if recordings:
                                                    client.recordings(recordings[0].sid).update(status='paused')
                                                    
                                                    # Calcular duración hasta el momento
                                                    dur_pausa = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                                                    
                                                    # Guardar en Sheet Informe con estado "Grabación Pausada"
                                                    if guardar_en_sheet_informe(c, tel, "Grabación Pausada", nota, dur_pausa, st.session_state.llamada_activa_sid):
                                                        st.session_state.grabacion_pausada = True
                                                        add_log(f"GRABACION_PAUSADA: {c['nombre']} - {dur_pausa}s", "ACCION")
                                                        st.success("✅ Grabación pausada y guardada en Sheet Informe")
                                                    else:
                                                        st.error("❌ Error guardando en Sheet Informe")
                                                    
                                                    time.sleep(1)
                                                    st.rerun()
                                            except Exception as e:
                                                st.error(f"Error pausando grabación: {e}")
                                    else:
                                        st.warning(f"⚠️ Llamada terminada automáticamente: {remote.status}")
                                    
                                    # 4. Accion de Finalización (Manual o Automática)
                                    print(f"[DEBUG] finalizar_manual={finalizar_manual}, call_ended_by_system={call_ended_by_system}")
                                    if finalizar_manual or call_ended_by_system:
                                        print(f"[DEBUG] ENTRANDO AL BLOQUE DE FINALIZACIÓN")
                                        
                                        # Obtener answered_by para detectar si contestó una persona o máquina
                                        answered_by = str(remote.answered_by) if hasattr(remote, 'answered_by') and remote.answered_by else 'unknown'
                                        print(f"[DEBUG] answered_by: {answered_by}, status: {remote.status}")
                                        
                                        # Determinar estado basado en answered_by y status
                                        final_status = 'Llamado'
                                        
                                        if remote.status in ['no-answer', 'busy', 'failed', 'canceled']:
                                            final_status = 'No Contesto'
                                        elif answered_by in ['machine_start', 'fax', 'unknown']:
                                            final_status = 'No Contesto'
                                            print(f"[DEBUG] Detectado como máquina/buzón: {answered_by}")
                                        elif answered_by == 'human':
                                            final_status = 'Llamado'
                                            print(f"[DEBUG] Detectado como humano")
                                        else:
                                            if remote.status == 'completed' and answered_by == 'unknown':
                                                final_status = 'No Contesto'
                                                print(f"[DEBUG] Status completed pero answered_by unknown - marcando como No Contesto")
                                        
                                        print(f"[DEBUG] Estado final determinado: {final_status}")
                                        
                                        # Calculamos duración
                                        t_fin = datetime.now()
                                        dur = int((t_fin - st.session_state.t_inicio_dt).total_seconds())
                                        print(f"[DEBUG] Duración calculada: {dur} segundos")
                                        
                                        # --- PASO 1: ACTUALIZACIÓN LOCAL INMEDIATA ---
                                        print(f"[DEBUG] Actualizando DataFrame local para idx={idx}")
                                        st.session_state.df_contactos.at[idx, 'estado'] = final_status
                                        st.session_state.df_contactos.at[idx, 'observacion'] = nota
                                        st.session_state.df_contactos.at[idx, 'duracion_seg'] = dur
                                        st.session_state.df_contactos.at[idx, 'agente_id'] = st.session_state.agente_id
                                        st.session_state.df_contactos.at[idx, 'fecha_llamada'] = t_fin.strftime("%Y-%m-%d %H:%M:%S")
                                        st.session_state.df_contactos.at[idx, 'sid_llamada'] = st.session_state.llamada_activa_sid
                                        print(f"[DEBUG] DataFrame local actualizado. Estado: {final_status}")
                                        
                                        # --- PASO 2: SINCRONIZACIÓN CON SHEET INFORME ---
                                        print(f"[DEBUG] Iniciando sincronización con Sheet Informe")
                                        st.write(f"💾 Guardando gestión: {final_status}")
                                        
                                        if URL_SHEET_INFORME:
                                            try:
                                                st.write("🔄 Sincronizando con Sheet Informe...")
                                                
                                                # Obtener información adicional de Twilio
                                                url_grabacion = ''
                                                precio_llamada = '0'
                                                duracion_facturada = '0'
                                                estado_respuesta = answered_by
                                                codigo_error = ''
                                                
                                                try:
                                                    recordings = client.recordings.list(call_sid=st.session_state.llamada_activa_sid, limit=1)
                                                    if recordings:
                                                        url_grabacion = f"https://api.twilio.com{recordings[0].uri.replace('.json', '.mp3')}"
                                                    
                                                    precio_llamada = str(remote.price) if remote.price else '0'
                                                    duracion_facturada = str(remote.duration) if remote.duration else '0'
                                                    codigo_error = str(remote.error_code) if remote.error_code else ''
                                                except Exception as e_twilio:
                                                    print(f"[DEBUG] Error obteniendo datos Twilio: {e_twilio}")
                                                
                                                # Preparar fila para Sheet Informe
                                                fila_informe = pd.DataFrame({
                                                    'agente_id': [st.session_state.agente_id],
                                                    'nombre': [c['nombre']],
                                                    'telefono': [tel],
                                                    'estado': [final_status],
                                                    'observacion': [nota],
                                                    'duracion_seg': [dur],
                                                    'fecha_llamada': [t_fin.strftime("%Y-%m-%d %H:%M:%S")],
                                                    'sid_llamada': [st.session_state.llamada_activa_sid],
                                                    'url_grabacion': [url_grabacion],
                                                    'precio_llamada': [precio_llamada],
                                                    'duracion_facturada': [duracion_facturada],
                                                    'estado_respuesta': [estado_respuesta],
                                                    'codigo_error': [codigo_error]
                                                })
                                                
                                                # Leer Sheet Informe actual (con caché para evitar rate limit)
                                                try:
                                                    # Usar caché de session_state para evitar múltiples lecturas
                                                    if 'df_informe_cache' not in st.session_state or st.session_state.get('informe_cache_time', 0) < time.time() - 30:
                                                        # Actualizar caché cada 30 segundos
                                                        df_informe_actual = read_sheet("0")
                                                        st.session_state.df_informe_cache = df_informe_actual
                                                        st.session_state.informe_cache_time = time.time()
                                                        print(f"[DEBUG] Caché de Informe actualizado: {len(df_informe_actual)} registros")
                                                    else:
                                                        df_informe_actual = st.session_state.df_informe_cache
                                                        print(f"[DEBUG] Usando caché de Informe: {len(df_informe_actual)} registros")
                                                    
                                                    st.write(f"📊 Registros en Informe: {len(df_informe_actual)}")
                                                except Exception as e_read:
                                                    print(f"[ERROR] Error leyendo Informe: {e_read}")
                                                    df_informe_actual = pd.DataFrame()
                                                
                                                # Agregar nuevo registro
                                                if df_informe_actual.empty:
                                                    df_informe_actualizado = fila_informe.copy()
                                                else:
                                                    df_informe_actualizado = pd.concat([df_informe_actual, fila_informe], ignore_index=True)
                                                
                                                # Guardar en Sheet Informe
                                                if update_sheet(df_informe_actualizado, "0"):
                                                    st.success(f"✅ Guardado en Sheet Informe: {final_status}")
                                                    add_log(f"SYNC_INFORME: {c['nombre']} - {final_status}", "DATA")
                                                else:
                                                    st.warning("⚠️ Error guardando en Sheet Informe")
                                                    
                                            except Exception as e_informe:
                                                st.error(f"❌ Error en Sheet Informe: {e_informe}")
                                                print(f"[ERROR] Sync Informe: {e_informe}")
                                        
                                        # --- PASO 3: ACTUALIZACIÓN DE SHEET LLAMADAS (campo estado) ---
                                        print(f"[DEBUG] Actualizando estado en Sheet Llamadas")
                                        if URL_SHEET_CONTACTOS:
                                            try:
                                                st.write("🔄 Actualizando estado en Sheet Llamadas...")
                                                
                                                # Actualizar el DataFrame completo y escribirlo de vuelta
                                                if update_sheet(st.session_state.df_contactos, "0", sheet_url=URL_SHEET_CONTACTOS):
                                                    st.success("✅ Estado actualizado en Sheet Llamadas")
                                                    add_log(f"UPDATE_LLAMADAS: {c['nombre']} - {final_status}", "DATA")
                                                else:
                                                    st.warning("⚠️ Error actualizando Sheet Llamadas")
                                                    
                                            except Exception as e_llamadas:
                                                st.error(f"❌ Error en Sheet Llamadas: {e_llamadas}")
                                                print(f"[ERROR] Update Llamadas: {e_llamadas}")
                                        
                                        # --- PASO 4: LIMPIEZA DE ESTADO ---
                                        print(f"[DEBUG] Limpiando estado de llamada")
                                        st.write("✅ Gestión completada - Pasando al siguiente contacto...")
                                        st.session_state.llamada_activa_sid = None
                                        st.session_state.grabacion_pausada = False
                                        time.sleep(2)
                                        st.rerun()
                                    
                                    # Bucle de espera activa
                                    if not call_ended_by_system:
                                        st.write("⏳ Esperando respuesta del cliente...")
                                        time.sleep(2)
                                        st.rerun()
                                
                                except Exception as e_monitor:
                                    import traceback
                                    error_trace = traceback.format_exc()
                                    print(f"[ERROR] Error monitoreando llamada: {e_monitor}")
                                    print(f"[ERROR] Traceback:\n{error_trace}")
                                    st.error(f"Error monitoreando llamada: {e_monitor}")
                                    st.code(error_trace)
        else:
            st.success(f"¡Felicidades! No hay más clientes en la categoría: {f_est}")
    else:
        st.info("Por favor, cargue un archivo CSV en el sidebar para comenzar la operación.")
