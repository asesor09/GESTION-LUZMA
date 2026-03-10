import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime
import plotly.express as px

# --- 1. CONEXIÓN SEGURA (La clave NO se ve aquí) ---
def conectar_db():
    # Solo busca la llave en la caja fuerte de Streamlit
    if "url_luzma" not in st.secrets:
        st.error("❌ Error: Configura 'url_luzma' en los Secrets de Streamlit.")
        return None
    try:
        conn = psycopg2.connect(st.secrets["url_luzma"])
        cur = conn.cursor()
        # Fuerza a que use la carpeta 'public'
        cur.execute("SET search_path TO public")
        return conn
    except Exception as e:
        st.error(f"❌ No se pudo conectar a Neon: {e}")
        return None

def inicializar_db():
    conn = conectar_db()
    if conn:
        try:
            cur = conn.cursor()
            # Crear tablas en orden para evitar errores de relación
            cur.execute('''CREATE TABLE IF NOT EXISTS vehiculos (
                id SERIAL PRIMARY KEY, placa TEXT UNIQUE, marca TEXT, modelo TEXT, conductor TEXT)''')
            
            cur.execute('''CREATE TABLE IF NOT EXISTS tarifario (
                id SERIAL PRIMARY KEY, servicio TEXT UNIQUE, precio_unidad NUMERIC)''')
            
            cur.execute('''CREATE TABLE IF NOT EXISTS ventas (
                id SERIAL PRIMARY KEY, vehiculo_id INTEGER, servicio TEXT, 
                valor_total NUMERIC, fecha DATE, cantidad INTEGER)''')
            
            cur.execute('''CREATE TABLE IF NOT EXISTS gastos (
                id SERIAL PRIMARY KEY, vehiculo_id INTEGER, tipo_gasto TEXT, 
                monto NUMERIC, fecha DATE, detalle TEXT)''')
            
            conn.commit()
        except Exception as e:
            st.error(f"❌ Error al crear tablas: {e}")
        finally:
            conn.close()

# --- 2. CONFIGURACIÓN ---
st.set_page_config(page_title="Luzma Producción", layout="wide")
st.title("🧵 Confejeans Luzma: Producción e Independencia")

# Se asegura de crear las tablas antes de cualquier otra cosa
inicializar_db()

menu = st.sidebar.selectbox("📂 Módulos", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Registro Ventas", "⚙️ Tarifas"])
conn = conectar_db()

if conn:
    if menu == "📊 Dashboard":
        st.header("📊 Resumen de la Operación")
        try:
            # Usamos try-except por si las tablas están vacías
            df_v = pd.read_sql("SELECT * FROM public.ventas", conn)
            df_g = pd.read_sql("SELECT * FROM public.gastos", conn)
            
            if df_v.empty and df_g.empty:
                st.info("👋 ¡Bienvenida Luzma! Registra tu primer vehículo y venta para ver los gráficos.")
            else:
                c1, c2 = st.columns(2)
                utilidad = df_v['valor_total'].sum() - df_g['monto'].sum()
                c1.metric("Ingresos Totales", f"${df_v['valor_total'].sum():,.0f}")
                c2.metric("Utilidad Neta", f"${utilidad:,.0f}")
                
                if not df_v.empty:
                    st.plotly_chart(px.bar(df_v, x='fecha', y='valor_total', title="Ventas Diarias"), use_container_width=True)
        except Exception as e:
            st.warning("El sistema se está inicializando. Por favor, registra una Tarifa primero.")

    # --- MÓDULO FLOTA (Con todos los campos) ---
    elif menu == "🚐 Flota":
        st.header("🚐 Mis 25 Vehículos")
        with st.form("nueva_flota"):
            p = st.text_input("Placa")
            ma = st.text_input("Marca")
            mo = st.text_input("Modelo (Año)")
            co = st.text_input("Conductor")
            if st.form_submit_button("Guardar Vehículo"):
                cur = conn.cursor()
                cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s,%s,%s,%s) ON CONFLICT (placa) DO NOTHING", (p.upper(), ma, mo, co))
                conn.commit(); st.success("Guardado"); st.rerun()
        st.dataframe(pd.read_sql("SELECT * FROM vehiculos", conn), use_container_width=True)

    # (Aquí irían los demás módulos de Gastos, Ventas y Tarifas del código anterior)
    
    conn.close()
