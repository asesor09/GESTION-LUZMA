import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
import plotly.express as px

# --- 1. CONFIGURACIÓN DE LA BASE DE DATOS ---
# Usamos tu URL de Neon
DB_URL = "postgresql://neondb_owner:npg_c7Dkwlh1jzGQ@ep-lucky-shadow-ac1thtiq-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require"

def conectar_db():
    return psycopg2.connect(DB_URL)

def inicializar_db():
    conn = conectar_db(); cur = conn.cursor()
    # Tus tablas originales
    cur.execute('CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, marca TEXT, modelo TEXT, conductor TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT)')
    
    # TABLA DE VENTAS (MODIFICADA PARA PRODUCCIÓN)
    cur.execute('''CREATE TABLE IF NOT EXISTS ventas (
                    id SERIAL PRIMARY KEY, 
                    vehiculo_id INTEGER REFERENCES vehiculos(id), 
                    servicio TEXT, 
                    cantidad INTEGER,
                    valor_viaje NUMERIC, 
                    fecha DATE, 
                    descripcion TEXT)''')
    
    # TABLA DE TARIFAS (NUEVA PARA EL CÁLCULO)
    cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)')
    
    cur.execute('''CREATE TABLE IF NOT EXISTS hoja_vida (
                    id SERIAL PRIMARY KEY, 
                    vehiculo_id INTEGER UNIQUE REFERENCES vehiculos(id), 
                    soat_vence DATE, tecno_vence DATE, prev_vence DATE,
                    p_contractual DATE, p_extracontractual DATE, p_todoriesgo DATE, t_operaciones DATE)''')
    
    cur.execute('CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, nombre TEXT, usuario TEXT UNIQUE NOT NULL, clave TEXT NOT NULL, rol TEXT DEFAULT "vendedor")')
    cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Jacobo Admin', 'admin', 'Jacobo2026', 'admin') ON CONFLICT (usuario) DO NOTHING")
    
    # Asegurar columnas nuevas
    columnas_extra = ["p_contractual", "p_extracontractual", "p_todoriesgo", "t_operaciones"]
    for col in columnas_extra:
        try: cur.execute(f"ALTER TABLE hoja_vida ADD COLUMN {col} DATE")
        except: conn.rollback()
    
    # Asegurar columnas en ventas para detalles y cantidad
    try:
        cur.execute("ALTER TABLE ventas ADD COLUMN cantidad INTEGER")
        cur.execute("ALTER TABLE ventas ADD COLUMN servicio TEXT")
    except: conn.rollback()
        
    conn.commit(); conn.close()

# --- 2. FUNCIONES DE APOYO ---
def to_excel(df_balance, df_g, df_v):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_balance.to_excel(writer, index=False, sheet_name='Balance General')
        df_g.to_excel(writer, index=False, sheet_name='Detalle Gastos')
        df_v.to_excel(writer, index=False, sheet_name='Detalle Ventas')
    return output.getvalue()

# --- 3. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="C&E Eficiencias", layout="wide", page_icon="🚐")
inicializar_db()

# --- 4. SISTEMA DE LOGIN ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.sidebar.title("🔐 Acceso al Sistema")
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

# --- 5. MENÚ PRINCIPAL ---
st.sidebar.write(f"👋 Bienvenid@, **{st.session_state.u_name}**")
st.sidebar.divider()
target = st.sidebar.number_input("🎯 Meta Utilidad ($)", value=3000000, step=500000)
# Agregamos "Tarifas" para que puedas configurar los precios
menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas", "⚙️ Usuarios"])

if st.sidebar.button("🚪 CERRAR SESIÓN"):
    st.session_state.logged_in = False; st.rerun()

# --- 6. LÓGICA DE MÓDULOS ---

# --- MÓDULO: DASHBOARD ---
if menu == "📊 Dashboard":
    st.title("📊 Análisis de Operación y Utilidades")
    conn = conectar_db()
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    c1, c2 = st.columns(2)
    with c1:
        placa_f = st.selectbox("Seleccione Vehículo:", ["TODOS"] + v_data['placa'].tolist())
    with c2:
        rango = st.date_input("Rango de Fechas:", [datetime.now().date() - timedelta(days=30), datetime.now().date()])

    if len(rango) == 2:
        q_g = "SELECT g.fecha, v.placa, g.tipo_gasto as concepto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id WHERE g.fecha BETWEEN %s AND %s"
        q_v = "SELECT s.fecha, v.placa, s.servicio as cliente, s.valor_viaje as monto, s.descripcion FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id WHERE s.fecha BETWEEN %s AND %s"
        params = [rango[0], rango[1]]
        
        if placa_f != "TODOS":
            q_g += " AND v.placa = %s"; q_v += " AND v.placa = %s"
            params.append(placa_f)
        
        df_g = pd.read_sql(q_g, conn, params=params)
        df_v = pd.read_sql(q_v, conn, params=params)

        sum_v = df_v['monto'].sum()
        sum_g = df_g['monto'].sum()
        utilidad_neta = sum_v - sum_g
        dif_meta = utilidad_neta - target

        st.divider()
        if utilidad_neta >= target:
            st.success(f"### 🏆 ¡META ALCANZADA! \n Utilidad: **${utilidad_neta:,.0f}**")
            st.balloons()
        else:
            st.error(f"### ⚠️ POR DEBAJO DE LA META \n Faltan: **${abs(dif_meta):,.0f}**")

        m1, m2, m3 = st.columns(3)
        m1.metric("Ingresos (Producción)", f"${sum_v:,.0f}")
        m2.metric("Egresos (Gastos)", f"${sum_g:,.0f}", delta=f"-{sum_g:,.0f}", delta_color="inverse")
        m3.metric("Utilidad Neta", f"${utilidad_neta:,.0f}", delta=f"{dif_meta:,.0f}")

        st.subheader("📈 Comparativa por Vehículo")
        res_g = df_g.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Gasto'})
        res_v = df_v.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Venta'})
        balance_df = pd.merge(res_v, res_g, on='placa', how='outer').fillna(0)
        
        fig = px.bar(balance_df, x='placa', y=['Venta', 'Gasto'], barmode='group', color_discrete_map={'Venta': '#2ecc71', 'Gasto': '#e74c3c'})
        st.plotly_chart(fig, use_container_width=True)
    conn.close()

# --- MÓDULO: VENTAS (MODIFICADO) ---
elif menu == "💰 Ventas":
    st.title("💰 Registro de Producción y Ventas")
    conn = conectar_db()
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
    
    if v_data.empty or t_data.empty:
        st.warning("⚠️ Asegúrate de tener Vehículos en 'Flota' y Precios en 'Tarifas'.")
    else:
        with st.form("form_produccion"):
            col1, col2 = st.columns(2)
            v_sel = col1.selectbox("Vehículo Responsable", v_data['placa'])
            serv_sel = col2.selectbox("Servicio / Tipo de Trabajo", t_data['servicio'].tolist())
            
            cant = st.number_input("Cantidad de Unidades", min_value=1, step=1)
            
            # Cálculo automático del precio
            precio_u = t_data[t_data['servicio'] == serv_sel]['precio_unidad'].values[0]
            total_venta = cant * precio_u
            
            st.info(f"💵 **Total a Cobrar: ${total_venta:,.0f}** (Precio unitario: ${precio_u:,.0f})")
            
            fecha = st.date_input("Fecha de Registro")
            detalles = st.text_area("Detalles / Descripción (Referencia, Lote, Observaciones)")
            
            if st.form_submit_button("💰 Guardar Producción"):
                v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                cur = conn.cursor()
                cur.execute("""INSERT INTO ventas (vehiculo_id, servicio, cantidad, valor_viaje, fecha, descripcion) 
                               VALUES (%s,%s,%s,%s,%s,%s)""", 
                            (int(v_id), serv_sel, int(cant), float(total_venta), fecha, detalles))
                conn.commit(); st.success("Registro de producción guardado"); st.rerun()
    
    st.divider()
    df_v_list = pd.read_sql("""SELECT s.fecha, v.placa, s.servicio, s.cantidad, s.valor_viaje as total, s.descripcion 
                               FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.id DESC""", conn)
    st.dataframe(df_v_list, use_container_width=True, hide_index=True)
    conn.close()

# --- MÓDULO: TARIFAS (NUEVO) ---
elif menu == "⚙️ Tarifas":
    st.title("⚙️ Configuración de Precios por Unidad")
    conn = conectar_db()
    with st.form("form_t"):
        serv = st.text_input("Nombre del Servicio (Ej: Lavandería, Corte)")
        precio = st.number_input("Precio por Unidad ($)", min_value=0)
        if st.form_submit_button("Guardar Tarifa"):
            cur = conn.cursor()
            cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (serv, precio))
            conn.commit(); st.success("Tarifa actualizada"); st.rerun()
    
    st.subheader("Lista de Precios Actuales")
    st.table(pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn))
    conn.close()

# --- MÓDULO: FLOTA (TÚ CÓDIGO IGUAL) ---
elif menu == "🚐 Flota":
    st.title("🚐 Administración de Vehículos")
    with st.form("form_f"):
        p = st.text_input("Placa").upper()
        m = st.text_input("Marca")
        mod = st.text_input("Modelo")
        cond = st.text_input("Conductor Asignado")
        if st.form_submit_button("➕ Añadir Carro"):
            conn = conectar_db(); cur = conn.cursor()
            cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s,%s,%s,%s)", (p, m, mod, cond))
            conn.commit(); conn.close(); st.success("Vehículo añadido"); st.rerun()
    
    conn = conectar_db()
    st.dataframe(pd.read_sql("SELECT placa, marca, modelo, conductor FROM vehiculos", conn), use_container_width=True)
    conn.close()

# (Los módulos de Gastos, Hoja de Vida y Usuarios permanecen exactamente igual a tu código original)
elif menu == "💸 Gastos":
    # [Tu código de gastos aquí...]
    st.title("💸 Registro y Control de Gastos")
    conn = conectar_db(); v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    if not v_data.empty:
        with st.form("form_g"):
            v_sel = st.selectbox("Vehículo", v_data['placa'])
            v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
            tipo = st.selectbox("Concepto", ["Combustible", "Peaje", "Mantenimiento", "Lavada", "Viáticos", "Otros"])
            monto = st.number_input("Valor ($)", min_value=0)
            fecha = st.date_input("Fecha")
            det = st.text_input("Nota/Detalle")
            if st.form_submit_button("💾 Guardar Gasto"):
                cur = conn.cursor()
                cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", (int(v_id), tipo, monto, fecha, det))
                conn.commit(); st.success("Registrado correctamente"); st.rerun()
    conn.close()

elif menu == "📑 Hoja de Vida":
    # [Tu código de Hoja de Vida aquí...]
    st.title("📑 Documentación y Vencimientos")
    conn = conectar_db(); v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    # ... (Resto de tu lógica de Hoja de Vida)
    conn.close()

elif menu == "⚙️ Usuarios" and st.session_state.u_rol == "admin":
    # [Tu código de Usuarios aquí...]
    st.title("⚙️ Gestión de Personal")
    # ...
