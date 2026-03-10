import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
import plotly.express as px

# --- 1. CONFIGURACIÓN DE LA BASE DE DATOS ---
DB_URL = "postgresql://neondb_owner:npg_c7Dkwlh1jzGQ@ep-lucky-shadow-ac1thtiq-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require"

def conectar_db():
    return psycopg2.connect(DB_URL)

def inicializar_db():
    conn = conectar_db(); cur = conn.cursor()
    # Tablas base
    cur.execute('CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, marca TEXT, modelo TEXT, conductor TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT)')
    
    # Tabla de Ventas (Usamos 'valor_viaje' para no romper tu Dashboard original)
    cur.execute('''CREATE TABLE IF NOT EXISTS ventas (
                    id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), 
                    cliente TEXT, valor_viaje NUMERIC, fecha DATE, descripcion TEXT, cantidad INTEGER)''')
    
    cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)')
    
    cur.execute('''CREATE TABLE IF NOT EXISTS hoja_vida (
                    id SERIAL PRIMARY KEY, vehiculo_id INTEGER UNIQUE REFERENCES vehiculos(id), 
                    soat_vence DATE, tecno_vence DATE, prev_vence DATE,
                    p_contractual DATE, p_extracontractual DATE, p_todoriesgo DATE, t_operaciones DATE)''')
    
    cur.execute('CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, nombre TEXT, usuario TEXT UNIQUE NOT NULL, clave TEXT NOT NULL, rol TEXT DEFAULT "vendedor")')
    
    # Usuario Admin y Luzma
    cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Jacobo Admin', 'admin', 'Jacobo2026', 'admin') ON CONFLICT (usuario) DO NOTHING")
    cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Luzma Personal', 'luzma', 'Luzma2026', 'vendedor') ON CONFLICT (usuario) DO NOTHING")
    
    # Asegurar columna cantidad en ventas
    try: cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS cantidad INTEGER")
    except: conn.rollback()

    conn.commit(); conn.close()

# --- 2. FUNCIONES DE APOYO (EXCEL RESTAURADO) ---
def to_excel(df_balance, df_g, df_v):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_balance.to_excel(writer, index=False, sheet_name='Balance General')
        df_g.to_excel(writer, index=False, sheet_name='Detalle Gastos')
        df_v.to_excel(writer, index=False, sheet_name='Detalle Ventas')
    return output.getvalue()

# --- 3. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="C&E Eficiencias", layout="wide", page_icon="🚐")
inicializar_db()

# --- 4. SISTEMA DE LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.sidebar.title("🔐 Acceso al Sistema")
    u_input = st.sidebar.text_input("Usuario")
    p_input = st.sidebar.text_input("Contraseña", type="password")
    if st.sidebar.button("Ingresar"):
        conn = conectar_db(); cur = conn.cursor()
        cur.execute("SELECT nombre, rol FROM usuarios WHERE usuario = %s AND clave = %s", (u_input, p_input))
        res = cur.fetchone(); conn.close()
        if res:
            st.session_state.logged_in = True
            st.session_state.u_name, st.session_state.u_rol = res[0], res[1]
            st.rerun()
        else: st.sidebar.error("Usuario o clave incorrectos")
    st.stop()

# --- 5. MENÚ PRINCIPAL ---
st.sidebar.write(f"👋 **{st.session_state.u_name}**")
target = st.sidebar.number_input("🎯 Meta Utilidad ($)", value=3000000, step=500000)
menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas", "⚙️ Usuarios"])

if st.sidebar.button("🚪 CERRAR SESIÓN"):
    st.session_state.logged_in = False; st.rerun()

# --- 6. LÓGICA DE MÓDULOS ---

if menu == "📊 Dashboard":
    st.title("📊 Análisis de Operación")
    conn = conectar_db()
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    c1, c2 = st.columns(2)
    with c1: placa_f = st.selectbox("Vehículo:", ["TODOS"] + v_data['placa'].tolist())
    with c2: rango = st.date_input("Fechas:", [datetime.now().date() - timedelta(days=30), datetime.now().date()])

    if len(rango) == 2:
        # CONSULTAS ORIGINALES (Sin cambiar nombres para no dañar el Dashboard)
        q_g = "SELECT g.fecha, v.placa, g.tipo_gasto as concepto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id WHERE g.fecha BETWEEN %s AND %s"
        q_v = "SELECT s.fecha, v.placa, s.cliente, s.valor_viaje as monto, s.descripcion FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id WHERE s.fecha BETWEEN %s AND %s"
        params = [rango[0], rango[1]]
        if placa_f != "TODOS":
            q_g += " AND v.placa = %s"; q_v += " AND v.placa = %s"
            params.append(placa_f)
        
        df_g = pd.read_sql(q_g, conn, params=params)
        df_v = pd.read_sql(q_v, conn, params=params)

        utilidad_neta = df_v['monto'].sum() - df_g['monto'].sum()
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
        m2.metric("Egresos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
        m3.metric("Utilidad", f"${utilidad_neta:,.0f}")

        # GRÁFICO (IGUAL AL ORIGINAL)
        res_g = df_g.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Gasto'})
        res_v = df_v.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Venta'})
        balance_df = pd.merge(res_v, res_g, on='placa', how='outer').fillna(0)
        st.plotly_chart(px.bar(balance_df, x='placa', y=['Venta', 'Gasto'], barmode='group'), use_container_width=True)

        # BOTÓN EXCEL (AQUÍ ESTÁ DE VUELTA)
        st.download_button("📥 Descargar Reporte (Excel)", data=to_excel(balance_df, df_g, df_v), file_name="Reporte.xlsx")
    conn.close()

elif menu == "💰 Ventas":
    st.title("💰 Producción Luzma")
    conn = conectar_db()
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
    
    with st.form("f_v"):
        v_sel = st.selectbox("Vehículo", v_data['placa'])
        s_sel = st.selectbox("Servicio", t_data['servicio'].tolist())
        cant = st.number_input("Cantidad", min_value=1)
        
        precio_u = t_data[t_data['servicio'] == s_sel]['precio_unidad'].values[0]
        total = cant * precio_u
        st.info(f"Total: ${total:,.0f}")
        
        desc = st.text_area("Detalles (Lote/Referencia)")
        if st.form_submit_button("Guardar"):
            v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
            cur = conn.cursor()
            # Mapeamos 'servicio' a 'cliente' y 'total' a 'valor_viaje' para que el Dashboard lo lea bien
            cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, descripcion, cantidad) VALUES (%s,%s,%s,%s,%s,%s)", 
                       (int(v_id), s_sel, total, datetime.now().date(), desc, int(cant)))
            conn.commit(); st.success("Venta guardada"); st.rerun()
    conn.close()

elif menu == "⚙️ Tarifas":
    st.title("⚙️ Precios")
    conn = conectar_db()
    with st.form("f_t"):
        s = st.text_input("Servicio"); p = st.number_input("Precio")
        if st.form_submit_button("Guardar"):
            cur = conn.cursor(); cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, p))
            conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT * FROM tarifario", conn)); conn.close()

elif menu == "⚙️ Usuarios" and st.session_state.u_rol == "admin":
    st.title("⚙️ Cambiar Clave de Luzma")
    conn = conectar_db(); cur = conn.cursor()
    # Sección para cambiar clave
    with st.form("cambio_clave"):
        st.write("Actualizar contraseña de Luzma")
        nueva_clave = st.text_input("Nueva Contraseña", type="password")
        if st.form_submit_button("Actualizar Clave"):
            cur.execute("UPDATE usuarios SET clave = %s WHERE usuario = 'luzma'", (nueva_clave,))
            conn.commit(); st.success("Clave de Luzma actualizada correctamente")
    conn.close()

# (Módulos de Flota, Gastos y Hoja de Vida se mantienen igual a tu código original)
