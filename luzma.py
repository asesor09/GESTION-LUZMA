import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
from PIL import Image, ImageOps, ImageEnhance
import pytesseract
import re
import plotly.express as px

# --- 1. CONFIGURACIÓN Y CONEXIÓN ---
st.set_page_config(page_title="Confejeans Luzma - Gestión de Flota", layout="wide", page_icon="🚐")

def conectar_db():
    if "url_luzma" not in st.secrets:
        st.error("❌ Falta 'url_luzma' en Secrets de Streamlit Cloud.")
        return None
    try:
        conn = psycopg2.connect(st.secrets["url_luzma"])
        return conn
    except Exception as e:
        st.error(f"❌ Error de conexión: {e}")
        return None

def generar_excel(df_balance, df_v, df_g):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_balance.to_excel(writer, index=False, sheet_name='Balance General')
        df_v.to_excel(writer, index=False, sheet_name='Detalle Ventas')
        df_g.to_excel(writer, index=False, sheet_name='Detalle Gastos')
    return output.getvalue()

# --- 🧠 FUNCIÓN DE IA (OCR) ---
def extraer_monto_ia(imagen_file):
    try:
        img = Image.open(imagen_file).convert('L')
        img = ImageOps.autocontrast(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        texto = pytesseract.image_to_string(img, config='--psm 6').upper()
        texto_limpio = texto.replace('.', '').replace(',', '').replace('$', '').replace("'", "")
        numeros = re.findall(r'\d+', texto_limpio)
        candidatos = [int(n) for n in numeros if 3000 <= int(n) <= 999999]
        return max(candidatos) if candidatos else 0
    except: return 0

# --- 🗄️ INICIALIZACIÓN ---
def inicializar_db():
    conn = conectar_db()
    if conn:
        cur = conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, marca TEXT, modelo TEXT, conductor TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS ventas (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), cliente TEXT, valor_viaje NUMERIC, fecha DATE, descripcion TEXT, cantidad INTEGER)')
        cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)')
        cur.execute('''CREATE TABLE IF NOT EXISTS hoja_vida (
                        id SERIAL PRIMARY KEY, vehiculo_id INTEGER UNIQUE REFERENCES vehiculos(id), 
                        soat_vence DATE, tecno_vence DATE, prev_vence DATE,
                        p_contractual DATE, p_extracontractual DATE, p_todoriesgo DATE, t_operaciones DATE)''')
        cur.execute("CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, nombre TEXT, usuario TEXT UNIQUE NOT NULL, clave TEXT NOT NULL, rol TEXT DEFAULT 'admin')")
        cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Admin', 'admin', 'Luzma2026', 'admin') ON CONFLICT (usuario) DO UPDATE SET clave = EXCLUDED.clave")
        conn.commit(); conn.close()

inicializar_db()

# --- 🔐 LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'monto_detectado' not in st.session_state: st.session_state.monto_detectado = 0.0

if not st.session_state.logged_in:
    st.title("🔐 Acceso Sistema Luzma")
    u, p = st.text_input("Usuario"), st.text_input("Clave", type="password")
    if st.button("Ingresar"):
        conn = conectar_db(); cur = conn.cursor()
        cur.execute("SELECT nombre FROM usuarios WHERE usuario = %s AND clave = %s", (u, p))
        res = cur.fetchone(); conn.close()
        if res:
            st.session_state.logged_in, st.session_state.u_name = True, res[0]
            st.rerun()
        else: st.error("Acceso denegado")
    st.stop()

# --- 🚀 MENÚ ---
st.sidebar.write(f"Conectado: **{st.session_state.u_name}**")
target = st.sidebar.number_input("🎯 Meta Utilidad ($)", value=5000000, step=500000)
menu = st.sidebar.selectbox("MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos con IA", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas"])
if st.sidebar.button("🚪 Cerrar Sesión"): st.session_state.logged_in = False; st.rerun()

conn = conectar_db()
if not conn: st.stop()

# --- 📊 DASHBOARD ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis de Operación")
    
    # Carga de datos
    df_v = pd.read_sql("SELECT s.fecha, v.placa, s.cliente, s.valor_viaje as monto, s.descripcion FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id", conn)
    df_g = pd.read_sql("SELECT g.fecha, v.placa, g.tipo_gasto as concepto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id", conn)
    
    # Métricas
    utilidad = df_v['monto'].sum() - df_g['monto'].sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
    c2.metric("Gastos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
    c3.metric("Utilidad", f"${utilidad:,.0f}", delta=f"{utilidad - target:,.0f}")

    # Gráfico Comparativo
    st.subheader("📈 Rendimiento por Placa")
    res_v = df_v.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Venta'})
    res_g = df_g.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Gasto'})
    balance_df = pd.merge(res_v, res_g, on='placa', how='outer').fillna(0)
    balance_df[['Venta', 'Gasto']] = balance_df[['Venta', 'Gasto']].apply(pd.to_numeric)
    
    fig = px.bar(balance_df, x='placa', y=['Venta', 'Gasto'], barmode='group', color_discrete_map={'Venta': '#2ecc71', 'Gasto': '#e74c3c'})
    st.plotly_chart(fig, use_container_width=True)

    # DETALLE DE MOVIMIENTOS
    st.divider()
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        st.write("### 📝 Detalle de Ventas")
        st.dataframe(df_v, use_container_width=True, hide_index=True)
    with col_d2:
        st.write("### 💸 Detalle de Gastos")
        st.dataframe(df_g, use_container_width=True, hide_index=True)

    if st.button("📦 Descargar Reporte Excel"):
        st.download_button("📥 Bajar Archivo", to_excel(balance_df, df_v, df_g), file_name="Reporte_Luzma.xlsx")

# --- 📑 HOJA DE VIDA (CORREGIDA) ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Documentación y Vencimientos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    with st.expander("📅 Actualizar Fechas"):
        with st.form("f_hv"):
            v_sel = st.selectbox("Vehículo", v_data['placa'])
            v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
            c1, c2 = st.columns(2)
            s_v = c1.date_input("SOAT"); t_v = c2.date_input("Tecno")
            if st.form_submit_button("🔄 Actualizar"):
                cur = conn.cursor()
                cur.execute("INSERT INTO hoja_vida (vehiculo_id, soat_vence, tecno_vence) VALUES (%s,%s,%s) ON CONFLICT (vehiculo_id) DO UPDATE SET soat_vence=EXCLUDED.soat_vence, tecno_vence=EXCLUDED.tecno_vence", (int(v_id), s_v, t_v))
                conn.commit(); st.rerun()

    df_hv = pd.read_sql("SELECT v.placa, h.soat_vence, h.tecno_vence FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id", conn)
    hoy = datetime.now().date()
    
    for _, r in df_hv.iterrows():
        st.write(f"--- 🚚 **{r['placa']}**")
        cols = st.columns(2)
        for i, (name, fecha) in enumerate([("SOAT", r['soat_vence']), ("TECNO", r['tecno_vence'])]):
            if fecha:
                # CORRECCIÓN AQUÍ: Aseguramos conversión a objeto date antes de restar
                f_date = pd.to_datetime(fecha).date()
                dias = (f_date - hoy).days
                if dias < 0: cols[i].error(f"❌ {name} VENCIDO ({abs(dias)}d)")
                elif dias <= 15: cols[i].warning(f"⚠️ {name} ({dias}d)")
                else: cols[i].success(f"✅ {name} OK")
            else:
                cols[i].info(f"⚪ {name}: Sin fecha")

# (Se mantienen los módulos de Flota, Gastos con IA, Ventas y Tarifas del código original)
# [ ... Resto del código de registro que ya funciona perfectamente ... ]
