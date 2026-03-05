import streamlit as st
import pandas as pd
from twilio.rest import Client
from datetime import datetime
import io
import time

st.set_page_config(page_title="Dialer Pro - Colombia", page_icon="📞", layout="wide")

# --- CONFIGURACIÓN DE TWILIO ---
try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets.get("TWILIO_NUMBER", "+17068069672")
    function_url = st.secrets["TWILIO_FUNCTION_URL"]
    # URL base de tu formulario (opcional)
    forms_base_url = st.secrets.get("MS_FORMS_URL", "https://forms.office.com/r/tu_codigo")
    
    client = Client(account_sid, auth_token)
except KeyError:
    st.error("⚠️ Configura los Secrets en Streamlit Cloud.")
    st.stop()

st.title("📞 Centro de Llamadas Inteligente")

# --- GESTIÓN DE ESTADO ---
if 'df_contactos' not in st.session_state:
    st.session_state.df_contactos = None
if 'llamada_activa_sid' not in st.session_state:
    st.session_state.llamada_activa_sid = None

# --- CARGA DE ARCHIVO ---
st.sidebar.header("1. Carga de Datos")
uploaded_file = st.sidebar.file_uploader("Subir clientes.csv", type="csv")

if uploaded_file and st.session_state.df_contactos is None:
    df = pd.read_csv(uploaded_file, sep=None, engine='python', encoding='utf-8-sig')
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    columnas_reporte = {
        'estado': 'Pendiente',
        'observacion': '',
        'fecha_llamada': '',
        'hora_inicio': '',
        'sid_llamada': '',
        'url_formulario_enviado': '', # Para rastrear el link generado
        'caller_id_usado': twilio_number
    }
    for col, val in columnas_reporte.items():
        if col not in df.columns: df[col] = val
    st.session_state.df_contactos = df

# --- LÓGICA DE TRABAJO ---
if st.session_state.df_contactos is not None:
    df_actual = st.session_state.df_contactos
    pendientes = df_actual[df_actual['estado'] == 'Pendiente']
    realizadas = df_actual[df_actual['estado'] == 'Llamado']

    # --- BARRA LATERAL: REPORTES ---
    st.sidebar.header("2. Reportes CSV")
    if not realizadas.empty:
        csv_realizadas = realizadas.to_csv(index=False).encode('utf-8-sig')
        st.sidebar.download_button("✅ Descargar Realizadas", csv_realizadas, "reporte_exitosas.csv")

    st.write("---")

    # --- PANEL CENTRAL ---
    if not pendientes.empty:
        idx = pendientes.index[0]
        proximo = pendientes.loc[idx]

        # Formateo de número
        pais = str(proximo['codigo_pais']).strip().replace('+', '')
        num_final = f"+{pais}{str(proximo['telefono']).strip()}"

        with st.container(border=True):
            col_info, col_status = st.columns([2, 1])
            
            with col_info:
                st.subheader(f"👤 Cliente: {proximo['nombre']}")
                st.write(f"📞 Número: **{num_final}**")
                nota_input = st.text_area("Notas internas:", key=f"nota_{idx}")

            with col_status:
                # LÓGICA DE ESTADOS VISUALES
                if st.session_state.llamada_activa_sid is None:
                    st.write("### 🟢 Disponible")
                    if st.button("🚀 INICIAR LLAMADA", key=f"call_{idx}", use_container_width=True, type="primary"):
                        try:
                            ahora = datetime.now()
                            call = client.calls.create(url=function_url, to=num_final, from_=twilio_number, record=True)
                            
                            st.session_state.llamada_activa_sid = call.sid
                            st.session_state.df_contactos.at[idx, 'sid_llamada'] = call.sid
                            st.session_state.df_contactos.at[idx, 'fecha_llamada'] = ahora.strftime("%Y-%m-%d")
                            st.session_state.df_contactos.at[idx, 'hora_inicio'] = ahora.strftime("%H:%M:%S")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                else:
                    st.write("### 🔴 EN LLAMADA")
                    st.warning("La llamada está en curso...")
                    
                    # 1. BOTÓN FINALIZAR
                    if st.button("⏹️ FINALIZAR LLAMADA", key="hangup", use_container_width=True):
                        try:
                            client.calls(st.session_state.llamada_activa_sid).update(status='completed')
                            st.session_state.llamada_activa_sid = None
                            st.session_state.df_contactos.at[idx, 'estado'] = 'Llamado'
                            st.session_state.df_contactos.at[idx, 'observacion'] = nota_input
                            
                            # 2. GENERAR LINK DE FORMULARIO (Ejemplo pasando el SID)
                            link_forms = f"{forms_base_url}?sid={proximo['sid_llamada']}&cliente={proximo['nombre']}"
                            st.session_state.df_contactos.at[idx, 'url_formulario_enviado'] = link_forms
                            
                            st.success("Llamada terminada.")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.session_state.llamada_activa_sid = None
                            st.rerun()

                    # 3. LINK AL FORMULARIO
                    link_dinamico = f"{forms_base_url}?id={st.session_state.llamada_activa_sid}"
                    st.markdown(f"[📝 Abrir Formulario Microsoft]({link_dinamico})")

    else:
        st.success("✅ ¡Jornada terminada!")

else:
    st.info("👈 Sube el archivo CSV para comenzar.")
