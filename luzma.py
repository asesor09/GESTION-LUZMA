import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
import plotly.express as px

# --- 1. CONEXIÓN SEGURA (GPS DE ESQUEMA ACTIVO) ---
def conectar_db():
    if "url_luzma" not in st.secrets:
        st.error("❌ Configura 'url_luzma' en los Secrets.")
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
        cur.execute('CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, marca TEXT, modelo TEXT, conductor TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS ventas (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), cliente TEXT, valor_viaje NUMERIC, fecha DATE, descripcion TEXT, cantidad INTEGER)')
        cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)')
        cur.execute('''CREATE TABLE IF NOT EXISTS hoja_vida (
                        id SERIAL PRIMARY KEY, vehiculo_id INTEGER UNIQUE REFERENCES vehiculos(id), 
                        soat_vence DATE, tecno_vence DATE, prev_vence DATE,
                        p_contractual DATE, p_extracontractual DATE, p_todoriesgo DATE, t_operaciones DATE)''')
        cur.execute("CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, nombre TEXT, usuario TEXT UNIQUE NOT NULL, clave TEXT NOT NULL, rol TEXT DEFAULT 'admin')")
        cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Jacobo Admin', 'admin', 'Jacobo2026', 'admin') ON CONFLICT (usuario) DO NOTHING")
        conn.commit(); conn.close()

# --- 2. FUNCIÓN EXCEL ---
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
            else: st.sidebar.error("Usuario o clave incorrectos")
    st.stop()

# --- 4. MENÚ ---
st.sidebar.write(f"👋 **{st.session_state.u_name}**")
target = st.sidebar.number_input("🎯 Meta Utilidad ($)", value=3000000, step=500000)
menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas", "⚙️ Usuarios"])

if st.sidebar.button("🚪 CERRAR SESIÓN"):
    st.session_state.logged_in = False; st.rerun()

conn = conectar_db()
if not conn: st.stop()

# --- 📊 DASHBOARD ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis de Operación")
    v_veh = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    c1, c2 = st.columns(2)
    with c1: placa_f = st.selectbox("Vehículo:", ["TODOS"] + v_veh['placa'].tolist())
    with c2: rango = st.date_input("Fechas:", [datetime.now().date() - timedelta(days=30), datetime.now().date()])

    if len(rango) == 2:
        q_g = "SELECT g.fecha, v.placa, g.tipo_gasto as concepto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id WHERE g.fecha BETWEEN %s AND %s"
        q_v = "SELECT s.fecha, v.placa, s.cliente as concepto, s.valor_viaje as monto, s.descripcion as detalle, s.cantidad FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id WHERE s.fecha BETWEEN %s AND %s"
        params = [rango[0], rango[1]]
        if placa_f != "TODOS":
            q_g += " AND v.placa = %s"; q_v += " AND v.placa = %s"
            params.append(placa_f)
        
        df_g = pd.read_sql(q_g, conn, params=params)
        df_v = pd.read_sql(q_v, conn, params=params)
        u_neta = df_v['monto'].sum() - df_g['monto'].sum()

        if u_neta >= target: st.success(f"### 🏆 Meta Lograda! ${u_neta:,.0f}"); st.balloons()
        else: st.error(f"### ⚠️ Faltan ${abs(u_neta - target):,.0f}")

        m1, m2, m3 = st.columns(3)
        m1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
        m2.metric("Egresos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
        m3.metric("Utilidad", f"${u_neta:,.0f}")

        st.plotly_chart(px.bar(df_v.groupby('placa')['monto'].sum().reset_index(), x='placa', y='monto', title="Ventas por Placa"), use_container_width=True)
        st.download_button("📥 Reporte Excel", data=to_excel(df_v, df_g, df_v), file_name="Reporte.xlsx")

# --- 💰 VENTAS (CON CAMPO MONTO RESALTADO) ---
elif menu == "💰 Ventas":
    st.title("💰 Registro de Producción")
    v_data_v = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data_v = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
    
    tab1, tab2 = st.tabs(["📝 Nuevo Registro", "📋 Historial"])
    
    with tab1:
        with st.form("f_v"):
            col_a, col_b = st.columns(2)
            v_sel = col_a.selectbox("Vehículo", v_data_v['placa'] if not v_data_v.empty else [])
            s_sel = col_b.selectbox("Servicio", t_data_v['servicio'].tolist() if not t_data_v.empty else [])
            cant = st.number_input("Cantidad de piezas/unidades", min_value=1, step=1)
            
            # MOSTRAR EL MONTO CALCULADO ANTES DE GUARDAR
            if not t_data_v.empty:
                precio_u = t_data_v[t_data_v['servicio'] == s_sel]['precio_unidad'].values[0]
                monto_total = float(cant * precio_u)
                st.metric("💵 MONTO TOTAL A COBRAR", f"${monto_total:,.0f}")
            
            desc = st.text_area("Detalles (Lote, Referencia, Notas)")
            if st.form_submit_button("💰 Guardar Venta"):
                v_id = v_data_v[v_data_v['placa'] == v_sel]['id'].values[0]
                cur = conn.cursor()
                cur.execute("SET search_path TO public")
                cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, descripcion, cantidad) VALUES (%s,%s,%s,%s,%s,%s)", 
                           (int(v_id), s_sel, monto_total, datetime.now().date(), desc, int(cant)))
                conn.commit(); st.success(f"Venta registrada por ${monto_total:,.0f}"); st.rerun()

    with tab2:
        st.subheader("Historial de Ventas")
        df_hist = pd.read_sql("SELECT s.fecha, v.placa, s.cliente as servicio, s.cantidad, s.valor_viaje as monto, s.descripcion FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.id DESC", conn)
        st.dataframe(df_hist, use_container_width=True, hide_index=True)

# --- 📑 HOJA DE VIDA ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Documentación y Alertas")
    df_hv = pd.read_sql('''SELECT v.placa, h.soat_vence, h.tecno_vence, h.prev_vence, h.p_contractual, h.p_extracontractual, h.p_todoriesgo, h.t_operaciones FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id''', conn)
    hoy = datetime.now().date()
    for _, row in df_hv.iterrows():
        st.subheader(f"Vehículo: {row['placa']}")
        cols = st.columns(4)
        docs = [("SOAT", row['soat_vence']), ("TECNO", row['tecno_vence']), ("PREV", row['prev_vence']), ("T.OPER", row['t_operaciones']), ("POL. CONT", row['p_contractual']), ("POL. EXTRA", row['p_extracontractual']), ("TODO RIESGO", row['p_todoriesgo'])]
        for i, (name, fecha) in enumerate(docs):
            if fecha:
                d = (fecha - hoy).days
                if d < 0: cols[i % 4].error(f"❌ {name} VENCIDO\n({fecha})")
                elif d <= 15: cols[i % 4].warning(f"⚠️ {name}\n({fecha})")
                else: cols[i % 4].success(f"✅ {name}\n({fecha})")
            else: cols[i % 4].info(f"⚪ {name}: S/D")

# (Los módulos de Gastos, Flota, Tarifas y Usuarios siguen igual para no dañar nada)
elif menu == "💸 Gastos":
    st.title("💸 Registro de Gastos")
    v_data_g = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    with st.form("f_g"):
        v_sel = st.selectbox("Vehículo", v_data_g['placa'] if not v_data_g.empty else [])
        tipo = st.selectbox("Tipo", ["Combustible", "Mantenimiento", "Peaje", "Otros"])
        monto = st.number_input("Valor ($)", min_value=0); det = st.text_input("Detalle")
        if st.form_submit_button("💾 Guardar"):
            v_id = v_data_g[v_data_g['placa'] == v_sel]['id'].values[0]
            cur = conn.cursor(); cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", (int(v_id), tipo, monto, datetime.now().date(), det))
            conn.commit(); st.success("Gasto guardado"); st.rerun()

elif menu == "⚙️ Tarifas":
    st.title("⚙️ Precios")
    with st.form("f_t"):
        s = st.text_input("Servicio"); p = st.number_input("Precio ($)")
        if st.form_submit_button("Guardar"):
            cur = conn.cursor(); cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, p))
            conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT * FROM tarifario", conn))

elif menu == "🚐 Flota":
    st.title("🚐 Flota")
    with st.form("f_f"):
        p = st.text_input("Placa").upper(); m = st.text_input("Marca"); mod = st.text_input("Modelo"); cond = st.text_input("Conductor")
        if st.form_submit_button("➕ Añadir"):
            cur = conn.cursor(); cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s,%s,%s,%s)", (p, m, mod, cond))
            conn.commit(); st.rerun()
    st.dataframe(pd.read_sql("SELECT * FROM vehiculos", conn), use_container_width=True)

conn.close()
