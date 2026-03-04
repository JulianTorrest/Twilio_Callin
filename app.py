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
    df = pd.read_csv(uploaded_file, sep=None, engine='python', encoding='utf-8-sig')
    df.columns = df.columns.str.strip().str.lower()
    
    # AGREGAMOS TODAS LAS COLUMNAS DE MÉTRICAS
    df['estado'] = 'Pendiente'
    df['observacion'] = ''
    df['fecha_llamada'] = ''
    df['hora_inicio'] = ''
    df['sid_llamada'] = ''
    df['enlace_grabacion'] = ''
    df['caller_id_usado'] = twilio_number
    
    st.session_state.df_contactos = df

# --- LÓGICA DE TRABAJO ---
if st.session_state.df_contactos is not None:
    df = st.session_state.df_contactos
    pendientes = df[df['estado'] == 'Pendiente']
    realizadas = df[df['estado'] == 'Llamado']

    # Métricas superiores
    c1, c2, c3 = st.columns(3)
    c1.metric("Pendientes", len(pendientes))
    c2.metric("Realizadas", len(realizadas))
    c3.metric("Total Archivo", len(df))

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
        proximo = pendientes.iloc[0]
        idx = pendientes.index[0]

        pais = str(proximo['codigo_pais']).strip()
        tel = str(proximo['telefono']).strip()
        if not pais.startswith('+'): pais = f"+{pais}"
        num_final = f"{pais}{tel}"

        with st.container(border=True):
            col_info, col_btn = st.columns([2, 1])
            with col_info:
                st.subheader(f"👤 Contacto: {proximo['nombre']}")
                st.info(f"📞 Marcando a: **{num_final}**")
                nota = st.text_area("Notas de la llamada:", key=f"nota_{idx}", placeholder="Ej: No contestó, cliente interesado, buzón de voz...")

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
                        
                        # Guardamos toda la información posible
                        st.session_state.df_contactos.at[idx, 'estado'] = 'Llamado'
                        st.session_state.df_contactos.at[idx, 'observacion'] = nota
                        st.session_state.df_contactos.at[idx, 'fecha_llamada'] = ahora.strftime("%Y-%m-%d")
                        st.session_state.df_contactos.at[idx, 'hora_inicio'] = ahora.strftime("%H:%M:%S")
                        st.session_state.df_contactos.at[idx, 'sid_llamada'] = call.sid
                        # Generamos el enlace de grabación estándar de Twilio
                        st.session_state.df_contactos.at[idx, 'enlace_grabacion'] = f"https://console.twilio.com/us1/monitor/logs/calls/{call.sid}"
                        
                        st.success("Llamada enviada a Twilio")
                        st.rerun() 
                    except Exception as e:
                        st.error(f"Error: {e}")
    else:
        st.balloons()
        st.success("✅ ¡Jornada terminada!")

    # Vista previa del reporte en la App
    with st.expander("🔍 Vista previa del reporte actual"):
        st.table(realizadas[['nombre', 'telefono', 'hora_inicio', 'observacion']].tail(5))

else:
    st.info("👈 Sube el archivo CSV para cargar los 300 contactos.")
