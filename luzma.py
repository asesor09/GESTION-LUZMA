import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime
import io
import plotly.express as px

# --- 1. CONEXIÓN ---
def conectar_db():
    if "url_luzma" not in st.secrets:
        st.error("❌ No se encontró la llave 'url_luzma'.")
        return None
    try:
        conn = psycopg2.connect(st.secrets["url_luzma"])
        cur = conn.cursor()
        cur.execute("SET search_path TO public")
        return conn
    except Exception as e:
        st.error(f"❌ Error de conexión: {e}")
        return None

def inicializar_db():
    conn = conectar_db()
    if conn:
        cur = conn.cursor()
        # TABLA DE VEHÍCULOS (Completa)
        cur.execute('''CREATE TABLE IF NOT EXISTS vehiculos (
            id SERIAL PRIMARY KEY, 
            placa TEXT UNIQUE NOT NULL, 
            marca TEXT, 
            modelo TEXT, 
            conductor TEXT)''')
        # TABLA DE GASTOS (Nueva)
        cur.execute('''CREATE TABLE IF NOT EXISTS gastos (
            id SERIAL PRIMARY KEY, 
            vehiculo_id INTEGER REFERENCES vehiculos(id), 
            tipo_gasto TEXT, 
            monto NUMERIC, 
            fecha DATE, 
            detalle TEXT)''')
        # TABLAS DE PRODUCCIÓN Y TARIFAS
        cur.execute('''CREATE TABLE IF NOT EXISTS ventas (
            id SERIAL PRIMARY KEY, vehiculo_id INTEGER, servicio TEXT, 
            valor_total NUMERIC, fecha DATE, cantidad INTEGER)''')
        cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE, precio_unidad NUMERIC)')
        conn.commit(); conn.close()

# --- 2. CONFIGURACIÓN ---
st.set_page_config(page_title="Luzma Producción", layout="wide")
st.title("🧵 Confejeans Luzma: Gestión de Producción")
inicializar_db()

menu = st.sidebar.selectbox("📂 Módulos", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Registro Ventas", "⚙️ Tarifas"])
conn = conectar_db()
if conn is None: st.stop()

# --- MÓDULO: FLOTA (CORREGIDO) ---
if menu == "🚐 Flota":
    st.header("🚐 Gestión de Flota (25 Vehículos)")
    with st.form("f_flota"):
        c1, c2 = st.columns(2)
        p = c1.text_input("Placa (Ej: XYZ123)")
        m = c1.text_input("Marca (Ej: Chevrolet)")
        mod = c2.text_input("Modelo (Año)")
        cond = c2.text_input("Nombre del Conductor")
        if st.form_submit_button("➕ Registrar Vehículo"):
            cur = conn.cursor()
            cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s, %s, %s, %s) ON CONFLICT (placa) DO NOTHING", 
                       (p.upper(), m, mod, cond))
            conn.commit(); st.success("✅ Vehículo guardado."); st.rerun()
    
    st.subheader("Listado de Vehículos")
    df_v = pd.read_sql("SELECT placa, marca, modelo, conductor FROM vehiculos", conn)
    st.dataframe(df_v, use_container_width=True)

# --- MÓDULO: GASTOS (NUEVO) ---
elif menu == "💸 Gastos":
    st.header("💸 Registro de Gastos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    if v_data.empty:
        st.warning("⚠️ Primero registra un vehículo en el módulo 'Flota'.")
    else:
        with st.form("f_gastos"):
            v_sel = st.selectbox("Vehículo", v_data['placa'])
            tipo = st.selectbox("Tipo de Gasto", ["Combustible", "Mantenimiento", "Peajes", "Seguros", "Otros"])
            monto = st.number_input("Monto ($)", min_value=0)
            fec = st.date_input("Fecha", datetime.now().date())
            det = st.text_area("Detalle adicional")
            if st.form_submit_button("💾 Guardar Gasto"):
                v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                cur = conn.cursor()
                cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", 
                           (int(v_id), tipo, monto, fec, det))
                conn.commit(); st.success("✅ Gasto registrado."); st.rerun()
    
    st.subheader("Historial de Gastos")
    st.dataframe(pd.read_sql("SELECT g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id", conn), use_container_width=True)

# --- OTROS MÓDULOS (Dashboard, Ventas, Tarifas) ---
elif menu == "💰 Registro Ventas":
    st.header("💰 Registro de Cobro")
    v_df = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_df = pd.read_sql("SELECT * FROM tarifario", conn)
    if v_df.empty or t_df.empty:
        st.error("🛑 Registra vehículos y tarifas primero.")
    else:
        with st.form("f_v"):
            v_sel = st.selectbox("Vehículo", v_df['placa'])
            s_sel = st.selectbox("Servicio", t_df['servicio'])
            cant = st.number_input("Cantidad", min_value=1)
            precio = t_df[t_df['servicio'] == s_sel]['precio_unidad'].values[0]
            total = cant * precio
            st.info(f"💵 TOTAL: ${total:,.0f}")
            if st.form_submit_button("✅ Guardar Venta"):
                v_id = v_df[v_df['placa'] == v_sel]['id'].values[0]
                cur = conn.cursor()
                cur.execute("INSERT INTO ventas (vehiculo_id, servicio, valor_total, fecha, cantidad) VALUES (%s,%s,%s,%s,%s)", 
                           (int(v_id), s_sel, total, datetime.now().date(), cant))
                conn.commit(); st.success("Venta guardada."); st.rerun()

elif menu == "⚙️ Tarifas":
    st.header("⚙️ Configuración de Precios")
    with st.form("f_t"):
        s = st.text_input("Nombre del Servicio (Ej: Lavandería)")
        p = st.number_input("Precio por unidad", min_value=0)
        if st.form_submit_button("Guardar"):
            cur = conn.cursor()
            cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s, %s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad = EXCLUDED.precio_unidad", (s, p))
            conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT * FROM tarifario", conn))

elif menu == "📊 Dashboard":
    st.header("📊 Resumen de Utilidades")
    df_v = pd.read_sql("SELECT valor_total FROM ventas", conn)
    df_g = pd.read_sql("SELECT monto FROM gastos", conn)
    utilidad = df_v['valor_total'].sum() - df_g['monto'].sum()
    st.metric("Utilidad Neta Actual", f"${utilidad:,.0f}")
    # Gráfico simple de ventas
    df_graf = pd.read_sql("SELECT fecha, SUM(valor_total) as total FROM ventas GROUP BY fecha", conn)
    if not df_graf.empty:
        st.plotly_chart(px.line(df_graf, x='fecha', y='total', title="Ventas en el tiempo"), use_container_width=True)

conn.close()
