import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
from PIL import Image, ImageOps, ImageEnhance
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

# --- 🧠 FUNCIÓN DE IA (OCR REFORZADO) ---
def extraer_monto_ia(imagen_file):
    try:
        # Pre-procesamiento para que la IA lea mejor
        img = Image.open(imagen_file)
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.5) # Resaltar letras negras
        
        # Ejecutar Tesseract
        texto = pytesseract.image_to_string(img, config='--psm 6').upper()
        
        # Limpieza de caracteres que rompen los números (puntos y comas)
        texto_limpio = texto.replace('.', '').replace(',', '').replace('$', '').replace("'", "")
        
        # Buscar todas las secuencias de números
        numeros = re.findall(r'\d+', texto_limpio)
        
        # Filtrar números que parezcan montos de gasolina (Ej: entre 5000 y 900000)
        candidatos = []
        for n in numeros:
            val = int(n)
            # Si el número es muy largo (ej: 7442600), probablemente leyó los centavos pegados
            if val > 1000000: val = val // 100
            
            if 4000 <= val <= 999999:
                candidatos.append(val)
        
        if candidatos:
            # En recibos, el TOTAL suele ser el valor más alto
            return max(candidatos)
        return 0
    except Exception as e:
        st.error(f"Error técnico en el escáner: {e}")
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

# --- 🔐 SESIÓN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'monto_ia' not in st.session_state: st.session_state.monto_ia = 0.0

if not st.session_state.logged_in:
    st.sidebar.title("🔐 Acceso")
    u = st.sidebar.text_input("Usuario")
    p = st.sidebar.text_input("Clave", type="password")
    if st.sidebar.button("Entrar"):
        conn = conectar_db()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT nombre, rol FROM usuarios WHERE usuario = %s AND clave = %s", (u, p))
            res = cur.fetchone(); conn.close()
            if res:
                st.session_state.logged_in, st.session_state.u_name = True, res[0]
                st.rerun()
            else: st.sidebar.error("Usuario o clave incorrectos")
    st.stop()

# --- 🚀 MENÚ ---
st.sidebar.write(f"Conectado: **{st.session_state.u_name}**")
menu = st.sidebar.selectbox("MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos con IA", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas"])

if st.sidebar.button("🚪 Cerrar Sesión"):
    st.session_state.logged_in = False; st.rerun()

conn = conectar_db()
if not conn: st.stop()

# --- DASHBOARD ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis de Operación")
    df_v = pd.read_sql("SELECT s.fecha, v.placa, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id", conn)
    df_g = pd.read_sql("SELECT g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id", conn)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
    c2.metric("Gastos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
    c3.metric("Utilidad", f"${df_v['monto'].sum() - df_g['monto'].sum():,.0f}")
    
    st.divider()
    if st.button("📦 Generar Archivo Excel"):
        data_ex = generar_excel(df_v, df_g)
        st.download_button("📥 Descargar Reporte_Luzma.xlsx", data_ex, file_name=f"Reporte_{datetime.now().date()}.xlsx")

# --- GASTOS CON IA ---
elif menu == "💸 Gastos con IA":
    st.title("💸 Registro de Gastos con Escáner")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    col_foto, col_form = st.columns([1, 1])
    with col_foto:
        foto = st.file_uploader("📸 Sube la foto del recibo", type=['jpg', 'png', 'jpeg'])
        if foto:
            st.image(foto, caption="Recibo cargado", width=280)
            if st.button("🔍 Escanear Valor del Recibo"):
                with st.spinner('Escaneando...'):
                    st.session_state.monto_ia = extraer_monto_ia(foto)
                    if st.session_state.monto_ia > 0:
                        st.success(f"Valor Detectado: ${st.session_state.monto_ia:,.0f}")
                    else:
                        st.warning("No se detectó un valor claro. Ingrésalo manualmente.")

    with col_form:
        with st.form("f_g_ia"):
            v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
            tipo = st.selectbox("Concepto", ["Combustible", "Mantenimiento", "Peaje", "Otros"])
            # El valor se llena automáticamente si la IA detecta algo
            monto_final = st.number_input("Monto a Registrar ($)", value=float(st.session_state.monto_ia))
            obs = st.text_input("Nota / Observación")
            
            if st.form_submit_button("💾 Guardar Gasto"):
                v_id = int(v_data[v_data['placa'] == v_sel]['id'].values[0])
                cur = conn.cursor()
                cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", (v_id, tipo, monto_final, datetime.now().date(), obs))
                conn.commit()
                st.session_state.monto_ia = 0.0 
                st.success("Gasto registrado con éxito"); st.rerun()

    st.subheader("🔍 Últimos Movimientos")
    st.dataframe(pd.read_sql("SELECT g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id ORDER BY g.id DESC LIMIT 10", conn), use_container_width=True)

# --- VENTAS ---
elif menu == "💰 Ventas":
    st.title("💰 Producción Diaria")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
    
    with st.form("f_v"):
        v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
        s_sel = st.selectbox("Servicio", t_data['servicio'].tolist() if not t_data.empty else [])
        cant = st.number_input("Cantidad", min_value=1)
        if st.form_submit_button("💾 Guardar Venta"):
            v_id = int(v_data[v_data['placa'] == v_sel]['id'].values[0])
            precio = float(t_data[t_data['servicio'] == s_sel]['precio_unidad'].values[0])
            cur = conn.cursor()
            cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, cantidad) VALUES (%s,%s,%s,%s,%s)", (v_id, s_sel, cant*precio, datetime.now().date(), cant))
            conn.commit(); st.rerun()
    
    st.dataframe(pd.read_sql("SELECT s.fecha, v.placa, s.cliente as servicio, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.id DESC", conn), use_container_width=True)

# --- HOJA DE VIDA ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Vencimientos y Alertas")
    v_data_h = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    with st.expander("📝 Actualizar Fechas de Documentos"):
        with st.form("f_hv"):
            v_sel = st.selectbox("Vehículo", v_data_h['placa'])
            v_id = int(v_data_h[v_data_h['placa'] == v_sel]['id'].values[0])
            soat = st.date_input("Vencimiento SOAT")
            tecno = st.date_input("Vencimiento Tecno")
            if st.form_submit_button("Actualizar"):
                cur = conn.cursor()
                cur.execute("INSERT INTO hoja_vida (vehiculo_id, soat_vence, tecno_vence) VALUES (%s,%s,%s) ON CONFLICT (vehiculo_id) DO UPDATE SET soat_vence=EXCLUDED.soat_vence, tecno_vence=EXCLUDED.tecno_vence", (v_id, soat, tecno))
                conn.commit(); st.rerun()

    df_hv = pd.read_sql("SELECT v.placa, h.soat_vence, h.tecno_vence FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id", conn)
    hoy = datetime.now().date()
    for _, r in df_hv.iterrows():
        st.write(f"---")
        st.subheader(f"🚚 {r['placa']}")
        c1, c2 = st.columns(2)
        for i, (n, f) in enumerate([("SOAT", r['soat_vence']), ("TECNO", r['tecno_vence'])]):
            col = c1 if i==0 else c2
            if f:
                d = (f - hoy).days
                if d < 0: col.error(f"❌ {n} VENCIDO")
                elif d <= 15: col.warning(f"⚠️ {n} ({d} días)")
                else: col.success(f"✅ {n} Vigente")
            else: col.info(f"⚪ Sin datos de {n}")

# --- FLOTA ---
elif menu == "🚐 Flota":
    st.title("🚐 Control de Vehículos")
    with st.form("f_f"):
        p = st.text_input("Placa del Vehículo").upper()
        if st.form_submit_button("➕ Añadir a la Flota"):
            cur = conn.cursor(); cur.execute("INSERT INTO vehiculos (placa) VALUES (%s)", (p,))
            conn.commit(); st.rerun()
    st.dataframe(pd.read_sql("SELECT * FROM vehiculos", conn), use_container_width=True)

# --- TARIFAS ---
elif menu == "⚙️ Tarifas":
    st.title("⚙️ Precios de Servicios")
    with st.form("f_t"):
        s = st.text_input("Nombre del Servicio")
        p = st.number_input("Precio ($)", min_value=0)
        if st.form_submit_button("Guardar Tarifa"):
            cur = conn.cursor(); cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, p))
            conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT * FROM tarifario", conn))

if conn: conn.close()
