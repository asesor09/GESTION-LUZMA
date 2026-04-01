import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
from PIL import Image, ImageOps
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

# --- 🧠 FUNCIÓN DE IA (OCR OPTIMIZADO) ---
def extraer_monto_ia(imagen_file):
    try:
        # Abrir y pre-procesar imagen para mejorar lectura
        img = Image.open(imagen_file)
        img = ImageOps.grayscale(img)  # Convertir a blanco y negro
        
        # Extraer texto
        texto = pytesseract.image_to_string(img, config='--psm 6').upper()
        
        # Lógica de búsqueda: Buscamos líneas que tengan "TOTAL" o "PAGAR"
        lineas = texto.split('\n')
        candidatos = []
        
        for linea in lineas:
            if any(palabra in linea for palabra in ["TOTAL", "PAGAR", "VALOR", "NETO", "CONTADO"]):
                # Extraer solo números, quitando puntos de miles y comas
                limpio = re.sub(r'\D', ' ', linea)
                nums = [int(s) for s in limpio.split() if len(s) >= 4]
                candidatos.extend(nums)
        
        if candidatos:
            return max(candidatos) # El total suele ser el número más alto cerca de la palabra TOTAL
            
        # Si falla lo anterior, buscar el número más grande de 4 a 7 cifras en todo el texto
        todos_los_nums = re.sub(r'\D', ' ', texto)
        nums_generales = [int(s) for s in todos_los_nums.split() if 4 <= len(s) <= 7]
        
        return max(nums_generales) if nums_generales else 0
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

# --- 🔐 LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'monto_detectado' not in st.session_state: st.session_state.monto_detectado = 0.0

if not st.session_state.logged_in:
    st.sidebar.title("🔐 Acceso")
    u = st.sidebar.text_input("Usuario")
    p = st.sidebar.text_input("Clave", type="password")
    if st.sidebar.button("Entrar"):
        conn = conectar_db()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT nombre, rol FROM usuarios WHERE usuario = %s AND clave = %s", (u, p))
            res = cur.fetchone()
            conn.close()
            if res:
                st.session_state.logged_in, st.session_state.u_name = True, res[0]
                st.rerun()
            else: st.sidebar.error("Error de acceso")
    st.stop()

# --- 🚀 MENÚ ---
st.sidebar.write(f"Conectado como: **{st.session_state.u_name}**")
menu = st.sidebar.selectbox("MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos con IA", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas"])

conn = conectar_db()
if not conn: st.stop()

# --- 📊 DASHBOARD ---
if menu == "📊 Dashboard":
    st.title("📊 Dashboard de Control")
    df_v = pd.read_sql("SELECT s.fecha, v.placa, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id", conn)
    df_g = pd.read_sql("SELECT g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id", conn)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
    c2.metric("Gastos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
    c3.metric("Utilidad", f"${df_v['monto'].sum() - df_g['monto'].sum():,.0f}")
    
    st.divider()
    if st.button("📦 Generar Reporte Excel"):
        data_ex = generar_excel(df_v, df_g)
        st.download_button("📥 Descargar Archivo", data_ex, file_name="Reporte_Luzma.xlsx")

# --- 💸 GASTOS CON IA ---
elif menu == "💸 Gastos con IA":
    st.title("💸 Registro de Gastos con Escáner")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    col_foto, col_form = st.columns([1, 1])
    
    with col_foto:
        foto = st.file_uploader("📸 Sube la foto del recibo", type=['jpg', 'png', 'jpeg'])
        if foto:
            st.image(foto, caption="Vista previa", width=300)
            if st.button("🔍 Escanear Total"):
                st.session_state.monto_detectado = extraer_monto_ia(foto)
    
    with col_form:
        with st.form("f_ia_g"):
            v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
            tipo = st.selectbox("Concepto", ["Combustible", "Mantenimiento", "Peaje", "Otros"])
            # Aquí aparece lo que detectó la IA, pero el usuario puede corregir
            monto_final = st.number_input("Valor detectado (Confirme)", value=float(st.session_state.monto_detectado))
            obs = st.text_input("Nota adicional")
            if st.form_submit_button("✅ Guardar Gasto"):
                v_id = int(v_data[v_data['placa'] == v_sel]['id'].values[0])
                cur = conn.cursor()
                cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", (v_id, tipo, monto_final, datetime.now().date(), obs))
                conn.commit()
                st.session_state.monto_detectado = 0
                st.success("Registrado"); st.rerun()

# --- 💰 VENTAS ---
elif menu == "💰 Ventas":
    st.title("💰 Registro de Ventas")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
    
    with st.form("f_v"):
        v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
        s_sel = st.selectbox("Servicio", t_data['servicio'].tolist() if not t_data.empty else [])
        cant = st.number_input("Cantidad", min_value=1)
        if st.form_submit_button("💾 Guardar"):
            v_id = int(v_data[v_data['placa'] == v_sel]['id'].values[0])
            precio = float(t_data[t_data['servicio'] == s_sel]['precio_unidad'].values[0])
            cur = conn.cursor()
            cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, cantidad) VALUES (%s,%s,%s,%s,%s)", (v_id, s_sel, cant*precio, datetime.now().date(), cant))
            conn.commit(); st.rerun()
    
    st.write("### Historial")
    st.dataframe(pd.read_sql("SELECT s.fecha, v.placa, s.cliente as servicio, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.id DESC", conn), use_container_width=True)

# --- 📑 HOJA DE VIDA ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Vencimientos")
    v_data_h = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    with st.expander("📝 Editar Fechas"):
        with st.form("f_hv"):
            v_sel = st.selectbox("Vehículo", v_data_h['placa'])
            v_id = int(v_data_h[v_data_h['placa'] == v_sel]['id'].values[0])
            c1, c2 = st.columns(2)
            soat = c1.date_input("SOAT")
            tecno = c2.date_input("Tecno")
            if st.form_submit_button("Actualizar"):
                cur = conn.cursor()
                cur.execute("INSERT INTO hoja_vida (vehiculo_id, soat_vence, tecno_vence) VALUES (%s,%s,%s) ON CONFLICT (vehiculo_id) DO UPDATE SET soat_vence=EXCLUDED.soat_vence, tecno_vence=EXCLUDED.tecno_vence", (v_id, soat, tecno))
                conn.commit(); st.rerun()

    df_hv = pd.read_sql("SELECT v.placa, h.soat_vence, h.tecno_vence FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id", conn)
    hoy = datetime.now().date()
    for _, r in df_hv.iterrows():
        st.write(f"---")
        st.subheader(f"🚚 {r['placa']}")
        cols = st.columns(2)
        for i, (n, f) in enumerate([("SOAT", r['soat_vence']), ("TECNO", r['tecno_vence'])]):
            if f:
                d = (f - hoy).days
                if d < 0: cols[i].error(f"❌ {n} VENCIDO")
                elif d <= 15: cols[i].warning(f"⚠️ {n} ({d} días)")
                else: cols[i].success(f"✅ {n} Ok")
            else: cols[i].info(f"S/D {n}")

# --- 🚐 FLOTA ---
elif menu == "🚐 Flota":
    st.title("🚐 Flota")
    with st.form("f_flota"):
        p = st.text_input("Placa").upper()
        if st.form_submit_button("Añadir"):
            cur = conn.cursor(); cur.execute("INSERT INTO vehiculos (placa) VALUES (%s)", (p,))
            conn.commit(); st.rerun()
    st.dataframe(pd.read_sql("SELECT * FROM vehiculos", conn), use_container_width=True)

# --- ⚙️ TARIFAS ---
elif menu == "⚙️ Tarifas":
    st.title("⚙️ Precios")
    with st.form("f_t"):
        s = st.text_input("Servicio")
        p = st.number_input("Precio ($)")
        if st.form_submit_button("Guardar"):
            cur = conn.cursor(); cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, p))
            conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT * FROM tarifario", conn))

if conn: conn.close()
