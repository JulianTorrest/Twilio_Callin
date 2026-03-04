import streamlit as st
import pandas as pd
from twilio.rest import Client

st.set_page_config(page_title="Twilio Outbound Dialer", page_icon="📞")

st.title("📞 Panel de Llamadas - Colombia")

# 1. Configurar credenciales mediante Secrets de Streamlit
try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets.get("TWILIO_NUMBER", "+17068069672")
    function_url = st.secrets["TWILIO_FUNCTION_URL"]
    
    client = Client(account_sid, auth_token)
except KeyError:
    st.error("⚠️ Faltan las credenciales en los Secrets de Streamlit.")
    st.stop()

# 2. Cargar lista de clientes
st.sidebar.header("Configuración")
uploaded_file = st.sidebar.file_uploader("Carga tu archivo clientes.csv", type="csv")

if uploaded_file:
    # Leer el CSV con las nuevas columnas
    df = pd.read_csv(uploaded_file)
    
    st.write(f"### Lista de Contactos ({len(df)} registros)")

    # Mostrar la interfaz de llamadas
    for index, row in df.iterrows():
        # --- LÓGICA DE UNIÓN Y LIMPIEZA ---
        pais = str(row['codigo_pais']).strip()
        tel = str(row['telefono']).strip()
        
        # Agregamos el '+' si no existe
        if not pais.startswith('+'):
            pais = f"+{pais}"
            
        numero_completo = f"{pais}{tel}"
        # ---------------------------------

        with st.container():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**👤 {row['nombre']}**")
                st.caption(f"📞 {numero_completo}")
            with col2:
                if st.button("Llamar", key=f"btn_{index}", use_container_width=True):
                    try:
                        call = client.calls.create(
                            url=function_url,
                            to=numero_completo,
                            from_=twilio_number,
                            record=True,
                            machine_detection='Enable'
                        )
                        st.success(f"Llamada iniciada")
                        st.toast(f"SID: {call.sid}")
                    except Exception as e:
                        st.error(f"Error al llamar: {e}")
            st.divider()
else:
    st.warning("👈 Por favor, carga un archivo CSV con columnas: nombre, codigo_pais, telefono.")
