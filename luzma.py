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
            
            # REPARACIÓN DE TABLA VENTAS (Añadiendo Detalles)
            cur.execute("CREATE TABLE IF NOT EXISTS ventas (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), fecha DATE)")
            cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS servicio TEXT")
            cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS cantidad INTEGER")
            cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS valor_total NUMERIC")
            cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS detalles TEXT") # Nueva columna solicitada
            
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

menu = st.sidebar.selectbox("📂 Módulos", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Registro Ventas", "⚙️ Tarifas"])
conn = conectar_db()

if conn:
    # --- DASHBOARD (Métrica e Ingresos) ---
    if menu == "📊 Dashboard":
        st.header("📊 Reporte de Utilidades y Producción")
        try:
            df_v = pd.read_sql("SELECT valor_total, fecha FROM ventas", conn)
            df_g = pd.read_sql("SELECT monto FROM gastos", conn)
            
            ingresos = df_v['valor_total'].sum() if not df_v.empty else 0
            egresos = df_g['monto'].sum() if not df_g.empty else 0
            utilidad = ingresos - egresos
            
            # Métricas principales
            c1, c2, c3 = st.columns(3)
            c1.metric("Ingresos Totales", f"${ingresos:,.0f}")
            c2.metric("Gastos Totales", f"${egresos:,.0f}", delta_color="inverse")
            c3.metric("Utilidad Neta", f"${utilidad:,.0f}")
            
            # Gráfico de ventas
            if not df_v.empty:
                df_graf = df_v.groupby('fecha')['valor_total'].sum().reset_index()
                st.plotly_chart(px.line(df_graf, x='fecha', y='valor_total', title="Evolución de Producción (Ventas)", markers=True), use_container_width=True)
            else:
                st.info("Aún no hay datos para mostrar gráficos.")
                
        except Exception as e:
            st.warning("Cargando datos del Dashboard...")

    # --- MÓDULO REGISTRO VENTAS (Con Detalles) ---
    elif menu == "💰 Registro Ventas":
        st.header("💰 Liquidación de Trabajo")
        v_df = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
        t_df = pd.read_sql("SELECT * FROM tarifario", conn)
        
        if v_df.empty or t_df.empty:
            st.error("🛑 Registra primero vehículos y tarifas en sus respectivos módulos.")
        else:
            with st.form("f_v"):
                vs = st.selectbox("Vehículo Responsable", v_df['placa'])
                ts = st.selectbox("Tipo de Servicio", t_df['servicio'])
                cant = st.number_input("Cantidad de piezas/unidades", min_value=1)
                
                # Campo de detalles solicitado
                detalles_v = st.text_area("Detalles de la producción (Ej: Referencia, lote, observaciones)")
                
                pre = t_df[t_df['servicio'] == ts]['precio_unidad'].values[0]
                total = cant * pre
                st.info(f"💵 Total calculado: ${total:,.0f}")
                
                if st.form_submit_button("✅ Guardar Producción"):
                    vid = v_df[v_df['placa'] == vs]['id'].values[0]
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO ventas (vehiculo_id, servicio, cantidad, valor_total, detalles, fecha) 
                        VALUES (%s,%s,%s,%s,%s,%s)
                    """, (int(vid), ts, int(cant), float(total), detalles_v, datetime.now().date()))
                    conn.commit(); st.success("¡Registro guardado con éxito!"); st.rerun()
        
        st.subheader("Últimos Registros")
        try:
            st.dataframe(pd.read_sql("SELECT fecha, servicio, cantidad, valor_total, detalles FROM ventas ORDER BY id DESC", conn), use_container_width=True)
        except: pass

    # --- MÓDULO GASTOS ---
    elif menu == "💸 Gastos":
        st.header("💸 Gastos Operativos")
        v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
        if v_data.empty:
            st.warning("⚠️ Registra un vehículo primero.")
        else:
            with st.form("f_g"):
                v_sel = st.selectbox("Vehículo", v_data['placa'])
                t_gasto = st.selectbox("Categoría", ["Combustible", "Mantenimiento", "Peajes", "Repuestos", "Otros"])
                monto = st.number_input("Valor ($)", min_value=0)
                det = st.text_input("Descripción del gasto")
                if st.form_submit_button("💾 Guardar"):
                    v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                    cur = conn.cursor()
                    cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", 
                               (int(v_id), t_gasto, monto, datetime.now().date(), det))
                    conn.commit(); st.success("Gasto registrado."); st.rerun()

    # --- MÓDULO FLOTA ---
    elif menu == "🚐 Flota":
        st.header("🚐 Gestión de Flota (25 Vehículos)")
        with st.form("f_f"):
            c1, c2 = st.columns(2)
            p = c1.text_input("Placa").upper()
            ma = c1.text_input("Marca")
            mo = c2.text_input("Modelo")
            cond = c2.text_input("Nombre Conductor")
            if st.form_submit_button("➕ Registrar"):
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO vehiculos (placa, marca, modelo, conductor) 
                    VALUES (%s,%s,%s,%s) 
                    ON CONFLICT (placa) DO UPDATE SET marca=EXCLUDED.marca, modelo=EXCLUDED.modelo, conductor=EXCLUDED.conductor
                """, (p, ma, mo, cond))
                conn.commit(); st.success("Vehículo actualizado"); st.rerun()
        st.dataframe(pd.read_sql("SELECT placa, marca, modelo, conductor FROM vehiculos", conn), use_container_width=True)

    # --- MÓDULO TARIFAS ---
    elif menu == "⚙️ Tarifas":
        st.header("⚙️ Configuración de Precios por Unidad")
        with st.form("f_t"):
            s = st.text_input("Nombre del Servicio (Ej: Lavandería)")
            p = st.number_input("Precio por unidad ($)")
            if st.form_submit_button("Guardar Precio"):
                cur = conn.cursor()
                cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, p))
                conn.commit(); st.success("Tarifa guardada"); st.rerun()
        st.table(pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn))

    conn.close()
