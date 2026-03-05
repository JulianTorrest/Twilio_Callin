import streamlit as st
import pandas as pd
from twilio.rest import Client
from datetime import datetime
from streamlit_gsheets import GSheetsConnection
import time

# --- CONFIGURACION DE PAGINA ---
st.set_page_config(page_title="Camacol - Dialer Pro", layout="wide")

# --- ESTILOS PERSONALIZADOS (CSS) ---
st.markdown("""
    <style>
    .stMetric {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        border: 1px solid #e1e4e8;
    }
    .client-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 15px;
        border-left: 10px solid #003366;
        margin-bottom: 20px;
    }
    .main-header {
        color: #003366;
        text-align: center;
        padding: 10px;
        border-bottom: 2px solid #003366;
        margin-bottom: 20px;
    }
    .status-active {
        color: #d9534f;
        font-weight: bold;
        text-align: center;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 1. CONFIGURACION DE CONEXIONES Y SECRETS ---
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

# --- 2. CONTROL DE ACCESO ---
if 'agente_id' not in st.session_state:
    st.markdown("<h1 class='main-header'>Acceso al Sistema Camacol</h1>", unsafe_allow_html=True)
    with st.form("login"):
        cedula_input = st.text_input("Ingrese su numero de cedula:", type="password").strip()
        if st.form_submit_button("Ingresar al Portal"):
            if cedula_input in [str(c).strip() for c in CEDULAS_AUTORIZADAS]:
                st.session_state.agente_id = cedula_input
                st.rerun()
            else:
                st.error("Cedula no autorizada.")
    st.stop()

# --- 3. GESTION DE ESTADO ---
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

# --- 4. SIDEBAR ---
with st.sidebar:
    st.write(f"Agente: {st.session_state.agente_id}")
    st.session_state.meta_diaria = st.number_input("Definir meta de llamadas diaria:", value=st.session_state.meta_diaria, min_value=1)
    
    if st.button("Cerrar Sesion"):
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()
    
    st.divider()
    uploaded_file = st.file_uploader("Cargar Base de Clientes (CSV)", type="csv")
    
    if uploaded_file and st.session_state.df_contactos is None:
        df = pd.read_csv(uploaded_file, sep=None, engine='python', encoding='utf-8-sig')
        df.columns = [str(c).strip().lower() for c in df.columns]
        columnas_necesarias = ['estado', 'observacion', 'fecha_llamada', 'hora_inicio', 'duracion_seg', 'sid_llamada']
        for col in columnas_necesarias:
            if col not in df.columns: df[col] = 'Pendiente' if col == 'estado' else ''
        df['agente_id'] = st.session_state.agente_id
        st.session_state.df_contactos = df

    # --- SECCION DE DESCARGAS ---
    if st.session_state.df_contactos is not None:
        st.divider()
        st.subheader("Reportes")
        df_full = st.session_state.df_contactos
        
        # Filtro para pendientes y no contestados
        df_pendientes = df_full[df_full['estado'].isin(['Pendiente', 'No Contesto'])]
        if not df_pendientes.empty:
            csv_pend = df_pendientes.to_csv(index=False).encode('utf-8-sig')
            st.download_button("Descargar Pendientes", csv_pend, "pendientes.csv", "text/csv", use_container_width=True)

        # Filtro para gestion realizada (Historico)
        if not st.session_state.df_historico_incremental.empty:
            csv_hist = st.session_state.df_historico_incremental.to_csv(index=False).encode('utf-8-sig')
            st.download_button("Descargar Mi Gestion", csv_hist, f"gestion_{st.session_state.agente_id}.csv", "text/csv", use_container_width=True)

# --- 5. CUERPO PRINCIPAL ---
st.markdown("<h1 class='main-header'>Centro de Llamadas Camacol</h1>", unsafe_allow_html=True)

if st.session_state.df_contactos is not None:
    # --- METRICAS ---
    df = st.session_state.df_contactos
    pendientes = len(df[df['estado'] == 'Pendiente'])
    llamados_hoy = len(df[df['estado'] == 'Llamado'])
    no_contesto = len(df[df['estado'] == 'No Contesto'])
    total_base = len(df)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pendientes", pendientes)
    c2.metric("Llamados Exitosos", llamados_hoy)
    c3.metric("No Contesto", no_contesto)
    c4.metric("Meta Diaria", f"{llamados_hoy}/{st.session_state.meta_diaria}")

    # --- BARRAS DE PROGRESO ---
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        progreso_lista = (total_base - pendientes) / total_base if total_base > 0 else 0
        st.write(f"Progreso de la Lista: {int(progreso_lista*100)}%")
        st.progress(progreso_lista)
    
    with col_p2:
        progreso_diario = llamados_hoy / st.session_state.meta_diaria if st.session_state.meta_diaria > 0 else 0
        progreso_diario = min(progreso_diario, 1.0)
        st.write(f"Progreso del Dia: {int(progreso_diario*100)}%")
        st.progress(progreso_diario)

    st.divider()

    tab_op, tab_test = st.tabs(["Operacion", "Pruebas"])

    with tab_test:
        modo_prueba = st.toggle("Activar Modo Prueba (Puente Humano)")
        col_t1, col_t2 = st.columns(2)
        mi_celular = col_t1.text_input("Tu celular (Agente):", value="+57")
        numero_prueba = col_t2.text_input("Numero de prueba (Cliente):", value="+57")

    with tab_op:
        opcion_lista = st.radio("Seleccionar lista:", ["Pendientes", "No Contestaron"], horizontal=True)
        df_trabajo = df[df['estado'] == 'Pendiente'] if "Pendientes" in opcion_lista else df[df['estado'] == 'No Contesto']

        if not df_trabajo.empty:
            idx = df_trabajo.index[0]
            cliente = df_trabajo.loc[idx]
            tel_cliente = f"+{str(cliente['codigo_pais']).replace('+', '')}{str(cliente['telefono'])}"

            col_info, col_ctrl = st.columns([2, 1])

            with col_info:
                st.markdown(f"<div class='client-card'><h2>{cliente['nombre']}</h2><p>Telefono: {tel_cliente}</p></div>", unsafe_allow_html=True)
                with st.expander("Script de llamada"):
                    st.write(f"Buenos dias, hablo con {cliente['nombre']}? Le llamamos de Camacol...")
                nota_input = st.text_area("Notas de la gestion:", key=f"n_{idx}")

            with col_ctrl:
                if st.session_state.llamada_activa_sid is None:
                    if st.button("INICIAR LLAMADA", use_container_width=True, type="primary"):
                        try:
                            ahora = datetime.now()
                            if modo_prueba:
                                twiml_bridge = f"<Response><Dial record='record-from-answer-dual' callerId='{twilio_number}'><Number>{numero_prueba}</Number></Dial></Response>"
                                call = client.calls.create(twiml=twiml_bridge, to=mi_celular, from_=twilio_number)
                            else:
                                call = client.calls.create(url=function_url, to=tel_cliente, from_=twilio_number, record=True)
                            
                            st.session_state.llamada_activa_sid = call.sid
                            st.session_state.t_inicio_dt = ahora
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error Twilio: {e}")
                else:
                    try:
                        remote_call = client.calls(st.session_state.llamada_activa_sid).fetch()
                        status = remote_call.status
                    except: status = "desconectado"

                    duracion = int((datetime.now() - st.session_state.t_inicio_dt).total_seconds())
                    st.markdown(f"<h1 class='status-active'>{duracion}s</h1>", unsafe_allow_html=True)
                    st.write(f"Estatus: {status.upper()}")

                    link_f = f"{forms_base_url}?id={st.session_state.llamada_activa_sid}"
                    st.link_button("ABRIR FORMULARIO", link_f, use_container_width=True)

                    if st.button("FINALIZAR GESTION", use_container_width=True, type="secondary"):
                        try: client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                        except: pass
                        
                        # Actualizar base local
                        st.session_state.df_contactos.at[idx, 'estado'] = 'Llamado'
                        st.session_state.df_contactos.at[idx, 'observacion'] = nota_input
                        st.session_state.df_contactos.at[idx, 'duracion_seg'] = duracion
                        st.session_state.df_contactos.at[idx, 'fecha_llamada'] = datetime.now().strftime("%Y-%m-%d")
                        
                        # Actualizar Historico Incremental
                        registro = st.session_state.df_contactos.loc[[idx]].copy()
                        st.session_state.df_historico_incremental = pd.concat([st.session_state.df_historico_incremental, registro], ignore_index=True)
                        
                        # GUARDADO EN GOOGLE SHEETS
                        if URL_SHEET_INFORME:
                            try:
                                conn.update(spreadsheet=URL_SHEET_INFORME, data=st.session_state.df_historico_incremental)
                                st.toast("Datos sincronizados con Sheets")
                            except Exception as e:
                                st.error(f"Error al sincronizar Sheets: {e}")
                        
                        st.session_state.llamada_activa_sid = None
                        st.rerun()

                    time.sleep(3)
                    st.rerun()
        else:
            st.success("Lista completada.")
else:
    st.info("Cargue un archivo CSV para iniciar.")
