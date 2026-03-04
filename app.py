import streamlit as st
import pandas as pd
from twilio.rest import Client
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

st.title(" Gestión de Llamadas")

# --- GESTIÓN DE ESTADO ---
if 'df_contactos' not in st.session_state:
    st.session_state.df_contactos = None

# --- CARGA DE ARCHIVO ---
st.sidebar.header("1. Carga de Datos")
uploaded_file = st.sidebar.file_uploader("Subir clientes.csv", type="csv")

if uploaded_file and st.session_state.df_contactos is None:
    df = pd.read_csv(uploaded_file, sep=None, engine='python', encoding='utf-8-sig')
    df.columns = df.columns.str.strip().str.lower()
    df['estado'] = 'Pendiente'
    df['observacion'] = ''
    df['sid_llamada'] = 'N/A'
    st.session_state.df_contactos = df

# --- LÓGICA DE TRABAJO ---
if st.session_state.df_contactos is not None:
    df = st.session_state.df_contactos
    pendientes = df[df['estado'] == 'Pendiente']
    realizadas = df[df['estado'] == 'Llamado']

    # Métricas visuales
    c1, c2, c3 = st.columns(3)
    c1.metric("Pendientes", len(pendientes))
    c2.metric("Realizadas", len(realizadas))
    c3.metric("Total", len(df))

    # --- SECCIÓN DE DESCARGAS (2 ARCHIVOS CSV) ---
    st.sidebar.header("2. Descargar Reportes")
    
    if not realizadas.empty:
        csv_realizadas = realizadas.to_csv(index=False).encode('utf-8-sig')
        st.sidebar.download_button(
            label="✅ Descargar Llamadas Realizadas",
            data=csv_realizadas,
            file_name="llamadas_realizadas.csv",
            mime="text/csv"
        )

    if not pendientes.empty:
        csv_pendientes = pendientes.to_csv(index=False).encode('utf-8-sig')
        st.sidebar.download_button(
            label="⏳ Descargar Pendientes",
            data=csv_pendientes,
            file_name="llamadas_pendientes.csv",
            mime="text/csv"
        )

    st.write("---")

    # --- INTERFAZ DE LLAMADA (UNO A LA VEZ) ---
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
                st.subheader(f"👤 {proximo['nombre']}")
                st.write(f"📞 **Número:** {num_final}")
                
                # Campo de observación para el reporte
                nota = st.text_input("Añadir nota/observación:", key=f"nota_{idx}", placeholder="Ej: No contestó / Interesado")

            with col_btn:
                st.write(" ") # Espaciador
                if st.button("📞 INICIAR LLAMADA", key=f"call_{idx}", use_container_width=True, type="primary"):
                    try:
                        call = client.calls.create(
                            url=function_url,
                            to=num_final,
                            from_=twilio_number,
                            record=True
                        )
                        # Actualizamos datos
                        st.session_state.df_contactos.at[idx, 'estado'] = 'Llamado'
                        st.session_state.df_contactos.at[idx, 'observacion'] = nota
                        st.session_state.df_contactos.at[idx, 'sid_llamada'] = call.sid
                        
                        st.success(f"Llamando...")
                        st.rerun() 
                    except Exception as e:
                        st.error(f"Error: {e}")
    else:
        st.balloons()
        st.success("✅ ¡Lista completada! No olvides descargar tus reportes en la barra lateral.")

else:
    st.info("👈 Carga el archivo CSV para comenzar la jornada.")
