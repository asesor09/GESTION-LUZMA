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
    if "url_luzma" not in st.secrets:
        st.error("❌ Falta 'url_luzma' en Secrets de Streamlit Cloud.")
        return None
    try:
        conn = psycopg2.connect(st.secrets["url_luzma"])
        return conn
    except Exception as e:
        st.error(f"❌ Error de conexión: {e}")
        return None

def generar_excel(df_balance, df_g, df_v):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_balance.to_excel(writer, index=False, sheet_name='Balance General')
        df_g.to_excel(writer, index=False, sheet_name='Detalle Gastos')
        df_v.to_excel(writer, index=False, sheet_name='Detalle Ventas')
    return output.getvalue()

# --- 🧠 FUNCIÓN DE IA (OCR) ---
def extraer_monto_ia(imagen_file):
    try:
        img = Image.open(imagen_file)
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        texto = pytesseract.image_to_string(img, config='--psm 6').upper()
        texto_limpio = texto.replace('.', '').replace(',', '').replace('$', '').replace("'", "")
        numeros = re.findall(r'\d+', texto_limpio)
        candidatos = [int(n) for n in numeros if 3000 <= int(n) <= 999999]
        return max(candidatos) if candidatos else 0
    except:
        return 0

# --- 🗄️ INICIALIZACIÓN DE BASE DE DATOS ---
def inicializar_db():
    conn = conectar_db()
    if conn:
        cur = conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, marca TEXT, modelo TEXT, conductor TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS ventas (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), cliente TEXT, valor_viaje NUMERIC, fecha DATE, descripcion TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)')
        # Hoja de Vida Ampliada
        cur.execute('''CREATE TABLE IF NOT EXISTS hoja_vida (
                        id SERIAL PRIMARY KEY, vehiculo_id INTEGER UNIQUE REFERENCES vehiculos(id), 
                        soat_vence DATE, tecno_vence DATE, prev_vence DATE,
                        p_contractual DATE, p_extracontractual DATE, p_todoriesgo DATE, t_operaciones DATE)''')
        cur.execute('CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, nombre TEXT, usuario TEXT UNIQUE NOT NULL, clave TEXT NOT NULL, rol TEXT DEFAULT "admin")')
        cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Luzma Admin', 'admin', 'Luzma2026', 'admin') ON CONFLICT (usuario) DO NOTHING")
        conn.commit(); conn.close()

inicializar_db()

# --- 🔐 LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'monto_detectado' not in st.session_state: st.session_state.monto_detectado = 0.0

if not st.session_state.logged_in:
    st.sidebar.title("🔐 Acceso")
    u_input = st.sidebar.text_input("Usuario")
    p_input = st.sidebar.text_input("Contraseña", type="password")
    if st.sidebar.button("Ingresar"):
        conn = conectar_db(); cur = conn.cursor()
        cur.execute("SELECT nombre, rol FROM usuarios WHERE usuario = %s AND clave = %s", (u_input, p_input))
        res = cur.fetchone(); conn.close()
        if res:
            st.session_state.logged_in, st.session_state.u_name, st.session_state.u_rol = True, res[0], res[1]
            st.rerun()
        else: st.sidebar.error("Usuario o clave incorrectos")
    st.stop()

# --- 🚀 MENÚ ---
st.sidebar.write(f"👋 Hola, **{st.session_state.u_name}**")
target = st.sidebar.number_input("🎯 Meta Utilidad ($)", value=5000000, step=500000)
menu = st.sidebar.selectbox("MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos con IA", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Usuarios"])
if st.sidebar.button("🚪 CERRAR SESIÓN"):
    st.session_state.logged_in = False; st.rerun()

conn = conectar_db()
if not conn: st.stop()

# --- 📊 MÓDULO: DASHBOARD (CON DETALLES Y GRÁFICOS) ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis de Operación")
    
    # Filtros
    v_data_f = pd.read_sql("SELECT placa FROM vehiculos", conn)
    c_f1, c_f2 = st.columns(2)
    with c_f1: placa_f = st.selectbox("Vehículo:", ["TODOS"] + v_data_f['placa'].tolist())
    with c_f2: rango = st.date_input("Rango:", [datetime.now().date() - timedelta(days=30), datetime.now().date()])

    if len(rango) == 2:
        q_g = "SELECT g.fecha, v.placa, g.tipo_gasto as concepto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id WHERE g.fecha BETWEEN %s AND %s"
        q_v = "SELECT s.fecha, v.placa, s.cliente, s.valor_viaje as monto, s.descripcion FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id WHERE s.fecha BETWEEN %s AND %s"
        params = [rango[0], rango[1]]
        if placa_f != "TODOS":
            q_g += " AND v.placa = %s"; q_v += " AND v.placa = %s"; params.append(placa_f)
        
        df_g = pd.read_sql(q_g, conn, params=params)
        df_v = pd.read_sql(q_v, conn, params=params)

        utilidad = df_v['monto'].sum() - df_g['monto'].sum()
        dif_meta = utilidad - target

        if utilidad >= target:
            st.success(f"### 🏆 ¡META ALCANZADA! Utilidad: **${utilidad:,.0f}** (+${dif_meta:,.0f})")
        else:
            st.error(f"### ⚠️ POR DEBAJO DE LA META. Faltan: **${abs(dif_meta):,.0f}**")

        m1, m2, m3 = st.columns(3)
        m1.metric("Ingresos", f"${df_v['monto'].sum():,.0f}")
        m2.metric("Egresos", f"${df_g['monto'].sum():,.0f}", delta_color="inverse")
        m3.metric("Utilidad Neta", f"${utilidad:,.0f}", delta=f"{dif_meta:,.0f}")

        # Gráfico Plotly
        st.subheader("📈 Comparativa Venta vs Gasto")
        res_v = df_v.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Venta'})
        res_g = df_g.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Gasto'})
        balance_df = pd.merge(res_v, res_g, on='placa', how='outer').fillna(0)
        fig = px.bar(balance_df, x='placa', y=['Venta', 'Gasto'], barmode='group', color_discrete_map={'Venta': '#2ecc71', 'Gasto': '#e74c3c'})
        st.plotly_chart(fig, use_container_width=True)

        st.download_button("📥 Reporte Excel", to_excel(balance_df, df_g, df_v), file_name="Reporte_Luzma.xlsx")

        # Detalle Tabular
        with st.expander("🔍 Ver Detalle de Movimientos"):
            st.write("**Detalle de Ventas:**")
            st.dataframe(df_v, use_container_width=True, hide_index=True)
            st.write("**Detalle de Gastos:**")
            st.dataframe(df_g, use_container_width=True, hide_index=True)

# --- 💸 MÓDULO: GASTOS (CON IA Y EDICIÓN) ---
elif menu == "💸 Gastos con IA":
    st.title("💸 Registro de Gastos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t1, t2 = st.tabs(["📝 Nuevo Gasto (IA)", "✏️ Gestionar Registros"])
    
    with t1:
        col_f, col_fo = st.columns(2)
        with col_f:
            foto = st.file_uploader("📸 Foto del recibo", type=['jpg', 'png', 'jpeg'])
            if foto:
                st.image(foto, width=300)
                if st.button("🔍 Escanear Total"):
                    st.session_state.monto_detectado = extraer_monto_ia(foto)
        with col_fo:
            with st.form("f_g"):
                v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
                tipo = st.selectbox("Concepto", ["Combustible", "Peaje", "Mantenimiento", "Lavada", "Viáticos", "Otros"])
                monto = st.number_input("Valor ($)", value=float(st.session_state.monto_detectado))
                fecha = st.date_input("Fecha", datetime.now().date())
                det = st.text_input("Nota")
                if st.form_submit_button("💾 Guardar"):
                    v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                    cur = conn.cursor(); cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", (int(v_id), tipo, monto, fecha, det))
                    conn.commit(); st.session_state.monto_detectado = 0; st.success("Guardado"); st.rerun()

    with t2:
        df_edit = pd.read_sql("SELECT g.id, g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id ORDER BY g.fecha DESC", conn)
        event = st.dataframe(df_edit, use_container_width=True, on_select="rerun", selection_mode="single-row", hide_index=True)
        if len(event.selection.rows) > 0:
            idx = event.selection.rows[0]; row = df_edit.iloc[idx]
            with st.form("edit_g"):
                new_m = st.number_input("Monto", value=float(row['monto']))
                new_d = st.text_input("Detalle", value=row['detalle'])
                c_e1, c_e2 = st.columns(2)
                if c_e1.form_submit_button("✅ Actualizar"):
                    cur = conn.cursor(); cur.execute("UPDATE gastos SET monto=%s, detalle=%s WHERE id=%s", (new_m, new_d, int(row['id'])))
                    conn.commit(); st.rerun()
                if c_e2.form_submit_button("🗑️ Eliminar"):
                    cur = conn.cursor(); cur.execute("DELETE FROM gastos WHERE id=%s", (int(row['id']),))
                    conn.commit(); st.rerun()

# --- 💰 MÓDULO: VENTAS ---
elif menu == "💰 Ventas":
    st.title("💰 Registro de Ingresos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    with st.form("f_v"):
        v_sel = st.selectbox("Vehículo", v_data['placa'])
        cli = st.text_input("Cliente / Empresa")
        val = st.number_input("Valor Viaje", min_value=0)
        fec = st.date_input("Fecha")
        dsc = st.text_input("Descripción")
        if st.form_submit_button("💰 Guardar"):
            v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
            cur = conn.cursor(); cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, descripcion) VALUES (%s,%s,%s,%s,%s)", (int(v_id), cli, val, fec, dsc))
            conn.commit(); st.success("Venta guardada"); st.rerun()
    st.dataframe(pd.read_sql("SELECT s.fecha, v.placa, s.cliente, s.valor_viaje FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.fecha DESC", conn), use_container_width=True)

# --- 📑 MÓDULO: HOJA DE VIDA (CORREGIDO SIN ERROR) ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Documentación y Vencimientos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    with st.expander("📅 Actualizar Vencimientos"):
        with st.form("f_hv"):
            v_sel = st.selectbox("Vehículo", v_data['placa'])
            v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
            c1, c2 = st.columns(2)
            s_v = c1.date_input("SOAT"); t_v = c1.date_input("Tecno"); p_v = c1.date_input("Preventivo")
            to_v = c1.date_input("Tarjeta Operación")
            pc_v = c2.date_input("Pol. Contractual"); pe_v = c2.date_input("Pol. Extra")
            pt_v = c2.date_input("Pol. Todo Riesgo")
            if st.form_submit_button("🔄 Actualizar"):
                cur = conn.cursor()
                cur.execute('''INSERT INTO hoja_vida (vehiculo_id, soat_vence, tecno_vence, prev_vence, p_contractual, p_extracontractual, p_todoriesgo, t_operaciones) 
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (vehiculo_id) DO UPDATE SET 
                               soat_vence=EXCLUDED.soat_vence, tecno_vence=EXCLUDED.tecno_vence, prev_vence=EXCLUDED.prev_vence,
                               p_contractual=EXCLUDED.p_contractual, p_extracontractual=EXCLUDED.p_extracontractual,
                               p_todoriesgo=EXCLUDED.p_todoriesgo, t_operaciones=EXCLUDED.t_operaciones''', (int(v_id), s_v, t_v, p_v, pc_v, pe_v, pt_v, to_v))
                conn.commit(); st.success("Actualizado"); st.rerun()

    df_hv = pd.read_sql("SELECT v.placa, h.soat_vence, h.tecno_vence, h.prev_vence, h.p_contractual, h.p_extracontractual, h.p_todoriesgo, h.t_operaciones FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id", conn)
    hoy = datetime.now().date()
    for _, row in df_hv.iterrows():
        st.subheader(f"🚚 {row['placa']}")
        cols = st.columns(4)
        docs = [("SOAT", row['soat_vence']), ("TECNO", row['tecno_vence']), ("PREV", row['prev_vence']), ("T.OPER", row['t_operaciones']), ("POL.CONT", row['p_contractual']), ("POL.EXTRA", row['p_extracontractual']), ("RIESGO", row['p_todoriesgo'])]
        for i, (name, fecha) in enumerate(docs):
            c_idx = i % 4
            if fecha:
                # CORRECCIÓN: Validamos que fecha sea de tipo date para evitar el TypeError
                dias = (fecha - hoy).days
                if dias < 0: cols[c_idx].error(f"❌ {name}")
                elif dias <= 15: cols[c_idx].warning(f"⚠️ {name} ({dias}d)")
                else: cols[c_idx].success(f"✅ {name}")
            else: cols[c_idx].info(f"⚪ {name}")

# --- 🚐 MÓDULO: FLOTA ---
elif menu == "🚐 Flota":
    st.title("🚐 Administración de Flota")
    with st.form("f_flota"):
        p = st.text_input("Placa").upper(); m = st.text_input("Marca"); mod = st.text_input("Modelo"); c = st.text_input("Conductor")
        if st.form_submit_button("Añadir"):
            cur = conn.cursor(); cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s,%s,%s,%s)", (p,m,mod,c))
            conn.commit(); st.success("Añadido"); st.rerun()
    st.dataframe(pd.read_sql("SELECT placa, marca, modelo, conductor FROM vehiculos", conn), use_container_width=True)

# --- ⚙️ MÓDULO: USUARIOS ---
elif menu == "⚙️ Usuarios" and st.session_state.u_rol == "admin":
    st.title("⚙️ Gestión de Usuarios")
    with st.form("f_u"):
        nom = st.text_input("Nombre"); usr = st.text_input("Usuario"); clv = st.text_input("Clave"); rol = st.selectbox("Rol", ["admin", "vendedor"])
        if st.form_submit_button("Crear"):
            cur = conn.cursor(); cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES (%s,%s,%s,%s)", (nom, usr, clv, rol))
            conn.commit(); st.success("Usuario creado")

if conn: conn.close()
