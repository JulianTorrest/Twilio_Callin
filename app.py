import streamlit as st
import pandas as pd
from twilio.rest import Client
from datetime import datetime
import io
import time

st.set_page_config(page_title="Dialer Pro - Colombia", page_icon="📞", layout="wide")

# --- 1. CONFIGURACIÓN DE TWILIO Y SECRETS ---
try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets.get("TWILIO_NUMBER", "+17068069672")
    function_url = st.secrets["TWILIO_FUNCTION_URL"]
    # URL base de tu formulario de Microsoft
    forms_base_url = st.secrets.get("MS_FORMS_URL", "https://forms.office.com/r/tu_codigo")
    
    client = Client(account_sid, auth_token)
except KeyError:
    st.error("⚠️ Configura los Secrets (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FUNCTION_URL, MS_FORMS_URL) en Streamlit Cloud.")
    st.stop()

st.title("📞 Centro de Llamadas Inteligente")

# --- 2. GESTIÓN DE ESTADO (SESSION STATE) ---
if 'df_contactos' not in st.session_state:
    st.session_state.df_contactos = None
if 'llamada_activa_sid' not in st.session_state:
    st.session_state.llamada_activa_sid = None

# --- 3. CARGA Y LIMPIEZA DE ARCHIVO ---
st.sidebar.header("1. Administración")
uploaded_file = st.sidebar.file_uploader("Cargar clientes.csv", type="csv")

if uploaded_file and st.session_state.df_contactos is None:
    # utf-8-sig para compatibilidad con Excel
    df = pd.read_csv(uploaded_file, sep=None, engine='python', encoding='utf-8-sig')
    
    # Limpieza estricta: minúsculas y sin espacios
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    # Columnas de métricas y control (sin borrar las originales)
    columnas_extra = {
        'estado': 'Pendiente',
        'observacion': '',
        'fecha_llamada': '',
        'hora_inicio': '',
        'sid_llamada': '',
        'enlace_grabacion': '',
        'url_formulario_enviado': '',
        'caller_id_usado': twilio_number
    }
    
    for col, val in columnas_extra.items():
        if col not in df.columns:
            df[col] = val
            
    st.session_state.df_contactos = df

# --- 4. LÓGICA DE INTERFAZ Y TRABAJO ---
if st.session_state.df_contactos is not None:
    df_actual = st.session_state.df_contactos
    pendientes = df_actual[df_actual['estado'] == 'Pendiente']
    realizadas = df_actual[df_actual['estado'] == 'Llamado']

    # Métricas superiores
    c1, c2, c3 = st.columns(3)
    c1.metric("Pendientes", len(pendientes))
    c2.metric("Realizadas", len(realizadas))
    c3.metric("Total Diario", len(df_actual))

    # --- DESCARGAS EN BARRA LATERAL ---
    st.sidebar.header("2. Descargar Reportes")
    if not realizadas.empty:
        csv_real = realizadas.to_csv(index=False).encode('utf-8-sig')
        st.sidebar.download_button("✅ Descargar Realizadas (CSV)", csv_real, "reporte_llamadas.csv", "text/csv")
    
    if not pendientes.empty:
        csv_pend = pendientes.to_csv(index=False).encode('utf-8-sig')
        st.sidebar.download_button("⏳ Descargar Pendientes (CSV)", csv_pend, "lista_restante.csv", "text/csv")

    st.write("---")

    # --- PANEL DE MARCACIÓN ---
    if not pendientes.empty:
        # Siempre tomamos el primero de la lista de pendientes
        idx = pendientes.index[0]
        proximo = pendientes.loc[idx]

        # Formateo de número (unión de columnas)
        pais = str(proximo['codigo_pais']).strip().replace('+', '')
        tel = str(proximo['telefono']).strip()
        num_final = f"+{pais}{tel}"

        with st.container(border=True):
            col_info, col_ctrl = st.columns([2, 1])
            
            with col_info:
                st.subheader(f"👤 Cliente: {proximo['nombre']}")
                st.info(f"📞 Marcando: **{num_final}**")
                nota_input = st.text_area("Notas / Observaciones:", key=f"nota_{idx}", placeholder="Escribe aquí el resultado de la llamada...")

            with col_ctrl:
                # Si NO hay una llamada activa, mostramos el botón de iniciar
                if st.session_state.llamada_activa_sid is None:
                    st.write("### 🟢 Estado: Listo")
                    if st.button("🚀 INICIAR LLAMADA", key=f"btn_start_{idx}", use_container_width=True, type="primary"):
                        try:
                            ahora = datetime.now()
                            call = client.calls.create(
                                url=function_url,
                                to=num_final,
                                from_=twilio_number,
                                record=True
                            )
                            # Guardamos SID en el estado temporal y en el DF
                            st.session_state.llamada_activa_sid = call.sid
                            st.session_state.df_contactos.at[idx, 'sid_llamada'] = call.sid
                            st.session_state.df_contactos.at[idx, 'fecha_llamada'] = ahora.strftime("%Y-%m-%d")
                            st.session_state.df_contactos.at[idx, 'hora_inicio'] = ahora.strftime("%H:%M:%S")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error Twilio: {e}")
                
                # Si HAY una llamada activa, mostramos botón de finalizar y link a Forms
                else:
                    st.write("### 🔴 Estado: EN LLAMADA")
                    st.warning("No cierres la app hasta finalizar.")
                    
                    # Link dinámico a Microsoft Forms con parámetros
                    id_call = st.session_state.llamada_activa_sid
                    link_forms = f"{forms_base_url}?id_llamada={id_call}&cliente={proximo['nombre']}"
                    
                    st.markdown(f"### [📝 LLENAR FORMULARIO]({link_forms})")
                    
                    if st.button("⏹️ FINALIZAR LLAMADA", key="btn_hangup", use_container_width=True, type="secondary"):
                        try:
                            # 1. Cortar llamada en Twilio
                            client.calls(id_call).update(status='completed')
                            
                            # 2. Actualizar registro final
                            st.session_state.df_contactos.at[idx, 'estado'] = 'Llamado'
                            st.session_state.df_contactos.at[idx, 'observacion'] = nota_input
                            st.session_state.df_contactos.at[idx, 'enlace_grabacion'] = f"https://console.twilio.com/us1/monitor/logs/calls/{id_call}"
                            st.session_state.df_contactos.at[idx, 'url_formulario_enviado'] = link_forms
                            
                            # 3. Limpiar estado de llamada activa y refrescar
                            st.session_state.llamada_activa_sid = None
                            st.success("Llamada finalizada correctamente.")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al colgar: {e}")
                            # Si falla porque ya colgaron, limpiamos el estado igual
                            st.session_state.llamada_activa_sid = None
                            st.rerun()

    else:
        st.balloons()
        st.success("✅ ¡Has terminado con todos los contactos del archivo!")

    # Vista previa de las últimas 5 llamadas realizadas hoy
    if not realizadas.empty:
        with st.expander("🔍 Historial reciente (últimas 5)"):
            st.table(realizadas[['nombre', 'telefono', 'hora_inicio', 'observacion']].tail(5))

else:
    st.info("👈 Por favor, carga el archivo clientes.csv para iniciar la sesión de llamadas.")
