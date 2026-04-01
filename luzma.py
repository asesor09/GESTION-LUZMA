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
        cur.execute('CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, marca TEXT, modelo TEXT, conductor TEXT)')
        # Agregamos columna 'imagen' tipo BYTEA para el archivo
        cur.execute('CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT, imagen BYTEA)')
        cur.execute('CREATE TABLE IF NOT EXISTS ventas (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), cliente TEXT, valor_viaje NUMERIC, fecha DATE, descripcion TEXT, cantidad INTEGER)')
        cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)')
        cur.execute('CREATE TABLE IF NOT EXISTS hoja_vida (id SERIAL PRIMARY KEY, vehiculo_id INTEGER UNIQUE REFERENCES vehiculos(id), soat_vence DATE, tecno_vence DATE, prev_vence DATE, t_operaciones DATE)')
        cur.execute("CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, usuario TEXT UNIQUE, clave TEXT, rol TEXT)")
        cur.execute("INSERT INTO usuarios (usuario, clave, rol) VALUES ('admin', 'Luzma2026', 'admin') ON CONFLICT (usuario) DO UPDATE SET clave = EXCLUDED.clave")
        
        # Parche para agregar columna imagen si la tabla ya existía sin ella
        try: cur.execute("ALTER TABLE gastos ADD COLUMN imagen BYTEA")
        except: conn.rollback()
        
        conn.commit(); conn.close()

inicializar_db()

# --- 🔐 LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'monto_ia' not in st.session_state: st.session_state.monto_ia = 0.0

if not st.session_state.logged_in:
    st.title("🔐 Acceso Sistema Luzma")
    u, p = st.text_input("Usuario"), st.text_input("Clave", type="password")
    if st.button("Ingresar"):
        if u == "admin" and p == "Luzma2026":
            st.session_state.logged_in = True; st.rerun()
        else: st.error("Acceso denegado")
    st.stop()

# --- 🚀 MENÚ ---
target = st.sidebar.number_input("🎯 Meta Utilidad ($)", value=5000000, step=500000)
menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos con IA", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas"])
if st.sidebar.button("🚪 Salir"): st.session_state.logged_in = False; st.rerun()

conn = conectar_db()
if not conn: st.stop()

# --- 📊 MÓDULO: DASHBOARD ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis y Resultados")
    df_v = pd.read_sql("SELECT s.fecha, v.placa, s.cliente, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id", conn)
    df_g = pd.read_sql("SELECT g.fecha, v.placa, g.tipo_gasto, g.monto FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id", conn)
    
    utilidad = df_v['monto'].sum() - df_g['monto'].sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
    c2.metric("Egresos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
    c3.metric("Utilidad", f"${utilidad:,.0f}", delta=f"{utilidad-target:,.0f}")

    st.subheader("📈 Comparativa por Placa")
    res_v = df_v.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Venta'})
    res_g = df_g.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Gasto'})
    balance_df = pd.merge(res_v, res_g, on='placa', how='outer').fillna(0)
    balance_df[['Venta', 'Gasto']] = balance_df[['Venta', 'Gasto']].apply(pd.to_numeric)
    fig = px.bar(balance_df, x='placa', y=['Venta', 'Gasto'], barmode='group', color_discrete_map={'Venta': '#2ecc71', 'Gasto': '#e74c3c'})
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("🔍 Ver Detalle de Movimientos"):
        st.write("**Ventas:**"); st.dataframe(df_v, use_container_width=True, hide_index=True)
        st.write("**Gastos:**"); st.dataframe(df_g, use_container_width=True, hide_index=True)
    st.download_button("📥 Excel", generar_excel(df_v, df_g, balance_df), "Reporte.xlsx")

# --- 💸 MÓDULO: GASTOS (CON IMAGEN Y EDICIÓN) ---
elif menu == "💸 Gastos con IA":
    st.title("💸 Gestión de Gastos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t1, t2 = st.tabs(["📝 Nuevo Gasto", "✏️ Editar/Borrar"])
    
    with t1:
        col_f, col_fo = st.columns(2)
        with col_f:
            foto = st.file_uploader("📸 Recibo", type=['jpg','png','jpeg'])
            if foto and st.button("🔍 Escanear"): st.session_state.monto_ia = extraer_monto_ia(foto)
            if foto: st.image(foto, width=250)
        with col_fo:
            with st.form("f_g"):
                v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
                tipo = st.selectbox("Concepto", ["Combustible", "Peaje", "Mantenimiento", "Lavada", "Viáticos", "Otros"])
                monto = st.number_input("Valor ($)", value=float(st.session_state.monto_ia))
                det = st.text_input("Nota")
                if st.form_submit_button("💾 Guardar"):
                    v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                    img_bin = foto.getvalue() if foto else None
                    cur = conn.cursor()
                    cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle, imagen) VALUES (%s,%s,%s,%s,%s,%s)", (int(v_id), tipo, monto, datetime.now().date(), det, img_bin))
                    conn.commit(); st.session_state.monto_ia = 0; st.success("Guardado"); st.rerun()

    with t2:
        df_edit_g = pd.read_sql("SELECT g.id, g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle, g.imagen FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id ORDER BY g.fecha DESC", conn)
        sel_g = st.dataframe(df_edit_g.drop(columns=['imagen']), use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel_g.selection.rows) > 0:
            row = df_edit_g.iloc[sel_g.selection.rows[0]]
            st.divider()
            if row['imagen']: st.image(row['imagen'], caption="Recibo Guardado", width=200)
            with st.form("edit_g_form"):
                new_m = st.number_input("Monto", value=float(row['monto']))
                new_d = st.text_input("Detalle", value=row['detalle'])
                c_g1, c_g2 = st.columns(2)
                if c_g1.form_submit_button("✅ Actualizar"):
                    cur = conn.cursor(); cur.execute("UPDATE gastos SET monto=%s, detalle=%s WHERE id=%s", (new_m, new_d, int(row['id'])))
                    conn.commit(); st.rerun()
                if c_g2.form_submit_button("🗑️ Borrar"):
                    cur = conn.cursor(); cur.execute("DELETE FROM gastos WHERE id=%s", (int(row['id']),))
                    conn.commit(); st.rerun()

# --- 💰 MÓDULO: VENTAS (CON EDICIÓN) ---
elif menu == "💰 Ventas":
    st.title("💰 Gestión de Ventas")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_v1, t_v2 = st.tabs(["💰 Nueva Venta", "✏️ Editar/Borrar"])
    
    with t_v1:
        t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
        with st.form("f_v"):
            v_sel = st.selectbox("Vehículo", v_data['placa'])
            serv = st.selectbox("Servicio", t_data['servicio'].tolist() if not t_data.empty else [])
            cant = st.number_input("Cantidad", min_value=1)
            if st.form_submit_button("💰 Registrar"):
                v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                precio = float(t_data[t_data['servicio'] == serv]['precio_unidad'].values[0])
                cur = conn.cursor(); cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, cantidad) VALUES (%s,%s,%s,%s,%s)", (int(v_id), serv, cant*precio, datetime.now().date(), cant))
                conn.commit(); st.success("Venta guardada"); st.rerun()

    with t_v2:
        df_edit_v = pd.read_sql("SELECT s.id, s.fecha, v.placa, s.cliente, s.valor_viaje FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.fecha DESC", conn)
        sel_v = st.dataframe(df_edit_v, use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(sel_v.selection.rows) > 0:
            row_v = df_edit_v.iloc[sel_v.selection.rows[0]]
            with st.form("edit_v_form"):
                new_v_m = st.number_input("Valor", value=float(row_v['valor_viaje']))
                c_v1, c_v2 = st.columns(2)
                if c_v1.form_submit_button("✅ Actualizar"):
                    cur = conn.cursor(); cur.execute("UPDATE ventas SET valor_viaje=%s WHERE id=%s", (new_v_m, int(row_v['id'])))
                    conn.commit(); st.rerun()
                if c_v2.form_submit_button("🗑️ Borrar"):
                    cur = conn.cursor(); cur.execute("DELETE FROM ventas WHERE id=%s", (int(row_v['id']),))
                    conn.commit(); st.rerun()

# --- 📑 MÓDULO: HOJA DE VIDA ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Vencimientos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    with st.expander("📅 Actualizar Fechas"):
        with st.form("f_hv"):
            v_sel = st.selectbox("Vehículo", v_data['placa'])
            v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
            c1, c2 = st.columns(2)
            s_v = c1.date_input("SOAT"); t_v = c1.date_input("Tecno"); p_v = c2.date_input("Preventivo"); to_v = c2.date_input("T. Operaciones")
            if st.form_submit_button("🔄 Actualizar"):
                cur = conn.cursor(); cur.execute("INSERT INTO hoja_vida (vehiculo_id, soat_vence, tecno_vence, prev_vence, t_operaciones) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (vehiculo_id) DO UPDATE SET soat_vence=EXCLUDED.soat_vence, tecno_vence=EXCLUDED.tecno_vence, prev_vence=EXCLUDED.prev_vence, t_operaciones=EXCLUDED.t_operaciones", (int(v_id), s_v, t_v, p_v, to_v))
                conn.commit(); st.rerun()

    df_hv = pd.read_sql("SELECT v.placa, h.soat_vence, h.tecno_vence, h.prev_vence, h.t_operaciones FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id", conn)
    hoy = datetime.now().date()
    for _, row in df_hv.iterrows():
        st.subheader(f"🚚 {row['placa']}")
        cols = st.columns(4)
        docs = [("SOAT", row['soat_vence']), ("TECNO", row['tecno_vence']), ("PREVENTIVO", row['prev_vence']), ("T. OPERACION", row['t_operaciones'])]
        for i, (name, fecha) in enumerate(docs):
            if fecha:
                try:
                    dias = (fecha - hoy).days
                    if dias < 0: cols[i].error(f"❌ {name}")
                    elif dias <= 15: cols[i].warning(f"⚠️ {name} ({dias}d)")
                    else: cols[i].success(f"✅ {name}")
                except: cols[i].info(f"⚪ {name}: Error")
            else: cols[i].info(f"⚪ {name}: Sin fecha")
        st.divider()

# --- 🚐 MÓDULO: FLOTA ---
elif menu == "🚐 Flota":
    st.title("🚐 Mis Vehículos")
    with st.form("ff"):
        p = st.text_input("Placa").upper()
        if st.form_submit_button("➕ Añadir"):
            cur = conn.cursor(); cur.execute("INSERT INTO vehiculos (placa) VALUES (%s)", (p,)); conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT placa FROM vehiculos", conn))

# --- ⚙️ MÓDULO: TARIFAS ---
elif menu == "⚙️ Tarifas":
    st.title("⚙️ Precios")
    with st.form("ft"):
        s = st.text_input("Servicio"); pr = st.number_input("Precio")
        if st.form_submit_button("Guardar"):
            cur = conn.cursor(); cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, pr)); conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT * FROM tarifario", conn))

if conn: conn.close()
