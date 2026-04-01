import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
from PIL import Image, ImageOps, ImageEnhance
import pytesseract
import re

# --- 1. CONFIGURACIÓN Y CONEXIÓN ---
st.set_page_config(page_title="Confejeans Luzma - Gestión Total", layout="wide", page_icon="🚐")

def conectar_db():
    if "url_luzma" not in st.secrets:
        st.error("❌ Falta la variable 'url_luzma' en los Secrets de Streamlit.")
        return None
    try:
        conn = psycopg2.connect(st.secrets["url_luzma"])
        return conn
    except Exception as e:
        st.error(f"❌ Error de conexión a la base de datos: {e}")
        return None

def generar_excel(df_v, df_g):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_v.to_excel(writer, index=False, sheet_name='Ventas_Ingresos')
        df_g.to_excel(writer, index=False, sheet_name='Gastos_Egresos')
    return output.getvalue()

# --- 🧠 IA LIGERA PARA ESCANEAR ---
def extraer_monto_ia(imagen_file):
    try:
        img = Image.open(imagen_file).convert('L')
        img = ImageOps.autocontrast(img)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        
        texto = pytesseract.image_to_string(img, config='--psm 6').upper()
        
        # Limpieza de puntos y comas para no romper números largos (ej: 74.426)
        texto_sucio = texto.replace('.', '').replace(',', '').replace('$', '').replace("'", "")
        numeros = re.findall(r'\d+', texto_sucio)
        
        candidatos = []
        for n in numeros:
            val = int(n)
            if val > 1000000: val = val // 100 # Manejo de centavos pegados
            if 3000 <= val <= 999999:
                candidatos.append(val)
        
        return max(candidatos) if candidatos else 0
    except:
        return 0

# --- INICIALIZAR TABLAS ---
def inicializar_db():
    conn = conectar_db()
    if conn:
        cur = conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL)')
        cur.execute('CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS ventas (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), cliente TEXT, valor_viaje NUMERIC, fecha DATE, cantidad INTEGER)')
        cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)')
        cur.execute('CREATE TABLE IF NOT EXISTS hoja_vida (id SERIAL PRIMARY KEY, vehiculo_id INTEGER UNIQUE REFERENCES vehiculos(id), soat_vence DATE, tecno_vence DATE)')
        cur.execute("CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, usuario TEXT UNIQUE, clave TEXT)")
        cur.execute("INSERT INTO usuarios (usuario, clave) VALUES ('admin', 'Luzma2026') ON CONFLICT DO NOTHING")
        conn.commit()
        conn.close()

inicializar_db()

# --- 🔐 SESIÓN Y LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'monto_ia' not in st.session_state: st.session_state.monto_ia = 0

if not st.session_state.logged_in:
    st.title("🔐 Acceso Confejeans Luzma")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar"):
        if u == "admin" and p == "Luzma2026":
            st.session_state.logged_in = True
            st.rerun()
        else: st.error("Clave incorrecta")
    st.stop()

# --- 🚀 MENÚ LATERAL ---
menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "💸 Gastos con IA", "💰 Ventas", "📑 Hoja de Vida", "🚐 Flota", "⚙️ Tarifas"])
if st.sidebar.button("🚪 Salir"):
    st.session_state.logged_in = False
    st.rerun()

conn = conectar_db()
if not conn: st.stop()

# --- DASHBOARD ---
if menu == "📊 Dashboard":
    st.title("📊 Resumen General")
    df_v = pd.read_sql("SELECT s.fecha, v.placa, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id", conn)
    df_g = pd.read_sql("SELECT g.fecha, v.placa, g.monto FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id", conn)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
    c2.metric("Gastos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
    c3.metric("Utilidad", f"${df_v['monto'].sum() - df_g['monto'].sum():,.0f}")
    
    st.divider()
    if not df_v.empty or not df_g.empty:
        st.download_button("📥 Descargar Reporte Excel", generar_excel(df_v, df_g), "Reporte_Luzma.xlsx")

# --- GASTOS CON IA ---
elif menu == "💸 Gastos con IA":
    st.title("💸 Registro de Gastos con Escáner")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    c1, c2 = st.columns(2)
    with c1:
        foto = st.file_uploader("📸 Foto del recibo", type=['jpg','png','jpeg'])
        if foto:
            st.image(foto, width=300)
            if st.button("🔍 Escanear Valor"):
                st.session_state.monto_ia = extraer_monto_ia(foto)
                st.success(f"Detectado: ${st.session_state.monto_ia:,.0f}")

    with c2:
        with st.form("f_g"):
            v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
            tipo = st.selectbox("Tipo", ["Combustible", "Mantenimiento", "Peaje", "Otros"])
            monto = st.number_input("Valor ($)", value=int(st.session_state.monto_ia))
            det = st.text_input("Detalle")
            if st.form_submit_button("💾 Guardar"):
                v_id = int(v_data[v_data['placa'] == v_sel]['id'].values[0])
                cur = conn.cursor()
                cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", (v_id, tipo, monto, datetime.now().date(), det))
                conn.commit()
                st.session_state.monto_ia = 0
                st.success("Gasto guardado"); st.rerun()

# --- VENTAS ---
elif menu == "💰 Ventas":
    st.title("💰 Producción")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
    with st.form("f_v"):
        v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
        s_sel = st.selectbox("Servicio", t_data['servicio'].tolist() if not t_data.empty else [])
        cant = st.number_input("Cantidad", min_value=1)
        if st.form_submit_button("Registrar"):
            v_id = int(v_data[v_data['placa'] == v_sel]['id'].values[0])
            precio = float(t_data[t_data['servicio'] == s_sel]['precio_unidad'].values[0])
            cur = conn.cursor()
            cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, cantidad) VALUES (%s,%s,%s,%s,%s)", (v_id, s_sel, cant*precio, datetime.now().date(), cant))
            conn.commit(); st.rerun()

# --- HOJA DE VIDA ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Vencimientos")
    df_hv = pd.read_sql("SELECT v.placa, h.soat_vence, h.tecno_vence FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id", conn)
    hoy = datetime.now().date()
    for _, r in df_hv.iterrows():
        st.write(f"🚚 **{r['placa']}**")
        c1, c2 = st.columns(2)
        for i, (n, f) in enumerate([("SOAT", r['soat_vence']), ("TECNO", r['tecno_vence'])]):
            if f:
                d = (f - hoy).days
                if d < 0: (c1 if i==0 else c2).error(f"{n} Vencido")
                else: (c1 if i==0 else c2).success(f"{n} Ok ({d} días)")
            else: (c1 if i==0 else c2).info(f"{n} Sin Datos")

# --- FLOTA ---
elif menu == "🚐 Flota":
    st.title("🚐 Flota")
    p = st.text_input("Nueva Placa").upper()
    if st.button("Añadir"):
        cur = conn.cursor(); cur.execute("INSERT INTO vehiculos (placa) VALUES (%s)", (p,)); conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT * FROM vehiculos", conn))

# --- TARIFAS ---
elif menu == "⚙️ Tarifas":
    st.title("⚙️ Tarifas")
    s = st.text_input("Servicio"); p = st.number_input("Precio")
    if st.button("Guardar"):
        cur = conn.cursor(); cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, p)); conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT * FROM tarifario", conn))

conn.close()
