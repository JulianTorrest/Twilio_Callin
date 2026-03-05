import streamlit as st
import pandas as pd
from twilio.rest import Client
from datetime import datetime
from streamlit_gsheets import GSheetsConnection
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Camacol - Dialer Pro", page_icon="📞", layout="wide")

# --- ESTILOS PERSONALIZADOS (CSS) ---
st.markdown("""
    <style>
    /* Estilo para las métricas principales */
    .stMetric {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        border: 1px solid #e1e4e8;
    }
    /* Estilo para el contenedor de información del cliente */
    .client-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 15px;
        border-left: 10px solid #003366;
        margin-bottom: 20px;
    }
    /* Botones redondeados */
    .stButton>button {
        border-radius: 8px;
        height: 3em;
        font-weight: bold;
    }
    /* Títulos personalizados */
    .main-header {
        color: #003366;
        text-align: center;
        padding: 10px;
        border-bottom: 2px solid #003366;
        margin-bottom: 20px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 1. CONFIGURACIÓN DE CONEXIONES Y SECRETS ---
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
    st.error(f"Error de configuración: {e}")
    st.stop()

# --- 2. CONTROL DE ACCESO ---
if 'agente_id' not in st.session_state:
    st.markdown("<h1 class='main-header'>Acceso al Sistema Camacol</h1>", unsafe_allow_html=True)
    with st.form("login"):
        cedula_input = st.text_input("Ingrese su número de cédula:", type="password").strip()
        if st.form_submit_button("Ingresar al Portal"):
            if cedula_input in [str(c).strip() for c in CEDULAS_AUTORIZADAS]:
                st.session_state.agente_id = cedula_input
                st.success(f"Bienvenido, Agente {cedula_input}")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("Cédula no autorizada.")
    st.stop()

# --- 3. GESTIÓN DE ESTADO ---
if 'df_contactos' not in st.session_state:
    st.session_state.df_contactos = None
if 'llamada_activa_sid' not in st.session_state:
    st.session_state.llamada_activa_sid = None
if 't_inicio_dt' not in st.session_state:
    st.session_state.t_inicio_dt = None
if 'df_historico_incremental' not in st.session_state:
    st.session_state.df_historico_incremental = pd.DataFrame()

# --- 4. SIDEBAR Y CARGA ---
with st.sidebar:
    st.image("https://camacol.co/sites/default/files/logo-camacol.png", width=150) # Logo genérico
    st.write(f"👤 **Agente:** {st.session_state.agente_id}")
    if st.button("Cerrar Sesión"):
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()
    
    st.divider()
    uploaded_file = st.file_uploader("Cargar Base de Clientes (.csv)", type="csv")
    if uploaded_file and st.session_state.df_contactos is None:
        df = pd.read_csv(uploaded_file, sep=None, engine='python', encoding='utf-8-sig')
        df.columns = [str(c).strip().lower() for c in df.columns]
        for col in ['estado', 'observacion', 'fecha_llamada', 'hora_inicio', 'duracion_seg', 'sid_llamada', 'enlace_grabacion', 'url_formulario_enviado']:
            if col not in df.columns: df[col] = 'Pendiente' if col == 'estado' else ''
        df['agente_id'] = st.session_state.agente_id
        st.session_state.df_contactos = df

# --- 5. CUERPO PRINCIPAL ---
st.markdown("<h1 class='main-header'>Centro de Llamadas Inteligente Camacol</h1>", unsafe_allow_html=True)

if st.session_state.df_contactos is not None:
    tab_op, tab_test = st.tabs([" Operación Real", " Pruebas de Calidad"])

    # --- TAB DE PRUEBAS ---
    with tab_test:
        st.info("Configura una prueba puente entre dos humanos (Tu celular <-> Número prueba)")
        modo_prueba = st.toggle("Activar Modo Prueba (Puente Humano)")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            mi_celular = st.text_input("Tu celular (Agente):", value="+57")
        with col_t2:
            numero_prueba = st.text_input("Número de prueba (Cliente):", value="+57")

    # --- TAB DE OPERACIÓN ---
    with tab_op:
        df = st.session_state.df_contactos
        # Métricas visuales superiores
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Pendientes", len(df[df['estado'] == 'Pendiente']))
        m2.metric("Llamados", len(df[df['estado'] == 'Llamado']))
        m3.metric("No Contesto", len(df[df['estado'] == 'No Contesto']))
        
        # Calcular porcentaje de progreso
        total = len(df)
        completados = len(df[df['estado'] != 'Pendiente'])
        progreso = completados / total if total > 0 else 0
        st.write(f"**Progreso de la lista:** {int(progreso*100)}%")
        st.progress(progreso)

        st.divider()

        opcion_lista = st.radio("Lista de trabajo:", ["Pendientes", "Re-intentos (No contestaron)"], horizontal=True)
        df_trabajo = df[df['estado'] == 'Pendiente'] if "Pendientes" in opcion_lista else df[df['estado'] == 'No Contesto']

        if not df_trabajo.empty:
            idx = df_trabajo.index[0]
            cliente = df_trabajo.loc[idx]
            tel_final = f"+{str(cliente['codigo_pais']).replace('+', '')}{str(cliente['telefono'])}"

            # --- INTERFAZ DE LLAMADA ---
            col_info, col_ctrl = st.columns([2, 1])

            with col_info:
                st.markdown(f"""
                    <div class='client-card'>
                        <h2 style='margin:0;'>{cliente['nombre']}</h2>
                        <p style='font-size:1.2em; color:#555;'>📍 Destino: {tel_final}</p>
                    </div>
                """, unsafe_allow_html=True)

                with st.expander("GUION SUGERIDO (SCRIPT)"):
                    st.write(f"**Hola {cliente['nombre']},** le hablamos de **Camacol**. El motivo de mi llamada es...")
                
                nota_input = st.text_area("Observaciones de la llamada:", placeholder="Ej: Interesado en el proyecto, volver a llamar en una semana...")

            with col_ctrl:
                if st.session_state.llamada_activa_sid is None:
                    st.subheader("Estado: 🟢 Listo")
                    if st.button(" INICIAR LLAMADA", use_container_width=True, type="primary"):
                        try:
                            ahora = datetime.now()
                            if modo_prueba:
                                twiml_bridge = f"<Response><Say language='es-MX'>Conectando con prueba.</Say><Dial record='record-from-answer-dual' callerId='{twilio_number}'><Number>{numero_prueba}</Number></Dial></Response>"
                                call = client.calls.create(twiml=twiml_bridge, to=mi_celular, from_=twilio_number)
                            else:
                                call = client.calls.create(url=function_url, to=tel_final, from_=twilio_number, record=True)
                            
                            st.session_state.llamada_activa_sid = call.sid
                            st.session_state.t_inicio_dt = ahora
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                else:
                    # Lógica de llamada activa
                    try:
                        remote_call = client.calls(st.session_state.llamada_activa_sid).fetch()
                        status = remote_call.status
                    except: status = "Finalizada"

                    # Cronómetro y Estado
                    duracion = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                    st.markdown(f"<h1 style='text-align:center; color:red;'>● {duracion}s</h1>", unsafe_allow_html=True)
                    st.write(f"**Estado Twilio:** `{status.upper()}`")

                    # Link a Formulario
                    link_f = f"{forms_base_url}?id={st.session_state.llamada_activa_sid}&agente={st.session_state.agente_id}"
                    st.link_button("📋 ABRIR FORMULARIO", link_f, use_container_width=True)

                    if st.button(" FINALIZAR GESTIÓN", use_container_width=True):
                        # Guardar datos
                        st.session_state.df_contactos.at[idx, 'estado'] = 'Llamado'
                        st.session_state.df_contactos.at[idx, 'observacion'] = nota_input
                        st.session_state.df_contactos.at[idx, 'duracion_seg'] = duracion
                        st.session_state.df_contactos.at[idx, 'sid_llamada'] = st.session_state.llamada_activa_sid
                        
                        # Sync con Google Sheets
                        if URL_SHEET_INFORME:
                            try:
                                registro = st.session_state.df_contactos.loc[[idx]]
                                st.session_state.df_historico_incremental = pd.concat([st.session_state.df_historico_incremental, registro])
                                conn.update(spreadsheet=URL_SHEET_INFORME, data=st.session_state.df_historico_incremental)
                            except: pass
                        
                        # Colgar llamada real en Twilio
                        try: client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                        except: pass
                        
                        st.session_state.llamada_activa_sid = None
                        st.rerun()

                    # Auto-refresh cada 3 segundos mientras hay llamada
                    time.sleep(3)
                    st.rerun()

        else:
            st.success(" ¡Felicidades! Has completado esta lista de contactos.")
else:
    st.info(" Bienvenida(o). Por favor carga un archivo CSV en el panel lateral para comenzar.")
