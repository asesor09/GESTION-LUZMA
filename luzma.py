import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime
import plotly.express as px

# --- 1. CONEXIÓN SEGURA ---
def conectar_db():
    if "url_luzma" not in st.secrets:
        st.error("❌ No se encontró 'url_luzma' en los Secrets.")
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
        try:
            cur = conn.cursor()
            # 1. Crear tabla base si no existe
            cur.execute('''CREATE TABLE IF NOT EXISTS vehiculos (
                id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, conductor TEXT)''')
            
            # 2. ACTUALIZACIÓN: Agregar columnas faltantes si ya existe la tabla antigua
            cur.execute("ALTER TABLE vehiculos ADD COLUMN IF NOT EXISTS marca TEXT")
            cur.execute("ALTER TABLE vehiculos ADD COLUMN IF NOT EXISTS modelo TEXT")
            
            # 3. Resto de tablas
            cur.execute('''CREATE TABLE IF NOT EXISTS tarifario (
                id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS ventas (
                id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), 
                servicio TEXT, cantidad INTEGER, valor_total NUMERIC, fecha DATE)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS gastos (
                id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), 
                tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT)''')
            
            conn.commit()
        except Exception as e:
            st.error(f"Error actualizando base de datos: {e}")
        finally:
            conn.close()

# --- 2. CONFIGURACIÓN ---
st.set_page_config(page_title="Confejeans Luzma", layout="wide", page_icon="🧵")
st.title("🧵 Confejeans Luzma: Gestión de Producción")

inicializar_db()

menu = st.sidebar.selectbox("📂 Módulos", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Ventas", "⚙️ Tarifas"])
conn = conectar_db()

if conn:
    # --- MÓDULO FLOTA (CORREGIDO) ---
    if menu == "🚐 Flota":
        st.header("🚐 Gestión de Flota (25 Vehículos)")
        with st.form("f_flota"):
            c1, c2 = st.columns(2)
            p = c1.text_input("Placa").upper()
            ma = c1.text_input("Marca")
            mo = c2.text_input("Modelo (Año)")
            cond = c2.text_input("Conductor")
            if st.form_submit_button("➕ Guardar"):
                cur = conn.cursor()
                cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s, %s, %s, %s) ON CONFLICT (placa) DO UPDATE SET marca=EXCLUDED.marca, modelo=EXCLUDED.modelo, conductor=EXCLUDED.conductor", (p, ma, mo, cond))
                conn.commit(); st.success("Guardado"); st.rerun()
        
        # Lectura segura
        try:
            df_v = pd.read_sql("SELECT placa, marca, modelo, conductor FROM vehiculos", conn)
            st.dataframe(df_v, use_container_width=True)
        except:
            st.info("No hay vehículos registrados.")

    # --- MÓDULO GASTOS ---
    elif menu == "💸 Gastos":
        st.header("💸 Registro de Gastos")
        v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
        if v_data.empty:
            st.warning("⚠️ Primero registra un vehículo en el módulo 'Flota'.")
        else:
            with st.form("f_g"):
                v_sel = st.selectbox("Vehículo", v_data['placa'])
                t = st.selectbox("Tipo", ["Combustible", "Mantenimiento", "Peajes", "Repuestos", "Otros"])
                m = st.number_input("Monto ($)", min_value=0)
                if st.form_submit_button("💾 Guardar Gasto"):
                    v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                    cur = conn.cursor()
                    cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha) VALUES (%s,%s,%s,%s)", (int(v_id), t, m, datetime.now().date()))
                    conn.commit(); st.success("Gasto guardado."); st.rerun()

    # --- MÓDULO VENTAS (PRODUCCIÓN) ---
    elif menu == "💰 Ventas":
        st.header("💰 Liquidación de Producción")
        v_df = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
        t_df = pd.read_sql("SELECT * FROM tarifario", conn)
        if v_df.empty or t_df.empty:
            st.error("🛑 Registra primero vehículos y tarifas.")
        else:
            with st.form("f_p"):
                vs = st.selectbox("Vehículo", v_df['placa'])
                ts = st.selectbox("Servicio", t_df['servicio'])
                cant = st.number_input("Cantidad", min_value=1)
                pre = t_df[t_df['servicio'] == ts]['precio_unidad'].values[0]
                st.info(f"💵 Total: ${cant * pre:,.0f}")
                if st.form_submit_button("✅ Guardar"):
                    vid = v_df[v_df['placa'] == vs]['id'].values[0]
                    cur = conn.cursor()
                    cur.execute("INSERT INTO ventas (vehiculo_id, servicio, cantidad, valor_total, fecha) VALUES (%s,%s,%s,%s,%s)", (int(vid), ts, cant, cant*pre, datetime.now().date()))
                    conn.commit(); st.success("Venta guardada."); st.rerun()

    # --- MÓDULO TARIFAS ---
    elif menu == "⚙️ Tarifas":
        st.header("⚙️ Precios por Unidad")
        with st.form("f_t"):
            s = st.text_input("Servicio")
            p = st.number_input("Precio ($)")
            if st.form_submit_button("Guardar"):
                cur = conn.cursor()
                cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, p))
                conn.commit(); st.rerun()
        st.table(pd.read_sql("SELECT * FROM tarifario", conn))

    # --- DASHBOARD ---
    elif menu == "📊 Dashboard":
        st.header("📊 Reporte de Utilidades")
        try:
            dv = pd.read_sql("SELECT valor_total FROM ventas", conn)
            dg = pd.read_sql("SELECT monto FROM gastos", conn)
            c1, c2 = st.columns(2)
            c1.metric("Ingresos", f"${dv['valor_total'].sum():,.0f}")
            c2.metric("Utilidad Neta", f"${dv['valor_total'].sum() - dg['monto'].sum():,.0f}")
        except:
            st.info("Registra datos para ver el balance.")

    conn.close()
