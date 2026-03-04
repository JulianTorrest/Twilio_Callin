import streamlit as st
import pandas as pd
from twilio.rest import Client
from datetime import datetime
import io

st.set_page_config(page_title="Dialer Pro - Colombia", page_icon="📞", layout="wide")

# --- CONFIGURACIÓN DE TWILIO ---
try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets.get("TWILIO_NUMBER", "+17068069672")
    function_url = st.secrets["TWILIO_FUNCTION_URL"]
    client = Client(account_sid, auth_token)
except KeyError:
    st.error("⚠️ Configura los Secrets en Streamlit Cloud.")
    st.stop()

st.title("📞 Sistema de Marcación Masiva")

# --- GESTIÓN DE ESTADO ---
if 'df_contactos' not in st.session_state:
    st.session_state.df_contactos = None

# --- CARGA DE ARCHIVO ---
st.sidebar.header("1. Carga de Datos")
uploaded_file = st.sidebar.file_uploader("Subir clientes.csv", type="csv")

if uploaded_file and st.session_state.df_contactos is None:
    # utf-8-sig limpia caracteres raros de Excel
    df = pd.read_csv(uploaded_file, sep=None, engine='python', encoding='utf-8-sig')
    
    # Limpieza estricta de columnas
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    # Aseguramos la existencia de todas las columnas necesarias para el reporte
    columnas_reporte = {
        'estado': 'Pendiente',
        'observacion': '',
        'fecha_llamada': '',
        'hora_inicio': '',
        'sid_llamada': '',
        'enlace_grabacion': '',
        'caller_id_usado': twilio_number
    }
    
    for col, val in columnas_reporte.items():
        if col not in df.columns:
            df[col] = val
    
    st.session_state.df_contactos = df

# --- LÓGICA DE TRABAJO ---
if st.session_state.df_contactos is not None:
    df_actual = st.session_state.df_contactos
    
    # Filtramos por el estado
    pendientes = df_actual[df_actual['estado'] == 'Pendiente']
    realizadas = df_actual[df_actual['estado'] == 'Llamado']

    # Métricas superiores
    c1, c2, c3 = st.columns(3)
    c1.metric("Pendientes", len(pendientes))
    c2.metric("Realizadas", len(realizadas))
    c3.metric("Total Archivo", len(df_actual))

    # --- SECCIÓN DE DESCARGAS ---
    st.sidebar.header("2. Reportes CSV")
    if not realizadas.empty:
        csv_realizadas = realizadas.to_csv(index=False).encode('utf-8-sig')
        st.sidebar.download_button("✅ Descargar Reporte Realizadas", csv_realizadas, "reporte_exitosas.csv", "text/csv")

    if not pendientes.empty:
        csv_pendientes = pendientes.to_csv(index=False).encode('utf-8-sig')
        st.sidebar.download_button("⏳ Descargar Lista Faltante", csv_pendientes, "lista_pendientes.csv", "text/csv")

    st.write("---")

    # --- PANEL DE MARCACIÓN ---
    if not pendientes.empty:
        # Extraemos el primer pendiente
        idx = pendientes.index[0]
        proximo = pendientes.loc[idx]

        # Limpieza de número
        pais = str(proximo['codigo_pais']).strip()
        tel = str(proximo['telefono']).strip()
        if not pais.startswith('+'): pais = f"+{pais}"
        num_final = f"{pais}{tel}"

        with st.container(border=True):
            col_info, col_btn = st.columns([2, 1])
            with col_info:
                st.subheader(f"👤 Contacto: {proximo['nombre']}")
                st.info(f"📞 Marcando a: **{num_final}**")
                # El campo de nota es opcional
                nota_input = st.text_area("Notas de la llamada:", key=f"nota_{idx}", placeholder="Ej: Interesado / Buzón / No contestó")

            with col_btn:
                st.write("### Acción")
                if st.button("🚀 INICIAR LLAMADA", key=f"call_{idx}", use_container_width=True, type="primary"):
                    try:
                        ahora = datetime.now()
                        call = client.calls.create(
                            url=function_url,
                            to=num_final,
                            from_=twilio_number,
                            record=True
                        )
                        
                        # Guardar datos en el DataFrame original usando el índice real
                        st.session_state.df_contactos.at[idx, 'estado'] = 'Llamado'
                        st.session_state.df_contactos.at[idx, 'observacion'] = nota_input
                        st.session_state.df_contactos.at[idx, 'fecha_llamada'] = ahora.strftime("%Y-%m-%d")
                        st.session_state.df_contactos.at[idx, 'hora_inicio'] = ahora.strftime("%H:%M:%S")
                        st.session_state.df_contactos.at[idx, 'sid_llamada'] = call.sid
                        st.session_state.df_contactos.at[idx, 'enlace_grabacion'] = f"https://console.twilio.com/us1/monitor/logs/calls/{call.sid}"
                        
                        st.success("Llamada enviada...")
                        st.rerun() 
                    except Exception as e:
                        st.error(f"Error Twilio: {e}")
    else:
        st.balloons()
        st.success("✅ ¡Jornada terminada!")

    # Vista previa segura: solo columnas que sabemos que existen
    if not realizadas.empty:
        with st.expander("🔍 Últimas llamadas realizadas"):
            st.dataframe(realizadas.tail(10))

else:
    st.info("👈 Sube el archivo CSV para cargar los contactos.")
