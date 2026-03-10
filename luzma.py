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
            # REPARACIÓN DE TABLA VEHICULOS
            cur.execute("CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, conductor TEXT)")
            cur.execute("ALTER TABLE vehiculos ADD COLUMN IF NOT EXISTS marca TEXT")
            cur.execute("ALTER TABLE vehiculos ADD COLUMN IF NOT EXISTS modelo TEXT")
            
            # REPARACIÓN DE TABLA VENTAS
            cur.execute("CREATE TABLE IF NOT EXISTS ventas (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), fecha DATE)")
            cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS servicio TEXT")
            cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS cantidad INTEGER")
            cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS valor_total NUMERIC")
            
            # REPARACIÓN DE TABLA GASTOS
            cur.execute("CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), fecha DATE)")
            cur.execute("ALTER TABLE gastos ADD COLUMN IF NOT EXISTS tipo_gasto TEXT")
            cur.execute("ALTER TABLE gastos ADD COLUMN IF NOT EXISTS monto NUMERIC")
            cur.execute("ALTER TABLE gastos ADD COLUMN IF NOT EXISTS detalle TEXT")

            # TABLA TARIFARIO
            cur.execute("CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)")
            
            conn.commit()
        except Exception as e:
            st.error(f"Error reparando base de datos: {e}")
        finally:
            conn.close()

# --- 2. INTERFAZ ---
st.set_page_config(page_title="Confejeans Luzma", layout="wide", page_icon="🧵")
st.title("🧵 Confejeans Luzma: Gestión de Producción")

inicializar_db()

# Menú lateral con todos los módulos solicitados
menu = st.sidebar.selectbox("📂 Módulos", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Registro Ventas", "⚙️ Tarifas"])
conn = conectar_db()

if conn:
    # --- DASHBOARD (SOLUCIÓN AL ERROR) ---
    if menu == "📊 Dashboard":
        st.header("📊 Reporte de Utilidades Reales")
        try:
            # Leemos los datos de forma segura
            df_v = pd.read_sql("SELECT valor_total FROM ventas", conn)
            df_g = pd.read_sql("SELECT monto FROM gastos", conn)
            
            # Cálculos con protección contra vacíos
            ingresos = df_v['valor_total'].sum() if not df_v.empty else 0
            egresos = df_g['monto'].sum() if not df_g.empty else 0
            utilidad = ingresos - egresos
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Ingresos Totales", f"${ingresos:,.0f}")
            c2.metric("Gastos Totales", f"${egresos:,.0f}", delta_color="inverse")
            c3.metric("Utilidad Neta", f"${utilidad:,.0f}")
            
            # Gráfico de barras de ventas por día
            df_graf = pd.read_sql("SELECT fecha, SUM(valor_total) as total FROM ventas GROUP BY fecha ORDER BY fecha", conn)
            if not df_graf.empty:
                st.plotly_chart(px.bar(df_graf, x='fecha', y='total', title="Ventas por Día", color_discrete_sequence=['#00CC96']), use_container_width=True)
            else:
                st.info("👋 Bienvenida Luzma. El gráfico aparecerá cuando registres tu primera venta.")
                
        except Exception as e:
            st.warning("El Dashboard se está sincronizando con la nueva base de datos...")

    # --- MÓDULO GASTOS ---
    elif menu == "💸 Gastos":
        st.header("💸 Registro de Gastos")
        v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
        if v_data.empty:
            st.warning("⚠️ Primero registra un vehículo en el módulo 'Flota'.")
        else:
            with st.form("f_g"):
                v_sel = st.selectbox("Vehículo", v_data['placa'])
                t_gasto = st.selectbox("Tipo de Gasto", ["Combustible", "Mantenimiento", "Peajes", "Repuestos", "Alimentación", "Otros"])
                monto = st.number_input("Monto ($)", min_value=0)
                det = st.text_input("Detalle (Ej: Cambio de aceite)")
                if st.form_submit_button("💾 Guardar Gasto"):
                    v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                    cur = conn.cursor()
                    cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", 
                               (int(v_id), t_gasto, monto, datetime.now().date(), det))
                    conn.commit(); st.success("Gasto guardado."); st.rerun()
        
        st.subheader("Historial de Gastos")
        try:
            st.dataframe(pd.read_sql("SELECT g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id", conn), use_container_width=True)
        except: pass

    # --- MÓDULO VENTAS ---
    elif menu == "💰 Registro Ventas":
        st.header("💰 Liquidación de Trabajo")
        v_df = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
        t_df = pd.read_sql("SELECT * FROM tarifario", conn)
        
        if v_df.empty or t_df.empty:
            st.error("🛑 Registra primero vehículos y tarifas.")
        else:
            with st.form("f_v"):
                vs = st.selectbox("Vehículo", v_df['placa'])
                ts = st.selectbox("Servicio", t_df['servicio'])
                cant = st.number_input("Cantidad de piezas", min_value=1)
                pre = t_df[t_df['servicio'] == ts]['precio_unidad'].values[0]
                total = cant * pre
                st.info(f"💵 Total a cobrar: ${total:,.0f}")
                
                if st.form_submit_button("✅ Guardar"):
                    vid = v_df[v_df['placa'] == vs]['id'].values[0]
                    cur = conn.cursor()
                    cur.execute("INSERT INTO ventas (vehiculo_id, servicio, cantidad, valor_total, fecha) VALUES (%s,%s,%s,%s,%s)", 
                               (int(vid), ts, int(cant), float(total), datetime.now().date()))
                    conn.commit(); st.success("Venta guardada."); st.rerun()

    # (Módulos de Flota y Tarifas se mantienen igual)
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
            s = st.text_input("Nombre del Servicio (Ej: Corte)")
            p = st.number_input("Precio por unidad ($)")
            if st.form_submit_button("Guardar"):
                cur = conn.cursor()
                cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, p))
                conn.commit(); st.success("Tarifa actualizada"); st.rerun()
        st.table(pd.read_sql("SELECT * FROM tarifario", conn))

    conn.close()
