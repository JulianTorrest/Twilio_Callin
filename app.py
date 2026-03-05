import streamlit as st
import pandas as pd
from twilio.rest import Client
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection
import time
import urllib.parse

# --- CONFIGURACION DE PAGINA Y DISEÑO RESPONSIVO ---
st.set_page_config(page_title="Camacol Dialer Pro", layout="wide")

st.markdown("""
    <style>
    /* Diseño adaptable para tablets y moviles */
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; }
    .stMetric { background-color: #ffffff; padding: 10px; border-radius: 10px; border: 1px solid #e1e4e8; }
    .client-card { 
        background-color: #f0f2f6; padding: 15px; border-radius: 15px; 
        border-left: 8px solid #003366; margin-bottom: 15px;
    }
    .main-header { color: #003366; text-align: center; border-bottom: 2px solid #003366; padding-bottom: 10px; }
    .log-box { 
        font-family: 'Courier New', monospace; font-size: 0.85rem; 
        background: #1e1e1e; color: #4af626; padding: 12px; 
        border-radius: 8px; height: 200px; overflow-y: auto;
    }
    /* Botones mas grandes para pantallas tactiles */
    .stButton>button { width: 100%; height: 3em; font-weight: bold; }
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
    CEDULAS_AUTORIZADAS = ["1121871773", "87654321", "12345678"] 
    client = Client(account_sid, auth_token)
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"Error de configuracion inicial: {e}")
    st.stop()

# --- 2. AUDITORIA Y LOGS (Manejo de errores robusto) ---
if 'logs' not in st.session_state:
    st.session_state.logs = []

def add_log(mensaje, tipo="INFO"):
    t_stamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{t_stamp}] {tipo}: {mensaje}"
    st.session_state.logs.append(log_entry)
    # Mantener solo los ultimos 100 logs para rendimiento
    if len(st.session_state.logs) > 100: st.session_state.logs.pop(0)

# --- 3. CONTROL DE ACCESO ---
if 'agente_id' not in st.session_state:
    st.markdown("<h1 class='main-header'>Acceso Camacol</h1>", unsafe_allow_html=True)
    with st.container():
        c1, c2, c3 = st.columns([1,2,1])
        with c2:
            with st.form("login"):
                cedula_input = st.text_input("Cedula de Agente:", type="password").strip()
                if st.form_submit_button("INGRESAR"):
                    if cedula_input in CEDULAS_AUTORIZADAS:
                        st.session_state.agente_id = cedula_input
                        add_log(f"Login exitoso agente {cedula_input}")
                        st.rerun()
                    else: st.error("Acceso denegado.")
    st.stop()

# --- 4. GESTION DE ESTADO Y PERSISTENCIA ---
if 'df_contactos' not in st.session_state: st.session_state.df_contactos = None
if 'llamada_activa_sid' not in st.session_state: st.session_state.llamada_activa_sid = None
if 't_inicio_dt' not in st.session_state: st.session_state.t_inicio_dt = None
if 'meta_diaria' not in st.session_state: st.session_state.meta_diaria = 50

# --- 5. SIDEBAR (Carga y Reportes) ---
with st.sidebar:
    st.header(f"Agente: {st.session_state.agente_id}")
    st.session_state.meta_diaria = st.number_input("Meta de hoy:", value=st.session_state.meta_diaria)
    
    if st.button("Cerrar Sesion", type="secondary"):
        add_log("Sesion cerrada")
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()
    
    st.divider()
    up_file = st.file_uploader("Cargar Base (CSV)", type="csv")
    if up_file and st.session_state.df_contactos is None:
        try:
            df = pd.read_csv(up_file, sep=None, engine='python', encoding='utf-8-sig')
            df.columns = [str(c).strip().lower() for c in df.columns]
            cols_req = ['estado', 'observacion', 'fecha_llamada', 'duracion_seg', 'sid_llamada', 'proxima_llamada']
            for c in cols_req:
                if c not in df.columns: df[c] = 'Pendiente' if c == 'estado' else ''
            df['agente_id'] = st.session_state.agente_id
            st.session_state.df_contactos = df
            add_log("Base cargada correctamente")
        except Exception as e: add_log(f"Error cargando CSV: {e}", "ERROR")

    if st.session_state.df_contactos is not None:
        st.subheader("Descargas")
        df_full = st.session_state.df_contactos
        # Reporte Pendientes
        df_p = df_full[df_full['estado'].isin(['Pendiente', 'No Contesto', 'Programada'])]
        st.download_button("Descargar Pendientes", df_p.to_csv(index=False).encode('utf-8-sig'), "pendientes.csv", "text/csv")
        # Reporte Logs
        st.download_button("Descargar Auditoria", "\n".join(st.session_state.logs), "auditoria.log", "text/plain")

# --- 6. PANEL PRINCIPAL ---
st.markdown("<h2 class='main-header'>Dialer Pro Camacol</h2>", unsafe_allow_html=True)

if st.session_state.df_contactos is not None:
    df = st.session_state.df_contactos
    
    # METRICAS
    m1, m2, m3, m4 = st.columns(4)
    llamados_hoy = len(df[df['estado'] == 'Llamado'])
    m1.metric("Pendientes", len(df[df['estado'] == 'Pendiente']))
    m2.metric("Logrados", llamados_hoy)
    m3.metric("No Contesto", len(df[df['estado'] == 'No Contesto']))
    m4.metric("Meta", f"{int((llamados_hoy/st.session_state.meta_diaria)*100)}%")

    st.divider()

    tab_op, tab_log = st.tabs(["Panel de Operacion", "Auditoria de Sistema"])

    with tab_log:
        st.markdown(f"<div class='log-box'>{'<br>'.join(st.session_state.logs[::-1])}</div>", unsafe_allow_html=True)

    with tab_op:
        # OPTIMIZACION DE CARGA: Paginacion / Filtros
        opc = st.radio("Ver lista:", ["Pendientes", "No Contestaron", "Programadas"], horizontal=True)
        f_est = "Pendiente" if "Pendientes" in opc else "No Contesto" if "No Contestaron" in opc else "Programada"
        
        # Filtrar datos de trabajo
        df_w = df[df['estado'] == f_est]
        
        if not df_w.empty:
            # PAGINACION: Tomamos solo el primero para procesar
            idx = df_w.index[0]
            c = df_w.loc[idx]
            tel = f"+{str(c['codigo_pais']).replace('+', '')}{str(c['telefono'])}"

            col_a, col_b = st.columns([2, 1])
            with col_a:
                st.markdown(f"""<div class='client-card'>
                    <h3>{c['nombre']}</h3>
                    <p><b>Telefono:</b> {tel} | <b>Estado Actual:</b> {c['estado']}</p>
                </div>""", unsafe_allow_html=True)
                nota = st.text_area("Notas de gestion:", key=f"note_{idx}")
                
                # CALLBACK SCHEDULING
                exp_c = st.expander("Programar rellamada futura")
                with exp_c:
                    c_date = st.date_input("Fecha:", min_value=datetime.now())
                    c_time = st.time_input("Hora:")

            with col_b:
                if st.session_state.llamada_activa_sid is None:
                    if st.button("INICIAR LLAMADA (AMD)", type="primary"):
                        with st.spinner("Conectando con Twilio..."):
                            try:
                                call = client.calls.create(
                                    url=function_url, to=tel, from_=twilio_number,
                                    machine_detection='Enable', record=True
                                )
                                st.session_state.llamada_activa_sid = call.sid
                                st.session_state.t_inicio_dt = datetime.now()
                                add_log(f"Llamando a {c['nombre']}")
                                st.rerun()
                            except Exception as e:
                                add_log(f"Error Twilio: {e}", "ERROR")
                                st.error("No se pudo iniciar la llamada.")
                else:
                    # FEEDBACK VISUAL DE LLAMADA
                    try:
                        remote = client.calls(st.session_state.llamada_activa_sid).fetch()
                        status = remote.status
                        amd = getattr(remote, 'answered_by', 'human')
                    except: status, amd = "error", "unknown"

                    st.markdown(f"<h2 class='status-active'>{status.upper()}</h2>", unsafe_allow_html=True)
                    if amd == 'machine_start': st.warning("Contestador detectado")
                    
                    st.link_button("ABRIR FORMULARIO MS", f"{forms_base_url}?id={st.session_state.llamada_activa_sid}")

                    if st.button("FINALIZAR GESTION", type="secondary"):
                        try: client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                        except: pass
                        
                        # CALCULO DURACION
                        dur = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                        
                        # ACTUALIZAR DATAFRAME LOCAL
                        st.session_state.df_contactos.at[idx, 'estado'] = 'Llamado'
                        st.session_state.df_contactos.at[idx, 'observacion'] = nota
                        st.session_state.df_contactos.at[idx, 'duracion_seg'] = dur
                        st.session_state.df_contactos.at[idx, 'fecha_llamada'] = datetime.now().strftime("%Y-%m-%d")
                        st.session_state.df_contactos.at[idx, 'sid_llamada'] = st.session_state.llamada_activa_sid
                        
                        if c_date:
                            st.session_state.df_contactos.at[idx, 'proxima_llamada'] = f"{c_date} {c_time}"

                        # --- LOGICA DE SINCRONIZACION INTELIGENTE (EVITAR DUPLICADOS) ---
                        if URL_SHEET_INFORME:
                            try:
                                # 1. Leer datos existentes en Drive
                                df_drive = conn.read(spreadsheet=URL_SHEET_INFORME, worksheet="0")
                                # 2. Combinar con el nuevo registro
                                nuevo_reg = st.session_state.df_contactos.loc[[idx]]
                                df_final = pd.concat([df_drive, nuevo_reg], ignore_index=True)
                                # 3. Limpiar duplicados por SID
                                df_final = df_final.drop_duplicates(subset=['sid_llamada'], keep='last')
                                # 4. Actualizar Drive
                                conn.update(spreadsheet=URL_SHEET_INFORME, data=df_final)
                                add_log(f"Sincronizado: {c['nombre']}")
                            except Exception as e:
                                add_log(f"Error sincronizacion Drive: {e}", "ERROR")
                                st.error("Guardado localmente, error al subir a Drive.")

                        # WHATSAPP AUTOMATICO
                        msg_wa = urllib.parse.quote(f"Hola {c['nombre']}, soy de Camacol. Intentamos contactarte.")
                        st.markdown(f"[ENVIAR WHATSAPP](https://wa.me/{tel.replace('+', '')}?text={msg_wa})")

                        st.session_state.llamada_activa_sid = None
                        st.rerun()

                    time.sleep(2)
                    st.rerun()
        else:
            st.success("No hay registros en esta categoria.")
else:
    st.info("Cargue un archivo CSV para comenzar la operacion.")
