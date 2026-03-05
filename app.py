import streamlit as st
import pandas as pd
from twilio.rest import Client
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection
import time
import urllib.parse
import plotly.express as px

# --- CONFIGURACION DE PAGINA ---
st.set_page_config(page_title="Camacol Dialer Pro v4.5 - Enhanced", layout="wide")

st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 10px; border-radius: 10px; border: 1px solid #e1e4e8; }
    .client-card { background-color: #f0f2f6; padding: 15px; border-radius: 15px; border-left: 8px solid #003366; margin-bottom: 15px; }
    .log-box { font-family: monospace; font-size: 0.8rem; background: #1e1e1e; color: #4af626; padding: 10px; border-radius: 5px; height: 180px; overflow-y: auto; }
    .latency-green { height: 10px; width: 10px; background-color: #28a745; border-radius: 50%; display: inline-block; }
    .latency-red { height: 10px; width: 10px; background-color: #dc3545; border-radius: 50%; display: inline-block; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. CONEXIONES ---
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
    st.error(f"Error de configuración: {e}")
    st.stop()

# --- 2. AUDITORIA AUTOMATICA ---
if 'logs' not in st.session_state: st.session_state.logs = []

def add_log(mensaje, tipo="INFO"):
    t_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{t_stamp} | {st.session_state.get('agente_id', 'SYS')} | {tipo} | {mensaje}"
    st.session_state.logs.append(entry)
    if URL_SHEET_INFORME:
        try:
            df_logs = pd.DataFrame([l.split(" | ") for l in st.session_state.logs], columns=['Fecha', 'Agente', 'Tipo', 'Evento'])
            conn.update(spreadsheet=URL_SHEET_INFORME, worksheet="Auditoria_Logs", data=df_logs)
        except Exception as e_log:
            print(f"Error guardando log en Sheet: {e_log}")

# --- 3. CONTROL DE ACCESO Y ESTADO ---
if 'agente_id' not in st.session_state:
    with st.form("login"):
        ced = st.text_input("Cédula:", type="password").strip()
        if st.form_submit_button("Entrar"):
            if ced in CEDULAS_AUTORIZADAS:
                st.session_state.agente_id = ced
                add_log("LOGIN_EXITOSO", "AUTH")
                st.rerun()
    st.stop()

# Inicialización explícita de estados (Mantenemos cada uno de tus estados)
if 'df_contactos' not in st.session_state: st.session_state.df_contactos = None
if 'en_pausa' not in st.session_state: st.session_state.en_pausa = False
if 'draft_notas' not in st.session_state: st.session_state.draft_notas = {}
if 'meta_diaria' not in st.session_state: st.session_state.meta_diaria = 50
if 'llamada_activa_sid' not in st.session_state: st.session_state.llamada_activa_sid = None
if 't_inicio_dt' not in st.session_state: st.session_state.t_inicio_dt = None

# --- 4. SIDEBAR (FUNCIONALIDADES COMPLETAS) ---
with st.sidebar:
    st.header(f"Agente: {st.session_state.agente_id}")
    
    if not st.session_state.en_pausa:
        if st.button("☕ Iniciar Pausa"):
            st.session_state.en_pausa = True
            st.session_state.pausa_inicio = datetime.now()
            add_log("INICIO_PAUSA", "ESTADO")
            st.rerun()
    else:
        st.warning("EN PAUSA")
        if st.button("✅ Volver"):
            st.session_state.en_pausa = False
            add_log("FIN_PAUSA", "ESTADO")
            st.rerun()

    st.divider()
    up_file = st.file_uploader("Cargar Base", type="csv")
    if up_file and st.session_state.df_contactos is None:
        df_up = pd.read_csv(up_file, sep=None, engine='python', encoding='utf-8-sig')
        df_up.columns = [str(c).strip().lower() for c in df_up.columns]
        for col in ['estado', 'observacion', 'fecha_llamada', 'duracion_seg', 'sid_llamada', 'proxima_llamada', 'agente_id']:
            if col not in df_up.columns: df_up[col] = 'Pendiente' if col == 'estado' else ''
        st.session_state.df_contactos = df_up
        add_log("BASE_CARGADA", "DATA")

    if st.session_state.df_contactos is not None:
        df_pend = st.session_state.df_contactos[st.session_state.df_contactos['estado'].isin(['Pendiente', 'No Contesto'])]
        st.download_button("📥 Descargar Pendientes", df_pend.to_csv(index=False).encode('utf-8-sig'), "pendientes.csv")

    if st.button("Cerrar Sesión"):
        add_log("LOGOUT", "AUTH")
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()

# --- 5. MODULO DE METRICAS Y DASHBOARDS ---
st.title("Dialer Pro Camacol")

try:
    # Leemos con bypass de cache para ver actualizaciones inmediatas
    df_historico = conn.read(spreadsheet=URL_SHEET_INFORME, worksheet="0", ttl=0)
except:
    df_historico = pd.DataFrame()

tab_op, tab_met, tab_sup, tab_aud = st.tabs(["📞 Operación", "📊 Mis Métricas", "👤 Supervisor", "📜 Auditoría"])

with tab_met:
    st.subheader("Rendimiento del Agente")
    if not df_historico.empty:
        # Aseguramos que la columna agente_id existe para filtrar
        if 'agente_id' in df_historico.columns:
            df_agente = df_historico[df_historico['agente_id'].astype(str) == str(st.session_state.agente_id)]
            if not df_agente.empty:
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Gestionados", len(df_agente))
                m2.metric("Efectividad", f"{(len(df_agente[df_agente['estado']=='Llamado'])/len(df_agente)*100):.1f}%")
                m3.metric("Promedio Duración", f"{pd.to_numeric(df_agente['duracion_seg'], errors='coerce').mean():.1f}s")
                st.plotly_chart(px.pie(df_agente, names='estado', title="Distribución de Estados"), use_container_width=True)
            else:
                st.info(f"No hay registros en el Sheet para el agente {st.session_state.agente_id}.")
        else:
            st.error("La columna 'agente_id' no se encuentra en el Sheet de informe.")
    else:
        st.warning("No hay datos en el Sheet de informe.")

with tab_sup:
    if st.session_state.agente_id == "12345678":
        st.subheader("Panel de Control Gerencial")
        if not df_historico.empty:
            st.write("Resumen por Agente Humano:")
            resumen_sup = df_historico.groupby(['agente_id', 'estado']).size().unstack(fill_value=0)
            st.dataframe(resumen_sup, use_container_width=True)
            st.plotly_chart(px.bar(df_historico, x='agente_id', color='estado', title="Productividad por Cédula"), use_container_width=True)
    else:
        st.error("Acceso restringido a Supervisores.")

with tab_aud:
    st.markdown(f"<div class='log-box'>{'<br>'.join(st.session_state.logs[::-1])}</div>", unsafe_allow_html=True)

# --- 6. OPERACIÓN (BLOQUE EXPANDIDO Y REFORZADO) ---
with tab_op:
    if st.session_state.df_contactos is not None:
        search = st.text_input("🔍 Buscar Cliente:").lower()
        df = st.session_state.df_contactos
        
        opc = st.radio("Ver:", ["Pendientes", "No Contestaron", "Programadas"], horizontal=True)
        # Lógica de mapeo de pestaña a estado del DF
        f_est = "Pendiente" if "Pendientes" in opc else "No Contesto" if "No Contestaron" in opc else "Programada"
        
        # Filtrado riguroso
        df_work = df[df['estado'] == f_est]
        if search:
            df_work = df_work[df_work['nombre'].str.lower().str.contains(search) | df_work['telefono'].astype(str).str.contains(search)]

        if not df_work.empty:
            idx = df_work.index[0]
            c = df_work.loc[idx]
            tel = f"+{str(c['codigo_pais']).replace('+', '')}{str(c['telefono'])}"

            col1, col2 = st.columns([2,1])
            with col1:
                st.markdown(f"<div class='client-card'><h3>{c['nombre']}</h3><p>Tel: {tel}</p></div>", unsafe_allow_html=True)
                val_n = st.session_state.draft_notas.get(idx, c['observacion'])
                nota = st.text_area("Notas:", value=val_n, key=f"n_{idx}")
                st.session_state.draft_notas[idx] = nota

            with col2:
                if not st.session_state.en_pausa:
                    if st.session_state.llamada_activa_sid is None:
                        if st.button("📞 LLAMAR", type="primary"):
                            try:
                                call = client.calls.create(url=function_url, to=tel, from_=twilio_number, machine_detection='Enable')
                                st.session_state.llamada_activa_sid = call.sid
                                st.session_state.t_inicio_dt = datetime.now()
                                add_log(f"CALL_START: {c['nombre']}", "TWILIO")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al iniciar llamada: {e}")
                    else:
                        # --- MONITOR DINÁMICO CON REFUERZO DE GUARDADO ---
                        try:
                            # 1. Consultar estado real en Twilio
                            remote = client.calls(st.session_state.llamada_activa_sid).fetch()
                            st.info(f"Estado Twilio: {remote.status}")
                            
                            # 2. Definir condiciones de terminación
                            # 'no-answer', 'busy', 'failed', 'canceled' son terminaciones de "No contestó"
                            call_ended_by_system = remote.status in ['completed', 'no-answer', 'busy', 'failed', 'canceled']
                            
                            # 3. Accion de Finalización (Manual o Automática)
                            if st.button("✅ FINALIZAR GESTIÓN") or call_ended_by_system:
                                
                                # --- DETERMINACIÓN DE ESTADO FINAL ---
                                final_status = 'Llamado'
                                if remote.status in ['no-answer', 'busy', 'failed', 'canceled']:
                                    final_status = 'No Contesto'
                                
                                # Calculamos duración
                                t_fin = datetime.now()
                                dur = int((t_fin - st.session_state.t_inicio_dt).total_seconds())
                                
                                # --- PASO CRÍTICO 1: ACTUALIZACIÓN LOCAL INMEDIATA ---
                                # Esto garantiza que el usuario se mueva de 'Pendiente' a 'No Contesto' en el DF de la sesión
                                st.session_state.df_contactos.at[idx, 'estado'] = final_status
                                st.session_state.df_contactos.at[idx, 'observacion'] = nota
                                st.session_state.df_contactos.at[idx, 'duracion_seg'] = dur
                                st.session_state.df_contactos.at[idx, 'agente_id'] = st.session_state.agente_id
                                st.session_state.df_contactos.at[idx, 'fecha_llamada'] = t_fin.strftime("%Y-%m-%d %H:%M:%S")
                                st.session_state.df_contactos.at[idx, 'sid_llamada'] = st.session_state.llamada_activa_sid
                                
                                # --- PASO CRÍTICO 2: SINCRONIZACIÓN CON GOOGLE SHEETS ---
                                if URL_SHEET_INFORME:
                                    try:
                                        # Leemos el estado actual del sheet para no sobreescribir otros agentes
                                        df_gsheet_actual = conn.read(spreadsheet=URL_SHEET_INFORME, worksheet="0", ttl=0)
                                        
                                        # Preparamos la nueva fila con los datos frescos
                                        fila_nueva = st.session_state.df_contactos.loc[[idx]].copy()
                                        
                                        # Unimos el histórico con el nuevo registro
                                        df_actualizado = pd.concat([df_gsheet_actual, fila_nueva], ignore_index=True)
                                        
                                        # Eliminamos duplicados basados en el SID para no repetir la misma llamada si hubo reintentos
                                        df_actualizado = df_actualizado.drop_duplicates(subset=['sid_llamada'], keep='last')
                                        
                                        # Subimos al Sheet - CRÍTICO: especificar worksheet="0"
                                        conn.update(spreadsheet=URL_SHEET_INFORME, worksheet="0", data=df_actualizado)
                                        add_log(f"SYNC_EXITOSA: {c['nombre']} como {final_status}", "DATA")
                                        st.success(f"✅ Guardado exitoso en Google Sheets: {final_status}")
                                    except Exception as e_sync:
                                        st.error(f"❌ Error crítico de sincronización: {e_sync}")
                                        add_log(f"ERROR_SYNC: {str(e_sync)}", "ERROR")
                                        st.warning("Datos guardados localmente pero no sincronizados con Google Sheets")
                                
                                # --- PASO 3: LIMPIEZA DE ESTADO ---
                                st.session_state.llamada_activa_sid = None
                                time.sleep(1) # Breve pausa para que el usuario vea el mensaje de éxito
                                st.rerun()
                            
                            # Bucle de espera activa (Polling)
                            # Si la llamada sigue 'ringing' o 'in-progress', refrescamos cada 4 segundos
                            time.sleep(4)
                            st.rerun()
                            
                        except Exception as e_monitor:
                            st.error(f"Error monitoreando llamada: {e_monitor}")
                            # Si el SID falla o no existe, liberamos la interfaz para no bloquear al agente
                            st.session_state.llamada_activa_sid = None
                            st.rerun()
                else:
                    st.warning("Finalice la pausa para poder gestionar llamadas.")
        else:
            st.success(f"¡Felicidades! No hay más clientes en la categoría: {f_est}")
    else:
        st.info("Por favor, cargue un archivo CSV en el sidebar para comenzar la operación.")
