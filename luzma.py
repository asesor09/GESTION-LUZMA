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

# --- 🧠 IA OCR PARA RECIBOS ---
def extraer_monto_ia(imagen_file):
    try:
        img = Image.open(imagen_file).convert('L')
        img = ImageOps.autocontrast(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        texto = pytesseract.image_to_string(img, config='--psm 6').upper()
        limpio = re.sub(r'\D', ' ', texto)
        nums = [int(s) for s in limpio.split() if 4 <= len(s) <= 8]
        return max(nums) if nums else 0
    except: return 0

# --- 🗄️ INICIALIZACIÓN DE TODAS LAS TABLAS ---
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
    st.title("🚐 Sistema de Gestión Luzma")
    u, p = st.text_input("Usuario"), st.text_input("Clave", type="password")
    if st.button("Ingresar"):
        conn = conectar_db(); cur = conn.cursor()
        cur.execute("SELECT nombre, rol FROM usuarios WHERE usuario = %s AND clave = %s", (u, p))
        res = cur.fetchone(); conn.close()
        if res:
            st.session_state.logged_in, st.session_state.u_name, st.session_state.u_rol = True, res[0], res[1]
            st.rerun()
        else: st.error("Usuario o clave incorrectos")
    st.stop()

# --- 🚀 MENÚ POR ROL ---
st.sidebar.write(f"👤 **{st.session_state.u_name}**")
if st.session_state.u_rol == "admin":
    target = st.sidebar.number_input("🎯 Meta Utilidad ($)", value=5000000, step=500000)
    menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos con IA", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Usuarios", "⚙️ Tarifas"])
else:
    menu = "📸 MODO CONDUCTOR"
    st.sidebar.warning("Acceso limitado: Registro de Gastos")

if st.sidebar.button("🚪 Cerrar Sesión"): st.session_state.logged_in = False; st.rerun()

conn = conectar_db()
if not conn: st.stop()

# --- 📊 DASHBOARD (FILTROS COMPLETOS) ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis de Operación")
    v_list = pd.read_sql("SELECT placa FROM vehiculos", conn)['placa'].tolist()
    c1, c2 = st.columns(2)
    with c1: placa_f = st.selectbox("🎯 Filtrar por Vehículo:", ["TODOS"] + v_list)
    with c2: rango = st.date_input("📅 Rango de Fechas:", [datetime.now().date() - timedelta(days=30), datetime.now().date()])

    if len(rango) == 2:
        q_v = "SELECT s.fecha, v.placa, s.cliente, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id WHERE s.fecha BETWEEN %s AND %s"
        q_g = "SELECT g.fecha, v.placa, g.tipo_gasto as concepto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id WHERE g.fecha BETWEEN %s AND %s"
        params = [rango[0], rango[1]]
        if placa_f != "TODOS":
            q_v += " AND v.placa = %s"; q_g += " AND v.placa = %s"; params.append(placa_f)
        
        df_v, df_g = pd.read_sql(q_v, conn, params=params), pd.read_sql(q_g, conn, params=params)
        utilidad = df_v['monto'].sum() - df_g['monto'].sum()
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
        m2.metric("Egresos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
        m3.metric("Utilidad Neta", f"${utilidad:,.0f}", delta=f"{utilidad-target:,.0f}")

        res_v = df_v.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Venta'})
        res_g = df_g.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Gasto'})
        balance_df = pd.merge(res_v, res_g, on='placa', how='outer').fillna(0)
        balance_df[['Venta', 'Gasto']] = balance_df[['Venta', 'Gasto']].apply(pd.to_numeric)
        st.plotly_chart(px.bar(balance_df, x='placa', y=['Venta', 'Gasto'], barmode='group'), use_container_width=True)

        with st.expander("🔍 Ver Detalles"):
            st.write("**Ventas Detalladas:**"); st.dataframe(df_v, use_container_width=True)
            st.write("**Gastos Detallados:**"); st.dataframe(df_g, use_container_width=True)
        st.download_button("📥 Excel Completo", generar_excel(df_v, df_g, balance_df), "Reporte_Luzma.xlsx")

# --- 🚐 MÓDULO: FLOTA (EDICIÓN DE TODOS LOS CAMPOS) ---
elif menu == "🚐 Flota":
    st.title("🚐 Administración de Vehículos")
    t1, t2 = st.tabs(["➕ Añadir", "✏️ Editar/Borrar"])
    with t1:
        with st.form("new_v"):
            p, ma, mo, co = st.text_input("Placa"), st.text_input("Marca"), st.text_input("Modelo"), st.text_input("Conductor")
            if st.form_submit_button("Guardar"):
                cur = conn.cursor(); cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s,%s,%s,%s)", (p.upper(), ma, mo, co))
                conn.commit(); st.rerun()
    with t2:
        df_f = pd.read_sql("SELECT * FROM vehiculos", conn)
        sel = st.dataframe(df_f, use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel.selection.rows) > 0:
            row = df_f.iloc[sel.selection.rows[0]]
            with st.form("ed_v"):
                n_p = st.text_input("Placa", row['placa'])
                n_ma = st.text_input("Marca", row['marca'])
                n_mo = st.text_input("Modelo", row['modelo'])
                n_co = st.text_input("Conductor", row['conductor'])
                if st.form_submit_button("✅ Actualizar Todo"):
                    cur = conn.cursor(); cur.execute("UPDATE vehiculos SET placa=%s, marca=%s, modelo=%s, conductor=%s WHERE id=%s", (n_p.upper(), n_ma, n_mo, n_co, int(row['id'])))
                    conn.commit(); st.rerun()

# --- 💸 MÓDULO: GASTOS (IA + IMAGEN DB + EDICIÓN TOTAL) ---
elif menu in ["💸 Gastos con IA", "📸 MODO CONDUCTOR"]:
    st.title("📸 Registro y Gestión de Gastos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    if st.session_state.u_rol == "admin":
        tg1, tg2 = st.tabs(["📝 Cargar Gasto", "✏️ Editar/Ver Imagen"])
    else: tg1 = st.container()

    with tg1:
        st.write("### 📸 Carga de Recibo")
        foto = st.file_uploader("Suba la foto (Vista Amplia)", type=['jpg','png','jpeg'])
        if foto:
            st.image(foto, use_container_width=True)
            if st.button("🔍 ESCANEAR CON IA"): st.session_state.monto_ia = extraer_monto_ia(foto)
        
        with st.form("g_form"):
            v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
            tipo = st.selectbox("Concepto", ["Combustible", "Peaje", "Mantenimiento", "Viáticos", "Otros"])
            monto = st.number_input("Monto Detectado ($)", value=float(st.session_state.get('monto_ia', 0.0)))
            f_gasto = st.date_input("Fecha Gasto", datetime.now().date())
            det = st.text_input("Nota")
            if st.form_submit_button("💾 GUARDAR GASTO"):
                v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                cur = conn.cursor()
                cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle, imagen) VALUES (%s,%s,%s,%s,%s,%s)", (int(v_id), tipo, monto, f_gasto, det, foto.getvalue() if foto else None))
                conn.commit(); st.session_state.monto_ia = 0; st.success("Gasto guardado"); st.rerun()

    if st.session_state.u_rol == "admin":
        with tg2:
            df_g = pd.read_sql("SELECT g.*, v.placa FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id ORDER BY g.fecha DESC", conn)
            sel_g = st.dataframe(df_g.drop(columns=['imagen']), use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
            if len(sel_g.selection.rows) > 0:
                rg = df_g.iloc[sel_g.selection.rows[0]]
                # --- CORRECCIÓN DE IMAGEN ---
                if rg['imagen']: st.image(io.BytesIO(rg['imagen']), width=400, caption="Recibo Original")
                with st.form("ed_g"):
                    n_m = st.number_input("Monto", value=float(rg['monto']))
                    n_f = st.date_input("Fecha", rg['fecha'])
                    n_t = st.selectbox("Tipo", ["Combustible", "Peaje", "Mantenimiento", "Viáticos", "Otros"], index=["Combustible", "Peaje", "Mantenimiento", "Viáticos", "Otros"].index(rg['tipo_gasto']))
                    n_d = st.text_input("Detalle", rg['detalle'])
                    if st.form_submit_button("✅ Actualizar Todos los Datos"):
                        cur = conn.cursor(); cur.execute("UPDATE gastos SET monto=%s, fecha=%s, tipo_gasto=%s, detalle=%s WHERE id=%s", (n_m, n_f, n_t, n_d, int(rg['id'])))
                        conn.commit(); st.rerun()

# --- 💰 MÓDULO: VENTAS (EDICIÓN TOTAL) ---
elif menu == "💰 Ventas":
    st.title("💰 Gestión de Producción")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
    tv1, tv2 = st.tabs(["💰 Nueva Venta", "✏️ Editar Registros"])
    with tv1:
        with st.form("v_new"):
            v_s = st.selectbox("Vehículo", v_data['placa'])
            s_s = st.selectbox("Servicio", t_data['servicio'].tolist())
            cant = st.number_input("Cantidad", min_value=1)
            f_v = st.date_input("Fecha Venta", datetime.now().date())
            if st.form_submit_button("💰 Registrar Venta"):
                v_id = v_data[v_data['placa'] == v_s]['id'].values[0]
                pr = float(t_data[t_data['servicio'] == s_s]['precio_unidad'].values[0])
                cur = conn.cursor(); cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, cantidad) VALUES (%s,%s,%s,%s,%s)", (int(v_id), s_s, pr*cant, f_v, cant))
                conn.commit(); st.rerun()
    with tv2:
        df_v = pd.read_sql("SELECT s.id, v.placa, s.cliente, s.valor_viaje, s.fecha, s.cantidad FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.fecha DESC", conn)
        sel_v = st.dataframe(df_v, use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel_v.selection.rows) > 0:
            rv = df_v.iloc[sel_v.selection.rows[0]]
            with st.form("ed_v"):
                en_c = st.text_input("Servicio/Cliente", rv['cliente'])
                en_v = st.number_input("Valor Total", value=float(rv['valor_viaje']))
                en_f = st.date_input("Fecha", rv['fecha'])
                if st.form_submit_button("✅ Actualizar Venta"):
                    cur = conn.cursor(); cur.execute("UPDATE ventas SET cliente=%s, valor_viaje=%s, fecha=%s WHERE id=%s", (en_c, en_v, en_f, int(rv['id'])))
                    conn.commit(); st.rerun()

# --- 📑 HOJA DE VIDA (SOLUCIÓN TYPEERROR + TODOS LOS DOCUMENTOS) ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Vencimientos de Documentos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    with st.expander("📅 Actualizar Fechas de Vencimiento"):
        with st.form("hv_form"):
            v_sel = st.selectbox("Vehículo", v_data['placa'])
            v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
            c1, c2 = st.columns(2)
            s, t, p = c1.date_input("SOAT"), c1.date_input("Tecno"), c1.date_input("Prev")
            pc, pe, ptr = c2.date_input("P. Contractual"), c2.date_input("P. Extra"), c2.date_input("Todo Riesgo")
            to = st.date_input("T. Operaciones")
            if st.form_submit_button("🔄 Actualizar Documentación"):
                cur = conn.cursor(); cur.execute('''INSERT INTO hoja_vida (vehiculo_id, soat_vence, tecno_vence, prev_vence, p_contractual, p_extracontractual, p_todoriesgo, t_operaciones) 
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (vehiculo_id) DO UPDATE SET soat_vence=EXCLUDED.soat_vence, tecno_vence=EXCLUDED.tecno_vence, prev_vence=EXCLUDED.prev_vence, 
                    p_contractual=EXCLUDED.p_contractual, p_extracontractual=EXCLUDED.p_extracontractual, p_todoriesgo=EXCLUDED.p_todoriesgo, t_operaciones=EXCLUDED.t_operaciones''', (int(v_id), s, t, p, pc, pe, ptr, to))
                conn.commit(); st.rerun()

    df_hv = pd.read_sql("SELECT v.placa, h.* FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id", conn)
    hoy = datetime.now().date()
    for _, row in df_hv.iterrows():
        st.subheader(f"🚚 {row['placa']}")
        cols = st.columns(4)
        docs = [("SOAT", row.get('soat_vence')), ("TECNO", row.get('tecno_vence')), ("PREV", row.get('prev_vence')), ("T.OPER", row.get('t_operaciones')), ("P.CONT", row.get('p_contractual')), ("P.EXTRA", row.get('p_extracontractual')), ("RIESGO", row.get('p_todoriesgo'))]
        for i, (name, f) in enumerate(docs):
            idx = i % 4
            if f and pd.notnull(f):
                try:
                    d = (pd.to_datetime(f).date() - hoy).days
                    if d < 0: cols[idx].error(f"❌ {name}")
                    elif d <= 15: cols[idx].warning(f"⚠️ {name} ({d}d)")
                    else: cols[idx].success(f"✅ {name}")
                except: cols[idx].info(f"⚪ {name}")
            else: cols[idx].info(f"⚪ {name}")
        st.divider()

# --- ⚙️ USUARIOS Y TARIFAS ---
elif menu == "⚙️ Usuarios":
    st.title("⚙️ Personal")
    with st.form("u_f"):
        nom, usr, clv, rol = st.text_input("Nombre"), st.text_input("User"), st.text_input("Clave"), st.selectbox("Rol", ["admin", "conductor"])
        if st.form_submit_button("Crear"):
            cur = conn.cursor(); cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES (%s,%s,%s,%s)", (nom, usr, clv, rol))
            conn.commit(); st.success("Creado")
    st.table(pd.read_sql("SELECT nombre, usuario, rol FROM usuarios", conn))

elif menu == "⚙️ Tarifas":
    st.title("⚙️ Precios")
    with st.form("t_f"):
        se, pr = st.text_input("Servicio"), st.number_input("Precio")
        if st.form_submit_button("Guardar"):
            cur = conn.cursor(); cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (se, pr))
            conn.commit(); st.success("Tarifa guardada")
    st.table(pd.read_sql("SELECT * FROM tarifario", conn))

if conn: conn.close()
