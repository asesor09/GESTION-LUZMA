import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime
import plotly.express as px

# --- 1. CONEXIÓN SEGURA ---
def conectar_db():
    if "url_luzma" not in st.secrets:
        st.error("❌ Configura 'url_luzma' en los Secrets de Streamlit.")
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
            # --- REPARACIÓN DE TABLA VEHICULOS ---
            cur.execute('''CREATE TABLE IF NOT EXISTS vehiculos (
                id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, conductor TEXT)''')
            cur.execute("ALTER TABLE vehiculos ADD COLUMN IF NOT EXISTS marca TEXT")
            cur.execute("ALTER TABLE vehiculos ADD COLUMN IF NOT EXISTS modelo TEXT")
            
            # --- REPARACIÓN DE TABLA VENTAS (Aquí estaba el error) ---
            cur.execute('''CREATE TABLE IF NOT EXISTS ventas (
                id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), fecha DATE)''')
            # Estas líneas aseguran que las columnas existan
            cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS servicio TEXT")
            cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS cantidad INTEGER")
            cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS valor_total NUMERIC")
            
            # --- RESTO DE TABLAS ---
            cur.execute('''CREATE TABLE IF NOT EXISTS tarifario (
                id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS gastos (
                id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), 
                tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT)''')
            
            conn.commit()
        except Exception as e:
            st.error(f"Error actualizando base de datos: {e}")
        finally:
            conn.close()

# --- 2. INTERFAZ ---
st.set_page_config(page_title="Luzma Producción", layout="wide", page_icon="🧵")
st.title("🧵 Confejeans Luzma: Gestión de Producción")

inicializar_db()

menu = st.sidebar.selectbox("📂 Módulos", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Registro Ventas", "⚙️ Tarifas"])
conn = conectar_db()

if conn:
    # --- MÓDULO VENTAS (CORREGIDO) ---
    if menu == "💰 Registro Ventas":
        st.header("💰 Liquidación de Producción")
        v_df = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
        t_df = pd.read_sql("SELECT * FROM tarifario", conn)
        
        if v_df.empty or t_df.empty:
            st.error("🛑 Registra primero vehículos y tarifas.")
        else:
            with st.form("f_v"):
                vs = st.selectbox("Vehículo", v_df['placa'])
                ts = st.selectbox("Servicio", t_df['servicio'])
                cant = st.number_input("Cantidad", min_value=1)
                pre = t_df[t_df['servicio'] == ts]['precio_unidad'].values[0]
                total = cant * pre
                st.info(f"💵 Total: ${total:,.0f}")
                
                if st.form_submit_button("✅ Guardar Venta"):
                    vid = v_df[v_df['placa'] == vs]['id'].values[0]
                    cur = conn.cursor()
                    # Ahora las columnas ya existen gracias a inicializar_db
                    cur.execute("""
                        INSERT INTO ventas (vehiculo_id, servicio, cantidad, valor_total, fecha) 
                        VALUES (%s,%s,%s,%s,%s)
                    """, (int(vid), ts, int(cant), float(total), datetime.now().date()))
                    conn.commit(); st.success("¡Venta guardada!"); st.rerun()

    # (Módulos de Flota, Gastos y Tarifas se mantienen igual)
    elif menu == "🚐 Flota":
        st.header("🚐 Gestión de Flota")
        with st.form("f_f"):
            c1, c2 = st.columns(2)
            p = c1.text_input("Placa").upper()
            ma = c1.text_input("Marca")
            mo = c2.text_input("Modelo")
            cond = c2.text_input("Conductor")
            if st.form_submit_button("➕ Guardar"):
                cur = conn.cursor()
                cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s,%s,%s,%s) ON CONFLICT (placa) DO UPDATE SET marca=EXCLUDED.marca, modelo=EXCLUDED.modelo, conductor=EXCLUDED.conductor", (p, ma, mo, cond))
                conn.commit(); st.success("Vehículo guardado"); st.rerun()
        st.dataframe(pd.read_sql("SELECT * FROM vehiculos", conn), use_container_width=True)

    elif menu == "⚙️ Tarifas":
        st.header("⚙️ Tarifas")
        with st.form("f_t"):
            s = st.text_input("Servicio")
            p = st.number_input("Precio ($)")
            if st.form_submit_button("Guardar"):
                cur = conn.cursor()
                cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, p))
                conn.commit(); st.rerun()
        st.table(pd.read_sql("SELECT * FROM tarifario", conn))

    conn.close()
