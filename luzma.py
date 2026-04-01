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

# --- 🧠 FUNCIÓN DE IA (OCR OPTIMIZADO) ---
def extraer_monto_ia(imagen_file):
    try:
        img = Image.open(imagen_file)
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        texto = pytesseract.image_to_string(img, config='--psm 6').upper()
        
        texto_limpio = texto.replace('.', '').replace(',', '').replace('$', '').replace("'", "")
        numeros = re.findall(r'\d+', texto_limpio)
        
        candidatos = []
        for n in numeros:
            val = int(n)
            if val > 1000000: val = val // 100
            if 3000 <= val <= 999999:
                candidatos.append(val)
        
        return max(candidatos) if candidatos else 0
    except:
        return 0

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

# --- 🔐 LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'monto_detectado' not in st.session_state: st.session_state.monto_detectado = 0.0

if not st.session_state.logged_in:
    st.sidebar.title("🔐 Acceso")
    u = st.sidebar.text_input("Usuario")
    p = st.sidebar.text_input("Clave", type="password")
    if st.sidebar.button("Entrar"):
        if u == "admin" and p == "Luzma2026":
            st.session_state.logged_in = True
            st.rerun()
        else: st.sidebar.error("Error de acceso")
    st.stop()

# --- 🚀 MENÚ ---
menu = st.sidebar.selectbox("MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos con IA", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas"])

conn = conectar_db()
if not conn: st.stop()

# --- 📊 DASHBOARD ---
if menu == "📊 Dashboard":
    st.title("📊 Dashboard de Control")
    
    # Consultas para el Dashboard
    df_v = pd.read_sql("SELECT s.fecha, v.placa, s.cliente as servicio, s.cantidad, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.fecha DESC", conn)
    df_g = pd.read_sql("SELECT g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id ORDER BY g.fecha DESC", conn)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
    c2.metric("Gastos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
    c3.metric("Utilidad", f"${df_v['monto'].sum() - df_g['monto'].sum():,.0f}")
    
    st.divider()
    
    # Detalle de Ventas y Gastos
    col_v, col_g = st.columns(2)
    with col_v:
        st.subheader("📝 Detalle de Ventas")
        st.dataframe(df_v, use_container_width=True, hide_index=True)
    
    with col_g:
        st.subheader("💸 Detalle de Gastos")
        st.dataframe(df_g, use_container_width=True, hide_index=True)

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

# --- 📑 HOJA DE VIDA (CORREGIDA) ---
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
        
        for i, (nombre_doc, fecha_vence) in enumerate([("SOAT", r['soat_vence']), ("TECNO", r['tecno_vence'])]):
            # CORRECCIÓN: Convertir a fecha de Python y verificar si es nulo
            if fecha_vence is not None:
                try:
                    # Aseguramos que sea objeto date para la resta
                    fecha_dt = pd.to_datetime(fecha_vence).date()
                    dias_restantes = (fecha_dt - hoy).days
                    
                    if dias_restantes < 0:
                        cols[i].error(f"❌ {nombre_doc} VENCIDO (hace {abs(dias_restantes)} días)")
                    elif dias_restantes <= 15:
                        cols[i].warning(f"⚠️ {nombre_doc} (Vence en {dias_restantes} días)")
                    else:
                        cols[i].success(f"✅ {nombre_doc} Ok ({dias_restantes} días restantes)")
                except:
                    cols[i].info(f"❓ Error en fecha de {nombre_doc}")
            else:
                cols[i].info(f"⚪ Sin fecha {nombre_doc}")

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
