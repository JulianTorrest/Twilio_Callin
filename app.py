import streamlit as st
import pandas as pd
from twilio.rest import Client
from datetime import datetime
from streamlit_gsheets import GSheetsConnection
import time

st.set_page_config(page_title="Dialer Pro - Colombia", page_icon="phone", layout="wide")

# --- 1. CONFIGURACION DE CONEXIONES Y SECRETS ---
try:
    # Twilio
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets.get("TWILIO_NUMBER", "+17068069672")
    function_url = st.secrets["TWILIO_FUNCTION_URL"]
    forms_base_url = st.secrets.get("MS_FORMS_URL", "https://forms.office.com/r/tu_codigo")
    
    # Google Sheets
    URL_SHEET_INFORME = st.secrets.get("GSHEET_URL")
    
    CEDULAS_AUTORIZADAS = ["1121871773", "87654321", "12345678"] 
    
    client = Client(account_sid, auth_token)
    
    # Inicializar la conexion a Google Sheets
    conn = st.connection("gsheets", type=GSheetsConnection)
except KeyError as e:
    st.error(f"Falta configuracion en Secrets: {e}")
    st.stop()
except Exception as e:
    st.error(f"Error de conexion: {e}")
    st.stop()

# --- 2. CONTROL DE ACCESO ---
if 'agente_id' not in st.session_state:
    st.title("Acceso al Sistema de Llamadas")
    cedula_input = st.text_input("Ingrese su numero de cedula:", type="password").strip()
    
    if st.button("Ingresar"):
        lista_limpia = [str(c).strip() for c in CEDULAS_AUTORIZADAS]
        if cedula_input in lista_limpia:
            st.session_state.agente_id = cedula_input
            st.success(f"Bienvenido, Agente {cedula_input}")
            time.sleep(0.5)
            st.rerun()
        else:
            st.error(f"Cedula '{cedula_input}' no autorizada.")
    st.stop()

# --- 3. GESTION DE ESTADO (SESSION STATE) ---
if 'df_contactos' not in st.session_state:
    st.session_state.df_contactos = None
if 'llamada_activa_sid' not in st.session_state:
    st.session_state.llamada_activa_sid = None
if 't_inicio_dt' not in st.session_state:
    st.session_state.t_inicio_dt = None
if 'df_historico_incremental' not in st.session_state:
    st.session_state.df_historico_incremental = pd.DataFrame()

st.title("Centro de Llamadas Inteligente + Drive")

# --- 4. CARGA Y LIMPIEZA DE ARCHIVO ---
st.sidebar.header(f"Agente: {st.session_state.agente_id}")
if st.sidebar.button("Cerrar Sesion"):
    for key in list(st.session_state.keys()): del st.session_state[key]
    st.rerun()

uploaded_file = st.sidebar.file_uploader("Cargar clientes.csv", type="csv")

if uploaded_file and st.session_state.df_contactos is None:
    df = pd.read_csv(uploaded_file, sep=None, engine='python', encoding='utf-8-sig')
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    columnas_extra = {
        'estado': 'Pendiente',
        'observacion': '',
        'fecha_llamada': '',
        'hora_inicio': '',
        'duracion_seg': 0,
        'sid_llamada': '',
        'enlace_grabacion': '',
        'url_formulario_enviado': '',
        'agente_id': st.session_state.agente_id
    }
    
    for col, val in columnas_extra.items():
        if col not in df.columns:
            df[col] = val
            
    st.session_state.df_contactos = df

# --- 5. LOGICA DE INTERFAZ Y TRABAJO ---
if st.session_state.df_contactos is not None:
    df_actual = st.session_state.df_contactos
    
    pendientes = df_actual[df_actual['estado'] == 'Pendiente']
    realizadas = df_actual[df_actual['estado'] == 'Llamado']
    no_contestados = df_actual[df_actual['estado'] == 'No Contesto']

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pendientes", len(pendientes))
    c2.metric("Realizadas", len(realizadas))
    c3.metric("No Contesto", len(no_contestados))
    c4.metric("Track Espejo", len(st.session_state.df_historico_incremental))

    # --- DESCARGAS PARA EL AGENTE ---
    st.sidebar.markdown("---")
    st.sidebar.header("Reportes Agente")
    if not st.session_state.df_historico_incremental.empty:
        csv_gestion = st.session_state.df_historico_incremental.to_csv(index=False).encode('utf-8-sig')
        st.sidebar.download_button("Descargar Mi Gestion", csv_gestion, f"gestion_{st.session_state.agente_id}.csv", "text/csv")
    
    if not pendientes.empty:
        csv_pend = pendientes.to_csv(index=False).encode('utf-8-sig')
        st.sidebar.download_button("Descargar Pendientes", csv_pend, "pendientes.csv", "text/csv")

    st.write("---")

    # --- SELECTOR DE LISTA DE TRABAJO ---
    st.subheader("Seleccion de Lista")
    opcion_lista = st.radio(
        "Elija el grupo de clientes a llamar:",
        ["Llamadas Pendientes (Nuevos)", "No Contestaron (Re-intentos)"],
        horizontal=True
    )

    if "Pendientes" in opcion_lista:
        df_trabajo = pendientes
    else:
        df_trabajo = no_contestados

    # --- PANEL DE MARCACION ---
    if not df_trabajo.empty:
        idx = df_trabajo.index[0]
        proximo = df_trabajo.loc[idx]

        pais = str(proximo['codigo_pais']).strip().replace('+', '')
        tel = str(proximo['telefono']).strip()
        num_final = f"+{pais}{tel}"

        with st.container(border=True):
            col_info, col_ctrl = st.columns([2, 1])
            
            with col_info:
                st.subheader(f"Cliente: {proximo['nombre']}")
                if st.session_state.llamada_activa_sid is None:
                    st.warning(f"Trabajando lista: {opcion_lista}")
                else:
                    st.info(f"Marcando: {num_final}")
                
                nota_input = st.text_area("Notas / Observaciones:", key=f"nota_{idx}")

            with col_ctrl:
                if st.session_state.llamada_activa_sid is None:
                    st.write("### Estado: Listo")
                    if st.button("INICIAR LLAMADA", key=f"btn_start_{idx}", use_container_width=True, type="primary"):
                        try:
                            ahora = datetime.now()
                            call = client.calls.create(url=function_url, to=num_final, from_=twilio_number, record=True)
                            st.session_state.llamada_activa_sid = call.sid
                            st.session_state.t_inicio_dt = ahora 
                            st.session_state.df_contactos.at[idx, 'sid_llamada'] = call.sid
                            st.session_state.df_contactos.at[idx, 'fecha_llamada'] = ahora.strftime("%Y-%m-%d")
                            st.session_state.df_contactos.at[idx, 'hora_inicio'] = ahora.strftime("%H:%M:%S")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error Twilio: {e}")
                
                else:
                    try:
                        remote_call = client.calls(st.session_state.llamada_activa_sid).fetch()
                        current_status = remote_call.status
                    except Exception:
                        current_status = "unknown"

                    st.write(f"### Estado: {current_status.upper()}")

                    id_call = st.session_state.llamada_activa_sid
                    link_forms = f"{forms_base_url}?id_llamada={id_call}&agente={st.session_state.agente_id}"
                    st.markdown(f"### [LLENAR FORMULARIO]({link_forms})")

                    if current_status in ['no-answer', 'busy', 'failed', 'canceled']:
                        st.session_state.df_contactos.at[idx, 'estado'] = 'No Contesto'
                        st.session_state.df_contactos.at[idx, 'observacion'] = f"Sistema: {current_status}"
                        
                        registro_espejo = st.session_state.df_contactos.loc[[idx]].copy()
                        st.session_state.df_historico_incremental = pd.concat([st.session_state.df_historico_incremental, registro_espejo], ignore_index=True)
                        
                        if URL_SHEET_INFORME:
                            conn.update(spreadsheet=URL_SHEET_INFORME, data=st.session_state.df_historico_incremental)
                        
                        st.session_state.llamada_activa_sid = None
                        st.rerun()

                    if st.button("FINALIZAR LLAMADA", key="btn_hangup", use_container_width=True, type="secondary"):
                        try:
                            duracion_seg = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                            client.calls(id_call).update(status='completed')
                            
                            st.session_state.df_contactos.at[idx, 'estado'] = 'Llamado'
                            st.session_state.df_contactos.at[idx, 'observacion'] = nota_input
                            st.session_state.df_contactos.at[idx, 'duracion_seg'] = duracion_seg
                            st.session_state.df_contactos.at[idx, 'enlace_grabacion'] = f"https://console.twilio.com/us1/monitor/logs/calls/{id_call}"
                            st.session_state.df_contactos.at[idx, 'url_formulario_enviado'] = link_forms
                            
                            registro_espejo = st.session_state.df_contactos.loc[[idx]].copy()
                            st.session_state.df_historico_incremental = pd.concat([st.session_state.df_historico_incremental, registro_espejo], ignore_index=True)
                            
                            if URL_SHEET_INFORME:
                                conn.update(spreadsheet=URL_SHEET_INFORME, data=st.session_state.df_historico_incremental)
                            
                            st.session_state.llamada_activa_sid = None
                            st.rerun()
                        except Exception:
                            st.session_state.llamada_activa_sid = None
                            st.rerun()
                    
                    time.sleep(4)
                    st.rerun()

    else:
        st.success(f"Has terminado con todos los contactos de la lista: {opcion_lista}")

    if not st.session_state.df_historico_incremental.empty:
        with st.expander("Vista Previa del Track Espejo (Drive Sync)"):
            st.dataframe(st.session_state.df_historico_incremental)

else:
    st.info("Por favor, ingrese su cedula y cargue el archivo clientes.csv.")
