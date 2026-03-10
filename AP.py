import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime
import io
import plotly.express as px

# --- 1. CONEXIÓN (Basada en tu captura) ---
def conectar_db():
    if "url_luzma" not in st.secrets:
        st.error("❌ No se encontró la llave 'url_luzma' en los Secretos.")
        return None
    try:
        # Usa la URL de tu base de datos independiente
        conn = psycopg2.connect(st.secrets["url_luzma"])
        cur = conn.cursor()
        cur.execute("SET search_path TO public") #
        return conn
    except Exception as e:
        st.error(f"❌ Error de conexión: {e}")
        return None

def inicializar_db():
    conn = conectar_db()
    if conn:
        cur = conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE, marca TEXT, conductor TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS ventas (id SERIAL PRIMARY KEY, vehiculo_id INTEGER, servicio TEXT, valor_total NUMERIC, fecha DATE, cantidad INTEGER)')
        cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE, precio_unidad NUMERIC)')
        conn.commit(); conn.close()

# --- 2. INICIO ---
st.set_page_config(page_title="Luzma Producción", layout="wide", page_icon="🧵")
st.title("🧵 Confejeans Luzma: Gestión de Producción")
inicializar_db()

menu = st.sidebar.selectbox("📂 Ir a:", ["📊 Dashboard", "🚐 Flota", "⚙️ Tarifas", "💰 Registro Ventas"])
conn = conectar_db()

if conn is None:
    st.warning("⚠️ Esperando configuración de base de datos...")
    st.stop()

# --- MÓDULO: TARIFAS (PRIMER PASO) ---
if menu == "⚙️ Tarifas":
    st.header("⚙️ Configurar Precios por Unidad")
    with st.form("f_tarifas"):
        s = st.selectbox("Servicio", ["Lavandería", "Corte", "Costura", "Bodega"])
        p = st.number_input("Precio por cada unidad ($)", min_value=0)
        if st.form_submit_button("💾 Guardar Precio"):
            cur = conn.cursor()
            cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s, %s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad = EXCLUDED.precio_unidad", (s, p))
            conn.commit(); st.success(f"Precio de {s} actualizado."); st.rerun()
    
    st.subheader("Lista de Precios")
    st.table(pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn))

# --- MÓDULO: FLOTA (SEGUNDO PASO) ---
elif menu == "🚐 Flota":
    st.header("🚐 Mis Vehículos (Luzma)")
    with st.form("f_flota"):
        p, c = st.text_input("Placa"), st.text_input("Conductor")
        if st.form_submit_button("➕ Registrar Vehículo"):
            cur = conn.cursor()
            cur.execute("INSERT INTO vehiculos (placa, conductor) VALUES (%s, %s)", (p.upper(), c))
            conn.commit(); st.success("Vehículo registrado."); st.rerun()
    
    st.dataframe(pd.read_sql("SELECT * FROM vehiculos", conn), use_container_width=True)

# --- MÓDULO: VENTAS (ESTO MOSTRARÁ EL TOTAL) ---
elif menu == "💰 Registro Ventas":
    st.header("💰 Cobro por Unidades")
    v_df = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_df = pd.read_sql("SELECT * FROM tarifario", conn)

    if v_df.empty or t_df.empty:
        st.error("🛑 PARA QUE ESTA PANTALLA MUESTRE ALGO, primero registra un Vehículo y una Tarifa.")
    else:
        with st.form("f_venta"):
            v_sel = st.selectbox("Vehículo", v_df['placa'])
            s_sel = st.selectbox("Trabajo realizado", t_df['servicio'])
            cant = st.number_input("Cantidad de piezas", min_value=1)
            
            # Cálculo automático
            precio = t_df[t_df['servicio'] == s_sel]['precio_unidad'].values[0]
            total = cant * precio
            st.info(f"💵 EL TOTAL A COBRAR ES: ${total:,.0f}")
            
            if st.form_submit_button("✅ Guardar y Cobrar"):
                v_id = v_df[v_df['placa'] == v_sel]['id'].values[0]
                cur = conn.cursor()
                cur.execute("INSERT INTO ventas (vehiculo_id, servicio, valor_total, fecha, cantidad) VALUES (%s,%s,%s,%s,%s)", 
                           (int(v_id), s_sel, total, datetime.now().date(), cant))
                conn.commit(); st.success("Venta guardada."); st.rerun()

# --- MÓDULO: DASHBOARD ---
elif menu == "📊 Dashboard":
    st.header("📊 Resumen de Ingresos")
    df = pd.read_sql("SELECT * FROM ventas", conn)
    if df.empty:
        st.info("Aún no hay ventas registradas para mostrar gráficos.")
    else:
        st.metric("Total Ingresos", f"${df['valor_total'].sum():,.0f}")
        st.plotly_chart(px.bar(df, x='fecha', y='valor_total', title="Ingresos por Día"), use_container_width=True)

conn.close()
