import streamlit as st
import pandas as pd
from twilio.rest import Client

st.set_page_config(page_title="Twilio Outbound Dialer", page_icon="📞")

st.title("📞 Panel de Llamadas - Colombia")

# 1. Configurar credenciales mediante Secrets de Streamlit
# Esto evita que tus llaves se filtren en GitHub
try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    # El número de Twilio también puede ser un secret para mayor flexibilidad
    twilio_number = st.secrets.get("TWILIO_NUMBER", "+17068069672")
    # La URL de tu Function
    function_url = st.secrets["TWILIO_FUNCTION_URL"]
    
    client = Client(account_sid, auth_token)
except KeyError:
    st.error("⚠️ Faltan las credenciales en los Secrets de Streamlit. Por favor, configúralas en el dashboard.")
    st.stop()

# 2. Cargar lista de clientes
st.sidebar.header("Configuración")
uploaded_file = st.sidebar.file_uploader("Carga tu archivo clientes.csv", type="csv")

if uploaded_file:
    # Leer el CSV (asegúrate de que tenga las columnas 'name' y 'phone_number')
    df = pd.read_csv(uploaded_file)
    
    st.write(f"### Lista de Contactos ({len(df)} registros)")
    st.info("Al presionar 'Llamar', Twilio marcará al cliente y activará la grabación automáticamente.")

    # Mostrar la interfaz de llamadas
    for index, row in df.iterrows():
        with st.container():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**👤 {row['name']}**")
                st.caption(f"📞 {row['phone_number']}")
            with col2:
                # El botón usa el índice para ser único
                if st.button("Llamar", key=f"btn_{index}", use_container_width=True):
                    try:
                        call = client.calls.create(
                            url=function_url,
                            to=row['phone_number'],
                            from_=twilio_number,
                            record=True,
                            machine_detection='Enable' # Para tus métricas de Humano/Máquina
                        )
                        st.success(f"Llamada iniciada")
                        st.toast(f"SID: {call.sid}")
                    except Exception as e:
                        st.error(f"Error al llamar: {e}")
            st.divider()
else:
    st.warning("👈 Por favor, carga un archivo CSV desde la barra lateral para comenzar.")
    st.image("https://img.icons8.com/clouds/200/000000/phone-office.png", width=200)
