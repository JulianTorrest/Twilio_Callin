import streamlit as st
import pandas as pd
from twilio.rest import Client
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection
import time
import urllib.parse

# --- CONFIGURACION DE PAGINA ---
st.set_page_config(page_title="Camacol Dialer Pro v3", layout="wide")

# --- ESTILOS CSS ---
st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 10px; border-radius: 10px; border: 1px solid #e1e4e8; }
    .client-card { background-color: #f0f2f6; padding: 15px; border-radius: 15px; border-left: 8px solid #003366; }
    .log-box { font-family: monospace; font-size: 0.8rem; background: #1e1e1e; color: #4af626; padding: 10px; border-radius: 5px; height: 180px; overflow-y: auto; }
    .latency-green { height: 10px; width: 10px; background-color: #28a745; border-radius: 50%; display: inline-block; }
    .latency-red { height: 10px; width: 10px; background-color: #dc3545; border-radius: 50%; display: inline-block; }
    .pause-status { color: #ff8c00; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. CONEXIONES ---
try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets.get("TWILIO_NUMBER", "+17068069672")
    function_url = st.secrets["TWILIO_FUNCTION_URL"]
    forms_base_url = st.secrets.get("MS_FORMS_URL")
    URL_SHEET_INFORME = st.secrets.get("GSHEET_URL")
    client = Client(account_sid, auth_token)
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"Error de configuración: {e}")
    st.stop()

# --- 2. GESTION DE LOGS Y AUDITORIA ---
if 'logs' not in st.session_state:
    st.session_state.logs = []
    st.session_state.session_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def add_log(mensaje, tipo="INFO"):
    t_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{t_stamp} | {st.session_state.get('agente_id', 'SYS')} | {tipo} | {mensaje}"
    st.session_state.logs.append(entry)
    # Mantener historial pequeño en pantalla pero completo para exportar
    if len(st.session_state.logs) > 500: st.session_state.logs.pop(0)

def sync_logs_to_drive():
    """Sincroniza los logs con una pestaña de auditoría en el sheet"""
    if URL_SHEET_INFORME and st.session_state.logs:
        try:
            df_logs = pd.DataFrame([l.split(" | ") for l in st.session_state.logs], 
                                   columns=['Fecha', 'Agente', 'Tipo', 'Evento'])
            conn.update(spreadsheet=URL_SHEET_INFORME, worksheet="Auditoria_Logs", data=df_logs)
        except: pass

# --- 3. GESTION DE ESTADO (PERSISTENCIA Y PAUSAS) ---
if 'agente_id' not in st.session_state:
    st.session_state.agente_id = None
if 'en_pausa' not in st.session_state: st.session_state.en_pausa = False
if 'pausa_inicio' not in st.session_state: st.session_state.pausa_inicio = None
if 'llamada_activa_sid' not in st.session_state: st.session_state.llamada_activa_sid = None
if 'df_contactos' not in st.session_state: st.session_state.df_contactos = None
if 'draft_notas' not in st.session_state: st.session_state.draft_notas = {}

# --- 4. ACCESO ---
if not st.session_state.agente_id:
    st.title("Acceso Camacol Dialer")
    with st.form("login"):
        cedula = st.text_input("Ingrese Cédula:", type="password").strip()
        if st.form_submit_button("Ingresar"):
            if cedula in ["1121871773", "87654321", "12345678"]:
                st.session_state.agente_id = cedula
                add_log("INICIO_SESION", "LOGIN")
                st.rerun()
            else: st.error("Cédula no autorizada")
    st.stop()

# --- 5. INDICADOR DE LATENCIA (Twilio API Check) ---
def check_twilio():
    try:
        client.calls.list(limit=1)
        return True
    except: return False

# --- 6. SIDEBAR: METRICAS Y PAUSAS ---
with st.sidebar:
    st.title(f"Agente: {st.session_state.agente_id}")
    
    # Indicador de Latencia
    is_online = check_twilio()
    st.markdown(f"{'<span class=latency-green></span>' if is_online else '<span class=latency-red></span>'} API Status: {'Online' if is_online else 'Offline'}", unsafe_allow_html=True)
    
    # Sistema de Pausas
    st.divider()
    if not st.session_state.en_pausa:
        if st.button("🔴 Iniciar Pausa / Break", use_container_width=True):
            st.session_state.en_pausa = True
            st.session_state.pausa_inicio = datetime.now()
            add_log("INICIO_PAUSA", "ESTADO")
            st.rerun()
    else:
        duracion_pausa = int((datetime.now() - st.session_state.pausa_inicio).total_seconds() / 60)
        st.markdown(f"<p class='pause-status'>EN PAUSA ({duracion_pausa} min)</p>", unsafe_allow_html=True)
        if st.button("🟢 Finalizar Pausa", use_container_width=True):
            st.session_state.en_pausa = False
            add_log(f"FIN_PAUSA (Duracion: {duracion_pausa}m)", "ESTADO")
            st.rerun()

    st.divider()
    # Carga de Base
    up_file = st.file_uploader("Cargar Base (CSV)", type="csv")
    if up_file and st.session_state.df_contactos is None:
        df = pd.read_csv(up_file, sep=None, engine='python', encoding='utf-8-sig')
        df.columns = [str(c).strip().lower() for c in df.columns]
        for col in ['estado', 'observacion', 'fecha_llamada', 'duracion_seg', 'sid_llamada', 'proxima_llamada']:
            if col not in df.columns: df[col] = 'Pendiente' if col == 'estado' else ''
        st.session_state.df_contactos = df
        add_log("BASE_CARGADA", "DATA")

    if st.button("Cerrar Sesión"):
        add_log("CIERRE_SESION", "LOGOUT")
        sync_logs_to_drive()
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()

# --- 7. MODULO SUPERVISOR (Solo 12345678) ---
if st.session_state.agente_id == "12345678":
    with st.expander("PANEL DE SUPERVISIÓN (EXCLUSIVO)"):
        st.subheader("Métricas Globales de Sesión")
        if st.session_state.df_contactos is not None:
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Base", len(st.session_state.df_contactos))
            col2.metric("Gestionados", len(st.session_state.df_contactos[st.session_state.df_contactos['estado'] != 'Pendiente']))
            col3.metric("Logs Generados", len(st.session_state.logs))
            st.dataframe(st.session_state.df_contactos.head(10))

# --- 8. CUERPO PRINCIPAL ---
if st.session_state.df_contactos is not None:
    # BUSCADOR DE CLIENTES
    search_query = st.text_input("Buscar cliente (Nombre o Teléfono):").lower()
    
    # Filtrado dinámico
    df_full = st.session_state.df_contactos
    if search_query:
        df_filtered = df_full[df_full['nombre'].str.lower().contains(search_query) | df_full['telefono'].astype(str).contains(search_query)]
    else:
        opc = st.radio("Lista:", ["Pendientes", "No Contestaron", "Programadas"], horizontal=True)
        f_est = "Pendiente" if "Pendientes" in opc else "No Contesto" if "No Contestaron" in opc else "Programada"
        df_filtered = df_full[df_full['estado'] == f_est]

    if not df_filtered.empty:
        idx = df_filtered.index[0]
        c = df_filtered.loc[idx]
        tel = f"+{str(c['codigo_pais']).replace('+', '')}{str(c['telefono'])}"

        # PANEL DE OPERACION
        st.divider()
        col_info, col_ctrl = st.columns([2, 1])

        with col_info:
            st.markdown(f"<div class='client-card'><h3>{c['nombre']}</h3><p>Teléfono: {tel}</p></div>", unsafe_allow_html=True)
            
            # AUTO-SAVE NOTAS: Se usa el session_state para persistencia
            prev_note = st.session_state.draft_notas.get(idx, c['observacion'])
            nota_input = st.text_area("Notas de gestión:", value=prev_note, key=f"note_{idx}")
            st.session_state.draft_notas[idx] = nota_input # Guardado en borrador

            # AGENDAMIENTO
            exp_c = st.expander("Programar Re-llamada")
            with exp_c:
                c_date = st.date_input("Fecha:", min_value=datetime.now())
                c_time = st.time_input("Hora:")

        with col_ctrl:
            if not st.session_state.en_pausa:
                if st.session_state.llamada_activa_sid is None:
                    if st.button("INICIAR LLAMADA", type="primary", use_container_width=True):
                        try:
                            call = client.calls.create(url=function_url, to=tel, from_=twilio_number, machine_detection='Enable')
                            st.session_state.llamada_activa_sid = call.sid
                            st.session_state.t_inicio_dt = datetime.now()
                            add_log(f"CALL_START: {c['nombre']}", "TWILIO")
                            st.rerun()
                        except Exception as e: st.error(f"Error: {e}")
                else:
                    # FEEDBACK LLAMADA
                    try:
                        remote = client.calls(st.session_state.llamada_activa_sid).fetch()
                        st.markdown(f"<h1 style='color:red; text-align:center;'>{remote.status.upper()}</h1>", unsafe_allow_html=True)
                    except: pass
                    
                    if st.button("FINALIZAR GESTION", type="secondary", use_container_width=True):
                        try: client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                        except: pass
                        
                        dur = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                        
                        # ACTUALIZAR DATAFRAME
                        st.session_state.df_contactos.at[idx, 'estado'] = 'Llamado'
                        st.session_state.df_contactos.at[idx, 'observacion'] = nota_input
                        st.session_state.df_contactos.at[idx, 'duracion_seg'] = dur
                        st.session_state.df_contactos.at[idx, 'fecha_llamada'] = datetime.now().strftime("%Y-%m-%d")
                        st.session_state.df_contactos.at[idx, 'sid_llamada'] = st.session_state.llamada_activa_sid
                        
                        # SINCRONIZACION DRIVE (ANTI-DUPLICADOS)
                        if URL_SHEET_INFORME:
                            try:
                                df_drive = conn.read(spreadsheet=URL_SHEET_INFORME, worksheet="0")
                                df_final = pd.concat([df_drive, st.session_state.df_contactos.loc[[idx]]], ignore_index=True)
                                df_final = df_final.drop_duplicates(subset=['sid_llamada'], keep='last')
                                conn.update(spreadsheet=URL_SHEET_INFORME, data=df_final)
                                add_log(f"SYNC_SUCCESS: {c['nombre']}", "DATA")
                                sync_logs_to_drive() # Guardar auditoría tras cada éxito
                            except Exception as e: add_log(f"SYNC_ERROR: {e}", "ERROR")

                        # WHATSAPP
                        msg_wa = urllib.parse.quote(f"Hola {c['nombre']}, intentamos contactarte de Camacol.")
                        st.link_button(" ENVIAR WHATSAPP", f"https://wa.me/{tel.replace('+', '')}?text={msg_wa}", use_container_width=True)
                        
                        st.session_state.llamada_activa_sid = None
                        st.rerun()
            else:
                st.warning("Debe finalizar la pausa para llamar.")

    # TAB DE LOGS
    st.divider()
    with st.expander(" Ver Log de Actividad (Auditoría en tiempo real)"):
        st.markdown(f"<div class='log-box'>{'<br>'.join(st.session_state.logs[::-1])}</div>", unsafe_allow_html=True)
else:
    st.info("Cargue un archivo para comenzar.")
