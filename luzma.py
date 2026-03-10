import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
import plotly.express as px

# --- 1. CONFIGURACIÓN DE CONEXIÓN SEGURA ---
DB_URL = "postgresql://neondb_owner:npg_c7Dkwlh1jzGQ@ep-lucky-shadow-ac1thtiq-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require"

def conectar_db():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SET search_path TO public") # Asegura el esquema correcto siempre
    return conn

def inicializar_db():
    conn = conectar_db(); cur = conn.cursor()
    # Esquema de tablas respetando tu lógica
    cur.execute('CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, marca TEXT, modelo TEXT, conductor TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS ventas (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), cliente TEXT, valor_viaje NUMERIC, fecha DATE, descripcion TEXT, cantidad INTEGER)')
    cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)')
    cur.execute('''CREATE TABLE IF NOT EXISTS hoja_vida (
                    id SERIAL PRIMARY KEY, vehiculo_id INTEGER UNIQUE REFERENCES vehiculos(id), 
                    soat_vence DATE, tecno_vence DATE, prev_vence DATE,
                    p_contractual DATE, p_extracontractual DATE, p_todoriesgo DATE, t_operaciones DATE)''')
    cur.execute('CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, nombre TEXT, usuario TEXT UNIQUE NOT NULL, clave TEXT NOT NULL, rol TEXT DEFAULT "admin")')
    
    # Usuario por defecto
    cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Jacobo Admin', 'admin', 'Jacobo2026', 'admin') ON CONFLICT (usuario) DO NOTHING")
    
    conn.commit(); conn.close()

# --- 2. FUNCIONES DE APOYO (EXCEL) ---
def to_excel(df_balance, df_g, df_v):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_balance.to_excel(writer, index=False, sheet_name='Balance General')
        df_g.to_excel(writer, index=False, sheet_name='Detalle Gastos')
        df_v.to_excel(writer, index=False, sheet_name='Detalle Ventas')
    return output.getvalue()

st.set_page_config(page_title="C&E - Confejeans Luzma", layout="wide", page_icon="🧵")
inicializar_db()

# --- 3. SISTEMA DE LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.sidebar.title("🔐 Acceso")
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

# --- 4. MENÚ PRINCIPAL (7 VENTANAS) ---
st.sidebar.write(f"👋 **{st.session_state.u_name}**")
st.sidebar.divider()
target = st.sidebar.number_input("🎯 Meta Utilidad ($)", value=3000000, step=500000)
menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas", "⚙️ Usuarios"])

if st.sidebar.button("🚪 CERRAR SESIÓN"):
    st.session_state.logged_in = False; st.rerun()

conn = conectar_db()

# --- MÓDULO: DASHBOARD ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis de Operación")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    c1, c2 = st.columns(2)
    with c1: placa_f = st.selectbox("Vehículo:", ["TODOS"] + v_data['placa'].tolist())
    with c2: rango = st.date_input("Rango:", [datetime.now().date() - timedelta(days=30), datetime.now().date()])

    if len(rango) == 2:
        q_g = "SELECT g.fecha, v.placa, g.tipo_gasto as concepto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id WHERE g.fecha BETWEEN %s AND %s"
        q_v = "SELECT s.fecha, v.placa, s.cliente as concepto, s.valor_viaje as monto, s.descripcion as detalles, s.cantidad FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id WHERE s.fecha BETWEEN %s AND %s"
        params = [rango[0], rango[1]]
        if placa_f != "TODOS":
            q_g += " AND v.placa = %s"; q_v += " AND v.placa = %s"; params.append(placa_f)
        
        df_g = pd.read_sql(q_g, conn, params=params)
        df_v = pd.read_sql(q_v, conn, params=params)
        u_neta = df_v['monto'].sum() - df_g['monto'].sum()

        if u_neta >= target: st.success(f"### 🏆 ¡Meta Lograda! ${u_neta:,.0f}"); st.balloons()
        else: st.error(f"### ⚠️ Faltan ${abs(u_neta - target):,.0f} para la meta")

        m1, m2, m3 = st.columns(3)
        m1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
        m2.metric("Egresos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
        m3.metric("Utilidad Neta", f"${u_neta:,.0f}", delta=f"{u_neta-target:,.0f}")

        st.plotly_chart(px.bar(df_v.groupby('placa')['monto'].sum().reset_index(), x='placa', y='monto', title="Ventas por Placa"), use_container_width=True)
        st.download_button("📥 Reporte Excel", data=to_excel(df_v, df_g, df_v), file_name="Reporte_Luzma.xlsx")

# --- MÓDULO: VENTAS (CÁLCULO + EDICIÓN) ---
elif menu == "💰 Ventas":
    st.title("💰 Registro de Producción")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
    tab1, tab2 = st.tabs(["📝 Nuevo Registro", "✏️ Editar/Borrar"])
    
    with tab1:
        with st.form("f_v"):
            v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
            s_sel = st.selectbox("Servicio", t_data['servicio'].tolist() if not t_data.empty else [])
            cant = st.number_input("Cantidad", min_value=1)
            if not t_data.empty:
                val_u = t_data[t_data['servicio'] == s_sel]['precio_unidad'].values[0]
                total = float(cant * val_u)
                st.metric("💵 MONTO TOTAL CALCULADO", f"${total:,.0f}")
            desc = st.text_area("Detalles (Lote/Ref)")
            if st.form_submit_button("💰 Guardar"):
                v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                cur = conn.cursor(); cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, descripcion, cantidad) VALUES (%s,%s,%s,%s,%s,%s)", (int(v_id), s_sel, total, datetime.now().date(), desc, int(cant)))
                conn.commit(); st.rerun()
    with tab2:
        df_v = pd.read_sql("SELECT s.id, s.fecha, v.placa, s.cliente, s.valor_viaje as monto, s.descripcion FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.id DESC", conn)
        sel = st.dataframe(df_v, use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel.selection.rows) > 0:
            row = df_v.iloc[sel.selection.rows[0]]
            with st.form("f_edit_v"):
                n_m = st.number_input("Monto", value=float(row['monto']))
                n_d = st.text_area("Descripción", value=row['descripcion'])
                c1, c2 = st.columns(2)
                if c1.form_submit_button("✅ Actualizar"):
                    cur = conn.cursor(); cur.execute("UPDATE ventas SET valor_viaje=%s, descripcion=%s WHERE id=%s", (n_m, n_d, int(row['id']))); conn.commit(); st.rerun()
                if c2.form_submit_button("🗑️ Borrar"):
                    cur = conn.cursor(); cur.execute("DELETE FROM ventas WHERE id=%s", (int(row['id']),)); conn.commit(); st.rerun()

# --- MÓDULO: GASTOS (EDICIÓN) ---
elif menu == "💸 Gastos":
    st.title("💸 Gastos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    tab1, tab2 = st.tabs(["📝 Registro", "✏️ Editar/Borrar"])
    with tab1:
        with st.form("f_g"):
            v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
            tipo = st.selectbox("Tipo", ["Combustible", "Mantenimiento", "Otros"]); monto = st.number_input("Valor", min_value=0); det = st.text_input("Nota")
            if st.form_submit_button("💾 Guardar"):
                v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                cur = conn.cursor(); cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", (int(v_id), tipo, monto, datetime.now().date(), det))
                conn.commit(); st.rerun()
    with tab2:
        df_g = pd.read_sql("SELECT g.id, g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id ORDER BY g.id DESC", conn)
        sel = st.dataframe(df_g, use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel.selection.rows) > 0:
            row = df_g.iloc[sel.selection.rows[0]]
            with st.form("f_edit_g"):
                n_m = st.number_input("Monto", value=float(row['monto']))
                n_d = st.text_input("Nota", value=row['detalle'])
                c1, c2 = st.columns(2)
                if c1.form_submit_button("✅ Actualizar"):
                    cur = conn.cursor(); cur.execute("UPDATE gastos SET monto=%s, detalle=%s WHERE id=%s", (n_m, n_d, int(row['id']))); conn.commit(); st.rerun()
                if c2.form_submit_button("🗑️ Borrar"):
                    cur = conn.cursor(); cur.execute("DELETE FROM gastos WHERE id=%s", (int(row['id']),)); conn.commit(); st.rerun()

# --- MÓDULO: HOJA DE VIDA (ALERTAS FULL) ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Documentos y Alertas")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    with st.expander("📅 Actualizar Fechas"):
        with st.form("f_hv"):
            v_sel = st.selectbox("Vehículo", v_data['placa']); v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
            c1, c2 = st.columns(2)
            s_v = c1.date_input("SOAT"); t_v = c1.date_input("Tecno"); p_v = c1.date_input("Preventivo")
            pc_v = c2.date_input("P. Contractual"); pe_v = c2.date_input("P. Extra"); ptr_v = c2.date_input("Todo Riesgo"); to_v = st.date_input("T. Operaciones")
            if st.form_submit_button("🔄 Actualizar"):
                cur = conn.cursor(); cur.execute('''INSERT INTO hoja_vida (vehiculo_id, soat_vence, tecno_vence, prev_vence, p_contractual, p_extracontractual, p_todoriesgo, t_operaciones) 
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (vehiculo_id) DO UPDATE SET soat_vence=EXCLUDED.soat_vence, tecno_vence=EXCLUDED.tecno_vence, prev_vence=EXCLUDED.prev_vence, p_contractual=EXCLUDED.p_contractual, p_extracontractual=EXCLUDED.p_extracontractual, p_todoriesgo=EXCLUDED.p_todoriesgo, t_operaciones=EXCLUDED.t_operaciones''', (int(v_id), s_v, t_v, p_v, pc_v, pe_v, ptr_v, to_v))
                conn.commit(); st.rerun()
    
    df_hv = pd.read_sql('''SELECT v.placa, h.soat_vence, h.tecno_vence, h.prev_vence, h.p_contractual, h.p_extracontractual, h.p_todoriesgo, h.t_operaciones FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id''', conn)
    hoy = datetime.now().date()
    for _, row in df_hv.iterrows():
        st.subheader(f"Vehículo: {row['placa']}")
        cols = st.columns(4); docs = [("SOAT", row['soat_vence']), ("TECNO", row['tecno_vence']), ("PREV", row['prev_vence']), ("T.OPER", row['t_operaciones']), ("POL. CONT", row['p_contractual']), ("POL. EXTRA", row['p_extracontractual']), ("TODO RIESGO", row['p_todoriesgo'])]
        for i, (name, fecha) in enumerate(docs):
            if fecha:
                d = (fecha - hoy).days
                if d < 0: cols[i%4].error(f"❌ {name} VENCIDO\n({fecha})")
                elif d <= 15: cols[i%4].warning(f"⚠️ {name}\n({fecha})")
                else: cols[i%4].success(f"✅ {name}\n({fecha})")
            else: cols[i%4].info(f"⚪ {name}: S/D")

# --- MÓDULO: TARIFAS ---
elif menu == "⚙️ Tarifas":
    st.title("⚙️ Precios por Servicio")
    with st.form("f_t"):
        s = st.text_input("Servicio"); p = st.number_input("Precio ($)")
        if st.form_submit_button("Guardar"):
            cur = conn.cursor(); cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, p))
            conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT * FROM tarifario", conn))

# --- MÓDULO: FLOTA Y USUARIOS ---
elif menu == "🚐 Flota":
    st.title("🚐 Flota")
    with st.form("f_f"):
        p = st.text_input("Placa").upper(); m = st.text_input("Marca"); mod = st.text_input("Modelo"); cond = st.text_input("Conductor")
        if st.form_submit_button("➕ Añadir"):
            cur = conn.cursor(); cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s,%s,%s,%s)", (p, m, mod, cond))
            conn.commit(); st.rerun()
    st.dataframe(pd.read_sql("SELECT * FROM vehiculos", conn), use_container_width=True)

elif menu == "⚙️ Usuarios" and st.session_state.u_rol == "admin":
    st.title("⚙️ Usuarios")
    with st.form("f_u"):
        nom = st.text_input("Nombre"); u = st.text_input("Usuario"); c = st.text_input("Clave")
        if st.form_submit_button("👤 Crear"):
            cur = conn.cursor(); cur.execute("INSERT INTO usuarios (nombre, usuario, clave) VALUES (%s,%s,%s)", (nom, u, c))
            conn.commit(); st.success("Creado")

conn.close()
