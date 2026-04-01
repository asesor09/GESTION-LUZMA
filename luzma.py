import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
import plotly.express as px
from PIL import Image
import pytesseract
import re

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

def generar_excel(df_v, df_g):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_v.to_excel(writer, index=False, sheet_name='Ventas_Ingresos')
        df_g.to_excel(writer, index=False, sheet_name='Gastos_Egresos')
    return output.getvalue()

# --- FUNCIÓN DE IA (OCR) ---
def extraer_monto_ia(imagen):
    try:
        img = Image.open(imagen)
        # Extraer texto de la imagen
        texto = pytesseract.image_to_string(img)
        # Buscar números (formato moneda)
        numeros = re.findall(r'\d+(?:\.\d+)?', texto.replace(',', '').replace('$', ''))
        # Convertir a float y filtrar valores reales (mayores a 1000 pesos)
        valores = [float(n) for n in numeros if float(n) > 1000]
        if valores:
            return max(valores) # El total suele ser el número más alto
        return 0
    except:
        return 0

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
        cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Luzma Admin', 'admin', 'Luzma2026', 'admin') ON CONFLICT (usuario) DO NOTHING")
        conn.commit()
        conn.close()

inicializar_db()

# --- 2. LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'monto_ia' not in st.session_state: st.session_state.monto_ia = 0

if not st.session_state.logged_in:
    st.sidebar.title("🔐 Acceso Sistema")
    u_input = st.sidebar.text_input("Usuario")
    p_input = st.sidebar.text_input("Contraseña", type="password")
    if st.sidebar.button("Ingresar"):
        conn = conectar_db()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT nombre, rol FROM usuarios WHERE usuario = %s AND clave = %s", (u_input, p_input))
            res = cur.fetchone()
            conn.close()
            if res:
                st.session_state.logged_in = True
                st.session_state.u_name, st.session_state.u_rol = res[0], res[1]
                st.rerun()
            else: st.sidebar.error("Usuario o clave incorrectos")
    st.stop()

# --- 3. INTERFAZ ---
st.sidebar.write(f"👤 **{st.session_state.u_name}**")
menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos IA", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas"])

if st.sidebar.button("🚪 Cerrar Sesión"):
    st.session_state.logged_in = False; st.rerun()

conn = conectar_db()
if not conn: st.stop()

# --- DASHBOARD ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis y Reportes")
    df_v = pd.read_sql("SELECT s.fecha, v.placa, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id", conn)
    df_g = pd.read_sql("SELECT g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id", conn)
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Ingresos", f"${df_v['monto'].sum():,.0f}")
    m2.metric("Total Gastos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
    m3.metric("Utilidad", f"${df_v['monto'].sum() - df_g['monto'].sum():,.0f}")

    st.divider()
    excel_file = generar_excel(df_v, df_g)
    st.download_button("📥 Descargar Excel Completo", data=excel_file, file_name="Reporte_Transportes.xlsx")

# --- GASTOS CON IA ---
elif menu == "💸 Gastos IA":
    st.title("💸 Registro de Gastos con Lectura de Foto")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    with st.container(border=True):
        foto = st.file_uploader("📸 Sube o toma foto del recibo", type=['jpg','jpeg','png'])
        if foto:
            st.image(foto, width=300)
            if st.button("🔍 Escanear Recibo"):
                st.session_state.monto_ia = extraer_monto_ia(foto)
                st.success(f"IA detectó: ${st.session_state.monto_ia:,.0f}")

    with st.form("f_gastos"):
        v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
        tipo = st.selectbox("Concepto", ["Combustible", "Mantenimiento", "Peaje", "Otros"])
        monto_final = st.number_input("Valor Final ($)", value=float(st.session_state.monto_ia))
        nota = st.text_input("Observación")
        
        if st.form_submit_button("💾 Guardar Gasto"):
            v_id = int(v_data[v_data['placa'] == v_sel]['id'].values[0])
            cur = conn.cursor()
            cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", 
                        (v_id, tipo, monto_final, datetime.now().date(), nota))
            conn.commit(); st.session_state.monto_ia = 0; st.success("Gasto Guardado"); st.rerun()

    st.subheader("🔍 Historial de Gastos")
    st.dataframe(pd.read_sql("SELECT g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id ORDER BY g.id DESC", conn), use_container_width=True)

# --- VENTAS ---
elif menu == "💰 Ventas":
    st.title("💰 Registro de Producción")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
    
    with st.form("f_v"):
        v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
        serv = st.selectbox("Servicio", t_data['servicio'].tolist() if not t_data.empty else [])
        cant = st.number_input("Cantidad", min_value=1)
        if st.form_submit_button("💰 Registrar Venta"):
            v_id = int(v_data[v_data['placa'] == v_sel]['id'].values[0])
            precio = float(t_data[t_data['servicio'] == serv]['precio_unidad'].values[0])
            cur = conn.cursor()
            cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, cantidad) VALUES (%s,%s,%s,%s,%s)", 
                        (v_id, serv, cant*precio, datetime.now().date(), cant))
            conn.commit(); st.rerun()
    
    st.dataframe(pd.read_sql("SELECT s.fecha, v.placa, s.cliente as servicio, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.id DESC", conn), use_container_width=True)

# --- HOJA DE VIDA ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Alertas de Documentos")
    v_data_h = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    with st.expander("📅 Actualizar Fechas"):
        with st.form("f_hv"):
            v_sel = st.selectbox("Vehículo", v_data_h['placa'])
            v_id = int(v_data_h[v_data_h['placa'] == v_sel]['id'].values[0])
            s_v = st.date_input("SOAT"); t_v = st.date_input("Tecno")
            if st.form_submit_button("Actualizar"):
                cur = conn.cursor()
                cur.execute("INSERT INTO hoja_vida (vehiculo_id, soat_vence, tecno_vence) VALUES (%s,%s,%s) ON CONFLICT (vehiculo_id) DO UPDATE SET soat_vence=EXCLUDED.soat_vence, tecno_vence=EXCLUDED.tecno_vence", (v_id, s_v, t_v))
                conn.commit(); st.rerun()

    df_hv = pd.read_sql("SELECT v.placa, h.soat_vence, h.tecno_vence FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id", conn)
    hoy = datetime.now().date()
    for _, row in df_hv.iterrows():
        st.subheader(f"🚚 {row['placa']}")
        c1, c2 = st.columns(2)
        for i, (name, fecha) in enumerate([("SOAT", row['soat_vence']), ("TECNO", row['tecno_vence'])]):
            col = c1 if i==0 else c2
            if fecha:
                d = (fecha - hoy).days
                if d < 0: col.error(f"❌ {name} VENCIDO")
                elif d <= 15: col.warning(f"⚠️ {name} vence en {d} días")
                else: col.success(f"✅ {name} Al día")
            else: col.info(f"⚪ {name} S/D")

# --- FLOTA ---
elif menu == "🚐 Flota":
    st.title("🚐 Mis 25 Vehículos")
    with st.form("f_f"):
        p = st.text_input("Placa").upper(); m = st.text_input("Marca")
        if st.form_submit_button("➕ Añadir"):
            cur = conn.cursor(); cur.execute("INSERT INTO vehiculos (placa, marca) VALUES (%s,%s)", (p, m))
            conn.commit(); st.rerun()
    st.dataframe(pd.read_sql("SELECT * FROM vehiculos", conn), use_container_width=True)

# --- TARIFAS ---
elif menu == "⚙️ Tarifas":
    st.title("⚙️ Precios")
    with st.form("f_t"):
        s = st.text_input("Servicio"); p = st.number_input("Precio ($)")
        if st.form_submit_button("Guardar"):
            cur = conn.cursor(); cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, p))
            conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT * FROM tarifario", conn))

conn.close()
