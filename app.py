import streamlit as st
import pandas as pd
from twilio.rest import Client
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import urllib.parse
import plotly.express as px
import re
import threading
import hashlib
from pytz import timezone
import pytz

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
    # Extraer la URL base para el endpoint /token (sin /hacer-llamada)
    function_url_base = function_url.replace('/hacer-llamada', '') if '/hacer-llamada' in function_url else function_url
    forms_base_url = st.secrets.get("MS_FORMS_URL", "https://forms.office.com/r/tu_codigo")
    URL_SHEET_INFORME = st.secrets.get("GSHEET_URL")
    URL_SHEET_CONTACTOS = st.secrets.get("GSHEET_CONTACTOS_URL")
    GDRIVE_LOGS_FOLDER_ID = st.secrets.get("GDRIVE_LOGS_FOLDER_ID")
    CEDULAS_AUTORIZADAS = st.secrets.get("CEDULAS_AUTORIZADAS", ["1121871773", "87654321", "12345678","52486921"])
    
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

# --- CONFIGURACIÓN DE ZONA HORARIA ---
# Configurar zona horaria de Bogotá (UTC-5)
TZ_BOGOTA = timezone('America/Bogota')

def obtener_hora_bogota():
    """Obtiene la fecha y hora actual en zona horaria de Bogotá"""
    return datetime.now(TZ_BOGOTA)

def convertir_a_bogota(fecha_utc):
    """Convierte una fecha UTC a zona horaria de Bogotá"""
    if fecha_utc.tzinfo is None:
        # Si no tiene timezone, asumir UTC
        fecha_utc = pytz.UTC.localize(fecha_utc)
    return fecha_utc.astimezone(TZ_BOGOTA)

def formatear_fecha_bogota(fecha):
    """Formatea fecha en zona horaria de Bogotá para mostrar en UI"""
    if fecha.tzinfo is None:
        fecha = TZ_BOGOTA.localize(fecha)
    return fecha

# --- SISTEMA DE SANITIZACIÓN Y SEGURIDAD ---
def sanitizar_nota(nota):
    """Sanitiza notas para prevenir inyección y contenido malicioso
    
    Args:
        nota: Texto de la nota a sanitizar
        
    Returns:
        str: Nota sanitizada y segura
    """
    if not nota or pd.isna(nota):
        return ""
    
    # Convertir a string si no lo es
    nota = str(nota)
    
    # Eliminar caracteres peligrosos para inyección
    nota = re.sub(r'[<>"\']', '', nota)
    
    # Eliminar scripts y patrones peligrosos
    nota = re.sub(r'(?i)script', '', nota)
    nota = re.sub(r'(?i)javascript:', '', nota)
    nota = re.sub(r'(?i)on\w+\s*=', '', nota)
    
    # Limitar longitud máxima (1000 caracteres)
    nota = nota[:1000] if len(nota) > 1000 else nota
    
    # Eliminar espacios excesivos
    nota = re.sub(r'\s+', ' ', nota).strip()
    
    return nota

def sanitizar_telefono(telefono):
    """Sanitiza números de teléfono
    
    Args:
        telefono: Número de teléfono a sanitizar
        
    Returns:
        str: Teléfono sanitizado
    """
    if not telefono or pd.isna(telefono):
        return ""
    
    # Mantener solo dígitos y signos +
    telefono = re.sub(r'[^\d+]', '', str(telefono))
    
    # Validar formato básico
    if telefono.startswith('+'):
        # Formato internacional: + seguido de 9-15 dígitos
        if re.match(r'^\+\d{9,15}$', telefono):
            return telefono
    else:
        # Formato nacional: 7-15 dígitos
        if re.match(r'^\d{7,15}$', telefono):
            return telefono
    
    return ""

def sanitizar_nombre(nombre):
    """Sanitiza nombres de contactos
    
    Args:
        nombre: Nombre a sanitizar
        
    Returns:
        str: Nombre sanitizado
    """
    if not nombre or pd.isna(nombre):
        return ""
    
    nombre = str(nombre)
    
    # Eliminar caracteres peligrosos pero permitir letras, números, espacios y caracteres comunes
    nombre = re.sub(r'[<>"\']', '', nombre)
    
    # Limitar longitud (100 caracteres)
    nombre = nombre[:100] if len(nombre) > 100 else nombre
    
    # Eliminar espacios excesivos
    nombre = re.sub(r'\s+', ' ', nombre).strip()
    
    return nombre

# --- SISTEMA DE CONTROL DE CONCURRENCIA PARA SHEETS ---
class SheetConcurrencyManager:
    """Maneja concurrencia para evitar conflictos de escritura en Google Sheets"""
    
    def __init__(self):
        self.locks = {}  # Locks por sheet
        self.last_operations = {}  # Últimas operaciones por agente
        self.operation_hashes = {}  # Hashes de operaciones para detectar duplicados
    
    def get_lock_key(self, sheet_url, worksheet_name):
        """Genera una clave única para el lock"""
        import hashlib
        key = f"{sheet_url}_{worksheet_name}"
        return hashlib.md5(key.encode()).hexdigest()
    
    def acquire_lock(self, sheet_url, worksheet_name, agente_id, timeout=10):
        """Adquiere un lock para escribir en un sheet específico
        
        Args:
            sheet_url: URL del Google Sheet
            worksheet_name: Nombre del worksheet
            agente_id: ID del agente que solicita el lock
            timeout: Tiempo máximo de espera en segundos
            
        Returns:
            bool: True si obtuvo el lock, False si no pudo obtenerlo
        """
        lock_key = self.get_lock_key(sheet_url, worksheet_name)
        
        if lock_key not in self.locks:
            self.locks[lock_key] = threading.Lock()
        
        lock = self.locks[lock_key]
        
        try:
            # Intentar adquirir el lock con timeout
            acquired = lock.acquire(timeout=timeout)
            if acquired:
                self.last_operations[lock_key] = {
                    'agente_id': agente_id,
                    'timestamp': time.time()
                }
                print(f"[CONCURRENCY] Lock adquirido por {agente_id} para {worksheet_name}")
            return acquired
        except Exception as e:
            print(f"[CONCURRENCY] Error adquiriendo lock: {e}")
            return False
    
    def release_lock(self, sheet_url, worksheet_name):
        """Libera un lock de escritura
        
        Args:
            sheet_url: URL del Google Sheet
            worksheet_name: Nombre del worksheet
        """
        lock_key = self.get_lock_key(sheet_url, worksheet_name)
        
        if lock_key in self.locks:
            lock = self.locks[lock_key]
            if lock.locked():
                lock.release()
                print(f"[CONCURRENCY] Lock liberado para {worksheet_name}")
            
            # Limpiar información antigua
            if lock_key in self.last_operations:
                del self.last_operations[lock_key]
    
    def is_operation_duplicate(self, sheet_url, worksheet_name, data_hash):
        """Verifica si una operación es duplicada
        
        Args:
            sheet_url: URL del Google Sheet
            worksheet_name: Nombre del worksheet
            data_hash: Hash de los datos a escribir
            
        Returns:
            bool: True si es duplicado, False si es nueva
        """
        key = f"{sheet_url}_{worksheet_name}"
        
        if key in self.operation_hashes:
            last_hash, last_time = self.operation_hashes[key]
            if last_hash == data_hash and (time.time() - last_time) < 5:  # 5 segundos de gracia
                return True
        
        # Registrar esta operación
        self.operation_hashes[key] = (data_hash, time.time())
        return False

# Instancia global del manejador de concurrencia
if 'concurrency_manager' not in st.session_state:
    st.session_state.concurrency_manager = SheetConcurrencyManager()

# --- FUNCIÓN DE ACTUALIZACIÓN SEGURA CON CONCURRENCIA ---
def update_sheet_safe(df, worksheet_name="0", sheet_url=None, agente_id=None):
    """Actualiza Google Sheets con control de concurrencia y sanitización
    
    Args:
        df: DataFrame a escribir
        worksheet_name: Nombre o índice del worksheet
        sheet_url: URL del Google Sheet (opcional)
        agente_id: ID del agente que realiza la operación
        
    Returns:
        bool: True si exitoso, False si falló
    """
    try:
        # Sanitizar datos antes de escribir
        df_sanitizado = df.copy()
        
        # Sanitizar columnas de texto
        if 'nombre' in df_sanitizado.columns:
            df_sanitizado['nombre'] = df_sanitizado['nombre'].apply(sanitizar_nombre)
        
        if 'observacion' in df_sanitizado.columns:
            df_sanitizado['observacion'] = df_sanitizado['observacion'].apply(sanitizar_nota)
        
        if 'telefono' in df_sanitizado.columns:
            df_sanitizado['telefono'] = df_sanitizado['telefono'].apply(sanitizar_telefono)
        
        # Generar hash de los datos para detectar duplicados
        data_hash = hashlib.md5(str(df_sanitizado.values.tolist()).encode()).hexdigest()
        
        # Determinar sheet URL
        target_url = sheet_url or URL_SHEET_INFORME
        
        # Verificar si es operación duplicada
        concurrency_manager = st.session_state.concurrency_manager
        if concurrency_manager.is_operation_duplicate(target_url, worksheet_name, data_hash):
            print(f"[CONCURRENCY] Operación duplicada detectada, omitiendo escritura")
            return True
        
        # Adquirir lock de concurrencia
        agente_id = agente_id or st.session_state.get('agente_id', 'unknown')
        if not concurrency_manager.acquire_lock(target_url, worksheet_name, agente_id):
            print(f"[CONCURRENCY] No se pudo adquirir lock para {worksheet_name}")
            return False
        
        try:
            # Realizar la actualización con rate limiting
            rate_limiter.check_and_wait(operation_type="write")
            
            # Determinar qué spreadsheet usar
            if sheet_url:
                rate_limiter.check_and_wait(operation_type="read")
                target_spreadsheet = gc.open_by_url(sheet_url)
            else:
                target_spreadsheet = get_spreadsheet_informe()
            
            # Obtener worksheet
            worksheet = target_spreadsheet.get_worksheet(int(worksheet_name)) if worksheet_name.isdigit() else target_spreadsheet.worksheet(worksheet_name)
            
            # Limpiar y actualizar
            rate_limiter.check_and_wait(operation_type="write")
            worksheet.clear()
            rate_limiter.check_and_wait(operation_type="write")
            worksheet.update([df_sanitizado.columns.values.tolist()] + df_sanitizado.values.tolist())
            
            print(f"[SECURITY] Sheet actualizado exitosamente por {agente_id}")
            return True
            
        finally:
            # Siempre liberar el lock
            concurrency_manager.release_lock(target_url, worksheet_name)
            
    except Exception as e:
        print(f"[SECURITY] Error actualizando sheet seguro: {e}")
        import traceback
        print(traceback.format_exc())
        return False

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
        
        # Definir columnas requeridas en el orden correcto
        columnas_requeridas = ['nombre', 'codigo_pais', 'telefono', 'cedula_agente', 'estado', 'observacion', 
                              'fecha_llamada', 'duracion_seg', 'sid_llamada', 'proxima_llamada', 'agente_id']
        
        if len(data) <= 1:
            print(f"[DEBUG] Sheet de contactos vacío o solo tiene encabezados")
            # Retornar DataFrame vacío pero con las columnas necesarias
            return pd.DataFrame(columns=columnas_requeridas)
        
        # Crear DataFrame con los datos del sheet
        df_todos = pd.DataFrame(data[1:], columns=data[0])
        print(f"[DEBUG] Total contactos en sheet: {len(df_todos)}")
        print(f"[DEBUG] Columnas actuales en Sheet: {list(df_todos.columns)}")
        
        # Verificar que existe la columna cedula_agente
        if 'cedula_agente' not in df_todos.columns:
            print(f"[ERROR] El sheet no tiene la columna 'cedula_agente'")
            return pd.DataFrame(columns=columnas_requeridas)
        
        # Agregar columnas faltantes a TODO el DataFrame (antes de filtrar)
        columnas_faltantes = []
        for col in columnas_requeridas:
            if col not in df_todos.columns:
                df_todos[col] = ''
                columnas_faltantes.append(col)
        
        if columnas_faltantes:
            print(f"[DEBUG] ⚠️ Columnas agregadas al DataFrame: {columnas_faltantes}")
            print(f"[DEBUG] 💡 Estas columnas se agregarán al Sheet cuando se guarde la primera gestión")
        
        # Reordenar columnas para que coincidan con el orden requerido
        df_todos = df_todos[columnas_requeridas]
        
        # RELLENO AUTOMÁTICO INTELIGENTE DE ESTADO
        # Solo rellenar 'Pendiente' si la fila tiene datos válidos (nombre, telefono, cedula_agente)
        # Esto evita rellenar filas vacías infinitas y problemas de quota
        filas_con_datos = (
            (df_todos['nombre'].astype(str).str.strip() != '') & 
            (df_todos['telefono'].astype(str).str.strip() != '') & 
            (df_todos['cedula_agente'].astype(str).str.strip() != '')
        )
        
        # Contar cuántas filas tienen estado vacío pero datos válidos
        estado_vacio = df_todos['estado'].fillna('').astype(str).str.strip() == ''
        filas_a_rellenar = filas_con_datos & estado_vacio
        num_filas_rellenadas = filas_a_rellenar.sum()
        
        if num_filas_rellenadas > 0:
            # Rellenar solo las filas que tienen datos válidos
            df_todos.loc[filas_a_rellenar, 'estado'] = 'Pendiente'
            print(f"[DEBUG] 🔄 Auto-rellenado: {num_filas_rellenadas} filas con estado vacío → 'Pendiente'")
            print(f"[DEBUG] ⚠️ IMPORTANTE: Estas filas se guardarán en el Sheet en la próxima actualización")
        
        # Filtrar por cedula_agente
        df_agente = df_todos[df_todos['cedula_agente'].astype(str) == str(cedula_agente)].copy()
        print(f"[DEBUG] Contactos para agente {cedula_agente}: {len(df_agente)}")
        
        if df_agente.empty:
            print(f"[DEBUG] No hay contactos asignados al agente {cedula_agente}")
            return pd.DataFrame(columns=columnas_requeridas)
        
        # Asignar agente_id si está vacío (solo para contactos del agente)
        df_agente['agente_id'] = df_agente['agente_id'].fillna('').replace('', cedula_agente)
        
        print(f"[DEBUG] ✅ DataFrame cargado con {len(df_agente)} contactos y {len(df_agente.columns)} columnas")
        
        return df_agente
    except Exception as e:
        print(f"[ERROR] Error cargando contactos: {e}")
        import traceback
        print(traceback.format_exc())
        # Retornar DataFrame vacío con columnas en caso de error
        columnas_requeridas = ['nombre', 'codigo_pais', 'telefono', 'cedula_agente', 'estado', 'observacion', 
                              'fecha_llamada', 'duracion_seg', 'sid_llamada', 'proxima_llamada', 'agente_id']
        return pd.DataFrame(columns=columnas_requeridas)

def solicitar_transcripcion(recording_sid):
    """Solicita transcripción de una grabación de Twilio
    
    Args:
        recording_sid: SID de la grabación de Twilio
    
    Returns:
        str: SID de la transcripción si fue exitosa, None en caso contrario
    """
    try:
        print(f"[DEBUG] 🎤 Solicitando transcripción para recording: {recording_sid}")
        
        # Primero verificar si la grabación existe
        recording = client.recordings(recording_sid).fetch()
        print(f"[DEBUG] 📼 Grabación encontrada - Status: {recording.status}, Duration: {recording.duration}s")
        
        # Intentar crear transcripción
        transcription = client.transcriptions.create(recording_sid=recording_sid)
        print(f"[DEBUG] ✅ Transcripción solicitada exitosamente: {transcription.sid}")
        print(f"[DEBUG] 📝 Transcripción Status: {transcription.status}")
        return transcription.sid
    except Exception as e:
        print(f"[ERROR] ❌ Error solicitando transcripción: {e}")
        import traceback
        print(f"[ERROR] Traceback completo: {traceback.format_exc()}")
        
        # Verificar si es un error de configuración
        if "transcription" in str(e).lower():
            print(f"[ERROR] ⚠️ Posible error de configuración de transcripción en Twilio")
        return None

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

# --- AUTO-GUARDADO DE CAMBIOS PENDIENTES ---
if 'ultimo_autoguardado' not in st.session_state:
    st.session_state.ultimo_autoguardado = time.time()
    st.session_state.cambios_pendientes = False

def verificar_autoguardado():
    """Verifica si es necesario auto-guardar cambios pendientes"""
    ahora = time.time()
    
    # Auto-guardar cada 30 segundos si hay cambios pendientes
    if st.session_state.cambios_pendientes and (ahora - st.session_state.ultimo_autoguardado) > 30:
        if URL_SHEET_CONTACTOS and st.session_state.df_contactos is not None:
            try:
                # Usar la función segura con concurrencia y sanitización
                if update_sheet_safe(st.session_state.df_contactos, "0", sheet_url=URL_SHEET_CONTACTOS, agente_id=st.session_state.get('agente_id', 'auto_guardado')):
                    st.session_state.ultimo_autoguardado = ahora
                    st.session_state.cambios_pendientes = False
                    print("[AUTOGUARDADO] ✅ Cambios guardados automáticamente con seguridad")
                    add_log("AUTO_GUARDADO: Cambios sincronizados con seguridad", "SISTEMA")
                else:
                    print("[AUTOGUARDADO] ⚠️ Error guardando cambios, se reintentará en 30s")
            except Exception as e:
                print(f"[AUTOGUARDADO] ❌ Error: {e}")

def marcar_cambios_pendientes():
    """Marca que hay cambios pendientes para auto-guardar"""
    st.session_state.cambios_pendientes = True
    print("[DEBUG] Cambios pendientes marcados para auto-guardado")

# Ejecutar verificación de auto-guardado en cada refresh
verificar_autoguardado()

# --- FUNCIÓN DE VERIFICACIÓN DIFERIDA DE GRABACIONES MEJORADA ---
def verificar_grabaciones_pendientes():
    """
    Verifica grabaciones pendientes con estrategia mejorada:
    - Primera verificación: 30 segundos después de la llamada
    - Verificaciones subsiguientes: Cada 2 minutos durante 15 minutos
    - Después: Cada 5 minutos (comportamiento original)
    """
    try:
        df_informe = read_sheet("0")
        if df_informe.empty:
            return
        
        # Asegurar que existe la columna grabacion_pendiente
        if 'grabacion_pendiente' not in df_informe.columns:
            df_informe['grabacion_pendiente'] = ''
        
        # Filtrar registros con grabación pendiente
        mask_pendientes = (df_informe['grabacion_pendiente'] == 'SI') & (df_informe['url_grabacion'].fillna('') == '')
        if not mask_pendientes.any():
            return
        
        df_pendientes = df_informe[mask_pendientes].copy()
        print(f"[GRABACION] 🔍 Verificando {len(df_pendientes)} grabaciones pendientes")
        
        now = datetime.now()
        grabaciones_actualizadas = 0
        
        for idx, row in df_pendientes.iterrows():
            call_sid = row.get('sid_llamada', '')
            if not call_sid or pd.isna(call_sid):
                continue
            
            try:
                fecha_llamada = pd.to_datetime(row['fecha_llamada'])
                tiempo_transcurrido = (now - fecha_llamada).total_seconds()
            except:
                continue
            
            # ESTRATEGIA MEJORADA DE VERIFICACIÓN
            # - Primera verificación: 30 segundos
            # - Verificaciones frecuentes: Cada 2 mins hasta 15 mins
            # - Verificaciones normales: Cada 5 mins después
            
            debe_verificar = False
            
            if tiempo_transcurrido >= 30 and tiempo_transcurrido < 900:
                # Entre 30 seg y 15 mins: verificar cada 2 minutos
                minutos_transcurridos = int(tiempo_transcurrido / 60)
                if minutos_transcurridos == 0 or (tiempo_transcurrido % 120 < 30):
                    debe_verificar = True
                    print(f"[GRABACION] ⚡ Verificación rápida (30s-15min): {call_sid[:8]}... - {int(tiempo_transcurrido)}s")
            elif tiempo_transcurrido >= 900:
                # Después de 15 mins: verificar cada 5 minutos (original)
                if tiempo_transcurrido % 300 < 30:
                    debe_verificar = True
                    print(f"[GRABACION] 🐌 Verificación normal (>15min): {call_sid[:8]}... - {int(tiempo_transcurrido)}s")
            
            if not debe_verificar:
                continue
            
            # Timeout extendido: 30 minutos en lugar de 15
            if tiempo_transcurrido > 1800:
                df_informe.at[idx, 'grabacion_pendiente'] = 'TIMEOUT'
                grabaciones_actualizadas += 1
                print(f"[GRABACION] ⏰ Timeout extendido para {call_sid[:8]}... ({int(tiempo_transcurrido/60)}min)")
                continue
            
            try:
                recordings = client.recordings.list(call_sid=call_sid, limit=1)
                if recordings:
                    recording_sid = recordings[0].sid
                    url_grabacion = f"https://api.twilio.com{recordings[0].uri.replace('.json', '.mp3')}"
                    df_informe.at[idx, 'url_grabacion'] = url_grabacion
                    df_informe.at[idx, 'grabacion_pendiente'] = 'NO'
                    grabaciones_actualizadas += 1
                    print(f"[GRABACION] ✅ URL encontrada: {call_sid[:8]}... ({int(tiempo_transcurrido)}s)")
                    
                    # Intentar transcripción si hay URL
                    try:
                        transcription_sid = solicitar_transcripcion(recording_sid)
                        if transcription_sid:
                            df_informe.at[idx, 'transcription_sid'] = transcription_sid
                            print(f"[GRABACION] 📝 Transcripción solicitada: {transcription_sid[:8]}...")
                    except Exception as e_trans:
                        print(f"[GRABACION] ⚠️ Error solicitando transcripción: {e_trans}")
                else:
                    print(f"[GRABACION] ❌ Sin grabación aún: {call_sid[:8]}... ({int(tiempo_transcurrido)}s)")
                    
            except Exception as e:
                print(f"[GRABACION] ❌ Error verificando {call_sid[:8]}...: {e}")
        
        if grabaciones_actualizadas > 0:
            if update_sheet(df_informe, "0"):
                print(f"[GRABACION] 💾 {grabaciones_actualizadas} grabaciones actualizadas")
                add_log(f"GRABACIONES_ACTUALIZADAS: {grabaciones_actualizadas}", "DATA")
    except Exception as e:
        print(f"[GRABACION] ❌ Error general verificando grabaciones: {e}")
        add_log(f"ERROR_GRABACIONES: {e}", "ERROR")

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
    
    # Determinar si hay una llamada WebRTC pendiente
    numero_a_llamar = st.session_state.webrtc_numero if st.session_state.webrtc_activo else ''
    
    twilio_webrtc_component = f"""
    <div id="twilio-device-status" style="padding: 10px; background: #f0f0f0; border-radius: 5px; margin-bottom: 10px;">
        <span id="device-status">🔴 Inicializando audio...</span>
    </div>
    
    <script>
    {twilio_sdk_content}
    console.log('✅ Twilio SDK cargado desde archivo local');
    </script>
    <script>
        var device;
        var currentConnection;
        var numeroLlamar = '{numero_a_llamar}';
        
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
            
            try {{
                updateStatus('🟡 Conectando con Twilio...');
                
                // Obtener token con retry automático
                const tokenUrl = `{function_url_base}/token?identity={st.session_state.agente_id}`;
                console.log('🔍 URL del token:', tokenUrl);
                
                let response;
                let retries = 0;
                const maxRetries = 3;
                
                // Retry automático para AccessTokenExpired
                while (retries < maxRetries) {{
                    try {{
                        response = await fetch(tokenUrl);
                        console.log(`📡 Intento ${{retries + 1}} - Respuesta del token: ${{response.status}}`);
                        
                        if (response.ok) {{
                            break; // Token obtenido exitosamente
                        }}
                        
                        const errorText = await response.text();
                        console.error(`❌ Error en intento ${{retries + 1}}: ${{response.status}} - ${{errorText}}`);
                        
                        // Si es AccessTokenExpired, esperar y reintentar
                        if (response.status === 401 || errorText.includes('AccessTokenExpired')) {{
                            retries++;
                            if (retries < maxRetries) {{
                                console.log(`🔄 AccessTokenExpired detectado, reintentando en ${{retries * 2}} segundos...`);
                                updateStatus(`🔄 Token expirado, reintentando (${{retries}}/${{maxRetries}})...`);
                                await new Promise(resolve => setTimeout(resolve, retries * 2000));
                                continue;
                            }}
                        }}
                        
                        // Si no es AccessTokenExpired o se acabaron los reintentos
                        throw new Error(`Error ${{response.status}}: ${{errorText}}`);
                        
                    }} catch (fetchError) {{
                        retries++;
                        if (retries < maxRetries && fetchError.message.includes('AccessTokenExpired')) {{
                            console.log(`🔄 Error de token, reintentando en ${{retries * 2}} segundos...`);
                            await new Promise(resolve => setTimeout(resolve, retries * 2000));
                            continue;
                        }}
                        throw fetchError;
                    }}
                }}
                
                if (!response.ok) {{
                    throw new Error(`No se pudo obtener token después de ${{maxRetries}} intentos`);
                }}
                
                const data = await response.json();
                console.log('✅ Token obtenido exitosamente');
                console.log('🔍 Verificando namespace Twilio:', typeof Twilio, Object.keys(Twilio));
                
                // Crear Device con SDK v2.x (usando opciones simplificadas)
                updateStatus('🟡 Configurando dispositivo...');
                device = new Twilio.Device(data.token, {{
                    logLevel: 1,
                    edge: 'ashburn'
                }});
                
                // Event listeners para SDK v2.x
                device.on('registered', function() {{
                    console.log('✅ Twilio Device registrado');
                    updateStatus('🟢 Audio listo - WebRTC conectado');
                    
                    // Si hay un número pendiente, llamar automáticamente
                    if (numeroLlamar && numeroLlamar !== '') {{
                        console.log('🚀 Ejecutando llamada automática a:', numeroLlamar);
                        setTimeout(function() {{
                            llamarWebRTC(numeroLlamar);
                        }}, 500);
                    }}
                }});
                
                device.on('error', function(error) {{
                    console.error('❌ Error Twilio Device:', error);
                    updateStatus('🔴 Error: ' + (error.message || 'Error desconocido'));
                }});
                
                device.on('incoming', function(call) {{
                    console.log('📞 Llamada entrante');
                    call.accept();
                }});
                
                // Registrar Device (SDK v2.x)
                updateStatus('🟡 Registrando dispositivo...');
                await device.register();
                console.log('✅ Device registrado exitosamente');
                
            }} catch(error) {{
                console.error('❌ Error inicializando Twilio:', error);
                updateStatus('🔴 Error: ' + error.message);
            }}
        }}
        
        // Función para hacer llamadas WebRTC
        async function llamarWebRTC(numero) {{
            if (!device) {{
                alert('⚠️ WebRTC no está inicializado. Espera a que aparezca "Audio listo"');
                return;
            }}
            
            console.log('📞 Iniciando llamada WebRTC a:', numero);
            
            try {{
                // Usar params en lugar de To para enviar parámetros personalizados
                const params = {{
                    params: {{
                        phoneNumber: numero
                    }}
                }};
                
                console.log('🔍 Parámetros enviados:', JSON.stringify(params));
                currentConnection = await device.connect(params);
                console.log('✅ Conexión establecida:', currentConnection);
                
                // Eventos del Call object
                currentConnection.on('accept', function() {{
                    console.log('✅ Llamada aceptada/conectada');
                }});
                
                currentConnection.on('disconnect', function() {{
                    console.log('📴 Llamada finalizada - Limpiando estado automáticamente');
                    currentConnection = null;
                    
                    // Notificar a Streamlit que la llamada terminó
                    // Esto limpiará el estado webrtc_activo automáticamente
                    setTimeout(function() {{
                        if (window.parent && window.parent.postMessage) {{
                            window.parent.postMessage({{
                                type: 'webrtc_disconnect',
                                timestamp: new Date().toISOString()
                            }}, '*');
                        }}
                    }}, 100);
                }});
                
                currentConnection.on('error', function(error) {{
                    console.error('❌ Error en llamada:', error);
                    alert('❌ Error: ' + error.message);
                }});
                
                currentConnection.on('reject', function() {{
                    console.log('❌ Llamada rechazada');
                    currentConnection = null;
                }});
                
            }} catch(error) {{
                console.error('❌ Error iniciando llamada:', error);
                alert('❌ Error: ' + error.message);
            }}
        }}
        
        window.llamarWebRTC = llamarWebRTC;
        
        window.colgarWebRTC = function() {{
            if (currentConnection) {{
                currentConnection.disconnect();
            }}
        }};
        
        // Inicializar Twilio Device cuando el DOM esté listo
        setTimeout(initTwilioDevice, 100);
    </script>
    """
    
    import streamlit.components.v1 as components
    components.html(twilio_webrtc_component, height=50)

with tab_op:
    # Verificar grabaciones pendientes en segundo plano
    verificar_grabaciones_pendientes()
    
    if st.session_state.df_contactos is not None:
        search = st.text_input("🔍 Buscar Cliente:").lower()
        df = st.session_state.df_contactos
        
        opc = st.radio("Ver:", ["Pendientes", "No Contestaron", "Programadas", "Gestionadas"], horizontal=True)
        # Lógica de mapeo de pestaña a estado del DF
        f_est = "Pendiente" if "Pendientes" in opc else "No Contesto" if "No Contestaron" in opc else "Programada" if "Programadas" in opc else "Gestionado"
        
        # Filtrado riguroso
        if "Gestionadas" in opc:
            # Para "Gestionadas": mostrar contactos que contestaron la llamada (solo 'Llamado')
            df_work = df[df['estado'] == 'Llamado']
        else:
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
                        # Mostrar información de programación si está programada
                        if c['estado'] == 'Programada' and pd.notna(c.get('proxima_llamada')) and c.get('proxima_llamada'):
                            try:
                                fecha_prog = pd.to_datetime(c['proxima_llamada'])
                                fecha_formateada = fecha_prog.strftime("%Y-%m-%d %H:%M")
                                st.markdown(f"""
                                <div style="background-color: #e3f2fd; padding: 10px; border-radius: 8px; border-left: 4px solid #2196f3; margin-bottom: 10px;">
                                    <strong>📅 Programado para:</strong> {fecha_formateada}<br>
                                    <small>⏰ Faltan {(fecha_prog - datetime.now()).total_seconds() / 3600:.1f} horas</small>
                                </div>
                                """, unsafe_allow_html=True)
                            except Exception as e:
                                st.info(f"📅 Programado para: {c['proxima_llamada']}")
                        
                        st.markdown(f"<div class='client-card'><h3>{c['nombre']}</h3><p>Tel: {tel}</p></div>", unsafe_allow_html=True)
                        nota_existente = st.session_state.draft_notas.get(idx, c['observacion'])
                        nota = st.text_area("📝 Notas:", value=nota_existente, key=f"notas_{idx}")
                        
                        # Auto-guardar cuando el agente modifica notas
                        if nota != nota_existente:
                            # Actualizar nota local inmediatamente
                            st.session_state.df_contactos.at[idx, 'observacion'] = nota
                            # Marcar para auto-guardado
                            marcar_cambios_pendientes()
                        
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
                                        
                                        # Guardar el SID de la llamada del cliente y el nombre de la conferencia (para tracking)
                                        conference_name = f"Room_{st.session_state.agente_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                                        st.session_state.llamada_activa_sid = call_cliente.sid
                                        st.session_state.conference_name = conference_name
                                        st.session_state.conference_idx = idx  # Guardar el índice del contacto activo
                                        st.session_state.t_inicio_dt = datetime.now()
                                        print(f"[DEBUG] Conference creada: {conference_name}")
                                        
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
                                    # Marcar WebRTC como activo y guardar datos
                                    st.session_state.webrtc_activo = True
                                    st.session_state.webrtc_numero = tel
                                    st.session_state.webrtc_nombre = c['nombre']
                                    st.session_state.webrtc_idx = idx  # Guardar el índice del contacto activo
                                    st.session_state.t_inicio_dt = datetime.now()
                                    add_log(f"WEBRTC_START: {c['nombre']} - {tel}", "TWILIO")
                                    st.rerun()
                            else:
                                # --- MONITOR DINÁMICO ---
                                
                                # Verificar si es llamada WebRTC Y si este es el contacto activo
                                if st.session_state.webrtc_activo and st.session_state.get('webrtc_idx') == idx:
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
                                                # Actualizar el tiempo de inicio cuando la llamada realmente se conecta
                                                st.session_state.t_inicio_dt = datetime.now()
                                                print(f"[DEBUG] WebRTC Call SID encontrado: {calls[0].sid}")
                                                st.success(f"🔗 Llamada conectada: {calls[0].sid[:8]}...")
                                        except Exception as e:
                                            print(f"[ERROR] Error buscando SID de llamada WebRTC: {e}")
                                    
                                    # Verificar si la llamada sigue activa en Twilio
                                    call_ended_by_remote = False
                                    webrtc_final_status = 'Llamado'  # Por defecto
                                    
                                    if st.session_state.webrtc_call_sid:
                                        try:
                                            remote_call = client.calls(st.session_state.webrtc_call_sid).fetch()
                                            print(f"[DEBUG] WebRTC - Estado Twilio: {remote_call.status}")
                                            
                                            # Si la llamada terminó, determinar el estado final
                                            if remote_call.status in ['completed', 'no-answer', 'busy', 'failed', 'canceled']:
                                                call_ended_by_remote = True
                                                
                                                # Obtener datos de la llamada para clasificación
                                                answered_by = str(remote_call.answered_by) if hasattr(remote_call, 'answered_by') and remote_call.answered_by else 'unknown'
                                                duracion_twilio = int(remote_call.duration) if remote_call.duration else 0
                                                error_code = str(remote_call.error_code) if hasattr(remote_call, 'error_code') and remote_call.error_code else None
                                                print(f"[DEBUG] WebRTC - answered_by: {answered_by}, status: {remote_call.status}, duration: {duracion_twilio}s, error_code: {error_code}")
                                                
                                                # CLASIFICACIÓN AUTOMÁTICA MEJORADA DE ESTADOS
                                                
                                                # PRIORIDAD ALTA 1: Número inválido/inexistente
                                                if remote_call.status == 'failed' and error_code in ['21217', '21214', '21211', '21612']:
                                                    webrtc_final_status = 'No Contesto'
                                                    st.error(f"❌ Número inválido o inexistente (error {error_code})")
                                                    print(f"[DEBUG] Clasificado como No Contesto - Número inválido: {error_code}")
                                                
                                                # PRIORIDAD MEDIA 1: Número bloqueado/spam
                                                elif remote_call.status == 'failed' and error_code in ['21610', '30006']:
                                                    webrtc_final_status = 'No Contesto'
                                                    st.error(f"🚫 Número bloqueado o marcado como spam (error {error_code})")
                                                    print(f"[DEBUG] Clasificado como No Contesto - Número bloqueado: {error_code}")
                                                
                                                # PRIORIDAD MEDIA 2: Error de red (podría reintentar)
                                                elif remote_call.status == 'failed' and error_code in ['31005', '31002', '31003', '31009']:
                                                    webrtc_final_status = 'No Contesto'
                                                    st.warning(f"⚠️ Error de red - Considerar reintento (error {error_code})")
                                                    print(f"[DEBUG] Clasificado como No Contesto - Error de red: {error_code}")
                                                
                                                # Caso 1: Celular apagado, ocupado, falló o cancelado (sin error_code específico)
                                                elif remote_call.status in ['no-answer', 'busy', 'canceled']:
                                                    webrtc_final_status = 'No Contesto'
                                                    st.warning(f"⚠️ Llamada no contestada: {remote_call.status}")
                                                    print(f"[DEBUG] Clasificado como No Contesto por status: {remote_call.status}")
                                                
                                                # Caso 2: Fallo genérico
                                                elif remote_call.status == 'failed':
                                                    webrtc_final_status = 'No Contesto'
                                                    st.warning(f"⚠️ Llamada falló: error {error_code or 'desconocido'}")
                                                    print(f"[DEBUG] Clasificado como No Contesto - Fallo genérico")
                                                
                                                # PRIORIDAD ALTA 3: Buzón de voz mejorado
                                                elif answered_by in ['machine_start', 'fax']:
                                                    if duracion_twilio < 5:
                                                        webrtc_final_status = 'No Contesto'
                                                        st.warning(f"📞 Buzón lleno o no dejó mensaje ({duracion_twilio}s)")
                                                        print(f"[DEBUG] Clasificado como No Contesto - Buzón lleno")
                                                    else:
                                                        webrtc_final_status = 'No Contesto'
                                                        st.warning(f"📞 Contestó buzón de voz ({duracion_twilio}s)")
                                                        print(f"[DEBUG] Clasificado como No Contesto - Buzón de voz")
                                                
                                                # Caso 3: Contestó una persona (humano)
                                                elif answered_by == 'human':
                                                    webrtc_final_status = 'Llamado'
                                                    st.success(f"✅ Llamada contestada por persona")
                                                    print(f"[DEBUG] Clasificado como Llamado por humano")
                                                
                                                # PRIORIDAD ALTA 2: Cliente colgó inmediatamente vs No contestó
                                                elif remote_call.status == 'completed' and answered_by == 'unknown':
                                                    if duracion_twilio == 0:
                                                        webrtc_final_status = 'No Contesto'
                                                        st.warning(f"⚠️ Llamada sin conexión (0s)")
                                                        print(f"[DEBUG] Clasificado como No Contesto - Sin conexión")
                                                    elif 0 < duracion_twilio < 3:
                                                        webrtc_final_status = 'No Contesto'
                                                        st.warning(f"⚠️ Cliente rechazó la llamada ({duracion_twilio}s)")
                                                        print(f"[DEBUG] Clasificado como No Contesto - Rechazó inmediatamente: {duracion_twilio}s")
                                                    elif 3 <= duracion_twilio < 10:
                                                        webrtc_final_status = 'No Contesto'
                                                        st.warning(f"⚠️ Llamada muy corta ({duracion_twilio}s) - Probablemente no contestó")
                                                        print(f"[DEBUG] Clasificado como No Contesto por duración corta: {duracion_twilio}s")
                                                    else:
                                                        webrtc_final_status = 'Llamado'
                                                        st.success(f"✅ Llamada completada ({duracion_twilio}s) - Conversación establecida")
                                                        print(f"[DEBUG] Clasificado como Llamado por duración suficiente: {duracion_twilio}s")
                                                
                                                # Caso por defecto
                                                else:
                                                    webrtc_final_status = 'Llamado'
                                                    st.info(f"ℹ️ Llamada terminada: {remote_call.status}")
                                                    print(f"[DEBUG] Clasificado como Llamado por defecto")
                                                
                                                print(f"[DEBUG] ✅ Estado final determinado: {webrtc_final_status}")
                                        except Exception as e:
                                            print(f"[ERROR] Error verificando estado WebRTC: {e}")
                                    
                                    # Botones en columnas (SIEMPRE mostrar durante llamada activa)
                                    finalizar_webrtc = False
                                    pausar_webrtc = False
                                    
                                    if not call_ended_by_remote:
                                        btn_webrtc_col1, btn_webrtc_col2 = st.columns(2)
                                        
                                        with btn_webrtc_col1:
                                            finalizar_webrtc = st.button("✅ FINALIZAR WebRTC", type="primary", key=f"fin_webrtc_{idx}")
                                        
                                        with btn_webrtc_col2:
                                            if not st.session_state.grabacion_pausada:
                                                pausar_webrtc = st.button("⏸️ PAUSAR GRABACIÓN", key=f"pause_webrtc_{idx}")
                                            else:
                                                st.info("🔴 Grabación pausada")
                                    else:
                                        # Si la llamada terminó remotamente, marcar para finalizar automáticamente
                                        finalizar_webrtc = True
                                    
                                    if pausar_webrtc:
                                        # Calcular duración hasta el momento
                                        dur_pausa = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                                        
                                        print(f"[DEBUG] Intentando pausar grabación WebRTC para call_sid: {st.session_state.webrtc_call_sid}")
                                        print(f"[DEBUG] ⚠️ WebRTC no permite pausar grabación DURANTE la llamada")
                                        print(f"[DEBUG] La grabación se crea después de finalizar la llamada")
                                        
                                        # Explicar al usuario la limitación de WebRTC
                                        st.error("⚠️ **WebRTC no permite pausar grabación durante la llamada**")
                                        st.info("📝 **La grabación se guardará automáticamente cuando finalices la llamada**")
                                        
                                        # Opción: Finalizar llamada ahora para guardar grabación parcial
                                        if st.button("📞 Finalizar llamada ahora", key=f"finish_for_recording_{idx}"):
                                            print(f"[DEBUG] Finalizando llamada para guardar grabación parcial...")
                                            finalizar_webrtc = True
                                            st.success("📞 Finalizando llamada para guardar grabación...")
                                            st.rerun()
                                        
                                        # Opción: Pausar la grabación en Twilio si tenemos el SID
                                        if st.session_state.webrtc_call_sid:
                                            print(f"[DEBUG] Intentando pausar grabación {st.session_state.webrtc_call_sid}...")
                                            try:
                                                # Primero verificar si existe la grabación
                                                recordings = client.recordings.list(call_sid=st.session_state.webrtc_call_sid, limit=1)
                                                print(f"[DEBUG] Grabaciones encontradas: {len(recordings)}")
                                                
                                                if recordings:
                                                    recording = recordings[0]
                                                    print(f"[DEBUG] Grabación SID: {recording.sid}")
                                                    print(f"[DEBUG] Grabación Status: {recording.status}")
                                                    print(f"[DEBUG] Grabación Duration: {recording.duration}")
                                                    
                                                    # Intentar pausar
                                                    print(f"[DEBUG] Intentando pausar grabación {recording.sid}...")
                                                    client.recordings(recording.sid).update(status='paused')
                                                    print(f"[DEBUG] ✅ Grabación pausada exitosamente")
                                                    st.success("⏸️ Grabación pausada en Twilio")
                                                else:
                                                    print(f"[DEBUG] ⚠️ No se encontraron grabaciones activas para {st.session_state.webrtc_call_sid}")
                                                    st.warning("⚠️ No hay grabación activa para pausar")
                                                    
                                                # Guardar en Sheet Informe con estado "Grabación Pausada"
                                                if guardar_en_sheet_informe(c, tel, "Grabación Pausada", nota, dur_pausa, st.session_state.webrtc_call_sid or ''):
                                                    st.session_state.grabacion_pausada = True
                                                    add_log(f"WEBRTC_GRABACION_PAUSADA: {c['nombre']} - {dur_pausa}s", "ACCION")
                                                    st.success("✅ Grabación pausada y guardada en Sheet Informe")
                                                else:
                                                    st.error("❌ Error guardando en Sheet Informe")
                                                    
                                            except Exception as e:
                                                print(f"[ERROR] Error pausando grabación WebRTC: {e}")
                                                import traceback
                                                print(f"[ERROR] Traceback: {traceback.format_exc()}")
                                                st.error(f"❌ Error pausando grabación: {e}")
                                        else:
                                            print(f"[DEBUG] ⚠️ No hay webrtc_call_sid disponible")
                                            st.warning("⚠️ No hay SID de llamada WebRTC disponible")
                                        
                                        time.sleep(1)
                                        st.rerun()
                                    
                                    # Manejar finalización de WebRTC (manual o automática)
                                    if finalizar_webrtc or call_ended_by_remote:
                                        # Si es finalización manual, colgar la llamada en Twilio primero
                                        if finalizar_webrtc and st.session_state.webrtc_call_sid:
                                            try:
                                                client.calls(st.session_state.webrtc_call_sid).update(status='completed')
                                                time.sleep(1)
                                            except Exception as e:
                                                print(f"[ERROR] Error colgando llamada: {e}")
                                        
                                        # Guardar gestión
                                        t_fin = datetime.now()
                                        dur = int((t_fin - st.session_state.t_inicio_dt).total_seconds())
                                        
                                        # --- PASO 1: ACTUALIZACIÓN LOCAL INMEDIATA ---
                                        print(f"[DEBUG] Actualizando DataFrame local para idx={idx}")
                                        st.session_state.df_contactos.at[idx, 'estado'] = webrtc_final_status  # Mantener Llamado/No Contesto
                                        st.session_state.df_contactos.at[idx, 'observacion'] = nota
                                        st.session_state.df_contactos.at[idx, 'duracion_seg'] = dur
                                        st.session_state.df_contactos.at[idx, 'agente_id'] = st.session_state.agente_id
                                        st.session_state.df_contactos.at[idx, 'fecha_llamada'] = t_fin.strftime("%Y-%m-%d %H:%M:%S")
                                        st.session_state.df_contactos.at[idx, 'sid_llamada'] = st.session_state.webrtc_call_sid or ''
                                        
                                        # Marcar como gestionado en campo adicional (si existe) o mantener estado original
                                        # El estado real (Llamado/No Contesto) se mantiene en 'estado'
                                        print(f"[DEBUG] DataFrame local actualizado. Estado: {webrtc_final_status}")
                                        
                                        # --- PASO 2: SINCRONIZACIÓN CON SHEET INFORME ---
                                        print(f"[DEBUG] Iniciando sincronización con Sheet Informe")
                                        st.write(f" Guardando gestión: {webrtc_final_status}")
                                        
                                        if URL_SHEET_INFORME:
                                            try:
                                                st.write(" Sincronizando con Sheet Informe...")
                                                
                                                # Obtener información adicional de Twilio
                                                url_grabacion = ''
                                                precio_llamada = '0'
                                                duracion_facturada = '0'
                                                estado_respuesta = ''
                                                codigo_error = ''
                                                
                                                try:
                                                    # Obtener TODOS los datos de la llamada de Twilio
                                                    if st.session_state.webrtc_call_sid:
                                                        call_data = client.calls(st.session_state.webrtc_call_sid).fetch()
                                                        
                                                        # Datos básicos
                                                        precio_llamada = str(call_data.price) if call_data.price else '0'
                                                        duracion_facturada = str(call_data.duration) if call_data.duration else '0'
                                                        estado_respuesta = str(call_data.answered_by) if call_data.answered_by else 'unknown'
                                                        codigo_error = str(call_data.error_code) if hasattr(call_data, 'error_code') and call_data.error_code else ''
                                                        
                                                        # Datos adicionales de Twilio Call Recording
                                                        account_sid = str(call_data.account_sid) if hasattr(call_data, 'account_sid') else ''
                                                        start_time = str(call_data.start_time) if hasattr(call_data, 'start_time') and call_data.start_time else ''
                                                        end_time = str(call_data.end_time) if hasattr(call_data, 'end_time') and call_data.end_time else ''
                                                        from_number = str(call_data.from_) if hasattr(call_data, 'from_') else ''
                                                        to_number = str(call_data.to) if hasattr(call_data, 'to') else ''
                                                        direction = str(call_data.direction) if hasattr(call_data, 'direction') else ''
                                                        status = str(call_data.status) if hasattr(call_data, 'status') else ''
                                                        price_unit = str(call_data.price_unit) if hasattr(call_data, 'price_unit') else 'USD'
                                                        call_type = 'client' if from_number.startswith('client:') else 'phone'
                                                        date_created = str(call_data.date_created) if hasattr(call_data, 'date_created') and call_data.date_created else ''
                                                        parent_call_sid = str(call_data.parent_call_sid) if hasattr(call_data, 'parent_call_sid') and call_data.parent_call_sid else ''
                                                        phone_number_sid = str(call_data.phone_number_sid) if hasattr(call_data, 'phone_number_sid') and call_data.phone_number_sid else ''
                                                        
                                                        print(f"[DEBUG] Datos de llamada obtenidos: duration={duracion_facturada}s, answered_by={estado_respuesta}, from={from_number}, to={to_number}")
                                                    
                                                    # Esperar 5 segundos para que la grabación esté disponible
                                                    st.write(" Esperando grabación (5s)...")
                                                    time.sleep(5)
                                                    
                                                    # Intentar obtener la grabación con retry (máximo 3 intentos)
                                                    max_intentos = 3
                                                    transcription_sid = None
                                                    
                                                    for intento in range(max_intentos):
                                                        recordings = client.recordings.list(call_sid=st.session_state.webrtc_call_sid, limit=1)
                                                        if recordings:
                                                            recording = recordings[0]
                                                            url_grabacion = f"https://api.twilio.com{recording.uri.replace('.json', '.mp3')}"
                                                            print(f"[DEBUG] Grabación encontrada: {url_grabacion}")
                                                            st.success(" Grabación disponible")
                                                            
                                                            # PCI Mode no permite transcripciones automáticas - Grabación solamente
                                                            st.info(" PCI Mode - Solo grabación disponible")
                                                            print(f"[DEBUG] PCI Mode detectado - Transcripción no disponible")
                                                            print(f"[DEBUG] Grabación guardada: {recording.sid}")
                                                            
                                                            # No intentar transcripción en PCI Mode para evitar errores
                                                            transcription_sid = None
                                                            
                                                            break
                                                        else:
                                                            print(f"[DEBUG] Intento {intento + 1}/{max_intentos}: Grabación no disponible aún")
                                                            if intento < max_intentos - 1:
                                                                st.write(f" Reintentando obtener grabación ({intento + 2}/{max_intentos})...")
                                                                time.sleep(3)
                                                            else:
                                                                st.warning(" Grabación no disponible aún - Se guardará sin URL")
                                                                print(f"[WARNING] Grabación no encontrada después de {max_intentos} intentos")
                                                    
                                                except Exception as e_twilio:
                                                    print(f"[DEBUG] Error obteniendo datos Twilio: {e_twilio}")
                                                    st.warning(f" Error obteniendo datos de Twilio: {e_twilio}")
                                                 
                                                # Preparar fila para Sheet Informe con TODAS las columnas de Twilio
                                                fila_informe = pd.DataFrame({
                                                    # Columnas del sistema
                                                    'agente_id': [st.session_state.agente_id],
                                                    'nombre': [c['nombre']],
                                                    'telefono': [tel],
                                                    'estado': [webrtc_final_status],  # Mantener Llamado/No Contesto real
                                                    'observacion': [nota],
                                                    'duracion_seg': [dur],
                                                    'fecha_llamada': [t_fin.strftime("%Y-%m-%d %H:%M:%S")],
                                                    
                                                    # Columnas de Twilio Call Recording
                                                    'call_sid': [st.session_state.webrtc_call_sid or ''],
                                                    'account_sid': [account_sid if 'account_sid' in locals() else ''],
                                                    'start_time': [start_time if 'start_time' in locals() else ''],
                                                    'end_time': [end_time if 'end_time' in locals() else ''],
                                                    'duration': [duracion_facturada],
                                                    'from': [from_number if 'from_number' in locals() else ''],
                                                    'to': [to_number if 'to_number' in locals() else tel],
                                                    'direction': [direction if 'direction' in locals() else ''],
                                                    'status': [status if 'status' in locals() else ''],
                                                    'price': [precio_llamada],
                                                    'price_unit': [price_unit if 'price_unit' in locals() else 'USD'],
                                                    'answered_by': [estado_respuesta],
                                                    'type': [call_type if 'call_type' in locals() else ''],
                                                    'date_created': [date_created if 'date_created' in locals() else ''],
                                                    'parent_call_sid': [parent_call_sid if 'parent_call_sid' in locals() else ''],
                                                    'phone_number_sid': [phone_number_sid if 'phone_number_sid' in locals() else ''],
                                                    'error_code': [codigo_error],
                                                    'url_grabacion': [url_grabacion],
                                                    'transcription_sid': [transcription_sid if 'transcription_sid' in locals() else ''],
                                                    'grabacion_pendiente': ['SI' if not url_grabacion else 'NO']
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
                                                    
                                                    st.write(f" Registros en Informe: {len(df_informe_actual)}")
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
                                                    st.success(f" Guardado en Sheet Informe: {webrtc_final_status}")
                                                    add_log(f"WEBRTC_SYNC_INFORME: {c['nombre']} - {webrtc_final_status}", "DATA")
                                                    
                                                    if not url_grabacion:
                                                        st.info(" Grabación pendiente - Se verificará en 5 minutos")
                                                        print(f"[GRABACION] Marcada como pendiente en Sheet Informe")
                                                else:
                                                    st.warning(" Error guardando en Sheet Informe")
                                                    
                                            except Exception as e_informe:
                                                st.error(f" Error en Sheet Informe: {e_informe}")
                                        
                                        # --- PASO 3: ACTUALIZACIÓN DE SHEET LLAMADAS (campo estado) ---
                                        print(f"[DEBUG] WebRTC - Actualizando estado en Sheet Llamadas")
                                        if URL_SHEET_CONTACTOS:
                                            try:
                                                st.write(" Actualizando estado en Sheet Llamadas...")
                                                
                                                # Actualizar el DataFrame completo y escribirlo de vuelta al Sheet CORRECTO
                                                if update_sheet(st.session_state.df_contactos, "0", sheet_url=URL_SHEET_CONTACTOS):
                                                    st.success(" Estado actualizado en Sheet Llamadas")
                                                    add_log(f"WEBRTC_SYNC_LLAMADAS: {c['nombre']} - {webrtc_final_status}", "DATA")
                                                else:
                                                    st.warning(" Error actualizando Sheet Llamadas")
                                            except Exception as e_llamadas:
                                                st.error(f" Error en Sheet Llamadas: {e_llamadas}")
                                                print(f"[ERROR] WebRTC Update Llamadas: {e_llamadas}")
                                        
                                        add_log(f"WEBRTC_END: {st.session_state.webrtc_nombre} - {dur}s", "TWILIO")
                                        
                                        # --- PASO 4: LIMPIEZA DE ESTADO ---
                                        print(f"[DEBUG] WebRTC - Limpiando estado de llamada")
                                        st.session_state.webrtc_activo = False
                                        st.session_state.webrtc_numero = None
                                        st.session_state.webrtc_nombre = None
                                        st.session_state.webrtc_call_sid = None
                                        st.session_state.webrtc_idx = None
                                        st.session_state.grabacion_pausada = False
                                        
                                        st.success(" Llamada WebRTC finalizada - Pasando al siguiente contacto...")
                                        time.sleep(2)
                                        st.rerun()
                                    else:
                                        # Auto-refresh para actualizar cronómetro y detectar cambios de estado
                                        time.sleep(1)
                                        st.rerun()

                                # Monitor para Conference Call Y si este es el contacto activo
                            if st.session_state.llamada_activa_sid is not None and not st.session_state.webrtc_activo and st.session_state.get('conference_idx') == idx:
                                try:
                                    print(f"[DEBUG] Iniciando monitoreo de llamada Conference...")
                                    
                                    # CRONÓMETRO EN TIEMPO REAL
                                    tiempo_transcurrido = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                                    minutos = tiempo_transcurrido // 60
                                    segundos = tiempo_transcurrido % 60
                                    st.markdown(f" ### Tiempo: {minutos:02d}:{segundos:02d}")
                                    
                                    # 1. Consultar estado real en Twilio
                                    print(f"[DEBUG] Consultando estado de llamada: {st.session_state.llamada_activa_sid}")
                                    remote = client.calls(st.session_state.llamada_activa_sid).fetch()
                                    print(f"[DEBUG] Estado Twilio obtenido: {remote.status}")
                                    st.info(f" Estado Twilio: {remote.status}")
                                    
                                    # 2. Definir condiciones de terminación
                                    call_ended_by_system = remote.status in ['completed', 'no-answer', 'busy', 'failed', 'canceled']
                                    print(f"[DEBUG] call_ended_by_system = {call_ended_by_system}")
                                    
                                    # 3. Detectar casos especiales y colgar automáticamente
                                    answered_by = str(remote.answered_by) if hasattr(remote, 'answered_by') and remote.answered_by else 'unknown'
                                    es_maquina = answered_by in ['machine_start', 'fax']
                                    
                                    # PRIORIDAD MEDIA 3: Timeout de conferencia INTELIGENTE (>60s con 1 solo participante)
                                    if not call_ended_by_system and tiempo_transcurrido > 60 and remote.status == 'in-progress':
                                        try:
                                            # Verificar cuántos participantes hay en la conferencia
                                            conference_name = st.session_state.get('conference_name', None)
                                            num_participantes = 0
                                            
                                            if conference_name:
                                                # Buscar la conferencia por nombre
                                                conferences = client.conferences.list(friendly_name=conference_name, status='in-progress', limit=1)
                                                
                                                if conferences:
                                                    conference_sid = conferences[0].sid
                                                    # Contar participantes activos
                                                    participants = client.conferences(conference_sid).participants.list()
                                                    num_participantes = len([p for p in participants if p.status in ['connected', 'in-progress']])
                                                    print(f"[DEBUG] Conference {conference_name}: {num_participantes} participantes activos")
                                                    
                                                    # Solo colgar si hay 1 solo participante (agente o cliente esperando solo)
                                                    if num_participantes == 1:
                                                        st.warning(f" Timeout: Solo 1 participante después de {tiempo_transcurrido}s - Finalizando...")
                                                        client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                                                        print(f"[DEBUG] Llamada finalizada automáticamente - 1 participante solo")
                                                        call_ended_by_system = True
                                                        time.sleep(2)
                                                        st.rerun()
                                                    elif num_participantes >= 2:
                                                        # Ambos están en la llamada - NO colgar
                                                        print(f"[DEBUG] Conference activa con {num_participantes} participantes - NO timeout")
                                                    else:
                                                        # 0 participantes - conferencia vacía
                                                        st.warning(f" Conferencia vacía - Finalizando...")
                                                        client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                                                        call_ended_by_system = True
                                                        time.sleep(2)
                                                        st.rerun()
                                                else:
                                                    print(f"[DEBUG] No se encontró conferencia activa: {conference_name}")
                                            else:
                                                print(f"[DEBUG] No hay conference_name en session_state")
                                                
                                        except Exception as e:
                                            print(f"[ERROR] Error verificando participantes de conferencia: {e}")
                                            # Si hay error, aplicar timeout simple como fallback
                                            st.warning(f" Timeout de conferencia ({tiempo_transcurrido}s) - Finalizando...")
                                            try:
                                                client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                                                call_ended_by_system = True
                                                time.sleep(2)
                                                st.rerun()
                                            except Exception as e2:
                                                print(f"[ERROR] Error finalizando por timeout: {e2}")
                                                st.error(f"Error: {e2}")
                                    
                                    # Colgar automáticamente si es máquina
                                    elif es_maquina and not call_ended_by_system:
                                        st.warning(f" Máquina/Buzón detectado: {answered_by} - Finalizando automáticamente...")
                                        try:
                                            # Colgar la llamada automáticamente
                                            client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                                            print(f"[DEBUG] Llamada Conference colgada manualmente")
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
                                            finalizar_manual = st.button(" FINALIZAR GESTIÓN", type="primary")
                                        with btn_col2:
                                            if not st.session_state.grabacion_pausada:
                                                pausar_grabacion = st.button(" PAUSAR GRABACIÓN")
                                            else:
                                                st.info(" Grabación pausada")
                                        
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
                                                        st.success(" Grabación pausada y guardada en Sheet Informe")
                                                    else:
                                                        st.error("Error guardando en Sheet Informe")
                                                    
                                                    time.sleep(1)
                                                    st.rerun()
                                            except Exception as e:
                                                st.error(f"Error pausando grabación: {e}")
                                    else:
                                        st.warning(f" Llamada terminada automáticamente: {remote.status}")
                                    
                                    # 4. Accion de Finalización (Manual o Automática)
                                    print(f"[DEBUG] finalizar_manual={finalizar_manual}, call_ended_by_system={call_ended_by_system}")
                                    if finalizar_manual or call_ended_by_system:
                                        print(f"[DEBUG] ENTRANDO AL BLOQUE DE FINALIZACIÓN")
                                        
                                        # Marcar que fue finalización manual por el agente
                                        if finalizar_manual:
                                            st.session_state.finalizacion_manual_agente = True
                                            print(f"[DEBUG] Finalización manual por agente marcada")
                                        else:
                                            st.session_state.finalizacion_manual_agente = False
                                        
                                        # Si es finalización manual, colgar la llamada en Twilio primero
                                        if finalizar_manual and st.session_state.llamada_activa_sid:
                                            try:
                                                client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                                                time.sleep(1)
                                                print(f"[DEBUG] Llamada Conference colgada manualmente")
                                            except Exception as e:
                                                print(f"[ERROR] Error colgando llamada Conference: {e}")
                                        
                                        # Obtener datos de la llamada para clasificación
                                        answered_by = str(remote.answered_by) if hasattr(remote, 'answered_by') and remote.answered_by else 'unknown'
                                        duracion_twilio = int(remote.duration) if remote.duration else 0
                                        error_code = str(remote.error_code) if hasattr(remote, 'error_code') and remote.error_code else None
                                        print(f"[DEBUG] Conference - answered_by: {answered_by}, status: {remote.status}, duration: {duracion_twilio}s, error_code: {error_code}")
                                        
                                        # CLASIFICACIÓN AUTOMÁTICA MEJORADA DE ESTADOS (igual que WebRTC)
                                        
                                        # PRIORIDAD ALTA 1: Si fue finalizada manualmente por el agente (botón "FINALIZAR GESTIÓN")
                                        if st.session_state.get('finalizacion_manual_agente', False):
                                            final_status = 'Llamado'
                                            print(f"[DEBUG] Conference - Finalización manual por agente - Clasificado como Llamado")
                                        # PRIORIDAD ALTA 2: Número inválido/inexistente
                                        elif remote.status == 'failed' and error_code in ['21217', '21214', '21211', '21612']:
                                            final_status = 'No Contesto'
                                            st.error(f"❌ Número inválido o inexistente (error {error_code})")
                                            print(f"[DEBUG] Conference - Clasificado como No Contesto - Número inválido: {error_code}")
                                        # PRIORIDAD MEDIA 1: Número bloqueado/spam
                                        elif remote.status == 'failed' and error_code in ['21610', '30006']:
                                            final_status = 'No Contesto'
                                            st.error(f"🚫 Número bloqueado o marcado como spam (error {error_code})")
                                            print(f"[DEBUG] Conference - Clasificado como No Contesto - Número bloqueado: {error_code}")
                                        # PRIORIDAD MEDIA 2: Error de red
                                        elif remote.status == 'failed' and error_code in ['31005', '31002', '31003', '31009']:
                                            final_status = 'No Contesto'
                                            st.warning(f"⚠️ Error de red - Considerar reintento (error {error_code})")
                                            print(f"[DEBUG] Conference - Clasificado como No Contesto - Error de red: {error_code}")
                                        # Caso 1: No contestó, ocupado, cancelado
                                        elif remote.status in ['no-answer', 'busy', 'canceled']:
                                            final_status = 'No Contesto'
                                            print(f"[DEBUG] Conference - No contestó: {remote.status}")
                                        # Caso 2: Fallo genérico
                                        elif remote.status == 'failed':
                                            final_status = 'No Contesto'
                                            print(f"[DEBUG] Conference - Fallo genérico: {error_code}")
                                        # PRIORIDAD ALTA 3: Buzón de voz mejorado
                                        elif answered_by in ['machine_start', 'fax']:
                                            if duracion_twilio < 5:
                                                final_status = 'No Contesto'
                                                print(f"[DEBUG] Conference - Buzón lleno")
                                            else:
                                                final_status = 'No Contesto'
                                                print(f"[DEBUG] Conference - Buzón de voz")
                                        
                                        # Caso 3: Contestó persona
                                        elif answered_by == 'human':
                                            final_status = 'Llamado'
                                            print(f"[DEBUG] Conference - Detectado como humano")
                                        
                                        # PRIORIDAD ALTA 2: Cliente colgó inmediatamente vs No contestó
                                        elif remote.status == 'completed' and answered_by == 'unknown':
                                            if duracion_twilio == 0:
                                                final_status = 'No Contesto'
                                                print(f"[DEBUG] Conference - Sin conexión")
                                            elif 0 < duracion_twilio < 3:
                                                final_status = 'No Contesto'
                                                print(f"[DEBUG] Conference - Rechazó inmediatamente: {duracion_twilio}s")
                                            elif 3 <= duracion_twilio < 10:
                                                final_status = 'No Contesto'
                                                print(f"[DEBUG] Conference - Duración muy corta: {duracion_twilio}s")
                                            else:
                                                final_status = 'Llamado'
                                                print(f"[DEBUG] Conference - Conversación establecida: {duracion_twilio}s")
                                        
                                        # Caso por defecto
                                        else:
                                            final_status = 'Llamado'
                                            print(f"[DEBUG] Conference - Clasificado como Llamado por defecto")
                                        
                                        print(f"[DEBUG] Estado final determinado: {final_status}")
                                        
                                        # Calculamos duración
                                        t_fin = datetime.now()
                                        dur = int((t_fin - st.session_state.t_inicio_dt).total_seconds())
                                        print(f"[DEBUG] Duración calculada: {dur} segundos")
                                        
                                        # --- PASO 1: ACTUALIZACIÓN LOCAL INMEDIATA ---
                                        print(f"[DEBUG] Actualizando DataFrame local para idx={idx}")
                                        st.session_state.df_contactos.at[idx, 'estado'] = final_status  # Mantener Llamado/No Contesto
                                        st.session_state.df_contactos.at[idx, 'observacion'] = nota
                                        st.session_state.df_contactos.at[idx, 'duracion_seg'] = dur
                                        st.session_state.df_contactos.at[idx, 'agente_id'] = st.session_state.agente_id
                                        st.session_state.df_contactos.at[idx, 'fecha_llamada'] = t_fin.strftime("%Y-%m-%d %H:%M:%S")
                                        st.session_state.df_contactos.at[idx, 'sid_llamada'] = st.session_state.llamada_activa_sid
                                        
                                        print(f"[DEBUG] DataFrame local actualizado. Estado: {final_status}")
                                        
                                        # --- PASO 2: SINCRONIZACIÓN CON SHEET INFORME ---
                                        print(f"[DEBUG] Iniciando sincronización con Sheet Informe")
                                        st.write(f" Guardando gestión: {final_status}")
                                        
                                        if URL_SHEET_INFORME:
                                            try:
                                                st.write("🔄 Sincronizando con Sheet Informe...")
                                                
                                                # Obtener información adicional de Twilio
                                                url_grabacion = ''
                                                precio_llamada = '0'
                                                duracion_facturada = '0'
                                                estado_respuesta = answered_by
                                                codigo_error = ''
                                                
                                                # Variables adicionales de Twilio para consistencia con WebRTC
                                                account_sid = ''
                                                start_time = ''
                                                end_time = ''
                                                from_number = ''
                                                to_number = ''
                                                direction = ''
                                                status = ''
                                                price_unit = 'USD'
                                                call_type = ''
                                                date_created = ''
                                                parent_call_sid = ''
                                                phone_number_sid = ''
                                                
                                                transcription_sid = None
                                                
                                                try:
                                                    recordings = client.recordings.list(call_sid=st.session_state.llamada_activa_sid, limit=1)
                                                    if recordings:
                                                        recording_sid = recordings[0].sid
                                                        url_grabacion = f"https://api.twilio.com{recordings[0].uri.replace('.json', '.mp3')}"
                                                        
                                                        # Solicitar transcripción automáticamente
                                                        st.write("📝 Solicitando transcripción...")
                                                        transcription_sid = solicitar_transcripcion(recording_sid)
                                                        if transcription_sid:
                                                            st.success(f"✅ Transcripción solicitada (SID: {transcription_sid[:8]}...)")
                                                        else:
                                                            st.warning("⚠️ No se pudo solicitar transcripción")
                                                    
                                                    # Obtener TODOS los datos de la llamada de Twilio (como WebRTC)
                                                    if st.session_state.llamada_activa_sid:
                                                        call_data = client.calls(st.session_state.llamada_activa_sid).fetch()
                                                        
                                                        # Datos básicos
                                                        precio_llamada = str(call_data.price) if call_data.price else '0'
                                                        duracion_facturada = str(call_data.duration) if call_data.duration else '0'
                                                        codigo_error = str(call_data.error_code) if hasattr(call_data, 'error_code') and call_data.error_code else ''
                                                        
                                                        # Datos adicionales completos de Twilio
                                                        account_sid = str(call_data.account_sid) if hasattr(call_data, 'account_sid') else ''
                                                        start_time = str(call_data.start_time) if hasattr(call_data, 'start_time') and call_data.start_time else ''
                                                        end_time = str(call_data.end_time) if hasattr(call_data, 'end_time') and call_data.end_time else ''
                                                        from_number = str(call_data.from_) if hasattr(call_data, 'from_') else ''
                                                        to_number = str(call_data.to) if hasattr(call_data, 'to') else tel
                                                        direction = str(call_data.direction) if hasattr(call_data, 'direction') else ''
                                                        status = str(call_data.status) if hasattr(call_data, 'status') else ''
                                                        price_unit = str(call_data.price_unit) if hasattr(call_data, 'price_unit') else 'USD'
                                                        call_type = 'client' if from_number.startswith('client:') else 'phone'
                                                        date_created = str(call_data.date_created) if hasattr(call_data, 'date_created') and call_data.date_created else ''
                                                        parent_call_sid = str(call_data.parent_call_sid) if hasattr(call_data, 'parent_call_sid') and call_data.parent_call_sid else ''
                                                        phone_number_sid = str(call_data.phone_number_sid) if hasattr(call_data, 'phone_number_sid') and call_data.phone_number_sid else ''
                                                        
                                                        print(f"[DEBUG] Conference - Datos completos obtenidos: duration={duracion_facturada}s, from={from_number}, to={to_number}")
                                                        
                                                except Exception as e_twilio:
                                                    print(f"[DEBUG] Error obteniendo datos Twilio: {e_twilio}")

                                                # Preparar fila para Sheet Informe con TODAS las columnas de Twilio (como WebRTC)
                                                fila_informe = pd.DataFrame({
                                                    # Columnas del sistema
                                                    'agente_id': [st.session_state.agente_id],
                                                    'nombre': [c['nombre']],
                                                    'telefono': [tel],
                                                    'estado': [final_status],  # Mantener Llamado/No Contesto real
                                                    'observacion': [nota],
                                                    'duracion_seg': [dur],
                                                    'fecha_llamada': [t_fin.strftime("%Y-%m-%d %H:%M:%S")],
                                                    
                                                    # Columnas de Twilio Call Recording (completas como WebRTC)
                                                    'call_sid': [st.session_state.llamada_activa_sid or ''],
                                                    'account_sid': [account_sid],
                                                    'start_time': [start_time],
                                                    'end_time': [end_time],
                                                    'duration': [duracion_facturada],
                                                    'from': [from_number],
                                                    'to': [to_number],
                                                    'direction': [direction],
                                                    'status': [status],
                                                    'price': [precio_llamada],
                                                    'price_unit': [price_unit],
                                                    'answered_by': [estado_respuesta],
                                                    'type': [call_type],
                                                    'date_created': [date_created],
                                                    'parent_call_sid': [parent_call_sid],
                                                    'phone_number_sid': [phone_number_sid],
                                                    'error_code': [codigo_error],
                                                    'url_grabacion': [url_grabacion],
                                                    'transcription_sid': [transcription_sid if transcription_sid else ''],
                                                    'grabacion_pendiente': ['SI' if not url_grabacion else 'NO']
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
                                                    
                                                    if not url_grabacion:
                                                        st.info("📋 Grabación pendiente - Se verificará en 5 minutos")
                                                        print(f"[GRABACION] 📋 Marcada como pendiente en Sheet Informe")
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
                                        st.session_state.conference_name = None
                                        st.session_state.conference_idx = None
                                        st.session_state.grabacion_pausada = False
                                        st.session_state.finalizacion_manual_agente = False  # Limpiar variable
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
                            # --- OPCIÓN DE REPROGRAMAR (SIEMPRE DISPONIBLE) ---
                            st.divider()
                            st.write("**📅 Reprogramar Llamada**")
                            
                            # Sección de programación
                            col_prog1, col_prog2 = st.columns(2)
                            with col_prog1:
                                # Obtener hora actual en Bogotá para valores por defecto
                                hora_bogota_actual = obtener_hora_bogota()
                                fecha_prog = st.date_input("Fecha:", value=hora_bogota_actual.date(), key=f"fecha_{idx}")
                            with col_prog2:
                                hora_prog = st.time_input("Hora:", value=hora_bogota_actual.time(), key=f"hora_{idx}")
                            
                            # Mostrar información de zona horaria
                            st.caption(f"🕐 Zona horaria: Bogotá (UTC-5) - Hora actual: {hora_bogota_actual.strftime('%Y-%m-%d %H:%M:%S')}")
                            
                            # Botones de acción
                            col_btn1, col_btn2 = st.columns(2)
                            with col_btn1:
                                if st.button("💾 Guardar Notas", key=f"save_notes_{idx}", use_container_width=True):
                                    # Obtener nota existente
                                    nota_existente = str(st.session_state.df_contactos.at[idx, 'observacion']) if pd.notna(st.session_state.df_contactos.at[idx, 'observacion']) else ''
                                    
                                    # Combinar notas si ya existe algo
                                    if nota_existente and nota_existente.strip():
                                        if nota.strip() and nota != nota_existente:
                                            # Acumular notas con timestamp
                                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                                            nota_acumulada = f"{nota_existente} | [{timestamp}] {nota}"
                                        else:
                                            nota_acumulada = nota_existente  # Mantener existente si la nueva está vacía o es igual
                                    else:
                                        nota_acumulada = nota  # Usar nueva nota si no existe nada
                                    
                                    # Actualizar DataFrame local con notas acumuladas
                                    st.session_state.df_contactos.at[idx, 'observacion'] = nota_acumulada
                                    
                                    # Actualizar Sheet Llamadas con función segura
                                    if URL_SHEET_CONTACTOS:
                                        try:
                                            if update_sheet_safe(st.session_state.df_contactos, "0", sheet_url=URL_SHEET_CONTACTOS, agente_id=st.session_state.agente_id):
                                                add_log(f"NOTAS_ACUMULADAS: {c['nombre']}", "ACCION")
                                                st.success("✅ Notas acumuladas en Sheet Llamadas con seguridad")
                                            else:
                                                st.warning("⚠️ Notas acumuladas localmente, pero error actualizando Sheet Llamadas")
                                        except Exception as e:
                                            st.error(f"❌ Error acumulando notas: {e}")
                                    else:
                                        st.success("✅ Notas acumuladas localmente")
                                    
                                    time.sleep(1)
                                    st.rerun()
                            
                            with col_btn2:
                                if st.button("✅ Programar", key=f"prog_{idx}", use_container_width=True):
                                    # Combinar fecha y hora
                                    fecha_hora_prog = datetime.combine(fecha_prog, hora_prog)
                                    
                                    # Obtener nota actual (que ya incluye notas acumuladas si se guardaron)
                                    nota_actual = st.session_state.df_contactos.at[idx, 'observacion']
                                    
                                    # Actualizar DataFrame local
                                    st.session_state.df_contactos.at[idx, 'estado'] = 'Programada'
                                    st.session_state.df_contactos.at[idx, 'proxima_llamada'] = fecha_hora_prog.strftime("%Y-%m-%d %H:%M:%S")
                                    st.session_state.df_contactos.at[idx, 'observacion'] = nota_actual  # Mantener notas acumuladas
                                    st.session_state.df_contactos.at[idx, 'agente_id'] = st.session_state.agente_id
                                    
                                    # Actualizar Sheet Llamadas con función segura
                                    if URL_SHEET_CONTACTOS:
                                        try:
                                            if update_sheet_safe(st.session_state.df_contactos, "0", sheet_url=URL_SHEET_CONTACTOS, agente_id=st.session_state.agente_id):
                                                add_log(f"PROGRAMADA: {c['nombre']} para {fecha_hora_prog.strftime('%Y-%m-%d %H:%M')}", "ACCION")
                                                st.success(f"✅ Llamada programada para {fecha_hora_prog.strftime('%Y-%m-%d %H:%M')} con seguridad")
                                            else:
                                                st.warning("⚠️ Programada localmente, pero error actualizando Sheet Llamadas")
                                        except Exception as e:
                                            st.error(f"❌ Error actualizando Sheet Llamadas: {e}")
                                            print(f"[ERROR] Programar llamada - Update Sheet: {e}")
                                    else:
                                        st.success(f"✅ Llamada programada para {fecha_hora_prog.strftime('%Y-%m-%d %H:%M')}")
                                    
                                    time.sleep(1)
                                    st.rerun()
        else:
            st.success(f"¡Felicidades! No hay más clientes en la categoría: {f_est}")
    else:
        st.info("Por favor, cargue un archivo CSV en el sidebar para comenzar la operación.")
