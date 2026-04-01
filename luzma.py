import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
from PIL import Image, ImageOps, ImageEnhance
import pytesseract
import re
import plotly.express as px

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Confejeans Luzma - Gestión de Flota", layout="wide", page_icon="🚐")

def conectar_db():
    try:
        return psycopg2.connect(st.secrets["url_luzma"])
    except Exception as e:
        st.error(f"❌ Error de conexión: {e}")
        return None

def generar_excel(df_v, df_g, df_balance):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_balance.to_excel(writer, index=False, sheet_name='Balance_General')
        df_v.to_excel(writer, index=False, sheet_name='Ventas')
        df_g.to_excel(writer, index=False, sheet_name='Gastos')
    return output.getvalue()

# --- 🧠 IA OCR ---
def extraer_monto_ia(imagen_file):
    try:
        img = Image.open(imagen_file).convert('L')
        img = ImageOps.autocontrast(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        texto = pytesseract.image_to_string(img, config='--psm 6').upper()
        limpio = re.sub(r'\D', ' ', texto)
        nums = [int(s) for s in limpio.split() if 4 <= len(s) <= 7]
        return max(nums) if nums else 0
    except: return 0

# --- 🗄️ INICIALIZACIÓN (SIN BORRAR CAMPOS) ---
def inicializar_db():
    conn = conectar_db()
    if conn:
        cur = conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, marca TEXT, modelo TEXT, conductor TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT, imagen BYTEA)')
        cur.execute('CREATE TABLE IF NOT EXISTS ventas (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), cliente TEXT, valor_viaje NUMERIC, fecha DATE, descripcion TEXT, cantidad INTEGER)')
        cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)')
        cur.execute('''CREATE TABLE IF NOT EXISTS hoja_vida (id SERIAL PRIMARY KEY, vehiculo_id INTEGER UNIQUE REFERENCES vehiculos(id), 
                        soat_vence DATE, tecno_vence DATE, prev_vence DATE, p_contractual DATE, p_extracontractual DATE, p_todoriesgo DATE, t_operaciones DATE)''')
        cur.execute('CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, nombre TEXT, usuario TEXT UNIQUE NOT NULL, clave TEXT NOT NULL, rol TEXT DEFAULT "conductor")')
        cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Admin', 'admin', 'Luzma2026', 'admin') ON CONFLICT (usuario) DO UPDATE SET clave = EXCLUDED.clave")
        conn.commit(); conn.close()

inicializar_db()

# --- 🔐 LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🔐 Acceso Sistema Luzma")
    u, p = st.text_input("Usuario"), st.text_input("Clave", type="password")
    if st.button("Ingresar"):
        conn = conectar_db(); cur = conn.cursor()
        cur.execute("SELECT nombre, rol FROM usuarios WHERE usuario = %s AND clave = %s", (u, p))
        res = cur.fetchone(); conn.close()
        if res:
            st.session_state.logged_in, st.session_state.u_name, st.session_state.u_rol = True, res[0], res[1]
            st.rerun()
        else: st.error("Acceso incorrecto")
    st.stop()

# --- 🚀 MENÚ ---
st.sidebar.write(f"👤 **{st.session_state.u_name}**")
if st.session_state.u_rol == "admin":
    target = st.sidebar.number_input("🎯 Meta Utilidad ($)", value=5000000, step=500000)
    menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos con IA", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Usuarios", "⚙️ Tarifas"])
else:
    menu = "💸 Gastos con IA"
    st.sidebar.info("Modo Conductor: Solo carga de recibos.")

if st.sidebar.button("🚪 Salir"): st.session_state.logged_in = False; st.rerun()

conn = conectar_db()
if not conn: st.stop()

# --- 📊 DASHBOARD (CON FILTROS DE CARRO Y FECHA) ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis de Operación")
    v_list = pd.read_sql("SELECT placa FROM vehiculos", conn)['placa'].tolist()
    
    col_f1, col_f2 = st.columns(2)
    with col_f1: placa_f = st.selectbox("🎯 Filtrar por Vehículo:", ["TODOS"] + v_list)
    with col_f2: rango = st.date_input("📅 Rango de Fechas:", [datetime.now().date() - timedelta(days=30), datetime.now().date()])

    if len(rango) == 2:
        q_v = "SELECT s.fecha, v.placa, s.cliente, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id WHERE s.fecha BETWEEN %s AND %s"
        q_g = "SELECT g.fecha, v.placa, g.tipo_gasto as concepto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id WHERE g.fecha BETWEEN %s AND %s"
        params = [rango[0], rango[1]]
        if placa_f != "TODOS":
            q_v += " AND v.placa = %s"; q_g += " AND v.placa = %s"; params.append(placa_f)
        
        df_v, df_g = pd.read_sql(q_v, conn, params=params), pd.read_sql(q_g, conn, params=params)
        utilidad = df_v['monto'].sum() - df_g['monto'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
        c2.metric("Egresos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
        c3.metric("Utilidad", f"${utilidad:,.0f}", delta=f"{utilidad-target:,.0f}")

        st.subheader("📈 Comparativa Venta vs Gasto")
        res_v = df_v.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Venta'})
        res_g = df_g.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Gasto'})
        balance_df = pd.merge(res_v, res_g, on='placa', how='outer').fillna(0)
        balance_df[['Venta', 'Gasto']] = balance_df[['Venta', 'Gasto']].apply(pd.to_numeric)
        fig = px.bar(balance_df, x='placa', y=['Venta', 'Gasto'], barmode='group', color_discrete_map={'Venta': '#2ecc71', 'Gasto': '#e74c3c'})
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("🔍 Ver Detalles"):
            st.write("**Ventas:**"); st.dataframe(df_v, use_container_width=True, hide_index=True)
            st.write("**Gastos:**"); st.dataframe(df_g, use_container_width=True, hide_index=True)
        st.download_button("📥 Excel", generar_excel(df_v, df_g, balance_df), "Reporte.xlsx")

# --- 🚐 FLOTA (CON EDICIÓN) ---
elif menu == "🚐 Flota":
    st.title("🚐 Flota")
    t1, t2 = st.tabs(["➕ Añadir", "✏️ Editar/Borrar"])
    with t1:
        with st.form("f_new"):
            pl, ma, mo, co = st.text_input("Placa"), st.text_input("Marca"), st.text_input("Modelo"), st.text_input("Conductor")
            if st.form_submit_button("Guardar"):
                cur = conn.cursor(); cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s,%s,%s,%s)", (pl.upper(), ma, mo, co))
                conn.commit(); st.rerun()
    with t2:
        df_f = pd.read_sql("SELECT * FROM vehiculos", conn)
        sel = st.dataframe(df_f, use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel.selection.rows) > 0:
            row = df_f.iloc[sel.selection.rows[0]]
            with st.form("f_ed"):
                n_ma, n_mo, n_co = st.text_input("Marca", row['marca']), st.text_input("Modelo", row['modelo']), st.text_input("Conductor", row['conductor'])
                c_f1, c_f2 = st.columns(2)
                if c_f1.form_submit_button("✅ Actualizar"):
                    cur = conn.cursor(); cur.execute("UPDATE vehiculos SET marca=%s, modelo=%s, conductor=%s WHERE id=%s", (n_ma, n_mo, n_co, int(row['id'])))
                    conn.commit(); st.rerun()
                if c_f2.form_submit_button("🗑️ Borrar"):
                    cur = conn.cursor(); cur.execute("DELETE FROM vehiculos WHERE id=%s", (int(row['id']),))
                    conn.commit(); st.rerun()

# --- 💸 GASTOS CON IA ---
elif menu == "💸 Gastos con IA":
    st.title("💸 Registro de Gastos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t1, t2 = st.tabs(["📝 Nuevo", "✏️ Gestionar"])
    with t1:
        col_ia1, col_ia2 = st.columns(2)
        with col_ia1:
            foto = st.file_uploader("📸 Recibo", type=['jpg','png','jpeg'])
            if foto and st.button("🔍 Escanear"): st.session_state.monto_ia = extraer_monto_ia(foto)
            if foto: st.image(foto, width=250)
        with col_ia2:
            with st.form("g_new"):
                v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
                monto = st.number_input("Monto ($)", value=float(st.session_state.get('monto_ia', 0.0)))
                det = st.text_input("Nota")
                if st.form_submit_button("💾 Guardar"):
                    v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                    cur = conn.cursor(); cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle, imagen) VALUES (%s,'Otros',%s,%s,%s,%s)", (int(v_id), monto, datetime.now().date(), det, foto.getvalue() if foto else None))
                    conn.commit(); st.session_state.monto_ia = 0; st.success("Guardado"); st.rerun()
    with t2:
        df_g = pd.read_sql("SELECT g.id, g.fecha, v.placa, g.monto, g.detalle, g.imagen FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id ORDER BY g.id DESC", conn)
        sel_g = st.dataframe(df_g.drop(columns=['imagen']), use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel_g.selection.rows) > 0:
            row_g = df_g.iloc[sel_g.selection.rows[0]]
            if row_g['imagen']: st.image(row_g['imagen'], width=200)
            if st.button("🗑️ Eliminar"):
                cur = conn.cursor(); cur.execute("DELETE FROM gastos WHERE id=%s", (int(row_g['id']),))
                conn.commit(); st.rerun()

# --- 💰 VENTAS ---
elif menu == "💰 Ventas":
    st.title("💰 Ventas")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_v1, t_v2 = st.tabs(["💰 Nueva", "✏️ Editar"])
    with t_v1:
        t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
        with st.form("v_new"):
            v_sel = st.selectbox("Vehículo", v_data['placa'])
            serv = st.selectbox("Servicio", t_data['servicio'].tolist() if not t_data.empty else [])
            cant = st.number_input("Cantidad", min_value=1)
            if st.form_submit_button("💰 Registrar"):
                v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                precio = float(t_data[t_data['servicio'] == serv]['precio_unidad'].values[0])
                cur = conn.cursor(); cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, cantidad) VALUES (%s,%s,%s,%s,%s)", (int(v_id), serv, cant*precio, datetime.now().date(), cant))
                conn.commit(); st.rerun()
    with t_v2:
        df_v = pd.read_sql("SELECT s.id, s.fecha, v.placa, s.cliente, s.valor_viaje FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.id DESC", conn)
        sel_v = st.dataframe(df_v, use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel_v.selection.rows) > 0:
            if st.button("🗑️ Eliminar Venta"):
                cur = conn.cursor(); cur.execute("DELETE FROM ventas WHERE id=%s", (int(df_v.iloc[sel_v.selection.rows[0]]['id']),))
                conn.commit(); st.rerun()

# --- 📑 HOJA DE VIDA (BLINDADA CONTRA TYPEERROR) ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Vencimientos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    with st.expander("📅 Actualizar Fechas"):
        with st.form("f_hv"):
            v_sel = st.selectbox("Vehículo", v_data['placa'])
            v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
            c1, c2 = st.columns(2)
            s_v, t_v, p_v = c1.date_input("SOAT"), c1.date_input("Tecno"), c1.date_input("Preventivo")
            pc_v, pe_v, ptr_v = c2.date_input("Pol. Contractual"), c2.date_input("Pol. Extra"), c2.date_input("Todo Riesgo")
            to_v = st.date_input("Tarjeta Operaciones")
            if st.form_submit_button("🔄 Actualizar"):
                cur = conn.cursor()
                cur.execute('''INSERT INTO hoja_vida (vehiculo_id, soat_vence, tecno_vence, prev_vence, p_contractual, p_extracontractual, p_todoriesgo, t_operaciones) 
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (vehiculo_id) DO UPDATE SET 
                               soat_vence=EXCLUDED.soat_vence, tecno_vence=EXCLUDED.tecno_vence, prev_vence=EXCLUDED.prev_vence,
                               p_contractual=EXCLUDED.p_contractual, p_extracontractual=EXCLUDED.p_extracontractual, 
                               p_todoriesgo=EXCLUDED.p_todoriesgo, t_operaciones=EXCLUDED.t_operaciones''', (int(v_id), s_v, t_v, p_v, pc_v, pe_v, ptr_v, to_v))
                conn.commit(); st.rerun()

    df_hv = pd.read_sql("SELECT v.placa, h.* FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id", conn)
    hoy = datetime.now().date()
    for _, row in df_hv.iterrows():
        st.subheader(f"🚚 {row['placa']}")
        cols = st.columns(4)
        docs = [("SOAT", row['soat_vence']), ("TECNO", row['tecno_vence']), ("PREV", row['prev_vence']), ("T.OPER", row['t_operaciones']), ("P.CONT", row['p_contractual']), ("P.EXTRA", row['p_extracontractual']), ("RIESGO", row['p_todoriesgo'])]
        for i, (name, f) in enumerate(docs):
            c_idx = i % 4
            if f and pd.notnull(f): # Validación de seguridad
                try:
                    dias = (f - hoy).days
                    if dias < 0: cols[c_idx].error(f"❌ {name}")
                    elif dias <= 15: cols[c_idx].warning(f"⚠️ {name} ({dias}d)")
                    else: cols[c_idx].success(f"✅ {name}")
                except: cols[c_idx].info(f"⚪ {name}")
            else: cols[c_idx].info(f"⚪ {name}")
        st.divider()

# --- ⚙️ USUARIOS ---
elif menu == "⚙️ Usuarios":
    st.title("⚙️ Usuarios")
    with st.form("u_form"):
        nom, usr, clv, rol = st.text_input("Nombre"), st.text_input("Usuario"), st.text_input("Clave"), st.selectbox("Rol", ["admin", "conductor"])
        if st.form_submit_button("Crear"):
            cur = conn.cursor(); cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES (%s,%s,%s,%s)", (nom, usr, clv, rol))
            conn.commit(); st.success("Creado")
    st.table(pd.read_sql("SELECT nombre, usuario, rol FROM usuarios", conn))

if conn: conn.close()
