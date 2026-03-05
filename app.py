import streamlit as st
import pandas as pd
from twilio.rest import Client
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection
import time
import urllib.parse

# --- CONFIGURACION DE PAGINA Y DISEÑO ---
st.set_page_config(page_title="Camacol Dialer Pro v3.1", layout="wide")

st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 10px; border-radius: 10px; border: 1px solid #e1e4e8; }
    .client-card { background-color: #f0f2f6; padding: 15px; border-radius: 15px; border-left: 8px solid #003366; margin-bottom: 15px; }
    .log-box { font-family: monospace; font-size: 0.8rem; background: #1e1e1e; color: #4af626; padding: 10px; border-radius: 5px; height: 180px; overflow-y: auto; }
    .latency-green { height: 10px; width: 10px; background-color: #28a745; border-radius: 50%; display: inline-block; }
    .latency-red { height: 10px; width: 10px; background-color: #dc3545; border-radius: 50%; display: inline-block; }
    .pause-status { color: #ff8c00; font-weight: bold; font-size: 1.2rem; }
    .stButton>button { width: 100%; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. CONEXIONES Y CONFIGURACION ---
try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets.get("TWILIO_NUMBER", "+17068069672")
    function_url = st.secrets["TWILIO_FUNCTION_URL"]
    forms_base_url = st.secrets.get("MS_FORMS_URL", "https://forms.office.com/r/tu_codigo")
    URL_SHEET_INFORME = st.secrets.get("GSHEET_URL")
    CEDULAS_AUTORIZADAS = ["1121871773", "87654321", "12345678"]
    client = Client(account_sid, auth_token)
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"Error de configuración crítica: {e}")
    st.stop()

# --- 2. GESTION DE LOGS (Auditoría Detallada) ---
if 'logs' not in st.session_state:
    st.session_state.logs = []

def add_log(mensaje, tipo="INFO"):
    t_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{t_stamp} | {st.session_state.get('agente_id', 'SYS')} | {tipo} | {mensaje}"
    st.session_state.logs.append(entry)
    if len(st.session_state.logs) > 500: st.session_state.logs.pop(0)

def sync_logs_to_drive():
    """Guarda la auditoría en una pestaña nueva del Sheets automáticamente"""
    if URL_SHEET_INFORME and st.session_state.logs:
        try:
            df_logs = pd.DataFrame([l.split(" | ") for l in st.session_state.logs], 
                                   columns=['Fecha', 'Agente', 'Tipo', 'Evento'])
            conn.update(spreadsheet=URL_SHEET_INFORME, worksheet="Auditoria_Logs", data=df_logs)
        except: pass

# --- 3. GESTION DE ESTADO (Persistencia) ---
if 'agente_id' not in st.session_state: st.session_state.agente_id = None
if 'df_contactos' not in st.session_state: st.session_state.df_contactos = None
if 'llamada_activa_sid' not in st.session_state: st.session_state.llamada_activa_sid = None
if 'en_pausa' not in st.session_state: st.session_state.en_pausa = False
if 'pausa_inicio' not in st.session_state: st.session_state.pausa_inicio = None
if 'draft_notas' not in st.session_state: st.session_state.draft_notas = {}
if 'meta_diaria' not in st.session_state: st.session_state.meta_diaria = 50

# --- 4. CONTROL DE ACCESO ---
if not st.session_state.agente_id:
    st.markdown("<h1 style='text-align: center; color: #003366;'>Acceso Camacol</h1>", unsafe_allow_html=True)
    with st.form("login_form"):
        cedula_in = st.text_input("Número de Cédula:", type="password").strip()
        if st.form_submit_button("Ingresar al Portal"):
            if cedula_in in CEDULAS_AUTORIZADAS:
                st.session_state.agente_id = cedula_in
                add_log("EVENTO: Inicio de Sesión exitoso", "LOGIN")
                st.rerun()
            else: st.error("Cédula no autorizada.")
    st.stop()

# --- 5. SIDEBAR (Pausas, Carga y REPORTES RESTAURADOS) ---
with st.sidebar:
    st.header(f"Agente: {st.session_state.agente_id}")
    
    # Latencia Check
    try: 
        client.calls.list(limit=1)
        st.markdown("<span class='latency-green'></span> Twilio API: Online", unsafe_allow_html=True)
    except: 
        st.markdown("<span class='latency-red'></span> Twilio API: Offline", unsafe_allow_html=True)

    # SISTEMA DE PAUSAS
    st.divider()
    if not st.session_state.en_pausa:
        if st.button("☕ Iniciar Pausa / Almuerzo", type="secondary"):
            st.session_state.en_pausa = True
            st.session_state.pausa_inicio = datetime.now()
            add_log("EVENTO: Agente inicia pausa", "ESTADO")
            st.rerun()
    else:
        minutos = int((datetime.now() - st.session_state.pausa_inicio).total_seconds() / 60)
        st.markdown(f"<p class='pause-status'>EN PAUSA: {minutos} min</p>", unsafe_allow_html=True)
        if st.button("✅ Volver a Trabajar"):
            st.session_state.en_pausa = False
            add_log(f"EVENTO: Fin de pausa (Duración: {minutos}m)", "ESTADO")
            st.rerun()

    st.divider()
    up_file = st.file_uploader("Cargar Base (CSV)", type="csv")
    if up_file and st.session_state.df_contactos is None:
        df_up = pd.read_csv(up_file, sep=None, engine='python', encoding='utf-8-sig')
        df_up.columns = [str(c).strip().lower() for c in df_up.columns]
        for col in ['estado', 'observacion', 'fecha_llamada', 'duracion_seg', 'sid_llamada', 'proxima_llamada']:
            if col not in df_up.columns: df_up[col] = 'Pendiente' if col == 'estado' else ''
        st.session_state.df_contactos = df_up
        add_log("EVENTO: Base de datos cargada", "DATA")

    # --- REPORTES (RESTAURADOS) ---
    if st.session_state.df_contactos is not None:
        st.subheader("Descargar Reportes")
        df_full = st.session_state.df_contactos
        # Reporte Pendientes (RESTAURADO)
        df_pend = df_full[df_full['estado'].isin(['Pendiente', 'No Contesto', 'Programada'])]
        st.download_button("📥 Descargar Pendientes", df_pend.to_csv(index=False).encode('utf-8-sig'), "pendientes.csv", "text/csv")
        # Reporte Logs
        st.download_button("📥 Descargar Auditoría", "\n".join(st.session_state.logs), "auditoria.log", "text/plain")

    if st.button("Cerrar Sesión"):
        add_log("EVENTO: Cierre de sesión manual", "LOGOUT")
        sync_logs_to_drive()
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()

# --- 6. MODULO SUPERVISOR (Cédula 12345678) ---
if st.session_state.agente_id == "12345678":
    with st.expander("👤 PANEL DE SUPERVISOR"):
        st.write("Avance General de Gestión:")
        if st.session_state.df_contactos is not None:
            st.dataframe(st.session_state.df_contactos['estado'].value_counts())

# --- 7. CUERPO PRINCIPAL ---
st.markdown("<h2 style='color:#003366;'>Centro de Operaciones Camacol</h2>", unsafe_allow_html=True)

if st.session_state.df_contactos is not None:
    # BUSCADOR DE CLIENTES (NUEVA MEJORA)
    search = st.text_input("🔍 Buscar por Nombre o Teléfono:").lower()
    
    df = st.session_state.df_contactos
    
    # METRICAS
    c1, c2, c3, c4 = st.columns(4)
    llamados = len(df[df['estado'] == 'Llamado'])
    c1.metric("Pendientes", len(df[df['estado'] == 'Pendiente']))
    c2.metric("Logrados", llamados)
    c3.metric("No Contesto", len(df[df['estado'] == 'No Contesto']))
    c4.metric("Progreso", f"{llamados}/{st.session_state.meta_diaria}")

    tab_op, tab_log = st.tabs(["Llamadas", "Auditoría en Vivo"])

    with tab_log:
        st.markdown(f"<div class='log-box'>{'<br>'.join(st.session_state.logs[::-1])}</div>", unsafe_allow_html=True)

    with tab_op:
        if search:
            df_work = df[df['nombre'].str.lower().str.contains(search) | df['telefono'].astype(str).str.contains(search)]
        else:
            opc = st.radio("Lista:", ["Pendientes", "No Contestaron", "Programadas"], horizontal=True)
            f_est = "Pendiente" if "Pendientes" in opc else "No Contesto" if "No Contestaron" in opc else "Programada"
            df_work = df[df['estado'] == f_est]

        if not df_work.empty:
            idx = df_work.index[0]
            cliente = df_work.loc[idx]
            tel_cliente = f"+{str(cliente['codigo_pais']).replace('+', '')}{str(cliente['telefono'])}"

            col_inf, col_ctr = st.columns([2, 1])
            with col_inf:
                st.markdown(f"<div class='client-card'><h3>{cliente['nombre']}</h3><p>Tel: {tel_cliente}</p></div>", unsafe_allow_html=True)
                
                # PERSISTENCIA DE NOTAS (AUTO-SAVE)
                val_nota = st.session_state.draft_notas.get(idx, cliente['observacion'])
                nota_input = st.text_area("Notas de gestión:", value=val_nota, key=f"txt_{idx}")
                st.session_state.draft_notas[idx] = nota_input # Guardar borrador

                # AGENDAMIENTO
                exp = st.expander("📅 Programar rellamada")
                with exp:
                    d_rel = st.date_input("Fecha:", min_value=datetime.now())
                    t_rel = st.time_input("Hora:")

            with col_ctr:
                if not st.session_state.en_pausa:
                    if st.session_state.llamada_activa_sid is None:
                        if st.button("📞 INICIAR LLAMADA", type="primary"):
                            try:
                                call = client.calls.create(url=function_url, to=tel_cliente, from_=twilio_number, machine_detection='Enable', record=True)
                                st.session_state.llamada_activa_sid = call.sid
                                st.session_state.t_inicio_dt = datetime.now()
                                add_log(f"CALL: Iniciada llamada a {cliente['nombre']}", "TWILIO")
                                st.rerun()
                            except Exception as e: st.error(f"Error: {e}")
                    else:
                        # LLAMADA ACTIVA
                        try:
                            remote = client.calls(st.session_state.llamada_activa_sid).fetch()
                            st.markdown(f"<h2 style='color:red; text-align:center;'>{remote.status.upper()}</h2>", unsafe_allow_html=True)
                        except: pass
                        
                        st.link_button("📝 ABRIR FORMULARIO", f"{forms_base_url}?id={st.session_state.llamada_activa_sid}")

                        if st.button("✅ FINALIZAR GESTION", type="secondary"):
                            try: client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                            except: pass
                            
                            dur = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                            
                            # ACTUALIZAR DATOS
                            st.session_state.df_contactos.at[idx, 'estado'] = 'Llamado'
                            st.session_state.df_contactos.at[idx, 'observacion'] = nota_input
                            st.session_state.df_contactos.at[idx, 'duracion_seg'] = dur
                            st.session_state.df_contactos.at[idx, 'fecha_llamada'] = datetime.now().strftime("%Y-%m-%d")
                            st.session_state.df_contactos.at[idx, 'sid_llamada'] = st.session_state.llamada_activa_sid
                            
                            if d_rel: st.session_state.df_contactos.at[idx, 'proxima_llamada'] = f"{d_rel} {t_rel}"

                            # SINCRONIZACION INTELIGENTE (ANTI-DUPLICADOS)
                            if URL_SHEET_INFORME:
                                try:
                                    df_dr = conn.read(spreadsheet=URL_SHEET_INFORME, worksheet="0")
                                    df_fin = pd.concat([df_dr, st.session_state.df_contactos.loc[[idx]]], ignore_index=True)
                                    df_fin = df_fin.drop_duplicates(subset=['sid_llamada'], keep='last')
                                    conn.update(spreadsheet=URL_SHEET_INFORME, data=df_fin)
                                    add_log(f"SYNC: {cliente['nombre']} actualizado en Drive", "DATA")
                                    sync_logs_to_drive()
                                except: add_log("ERR: Falló sincronización Drive", "ERROR")

                            # WHATSAPP
                            wa_m = urllib.parse.quote(f"Hola {cliente['nombre']}, soy de Camacol. Intentamos contactarte.")
                            st.link_button("💬 WHATSAPP", f"https://wa.me/{tel_cliente.replace('+', '')}?text={wa_m}")
                            
                            st.session_state.llamada_activa_sid = None
                            st.rerun()
                else:
                    st.warning("⚠️ Finalice la pausa para poder llamar.")
        
        # PERSISTENCIA: Si la llamada está activa, refrescar cada 5 seg para ver estatus
        if st.session_state.llamada_activa_sid:
            time.sleep(5)
            st.rerun()
else:
    st.info("Cargue un archivo CSV para iniciar.")
