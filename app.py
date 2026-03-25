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
import math
import random
import json

# --- CONFIGURACION DE PAGINA ---
st.set_page_config(page_title="Camacol Dialer Pro v4.5 - Enhanced", layout="wide")

st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 10px; border-radius: 10px; border: 1px solid #e1e4e8; }
    .client-card { background-color: #f0f2f6; padding: 15px; border-radius: 15px; border-left: 8px solid #003366; margin-bottom: 15px; }
    .log-box { font-family: monospace; font-size: 0.8rem; background: #1e1e1e; color: #4af626; padding: 10px; border-radius: 5px; height: 180px; overflow-y: auto; }
    .latency-green { height: 10px; width: 10px; background-color: #28a745; border-radius: 50%; display: inline-block; }
    .latency-red { height: 10px; width: 10px; background-color: #dc3545; border-radius: 50%; display: inline-block; }
    
    /* Estilos para recordatorios inteligentes */
    .reminder-alert {
        background: linear-gradient(135deg, #ff6b6b, #ff8787);
        color: white;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 15px;
        box-shadow: 0 4px 15px rgba(255, 107, 107, 0.3);
        animation: pulse 2s infinite;
        border-left: 5px solid #ff4444;
    }
    
    .reminder-urgent {
        background: linear-gradient(135deg, #ff6b6b, #ff4444);
        animation: urgent-pulse 1s infinite;
    }
    
    @keyframes pulse {
        0% { transform: scale(1); }
        50% { transform: scale(1.02); }
        100% { transform: scale(1); }
    }
    
    @keyframes urgent-pulse {
        0% { transform: scale(1); box-shadow: 0 4px 15px rgba(255, 107, 107, 0.3); }
        50% { transform: scale(1.05); box-shadow: 0 6px 20px rgba(255, 107, 107, 0.5); }
        100% { transform: scale(1); box-shadow: 0 4px 15px rgba(255, 107, 107, 0.3); }
    }
    
    .countdown-timer {
        font-size: 1.2em;
        font-weight: bold;
        color: #ff4444;
        text-align: center;
        margin: 10px 0;
    }
    
    /* Estilos para dashboard de productividad */
    .productivity-card {
        background: linear-gradient(135deg, #667eea, #764ba2);
        color: white;
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 8px 25px rgba(102, 126, 234, 0.3);
        margin-bottom: 15px;
    }
    
    .metric-positive {
        color: #28a745;
        font-weight: bold;
    }
    
    .metric-negative {
        color: #dc3545;
        font-weight: bold;
    }
    
    .progress-bar-container {
        background: rgba(255, 255, 255, 0.2);
        border-radius: 10px;
        padding: 3px;
        margin: 10px 0;
    }
    
    .progress-bar-fill {
        background: linear-gradient(90deg, #28a745, #20c997);
        height: 20px;
        border-radius: 7px;
        transition: width 0.5s ease;
    }
    
    .dashboard-header {
        text-align: center;
        color: #2c3e50;
        margin-bottom: 20px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 1. CONEXIONES ---
try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets.get("TWILIO_NUMBER", "+17068069672")
    function_url = st.secrets["TWILIO_FUNCTION_URL"]
    # Extraer la URL base para el endpoint /token (sin /hacer-llamada)
    function_url_base = function_url.replace('/hacer-llamada', '').rstrip('/')
    #function_url_base = function_url.replace('/hacer-llamada', '') if '/hacer-llamada' in function_url else function_url
    forms_base_url = st.secrets.get("MS_FORMS_URL", "https://forms.office.com/r/tu_codigo")
    URL_SHEET_INFORME = st.secrets.get("GSHEET_URL")
    URL_SHEET_CONTACTOS = st.secrets.get("GSHEET_CONTACTOS_URL")
    GDRIVE_LOGS_FOLDER_ID = st.secrets.get("GDRIVE_LOGS_FOLDER_ID")
    CEDULAS_AUTORIZADAS = st.secrets.get("CEDULAS_AUTORIZADAS", ["1121871773", "87654321", "12345678","52486921"])
    
    # Sheets específicos por agente
    AGENT_SHEETS = dict(st.secrets.get("agent_sheets", {}))
    
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

# --- SISTEMA DE PERSISTENCIA DE LLAMADAS ACTIVAS ---
def guardar_llamada_activa_en_cookie():
    """Guarda el estado de la llamada activa en cookies del navegador"""
    if st.session_state.get('llamada_activa_sid') and st.session_state.get('agente_id'):
        llamada_data = {
            'llamada_activa_sid': st.session_state.llamada_activa_sid,
            'conference_name': st.session_state.get('conference_name', ''),
            'conference_idx': st.session_state.get('conference_idx', 0),
            't_inicio_dt': st.session_state.t_inicio_dt.isoformat() if hasattr(st.session_state.t_inicio_dt, 'isoformat') else str(st.session_state.t_inicio_dt),
            'agente_id': st.session_state.agente_id,
            'webrtc_activo': st.session_state.get('webrtc_activo', False),
            'webrtc_numero': st.session_state.get('webrtc_numero', ''),
            'webrtc_nombre': st.session_state.get('webrtc_nombre', ''),
            'webrtc_idx': st.session_state.get('webrtc_idx', 0),
            'timestamp': datetime.now().isoformat()
        }
        
        # Guardar en cookie usando JavaScript
        cookie_script = f"""
        <script>
        document.cookie = 'llamada_activa={json.dumps(llamada_data)}; max-age=3600; path=/';
        console.log('Llamada activa guardada en cookie');
        </script>
        """
        st.components.v1.html(cookie_script, height=0)
        print(f"[PERSISTENCE] Llamada activa guardada en cookie para agente {st.session_state.agente_id}")

def recuperar_llamada_activa_desde_cookie():
    """Recupera el estado de la llamada activa desde cookies del navegador"""
    try:
        # Intentar leer la cookie usando JavaScript
        cookie_script = """
        <script>
        function getCookie(name) {
            const value = `; ${document.cookie}`;
            const parts = value.split(`; ${name}=`);
            if (parts.length === 2) return parts.pop().split(';').shift();
        }
        
        const llamadaData = getCookie('llamada_activa');
        if (llamadaData) {
            window.parent.postMessage({
                type: 'llamada_activa_recuperada',
                data: llamadaData
            }, '*');
        }
        </script>
        """
        st.components.v1.html(cookie_script, height=0)
        
        # Verificar si hay datos de llamada recuperados
        if 'llamada_recuperada_data' in st.query_params:
            try:
                llamada_data = json.loads(st.query_params['llamada_recuperada_data'][0])
                return llamada_data
            except:
                pass
    except Exception as e:
        print(f"[PERSISTENCE] Error recuperando llamada desde cookie: {e}")
    
    return None

def verificar_llamada_activa_en_twilio(llamada_sid):
    """Verifica si una llamada sigue activa en Twilio"""
    try:
        if not llamada_sid:
            return False
        
        call = client.calls(llamada_sid).fetch()
        return call.status in ['in-progress', 'queued', 'ringing']
    except Exception as e:
        print(f"[PERSISTENCE] Error verificando llamada en Twilio: {e}")
        return False

def restaurar_llamada_activa():
    """Restaura el estado de una llamada activa desde persistencia"""
    print(f"[PERSISTENCE] Iniciando restauración de llamada activa...")
    
    # Intentar recuperar desde cookie
    llamada_data = recuperar_llamada_activa_desde_cookie()
    
    if llamada_data:
        print(f"[PERSISTENCE] Datos de llamada recuperados: {llamada_data}")
        
        # Verificar que la llamada siga activa en Twilio
        llamada_sid = llamada_data.get('llamada_activa_sid')
        if verificar_llamada_activa_en_twilio(llamada_sid):
            print(f"[PERSISTENCE] Llamada {llamada_sid} sigue activa en Twilio")
            
            # Restaurar estado en session_state
            st.session_state.llamada_activa_sid = llamada_data['llamada_activa_sid']
            st.session_state.conference_name = llamada_data.get('conference_name', '')
            st.session_state.conference_idx = llamada_data.get('conference_idx', 0)
            st.session_state.t_inicio_dt = datetime.fromisoformat(llamada_data['t_inicio_dt'])
            st.session_state.agente_id = llamada_data['agente_id']
            st.session_state.webrtc_activo = llamada_data.get('webrtc_activo', False)
            st.session_state.webrtc_numero = llamada_data.get('webrtc_numero', '')
            st.session_state.webrtc_nombre = llamada_data.get('webrtc_nombre', '')
            st.session_state.webrtc_idx = llamada_data.get('webrtc_idx', 0)
            
            print(f"[PERSISTENCE] ✅ Llamada activa restaurada exitosamente")
            return True
        else:
            print(f"[PERSISTENCE] Llamada {llamada_sid} ya no está activa en Twilio")
            # Limpiar cookie
            limpiar_cookie_llamada_activa()
    else:
        print(f"[PERSISTENCE] No se encontraron datos de llamada activa")
    
    return False

def limpiar_cookie_llamada_activa():
    """Limpia la cookie de llamada activa"""
    cookie_script = """
    <script>
    document.cookie = 'llamada_activa=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
    console.log('Cookie de llamada activa limpiada');
    </script>
    """
    st.components.v1.html(cookie_script, height=0)
    print(f"[PERSISTENCE] Cookie de llamada activa limpiada")

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
            
            # OPTIMIZACIÓN: Leer el sheet UNA SOLA VEZ antes del bucle
            rate_limiter.check_and_wait(operation_type="read")
            existing_data = worksheet.get_all_records()
            
            # Calcular la siguiente fila vacía disponible para nuevos registros
            next_empty_row = len(existing_data) + 2
            
            # En lugar de borrar todo, actualizar solo las filas necesarias
            # Esto preserva otros contactos que puedan existir en el sheet
            for idx, row in df_sanitizado.iterrows():
                # Buscar la fila correspondiente en el sheet basándose en un identificador único
                # Usar teléfono como identificador único para encontrar la fila correcta
                telefono = str(row.get('telefono', ''))
                if telefono:
                    # Intentar encontrar la fila existente
                    try:
                        # Buscar fila existente por teléfono en los datos ya leídos
                        target_row = None
                        for i, existing_row in enumerate(existing_data):
                            if str(existing_row.get('telefono', '')) == telefono:
                                target_row = i + 2  # +2 porque Google Sheets es 1-indexed y tiene header
                                break
                        
                        # Si no se encuentra, usar la siguiente fila vacía e incrementarla
                        if target_row is None:
                            target_row = next_empty_row
                            next_empty_row += 1
                        
                        # Preparar datos de la fila
                        row_data = row.values.tolist()
                        row_data = [str(val) if val is not None and str(val) != 'nan' else '' for val in row_data]
                        
                        # Actualizar solo esta fila específica
                        rate_limiter.check_and_wait(operation_type="write")
                        worksheet.update(f'A{target_row}:{chr(65 + len(row_data) - 1)}{target_row}', [row_data])
                        
                        print(f"[DEBUG] Fila {target_row} actualizada para teléfono {telefono}")
                        
                    except Exception as e:
                        print(f"[ERROR] Error actualizando fila específica para {telefono}: {e}")
                        # Fallback: agregar al final si hay error
                        try:
                            rate_limiter.check_and_wait(operation_type="write")
                            worksheet.append_row(row.values.tolist())
                        except Exception as e2:
                            print(f"[ERROR] Error en fallback append: {e2}")
            
            print(f"[SECURITY] Sheet actualizado exitosamente por {agente_id} (actualización targeted)")
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
    def __init__(self, max_requests_per_minute=80, warning_threshold=0.85):
        self.max_requests = max_requests_per_minute
        self.warning_threshold = warning_threshold
        self.request_times = []
        self.warning_shown = False
        self.last_warning_time = 0
    
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
        
        # 🔥 OPTIMIZACIÓN: Reducir delays para sincronización más rápida
        if usage_percentage >= self.warning_threshold:
            wait_time = 1.5  # 🔥 REDUCIDO: Esperar solo 1.5 segundos
            # Mostrar advertencia solo cada 10 segundos para no spam
            if now - self.last_warning_time > 10:
                print(f"[RATE LIMIT] ⚠️ Uso al {usage_percentage*100:.1f}% ({current_usage}/{self.max_requests})")
                print(f"[RATE LIMIT] Aplicando delay de {wait_time}s para evitar quota exceeded")
                self.last_warning_time = now
            time.sleep(wait_time)
        elif usage_percentage >= 0.75:  # 🔥 CAMBIADO: Al 75% empezar a reducir velocidad
            time.sleep(0.5)  # 🔥 REDUCIDO: Solo 0.5 segundos
        else:
            # 🔥 NUEVO: Delay mínimo para operaciones rápidas
            if operation_type == "write" and current_usage > 5:
                time.sleep(0.2)  # Delay muy pequeño solo para escrituras después de 5 ops
        
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

def update_single_call_row(df_contactos, idx, sheet_url):
    """
    Actualiza solo la fila específica de una llamada en Google Sheets
    usando el número de línea (índice + 2) para mayor precisión.
    
    Args:
        df_contactos: DataFrame completo de contactos
        idx: Índice de la fila a actualizar
        sheet_url: URL del Google Sheet
    
    Returns:
        bool: True si la actualización fue exitosa, False en caso contrario
    """
    try:
        # Verificar rate limit
        rate_limiter.check_and_wait(operation_type="write")
        
        # Abrir el spreadsheet
        spreadsheet = gc.open_by_url(sheet_url)
        worksheet = spreadsheet.get_worksheet(0)
        
        # 🔥 MÉTODO POR NÚMERO DE LÍNEA (más confiable)
        # Usar el índice directamente + 2 (header + 1-indexed)
        row_number = idx + 2
        
        # Verificar que la fila exista en el sheet
        rate_limiter.check_and_wait(operation_type="read")
        sheet_data = worksheet.get_all_values()
        
        if row_number > len(sheet_data):
            print(f"[ERROR] Fila {row_number} no existe en sheet (total filas: {len(sheet_data)})")
            return False
        
        # Obtener datos del contacto específico
        contact_data = df_contactos.iloc[idx]
        telefono_contacto = str(contact_data.get('telefono', ''))
        nombre_contacto = str(contact_data.get('nombre', ''))
        
        print(f"[DEBUG] Actualizando por línea {row_number}:")
        print(f"[DEBUG] Contacto: {nombre_contacto} - Tel: {telefono_contacto}")
        
        # Verificación adicional: comparar teléfono para seguridad
        telefono_en_sheet = str(sheet_data[row_number - 1][list(sheet_data[0]).index('telefono')] if 'telefono' in sheet_data[0] else '')
        telefono_normalizado = normalize_phone_for_search(telefono_contacto)
        sheet_telefono_normalizado = normalize_phone_for_search(telefono_en_sheet)
        
        if telefono_normalizado and sheet_telefono_normalizado and telefono_normalizado != sheet_telefono_normalizado:
            print(f"[WARNING] Discrepancia de teléfono: DF={telefono_contacto} vs Sheet={telefono_en_sheet}")
            print(f"[WARNING] Continuando actualización por línea de todas formas...")
        
        # Preparar datos de la fila
        row_data = []
        headers = sheet_data[0]  # Headers del sheet
        
        for header in headers:
            # Buscar el valor en el DataFrame (insensible a mayúsculas)
            val = ""
            for df_col in contact_data.index:
                if df_col.lower() == header.lower():
                    val = contact_data[df_col]
                    break
            
            # Convertir a string seguro
            val_str = str(val) if val is not None and str(val) != 'nan' else ''
            row_data.append(val_str)
        
        print(f"[DEBUG] Datos a actualizar ({len(row_data)} columnas): {row_data[:3]}...")
        
        # Actualizar solo la fila específica
        rate_limiter.check_and_wait(operation_type="write")
        worksheet.update(f'A{row_number}:{chr(65 + len(row_data) - 1)}{row_number}', [row_data])
        
        print(f"[DEBUG] ✅ Fila {row_number} actualizada exitosamente por línea")
        return True
        
    except Exception as e:
        print(f"[ERROR] Error actualizando fila por línea: {e}")
        import traceback
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        return False

def update_call_status_safe(df_contactos, idx, nuevo_estado, observacion, duracion_seg, agente_id, fecha_llamada, sid_llamada, sheet_url):
    """
    Actualiza de forma segura el estado de una llamada específica sin sobreescribir todo el sheet.
    
    Args:
        df_contactos: DataFrame de contactos
        idx: Índice de la llamada a actualizar
        nuevo_estado: Nuevo estado de la llamada
        observacion: Observación de la llamada
        duracion_seg: Duración en segundos
        agente_id: ID del agente
        fecha_llamada: Fecha y hora de la llamada
        sid_llamada: SID de la llamada de Twilio
        sheet_url: URL del Google Sheet
    
    Returns:
        bool: True si la actualización fue exitosa
    """
    try:
        # Actualizar el DataFrame local primero
        df_contactos.at[idx, 'estado'] = nuevo_estado
        df_contactos.at[idx, 'observacion'] = observacion
        df_contactos.at[idx, 'duracion_seg'] = duracion_seg
        df_contactos.at[idx, 'agente_id'] = agente_id
        df_contactos.at[idx, 'fecha_llamada'] = fecha_llamada
        df_contactos.at[idx, 'sid_llamada'] = sid_llamada
        
        # Actualizar solo esta fila en Google Sheets
        return update_single_call_row(df_contactos, idx, sheet_url)
        
    except Exception as e:
        print(f"[ERROR] Error en update_call_status_safe: {e}")
        return False

def normalize_phone_for_search(phone):
    """Normaliza número de teléfono para búsqueda (solo dígitos) para evitar errores de formato"""
    if pd.isna(phone): return ""
    return re.sub(r'\D', '', str(phone))

def update_contact_in_sheet_safe(df_contactos, idx, sheet_url, agente_id, operation_type="update"):
    """
    Actualiza solo un contacto específico en el sheet usando número de línea.
    MÉTODO ACTUALIZADO: Usa línea en lugar de búsqueda por teléfono para mayor confiabilidad.
    
    Args:
        df_contactos: DataFrame de contactos
        idx: Índice del contacto a actualizar
        sheet_url: URL del Google Sheet
        agente_id: ID del agente
        operation_type: Tipo de operación para logging
    
    Returns:
        bool: True si la actualización fue exitosa
    """
    try:
        # 🔥 VERIFICACIONES DE SEGURIDAD ANTES DE EMPEZAR
        print(f"[DEBUG] {operation_type} - INICIO ACTUALIZACIÓN")
        print(f"[DEBUG] {operation_type} - Sheet URL: {sheet_url[:50]}...")
        print(f"[DEBUG] {operation_type} - Agente ID: {agente_id}")
        print(f"[DEBUG] {operation_type} - Índice recibido: {idx}")
        print(f"[DEBUG] {operation_type} - DF shape: {df_contactos.shape}")
        
        # Verificar que el índice sea válido
        if idx < 0 or idx >= len(df_contactos):
            print(f"[ERROR] {operation_type} - Índice inválido: {idx} (rango válido: 0-{len(df_contactos)-1})")
            return False
        
        # Verificar rate limit
        rate_limiter.check_and_wait(operation_type="write")
        
        # Obtener datos del contacto específico
        contact_data = df_contactos.loc[idx]
        telefono = str(contact_data.get('telefono', ''))
        nombre = str(contact_data.get('nombre', ''))
        
        print(f"[DEBUG] {operation_type} - Actualizando contacto por línea:")
        print(f"[DEBUG] Contacto: {nombre} - Tel: {telefono} - Índice: {idx}")
        print(f"[DEBUG] {operation_type} - Estado: {contact_data.get('estado', 'N/A')}")
        
        # Abrir el spreadsheet
        spreadsheet = gc.open_by_url(sheet_url)
        worksheet = spreadsheet.get_worksheet(0)
        
        # 🔥 MÉTODO POR NÚMERO DE LÍNEA (más confiable que búsqueda por teléfono)
        rate_limiter.check_and_wait(operation_type="read")
        sheet_data = worksheet.get_all_values()
        
        # Calcular fila objetivo: índice + 2 (header + 1-indexed)
        target_row = idx + 2
        
        print(f"[DEBUG] {operation_type} - Cálculo de fila:")
        print(f"[DEBUG] {operation_type} - Índice DF: {idx}")
        print(f"[DEBUG] {operation_type} - Fila objetivo: {target_row}")
        print(f"[DEBUG] {operation_type} - Total filas Sheet: {len(sheet_data)}")
        
        # Verificar que la fila exista
        if target_row > len(sheet_data):
            print(f"[ERROR] {operation_type} - Fila {target_row} no existe (total: {len(sheet_data)})")
            print(f"[ERROR] {operation_type} - Posible causa: DF y Sheet desincronizados")
            return False
        
        # Obtener headers del sheet
        headers = sheet_data[0]
        print(f"[DEBUG] {operation_type} - Headers Sheet: {len(headers)} columnas")
        
        # Verificación de seguridad opcional: comparar teléfono
        if 'telefono' in headers:
            telefono_col_idx = headers.index('telefono')
            telefono_en_sheet = str(sheet_data[target_row - 1][telefono_col_idx]) if target_row <= len(sheet_data) else ''
            
            telefono_normalizado = normalize_phone_for_search(telefono)
            sheet_telefono_normalizado = normalize_phone_for_search(telefono_en_sheet)
            
            if telefono_normalizado and sheet_telefono_normalizado:
                if telefono_normalizado != sheet_telefono_normalizado:
                    print(f"[WARNING] {operation_type} - Discrepancia teléfono: DF={telefono} vs Sheet={telefono_en_sheet}")
                    print(f"[WARNING] {operation_type} - Continuando por línea de todas formas...")
                else:
                    print(f"[DEBUG] {operation_type} - Teléfono coincide: {telefono}")
        
        # Preparar datos de la fila respetando el orden del sheet
        row_data = []
        for header in headers:
            # Buscar el valor en el DataFrame (insensible a mayúsculas)
            val = ""
            for df_col in contact_data.index:
                if df_col.lower() == header.lower():
                    val = contact_data[df_col]
                    break
            
            # Convertir a string seguro
            val_str = str(val) if val is not None and str(val) != 'nan' else ''
            row_data.append(val_str)
        
        print(f"[DEBUG] {operation_type} - Preparando actualización fila {target_row}")
        print(f"[DEBUG] {operation_type} - Columnas: {len(headers)} - Datos: {len(row_data)}")
        
        # Actualizar solo esta fila específica
        rate_limiter.check_and_wait(operation_type="write")
        
        # 🔥 LOGGING DETALLADO ANTES DE ACTUALIZAR
        print(f"[DEBUG] {operation_type} - Preparando actualización:")
        print(f"[DEBUG] {operation_type} - Rango: A{target_row}:{chr(65 + len(row_data) - 1)}{target_row}")
        print(f"[DEBUG] {operation_type} - Datos a escribir: {len(row_data)} valores")
        
        # Mostrar primeros valores para depuración
        if len(row_data) > 0:
            print(f"[DEBUG] {operation_type} - Primer valor: {row_data[0]}")
            print(f"[DEBUG] {operation_type} - Último valor: {row_data[-1]}")
        
        worksheet.update(f'A{target_row}:{chr(65 + len(row_data) - 1)}{target_row}', [row_data])
        
        print(f"[DEBUG] {operation_type} - ✅ Fila {target_row} actualizada exitosamente (método línea)")
        print(f"[DEBUG] {operation_type} - ✅ Sheet actualizado: {sheet_url[:30]}...")
        return True
        
    except Exception as e:
        print(f"[ERROR] {operation_type} - Error actualizando por línea: {e}")
        print(f"[ERROR] {operation_type} - Detalles del error:")
        print(f"[ERROR] - Índice: {idx}")
        print(f"[ERROR] - Sheet: {sheet_url[:50]}...")
        print(f"[ERROR] - Agente: {agente_id}")
        
        # 🔥 DETECTAR ESPECÍFICAMENTE ERROR DE PERMISOS
        error_str = str(e).lower()
        if 'permission_denied' in error_str or '403' in error_str or 'does not have permission' in error_str:
            print(f"[ERROR] {operation_type} - 🔥 ERROR DE PERMISOS DETECTADO")
            print(f"[ERROR] {operation_type} - El service account no tiene permisos de edición en este Sheet")
            print(f"[ERROR] {operation_type} - Solución: Compartir el Sheet con el email del service account")
            print(f"[ERROR] {operation_type} - O: Eliminar configuración de sheet individual para usar solo compartido")
        
        import traceback
        print(f"[ERROR] Traceback completo:")
        print(f"[ERROR] {traceback.format_exc()}")
        return False

def update_both_sheets_safe(df_contactos, agente_id, operation_type="general", contact_idx=None):
    """
    Actualiza tanto el sheet compartido como el sheet específico del agente.
    MODIFICADO: Ahora actualiza solo contactos específicos en lugar de sobreescribir todo.
    
    Args:
        df_contactos: DataFrame de contactos
        agente_id: ID del agente
        operation_type: Tipo de operación para logging
        contact_idx: Índice específico del contacto a actualizar (opcional)
    
    Returns:
        bool: True si ambas actualizaciones fueron exitosas
    """
    try:
        success_shared = False
        success_agent = False
        
        # Determinar qué contactos actualizar
        if contact_idx is not None:
            # Actualizar solo un contacto específico
            contacts_to_update = [contact_idx]
        else:
            # Actualizar todos los contactos del DataFrame local
            contacts_to_update = df_contactos.index.tolist()
        
        # 1. Actualizar sheet compartido (output)
        try:
            all_shared_success = True
            for idx in contacts_to_update:
                if not update_contact_in_sheet_safe(df_contactos, idx, URL_SHEET_CONTACTOS, agente_id, f"{operation_type}_SHARED"):
                    all_shared_success = False
                    print(f"[ERROR] {operation_type} - Error actualizando contacto {idx} en sheet compartido")
            
            success_shared = all_shared_success
            if success_shared:
                print(f"[DEBUG] {operation_type} - Sheet compartido actualizado exitosamente")
        except Exception as e:
            print(f"[ERROR] {operation_type} - Error en sheet compartido: {e}")
        
        # 2. Actualizar sheet específico del agente (si existe)
        try:
            agent_sheet_url = get_agent_sheet_url(agente_id)
            if agent_sheet_url != URL_SHEET_CONTACTOS:  # Solo si tiene sheet específico
                print(f"[DEBUG] {operation_type} - Intentando actualizar sheet individual del agente...")
                print(f"[DEBUG] {operation_type} - Sheet agente URL: {agent_sheet_url[:50]}...")
                
                all_agent_success = True
                permission_errors = 0
                
                for idx in contacts_to_update:
                    result = update_contact_in_sheet_safe(df_contactos, idx, agent_sheet_url, agente_id, f"{operation_type}_AGENT")
                    if not result:
                        all_agent_success = False
                        print(f"[ERROR] {operation_type} - Error actualizando contacto {idx} en sheet del agente")
                        
                        # 🔥 DETECTAR ERROR DE PERMISOS ESPECÍFICAMENTE
                        # Esto lo hacemos dentro de update_contact_in_sheet_safe con el logging mejorado
                
                success_agent = all_agent_success
                if success_agent:
                    print(f"[DEBUG] {operation_type} - Sheet del agente {agente_id} actualizado exitosamente")
                else:
                    print(f"[WARNING] {operation_type} - ⚠️ Sheet individual del agente NO actualizado")
                    print(f"[WARNING] {operation_type} - 🔥 Posible causa: El service account no tiene permisos de edición")
                    print(f"[WARNING] {operation_type} - 📋 Solución: Compartir sheet con service account o usar solo sheet compartido")
                    
                    # 🔥 NO FALLAR COMPLETAMENTE - CONTINUAR CON SHEET COMPARTIDO
                    print(f"[INFO] {operation_type} - Continuando con Sheet Compartido como fallback...")
                    success_agent = True  # No marcar como error para permitir continuación
            else:
                success_agent = True  # No hay sheet específico, solo usar compartido
                print(f"[DEBUG] {operation_type} - Agente {agente_id} usa solo sheet compartido")
        except Exception as e:
            print(f"[ERROR] {operation_type} - Error en sheet del agente: {e}")
            print(f"[WARNING] {operation_type} - Continuando con Sheet Compartido...")
            success_agent = True  # No marcar como error para permitir continuación
        
        return success_shared and success_agent
        
    except Exception as e:
        print(f"[ERROR] Error en update_both_sheets_safe: {e}")
        return False

def validate_agent_access(agente_id):
    """
    Valida si un agente tiene acceso al sistema.
    Solo agentes con sheet individual configurado pueden acceder.
    
    Args:
        agente_id: ID del agente
    
    Returns:
        tuple: (has_access: bool, message: str)
    """
    if agente_id in AGENT_SHEETS:
        return True, f"Agente {agente_id} autorizado con sheet individual"
    else:
        return False, f"Agente {agente_id} no tiene sheet individual configurado"

def get_agent_sheet_url(agente_id):
    """
    Obtiene la URL del sheet específico para un agente.
    Si no tiene sheet específico, usa el sheet por defecto.
    
    Args:
        agente_id: ID del agente
    
    Returns:
        str: URL del Google Sheet para el agente
    """
    if agente_id in AGENT_SHEETS:
        sheet_url = AGENT_SHEETS[agente_id]
        print(f"[DEBUG] Usando sheet específico para agente {agente_id}: {sheet_url[:50]}...")
        return sheet_url
    else:
        print(f"[DEBUG] Usando sheet por defecto para agente {agente_id}: {URL_SHEET_CONTACTOS[:50]}...")
        return URL_SHEET_CONTACTOS

def cargar_contactos_agente(cedula_agente, preserve_local_changes=True):
    """Carga contactos desde Google Sheets filtrados por cedula_agente usando su sheet específico
    
    Args:
        cedula_agente: ID del agente
        preserve_local_changes: Si True, preserva los cambios locales existentes
    """
    try:
        # Obtener la URL del sheet específico del agente
        agent_sheet_url = get_agent_sheet_url(cedula_agente)
        
        # Leer todos los contactos del Sheet específico del agente con rate limiting
        rate_limiter.check_and_wait(operation_type="read")
        spreadsheet_contactos = gc.open_by_url(agent_sheet_url)
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
        
        # ✅ PRESERVAR CAMBIOS LOCALES (si se solicita)
        if preserve_local_changes and 'df_contactos' in st.session_state and st.session_state.df_contactos is not None:
            df_local = st.session_state.df_contactos
            print(f"[SYNC] Preservando cambios locales de {len(df_local)} contactos...")
            
            # Identificar contactos modificados localmente
            contactos_modificados_local = df_local[
                df_local['estado'].isin(['Llamado', 'No Contesto', 'Gestionada'])
            ]
            
            if not contactos_modificados_local.empty:
                print(f"[SYNC] Se preservarán {len(contactos_modificados_local)} contactos con estados modificados")
                
                # Para cada contacto modificado localmente, actualizar su estado en el DataFrame cargado
                for _, local_row in contactos_modificados_local.iterrows():
                    # Buscar el contacto por teléfono en el DataFrame cargado
                    mask = df_agente['telefono'] == local_row['telefono']
                    if mask.any():
                        # Actualizar el estado y otros campos del contacto
                        idx_actualizar = df_agente[mask].index[0]
                        df_agente.loc[idx_actualizar, 'estado'] = local_row['estado']
                        df_agente.loc[idx_actualizar, 'observacion'] = local_row['observacion']
                        df_agente.loc[idx_actualizar, 'fecha_llamada'] = local_row['fecha_llamada']
                        df_agente.loc[idx_actualizar, 'duracion_seg'] = local_row['duracion_seg']
                        df_agente.loc[idx_actualizar, 'sid_llamada'] = local_row['sid_llamada']
                        df_agente.loc[idx_actualizar, 'agente_id'] = local_row['agente_id']
                        
                        print(f"[SYNC] Contacto {local_row['nombre']} - Estado preservado: {local_row['estado']}")
                    else:
                        print(f"[SYNC] ⚠️ No se encontró teléfono {local_row['telefono']} en Sheet")
                
                print(f"[SYNC] ✅ Cambios locales preservados exitosamente")
            else:
                print(f"[SYNC] No hay cambios locales que preservar")
        
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

# --- 3. AUDITORIA AUTOMATICA ---
if 'logs' not in st.session_state: st.session_state.logs = []

def add_log(mensaje, tipo="INFO"):
    t_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{t_stamp} | {st.session_state.get('agente_id', 'SYS')} | {tipo} | {mensaje}"
    st.session_state.logs.append(entry)
    # Imprimir en consola de Streamlit Cloud para debugging
    print(f"[LOG] {entry}")

# --- SISTEMA DE RECORDATORIOS INTELIGENTES ---
def verificar_recordatorios_proximos(df_contactos):
    """Verifica llamadas programadas en los próximos 5 minutos y muestra alertas
    
    Args:
        df_contactos: DataFrame con los contactos
        
    Returns:
        list: Lista de recordatorios encontrados
    """
    if df_contactos is None:
        return []
    
    ahora = obtener_hora_bogota()
    limite_tiempo = ahora + timedelta(minutes=5)
    
    # Filtrar contactos programados en los próximos 5 minutos
    programados_proximos = df_contactos[
        (df_contactos['estado'] == 'Programada') &
        (pd.notna(df_contactos['proxima_llamada'])) &
        (df_contactos['proxima_llamada'] != '')
    ].copy()
    
    if programados_proximos.empty:
        return []
    
    recordatorios = []
    
    for idx, contacto in programados_proximos.iterrows():
        try:
            fecha_prog = pd.to_datetime(contacto['proxima_llamada'])
            
            # Convertir a zona horaria de Bogotá si es necesario
            if fecha_prog.tzinfo is None:
                fecha_prog = TZ_BOGOTA.localize(fecha_prog)
            else:
                fecha_prog = fecha_prog.astimezone(TZ_BOGOTA)
            
            # Verificar si está en los próximos 5 minutos
            if ahora <= fecha_prog <= limite_tiempo:
                tiempo_restante = (fecha_prog - ahora).total_seconds()
                
                if tiempo_restante <= 300:  # 5 minutos = 300 segundos
                    minutos_restantes = int(tiempo_restante / 60)
                    segundos_restantes = int(tiempo_restante % 60)
                    
                    recordatorios.append({
                        'nombre': contacto['nombre'],
                        'telefono': contacto['telefono'],
                        'fecha_prog': fecha_prog,
                        'minutos_restantes': minutos_restantes,
                        'segundos_restantes': segundos_restantes,
                        'tiempo_segundos': tiempo_restante,
                        'idx': idx
                    })
                    
        except Exception as e:
            print(f"[ERROR] Error procesando recordatorio para {contacto.get('nombre', 'Unknown')}: {e}")
    
    # Ordenar por tiempo restante (más urgente primero)
    recordatorios.sort(key=lambda x: x['tiempo_segundos'])
    
    return recordatorios

def mostrar_recordatorios(recordatorios):
    """Muestra los recordatorios con alertas visuales animadas
    
    Args:
        recordatorios: Lista de recordatorios encontrados
    """
    if not recordatorios:
        return
    
    st.markdown("### 🔔 RECORDATORIOS INTELIGENTES")
    
    for recordatorio in recordatorios:
        urgencia_class = "reminder-urgent" if recordatorio['tiempo_segundos'] <= 60 else "reminder-alert"
        
        # Construir teléfono completo
        telefono = str(recordatorio['telefono'])
        if not telefono.startswith('+'):
            telefono = f"+57{telefono}"
        
        st.markdown(f"""
        <div class="{urgencia_class}">
            <div style="display: flex; align-items: center; margin-bottom: 8px;">
                <span style="font-size: 1.5em; margin-right: 10px;">⏰</span>
                <strong style="font-size: 1.2em;">¡LLAMADA INMINENTE!</strong>
            </div>
            <div style="margin-bottom: 5px;">
                <strong>📞 Contacto:</strong> {recordatorio['nombre']}
            </div>
            <div style="margin-bottom: 5px;">
                <strong>📱 Teléfono:</strong> {telefono}
            </div>
            <div class="countdown-timer">
                ⏱️ Tiempo restante: {recordatorio['minutos_restantes']}:{recordatorio['segundos_restantes']:02d}
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Agregar sonido de notificación automático (solo para muy urgentes)
        if recordatorio['tiempo_segundos'] <= 60:
            st.markdown("""
            <audio autoplay>
                <source src="data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2/LDciUFLIHO8tiJNwgZaLvt559NEAxQp+PwtmMcBjiR1/LMeSwFJHfH8N2QQAoUXrTp66hVFApGn+DyvmwhBSuBzvLZiTYIG2m98OScTgwOUarm7blmFgU7k9n1unEiBC13yO/eizEIHWq+8+OWT" type="audio/wav">
            </audio>
            """, unsafe_allow_html=True)

# --- DASHBOARD DE PRODUCTIVIDAD EN TIEMPO REAL ---
def calcular_metricas_productividad(df_contactos, df_informe=None):
    """Calcula métricas de productividad para el dashboard
    
    Args:
        df_contactos: DataFrame con los contactos
        df_informe: DataFrame con el informe de llamadas (opcional)
        
    Returns:
        dict: Diccionario con todas las métricas calculadas
    """
    if df_contactos is None:
        return {}
    
    ahora = obtener_hora_bogota()
    hoy = ahora.date()
    
    # Métricas básicas
    total_contactos = len(df_contactos)
    contactados = len(df_contactos[df_contactos['estado'] == 'Llamado'])
    no_contactados = len(df_contactos[df_contactos['estado'] == 'No Contesto'])
    programados = len(df_contactos[df_contactos['estado'] == 'Programada'])
    pendientes = len(df_contactos[df_contactos['estado'] == 'Pendiente'])
    
    # Tasa de contacto
    gestionados = contactados + no_contactados
    tasa_contacto = (contactados / gestionados * 100) if gestionados > 0 else 0
    
    # Duración promedio (si hay informe)
    duracion_promedio = 0
    if df_informe is not None and not df_informe.empty:
        # Convertir a numérico con manejo de errores
        duraciones_numericas = pd.to_numeric(df_informe['duracion_seg'], errors='coerce')
        duraciones = duraciones_numericas[duraciones_numericas.notna()]
        if not duraciones.empty:
            duracion_promedio = duraciones.mean()
    
    # Métricas del día de hoy
    llamadas_hoy = 0
    if df_informe is not None and not df_informe.empty:
        df_informe['fecha_llamada'] = pd.to_datetime(df_informe['fecha_llamada'], errors='coerce')
        llamadas_hoy = len(df_informe[df_informe['fecha_llamada'].dt.date == hoy])
    
    # Comparación con día anterior
    llamadas_ayer = 0
    if df_informe is not None and not df_informe.empty:
        ayer = hoy - timedelta(days=1)
        llamadas_ayer = len(df_informe[df_informe['fecha_llamada'].dt.date == ayer])
    
    delta_dias = llamadas_hoy - llamadas_ayer
    delta_porcentaje = (delta_dias / llamadas_ayer * 100) if llamadas_ayer > 0 else 0
    
    # Meta diaria (configurable)
    meta_diaria = 50  # Puede ser configurable en el futuro
    progreso_diario = (llamadas_hoy / meta_diaria * 100) if meta_diaria > 0 else 0
    
    return {
        'total_contactos': total_contactos,
        'contactados': contactados,
        'no_contactados': no_contactados,
        'programados': programados,
        'pendientes': pendientes,
        'tasa_contacto': tasa_contacto,
        'duracion_promedio': duracion_promedio,
        'llamadas_hoy': llamadas_hoy,
        'llamadas_ayer': llamadas_ayer,
        'delta_dias': delta_dias,
        'delta_porcentaje': delta_porcentaje,
        'meta_diaria': meta_diaria,
        'progreso_diario': progreso_diario
    }

def mostrar_dashboard_productividad(metricas):
    """Muestra el dashboard de productividad con visualización atractiva
    
    Args:
        metricas: Diccionario con las métricas calculadas
    """
    if not metricas:
        return
    
    st.markdown("### 📊 DASHBOARD DE PRODUCTIVIDAD")
    
    # Tarjetas principales
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        delta_class = "metric-positive" if metricas['delta_dias'] >= 0 else "metric-negative"
        delta_icon = "📈" if metricas['delta_dias'] >= 0 else "📉"
        
        st.markdown(f"""
        <div class="productivity-card">
            <h4>📞 Llamadas Hoy</h4>
            <h2>{metricas['llamadas_hoy']}</h2>
            <div class="{delta_class}">
                {delta_icon} {metricas['delta_dias']:+d} ({metricas['delta_porcentaje']:+.1f}%)
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="productivity-card">
            <h4>👥 Contactados</h4>
            <h2>{metricas['contactados']}</h2>
            <div>Tasa: {metricas['tasa_contacto']:.1f}%</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        duracion_minutos = int(metricas['duracion_promedio'] / 60) if metricas['duracion_promedio'] > 0 else 0
        duracion_segundos = int(metricas['duracion_promedio'] % 60) if metricas['duracion_promedio'] > 0 else 0
        
        st.markdown(f"""
        <div class="productivity-card">
            <h4>⏱️ Duración Promedio</h4>
            <h2>{duracion_minutos}:{duracion_segundos:02d}</h2>
            <div>{metricas['duracion_promedio']:.0f} segundos</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="productivity-card">
            <h4>📅 Programados</h4>
            <h2>{metricas['programados']}</h2>
            <div>Pendientes: {metricas['pendientes']}</div>
        </div>
        """, unsafe_allow_html=True)
    
    # Barra de progreso diaria
    st.markdown("### 🎯 META DIARIA")
    
    progress_color = "#28a745" if metricas['progreso_diario'] >= 100 else "#ffc107" if metricas['progreso_diario'] >= 50 else "#dc3545"
    
    st.markdown(f"""
    <div style="text-align: center; margin-bottom: 10px;">
        <strong>Progreso: {metricas['llamadas_hoy']} / {metricas['meta_diaria']} llamadas ({metricas['progreso_diario']:.1f}%)</strong>
    </div>
    <div class="progress-bar-container">
        <div class="progress-bar-fill" style="width: {min(metricas['progreso_diario'], 100)}%; background: {progress_color};">
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Mensaje motivacional
    if metricas['progreso_diario'] >= 100:
        st.success("🎉 ¡Felicidades! Has alcanzado tu meta diaria")
    elif metricas['progreso_diario'] >= 75:
        st.info("💪 ¡Estás muy cerca! ¡Sigue así!")
    elif metricas['progreso_diario'] >= 50:
        st.warning("⚡ Vamos bien, pero podemos mejorar")
    else:
        st.error("🔥 ¡Es momento de darlo todo!")

# --- SISTEMA DE BÚSQUEDA AVANZADA MEJORADO ---
def busqueda_avanzada(df_contactos, query):
    """Búsqueda predictiva robusta con manejo de casos especiales
    
    Args:
        df_contactos: DataFrame con los contactos
        query: Término de búsqueda
        
    Returns:
        tuple: (DataFrame filtrado, lista de resultados con puntuación)
    """
    if df_contactos is None or df_contactos.empty or not query.strip():
        return df_contactos, []
    
    query = query.lower().strip()
    print(f"[DEBUG] Búsqueda: '{query}' en {len(df_contactos)} contactos")
    
    resultados = []
    
    for idx, contacto in df_contactos.iterrows():
        puntuacion = 0
        coincidencias = []
        
        # 🔥 Búsqueda en nombre (3 puntos) - Manejo robusto
        nombre = str(contacto.get('nombre', '')).lower().strip()
        if query in nombre:
            puntuacion += 3
            coincidencias.append(f"Nombre: {contacto.get('nombre', '')}")
            print(f"[DEBUG] Coincidencia en nombre: {contacto.get('nombre', '')}")
        
        # 🔥 Búsqueda en teléfono (2 puntos) - Limpieza completa
        telefono_original = str(contacto.get('telefono', ''))
        telefono_limpio = telefono_original.replace('+57', '').replace('+', '').replace(' ', '').replace('-', '').replace('.', '').strip()
        query_telefono = query.replace('+57', '').replace('+', '').replace(' ', '').replace('-', '').replace('.', '').strip()
        
        if query_telefono in telefono_limpio:
            puntuacion += 2
            coincidencias.append(f"Teléfono: {telefono_original}")
            print(f"[DEBUG] Coincidencia en teléfono: {telefono_original}")
        
        # 🔥 Búsqueda en notas/observaciones (1 punto) - Manejo NaN
        notas = str(contacto.get('observacion', '')).lower().strip()
        if query in notas:
            puntuacion += 1
            coincidencias.append("Notas")
            print(f"[DEBUG] Coincidencia en notas")
        
        # 🔥 Búsqueda en estado (1 punto)
        estado = str(contacto.get('estado', '')).lower().strip()
        if query in estado:
            puntuacion += 1
            coincidencias.append(f"Estado: {contacto.get('estado', '')}")
            print(f"[DEBUG] Coincidencia en estado: {contacto.get('estado', '')}")
        
        # 🔥 Búsqueda parcial en nombre (2 puntos)
        palabras_nombre = nombre.split()
        for palabra in palabras_nombre:
            if query in palabra or palabra in query:
                puntuacion += 2
                coincidencias.append(f"Parcial: {palabra}")
                print(f"[DEBUG] Coincidencia parcial en nombre: {palabra}")
                break
        
        if puntuacion > 0:
            resultados.append({
                'idx': idx,
                'puntuacion': puntuacion,
                'coincidencias': coincidencias,
                'contacto': contacto
            })
            print(f"[DEBUG] Resultado encontrado: {contacto.get('nombre', '')} (puntuación: {puntuacion})")
    
    # Ordenar por puntuación (más relevante primero)
    resultados.sort(key=lambda x: x['puntuacion'], reverse=True)
    
    print(f"[DEBUG] Total resultados: {len(resultados)}")
    
    if resultados:
        # Crear DataFrame con resultados ordenados
        indices_resultado = [r['idx'] for r in resultados]
        df_resultado = df_contactos.loc[indices_resultado].copy()
        return df_resultado, resultados
    else:
        print(f"[DEBUG] No se encontraron resultados para '{query}'")
        return pd.DataFrame(), []

def mostrar_feedback_busqueda(resultados, query):
    """Muestra feedback visual de resultados encontrados
    
    Args:
        resultados: Lista de resultados con puntuación
        query: Término de búsqueda
    """
    if not resultados:
        if query.strip():
            st.info(f"🔍 No se encontraron resultados para '{query}'")
            st.write("💡 **Sugerencias:**")
            st.write("   • Intenta con diferentes palabras clave")
            st.write("   • Verifica la ortografía")
            st.write("   • Usa solo parte del nombre")
            st.write("   • Prueba con el número de teléfono sin +57")
        return
    
    total_resultados = len(resultados)
    puntuacion_max = max(r['puntuacion'] for r in resultados)
    
    # 🔥 FEEDBACK DETALLADO
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #e8f5e8, #c8e6c8); padding: 10px; border-radius: 8px; border-left: 4px solid #28a745; margin-bottom: 15px;">
        <strong>🔍 Resultados encontrados:</strong> {total_resultados} contactos para "{query}"<br>
        <small>📊 Relevancia máxima: {puntuacion_max}/5 puntos</small>
    </div>
    """, unsafe_allow_html=True)
    
    # Mostrar los 3 mejores resultados con detalles
    st.markdown("**🌟 Mejores coincidencias:**")
    for i, resultado in enumerate(resultados[:3]):
        contacto = resultado['contacto']
        telefono = str(contacto.get('telefono', ''))
        if not telefono.startswith('+'):
            telefono = f"+57{telefono}"
        
        st.markdown(f"""
        <div style="background: #f8f9fa; padding: 8px; border-radius: 5px; margin-bottom: 5px; border-left: 3px solid #007bff;">
            <strong>{i+1}. {contacto.get('nombre', '')}</strong> - {telefono}<br>
            <small>📍 {contacto.get('estado', '')} | 🎯 Puntuación: {resultado['puntuacion']}/5</small><br>
            <small>🔍 Coincidencias: {', '.join(resultado['coincidencias'])}</small>
        </div>
        """, unsafe_allow_html=True)

# --- SISTEMA DE NOTIFICACIONES INTELIGENTES ---
def analizar_notificaciones_contextuales(df_contactos, metricas):
    """Analiza el contexto y genera notificaciones inteligentes
    
    Args:
        df_contactos: DataFrame con los contactos
        metricas: Diccionario con métricas de productividad
        
    Returns:
        list: Lista de notificaciones contextuales
    """
    if df_contactos is None or metricas is None:
        return []
    
    notificaciones = []
    ahora = obtener_hora_bogota()
    hora_actual = ahora.hour
    
    # 1. Alerta de fin de jornada si meta no alcanzada
    if hora_actual >= 17 and metricas.get('progreso_diario', 0) < 80:
        llamadas_faltantes = metricas.get('meta_diaria', 50) - metricas.get('llamadas_hoy', 0)
        notificaciones.append({
            'tipo': 'alerta_meta',
            'titulo': '⏰ Fin de jornada',
            'mensaje': f'Te faltan {llamadas_faltantes} llamadas para alcanzar tu meta diaria',
            'urgencia': 'alta',
            'color': '#dc3545',
            'recomendacion': 'Concéntrate en llamadas rápidas o reagenda contactos difíciles'
        })
    
    # 2. Alerta de sin pendientes pero con programadas
    pendientes = metricas.get('pendientes', 0)
    programadas = metricas.get('programados', 0)
    
    if pendientes == 0 and programadas > 0:
        notificaciones.append({
            'tipo': 'sin_pendientes',
            'titulo': '📋 Sin pendientes',
            'mensaje': f'Tienes {programadas} llamadas programadas para seguir trabajando',
            'urgencia': 'media',
            'color': '#ffc107',
            'recomendacion': 'Revisa tus llamadas programadas y prepárate para las próximas'
        })
    
    # 3. Alerta de alta tasa de no contestación (>70%)
    gestionados = metricas.get('contactados', 0) + metricas.get('no_contactados', 0)
    if gestionados > 10:  # Solo si hay suficientes llamadas
        tasa_no_contestacion = (metricas.get('no_contactados', 0) / gestionados * 100) if gestionados > 0 else 0
        
        if tasa_no_contestacion > 70:
            notificaciones.append({
                'tipo': 'alta_no_contestacion',
                'titulo': '📈 Alta tasa de no contestación',
                'mensaje': f'Tu tasa de no contestación es del {tasa_no_contestacion:.1f}%',
                'urgencia': 'media',
                'color': '#fd7e14',
                'recomendacion': 'Considera cambiar el horario de llamadas o revisar la calidad de los datos'
            })
    
    # 4. Recomendación de mejor momento para llamar
    if 9 <= hora_actual <= 11:
        notificaciones.append({
            'tipo': 'mejor_momento',
            'titulo': '🌟 Mejor momento',
            'mensaje': 'Este es un excelente momento para llamar (9-11 AM)',
            'urgencia': 'info',
            'color': '#17a2b8',
            'recomendacion': 'Aprovecha las tasas de respuesta más altas del día'
        })
    elif 14 <= hora_actual <= 16:
        notificaciones.append({
            'tipo': 'buen_momento',
            'titulo': '⭐ Buen momento',
            'mensaje': 'Buen momento para continuar llamadas (2-4 PM)',
            'urgencia': 'info',
            'color': '#17a2b8',
            'recomendacion': 'Las tasas de respuesta siguen siendo buenas'
        })
    elif hora_actual >= 18:
        notificaciones.append({
            'tipo': 'fin_dia',
            'titulo': '🌆 Fin del día',
            'mensaje': 'Las tasas de respuesta disminuyen después de las 6 PM',
            'urgencia': 'baja',
            'color': '#6c757d',
            'recomendacion': 'Considera reprogramar para mañana o enfocarte en contactos prioritarios'
        })
    
    return notificaciones

def mostrar_notificaciones_inteligentes(notificaciones):
    """Muestra las notificaciones contextuales con diseño atractivo
    
    Args:
        notificaciones: Lista de notificaciones contextuales
    """
    if not notificaciones:
        return
    
    st.markdown("### 💡 NOTIFICACIONES INTELIGENTES")
    
    for notificacion in notificaciones:
        icono_urgencia = {
            'alta': '🔴',
            'media': '🟡',
            'baja': '🟢',
            'info': '🔵'
        }.get(notificacion['urgencia'], '⚪')
        
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, {notificacion['color']}22, {notificacion['color']}44);
            border-left: 5px solid {notificacion['color']};
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        ">
            <div style="display: flex; align-items: center; margin-bottom: 8px;">
                <span style="font-size: 1.2em; margin-right: 8px;">{icono_urgencia}</span>
                <strong style="font-size: 1.1em;">{notificacion['titulo']}</strong>
            </div>
            <div style="margin-bottom: 8px; color: #2c3e50;">
                {notificacion['mensaje']}
            </div>
            <div style="color: #6c757d; font-style: italic; font-size: 0.9em;">
                💡 {notificacion['recomendacion']}
            </div>
        </div>
        """, unsafe_allow_html=True)

# --- 6. REPORTES Y ANÁLISIS PERSONAL ---
def generar_reportes_personalizados(df_contactos, df_informe=None):
    """
    Genera reportes y análisis personalizados con gráficos interactivos,
    métricas clave y recomendaciones personalizadas según rendimiento.
    """
    if df_contactos is None or df_contactos.empty:
        st.info("📊 No hay datos disponibles para generar reportes.")
        return
    
    # Configuración de zona horaria
    bogota_tz = timezone('America/Bogota')
    ahora = datetime.now(bogota_tz)
    
    # Preparar datos para análisis
    try:
        # 🔍 DEBUG: Mostrar columnas disponibles
        print(f"[DEBUG] Columnas en df_contactos: {list(df_contactos.columns)}")
        print(f"[DEBUG] Columnas en df_informe: {list(df_informe.columns) if not df_informe.empty else 'DataFrame vacío'}")
        
        # Datos de contactos
        total_contactos = len(df_contactos)
        
        # 🔍 CORRECCIÓN: Verificar que exista la columna 'estado'
        if 'estado' in df_contactos.columns:
            llamados = len(df_contactos[df_contactos['estado'].isin(['Llamado', 'Gestionado'])])
            pendientes = len(df_contactos[df_contactos['estado'] == 'Pendiente'])
            no_contesto = len(df_contactos[df_contactos['estado'] == 'No Contesto'])
            programadas = len(df_contactos[df_contactos['estado'] == 'Programada'])
        else:
            print(f"[WARNING] Columna 'estado' no encontrada en df_contactos")
            # Fallback: contar todos como pendientes si no hay columna de estado
            llamados = 0
            pendientes = total_contactos
            no_contesto = 0
            programadas = 0
        
        # Calcular tasa de respuesta
        if (llamados + no_contesto) > 0:
            tasa_respuesta = (llamados / (llamados + no_contesto)) * 100
        else:
            tasa_respuesta = 0
        
        # Datos históricos si hay informe
        datos_semanales = []
        if df_informe is not None and not df_informe.empty:
            # Preprocesar fechas para filtrado eficiente
            if 'fecha_llamada' in df_informe.columns:
                df_informe['fecha_dt'] = pd.to_datetime(df_informe['fecha_llamada'], errors='coerce')
            
            # Últimos 7 días
            for i in range(7):
                fecha = ahora - timedelta(days=i)
                dia_semana = fecha.strftime('%A')
                
                # Filtrar datos del día
                if 'fecha_dt' in df_informe.columns:
                    dia_informe = df_informe[df_informe['fecha_dt'].dt.date == fecha.date()]
                elif 'fecha' in df_informe.columns:
                    try:
                        dia_informe = df_informe[df_informe['fecha'] == fecha.strftime('%Y-%m-%d')]
                    except KeyError:
                        dia_informe = pd.DataFrame()
                else:
                    dia_informe = pd.DataFrame()
                
                if not dia_informe.empty:
                    # 🔍 CORRECCIÓN: Usar columnas reales del sheet de informe
                    print(f"[DEBUG] Columnas disponibles en dia_informe: {list(dia_informe.columns)}")
                    
                    # Contar llamadas efectivas (estado 'Llamado' o 'Gestionado')
                    if 'estado' in dia_informe.columns:
                        llamadas_dia = len(dia_informe[dia_informe['estado'].isin(['Llamado', 'Gestionado'])])
                    else:
                        llamadas_dia = len(dia_informe)  # Fallback: contar todas las filas
                    
                    # Contar no contesto
                    if 'estado' in dia_informe.columns:
                        no_contesto_dia = len(dia_informe[dia_informe['estado'] == 'No Contesto'])
                    else:
                        no_contesto_dia = 0  # Fallback
                    
                    # 🔥 CORRECCIÓN: Calcular duración promedio con manejo de errores
                    if 'duracion_seg' in dia_informe.columns:
                        try:
                            # Convertir a numérico, ignorando valores no numéricos
                            duracion_numeric = pd.to_numeric(dia_informe['duracion_seg'], errors='coerce')
                            duracion_promedio = duracion_numeric.mean()
                            if pd.isna(duracion_promedio):
                                duracion_promedio = 0
                        except Exception as e:
                            print(f"[ERROR] Error calculando duración promedio: {e}")
                            duracion_promedio = 0  # Fallback
                    else:
                        duracion_promedio = 0  # Fallback
                    
                    print(f"[DEBUG] Día {fecha.strftime('%Y-%m-%d')}: {llamadas_dia} llamadas, {no_contesto_dia} no contesto, {duracion_promedio:.1f}s promedio")
                else:
                    llamadas_dia = 0
                    no_contesto_dia = 0
                    duracion_promedio = 0
                
                datos_semanales.append({
                    'dia': dia_semana,
                    'fecha': fecha.strftime('%Y-%m-%d'),
                    'llamadas': llamadas_dia,
                    'no_contesto': no_contesto_dia,
                    'tasa_respuesta': (llamadas_dia / (llamadas_dia + no_contesto_dia) * 100) if (llamadas_dia + no_contesto_dia) > 0 else 0,
                    'duracion_promedio': duracion_promedio
                })
        else:
            # Simular datos de la semana con datos actuales
            for i in range(7):
                fecha = ahora - timedelta(days=i)
                dia_semana = fecha.strftime('%A')
                
                # Simulación basada en rendimiento actual
                factor_simulacion = 0.8 + (random.random() * 0.4)  # Variación 20%
                llamadas_sim = int(llamados * factor_simulacion / 7) if i == 0 else int(llamados * factor_simulacion / 7 * (0.5 + random.random()))
                no_contesto_sim = int(no_contesto * factor_simulacion / 7) if i == 0 else int(no_contesto * factor_simulacion / 7 * (0.5 + random.random()))
                
                datos_semanales.append({
                    'dia': dia_semana,
                    'fecha': fecha.strftime('%Y-%m-%d'),
                    'llamadas': llamadas_sim,
                    'no_contesto': no_contesto_sim,
                    'tasa_respuesta': (llamadas_sim / (llamadas_sim + no_contesto_sim) * 100) if (llamadas_sim + no_contesto_sim) > 0 else 0,
                    'duracion_promedio': 180 + (random.random() * 120)  # 3-5 minutos promedio
                })
        
        df_semanal = pd.DataFrame(datos_semanales[::-1])  # Orden cronológico
        
        # Título del reporte
        st.markdown("### 📈 Reportes y Análisis Personal")
        st.markdown(f"**Análisis personalizado para el agente {st.session_state.agente_id}**")
        st.markdown(f"**Período:** {ahora.strftime('%d de %B de %Y')}")
        
        # Métricas Clave del Período
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "📞 Llamadas Efectivas", 
                llamados,
                delta=f"{tasa_respuesta:.1f}% tasa respuesta"
            )
        
        with col2:
            st.metric(
                "⏳ Pendientes", 
                pendientes,
                delta=f"{((pendientes/total_contactos)*100):.1f}% del total"
            )
        
        with col3:
            st.metric(
                "❌ No Contestaron", 
                no_contesto,
                delta=f"{((no_contesto/total_contactos)*100):.1f}% del total"
            )
        
        with col4:
            st.metric(
                "📅 Programadas", 
                programadas,
                delta=f"{((programadas/total_contactos)*100):.1f}% del total"
            )
        
        # Gráfico de Tendencias Semanales Interactivo
        st.markdown("#### 📊 Tendencias Semanales de Llamadas")
        
        # Crear gráfico interactivo con Plotly
        fig_tendencias = px.line(
            df_semanal, 
            x='dia', 
            y=['llamadas', 'no_contesto'],
            title='Evolución Semanal de Llamadas',
            labels={'value': 'Cantidad de Llamadas', 'dia': 'Día de la Semana'},
            color_discrete_map={'llamadas': '#28a745', 'no_contesto': '#dc3545'}
        )
        
        fig_tendencias.update_layout(
            hovermode='x unified',
            showlegend=True,
            height=400
        )
        
        fig_tendencias.update_traces(
            hovertemplate='<b>%{fullData.name}</b><br>Día: %{x}<br>Llamadas: %{y}<extra></extra>'
        )
        
        st.plotly_chart(fig_tendencias, width='stretch')
        
        # Gráfico de Tasa de Respuesta
        st.markdown("#### 📈 Tasa de Respuesta Semanal")
        
        fig_respuesta = px.bar(
            df_semanal,
            x='dia',
            y='tasa_respuesta',
            title='Tasa de Respuesta por Día (%)',
            labels={'tasa_respuesta': 'Tasa de Respuesta (%)', 'dia': 'Día'},
            color='tasa_respuesta',
            color_continuous_scale='RdYlGn'
        )
        
        fig_respuesta.update_layout(
            height=350,
            showlegend=False
        )
        
        fig_respuesta.update_traces(
            hovertemplate='<b>Día: %{x}</b><br>Tasa Respuesta: %{y:.1f}%<extra></extra>'
        )
        
        st.plotly_chart(fig_respuesta, width='stretch')
        
        # Insights y Recomendaciones Personalizadas
        st.markdown("#### 🎯 Insights y Recomendaciones Personalizadas")
        
        # Análisis de rendimiento
        insights = []
        recomendaciones = []
        
        # Análisis de tendencia
        if len(df_semanal) >= 3:
            tendencia_llamadas = df_semanal['llamadas'].tail(3).mean() - df_semanal['llamadas'].head(3).mean()
            if tendencia_llamadas > 0:
                insights.append("📈 **Tendencia Positiva:** Tu volumen de llamadas ha aumentado en los últimos días.")
                recomendaciones.append("✅ **Mantén el ritmo:** Continúa con tu estrategia actual, está funcionando bien.")
            else:
                insights.append("📉 **Tendencia a la Baja:** Tu volumen de llamadas ha disminuido recientemente.")
                recomendaciones.append("🔄 **Revisa tu enfoque:** Considera ajustar horarios o estrategias de contacto.")
        
        # Análisis de tasa de respuesta
        if tasa_respuesta >= 70:
            insights.append("🎯 **Excelente Tasa de Respuesta:** Tu tasa de respuesta es muy buena.")
            recomendaciones.append("🏆 **Sigue así:** Tu técnica de contacto es efectiva, compártela con el equipo.")
        elif tasa_respuesta >= 50:
            insights.append("📊 **Tasa de Respuesta Aceptable:** Estás en un buen nivel.")
            recomendaciones.append("💡 **Pequeños ajustes:** Prueba diferentes horarios para mejorar la tasa de respuesta.")
        else:
            insights.append("⚠️ **Tasa de Respuesta Baja:** Necesitas mejorar la efectividad de contacto.")
            recomendaciones.append("🎯 **Enfócate en horarios óptimos:** 9-11 AM y 2-4 PM suelen tener mejores tasas.")
        
        # Análisis de carga de trabajo
        if pendientes > total_contactos * 0.3:
            insights.append("📋 **Alta Carga Pendiente:** Tienes muchos contactos por gestionar.")
            recomendaciones.append("⏰ **Prioriza llamadas:** Enfócate en contactos más probables de responder.")
        elif pendientes < total_contactos * 0.1:
            insights.append("✅ **Carga Manejable:** Tienes una carga de trabajo equilibrada.")
            recomendaciones.append("🎯 **Calidad sobre cantidad:** Enfócate en la calidad de cada conversación.")
        
        # Análisis de programación
        if programadas > 0:
            insights.append(f"📅 **Llamadas Programadas:** Tienes {programadas} llamadas agendadas.")
            recomendaciones.append("⏰ **Prepárate con anticipación:** Revisa notas y prepara material para llamadas programadas.")
        
        # Análisis de hora actual
        hora_actual = ahora.hour
        if 9 <= hora_actual <= 11:
            insights.append("🌅 **Horario Óptimo:** Estás en el mejor momento para hacer llamadas.")
            recomendaciones.append("🚀 **Aprovecha el momento:** Este horario tiene las mejores tasas de respuesta.")
        elif 14 <= hora_actual <= 16:
            insights.append("🌆 **Buen Horario:** Estás en un buen momento para contactar.")
            recomendaciones.append("📞 **Continúa llamando:** Las tasas de respuesta siguen siendo buenas.")
        elif hora_actual >= 18:
            insights.append("🌃 **Fin de Jornada:** Las tasas de respuesta tienden a bajar.")
            recomendaciones.append("📋 **Prepara el día siguiente:** Organiza tus contactos para mañana.")
        
        # Mostrar insights y recomendaciones
        col_insights, col_recomendaciones = st.columns(2)
        
        with col_insights:
            st.markdown("""
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 10px; border-left: 4px solid #007bff;">
                <h4>🔍 Insights Clave</h4>
            </div>
            """, unsafe_allow_html=True)
            
            for insight in insights:
                st.markdown(f"<div style='margin: 8px 0;'>{insight}</div>", unsafe_allow_html=True)
        
        with col_recomendaciones:
            st.markdown("""
            <div style="background-color: #f0f8f0; padding: 15px; border-radius: 10px; border-left: 4px solid #28a745;">
                <h4>💡 Recomendaciones</h4>
            </div>
            """, unsafe_allow_html=True)
            
            for recomendacion in recomendaciones:
                st.markdown(f"<div style='margin: 8px 0;'>{recomendacion}</div>", unsafe_allow_html=True)
        
        # Métricas Adicionales
        st.markdown("#### 📊 Métricas Detalladas del Período")
        
        col_metricas1, col_metricas2, col_metricas3 = st.columns(3)
        
        with col_metricas1:
            # Mejor día de la semana
            mejor_dia = df_semanal.loc[df_semanal['llamadas'].idxmax()]
            st.markdown(f"""
            <div style="background-color: #e8f5e8; padding: 15px; border-radius: 10px; text-align: center;">
                <h5>🏆 Mejor Día</h5>
                <h3>{mejor_dia['dia']}</h3>
                <p>{mejor_dia['llamadas']} llamadas</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col_metricas2:
            # Promedio semanal
            promedio_semanal = df_semanal['llamadas'].mean()
            st.markdown(f"""
            <div style="background-color: #e8f4f8; padding: 15px; border-radius: 10px; text-align: center;">
                <h5>📊 Promedio Diario</h5>
                <h3>{promedio_semanal:.1f}</h3>
                <p>llamadas por día</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col_metricas3:
            # Meta diaria y progreso
            meta_diaria = st.session_state.get('meta_diaria', 50)
            progreso_meta = (llamados / meta_diaria) * 100 if meta_diaria > 0 else 0
            color_progreso = '#28a745' if progreso_meta >= 80 else '#ffc107' if progreso_meta >= 50 else '#dc3545'
            
            st.markdown(f"""
            <div style="background-color: #fff8e8; padding: 15px; border-radius: 10px; text-align: center;">
                <h5>🎯 Meta Diaria</h5>
                <h3>{progreso_meta:.1f}%</h3>
                <p>{llamados}/{meta_diaria} llamadas</p>
                <div style="background-color: #e0e0e0; border-radius: 5px; height: 8px; margin-top: 10px;">
                    <div style="background-color: {color_progreso}; width: {min(progreso_meta, 100)}%; height: 8px; border-radius: 5px;"></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        # Tabla de datos detallados
        st.markdown("#### 📋 Datos Detallados de la Semana")
        
        df_mostrar = df_semanal[['dia', 'llamadas', 'no_contesto', 'tasa_respuesta', 'duracion_promedio']].copy()
        df_mostrar.columns = ['Día', 'Llamadas', 'No Contestó', 'Tasa Respuesta (%)', 'Duración Promedio (s)']
        df_mostrar['Tasa Respuesta (%)'] = df_mostrar['Tasa Respuesta (%)'].round(1)
        df_mostrar['Duración Promedio (s)'] = df_mostrar['Duración Promedio (s)'].round(0).astype(int)
        
        st.dataframe(df_mostrar, width='stretch', hide_index=True)
        
        # Footer del reporte
        st.markdown(f"""
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 10px; margin-top: 20px; text-align: center;">
            <p><strong>📊 Reporte generado el {ahora.strftime('%d de %B de %Y a las %I:%M %p')}</strong></p>
            <p><em>Los datos se actualizan en tiempo real según tu actividad</em></p>
        </div>
        """, unsafe_allow_html=True)
        
    except Exception as e:
        st.error(f"❌ Error al generar reportes: {e}")
        print(f"[ERROR] Error en generar_reportes_personalizados: {e}")
        import traceback
        print(traceback.format_exc())

# --- 3. CONTROL DE ACCESO Y ESTADO ---
if 'agente_id' not in st.session_state:
    with st.form("login"):
        ced = st.text_input("Cédula:", type="password").strip()
        if st.form_submit_button("Entrar"):
            if ced in CEDULAS_AUTORIZADAS:
                # Validar si el agente tiene sheet individual configurado
                has_access, access_message = validate_agent_access(ced)
                
                if not has_access:
                    st.error(f"🚫 **Acceso Denegado**")
                    st.error(f"⚠️ {access_message}")
                    st.info("📋 **Para obtener acceso:**")
                    st.info("1. Contacta al administrador del sistema")
                    st.info("2. Solicita la configuración de tu sheet individual de llamadas")
                    st.info("3. Una vez configurado, podrás acceder normalmente")
                    st.warning("🔒 Solo agentes con sheet individual pueden usar el sistema")
                    add_log(f"ACCESO_DENEGADO: {ced} - Sin sheet individual", "AUTH")
                    st.stop()
                
                # Obtener número celular del agente desde secrets
                numero_celular = NUMEROS_CELULAR_AGENTES.get(ced)
                
                if not numero_celular:
                    st.error(f"⚠️ No se encontró número celular configurado para la cédula {ced}. Contacta al administrador.")
                    st.stop()
                
                st.session_state.agente_id = ced
                st.session_state.numero_celular_agente = numero_celular
                add_log(f"LOGIN_EXITOSO - Número: {numero_celular} - Sheet individual: SÍ", "AUTH")
                
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
if 'agente_id' not in st.session_state: st.session_state.agente_id = None
if 'df_contactos' not in st.session_state: st.session_state.df_contactos = None
if 'llamada_activa_sid' not in st.session_state: st.session_state.llamada_activa_sid = None
if 'webrtc_activo' not in st.session_state: st.session_state.webrtc_activo = False
if 'draft_notas' not in st.session_state: st.session_state.draft_notas = {}
if 'meta_diaria' not in st.session_state: st.session_state.meta_diaria = 50
if 't_inicio_dt' not in st.session_state: st.session_state.t_inicio_dt = None
if 'grabacion_pausada' not in st.session_state: st.session_state.grabacion_pausada = False
if 'pagina_actual' not in st.session_state: st.session_state.pagina_actual = 0
if 'numero_celular_agente' not in st.session_state: st.session_state.numero_celular_agente = None
if 'en_pausa' not in st.session_state: st.session_state.en_pausa = False
if 'pausa_inicio' not in st.session_state: st.session_state.pausa_inicio = None

# Estados para control de refresh inteligente
if 'usuario_interactuando' not in st.session_state: st.session_state.usuario_interactuando = False
if 'ultima_interaccion' not in st.session_state: st.session_state.ultima_interaccion = time.time()
if 'refresh_pausado' not in st.session_state: st.session_state.refresh_pausado = False

# ✅ RECUPERACIÓN AUTOMÁTICA DE LLAMADAS ACTIVAS AL RECARGAR PÁGINA
if st.session_state.agente_id and not st.session_state.llamada_activa_sid and not st.session_state.webrtc_activo:
    print(f"[PERSISTENCE] Agente {st.session_state.agente_id} logueado, verificando llamadas activas...")
    if restaurar_llamada_activa():
        st.success("🔄 ⚠️ ¡LLAMADA ACTIVA RECUPERADA!")
        st.warning("La página se recargó pero había una llamada en curso. El estado ha sido restaurado.")
        st.info("Puedes continuar gestionando la llamada normalmente.")
        
        # Forzar rerun para mostrar la llamada activa
        time.sleep(2)
        st.rerun()
    else:
        print(f"[PERSISTENCE] No hay llamadas activas para restaurar")

# ✅ SINCRONIZACIÓN INTELIGENTE AL RECARGAR (Evitar sobreescribir cambios locales)
if st.session_state.agente_id and 'df_contactos' in st.session_state and st.session_state.df_contactos is not None:
    print(f"[SYNC] Verificando si hay cambios locales pendientes antes de recargar contactos...")
    
    # Verificar si hay contactos con estados modificados localmente
    cambios_locales = False
    if st.session_state.df_contactos is not None and not st.session_state.df_contactos.empty:
        # Buscar contactos que ya no estén en "Pendientes" pero podrían estar desactualizados en el Sheet
        contactos_modificados = st.session_state.df_contactos[
            st.session_state.df_contactos['estado'].isin(['Llamado', 'No Contesto', 'Gestionada'])
        ]
        
        if not contactos_modificados.empty:
            cambios_locales = True
            print(f"[SYNC] Se detectaron {len(contactos_modificados)} contactos con estados modificados localmente")
            
            # 🔥 OPTIMIZACIÓN: Sincronizar solo contactos que realmente cambiaron desde la última sincronización
            try:
                # 🔥 VERIFICAR SI EL USUARIO ESTÁ CAMBIANDO DE PESTAÑA RÁPIDAMENTE
                last_user_action = st.session_state.get('ultimo_refresh_llamada', 0)
                time_since_last_action = time.time() - last_user_action
                
                # Si el usuario cambió de pestaña hace menos de 2 segundos, omitir sincronización
                if time_since_last_action < 2:
                    print(f"[SYNC] ⚠️ Usuario cambiando de pestaña rápidamente ({time_since_last_action:.1f}s), omitiendo sincronización...")
                    cambios_locales = False  # Marcar como si no hubiera cambios para saltar sincronización
                
                # Verificar si ya hay una sincronización en progreso para evitar duplicados
                sync_key = f"sync_in_progress_{st.session_state.agente_id}"
                if sync_key not in st.session_state:
                    st.session_state[sync_key] = False
                
                # Si ya hay una sincronización en progreso, saltar
                if st.session_state[sync_key]:
                    print(f"[SYNC] ⚠️ Sincronización ya en progreso, omitiendo...")
                    cambios_locales = False  # Marcar como si no hubiera cambios para saltar sincronización
                
                st.session_state[sync_key] = True
                
                # 🔥 LIMITAR A MÁXIMO 3 CONTACTOS POR SINCRONIZACIÓN PARA EVITAR TIMEOUTS
                contactos_a_sincronizar = contactos_modificados.head(3)
                print(f"[SYNC] 🔥 OPTIMIZACIÓN: Sincronizando solo {len(contactos_a_sincronizar)} de {len(contactos_modificados)} contactos")
                
                if update_both_sheets_safe(contactos_a_sincronizar, st.session_state.agente_id, "SYNC_ON_RELOAD_OPTIMIZED"):
                    print(f"[SYNC] ✅ Cambios locales sincronizados con Sheet exitosamente")
                    add_log(f"SYNC_ON_RELOAD: {len(contactos_a_sincronizar)} contactos sincronizados (optimizado)", "DATA")
                    
                    # 🔥 MARCAR COMO SINCRONIZADOS PARA NO VOLVER A PROCESARLOS
                    for idx in contactos_a_sincronizar.index:
                        # Agregar marca de sincronización
                        if 'ultima_sincronizacion' not in st.session_state:
                            st.session_state.ultima_sincronizacion = {}
                        st.session_state.ultima_sincronizacion[idx] = datetime.now().isoformat()
                else:
                    print(f"[SYNC] ⚠️ Error sincronizando cambios locales")
                    add_log(f"SYNC_ON_RELOAD_ERROR: Falló sincronización", "ERROR")
                
                # Liberar el flag de sincronización
                st.session_state[sync_key] = False
                
            except Exception as e:
                print(f"[SYNC] ERROR sincronizando cambios: {e}")
                add_log(f"SYNC_EXCEPTION: {e}", "ERROR")
                # Liberar el flag en caso de error
                if sync_key in st.session_state:
                    st.session_state[sync_key] = False
    
    if not cambios_locales:
        print(f"[SYNC] No hay cambios locales pendientes, se puede recargar desde Sheet normalmente")
if 'ultimo_refresh_llamada' not in st.session_state: st.session_state.ultimo_refresh_llamada = 0
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
                # Usar la función segura con concurrencia y sanitización en el sheet compartido de salida
                if update_sheet_safe(st.session_state.df_contactos, "0", sheet_url=URL_SHEET_CONTACTOS, agente_id=st.session_state.get('agente_id', 'auto_guardado')):
                    st.session_state.ultimo_autoguardado = ahora
                    st.session_state.cambios_pendientes = False
                    print("[AUTOGUARDADO] ✅ Cambios guardados automáticamente con seguridad")
                    add_log("AUTO_GUARDADO: Cambios sincronizados con seguridad", "SISTEMA")
                else:
                    print("[AUTOGUARDADO] ⚠️ Error guardando cambios, se reintentará en 30s")
            except Exception as e:
                print(f"[AUTOGUARDADO] ❌ Error: {e}")

def mostrar_historial_notas_visual(contacto, idx):
    """
    Muestra el historial completo de notas de un contacto de forma visual
    con timestamps, categorías y separación clara entre cada nota.
    """
    notas_completas = str(contacto.get('observacion', '')) if pd.notna(contacto.get('observacion')) else ''
    
    if notas_completas and notas_completas.strip():
        with st.expander(f"📋 Historial Completo de Notas - {contacto['nombre']}", expanded=False):
            # Parsear notas separadas por " | "
            notas_individuales = notas_completas.split(' | ')
            
            st.markdown("**📝 Cronología de todas las notas (más reciente primero):**")
            
            import re
            for i, nota_individual in enumerate(reversed(notas_individuales)):
                nota_individual = nota_individual.strip()
                if nota_individual:
                    # Detectar timestamp [YYYY-MM-DD HH:MM] y categoría (Categoría)
                    timestamp_categoria_match = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s*\(([^)]+)\)', nota_individual)
                    timestamp_solo_match = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]', nota_individual)
                    
                    if timestamp_categoria_match:
                        # Formato nuevo: [timestamp] (categoría) nota
                        timestamp = timestamp_categoria_match.group(1)
                        categoria = timestamp_categoria_match.group(2)
                        nota_texto = nota_individual.replace(f'[{timestamp}] ({categoria})', '').strip()
                        
                        # Colores por categoría
                        if categoria == 'Pendiente':
                            border_color = '#ffc107'  # Amarillo
                            bg_color = '#fff8e1'
                            categoria_icon = '⏳'
                        elif categoria == 'No Contesto':
                            border_color = '#dc3545'  # Rojo
                            bg_color = '#ffebee'
                            categoria_icon = '📞❌'
                        elif categoria == 'Llamado':
                            border_color = '#17a2b8'  # Azul
                            bg_color = '#e1f5fe'
                            categoria_icon = '📞✅'
                        elif categoria == 'Gestionada':
                            border_color = '#28a745'  # Verde
                            bg_color = '#e8f5e8'
                            categoria_icon = '✅'
                        elif categoria == 'Programada':
                            border_color = '#6f42c1'  # Púrpura
                            bg_color = '#f3e5f5'
                            categoria_icon = '📅'
                        else:
                            border_color = '#6c757d'  # Gris
                            bg_color = '#f8f9fa'
                            categoria_icon = '📝'
                        
                        orden_badge = "🟢 **MÁS RECIENTE**" if i == 0 else f"#{len(notas_individuales) - i}"
                        
                        st.markdown(f"""
                        <div style="
                            border-left: 4px solid {border_color}; 
                            padding: 12px; 
                            margin: 8px 0; 
                            background-color: {bg_color};
                            border-radius: 8px;
                            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                        ">
                            <div style="font-size: 12px; color: #666; margin-bottom: 8px; display: flex; justify-content: space-between;">
                                <span><strong>{orden_badge}</strong></span>
                                <span>📅 {timestamp}</span>
                            </div>
                            <div style="font-size: 13px; color: #444; margin-bottom: 6px;">
                                <strong>{categoria_icon} Categoría: {categoria}</strong>
                            </div>
                            <div style="font-size: 14px; color: #222; line-height: 1.4;">
                                {nota_texto}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                        
                    elif timestamp_solo_match:
                        # Formato anterior: [timestamp] nota
                        timestamp = timestamp_solo_match.group(1)
                        nota_texto = nota_individual.replace(f'[{timestamp}]', '').strip()
                        
                        orden_badge = "🟡 **RECIENTE**" if i == 0 else f"#{len(notas_individuales) - i}"
                        
                        st.markdown(f"""
                        <div style="
                            border-left: 4px solid #1f77b4; 
                            padding: 12px; 
                            margin: 8px 0; 
                            background-color: #f8f9fa;
                            border-radius: 8px;
                        ">
                            <div style="font-size: 12px; color: #666; margin-bottom: 8px; display: flex; justify-content: space-between;">
                                <span><strong>{orden_badge}</strong></span>
                                <span>📅 {timestamp}</span>
                            </div>
                            <div style="font-size: 13px; color: #444; margin-bottom: 6px;">
                                <strong>📝 Nota sin categoría específica</strong>
                            </div>
                            <div style="font-size: 14px; color: #222; line-height: 1.4;">
                                {nota_texto}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        # Nota sin timestamp (muy antigua)
                        orden_badge = "📄 **HISTÓRICA**" if i == len(notas_individuales) - 1 else f"#{len(notas_individuales) - i}"
                        
                        st.markdown(f"""
                        <div style="
                            border-left: 4px solid #28a745; 
                            padding: 12px; 
                            margin: 8px 0; 
                            background-color: #f1f8e9;
                            border-radius: 8px;
                        ">
                            <div style="font-size: 12px; color: #666; margin-bottom: 8px;">
                                <strong>{orden_badge}</strong> • Sin timestamp
                            </div>
                            <div style="font-size: 14px; color: #222; line-height: 1.4;">
                                {nota_individual}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
            
            # Mostrar estadísticas del historial
            total_notas = len([n for n in notas_individuales if n.strip()])
            categorias_detectadas = set()
            for nota in notas_individuales:
                categoria_match = re.search(r'\([^)]+\)', nota)
                if categoria_match:
                    categorias_detectadas.add(categoria_match.group(0).strip('()'))
            
            st.markdown("---")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("📊 Total Notas", total_notas)
            with col2:
                st.metric("🔄 Categorías", len(categorias_detectadas) if categorias_detectadas else 1)
            with col3:
                st.metric("📍 Estado Actual", contacto.get('estado', 'Sin estado'))
            
            if categorias_detectadas:
                st.caption(f"🏷️ **Categorías registradas:** {', '.join(sorted(categorias_detectadas))}")
    else:
        st.info("📝 Sin notas registradas para este contacto")
        st.caption("💡 **Tip:** Las notas se guardan automáticamente con timestamp y categoría cuando presiona 'Guardar Notas'")

def marcar_cambios_pendientes():
    """Marca que hay cambios pendientes para auto-guardar"""
    st.session_state.cambios_pendientes = True
    print("[DEBUG] Cambios pendientes marcados para auto-guardado")

# Función para detectar interacción del usuario
def detectar_interaccion_usuario():
    """Detecta si el usuario está interactuando con la interfaz"""
    # Marcar interacción cuando hay cambios en session_state
    if hasattr(st.session_state, '_last_widget_state'):
        current_state = {k: v for k, v in st.session_state.items() if not k.startswith('_')}
        if current_state != st.session_state._last_widget_state:
            st.session_state.usuario_interactuando = True
            st.session_state.ultima_interaccion = time.time()
            print(f"[DEBUG] Interacción detectada - Pausando refresh agresivo")
    
    st.session_state._last_widget_state = {k: v for k, v in st.session_state.items() if not k.startswith('_')}
    
    # Si han pasado más de 3 segundos sin interacción, permitir refresh
    if time.time() - st.session_state.ultima_interaccion > 3:
        st.session_state.usuario_interactuando = False

def refresh_inteligente_llamada(forzar=False):
    """Refresh inteligente que respeta la interacción del usuario"""
    detectar_interaccion_usuario()
    
    # Si el usuario está interactuando, usar refresh menos agresivo
    if st.session_state.usuario_interactuando and not forzar:
        # Refresh cada 5 segundos cuando el usuario está interactuando
        if time.time() - st.session_state.ultimo_refresh_llamada > 5:
            st.session_state.ultimo_refresh_llamada = time.time()
            print(f"[DEBUG] Refresh suave - Usuario interactuando")
            time.sleep(1)
            st.rerun()
    else:
        # Refresh normal cada 2 segundos cuando no hay interacción
        if time.time() - st.session_state.ultimo_refresh_llamada > 2:
            st.session_state.ultimo_refresh_llamada = time.time()
            print(f"[DEBUG] Refresh normal - Sin interacción")
            time.sleep(1)
            st.rerun()

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
    
    # 🔥 BOTÓN DE EMERGENCIA - LIMPIAR ESTADO DE LLAMADA
    if (st.session_state.llamada_activa_sid or st.session_state.webrtc_activo):
        st.error("⚠️ **ESTADO DE LLAMADA DETECTADO**")
        st.caption("El sistema detecta que hay una llamada activa")
        
        if st.button("🚨 FORZAR LIMPIEZA DE LLAMADA", type="primary"):
            st.warning("🔄 Limpiando estado de llamada forzadamente...")
            
            # 🔥 LIMPIEZA COMPLETA DE ESTADO
            st.session_state.llamada_activa_sid = None
            st.session_state.conference_name = None
            st.session_state.conference_idx = None
            st.session_state.webrtc_activo = False
            st.session_state.webrtc_numero = None
            st.session_state.webrtc_nombre = None
            st.session_state.webrtc_call_sid = None
            st.session_state.webrtc_idx = None
            st.session_state.grabacion_pausada = False
            st.session_state.finalizacion_manual_agente = False
            
            # Limpiar cookie
            try:
                limpiar_cookie_llamada_activa()
                st.success("✅ Cookie limpiada")
            except Exception as e:
                st.error(f"❌ Error limpiando cookie: {e}")
            
            add_log("FORCE_CLEAR_CALL_STATE", "EMERGENCY")
            st.success("✅ **ESTADO LIMPIADO EXITOSAMENTE**")
            st.info("🔄 La página se recargará en 2 segundos...")
            time.sleep(2)
            st.rerun()
    else:
        st.success("✅ No hay llamadas activas")
    
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
    total_llamados = len(df[df['estado'].isin(['Llamado', 'Gestionado'])])
    
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

tab_op, tab_met, tab_reportes, tab_sup, tab_aud, tab_pruebas = st.tabs(["📞 Operación", "📊 Mis Métricas", "📈 Reportes", "👤 Supervisor", "📜 Auditoría", "🧪 Pruebas"])

with tab_met:
    st.subheader("📊 Dashboard de Productividad en Tiempo Real")
    
    # Calcular y mostrar métricas
    if st.session_state.df_contactos is not None:
        # Obtener datos del informe para métricas avanzadas
        try:
            df_informe = read_sheet("0") if URL_SHEET_INFORME else pd.DataFrame()
        except:
            df_informe = pd.DataFrame()
        
        # Calcular métricas
        metricas = calcular_metricas_productividad(st.session_state.df_contactos, df_informe)
        
        # Mostrar dashboard
        mostrar_dashboard_productividad(metricas)
        
        # Auto-refresh cada 30 segundos para llamadas próximas
        if 'ultimo_refresh_dashboard' not in st.session_state:
            st.session_state.ultimo_refresh_dashboard = time.time()
        
        if time.time() - st.session_state.ultimo_refresh_dashboard > 30:
            st.session_state.ultimo_refresh_dashboard = time.time()
            st.rerun()
        
        st.caption("🔄 Auto-refresh cada 30 segundos")
    else:
        st.warning("⚠️ No hay datos de contactos disponibles")
    
    st.divider()
    
    # Métricas adicionales (mantener compatibilidad con datos históricos)
    st.subheader("📈 Métricas Históricas")
    if not df_historico.empty:
        # Aseguramos que la columna agente_id existe para filtrar
        if 'agente_id' in df_historico.columns:
            df_agente = df_historico[df_historico['agente_id'].astype(str) == str(st.session_state.agente_id)]
            if not df_agente.empty:
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Gestionados", len(df_agente))
                m2.metric("Efectividad", f"{(len(df_agente[df_agente['estado']=='Llamado'])/len(df_agente)*100):.1f}%")
                m3.metric("Promedio Duración", f"{pd.to_numeric(df_agente['duracion_seg'], errors='coerce').mean():.1f}s")
                st.plotly_chart(px.pie(df_agente, names='estado', title="Distribución de Estados"), width='stretch')
            else:
                st.info(f"No hay registros en el Sheet para el agente {st.session_state.agente_id}.")
        else:
            st.error("La columna 'agente_id' no se encuentra en el Sheet de informe.")
    else:
        st.warning("No hay datos en el Sheet de informe.")

with tab_reportes:
    st.subheader("📈 Reportes y Análisis Personal")
    
    # Obtener datos para reportes
    df_contactos = st.session_state.df_contactos
    
    try:
        df_informe = read_sheet("0") if URL_SHEET_INFORME else pd.DataFrame()
    except:
        df_informe = pd.DataFrame()
    
    # Generar reportes personalizados
    generar_reportes_personalizados(df_contactos, df_informe)

with tab_sup:
    if st.session_state.agente_id == "12345678":
        st.subheader("Panel de Control Gerencial")
        if not df_historico.empty:
            st.write("Resumen por Agente Humano:")
            resumen_sup = df_historico.groupby(['agente_id', 'estado']).size().unstack(fill_value=0)
            st.dataframe(resumen_sup, width='stretch')
            st.plotly_chart(px.bar(df_historico, x='agente_id', color='estado', title="Productividad por Cédula"), width='stretch')
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
    # --- SISTEMA DE RECORDATORIOS INTELIGENTES ---
    if st.session_state.df_contactos is not None:
        # Verificar recordatorios próximos
        recordatorios = verificar_recordatorios_proximos(st.session_state.df_contactos)
        
        # Mostrar recordatorios si hay alguno
        if recordatorios:
            mostrar_recordatorios(recordatorios)
            
            # Auto-refresh más frecuente cuando hay recordatorios
            if 'ultimo_refresh_recordatorios' not in st.session_state:
                st.session_state.ultimo_refresh_recordatorios = time.time()
            
            # Refresh cada 15 segundos cuando hay recordatorios activos
            if time.time() - st.session_state.ultimo_refresh_recordatorios > 15:
                st.session_state.ultimo_refresh_recordatorios = time.time()
                st.rerun()
    
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
    
    # 🔥 CORRECCIÓN: Validación robusta de df_contactos
    if st.session_state.df_contactos is not None and not st.session_state.df_contactos.empty:
        df = st.session_state.df_contactos
    else:
        df = pd.DataFrame()  # DataFrame vacío como fallback
        
        # 🔥 MANEJO DE ESTADO LIMPIO CUANDO df ESTÁ VACÍO
        st.warning("⚠️ No hay contactos cargados. Intenta recargar la página.")
        
        # Limpiar estado de llamada si hay datos inconsistentes
        if 'conference_idx' in st.session_state or 'llamada_activa_sid' in st.session_state:
            print(f"[DEBUG] Limpiando estado de llamada debido a df vacío")
            if 'conference_idx' in st.session_state:
                del st.session_state.conference_idx
            if 'llamada_activa_sid' in st.session_state:
                del st.session_state.llamada_activa_sid
            if 'conference_name' in st.session_state:
                del st.session_state.conference_name
            if 't_inicio_dt' in st.session_state:
                del st.session_state.t_inicio_dt
            
            st.info("🔄 Estado de llamada limpiado. Por favor, recarga la página.")
            
        # Botón para recargar
        if st.button("🔄 Recargar Contactos", key="reload_contacts"):
            st.rerun()
            
        st.stop()  # Detener ejecución si no hay contactos
    
    # 🔥 LÓGICA DE MAPEO DE PESTAÑA A ESTADO DEL DF (solo si hay contactos)
    opc = st.radio("Ver:", ["Pendientes", "No Contestaron", "Programadas", "Gestionadas"], horizontal=True, key="pestana_opciones")
    # 🔥 CORRECCIÓN: Mapeo correcto de pestañas a estados del sheet del agente
    # Pendientes = "Pendiente" o vacío/NaN en campo estado
    # Programadas = "Programada" en campo estado  
    # No Contestaron = "No Contesto" en campo estado
    # Gestionadas = "Llamado" o "Gestionado" en campo estado
    if "Pendientes" in opc:
        f_est = "Pendiente"  # También incluirá valores vacíos/NaN en el filtrado
    elif "Programadas" in opc:
        f_est = "Programada"
    elif "No Contestaron" in opc:
        f_est = "No Contesto"
    else:  # Gestionadas
        f_est = "Gestionado"  # También incluirá "Llamado" en el filtrado
    
    # 🔥 DEBUG: Verificar datos por categoría
    print(f"[DEBUG] Categoría seleccionada: {opc} -> Estado: {f_est}")
    print(f"[DEBUG] Total contactos en df: {len(df)}")
    if not df.empty:
        estados_disponibles = df['estado'].value_counts()
        print(f"[DEBUG] Estados disponibles: {estados_disponibles.to_dict()}")
        contactos_categoria = len(df[df['estado'] == f_est])
        print(f"[DEBUG] Contactos en {f_est}: {contactos_categoria}")
        
        # 🔥 DEBUG ADICIONAL: Verificar valores exactos
        estados_unicos = df['estado'].unique()
        print(f"[DEBUG] Estados únicos en df: {list(estados_unicos)}")
        print(f"[DEBUG] Buscando estado exacto: '{f_est}'")
        
        # Verificar si hay espacios o caracteres extra
        for estado in estados_unicos:
            if str(estado).strip() == f_est:
                print(f"[DEBUG] Coincidencia encontrada (con strip): '{estado}' == '{f_est}'")
            elif str(estado) == f_est:
                print(f"[DEBUG] Coincidencia exacta: '{estado}' == '{f_est}'")
    
    # 🔥 REDIRECCIÓN AUTOMÁTICA A "PROGRAMADAS" SI SE PROGRAMÓ UNA LLAMADA
    if hasattr(st.session_state, 'pestana_actual') and st.session_state.pestana_actual == "Programadas":
        # Usar variable de control separada (no modificar st.radio directamente)
        st.session_state.redireccionar_a_programadas = True
        # Limpiar el estado de redirección
        del st.session_state.pestana_actual
    
    # 🔥 APLICAR REDIRECCIÓN SI ES NECESARIO
    if hasattr(st.session_state, 'redireccionar_a_programadas') and st.session_state.redireccionar_a_programadas:
        # Forzar la pestaña "Programadas" usando la lógica de mapeo
        f_est = "Programada"
        # Limpiar el estado de redirección
        del st.session_state.redireccionar_a_programadas
    
    # --- BÚSQUEDA AVANZADA ---
    st.markdown("### 🔍 Búsqueda Avanzada")
    search = st.text_input("🔍 Buscar Cliente (nombre, teléfono, notas, estado):", placeholder="Ej: Juan, 3001234567, pendiente...")
    
    # 🔥 FILTRO INTELIGENTE CORREGIDO SEGÚN ESTADOS REALES DEL SHEET
    print(f"[DEBUG] Aplicando filtro para categoría: {opc}")
    
    if "Pendientes" in opc:
        # Pendientes = "Pendiente" o valores vacíos/NaN en campo estado
        df_work = df[(df['estado'] == 'Pendiente') | (df['estado'].isna()) | (df['estado'] == '')]
        print(f"[DEBUG] Filtro Pendientes (Pendiente/vacío/NaN) aplicado - Resultados: {len(df_work)}")
    elif "Gestionadas" in opc:
        # Gestionadas = "Llamado" o "Gestionado" 
        df_work = df[df['estado'].isin(['Llamado', 'Gestionado'])]
        print(f"[DEBUG] Filtro Gestionadas (Llamado/Gestionado) aplicado - Resultados: {len(df_work)}")
    else:
        # Para Programadas y No Contestaron: filtro exacto
        # 🔥 CORRECCIÓN: Normalizar estado para comparación
        df_work = df[df['estado'].str.strip() == f_est]
        print(f"[DEBUG] Filtro {f_est} aplicado - Resultados: {len(df_work)}")
        
        # Si no hay resultados, intentar sin strip
        if df_work.empty:
            df_work = df[df['estado'] == f_est]
            print(f"[DEBUG] Filtro sin strip - Resultados: {len(df_work)}")
    
    print(f"[DEBUG] df_work final tiene {len(df_work)} contactos")
    
    # 🔥 MOSTRAR CONTACTO ACTIVO DE CONFERENCE CALL EN SECCIÓN DESTACADA
    # ✅ CORRECCIÓN: Limpiar estado activo de todos los contactos primero
    if 'activo_en_conference' in df_work.columns:
        df_work['activo_en_conference'] = False
    
    # Marcar solo el contacto realmente activo
    if 'conference_idx' in st.session_state and 'llamada_activa_sid' in st.session_state and st.session_state.llamada_activa_sid is not None:
        idx_activo = st.session_state.conference_idx
        
        # 🔥 CORRECCIÓN: Validar que df no sea None ni esté vacío
        if df is not None and not df.empty and idx_activo < len(df):
            contacto_activo = df.iloc[idx_activo]
            
            # Si el contacto activo no está en el filtrado, agregarlo
            if idx_activo not in df_work.index:
                print(f"[DEBUG] Contacto activo {idx_activo} no está en filtro '{f_est}', agregando...")
                # 🔥 CORRECCIÓN: Crear copia para evitar SettingWithCopyWarning
                df_work = pd.concat([df_work, df.iloc[[idx_activo]]], ignore_index=False).copy()
                
                # Marcar SOLO este contacto como activo para identificación visual
                df_work.loc[idx_activo, 'activo_en_conference'] = True
                print(f"[DEBUG] Contacto activo agregado al filtrado y marcado como activo")
            else:
                # Ya está en el filtrado, marcar SOLO este como activo
                # 🔥 CORRECCIÓN: Crear copia antes de modificar
                df_work = df_work.copy()
                df_work.loc[idx_activo, 'activo_en_conference'] = True
                print(f"[DEBUG] Contacto activo ya estaba en filtrado, marcado como activo")
        else:
            print(f"[WARNING] Índice de contacto activo {idx_activo} inválido")
    else:
        # 🔥 CORRECCIÓN: Si no hay llamada activa, asegurarse de que ningún contacto aparezca como activo
        if 'activo_en_conference' in df_work.columns:
            df_work['activo_en_conference'] = False
        print(f"[DEBUG] Sin llamada activa - limpiando estados activos")
    
    # Aplicar búsqueda avanzada si hay término de búsqueda
    resultados_busqueda = []
    if search:
        df_work, resultados_busqueda = busqueda_avanzada(df_work, search)
        mostrar_feedback_busqueda(resultados_busqueda, search)
    
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

    # 🔥 MOSTRAR CONTACTO ACTIVO DE CONFERENCE CALL EN SECCIÓN DESTACADA
    contacto_activo_mostrado = False
    idx_activo = None
    
    if 'conference_idx' in st.session_state and 'llamada_activa_sid' in st.session_state:
        idx_activo = st.session_state.conference_idx
        
        # 🔥 CORRECCIÓN CRÍTICA: Validar que idx_activo no sea None y sea válido
        if df is not None and not df.empty and idx_activo is not None and isinstance(idx_activo, int) and idx_activo >= 0 and idx_activo < len(df):
            contacto_activo = df.iloc[idx_activo]
            inicio_llamada = st.session_state.get('t_inicio_dt', datetime.now())
            
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #ff6b6b, #ee5a24); color: white; padding: 20px; border-radius: 15px; margin-bottom: 20px; box-shadow: 0 8px 25px rgba(255, 107, 107, 0.3);">
                <div style="display: flex; align-items: center; margin-bottom: 10px;">
                    <span style="font-size: 28px; margin-right: 15px;">📞</span>
                    <strong style="font-size: 18px;">LLAMADA ACTIVA</strong>
                    <span style="margin-left: auto; font-size: 24px;">🔴 EN CURSO</span>
                </div>
                <div style="font-size: 16px;">
                    <strong>👤 Contacto:</strong> {contacto_activo['nombre']}<br>
                    <strong>📱 Teléfono:</strong> {contacto_activo['telefono']}<br>
                    <strong>⏰ Inicio:</strong> {inicio_llamada.strftime('%H:%M:%S')}<br>
                    <strong>📊 Estado:</strong> {contacto_activo.get('estado', 'Pendiente')}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            contacto_activo_mostrado = True
            print(f"[DEBUG] Mostrando contacto activo destacado: {contacto_activo['nombre']}")
    
    # 🔥 EXCLUIR CONTACTO ACTIVO DE LA LISTA NORMAL PARA EVITAR DUPLICACIÓN
    if contacto_activo_mostrado and idx_activo is not None:
        # Eliminar el contacto activo de df_work para evitar duplicación
        if idx_activo in df_work.index:
            df_work = df_work.drop(idx_activo)
            print(f"[DEBUG] Contacto activo {idx_activo} excluido de lista normal para evitar duplicación")
        else:
            print(f"[DEBUG] Contacto activo {idx_activo} no estaba en df_work")
    
    # 🔥 EXCLUIR TAMBIÉN CONTACTO WEBRTC ACTIVO PARA EVITAR DUPLICACIÓN
    webrtc_activo = st.session_state.get('webrtc_activo', False)
    webrtc_idx = st.session_state.get('webrtc_idx', None)
    
    if webrtc_activo and webrtc_idx is not None:
        # Eliminar el contacto WebRTC activo de df_work para evitar duplicación
        if webrtc_idx in df_work.index:
            df_work = df_work.drop(webrtc_idx)
            print(f"[DEBUG] Contacto WebRTC activo {webrtc_idx} excluido de lista normal para evitar duplicación")
        else:
            print(f"[DEBUG] Contacto WebRTC activo {webrtc_idx} no estaba en df_work")
    
    if not df_work.empty:
        # Mostrar TODOS los contactos de la página (hasta 30)
        st.write(f"**Mostrando {len(df_work)} contactos:**")
            
        # Iterar sobre TODOS los contactos de la página
        for idx in df_work.index:
            # 🔥 VALIDACIÓN ADICIONAL - Asegurar que el índice sea válido
            if idx >= len(st.session_state.df_contactos):
                print(f"[WARNING] Índice {idx} inválido en df_work, saltando contacto")
                continue
                
            c = df_work.loc[idx]
            # Construir número completo desde CSV (codigo_pais + telefono)
            if 'codigo_pais' in c.index and pd.notna(c['codigo_pais']):
                tel = f"+{str(c['codigo_pais']).replace('+', '')}{str(c['telefono'])}"
            else:
                tel = str(c['telefono']) if str(c['telefono']).startswith('+') else f"+{str(c['telefono'])}"

            # 🔥 IDENTIFICACIÓN VISUAL ESPECIAL PARA CONTACTO ACTIVO
            # 🔥 CORRECCIÓN: Asegurar que es_activo sea booleano, no float
            es_activo = bool(c.get('activo_en_conference', False))
            icono_activo = "🔴" if es_activo else "📞"
            titulo_activo = f" {icono_activo} **LLAMANDO** - " if es_activo else f" {icono_activo} "
            
            # 🔥 CORRECCIÓN: Convertir es_activo a int para expanded parameter
            with st.expander(f"{titulo_activo}{c['nombre']} - {tel}", expanded=bool(es_activo)):
                col1, col2 = st.columns([2,1])
                
                # 🔥 INDICADOR VISUAL PARA CONTACTO ACTIVO
                if es_activo:
                    st.markdown("""
                    <div style="background: linear-gradient(135deg, #ff6b6b, #ee5a24); color: white; padding: 10px; border-radius: 8px; margin-bottom: 10px; text-align: center;">
                        <strong>🔴 LLAMADA EN CURSO - CONTACTO ACTIVO</strong>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col1:
                        # Mostrar información de programación si está programada
                        if c['estado'] == 'Programada' and pd.notna(c.get('proxima_llamada')) and c.get('proxima_llamada'):
                            try:
                                fecha_prog = pd.to_datetime(c['proxima_llamada'])
                                fecha_formateada = fecha_prog.strftime("%Y-%m-%d %H:%M")
                                ahora = obtener_hora_bogota()
                                tiempo_restante = fecha_prog - ahora
                                
                                # MENSAJE MÁS VISIBLE Y DETALLADO
                                if tiempo_restante.total_seconds() > 0:
                                    dias_restantes = int(tiempo_restante.total_seconds() / 86400)
                                    horas_restantes = int((tiempo_restante.total_seconds() % 86400) / 3600)
                                    minutos_restantes = int((tiempo_restante.total_seconds() % 3600) / 60)
                                    
                                    if dias_restantes > 0:
                                        tiempo_texto = f"en {dias_restantes} día(s), {horas_restantes}h {minutos_restantes}m"
                                    elif horas_restantes > 0:
                                        tiempo_texto = f"en {horas_restantes}h {minutos_restantes}m"
                                    else:
                                        tiempo_texto = f"en {minutos_restantes} minutos"
                                    
                                    st.markdown(f"""
                                    <div style="background: linear-gradient(135deg, #2196f3, #1976d2); color: white; padding: 15px; border-radius: 10px; border-left: 5px solid #0d47a1; margin-bottom: 15px; box-shadow: 0 4px 15px rgba(33, 150, 243, 0.3);">
                                        <div style="display: flex; align-items: center; margin-bottom: 8px;">
                                            <span style="font-size: 24px; margin-right: 10px;">📅</span>
                                            <strong style="font-size: 16px;">LLAMADA PROGRAMADA</strong>
                                        </div>
                                        <div style="font-size: 14px; margin-bottom: 5px;">
                                            <strong>📞 Fecha y hora:</strong> {fecha_formateada}
                                        </div>
                                        <div style="font-size: 14px; margin-bottom: 5px;">
                                            <strong>⏰ Realizar llamada:</strong> {tiempo_texto}
                                        </div>
                                        <div style="font-size: 12px; opacity: 0.9;">
                                            <small>📍 Zona horaria: Bogotá (UTC-5)</small>
                                        </div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                else:
                                    # LLAMADA ATRASADA
                                    st.markdown(f"""
                                    <div style="background: linear-gradient(135deg, #ff6b6b, #ff4444); color: white; padding: 15px; border-radius: 10px; border-left: 5px solid #cc0000; margin-bottom: 15px; box-shadow: 0 4px 15px rgba(255, 107, 107, 0.3);">
                                        <div style="display: flex; align-items: center; margin-bottom: 8px;">
                                            <span style="font-size: 24px; margin-right: 10px;">⚠️</span>
                                            <strong style="font-size: 16px;">LLAMADA ATRASADA</strong>
                                        </div>
                                        <div style="font-size: 14px; margin-bottom: 5px;">
                                            <strong>📞 Programada para:</strong> {fecha_formateada}
                                        </div>
                                        <div style="font-size: 14px;">
                                            <strong>🔴 Debió realizarse hace:</strong> {abs(tiempo_restante.total_seconds() / 3600):.1f} horas
                                        </div>
                                    </div>
                                    """, unsafe_allow_html=True)
                            except Exception as e:
                                st.info(f"📅 Programado para: {c['proxima_llamada']}")
                        
                        st.markdown(f"<div class='client-card'><h3>{c['nombre']}</h3><p>Tel: {tel}</p></div>", unsafe_allow_html=True)
                        
                        # Mostrar historial completo de notas con categorías
                        mostrar_historial_notas_visual(c, idx)
                        
                        nota_existente = st.session_state.draft_notas.get(idx, '')
                        nota = st.text_area("📝 Nueva Nota:", value=nota_existente, key=f"notas_{idx}", placeholder="Escriba aquí sus observaciones...")
                        
                        # Auto-guardar cuando el agente modifica notas
                        if nota != nota_existente:
                            # 🔍 VALIDACIÓN ANTES DE AUTO-GUARDAR
                            if idx >= len(st.session_state.df_contactos):
                                print(f"[DEBUG] Índice inválido en auto-guardado: {idx}")
                                # Limpiar draft inválido
                                if idx in st.session_state.draft_notas:
                                    del st.session_state.draft_notas[idx]
                            else:
                                # Guardar en draft para evitar pérdida de datos
                                st.session_state.draft_notas[idx] = nota
                                # Limpiar draft después de guardar
                                if idx in st.session_state.draft_notas:
                                    del st.session_state.draft_notas[idx]
                                
                                # Forzar refresh para mostrar el historial actualizado
                                refresh_inteligente_llamada(forzar=True)

                with col2:
                    if not st.session_state.en_pausa:
                        # Verificar si hay llamada activa (Conference o WebRTC)
                        llamada_activa = st.session_state.llamada_activa_sid is not None or st.session_state.webrtc_activo
                        
                        if not llamada_activa:
                            # 🎛️ PANEL DE BOTONES DE LLAMADA
                            st.markdown("""
                            <div style="background: #f8f9fa; padding: 15px; border-radius: 10px; border: 2px solid #dee2e6; margin-bottom: 15px;">
                                <h4 style="margin: 0 0 10px 0; color: #495057;">🎛️ Opciones de Llamada</h4>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            # Botón principal: Conference Call
                            if st.button("📞 LLAMAR (Conference Call)", type="primary", width='stretch', key=f"call_{idx}"):
                                try:
                                    # 🔍 VALIDACIÓN ANTES DE INICIAR LLAMADA
                                    print(f"[DEBUG] Botón Conference Call presionado - idx: {idx}")
                                    print(f"[DEBUG] Contacto actual: {c['nombre']} - {tel}")
                                    
                                    # Validar que no haya llamada activa
                                    if st.session_state.llamada_activa_sid is not None:
                                        st.error(f"❌ ERROR: Ya hay una llamada activa")
                                        st.stop()
                                    
                                    # Validar número del agente
                                    if not st.session_state.numero_celular_agente:
                                        st.error(f"❌ ERROR: No hay número de agente configurado")
                                        st.stop()
                                    
                                    # Crear conference call
                                    print(f"[DEBUG] Iniciando conference call")
                                    conference_name = f"Room_{st.session_state.agente_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                                    
                                    # TwiML para el agente
                                    twiml_agente = f"""<?xml version="1.0" encoding="UTF-8"?>
                                    <Response>
                                        <Say language="es-MX" voice="alice">Conectando llamada</Say>
                                        <Dial callerId="{twilio_number}" timeout="30">
                                            <Conference 
                                                startConferenceOnEnter="true"
                                                endConferenceOnExit="true"
                                                record="record-from-start"
                                                recordingStatusCallback="{function_url_base}/recording-status"
                                                trim="trim-silence"
                                                transcribe="true"
                                                transcribeCallback="{function_url_base}/transcription-callback"
                                                waitUrl=""
                                                beep="false"
                                                maxParticipants="2"
                                                quiet="false"
                                            >{conference_name}</Conference>
                                        </Dial>
                                    </Response>"""
                                    
                                    # TwiML para el cliente
                                    twiml_cliente = f"""<?xml version="1.0" encoding="UTF-8"?>
                                    <Response>
                                        <Dial timeout="30" record="true">
                                            <Conference 
                                                startConferenceOnEnter="true"
                                                endConferenceOnExit="true"
                                                record="record-from-start"
                                                recordingStatusCallback="{function_url_base}/recording-status"
                                                trim="trim-silence"
                                                transcribe="true"
                                                transcribeCallback="{function_url_base}/transcription-callback"
                                                waitUrl=""
                                                beep="false"
                                                maxParticipants="2"
                                                quiet="false"
                                            >{conference_name}</Conference>
                                        </Dial>
                                    </Response>"""
                                    
                                    # Llamar al agente primero
                                    call_agente = client.calls.create(
                                        twiml=twiml_agente,
                                        to=st.session_state.numero_celular_agente,
                                        from_=twilio_number,
                                        status_callback=f"{function_url}/status",
                                        status_callback_event=['initiated', 'ringing', 'answered', 'completed']
                                    )
                                    
                                    # Llamar al cliente con Caller ID del agente
                                    numero_agente = st.session_state.numero_celular_agente
                                    call_cliente = client.calls.create(
                                        twiml=twiml_cliente,
                                        to=tel,
                                        from_=numero_agente,
                                        machine_detection='Enable',
                                        status_callback=f"{function_url}/status",
                                        status_callback_event=['initiated', 'ringing', 'answered', 'completed']
                                    )
                                    
                                    # Guardar estado de la llamada
                                    st.session_state.llamada_activa_sid = call_cliente.sid
                                    st.session_state.conference_name = conference_name
                                    st.session_state.conference_idx = idx
                                    st.session_state.t_inicio_dt = datetime.now()
                                    
                                    # ✅ GUARDAR ESTADO EN COOKIES PARA RECUPERACIÓN
                                    guardar_llamada_activa_en_cookie()
                                    
                                    print(f"[DEBUG] Conference Call iniciada exitosamente")
                                    add_log(f"CONFERENCE_CALL_SUCCESS - Cliente: {tel} - Caller ID: {numero_agente}", "TWILIO")
                                    
                                    st.success(f"✅ Conference Call iniciada exitosamente")
                                    st.info(f"📞 Agente: Recibirás llamada de {twilio_number}")
                                    st.info(f"📱 Cliente: Verá tu número {numero_agente}")
                                    
                                    time.sleep(1)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ Error al iniciar llamada: {e}")
                                    print(f"[ERROR] Error en conference call: {e}")
                                    import traceback
                                    print(traceback.format_exc())
                                    
                                    # 🔥 RECUPERACIÓN DE ESTADO EN CASO DE ERROR
                                    add_log(f"CONFERENCE_CALL_ERROR - {e}", "ERROR")
                                    
                                    # Limpiar estado parcial si algo falló
                                    if 'llamada_activa_sid' in st.session_state and st.session_state.llamada_activa_sid:
                                        try:
                                            client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                                            print(f"[DEBUG] Llamada parcial colgada por error")
                                        except:
                                            pass
                                        finally:
                                            st.session_state.llamada_activa_sid = None
                                            st.session_state.conference_idx = None
                                            st.session_state.conference_name = None
                                    
                                    st.warning("🔄 Estado limpiado. Intenta nuevamente.")
                            
                            # Botón alternativo: WebRTC
                            st.markdown("---")
                            st.markdown("**Opción alternativa:**")
                            if st.button("🎧 LLAMAR (WebRTC)", width='stretch', key=f"call_webrtc_{idx}"):
                                # Marcar WebRTC como activo y guardar datos
                                st.session_state.webrtc_activo = True
                                st.session_state.webrtc_numero = tel
                                st.session_state.webrtc_nombre = c['nombre']
                                st.session_state.webrtc_idx = idx  # Guardar el índice del contacto activo
                                st.session_state.t_inicio_dt = datetime.now()
                                
                                # ✅ GUARDAR ESTADO EN COOKIES PARA RECUPERACIÓN
                                guardar_llamada_activa_en_cookie()
                                
                                add_log(f"WEBRTC_START: {c['nombre']} - {tel}", "TWILIO")
                                st.rerun()
                            
                            # Información sobre las opciones
                            with st.expander("📋 Información sobre opciones de llamada", expanded=False):
                                st.markdown("""
                                ### 📞 **Conference Call (Recomendado)**
                                - ✅ Llama desde tu celular/tablet
                                - ✅ Mejor calidad de audio
                                - ✅ Puedes moverte libremente
                                - ✅ Grabación automática
                                
                                ### 🎧 **WebRTC (Alternativa)**
                                - 📱 Llama desde el navegador
                                - 🔊 Usa micrófono y altavoces de la computadora
                                - 📡 Requiere conexión estable a internet
                                - 🎯 Bueno para pruebas rápidas
                                """)
                            
                            # 🔥 BOTONES DE ACCIÓN SIEMPRE DISPONIBLES (GUARDAR NOTAS Y REPROGRAMAR)
                            st.divider()
                            st.markdown("### 📝 **Acciones de Gestión**")
                            
                            # 🔥 INFORMACIÓN PARA CONTACTOS "NO CONTESTO" (SIN BOTÓN MANUAL)
                            if c['estado'] == 'No Contesto':
                                st.info("🔔 **Este contacto no contestó la llamada**")
                                st.caption("💡 El estado se clasificó automáticamente según el resultado de la llamada")
                            
                            # Botones de acción principales
                            col_btn1, col_btn2 = st.columns(2)
                            with col_btn1:
                                if st.button("💾 Guardar Notas", key=f"save_notes_{idx}", width='stretch'):
                                    # Obtener nota existente
                                    nota_existente = str(st.session_state.df_contactos.at[idx, 'observacion']) if pd.notna(st.session_state.df_contactos.at[idx, 'observacion']) else ''
                                    
                                    # Combinar notas si ya existe algo
                                    if nota_existente and nota_existente.strip():
                                        if nota.strip() and nota != nota_existente:
                                            # Acumular notas con timestamp y contexto de categoría
                                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                                            categoria_actual = st.session_state.df_contactos.at[idx, 'estado'] if 'estado' in st.session_state.df_contactos.columns else 'Sin categoría'
                                            nota_acumulada = f"{nota_existente} | [{timestamp}] ({categoria_actual}) {nota}"
                                        else:
                                            nota_acumulada = nota_existente  # Mantener existente si la nueva está vacía o es igual
                                    else:
                                        # Agregar timestamp y categoría a la primera nota
                                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                                        categoria_actual = st.session_state.df_contactos.at[idx, 'estado'] if 'estado' in st.session_state.df_contactos.columns else 'Sin categoría'
                                        nota_acumulada = f"[{timestamp}] ({categoria_actual}) {nota}"  # Primera nota con timestamp y categoría
                                    
                                    # Actualizar DataFrame local con notas acumuladas
                                    st.session_state.df_contactos.at[idx, 'observacion'] = nota_acumulada
                                    
                                    # Actualizar tanto Sheet compartido como Sheet del agente
                                    if URL_SHEET_CONTACTOS:
                                        try:
                                            if update_both_sheets_safe(st.session_state.df_contactos, st.session_state.agente_id, "NOTAS_ACUMULADAS", contact_idx=idx):
                                                add_log(f"NOTAS_ACUMULADAS: {c['nombre']}", "ACCION")
                                                st.success("✅ Notas acumuladas en ambos sheets (compartido y agente)")
                                            else:
                                                st.warning("⚠️ Notas acumuladas localmente, pero error actualizando sheets")
                                        except Exception as e:
                                            st.error(f"❌ Error acumulando notas: {e}")
                                    else:
                                        st.success("✅ Notas acumuladas localmente")
                                    
                                    time.sleep(1)
                                    st.rerun()
                            
                            with col_btn2:
                                if st.button("📅 Reprogramar", key=f"prog_{idx}", width='stretch'):
                                    # Obtener hora actual en Bogotá para valores por defecto
                                    hora_bogota_actual = obtener_hora_bogota()
                                    
                                    # Mostrar diálogo simple para reprogramar
                                    st.markdown("#### 📅 **Reprogramar Llamada**")
                                    col_prog1, col_prog2 = st.columns(2)
                                    with col_prog1:
                                        fecha_prog = st.date_input("Fecha:", value=hora_bogota_actual.date(), key=f"fecha_prog_{idx}")
                                    with col_prog2:
                                        hora_prog = st.time_input("Hora:", value=hora_bogota_actual.time(), key=f"hora_prog_{idx}")
                                    
                                    # Botón para confirmar programación
                                    if st.button("✅ Confirmar Programación", key=f"confirm_prog_{idx}", type="primary"):
                                        # Combinar fecha y hora
                                        fecha_hora_prog = datetime.combine(fecha_prog, hora_prog)
                                        
                                        # Actualizar estado a "Programada"
                                        st.session_state.df_contactos.at[idx, 'estado'] = 'Programada'
                                        st.session_state.df_contactos.at[idx, 'proxima_llamada'] = fecha_hora_prog.isoformat()
                                        
                                        # Actualizar sheets
                                        if URL_SHEET_CONTACTOS:
                                            try:
                                                if update_both_sheets_safe(st.session_state.df_contactos, st.session_state.agente_id, "PROGRAMAR_LLAMADA", contact_idx=idx):
                                                    add_log(f"PROGRAMAR: {c['nombre']} - {fecha_hora_prog.strftime('%Y-%m-%d %H:%M')}", "ACCION")
                                                    st.success(f"✅ Llamada programada para {fecha_hora_prog.strftime('%Y-%m-%d %H:%M')}")
                                                else:
                                                    st.warning("⚠️ Llamada programada localmente, pero error actualizando sheets")
                                            except Exception as e:
                                                st.error(f"❌ Error programando llamada: {e}")
                                        else:
                                            st.success(f"✅ Llamada programada localmente para {fecha_hora_prog.strftime('%Y-%m-%d %H:%M')}")
                                        
                                        time.sleep(1)
                                        st.rerun()
                            
                            # ============================================================
                        # MONITOR DINÁMICO CUANDO HAY LLAMADA ACTIVA
                        # ============================================================
                        else:
                            # --- MONITOR PARA WEBRTC ---
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
                                            
                                            # PRIORIDAD ALTA 1: Número inválido/inexistente (códigos ampliados)
                                            if remote_call.status == 'failed' and error_code in ['21217', '21214', '21211', '21612', '30001', '30003']:
                                                webrtc_final_status = 'No Contesto'
                                                st.error(f"❌ Número inválido o inexistente (error {error_code})")
                                                print(f"[DEBUG] Clasificado como No Contesto - Número inválido: {error_code}")
                                            
                                            # PRIORIDAD MEDIA 1: Número bloqueado/spam/no entregado
                                            elif remote_call.status == 'failed' and error_code in ['21610', '30006', '30004']:
                                                webrtc_final_status = 'No Contesto'
                                                st.error(f"🚫 Número bloqueado, spam o mensaje no entregado (error {error_code})")
                                                print(f"[DEBUG] Clasificado como No Contesto - Número bloqueado/no entregado: {error_code}")
                                            
                                            # PRIORIDAD MEDIA 2: Error de red (podría reintentar)
                                        elif remote_call.status == 'failed' and error_code in ['31005', '31002', '31003', '31009']:
                                            webrtc_final_status = 'No Contesto'
                                            st.warning(f"⚠️ Error de red - Considerar reintento (error {error_code})")
                                            print(f"[DEBUG] Clasificado como No Contesto - Error de red: {error_code}")
                                        
                                        # Estados intermedios - Llamada en progreso
                                        elif remote_call.status in ['in-progress', 'queued', 'ringing']:
                                            webrtc_final_status = 'Llamado'  # Asumimos que está en progreso
                                            st.info(f"📞 Llamada en progreso: {remote_call.status}")
                                            print(f"[DEBUG] Clasificado como Llamado - Estado intermedio: {remote_call.status}")
                                        
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
                                        
                                        # PRIORIDAD ALTA 3: Buzón de voz mejorado (detección ampliada)
                                        elif answered_by in ['machine_start', 'machine_end_beep', 'machine_end_silence', 'fax']:
                                            if duracion_twilio < 5:
                                                webrtc_final_status = 'No Contesto'
                                                st.warning(f"📞 Buzón lleno o no dejó mensaje ({duracion_twilio}s) - Tipo: {answered_by}")
                                                print(f"[DEBUG] Clasificado como No Contesto - Buzón lleno - Tipo: {answered_by}")
                                            else:
                                                webrtc_final_status = 'No Contesto'
                                                st.warning(f"📞 Contestó buzón de voz ({duracion_twilio}s) - Tipo: {answered_by}")
                                                print(f"[DEBUG] Clasificado como No Contesto - Buzón de voz - Tipo: {answered_by}")
                                        
                                        # Caso 3: Contestó una persona (humano) - Validación de duración
                                        elif answered_by == 'human':
                                            if duracion_twilio >= 300:  # 5 minutos o más
                                                st.info(f"📞 Conversación larga detectada ({duracion_twilio}s = {duracion_twilio//60}min {duracion_twilio%60}s)")
                                                print(f"[DEBUG] Conversación larga: {duracion_twilio}s")
                                            webrtc_final_status = 'Llamado'
                                            st.success(f"✅ Llamada contestada por persona ({duracion_twilio}s)")
                                            print(f"[DEBUG] Clasificado como Llamado por humano - Duración: {duracion_twilio}s")
                                        
                                        # PRIORIDAD ALTA 2: Cliente colgó inmediatamente vs No contestó (casos especiales de duración)
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
                                            elif duracion_twilio == 10:
                                                webrtc_final_status = 'Llamado'
                                                st.info(f"⚖️ Llamada en límite exacto (10s) - Clasificada como Llamado")
                                                print(f"[DEBUG] Clasificado como Llamado - Duración límite exacto: 10s")
                                            elif duracion_twilio >= 300:  # 5 minutos o más
                                                webrtc_final_status = 'Llamado'
                                                st.success(f"✅ Conversación larga ({duracion_twilio}s = {duracion_twilio//60}min {duracion_twilio%60}s)")
                                                print(f"[DEBUG] Clasificado como Llamado - Conversación larga: {duracion_twilio}s")
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
                                        # Marcar si fue finalización manual por el agente
                                        agent_ended_call = finalizar_webrtc and not call_ended_by_remote
                                        
                                        # Si es finalización manual, colgar la llamada en Twilio primero
                                        if finalizar_webrtc and st.session_state.webrtc_call_sid:
                                            try:
                                                client.calls(st.session_state.webrtc_call_sid).update(status='completed')
                                                time.sleep(1)
                                            except Exception as e:
                                                print(f"[ERROR] Error colgando llamada: {e}")
                                        
                                        # Determinar estado final: Si el agente finalizó manualmente, marcar como Gestionada
                                        if agent_ended_call:
                                            webrtc_final_status = 'Gestionada'
                                            print(f"[DEBUG] WebRTC - Finalización manual por agente - Clasificado como Gestionada")
                                        # Si no, mantener la clasificación automática ya determinada
                                        
                                        # Guardar gestión
                                        t_fin = datetime.now()
                                        dur = int((t_fin - st.session_state.t_inicio_dt).total_seconds())
                                        
                                        # --- PASO 1: ACTUALIZACIÓN LOCAL INMEDIATA ---
                                        print(f"[DEBUG] Actualizando DataFrame local para idx={idx}")
                                        st.session_state.df_contactos.at[idx, 'estado'] = webrtc_final_status  # Mantener Llamado/No Contesto/Gestionada
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
                                        
                                        # --- PASO 3: ACTUALIZACIÓN SEGURA DE SHEET LLAMADAS (solo fila específica) ---
                                        print(f"[DEBUG] WebRTC - Actualizando estado en Sheet Llamadas")
                                        if URL_SHEET_CONTACTOS:
                                            try:
                                                st.write("🔄 Actualizando estado en Sheet Llamadas...")
                                                
                                                # 📋 MOSTRAR INFORMACIÓN CLARA DE QUÉ SHEETS SE ACTUALIZARÁN
                                                agent_sheet_url = get_agent_sheet_url(st.session_state.agente_id)
                                                st.info(f"📊 **ACTUALIZANDO SHEETS (WebRTC):**")
                                                st.write(f"• 📋 **Sheet Compartido:** {URL_SHEET_CONTACTOS[:50]}...")
                                                if agent_sheet_url != URL_SHEET_CONTACTOS:
                                                    st.write(f"• 👤 **Sheet Individual Agente {st.session_state.agente_id}:** {agent_sheet_url[:50]}...")
                                                    st.write(f"✅ **Se actualizarán AMBOS sheets**")
                                                else:
                                                    st.write(f"⚠️ **Solo existe sheet compartido (sin sheet individual)**")
                                                
                                                # Usar actualización segura que busca por teléfono y actualiza ambos sheets
                                                if update_both_sheets_safe(st.session_state.df_contactos, st.session_state.agente_id, "WEBRTC_END", contact_idx=idx):
                                                    st.success("✅ **ESTADO ACTUALIZADO EN SHEETS (WebRTC)**")
                                                    
                                                    if agent_sheet_url != URL_SHEET_CONTACTOS:
                                                        # 🔥 VERIFICAR SI REALMENTE SE ACTUALIZARON AMBOS
                                                        st.success(f"📋 **Sheet Compartido**: Actualizado ✅")
                                                        st.info(f"👤 **Sheet Individual del Agente**: Verificar permisos")
                                                        st.warning(f"⚠️ Si el Sheet individual no se actualizó, compártelo con el service account")
                                                        add_log(f"WEBRTC_SHEETS_MIXED: {c['nombre']} - {webrtc_final_status} (COMPARTIDO OK, INDIVIDUAL PUEDE FALLAR)", "DATA")
                                                    else:
                                                        st.success(f"📋 **Sheet Compartido**: Actualizado ✅")
                                                        add_log(f"WEBRTC_SHARED_SHEET: {c['nombre']} - {webrtc_final_status} (SOLO COMPARTIDO)", "DATA")
                                                    
                                                    # 📊 MOSTRAR RESUMEN DE LA ACTUALIZACIÓN
                                                    st.markdown(f"""
                                                    <div style="background: #e3f2fd; padding: 15px; border-radius: 10px; margin: 10px 0;">
                                                        <h4 style="margin: 0 0 10px 0; color: #1976d2;">📝 **RESUMEN DE ACTUALIZACIÓN (WebRTC)</h4>
                                                        <div style="font-size: 0.9em;">
                                                            <strong>📞 Contacto:</strong> {c['nombre']} - {tel}<br>
                                                            <strong>🔄 Estado:</strong> {webrtc_final_status}<br>
                                                            <strong>📅 Fecha:</strong> {t_fin.strftime("%Y-%m-%d %H:%M:%S")}<br>
                                                            <strong>⏱️ Duración:</strong> {dur} segundos<br>
                                                            <strong>👤 Agente:</strong> {st.session_state.agente_id}<br>
                                                            <strong>📊 Sheets actualizados:</strong> {'Compartido + Individual' if agent_sheet_url != URL_SHEET_CONTACTOS else 'Solo Compartido'}
                                                        </div>
                                                    </div>
                                                    """, unsafe_allow_html=True)
                                                else:
                                                    st.error("❌ **ERROR ACTUALIZANDO SHEETS (WebRTC)**")
                                                    st.error("⚠️ **Los cambios podrían no haberse guardado correctamente**")
                                                    add_log(f"WEBRTC_SHEETS_ERROR: {c['nombre']} - {webrtc_final_status}", "ERROR")
                                            except Exception as e_llamadas:
                                                st.error(f"❌ **ERROR CRÍTICO EN SHEETS (WebRTC)**")
                                                st.error(f"📋 **Error:** {e_llamadas}")
                                                print(f"[ERROR] WebRTC Update Llamadas: {e_llamadas}")
                                                add_log(f"WEBRTC_CRITICAL_SHEET_ERROR: {e_llamadas}", "ERROR")
                                        
                                        add_log(f"WEBRTC_END: {st.session_state.webrtc_nombre} - {dur}s", "TWILIO")
                                        
                                        # --- PASO 4: LIMPIEZA DE ESTADO (SIEMPRE SE EJECUTA) ---
                                    print(f"[DEBUG] WebRTC - Limpiando estado de llamada - ESTE PASO SIEMPRE SE EJECUTA")
                                    
                                    # 🔥 LIMPIEZA CRÍTICA - SIEMPRE SE EJECUTA INDEPENDIENTEMENTE DE SHEETS
                                    st.session_state.webrtc_activo = False
                                    st.session_state.webrtc_numero = None
                                    st.session_state.webrtc_nombre = None
                                    st.session_state.webrtc_call_sid = None
                                    st.session_state.webrtc_idx = None
                                    st.session_state.grabacion_pausada = False
                                    
                                    # ✅ LIMPIAR COOKIE DE LLAMADA ACTIVA
                                    try:
                                        limpiar_cookie_llamada_activa()
                                        print(f"[DEBUG] WebRTC - Cookie de llamada activa limpiada")
                                    except Exception as e_cookie:
                                        print(f"[ERROR] WebRTC - Error limpiando cookie: {e_cookie}")
                                    
                                    print(f"[DEBUG] WebRTC - Estado de llamada limpiado completamente")
                                    print(f"[DEBUG] - webrtc_activo: {st.session_state.webrtc_activo}")
                                    print(f"[DEBUG] - webrtc_numero: {st.session_state.webrtc_numero}")
                                    print(f"[DEBUG] - webrtc_nombre: {st.session_state.webrtc_nombre}")
                                    
                                    st.success("✅ Llamada WebRTC finalizada - Pasando al siguiente contacto...")
                                    time.sleep(2)
                                    st.rerun()
                                else:
                                    # Refresh inteligente que respeta la interacción del usuario
                                    refresh_inteligente_llamada()

                                # Monitor para Conference Call Y si este es el contacto activo
                            if st.session_state.llamada_activa_sid is not None and not st.session_state.webrtc_activo and st.session_state.get('conference_idx') == idx:
                                try:
                                    print(f"[DEBUG] Iniciando monitoreo de llamada Conference...")
                                    
                                    # 🎥 CONTADOR DE TIEMPO VISUAL GRANDE
                                    tiempo_transcurrido = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                                    minutos = tiempo_transcurrido // 60
                                    segundos = tiempo_transcurrido % 60
                                    
                                    # Mostrar contador grande y visible
                                    st.markdown(f"""
                                    <div style="background: linear-gradient(135deg, #4CAF50, #45a049); color: white; padding: 20px; border-radius: 15px; text-align: center; margin-bottom: 20px;">
                                        <h2 style="margin: 0; font-size: 2em;">⏱️ {minutos:02d}:{segundos:02d}</h2>
                                        <p style="margin: 5px 0 0 0; font-size: 1.2em;">📞 LLAMADA EN CURSO</p>
                                    </div>
                                    """, unsafe_allow_html=True)
                                    
                                    # 1. Consultar estado real en Twilio
                                    print(f"[DEBUG] Consultando estado de llamada: {st.session_state.llamada_activa_sid}")
                                    remote = client.calls(st.session_state.llamada_activa_sid).fetch()
                                    print(f"[DEBUG] Estado Twilio obtenido: {remote.status}")
                                    st.info(f"📊 Estado Twilio: {remote.status}")
                                    
                                    # 2. Definir condiciones de terminación
                                    call_ended_by_system = remote.status in ['completed', 'no-answer', 'busy', 'failed', 'canceled']
                                    print(f"[DEBUG] call_ended_by_system = {call_ended_by_system}")
                                    
                                    # ✅ DETECCIÓN MEJORADA: Si el agente colgó desde celular/tablet
                                    if call_ended_by_system:
                                        st.warning(f"📞 La llamada fue terminada remotamente (agente colgó desde celular/tablet)")
                                        print(f"[DEBUG] Llamada terminada remotamente por agente")
                                    
                                    # 3. Detectar casos especiales y colgar automáticamente
                                    answered_by = str(remote.answered_by) if hasattr(remote, 'answered_by') and remote.answered_by else 'unknown'
                                    es_maquina = answered_by in ['machine_start', 'fax']
                                    
                                    # PRIORIDAD MEDIA 3: Timeout de conferencia INTELIGENTE (>60s con 1 solo participante o sin respuesta)
                                    if not call_ended_by_system and tiempo_transcurrido > 60 and remote.status in ['in-progress', 'ringing']:
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
                                    
                                    # 🔥 TIMEOUT ESPECÍFICO PARA NO CONTESTADOS (>20s)
                                    elif not call_ended_by_system and tiempo_transcurrido > 20 and remote.status == 'ringing':
                                        st.warning(f"⏰ Tiempo de espera agotado ({tiempo_transcurrido}s) - Cliente no contestó")
                                        st.info("📞 Finalizando llamada como 'No Contesto'")
                                        try:
                                            client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                                            call_ended_by_system = True
                                            time.sleep(2)
                                            st.rerun()
                                        except Exception as e:
                                            print(f"[ERROR] Error finalizando por no contestado: {e}")
                                    
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
                                    
                                    # ✅ MOSTRAR BOTONES SIEMPRE DURANTE LLAMADA ACTIVA
                                    if not call_ended_by_system:
                                        # 🎛️ PANEL DE CONTROL DE LLAMADA
                                        st.markdown("""
                                        <div style="background: #f8f9fa; padding: 15px; border-radius: 10px; border: 2px solid #dee2e6; margin-bottom: 15px;">
                                            <h4 style="margin: 0 0 10px 0; color: #495057;">🎛️ Control de Llamada Activa</h4>
                                        </div>
                                        """, unsafe_allow_html=True)
                                        
                                        # Mostrar botones en columnas
                                        btn_col1, btn_col2 = st.columns(2)
                                        with btn_col1:
                                            finalizar_manual = st.button("🔴 FINALIZAR GESTIÓN", type="primary", use_container_width=True)
                                        with btn_col2:
                                            if not st.session_state.grabacion_pausada:
                                                pausar_grabacion = st.button("⏸️ PAUSAR GRABACIÓN", use_container_width=True)
                                            else:
                                                st.info("⏸️ Grabación pausada")
                                        
                                        # 📝 Área de notas durante la llamada
                                        st.markdown("### 📝 Notas durante la llamada")
                                        nota_llamada = st.text_area("Añadir notas:", value=nota, key=f"nota_llamada_{idx}", height=100)
                                        
                                        # Botón de guardar notas
                                        if st.button("💾 Guardar Notas", key=f"guardar_notas_llamada_{idx}", use_container_width=True):
                                            # Actualizar nota en el DataFrame
                                            st.session_state.df_contactos.at[idx, 'observacion'] = nota_llamada
                                            st.success("✅ Notas guardadas durante la llamada")
                                            time.sleep(1)
                                            st.rerun()
                                    else:
                                        st.warning("📞 La llamada ha terminado - Procesando finalización...")
                                    
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
                                                
                                                # Usar refresh inteligente para pausar grabación
                                                refresh_inteligente_llamada(forzar=True)
                                        except Exception as e:
                                            st.error(f"❌ Error pausando grabación: {e}")
                                    elif call_ended_by_system:
                                        st.warning(f"📞 Llamada terminada automáticamente: {remote.status}")
                                    
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
                                        
                                        # Si es finalización manual, colgar la llamada directamente
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
                                            final_status = 'Gestionada'
                                            print(f"[DEBUG] Conference - Finalización manual por agente - Clasificado como Gestionada")
                                        # PRIORIDAD ALTA 1.5: Si el agente colgó desde celular/tablet (completed con duración significativa)
                                        elif remote.status == 'completed' and duracion_twilio >= 10:
                                            final_status = 'Gestionada'
                                            print(f"[DEBUG] Conference - Agente colgó desde celular/tablet - Clasificado como Gestionada")
                                            st.info(f"✅ Llamada gestionada por agente ({duracion_twilio}s)")
                                        # PRIORIDAD ALTA 2: Número inválido/inexistente (códigos ampliados)
                                        elif remote.status == 'failed' and error_code in ['21217', '21214', '21211', '21612', '30001', '30003']:
                                            final_status = 'No Contesto'
                                            st.error(f"❌ Número inválido o inexistente (error {error_code})")
                                            print(f"[DEBUG] Conference - Clasificado como No Contesto - Número inválido: {error_code}")
                                        # PRIORIDAD MEDIA 1: Número bloqueado/spam/no entregado
                                        elif remote.status == 'failed' and error_code in ['21610', '30006', '30004']:
                                            final_status = 'No Contesto'
                                            st.error(f"🚫 Número bloqueado, spam o mensaje no entregado (error {error_code})")
                                            print(f"[DEBUG] Conference - Clasificado como No Contesto - Número bloqueado/no entregado: {error_code}")
                                        # PRIORIDAD MEDIA 2: Error de red
                                        elif remote.status == 'failed' and error_code in ['31005', '31002', '31003', '31009']:
                                            final_status = 'No Contesto'
                                            st.warning(f"⚠️ Error de red - Considerar reintento (error {error_code})")
                                            print(f"[DEBUG] Conference - Clasificado como No Contesto - Error de red: {error_code}")
                                        # Estados intermedios - Llamada en progreso
                                        elif remote.status in ['in-progress', 'queued', 'ringing']:
                                            final_status = 'Llamado'  # Asumimos que está en progreso
                                            st.info(f"📞 Llamada en progreso: {remote.status}")
                                            print(f"[DEBUG] Conference - Clasificado como Llamado - Estado intermedio: {remote.status}")
                                        
                                        # Caso 1: No contestó, ocupado, cancelado
                                        elif remote.status in ['no-answer', 'busy', 'canceled']:
                                            final_status = 'No Contesto'
                                            print(f"[DEBUG] Conference - No contestó: {remote.status}")
                                        # Caso 2: Fallo genérico
                                        elif remote.status == 'failed':
                                            final_status = 'No Contesto'
                                            print(f"[DEBUG] Conference - Fallo genérico: {error_code}")
                                        # PRIORIDAD ALTA 3: Buzón de voz mejorado (detección ampliada)
                                        elif answered_by in ['machine_start', 'machine_end_beep', 'machine_end_silence', 'fax']:
                                            if duracion_twilio < 5:
                                                final_status = 'No Contesto'
                                                st.warning(f"📞 Buzón lleno o no dejó mensaje ({duracion_twilio}s) - Tipo: {answered_by}")
                                                print(f"[DEBUG] Conference - Buzón lleno - Tipo: {answered_by}")
                                            else:
                                                final_status = 'No Contesto'
                                                st.warning(f"📞 Contestó buzón de voz ({duracion_twilio}s) - Tipo: {answered_by}")
                                                print(f"[DEBUG] Conference - Buzón de voz - Tipo: {answered_by}")
                                        
                                        # Caso 3: Contestó persona - Validación de duración
                                        elif answered_by == 'human':
                                            if duracion_twilio >= 300:  # 5 minutos o más
                                                final_status = 'Gestionada'  # Conversación larga = gestionada
                                                st.info(f"📞 Conversación larga detectada ({duracion_twilio}s = {duracion_twilio//60}min {duracion_twilio%60}s)")
                                                print(f"[DEBUG] Conference - Conversación larga gestionada: {duracion_twilio}s")
                                            elif duracion_twilio >= 30:  # 30 segundos o más = conversación real
                                                final_status = 'Gestionada'  # Conversación real = gestionada
                                                st.success(f"✅ Conversación establecida ({duracion_twilio}s)")
                                                print(f"[DEBUG] Conference - Conversación real gestionada: {duracion_twilio}s")
                                            else:
                                                final_status = 'Llamado'  # Conversación muy corta
                                                st.success(f"✅ Llamada contestada por persona ({duracion_twilio}s)")
                                                print(f"[DEBUG] Conference - Detectado como humano - Duración: {duracion_twilio}s")
                                        
                                        # PRIORIDAD ALTA 2: Cliente colgó inmediatamente vs No contestó (casos especiales de duración)
                                        elif remote.status == 'completed' and answered_by == 'unknown':
                                            if duracion_twilio == 0:
                                                final_status = 'No Contesto'
                                                st.warning(f"⚠️ Llamada sin conexión (0s)")
                                                print(f"[DEBUG] Conference - Sin conexión")
                                            elif 0 < duracion_twilio < 3:
                                                final_status = 'No Contesto'
                                                st.warning(f"⚠️ Cliente rechazó la llamada ({duracion_twilio}s)")
                                                print(f"[DEBUG] Conference - Rechazó inmediatamente: {duracion_twilio}s")
                                            elif 3 <= duracion_twilio < 10:
                                                final_status = 'No Contesto'
                                                st.warning(f"⚠️ Llamada muy corta ({duracion_twilio}s) - Probablemente no contestó")
                                                print(f"[DEBUG] Conference - Duración muy corta: {duracion_twilio}s")
                                            elif duracion_twilio == 10:
                                                final_status = 'Llamado'  # Exactamente 10s = muy corta
                                                st.info(f"⚖️ Llamada en límite exacto (10s) - Clasificada como Llamado")
                                                print(f"[DEBUG] Conference - Duración límite exacto: 10s")
                                            elif duracion_twilio >= 300:  # 5 minutos o más
                                                final_status = 'Gestionada'  # Conversación larga = gestionada
                                                st.success(f"✅ Conversación larga gestionada ({duracion_twilio}s = {duracion_twilio//60}min {duracion_twilio%60}s)")
                                                print(f"[DEBUG] Conference - Conversación larga gestionada: {duracion_twilio}s")
                                            elif duracion_twilio >= 30:  # 30 segundos o más
                                                final_status = 'Gestionada'  # Conversación real = gestionada
                                                st.success(f"✅ Conversación gestionada ({duracion_twilio}s)")
                                                print(f"[DEBUG] Conference - Conversación gestionada: {duracion_twilio}s")
                                            else:
                                                final_status = 'Llamado'  # 11-29 segundos = corta
                                                st.success(f"✅ Llamada completada ({duracion_twilio}s) - Conversación corta")
                                                print(f"[DEBUG] Conference - Conversación corta: {duracion_twilio}s")
                                        
                                        # Caso por defecto
                                        else:
                                            final_status = 'Llamado'
                                            print(f"[DEBUG] Conference - Clasificado como Llamado por defecto")
                                        
                                        print(f"[DEBUG] Estado final determinado: {final_status}")
                                        
                                        # 📊 MENSAJE CLARO PARA EL AGENTE
                                        if final_status == 'Gestionada':
                                            st.success(f"✅ CONTACTO GESTIONADO - Cambiará a la sección 'Gestionadas'")
                                            if st.session_state.get('finalizacion_manual_agente', False):
                                                st.info("🔹 Finalizado por: Botón 'FINALIZAR GESTIÓN'")
                                            elif remote.status == 'completed' and duracion_twilio >= 10:
                                                st.info("🔹 Finalizado por: Agente colgó desde celular/tablet")
                                            elif answered_by == 'human' and duracion_twilio >= 30:
                                                st.info("🔹 Finalizado por: Conversación real establecida")
                                        elif final_status == 'Llamado':
                                            st.warning("⚠️ CONTACTO LLAMADO - Permanecerá en 'Pendientes' (conversación corta)")
                                        elif final_status == 'No Contesto':
                                            st.warning("⚠️ NO CONTESTÓ - Permanecerá en 'Pendientes'")
                                        
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
                                        
                                        # --- PASO 3: ACTUALIZACIÓN SEGURA DE SHEET LLAMADAS (solo fila específica) ---
                                        print(f"[DEBUG] Conference - Actualizando estado en Sheet Llamadas")
                                        if URL_SHEET_CONTACTOS:
                                            try:
                                                st.write("🔄 Actualizando estado en Sheet Llamadas...")
                                                
                                                # 📋 MOSTRAR INFORMACIÓN CLARA DE QUÉ SHEETS SE ACTUALIZARÁN
                                                agent_sheet_url = get_agent_sheet_url(st.session_state.agente_id)
                                                st.info(f"📊 **ACTUALIZANDO SHEETS:**")
                                                st.write(f"• 📋 **Sheet Compartido:** {URL_SHEET_CONTACTOS[:50]}...")
                                                if agent_sheet_url != URL_SHEET_CONTACTOS:
                                                    st.write(f"• 👤 **Sheet Individual Agente {st.session_state.agente_id}:** {agent_sheet_url[:50]}...")
                                                    st.write(f"✅ **Se actualizarán AMBOS sheets**")
                                                else:
                                                    st.write(f"⚠️ **Solo existe sheet compartido (sin sheet individual)**")
                                                
                                                # Usar actualización segura que busca por teléfono y actualiza ambos sheets
                                                if update_both_sheets_safe(st.session_state.df_contactos, st.session_state.agente_id, "CONFERENCE_END", contact_idx=idx):
                                                    st.success("✅ **ESTADO ACTUALIZADO EN SHEETS**")
                                                    
                                                    if agent_sheet_url != URL_SHEET_CONTACTOS:
                                                        # 🔥 VERIFICAR SI REALMENTE SE ACTUALIZARON AMBOS
                                                        # (el sistema ahora maneja errores de permisos gracefulmente)
                                                        st.success(f"📋 **Sheet Compartido**: Actualizado ✅")
                                                        st.info(f"👤 **Sheet Individual del Agente**: Verificar permisos")
                                                        st.warning(f"⚠️ Si el Sheet individual no se actualizó, compártelo con el service account")
                                                        add_log(f"UPDATE_SHEETS_MIXED: {c['nombre']} - {final_status} (COMPARTIDO OK, INDIVIDUAL PUEDE FALLAR)", "DATA")
                                                    else:
                                                        st.success(f"📋 **Sheet Compartido**: Actualizado ✅")
                                                        add_log(f"UPDATE_SHARED_SHEET: {c['nombre']} - {final_status} (SOLO COMPARTIDO)", "DATA")
                                                    
                                                    # 📊 MOSTRAR RESUMEN DE LA ACTUALIZACIÓN
                                                    st.markdown(f"""
                                                    <div style="background: #e8f5e8; padding: 15px; border-radius: 10px; margin: 10px 0;">
                                                        <h4 style="margin: 0 0 10px 0; color: #2e7d32;">📝 **RESUMEN DE ACTUALIZACIÓN</h4>
                                                        <div style="font-size: 0.9em;">
                                                            <strong>📞 Contacto:</strong> {c['nombre']} - {tel}<br>
                                                            <strong>🔄 Estado:</strong> {final_status}<br>
                                                            <strong>📅 Fecha:</strong> {t_fin.strftime("%Y-%m-%d %H:%M:%S")}<br>
                                                            <strong>⏱️ Duración:</strong> {dur} segundos<br>
                                                            <strong>👤 Agente:</strong> {st.session_state.agente_id}<br>
                                                            <strong>📊 Sheets actualizados:</strong> {'Compartido + Individual' if agent_sheet_url != URL_SHEET_CONTACTOS else 'Solo Compartido'}
                                                        </div>
                                                    </div>
                                                    """, unsafe_allow_html=True)
                                                else:
                                                    st.error("❌ **ERROR ACTUALIZANDO SHEETS**")
                                                    st.error("⚠️ **Los cambios podrían no haberse guardado correctamente**")
                                                    add_log(f"UPDATE_SHEETS_ERROR: {c['nombre']} - {final_status}", "ERROR")
                                            except Exception as e_llamadas:
                                                st.error(f"❌ **ERROR CRÍTICO EN SHEETS**")
                                                st.error(f"📋 **Error:** {e_llamadas}")
                                                print(f"[ERROR] Conference Update Llamadas: {e_llamadas}")
                                                add_log(f"CRITICAL_SHEET_ERROR: {e_llamadas}", "ERROR")
                                        
                                        # --- PASO 4: LIMPIEZA DE ESTADO (SIEMPRE SE EJECUTA) ---
                                    print(f"[DEBUG] Limpiando estado de llamada - ESTE PASO SIEMPRE SE EJECUTA")
                                    st.write("✅ Gestión completada - Pasando al siguiente contacto...")
                                    
                                    # 🔥 LIMPIEZA CRÍTICA - SIEMPRE SE EJECUTA INDEPENDIENTEMENTE DE SHEETS
                                    st.session_state.llamada_activa_sid = None
                                    st.session_state.conference_name = None
                                    st.session_state.conference_idx = None
                                    st.session_state.grabacion_pausada = False
                                    st.session_state.finalizacion_manual_agente = False  # Limpiar variable
                                    
                                    # ✅ LIMPIAR COOKIE DE LLAMADA ACTIVA
                                    try:
                                        limpiar_cookie_llamada_activa()
                                        print(f"[DEBUG] Cookie de llamada activa limpiada")
                                    except Exception as e_cookie:
                                        print(f"[ERROR] Error limpiando cookie: {e_cookie}")
                                    
                                    print(f"[DEBUG] Estado de llamada limpiado completamente")
                                    print(f"[DEBUG] - llamada_activa_sid: {st.session_state.llamada_activa_sid}")
                                    print(f"[DEBUG] - conference_name: {st.session_state.conference_name}")
                                    print(f"[DEBUG] - conference_idx: {st.session_state.conference_idx}")
                                    
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
                            # ✅ MOVER AQUÍ PARA QUE ESTÉ DISPONIBLE DURANTE LLAMADA ACTIVA
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
                                if st.button("💾 Guardar Notas", key=f"save_notes_{idx}", width='stretch'):
                                    # Obtener nota existente
                                    nota_existente = str(st.session_state.df_contactos.at[idx, 'observacion']) if pd.notna(st.session_state.df_contactos.at[idx, 'observacion']) else ''
                                    
                                    # Combinar notas si ya existe algo
                                    if nota_existente and nota_existente.strip():
                                        if nota.strip() and nota != nota_existente:
                                            # Acumular notas con timestamp y contexto de categoría
                                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                                            categoria_actual = st.session_state.df_contactos.at[idx, 'estado'] if 'estado' in st.session_state.df_contactos.columns else 'Sin categoría'
                                            nota_acumulada = f"{nota_existente} | [{timestamp}] ({categoria_actual}) {nota}"
                                        else:
                                            nota_acumulada = nota_existente  # Mantener existente si la nueva está vacía o es igual
                                    else:
                                        # Agregar timestamp y categoría a la primera nota
                                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                                        categoria_actual = st.session_state.df_contactos.at[idx, 'estado'] if 'estado' in st.session_state.df_contactos.columns else 'Sin categoría'
                                        nota_acumulada = f"[{timestamp}] ({categoria_actual}) {nota}"  # Primera nota con timestamp y categoría
                                    
                                    # Actualizar DataFrame local con notas acumuladas
                                    st.session_state.df_contactos.at[idx, 'observacion'] = nota_acumulada
                                    
                                    # Actualizar tanto Sheet compartido como Sheet del agente
                                    if URL_SHEET_CONTACTOS:
                                        try:
                                            if update_both_sheets_safe(st.session_state.df_contactos, st.session_state.agente_id, "NOTAS_ACUMULADAS", contact_idx=idx):
                                                add_log(f"NOTAS_ACUMULADAS: {c['nombre']}", "ACCION")
                                                st.success("✅ Notas acumuladas en ambos sheets (compartido y agente)")
                                            else:
                                                st.warning("⚠️ Notas acumuladas localmente, pero error actualizando sheets")
                                        except Exception as e:
                                            st.error(f"❌ Error acumulando notas: {e}")
                                    else:
                                        st.success("✅ Notas acumuladas localmente")
                                    
                                    time.sleep(1)
                                    st.rerun()
                            
                            with col_btn2:
                                if st.button("✅ Programar", key=f"prog_{idx}", width='stretch'):
                                    # Combinar fecha y hora
                                    fecha_hora_prog = datetime.combine(fecha_prog, hora_prog)
                                    
                                    # Obtener nota actual (que ya incluye notas acumuladas si se guardaron)
                                    nota_actual = st.session_state.df_contactos.at[idx, 'observacion']
                                    
                                    # Actualizar DataFrame local
                                    st.session_state.df_contactos.at[idx, 'estado'] = 'Programada'
                                    st.session_state.df_contactos.at[idx, 'proxima_llamada'] = fecha_hora_prog.strftime("%Y-%m-%d %H:%M:%S")
                                    st.session_state.df_contactos.at[idx, 'observacion'] = nota_actual  # Mantener notas acumuladas
                                    st.session_state.df_contactos.at[idx, 'agente_id'] = st.session_state.agente_id
                                    
                                    # Actualizar tanto Sheet compartido como Sheet del agente
                                    if URL_SHEET_CONTACTOS:
                                        try:
                                            if update_both_sheets_safe(st.session_state.df_contactos, st.session_state.agente_id, "PROGRAMADA", contact_idx=idx):
                                                add_log(f"PROGRAMADA: {c['nombre']} para {fecha_hora_prog.strftime('%Y-%m-%d %H:%M')}", "ACCION")
                                                st.success(f"✅ Llamada programada para {fecha_hora_prog.strftime('%Y-%m-%d %H:%M')} en ambos sheets")
                                                # 🔥 REDIRECCIÓN AUTOMÁTICA A "PROGRAMADAS"
                                                st.session_state.pestana_actual = "Programadas"
                                                # Usar refresh inteligente para programación
                                                refresh_inteligente_llamada(forzar=True)
                                            else:
                                                st.warning("⚠️ Programada localmente, pero error actualizando sheets")
                                        except Exception as e:
                                            st.error(f"❌ Error actualizando sheets: {e}")
                                            print(f"[ERROR] Programar llamada - Update Sheet: {e}")
                                    else:
                                        st.success(f"✅ Llamada programada para {fecha_hora_prog.strftime('%Y-%m-%d %H:%M')}")
                                        # 🔥 REDIRECCIÓN AUTOMÁTICA A "PROGRAMADAS" (incluso sin Sheet)
                                        st.session_state.pestana_actual = "Programadas"
                                        # Usar refresh inteligente para programación
                                        refresh_inteligente_llamada(forzar=True)
    else:
        # 🔥 CORRECCIÓN: Solo mostrar mensaje cuando realmente no hay contactos en la categoría
        # Verificar si realmente no hay contactos en esta categoría (no por paginación)
        if "Pendientes" in opc:
            total_en_categoria = len(df[(df['estado'] == 'Pendiente') | (df['estado'].isna()) | (df['estado'] == '')]) if not df.empty else 0
        elif "Gestionadas" in opc:
            total_en_categoria = len(df[df['estado'].isin(['Llamado', 'Gestionado'])]) if not df.empty else 0
        else:
            total_en_categoria = len(df[df['estado'] == f_est]) if not df.empty else 0
        
        # Solo mostrar mensaje si realmente no hay contactos en la categoría
        if total_en_categoria == 0:
            st.success(f"¡Felicidades! No hay más clientes en la categoría: {opc}")
        # Si hay contactos pero df_work está vacío, no mostrar nada (puede ser por paginación/filtros)
