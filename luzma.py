import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
from PIL import Image, ImageOps, ImageEnhance
import pytesseract
import re
import plotly.express as px

# --- 1. CONFIGURACIÓN Y CONEXIÓN ---
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
        nums = [int(s) for s in limpio.split() if 4 <= len(s) <= 7]
        return max(nums) if nums else 0
    except: return 0

# --- 🗄️ INICIALIZACIÓN DE TABLAS (SIN OMITIR NADA) ---
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
        else: st.error("Usuario o clave incorrectos")
    st.stop()

# --- 🚀 MENÚ ---
st.sidebar.write(f"👤 **{st.session_state.u_name}**")
if st.session_state.u_rol == "admin":
    menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos con IA", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Usuarios", "⚙️ Tarifas"])
else:
    menu = "💸 Gastos con IA" # Conductor solo carga gastos
    st.sidebar.info("Modo Conductor: Registro de gastos activo.")

if st.sidebar.button("🚪 Salir"): st.session_state.logged_in = False; st.rerun()

conn = conectar_db()
if not conn: st.stop()

# --- 📊 MÓDULO: DASHBOARD ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis de Operación")
    v_list = pd.read_sql("SELECT placa FROM vehiculos", conn)['placa'].tolist()
    c1, c2 = st.columns(2)
    with c1: placa_f = st.selectbox("🎯 Vehículo:", ["TODOS"] + v_list)
    with c2: rango = st.date_input("📅 Rango:", [datetime.now().date() - timedelta(days=30), datetime.now().date()])

    if len(rango) == 2:
        q_v = "SELECT s.fecha, v.placa, s.cliente, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id WHERE s.fecha BETWEEN %s AND %s"
        q_g = "SELECT g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id WHERE g.fecha BETWEEN %s AND %s"
        params = [rango[0], rango[1]]
        if placa_f != "TODOS":
            q_v += " AND v.placa = %s"; q_g += " AND v.placa = %s"; params.append(placa_f)
        
        df_v, df_g = pd.read_sql(q_v, conn, params=params), pd.read_sql(q_g, conn, params=params)
        utilidad = df_v['monto'].sum() - df_g['monto'].sum()
        
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
        col_m2.metric("Egresos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
        col_m3.metric("Utilidad Neta", f"${utilidad:,.0f}")

        st.subheader("📈 Comparativa")
        res_v = df_v.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Venta'})
        res_g = df_g.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Gasto'})
        balance_df = pd.merge(res_v, res_g, on='placa', how='outer').fillna(0)
        balance_df[['Venta', 'Gasto']] = balance_df[['Venta', 'Gasto']].apply(pd.to_numeric)
        st.plotly_chart(px.bar(balance_df, x='placa', y=['Venta', 'Gasto'], barmode='group'), use_container_width=True)

        with st.expander("🔍 Ver Detalles"):
            st.write("**Ventas:**"); st.dataframe(df_v, use_container_width=True, hide_index=True)
            st.write("**Gastos:**"); st.dataframe(df_g, use_container_width=True, hide_index=True)
        st.download_button("📥 Excel", generar_excel(df_v, df_g, balance_df), "Reporte_Luzma.xlsx")

# --- 🚐 MÓDULO: FLOTA (EDICIÓN TOTAL) ---
elif menu == "🚐 Flota":
    st.title("🚐 Administración de Vehículos")
    tab1, tab2 = st.tabs(["➕ Añadir Vehículo", "✏️ Gestionar Flota"])
    with tab1:
        with st.form("new_v"):
            p, ma, mo, co = st.text_input("Placa"), st.text_input("Marca"), st.text_input("Modelo"), st.text_input("Conductor")
            if st.form_submit_button("Guardar"):
                cur = conn.cursor(); cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s,%s,%s,%s)", (p.upper(), ma, mo, co))
                conn.commit(); st.rerun()
    with tab2:
        df_f = pd.read_sql("SELECT * FROM vehiculos", conn)
        sel = st.dataframe(df_f, use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel.selection.rows) > 0:
            row = df_f.iloc[sel.selection.rows[0]]
            with st.form("edit_v"):
                e_p = st.text_input("Placa", row['placa'])
                e_ma = st.text_input("Marca", row['marca'])
                e_mo = st.text_input("Modelo", row['modelo'])
                e_co = st.text_input("Conductor", row['conductor'])
                c1, c2 = st.columns(2)
                if c1.form_submit_button("✅ Actualizar"):
                    cur = conn.cursor(); cur.execute("UPDATE vehiculos SET placa=%s, marca=%s, modelo=%s, conductor=%s WHERE id=%s", (e_p.upper(), e_ma, e_mo, e_co, int(row['id'])))
                    conn.commit(); st.rerun()
                if c2.form_submit_button("🗑️ Eliminar"):
                    cur = conn.cursor(); cur.execute("DELETE FROM vehiculos WHERE id=%s", (int(row['id']),))
                    conn.commit(); st.rerun()

# --- 💸 MÓDULO: GASTOS (CON IA Y EDICIÓN DE TODO) ---
elif menu == "💸 Gastos con IA":
    st.title("💸 Gestión de Gastos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    tab_g1, tab_g2 = st.tabs(["📝 Registro", "✏️ Editar/Borrar"])
    with tab_g1:
        col_ia1, col_ia2 = st.columns(2)
        with col_ia1:
            foto = st.file_uploader("📸 Recibo", type=['jpg','png','jpeg'])
            if foto and st.button("🔍 Escanear"): st.session_state.monto_ia = extraer_monto_ia(foto)
            if foto: st.image(foto, width=250)
        with col_ia2:
            with st.form("g_new"):
                v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
                tipo = st.selectbox("Concepto", ["Combustible", "Peaje", "Mantenimiento", "Viáticos", "Otros"])
                monto = st.number_input("Valor ($)", value=float(st.session_state.get('monto_ia', 0.0)))
                det = st.text_input("Detalle")
                if st.form_submit_button("💾 Guardar"):
                    v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                    cur = conn.cursor(); cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle, imagen) VALUES (%s,%s,%s,%s,%s,%s)", (int(v_id), tipo, monto, datetime.now().date(), det, foto.getvalue() if foto else None))
                    conn.commit(); st.session_state.monto_ia = 0; st.success("Guardado"); st.rerun()
    with tab_g2:
        df_g = pd.read_sql("SELECT g.id, g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle, g.imagen FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id ORDER BY g.id DESC", conn)
        sel_g = st.dataframe(df_g.drop(columns=['imagen']), use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel_g.selection.rows) > 0:
            row_g = df_g.iloc[sel_g.selection.rows[0]]
            if row_g['imagen']: st.image(row_g['imagen'], width=200)
            with st.form("edit_g"):
                en_m = st.number_input("Monto", value=float(row_g['monto']))
                en_d = st.text_input("Detalle", value=row_g['detalle'])
                en_t = st.selectbox("Concepto", ["Combustible", "Peaje", "Mantenimiento", "Viáticos", "Otros"], index=["Combustible", "Peaje", "Mantenimiento", "Viáticos", "Otros"].index(row_g['tipo_gasto']))
                c1, c2 = st.columns(2)
                if c1.form_submit_button("✅ Actualizar"):
                    cur = conn.cursor(); cur.execute("UPDATE gastos SET monto=%s, detalle=%s, tipo_gasto=%s WHERE id=%s", (en_m, en_d, en_t, int(row_g['id'])))
                    conn.commit(); st.rerun()
                if c2.form_submit_button("🗑️ Borrar"):
                    cur = conn.cursor(); cur.execute("DELETE FROM gastos WHERE id=%s", (int(row_g['id']),))
                    conn.commit(); st.rerun()

# --- 💰 MÓDULO: VENTAS (RESTAURADO Y EDITABLE) ---
elif menu == "💰 Ventas":
    st.title("💰 Gestión de Ventas")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    tab_v1, tab_v2 = st.tabs(["💰 Nueva Venta", "✏️ Editar/Borrar"])
    with tab_v1:
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
    with tab_v2:
        df_v = pd.read_sql("SELECT s.id, s.fecha, v.placa, s.cliente as servicio, s.valor_viaje FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.id DESC", conn)
        sel_v = st.dataframe(df_v, use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel_v.selection.rows) > 0:
            row_v = df_v.iloc[sel_v.selection.rows[0]]
            with st.form("edit_v"):
                en_val = st.number_input("Valor Total", value=float(row_v['valor_viaje']))
                en_cli = st.text_input("Servicio/Cliente", value=row_v['servicio'])
                c1, c2 = st.columns(2)
                if c1.form_submit_button("✅ Actualizar"):
                    cur = conn.cursor(); cur.execute("UPDATE ventas SET valor_viaje=%s, cliente=%s WHERE id=%s", (en_val, en_cli, int(row_v['id'])))
                    conn.commit(); st.rerun()
                if c2.form_submit_button("🗑️ Borrar"):
                    cur = conn.cursor(); cur.execute("DELETE FROM ventas WHERE id=%s", (int(row_v['id']),))
                    conn.commit(); st.rerun()

# --- 📑 MÓDULO: HOJA DE VIDA (SOLUCIÓN DEFINITIVA TYPEERROR) ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Vencimientos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    with st.expander("📅 Actualizar Fechas"):
        with st.form("hv_form"):
            v_sel = st.selectbox("Vehículo", v_data['placa'])
            v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
            c1, c2 = st.columns(2)
            s, t, p = c1.date_input("SOAT"), c1.date_input("Tecno"), c1.date_input("Preventivo")
            pc, pe, ptr = c2.date_input("P. Contractual"), c2.date_input("P. Extra"), c2.date_input("Todo Riesgo")
            top = st.date_input("T. Operaciones")
            if st.form_submit_button("🔄 Actualizar"):
                cur = conn.cursor(); cur.execute('''INSERT INTO hoja_vida (vehiculo_id, soat_vence, tecno_vence, prev_vence, p_contractual, p_extracontractual, p_todoriesgo, t_operaciones) 
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (vehiculo_id) DO UPDATE SET soat_vence=EXCLUDED.soat_vence, tecno_vence=EXCLUDED.tecno_vence, 
                    prev_vence=EXCLUDED.prev_vence, p_contractual=EXCLUDED.p_contractual, p_extracontractual=EXCLUDED.p_extracontractual, 
                    p_todoriesgo=EXCLUDED.p_todoriesgo, t_operaciones=EXCLUDED.t_operaciones''', (int(v_id), s, t, p, pc, pe, ptr, top))
                conn.commit(); st.rerun()

    df_hv = pd.read_sql("SELECT v.placa, h.* FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id", conn)
    hoy = datetime.now().date()
    for _, row in df_hv.iterrows():
        st.subheader(f"🚚 {row['placa']}")
        cols = st.columns(4)
        # Lista de documentos corregida
        docs = [("SOAT", row.get('soat_vence')), ("TECNO", row.get('tecno_vence')), ("PREV", row.get('prev_vence')), 
                ("T.OPER", row.get('t_operaciones')), ("P.CONT", row.get('p_contractual')), ("P.EXTRA", row.get('p_extracontractual')), 
                ("RIESGO", row.get('p_todoriesgo'))]
        for i, (name, f) in enumerate(docs):
            idx = i % 4
            if f and pd.notnull(f):
                try:
                    d = (f - hoy).days
                    if d < 0: cols[idx].error(f"❌ {name}")
                    elif d <= 15: cols[idx].warning(f"⚠️ {name} ({d}d)")
                    else: cols[idx].success(f"✅ {name}")
                except: cols[idx].info(f"⚪ {name}")
            else: cols[idx].info(f"⚪ {name}")
        st.divider()

# --- ⚙️ USUARIOS ---
elif menu == "⚙️ Usuarios":
    st.title("⚙️ Gestión de Usuarios")
    with st.form("u_new"):
        nom, usr, clv, rol = st.text_input("Nombre"), st.text_input("ID"), st.text_input("Clave"), st.selectbox("Rol", ["admin", "conductor"])
        if st.form_submit_button("Crear"):
            cur = conn.cursor(); cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES (%s,%s,%s,%s)", (nom, usr, clv, rol))
            conn.commit(); st.success("Creado")
    st.table(pd.read_sql("SELECT nombre, usuario, rol FROM usuarios", conn))

if conn: conn.close()
