import streamlit as st
import pandas as pd
from twilio.rest import Client
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection
import time
import urllib.parse

# --- CONFIGURACION DE PAGINA ---
st.set_page_config(page_title="Camacol - Dialer Pro", layout="wide")

# --- ESTILOS PERSONALIZADOS (CSS) ---
st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; border: 1px solid #e1e4e8; }
    .client-card { background-color: #f0f2f6; padding: 20px; border-radius: 15px; border-left: 10px solid #003366; margin-bottom: 20px; }
    .main-header { color: #003366; text-align: center; border-bottom: 2px solid #003366; margin-bottom: 20px; }
    .status-active { color: #d9534f; font-weight: bold; text-align: center; }
    .log-box { font-family: monospace; font-size: 0.8em; background: #000; color: #0f0; padding: 10px; border-radius: 5px; height: 150px; overflow-y: scroll; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. CONFIGURACION DE CONEXIONES ---
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
    st.error(f"Error de configuracion: {e}")
    st.stop()

# --- 2. GESTION DE LOGS (Auditoria) ---
if 'logs' not in st.session_state:
    st.session_state.logs = []

def add_log(mensaje):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.logs.append(f"[{timestamp}] {mensaje}")

# --- 3. CONTROL DE ACCESO ---
if 'agente_id' not in st.session_state:
    st.markdown("<h1 class='main-header'>Acceso al Sistema Camacol</h1>", unsafe_allow_html=True)
    with st.form("login"):
        cedula_input = st.text_input("Ingrese su numero de cedula:", type="password").strip()
        if st.form_submit_button("Ingresar al Portal"):
            if cedula_input in [str(c).strip() for c in CEDULAS_AUTORIZADAS]:
                st.session_state.agente_id = cedula_input
                add_log(f"Agente {cedula_input} inicio sesion")
                st.rerun()
            else:
                st.error("Cedula no autorizada.")
    st.stop()

# --- 4. GESTION DE ESTADO ---
if 'df_contactos' not in st.session_state:
    st.session_state.df_contactos = None
if 'llamada_activa_sid' not in st.session_state:
    st.session_state.llamada_activa_sid = None
if 't_inicio_dt' not in st.session_state:
    st.session_state.t_inicio_dt = None
if 'df_historico_incremental' not in st.session_state:
    st.session_state.df_historico_incremental = pd.DataFrame()
if 'meta_diaria' not in st.session_state:
    st.session_state.meta_diaria = 50

# --- 5. SIDEBAR ---
with st.sidebar:
    st.write(f"Agente: {st.session_state.agente_id}")
    st.session_state.meta_diaria = st.number_input("Meta diaria:", value=st.session_state.meta_diaria, min_value=1)
    
    if st.button("Cerrar Sesion"):
        add_log("Sesion cerrada manualmente")
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()
    
    st.divider()
    uploaded_file = st.file_uploader("Cargar Base (CSV)", type="csv")
    if uploaded_file and st.session_state.df_contactos is None:
        df = pd.read_csv(uploaded_file, sep=None, engine='python', encoding='utf-8-sig')
        df.columns = [str(c).strip().lower() for c in df.columns]
        columnas = ['estado', 'observacion', 'fecha_llamada', 'duracion_seg', 'sid_llamada', 'proxima_llamada']
        for col in columnas:
            if col not in df.columns: df[col] = 'Pendiente' if col == 'estado' else ''
        df['agente_id'] = st.session_state.agente_id
        st.session_state.df_contactos = df
        add_log("Base de datos cargada exitosamente")

    if st.session_state.df_contactos is not None:
        st.divider()
        st.subheader("Reportes")
        df_full = st.session_state.df_contactos
        
        # Pendientes + No Contestados
        df_pend = df_full[df_full['estado'].isin(['Pendiente', 'No Contesto', 'Programada'])]
        if not df_pend.empty:
            st.download_button("Descargar Pendientes", df_pend.to_csv(index=False).encode('utf-8-sig'), "pendientes.csv", "text/csv", use_container_width=True)

        # Mi Gestion
        if not st.session_state.df_historico_incremental.empty:
            st.download_button("Descargar Mi Gestion", st.session_state.df_historico_incremental.to_csv(index=False).encode('utf-8-sig'), "gestion_agente.csv", "text/csv", use_container_width=True)
        
        # Log de Auditoria
        st.download_button("Descargar Log Auditoria", "\n".join(st.session_state.logs), "auditoria.log", "text/plain", use_container_width=True)

# --- 6. CUERPO PRINCIPAL ---
st.markdown("<h1 class='main-header'>Centro de Llamadas Camacol</h1>", unsafe_allow_html=True)

if st.session_state.df_contactos is not None:
    # --- METRICAS ---
    df = st.session_state.df_contactos
    pendientes = len(df[df['estado'] == 'Pendiente'])
    llamados = len(df[df['estado'] == 'Llamado'])
    no_contesto = len(df[df['estado'] == 'No Contesto'])
    total_base = len(df)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pendientes", pendientes)
    c2.metric("Llamados", llamados)
    c3.metric("No Contesto", no_contesto)
    c4.metric("Progreso Dia", f"{llamados}/{st.session_state.meta_diaria}")

    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.write("Progreso Lista")
        st.progress((total_base - pendientes) / total_base if total_base > 0 else 0)
    with col_p2:
        st.write("Progreso Objetivo")
        st.progress(min(llamados / st.session_state.meta_diaria, 1.0) if st.session_state.meta_diaria > 0 else 0)

    st.divider()

    tab_op, tab_log = st.tabs(["Operacion de Llamadas", "Log de Actividad"])

    with tab_log:
        st.markdown(f"<div class='log-box'>{'<br>'.join(st.session_state.logs[::-1])}</div>", unsafe_allow_html=True)

    with tab_op:
        opcion_lista = st.radio("Lista:", ["Pendientes", "No Contestaron", "Programadas"], horizontal=True)
        filtro_est = "Pendiente" if "Pendientes" in opcion_lista else "No Contesto" if "No Contestaron" in opcion_lista else "Programada"
        df_trabajo = df[df['estado'] == filtro_est]

        if not df_trabajo.empty:
            idx = df_trabajo.index[0]
            cliente = df_trabajo.loc[idx]
            tel_cliente = f"+{str(cliente['codigo_pais']).replace('+', '')}{str(cliente['telefono'])}"

            col_info, col_ctrl = st.columns([2, 1])

            with col_info:
                st.markdown(f"<div class='client-card'><h2>{cliente['nombre']}</h2><p>Tel: {tel_cliente}</p></div>", unsafe_allow_html=True)
                nota_input = st.text_area("Notas de la gestion:", key=f"n_{idx}")
                
                # CALLBACK SCHEDULING
                col_c1, col_c2 = st.columns(2)
                callback_date = col_c1.date_input("Programar re-llamada (Opcional):", min_value=datetime.now())
                callback_time = col_c2.time_input("Hora proxima:", value=(datetime.now() + timedelta(hours=1)).time())

            with col_ctrl:
                if st.session_state.llamada_activa_sid is None:
                    if st.button("INICIAR LLAMADA (AMD ACTIVE)", use_container_width=True, type="primary"):
                        try:
                            ahora = datetime.now()
                            # AMD (Deteccion de contestador) activado
                            call = client.calls.create(
                                url=function_url, to=tel_cliente, from_=twilio_number, 
                                record=True, machine_detection='Enable'
                            )
                            st.session_state.llamada_activa_sid = call.sid
                            st.session_state.t_inicio_dt = ahora
                            add_log(f"Llamada iniciada a {cliente['nombre']} (SID: {call.sid})")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error Twilio: {e}")
                else:
                    try:
                        remote_call = client.calls(st.session_state.llamada_activa_sid).fetch()
                        status = remote_call.status
                        answered_by = getattr(remote_call, 'answered_by', 'Desconocido')
                    except: status, answered_by = "finalizada", "Desconocido"

                    st.markdown(f"<h1 class='status-active'>{status.upper()}</h1>", unsafe_allow_html=True)
                    if answered_by == 'machine_start':
                        st.warning("DETECTOR: Contestador automatico detectado")

                    st.link_button("ABRIR FORMULARIO", f"{forms_base_url}?id={st.session_state.llamada_activa_sid}", use_container_width=True)

                    # FINALIZAR GESTION
                    if st.button("FINALIZAR GESTION", use_container_width=True, type="secondary"):
                        try: client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                        except: pass
                        
                        duracion = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                        
                        # Guardar Datos
                        st.session_state.df_contactos.at[idx, 'estado'] = 'Llamado'
                        st.session_state.df_contactos.at[idx, 'observacion'] = nota_input
                        st.session_state.df_contactos.at[idx, 'duracion_seg'] = duracion
                        st.session_state.df_contactos.at[idx, 'fecha_llamada'] = datetime.now().strftime("%Y-%m-%d")
                        
                        # Si programo rellamada
                        if st.button("Confirmar Programacion"):
                            st.session_state.df_contactos.at[idx, 'estado'] = 'Programada'
                            st.session_state.df_contactos.at[idx, 'proxima_llamada'] = f"{callback_date} {callback_time}"
                        
                        # WhatsApp Post-Llamada
                        wa_msg = urllib.parse.quote(f"Hola {cliente['nombre']}, soy {st.session_state.agente_id} de Camacol. Intentamos comunicarnos contigo...")
                        wa_url = f"https://wa.me/{tel_cliente.replace('+', '')}?text={wa_msg}"
                        st.link_button("ENVIAR WHATSAPP", wa_url, use_container_width=True)

                        # Sync Historial
                        registro = st.session_state.df_contactos.loc[[idx]].copy()
                        st.session_state.df_historico_incremental = pd.concat([st.session_state.df_historico_incremental, registro], ignore_index=True)
                        
                        if URL_SHEET_INFORME:
                            try:
                                conn.update(spreadsheet=URL_SHEET_INFORME, data=st.session_state.df_historico_incremental)
                                add_log(f"Gestion guardada y sincronizada para {cliente['nombre']}")
                            except: pass
                        
                        st.session_state.llamada_activa_sid = None
                        st.rerun()

                    time.sleep(3)
                    st.rerun()
        else:
            st.success("Lista completada.")
else:
    st.info("Cargue un archivo CSV para iniciar.")
