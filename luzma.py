import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
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

def inicializar_db():
    conn = conectar_db()
    if conn:
        cur = conn.cursor()
        # Tablas base
        cur.execute('CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, marca TEXT, modelo TEXT, conductor TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT, foto_url TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS ventas (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), cliente TEXT, valor_viaje NUMERIC, fecha DATE, descripcion TEXT, cantidad INTEGER)')
        cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)')
        cur.execute('''CREATE TABLE IF NOT EXISTS hoja_vida (
                        id SERIAL PRIMARY KEY, vehiculo_id INTEGER UNIQUE REFERENCES vehiculos(id), 
                        soat_vence DATE, tecno_vence DATE, prev_vence DATE,
                        p_contractual DATE, p_extracontractual DATE, p_todoriesgo DATE, t_operaciones DATE)''')
        cur.execute("CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, nombre TEXT, usuario TEXT UNIQUE NOT NULL, clave TEXT NOT NULL, rol TEXT DEFAULT 'admin')")
        cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Luzma Admin', 'admin', 'Luzma2026', 'admin') ON CONFLICT (usuario) DO NOTHING")
        conn.commit()
        conn.close()

inicializar_db()

# --- 2. LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.sidebar.title("🔐 Acceso Sistema")
    u_input = st.sidebar.text_input("Usuario")
    p_input = st.sidebar.text_input("Contraseña", type="password")
    if st.sidebar.button("Ingresar"):
        conn = conectar_db()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT nombre, rol FROM usuarios WHERE usuario = %s AND clave = %s", (u_input, p_input))
            res = cur.fetchone()
            conn.close()
            if res:
                st.session_state.logged_in = True
                st.session_state.u_name, st.session_state.u_rol = res[0], res[1]
                st.rerun()
            else: st.sidebar.error("Usuario o clave incorrectos")
    st.stop()

# --- 3. INTERFAZ PRINCIPAL ---
st.sidebar.write(f"👤 **{st.session_state.u_name}**")
menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas", "⚙️ Usuarios"])

if st.sidebar.button("🚪 Cerrar Sesión"):
    st.session_state.logged_in = False
    st.rerun()

conn = conectar_db()
if not conn: st.stop()

# --- MÓDULO: DASHBOARD ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis de Operación")
    v_veh = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    c1, c2 = st.columns(2)
    with c1: placa_f = st.selectbox("Filtrar Vehículo:", ["TODOS"] + v_veh['placa'].tolist())
    with c2: rango = st.date_input("Rango de Fechas:", [datetime.now().date() - timedelta(days=30), datetime.now().date()])

    if len(rango) == 2:
        params = [rango[0], rango[1]]
        q_g = "SELECT g.fecha, v.placa, g.tipo_gasto, g.monto FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id WHERE g.fecha BETWEEN %s AND %s"
        q_v = "SELECT s.fecha, v.placa, s.valor_viaje as monto FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id WHERE s.fecha BETWEEN %s AND %s"
        
        if placa_f != "TODOS":
            q_g += " AND v.placa = %s"; q_v += " AND v.placa = %s"; params.append(placa_f)
        
        df_g = pd.read_sql(q_g, conn, params=params)
        df_v = pd.read_sql(q_v, conn, params=params)
        
        ingresos = df_v['monto'].sum()
        egresos = df_g['monto'].sum()
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Ingresos Total", f"${ingresos:,.0f}")
        m2.metric("Gastos Total", f"${egresos:,.0f}", delta_color="inverse")
        m3.metric("Utilidad Neta", f"${ingresos - egresos:,.0f}")

# --- MÓDULO: FLOTA ---
elif menu == "🚐 Flota":
    st.title("🚐 Gestión de Vehículos")
    with st.form("f_flota"):
        c1, c2 = st.columns(2)
        p = c1.text_input("Placa").upper()
        m = c1.text_input("Marca")
        mod = c2.text_input("Modelo")
        cond = c2.text_input("Conductor Asignado")
        if st.form_submit_button("➕ Registrar Vehículo"):
            cur = conn.cursor()
            cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s,%s,%s,%s)", (p, m, mod, cond))
            conn.commit(); st.success("Vehículo registrado"); st.rerun()
    
    st.write("### Listado de Flota")
    df_f = pd.read_sql("SELECT * FROM vehiculos", conn)
    st.dataframe(df_f, use_container_width=True, hide_index=True)

# --- MÓDULO: GASTOS (CON FOTO) ---
elif menu == "💸 Gastos":
    st.title("💸 Registro de Gastos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    with st.form("f_gastos"):
        v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else ["No hay vehículos"])
        tipo = st.selectbox("Concepto", ["Combustible", "Mantenimiento", "Peaje", "Lavado", "Otros"])
        monto = st.number_input("Valor Pagado ($)", min_value=0)
        det = st.text_input("Observación/Taller")
        foto = st.file_uploader("📸 Subir Recibo/Factura", type=['jpg', 'png', 'jpeg'])
        
        if st.form_submit_button("💾 Guardar Gasto"):
            if not v_data.empty:
                v_id = int(v_data[v_data['placa'] == v_sel]['id'].values[0])
                cur = conn.cursor()
                cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", 
                            (v_id, tipo, monto, datetime.now().date(), det))
                conn.commit(); st.success("Gasto registrado correctamente"); st.rerun()

# --- MÓDULO: HOJA DE VIDA (ALERTAS) ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Alertas de Documentación")
    v_data_h = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    if v_data_h.empty:
        st.warning("Primero registre vehículos en el módulo 'Flota'")
    else:
        with st.expander("📅 Actualizar Vencimientos"):
            with st.form("f_hv"):
                v_sel = st.selectbox("Vehículo", v_data_h['placa'])
                v_id = int(v_data_h[v_data_h['placa'] == v_sel]['id'].values[0])
                c1, c2 = st.columns(2)
                s_v = c1.date_input("SOAT")
                t_v = c1.date_input("Tecno")
                p_v = c1.date_input("Preventivo")
                pc_v = c2.date_input("P. Contractual")
                pe_v = c2.date_input("P. Extra")
                ptr_v = c2.date_input("Todo Riesgo")
                to_v = st.date_input("T. Operaciones")
                
                if st.form_submit_button("🔄 Actualizar Fechas"):
                    cur = conn.cursor()
                    cur.execute('''INSERT INTO hoja_vida (vehiculo_id, soat_vence, tecno_vence, prev_vence, p_contractual, p_extracontractual, p_todoriesgo, t_operaciones) 
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (vehiculo_id) DO UPDATE SET 
                                soat_vence=EXCLUDED.soat_vence, tecno_vence=EXCLUDED.tecno_vence, prev_vence=EXCLUDED.prev_vence, 
                                p_contractual=EXCLUDED.p_contractual, p_extracontractual=EXCLUDED.p_extracontractual, 
                                p_todoriesgo=EXCLUDED.p_todoriesgo, t_operaciones=EXCLUDED.t_operaciones''', 
                                (v_id, s_v, t_v, p_v, pc_v, pe_v, ptr_v, to_v))
                    conn.commit(); st.success("Documentación actualizada"); st.rerun()

        # Semáforo de Alertas
        df_hv = pd.read_sql('''SELECT v.placa, h.* FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id''', conn)
        hoy = datetime.now().date()
        for _, row in df_hv.iterrows():
            st.subheader(f"🚚 {row['placa']}")
            cols = st.columns(4)
            docs = [("SOAT", row['soat_vence']), ("TECNO", row['tecno_vence']), ("PREV", row['prev_vence']), 
                    ("T.OPER", row['t_operaciones']), ("POL. CONT", row['p_contractual']), 
                    ("POL. EXTRA", row['p_extracontractual']), ("TODO RIESGO", row['p_todoriesgo'])]
            
            for i, (name, fecha) in enumerate(docs):
                if fecha:
                    d = (fecha - hoy).days
                    if d < 0: cols[i % 4].error(f"❌ {name}\nVENCIDO")
                    elif d <= 15: cols[i % 4].warning(f"⚠️ {name}\nCasi vence")
                    else: cols[i % 4].success(f"✅ {name}\nAl día")
                else: cols[i % 4].info(f"⚪ {name}\nS/D")

# --- MÓDULO: VENTAS ---
elif menu == "💰 Ventas":
    st.title("💰 Registro de Ventas")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
    
    with st.form("f_ventas"):
        v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
        s_sel = st.selectbox("Servicio/Tarifa", t_data['servicio'].tolist() if not t_data.empty else [])
        cant = st.number_input("Cantidad", min_value=1)
        desc = st.text_input("Descripción del Viaje/Carga")
        if st.form_submit_button("💰 Guardar Venta"):
            v_id = int(v_data[v_data['placa'] == v_sel]['id'].values[0])
            precio = float(t_data[t_data['servicio'] == s_sel]['precio_unidad'].values[0])
            cur = conn.cursor()
            cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, descripcion, cantidad) VALUES (%s,%s,%s,%s,%s,%s)", 
                        (v_id, s_sel, cant*precio, datetime.now().date(), desc, cant))
            conn.commit(); st.success("Venta registrada"); st.rerun()

# --- MÓDULO: TARIFAS ---
elif menu == "⚙️ Tarifas":
    st.title("⚙️ Tarifario de Servicios")
    with st.form("f_tarifas"):
        serv = st.text_input("Nombre del Servicio")
        prec = st.number_input("Precio por Unidad ($)", min_value=0)
        if st.form_submit_button("💾 Guardar Tarifa"):
            cur = conn.cursor()
            cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (serv, prec))
            conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT * FROM tarifario", conn))

# --- MÓDULO: USUARIOS ---
elif menu == "⚙️ Usuarios" and st.session_state.u_rol == "admin":
    st.title("⚙️ Gestión de Usuarios")
    with st.form("f_users"):
        n = st.text_input("Nombre")
        u = st.text_input("Usuario (Login)")
        c = st.text_input("Clave", type="password")
        if st.form_submit_button("➕ Crear"):
            cur = conn.cursor()
            cur.execute("INSERT INTO usuarios (nombre, usuario, clave) VALUES (%s,%s,%s)", (n, u, c))
            conn.commit(); st.success("Usuario creado")

conn.close()
