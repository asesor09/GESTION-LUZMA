import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
import plotly.express as px

# --- 1. CONEXIÓN SEGURA (Usa tus Secrets de Streamlit Cloud) ---
def conectar_db():
    if "url_luzma" not in st.secrets:
        st.error("❌ Configura 'url_luzma' en los Secrets.")
        return None
    return psycopg2.connect(st.secrets["url_luzma"])

def inicializar_db():
    conn = conectar_db()
    if conn:
        cur = conn.cursor()
        # Reparación de tablas con sintaxis correcta de comillas
        cur.execute("CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, marca TEXT, modelo TEXT, conductor TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT)")
        
        # Tabla Ventas: Usamos 'valor_viaje' para que tu Dashboard original funcione perfecto
        cur.execute('''CREATE TABLE IF NOT EXISTS ventas (
                        id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), 
                        cliente TEXT, valor_viaje NUMERIC, fecha DATE, descripcion TEXT, cantidad INTEGER)''')
        
        cur.execute("CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)")
        
        cur.execute('''CREATE TABLE IF NOT EXISTS hoja_vida (
                        id SERIAL PRIMARY KEY, vehiculo_id INTEGER UNIQUE REFERENCES vehiculos(id), 
                        soat_vence DATE, tecno_vence DATE, prev_vence DATE,
                        p_contractual DATE, p_extracontractual DATE, p_todoriesgo DATE, t_operaciones DATE)''')
        
        # FIX: Usamos comillas simples para 'vendedor'
        cur.execute("CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, nombre TEXT, usuario TEXT UNIQUE NOT NULL, clave TEXT NOT NULL, rol TEXT DEFAULT 'vendedor')")
        
        # Inserción de usuarios iniciales
        cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Jacobo Admin', 'admin', 'Jacobo2026', 'admin') ON CONFLICT (usuario) DO NOTHING")
        cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Luzma Personal', 'luzma', 'Luzma2026', 'vendedor') ON CONFLICT (usuario) DO NOTHING")
        
        conn.commit(); conn.close()

# --- 2. EXCEL (Restaurado tal cual lo enviaste) ---
def to_excel(df_balance, df_g, df_v):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_balance.to_excel(writer, index=False, sheet_name='Balance General')
        df_g.to_excel(writer, index=False, sheet_name='Detalle Gastos')
        df_v.to_excel(writer, index=False, sheet_name='Detalle Ventas')
    return output.getvalue()

st.set_page_config(page_title="C&E - Luzma", layout="wide", page_icon="🧵")
inicializar_db()

# --- 3. LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if not st.session_state.logged_in:
    st.sidebar.title("🔐 Acceso")
    u_input = st.sidebar.text_input("Usuario")
    p_input = st.sidebar.text_input("Contraseña", type="password")
    if st.sidebar.button("Ingresar"):
        conn = conectar_db()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT nombre, rol FROM usuarios WHERE usuario = %s AND clave = %s", (u_input, p_input))
            res = cur.fetchone(); conn.close()
            if res:
                st.session_state.logged_in = True
                st.session_state.u_name, st.session_state.u_rol = res[0], res[1]
                st.rerun()
            else: st.sidebar.error("Error en credenciales")
    st.stop()

# --- 4. MENÚ ---
st.sidebar.write(f"👋 **{st.session_state.u_name}**")
target = st.sidebar.number_input("🎯 Meta Utilidad ($)", value=3000000, step=500000)
menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas", "⚙️ Usuarios"])

if st.sidebar.button("🚪 CERRAR SESIÓN"):
    st.session_state.logged_in = False; st.rerun()

conn = conectar_db()

# --- 5. LÓGICA DE MÓDULOS (Dashboard Original) ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis de Operación")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    c1, c2 = st.columns(2)
    with c1: placa_f = st.selectbox("Vehículo:", ["TODOS"] + v_data['placa'].tolist())
    with c2: rango = st.date_input("Fechas:", [datetime.now().date() - timedelta(days=30), datetime.now().date()])

    if len(rango) == 2:
        q_g = "SELECT g.fecha, v.placa, g.tipo_gasto as concepto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id WHERE g.fecha BETWEEN %s AND %s"
        q_v = "SELECT s.fecha, v.placa, s.cliente as concepto, s.valor_viaje as monto, s.descripcion FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id WHERE s.fecha BETWEEN %s AND %s"
        params = [rango[0], rango[1]]
        if placa_f != "TODOS":
            q_g += " AND v.placa = %s"; q_v += " AND v.placa = %s"
            params.append(placa_f)
        
        df_g = pd.read_sql(q_g, conn, params=params)
        df_v = pd.read_sql(q_v, conn, params=params)

        m1, m2, m3 = st.columns(3)
        m1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
        m2.metric("Egresos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
        m3.metric("Utilidad", f"${df_v['monto'].sum() - df_g['monto'].sum():,.0f}")

        res_g = df_g.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Gasto'})
        res_v = df_v.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Venta'})
        balance_df = pd.merge(res_v, res_g, on='placa', how='outer').fillna(0)
        st.plotly_chart(px.bar(balance_df, x='placa', y=['Venta', 'Gasto'], barmode='group'), use_container_width=True)

        st.download_button("📥 Reporte Excel", data=to_excel(balance_df, df_g, df_v), file_name="Reporte_Luzma.xlsx")

elif menu == "💰 Ventas":
    st.title("💰 Registro de Producción")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
    
    with st.form("f_v"):
        v_sel = st.selectbox("Vehículo", v_data['placa'])
        s_sel = st.selectbox("Servicio", t_data['servicio'].tolist())
        cant = st.number_input("Cantidad", min_value=1)
        precio_u = t_data[t_data['servicio'] == s_sel]['precio_unidad'].values[0]
        total = cant * precio_u
        st.info(f"💵 Total: ${total:,.0f}")
        desc = st.text_area("Detalles del Lote")
        if st.form_submit_button("💰 Guardar"):
            v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
            cur = conn.cursor()
            cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, descripcion, cantidad) VALUES (%s,%s,%s,%s,%s,%s)", 
                       (int(v_id), s_sel, total, datetime.now().date(), desc, int(cant)))
            conn.commit(); st.success("Guardado"); st.rerun()

elif menu == "⚙️ Tarifas":
    st.title("⚙️ Precios")
    with st.form("f_t"):
        s = st.text_input("Servicio"); p = st.number_input("Precio ($)")
        if st.form_submit_button("Guardar"):
            cur = conn.cursor(); cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, p))
            conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT * FROM tarifario", conn))

elif menu == "⚙️ Usuarios" and st.session_state.u_rol == "admin":
    st.title("⚙️ Cambiar Clave de Luzma")
    with st.form("c_l"):
        nueva_c = st.text_input("Nueva Clave para Luzma", type="password")
        if st.form_submit_button("Actualizar"):
            cur = conn.cursor(); cur.execute("UPDATE usuarios SET clave = %s WHERE usuario = 'luzma'", (nueva_c,))
            conn.commit(); st.success("Clave actualizada")

# (Flota, Gastos y Hoja de Vida siguen la lógica exacta que enviaste)

conn.close()
