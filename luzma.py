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

# --- 🧠 IA OCR ---
def extraer_monto_ia(imagen_file):
    try:
        img = Image.open(imagen_file).convert('L')
        img = ImageOps.autocontrast(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        texto = pytesseract.image_to_string(img, config='--psm 6').upper()
        limpio = texto.replace('.', '').replace(',', '').replace('$', '').replace("'", "")
        nums = re.findall(r'\d+', limpio)
        candidatos = [int(n) for n in nums if 3000 <= int(n) <= 999999]
        return max(candidatos) if candidatos else 0
    except: return 0

# --- 🗄️ INICIALIZAR TABLAS ---
def inicializar_db():
    conn = conectar_db()
    if conn:
        cur = conn.cursor()
        # Flota
        cur.execute('CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, marca TEXT, modelo TEXT, conductor TEXT)')
        # Gastos con Imagen
        cur.execute('CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT, imagen BYTEA)')
        # Ventas
        cur.execute('CREATE TABLE IF NOT EXISTS ventas (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), cliente TEXT, valor_viaje NUMERIC, fecha DATE, descripcion TEXT, cantidad INTEGER)')
        # Tarifas
        cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)')
        # Documentos
        cur.execute('CREATE TABLE IF NOT EXISTS hoja_vida (id SERIAL PRIMARY KEY, vehiculo_id INTEGER UNIQUE REFERENCES vehiculos(id), soat_vence DATE, tecno_vence DATE, prev_vence DATE, t_operaciones DATE)')
        # USUARIOS CON ROL
        cur.execute('CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, nombre TEXT, usuario TEXT UNIQUE NOT NULL, clave TEXT NOT NULL, rol TEXT DEFAULT "conductor")')
        
        # Insertar Admin por defecto
        cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Luzma Admin', 'admin', 'Luzma2026', 'admin') ON CONFLICT (usuario) DO UPDATE SET clave = EXCLUDED.clave")
        
        conn.commit(); conn.close()

inicializar_db()

# --- 🔐 LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🔐 Acceso Sistema Luzma")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Ingresar"):
        conn = conectar_db(); cur = conn.cursor()
        cur.execute("SELECT nombre, rol FROM usuarios WHERE usuario = %s AND clave = %s", (u, p))
        res = cur.fetchone(); conn.close()
        if res:
            st.session_state.logged_in = True
            st.session_state.u_name, st.session_state.u_rol = res[0], res[1]
            st.rerun()
        else: st.error("Usuario o clave incorrectos")
    st.stop()

# --- 🚀 MENÚ SEGÚN ROL ---
st.sidebar.write(f"👤 **{st.session_state.u_name}** ({st.session_state.u_rol})")

if st.session_state.u_rol == "admin":
    menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos con IA", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Usuarios", "⚙️ Tarifas"])
else:
    # EL CONDUCTOR SOLO VE ESTO
    menu = "📸 Subir Recibos (Conductor)"
    st.sidebar.info("Modo Conductor: Solo carga de gastos.")

if st.sidebar.button("🚪 Cerrar Sesión"):
    st.session_state.logged_in = False; st.rerun()

conn = conectar_db()
if not conn: st.stop()

# --- 📊 DASHBOARD (SOLO ADMIN) ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis de Operación")
    df_v = pd.read_sql("SELECT s.fecha, v.placa, s.cliente, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id", conn)
    df_g = pd.read_sql("SELECT g.fecha, v.placa, g.tipo_gasto, g.monto FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id", conn)
    
    c1, c2 = st.columns(2)
    c1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
    c2.metric("Egresos", f"${df_g['monto'].sum():,.0f}")

    res_v = df_v.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Venta'})
    res_g = df_g.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Gasto'})
    balance_df = pd.merge(res_v, res_g, on='placa', how='outer').fillna(0)
    balance_df[['Venta', 'Gasto']] = balance_df[['Venta', 'Gasto']].apply(pd.to_numeric)
    fig = px.bar(balance_df, x='placa', y=['Venta', 'Gasto'], barmode='group')
    st.plotly_chart(fig, use_container_width=True)
    st.download_button("📥 Excel", generar_excel(df_v, df_g, balance_df), "Reporte.xlsx")

# --- 🚐 FLOTA (ADMIN) ---
elif menu == "🚐 Flota":
    st.title("🚐 Gestión de Flota")
    t1, t2 = st.tabs(["➕ Añadir", "✏️ Editar"])
    with t1:
        with st.form("new_f"):
            pl, ma, mo, co = st.text_input("Placa"), st.text_input("Marca"), st.text_input("Modelo"), st.text_input("Conductor")
            if st.form_submit_button("Guardar"):
                cur = conn.cursor(); cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s,%s,%s,%s)", (pl.upper(), ma, mo, co))
                conn.commit(); st.rerun()
    with t2:
        df_f = pd.read_sql("SELECT * FROM vehiculos", conn)
        sel = st.dataframe(df_f, use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel.selection.rows) > 0:
            row = df_f.iloc[sel.selection.rows[0]]
            with st.form("ed_f"):
                n_ma, n_mo, n_co = st.text_input("Marca", row['marca']), st.text_input("Modelo", row['modelo']), st.text_input("Conductor", row['conductor'])
                if st.form_submit_button("Actualizar"):
                    cur = conn.cursor(); cur.execute("UPDATE vehiculos SET marca=%s, modelo=%s, conductor=%s WHERE id=%s", (n_ma, n_mo, n_co, int(row['id'])))
                    conn.commit(); st.rerun()

# --- 💸 GASTOS (AMBOS ROLES, PERO CONDUCTOR SOLO SUBE) ---
elif menu in ["💸 Gastos con IA", "📸 Subir Recibos (Conductor)"]:
    st.title("💸 Registro de Gastos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    # Si es admin, mostramos pestañas. Si es conductor, solo el formulario.
    if st.session_state.u_rol == "admin":
        tab_g1, tab_g2 = st.tabs(["📝 Nuevo", "✏️ Gestionar"])
    else:
        tab_g1 = st.container()

    with tab_g1:
        col1, col2 = st.columns(2)
        with col1:
            foto = st.file_uploader("📸 Foto Recibo", type=['jpg','jpeg','png'])
            if foto: 
                st.image(foto, width=250)
                if st.button("🔍 Escanear Total"): st.session_state.monto_ia = extraer_monto_ia(foto)
        with col2:
            with st.form("g_form"):
                v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
                monto = st.number_input("Monto", value=float(st.session_state.get('monto_ia', 0.0)))
                det = st.text_input("Nota")
                if st.form_submit_button("💾 Guardar"):
                    v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                    img_bin = foto.getvalue() if foto else None
                    cur = conn.cursor()
                    cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle, imagen) VALUES (%s,'Gasto',%s,%s,%s,%s)", (int(v_id), monto, datetime.now().date(), det, img_bin))
                    conn.commit(); st.success("Gasto Guardado"); st.rerun()

    if st.session_state.u_rol == "admin":
        with tab_g2:
            df_g = pd.read_sql("SELECT g.id, v.placa, g.monto, g.detalle, g.imagen FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id ORDER BY g.id DESC", conn)
            sel_g = st.dataframe(df_g.drop(columns=['imagen']), use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
            if len(sel_g.selection.rows) > 0:
                row_g = df_g.iloc[sel_g.selection.rows[0]]
                if row_g['imagen']: st.image(row_g['imagen'], width=200)
                if st.button("🗑️ Eliminar Gasto"):
                    cur = conn.cursor(); cur.execute("DELETE FROM gastos WHERE id=%s", (int(row_g['id']),))
                    conn.commit(); st.rerun()

# --- 💰 VENTAS (ADMIN) ---
elif menu == "💰 Ventas":
    st.title("💰 Gestión de Ventas")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
    tab_v1, tab_v2 = st.tabs(["💰 Nueva Venta", "✏️ Editar"])
    with tab_v1:
        with st.form("v_form"):
            v_sel = st.selectbox("Vehículo", v_data['placa'])
            serv = st.selectbox("Servicio", t_data['servicio'].tolist() if not t_data.empty else [])
            cant = st.number_input("Cantidad", min_value=1)
            if st.form_submit_button("Guardar Venta"):
                v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                precio = float(t_data[t_data['servicio'] == serv]['precio_unidad'].values[0])
                cur = conn.cursor(); cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, cantidad) VALUES (%s,%s,%s,%s,%s)", (int(v_id), serv, cant*precio, datetime.now().date(), cant))
                conn.commit(); st.rerun()
    with tab_v2:
        df_v = pd.read_sql("SELECT s.id, v.placa, s.cliente, s.valor_viaje FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.id DESC", conn)
        sel_v = st.dataframe(df_v, use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel_v.selection.rows) > 0:
            row_v = df_v.iloc[sel_v.selection.rows[0]]
            if st.button("🗑️ Eliminar Venta"):
                cur = conn.cursor(); cur.execute("DELETE FROM ventas WHERE id=%s", (int(row_v['id']),))
                conn.commit(); st.rerun()

# --- 📑 HOJA DE VIDA (ADMIN) ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Vencimientos")
    df_hv = pd.read_sql("SELECT v.placa, h.soat_vence, h.tecno_vence, h.prev_vence, h.t_operaciones FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id", conn)
    for _, row in df_hv.iterrows():
        st.subheader(f"🚚 {row['placa']}")
        cols = st.columns(4)
        docs = [("SOAT", row['soat_vence']), ("TECNO", row['tecno_vence']), ("PREV", row['prev_vence']), ("T.OP", row['t_operaciones'])]
        for i, (name, f) in enumerate(docs):
            if f:
                d = (f - datetime.now().date()).days
                if d < 0: cols[i].error(f"❌ {name}")
                elif d <= 15: cols[i].warning(f"⚠️ {name} ({d}d)")
                else: cols[i].success(f"✅ {name}")
            else: cols[i].info(f"⚪ {name}")

# --- ⚙️ USUARIOS (SOLO ADMIN) ---
elif menu == "⚙️ Usuarios":
    st.title("⚙️ Gestión de Usuarios")
    with st.form("u_form"):
        nom, usr, clv, rol = st.text_input("Nombre"), st.text_input("ID Usuario"), st.text_input("Clave"), st.selectbox("Rol", ["admin", "conductor"])
        if st.form_submit_button("Crear Usuario"):
            cur = conn.cursor(); cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES (%s,%s,%s,%s)", (nom, usr, clv, rol))
            conn.commit(); st.success("Usuario creado")
    st.table(pd.read_sql("SELECT nombre, usuario, rol FROM usuarios", conn))

# --- ⚙️ TARIFAS ---
elif menu == "⚙️ Tarifas":
    st.title("⚙️ Precios")
    with st.form("t_form"):
        s, pr = st.text_input("Servicio"), st.number_input("Precio")
        if st.form_submit_button("Guardar"):
            cur = conn.cursor(); cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, pr))
            conn.commit(); st.rerun()

if conn: conn.close()
