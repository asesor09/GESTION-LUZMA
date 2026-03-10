import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime
import plotly.express as px

# --- 1. CONEXIÓN A BASE DE DATOS ---
def conectar_db():
    # Se utiliza la llave configurada en los Secrets de Streamlit
    if "url_luzma" not in st.secrets:
        st.error("❌ No se encontró la configuración 'url_luzma' en los Secretos.")
        return None
    try:
        conn = psycopg2.connect(st.secrets["url_luzma"])
        cur = conn.cursor()
        # Asegura que trabajamos en el esquema público de Neon
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
            # Tabla de Vehículos (Flota completa)
            cur.execute('''CREATE TABLE IF NOT EXISTS vehiculos (
                id SERIAL PRIMARY KEY, 
                placa TEXT UNIQUE NOT NULL, 
                marca TEXT, 
                modelo TEXT, 
                conductor TEXT)''')
            
            # Tabla de Tarifas (Precios por tipo de trabajo)
            cur.execute('''CREATE TABLE IF NOT EXISTS tarifario (
                id SERIAL PRIMARY KEY, 
                servicio TEXT UNIQUE NOT NULL, 
                precio_unidad NUMERIC NOT NULL)''')
            
            # Tabla de Ventas/Producción (Cálculo automático)
            cur.execute('''CREATE TABLE IF NOT EXISTS ventas (
                id SERIAL PRIMARY KEY, 
                vehiculo_id INTEGER REFERENCES vehiculos(id), 
                servicio TEXT, 
                cantidad INTEGER, 
                valor_total NUMERIC, 
                fecha DATE)''')
            
            # Tabla de Gastos
            cur.execute('''CREATE TABLE IF NOT EXISTS gastos (
                id SERIAL PRIMARY KEY, 
                vehiculo_id INTEGER REFERENCES vehiculos(id), 
                tipo_gasto TEXT, 
                monto NUMERIC, 
                fecha DATE, 
                detalle TEXT)''')
            
            conn.commit()
        except Exception as e:
            st.error(f"Error al inicializar tablas: {e}")
        finally:
            conn.close()

# --- 2. CONFIGURACIÓN DE LA APP ---
st.set_page_config(page_title="Confejeans Luzma", layout="wide", page_icon="🧵")
st.title("🧵 Confejeans Luzma: Gestión de Producción y Flota")

# Inicializar tablas al arrancar
inicializar_db()

menu = st.sidebar.selectbox("📂 Seleccione Módulo", 
                            ["📊 Dashboard", "🚐 Gestión de Flota", "💸 Registro de Gastos", "💰 Producción (Ventas)", "⚙️ Configurar Precios"])

conn = conectar_db()
if not conn:
    st.stop()

# --- MÓDULO: DASHBOARD ---
if menu == "📊 Dashboard":
    st.header("📊 Resumen General de Utilidades")
    
    try:
        df_v = pd.read_sql("SELECT * FROM ventas", conn)
        df_g = pd.read_sql("SELECT * FROM gastos", conn)
        
        if df_v.empty and df_g.empty:
            st.info("Bienvenida. Inicie registrando vehículos y servicios en los módulos correspondientes.")
        else:
            col1, col2, col3 = st.columns(3)
            total_ingresos = df_v['valor_total'].sum() if not df_v.empty else 0
            total_gastos = df_g['monto'].sum() if not df_g.empty else 0
            utilidad = total_ingresos - total_gastos
            
            col1.metric("Ingresos Totales", f"${total_ingresos:,.0f}")
            col2.metric("Gastos Totales", f"${total_gastos:,.0f}")
            col3.metric("Utilidad Neta", f"${utilidad:,.0f}", delta_color="normal")
            
            if not df_v.empty:
                df_v['fecha'] = pd.to_datetime(df_v['fecha'])
                ventas_dia = df_v.groupby('fecha')['valor_total'].sum().reset_index()
                st.plotly_chart(px.line(ventas_dia, x='fecha', y='valor_total', title="Evolución de Ingresos"), use_container_width=True)
    except:
        st.warning("Aún no hay datos suficientes para generar el reporte.")

# --- MÓDULO: FLOTA ---
elif menu == "🚐 Gestión de Flota":
    st.header("🚐 Registro de Vehículos")
    with st.form("form_vehiculo"):
        c1, c2 = st.columns(2)
        placa = c1.text_input("Placa").upper()
        marca = c1.text_input("Marca")
        modelo = c2.text_input("Modelo (Año)")
        conductor = c2.text_input("Nombre del Conductor")
        if st.form_submit_button("Guardar Vehículo"):
            cur = conn.cursor()
            cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s,%s,%s,%s) ON CONFLICT (placa) DO NOTHING", 
                       (placa, marca, modelo, conductor))
            conn.commit()
            st.success(f"Vehículo {placa} registrado.")
            st.rerun()
    
    df_f = pd.read_sql("SELECT placa, marca, modelo, conductor FROM vehiculos", conn)
    st.subheader("Listado de Vehículos")
    st.dataframe(df_f, use_container_width=True)

# --- MÓDULO: GASTOS ---
elif menu == "💸 Registro de Gastos":
    st.header("💸 Control de Egresos")
    df_v = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    if df_v.empty:
        st.error("Debe registrar un vehículo primero.")
    else:
        with st.form("form_gastos"):
            veh_sel = st.selectbox("Vehículo", df_v['placa'])
            tipo = st.selectbox("Categoría", ["Combustible", "Mantenimiento", "Peajes", "Repuestos", "Seguros", "Otros"])
            monto = st.number_input("Monto del Gasto ($)", min_value=0)
            fecha_g = st.date_input("Fecha", datetime.now().date())
            detalle = st.text_area("Descripción")
            
            if st.form_submit_button("Registrar Gasto"):
                v_id = df_v[df_v['placa'] == veh_sel]['id'].values[0]
                cur = conn.cursor()
                cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", 
                           (int(v_id), tipo, monto, fecha_g, detalle))
                conn.commit()
                st.success("Gasto guardado correctamente.")
                st.rerun()

# --- MÓDULO: PRODUCCIÓN ---
elif menu == "💰 Producción (Ventas)":
    st.header("💰 Liquidación de Trabajo")
    df_v = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    df_t = pd.read_sql("SELECT * FROM tarifario", conn)
    
    if df_v.empty or df_t.empty:
        st.error("Se requiere tener vehículos y precios configurados.")
    else:
        with st.form("form_produccion"):
            v_sel = st.selectbox("Vehículo Responsable", df_v['placa'])
            s_sel = st.selectbox("Tipo de Servicio", df_t['servicio'])
            cant = st.number_input("Cantidad de Unidades", min_value=1, step=1)
            
            # Cálculo automático basado en el precio guardado
            precio_u = df_t[df_t['servicio'] == s_sel]['precio_unidad'].values[0]
            total_calc = cant * precio_u
            
            st.info(f"💵 Total a Cobrar: ${total_calc:,.0f} (Precio unitario: ${precio_u:,.0f})")
            
            if st.form_submit_button("✅ Finalizar y Guardar"):
                v_id = df_v[df_v['placa'] == v_sel]['id'].values[0]
                cur = conn.cursor()
                cur.execute("INSERT INTO ventas (vehiculo_id, servicio, cantidad, valor_total, fecha) VALUES (%s,%s,%s,%s,%s)", 
                           (int(v_id), s_sel, cant, total_calc, datetime.now().date()))
                conn.commit()
                st.success("Producción registrada.")
                st.rerun()

# --- MÓDULO: TARIFAS ---
elif menu == "⚙️ Configurar Precios":
    st.header("⚙️ Tarifario por Unidad")
    with st.form("form_precios"):
        nuevo_s = st.text_input("Nombre del Servicio (Ej: Lavandería, Corte)")
        nuevo_p = st.number_input("Precio por Unidad ($)", min_value=0)
        if st.form_submit_button("Actualizar Precio"):
            cur = conn.cursor()
            cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s, %s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad = EXCLUDED.precio_unidad", 
                       (nuevo_s, nuevo_p))
            conn.commit()
            st.success("Tarifa actualizada.")
            st.rerun()
    
    st.subheader("Precios Actuales")
    st.table(pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn))

conn.close()
