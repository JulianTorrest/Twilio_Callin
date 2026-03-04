import streamlit as st
import pandas as pd
from twilio.rest import Client
import io

st.set_page_config(page_title="Dialer Profesional", page_icon="📞", layout="wide")

# --- CONFIGURACIÓN DE TWILIO ---
try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets.get("TWILIO_NUMBER", "+17068069672")
    function_url = st.secrets["TWILIO_FUNCTION_URL"]
    client = Client(account_sid, auth_token)
except KeyError:
    st.error("⚠️ Faltan credenciales en Secrets.")
    st.stop()

st.title("📞 Gestión de Llamadas en Lote")

# --- GESTIÓN DE ESTADO (Session State) ---
if 'df_contactos' not in st.session_state:
    st.session_state.df_contactos = None
if 'llamados' not in st.session_state:
    st.session_state.llamados = []

# --- CARGA DE ARCHIVO ---
st.sidebar.header("Administración")
uploaded_file = st.sidebar.file_uploader("Cargar clientes.csv", type="csv")

if uploaded_file and st.session_state.df_contactos is None:
    df = pd.read_csv(uploaded_file, sep=None, engine='python', encoding='utf-8-sig')
    df.columns = df.columns.str.strip().str.lower()
    # Añadimos columna de estado si no existe
    df['estado'] = 'Pendiente'
    st.session_state.df_contactos = df

# --- LÓGICA DE INTERFAZ ---
if st.session_state.df_contactos is not None:
    df = st.session_state.df_contactos
    
    # Separar contactos
    pendientes = df[df['estado'] == 'Pendiente']
    completados = df[df['estado'] == 'Llamado']

    col_stats1, col_stats2, col_stats3 = st.columns(3)
    col_stats1.metric("Pendientes", len(pendientes))
    col_stats2.metric("Completados", len(completados))
    
    # BOTÓN PARA DESCARGAR RESTANTES
    if len(pendientes) > 0:
        csv_restante = pendientes.to_csv(index=False).encode('utf-8')
        st.sidebar.download_button(
            label="📥 Descargar Pendientes (CSV)",
            data=csv_restante,
            file_name="contactos_restantes.csv",
            mime="text/csv"
        )

    st.write("---")

    # MOSTRAR SOLO PENDIENTES
    if not pendientes.empty:
        st.subheader("📋 Lista de Trabajo (Siguiente cliente)")
        # Solo mostramos los primeros 5 para no saturar el navegador con 300
        for index, row in pendientes.head(10).iterrows():
            pais = str(row['codigo_pais']).strip()
            tel = str(row['telefono']).strip()
            if not pais.startswith('+'): pais = f"+{pais}"
            numero_completo = f"{pais}{tel}"

            with st.expander(f"👤 {row['nombre']} - {numero_completo}", expanded=True):
                c1, c2 = st.columns([3, 1])
                c1.write(f"Preparado para marcar a {row['nombre']}")
                if c2.button("📞 Iniciar Llamada", key=f"btn_{index}", use_container_width=True):
                    try:
                        call = client.calls.create(
                            url=function_url,
                            to=numero_completo,
                            from_=twilio_number,
                            record=True
                        )
                        # ACTUALIZAR ESTADO
                        st.session_state.df_contactos.at[index, 'estado'] = 'Llamado'
                        st.success(f"Llamando a {row['nombre']}...")
                        st.rerun() # Refresca la pantalla para que desaparezca
                    except Exception as e:
                        st.error(f"Error: {e}")
    else:
        st.balloons()
        st.success("¡Felicidades! Has terminado la lista del día.")

    # SECCIÓN DE HISTORIAL (Opcional, abajo)
    if not completados.empty:
        with st.sidebar.expander("✅ Historial de hoy"):
            st.write(completados[['nombre', 'telefono']])

else:
    st.info("👈 Por favor, carga el archivo CSV para empezar a trabajar.")
