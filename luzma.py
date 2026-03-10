import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io
import plotly.express as px

# --- 1. CONFIGURACIÓN DE LA BASE DE DATOS ---
# Usamos tu URL de Neon para Luzma
DB_URL = "postgresql://neondb_owner:npg_c7Dkwlh1jzGQ@ep-lucky-shadow-ac1thtiq-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require"

def conectar_db():
    return psycopg2.connect(DB_URL)

def inicializar_db():
    conn = conectar_db(); cur = conn.cursor()
    # 1. Tabla de Vehículos
    cur.execute('CREATE TABLE IF NOT EXISTS vehiculos (id SERIAL PRIMARY KEY, placa TEXT UNIQUE NOT NULL, marca TEXT, modelo TEXT, conductor TEXT)')
    # 2. Tabla de Gastos
    cur.execute('CREATE TABLE IF NOT EXISTS gastos (id SERIAL PRIMARY KEY, vehiculo_id INTEGER REFERENCES vehiculos(id), tipo_gasto TEXT, monto NUMERIC, fecha DATE, detalle TEXT)')
    # 3. Tabla de Ventas (Adaptada a Luzma con Detalles)
    cur.execute('''CREATE TABLE IF NOT EXISTS ventas (
                    id SERIAL PRIMARY KEY, 
                    vehiculo_id INTEGER REFERENCES vehiculos(id), 
                    servicio TEXT, 
                    cantidad INTEGER,
                    valor_total NUMERIC, 
                    fecha DATE, 
                    detalles TEXT)''')
    # 4. Tabla de Tarifas (Para el cálculo Cantidad x Precio)
    cur.execute('CREATE TABLE IF NOT EXISTS tarifario (id SERIAL PRIMARY KEY, servicio TEXT UNIQUE NOT NULL, precio_unidad NUMERIC NOT NULL)')
    # 5. Tabla Hoja de Vida
    cur.execute('''CREATE TABLE IF NOT EXISTS hoja_vida (
                    id SERIAL PRIMARY KEY, 
                    vehiculo_id INTEGER UNIQUE REFERENCES vehiculos(id), 
                    soat_vence DATE, tecno_vence DATE, prev_vence DATE,
                    p_contractual DATE, p_extracontractual DATE, p_todoriesgo DATE, t_operaciones DATE)''')
    # 6. Tabla de Usuarios
    cur.execute('CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, nombre TEXT, usuario TEXT UNIQUE NOT NULL, clave TEXT NOT NULL, rol TEXT DEFAULT "vendedor")')
    cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES ('Jacobo Admin', 'admin', 'Jacobo2026', 'admin') ON CONFLICT (usuario) DO NOTHING")
    
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
st.set_page_config(page_title="C&E - Confejeans Luzma", layout="wide", page_icon="🧵")
inicializar_db()

# --- 4. SISTEMA DE LOGIN (IDÉNTICO AL TUYO) ---
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
menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas", "⚙️ Usuarios"])

if st.sidebar.button("🚪 CERRAR SESIÓN"):
    st.session_state.logged_in = False; st.rerun()

# --- 6. LÓGICA DE MÓDULOS ---

# --- MÓDULO: DASHBOARD (MISMA FIGURA QUE ENVIASTE) ---
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
        q_v = "SELECT s.fecha, v.placa, s.servicio as concepto, s.valor_total as monto, s.detalles FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id WHERE s.fecha BETWEEN %s AND %s"
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
        # Semáforo de Metas (IGUAL AL TUYO)
        if utilidad_neta >= target:
            st.success(f"### 🏆 ¡META ALCANZADA! \n Utilidad: **${utilidad_neta:,.0f}** | Superas el objetivo por: **${dif_meta:,.0f}**")
            st.balloons()
        else:
            st.error(f"### ⚠️ POR DEBAJO DE LA META \n Utilidad: **${utilidad_neta:,.0f}** | Faltan: **${abs(dif_meta):,.0f}**")

        m1, m2, m3 = st.columns(3)
        m1.metric("Ingresos (Producción)", f"${sum_v:,.0f}")
        m2.metric("Egresos (Gastos)", f"${sum_g:,.0f}", delta=f"-{sum_g:,.0f}", delta_color="inverse")
        m3.metric("Utilidad Neta", f"${utilidad_neta:,.0f}", delta=f"{dif_meta:,.0f}")

        # Gráfico Comparativo (IGUAL AL TUYO)
        st.subheader("📈 Comparativa por Vehículo")
        res_g = df_g.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Gasto'})
        res_v = df_v.groupby('placa')['monto'].sum().reset_index().rename(columns={'monto': 'Venta'})
        balance_df = pd.merge(res_v, res_g, on='placa', how='outer').fillna(0)
        
        fig = px.bar(balance_df, x='placa', y=['Venta', 'Gasto'], barmode='group', color_discrete_map={'Venta': '#2ecc71', 'Gasto': '#e74c3c'})
        st.plotly_chart(fig, use_container_width=True)
    conn.close()

# --- MÓDULO: VENTAS (MODIFICADO PARA LUZMA CON DETALLES) ---
elif menu == "💰 Ventas":
    st.title("💰 Registro de Producción")
    conn = conectar_db()
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)
    
    if v_data.empty or t_data.empty:
        st.warning("⚠️ Asegúrate de tener Vehículos en 'Flota' y Precios en 'Tarifas'.")
    else:
        with st.form("form_produccion"):
            c1, c2 = st.columns(2)
            v_sel = c1.selectbox("Vehículo", v_data['placa'])
            serv_sel = c2.selectbox("Tipo de Trabajo", t_data['servicio'].tolist())
            
            cant = st.number_input("Cantidad de Unidades", min_value=1, step=1)
            # Cálculo automático
            precio_u = t_data[t_data['servicio'] == serv_sel]['precio_unidad'].values[0]
            total_calc = cant * precio_u
            st.info(f"💵 **Total Liquidado: ${total_calc:,.0f}**")
            
            fec = st.date_input("Fecha")
            # CAMPO DE DETALLES SOLICITADO
            detalles = st.text_area("Detalles de la producción (Lote, Referencia, Observaciones)")
            
            if st.form_submit_button("💰 Registrar Venta"):
                v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
                cur = conn.cursor()
                cur.execute("""INSERT INTO ventas (vehiculo_id, servicio, cantidad, valor_total, fecha, detalles) 
                               VALUES (%s,%s,%s,%s,%s,%s)""", 
                            (int(v_id), serv_sel, int(cant), float(total_calc), fec, detalles))
                conn.commit(); st.success("Guardado correctamente"); st.rerun()
    
    st.divider()
    df_v_list = pd.read_sql("""SELECT s.fecha, v.placa, s.servicio, s.cantidad, s.valor_total as total, s.detalles 
                               FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.id DESC""", conn)
    st.dataframe(df_v_list, use_container_width=True, hide_index=True)
    conn.close()

# --- MÓDULO: TARIFAS ---
elif menu == "⚙️ Tarifas":
    st.title("⚙️ Precios por Servicio")
    conn = conectar_db()
    with st.form("form_t"):
        serv = st.text_input("Nombre del Servicio (Ej: Lavandería)")
        precio = st.number_input("Precio ($)", min_value=0)
        if st.form_submit_button("Guardar"):
            cur = conn.cursor()
            cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (serv, precio))
            conn.commit(); st.success("Tarifa guardada"); st.rerun()
    st.table(pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn))
    conn.close()

# --- MÓDULOS RESTANTES (IGUALES A TU CÓDIGO) ---
elif menu == "🚐 Flota":
    st.title("🚐 Administración de Vehículos")
    with st.form("form_f"):
        p = st.text_input("Placa").upper()
        m = st.text_input("Marca"); mod = st.text_input("Modelo"); cond = st.text_input("Conductor")
        if st.form_submit_button("➕ Añadir"):
            conn = conectar_db(); cur = conn.cursor()
            cur.execute("INSERT INTO vehiculos (placa, marca, modelo, conductor) VALUES (%s,%s,%s,%s)", (p, m, mod, cond))
            conn.commit(); conn.close(); st.success("Añadido"); st.rerun()
    conn = conectar_db(); st.dataframe(pd.read_sql("SELECT placa, marca, modelo, conductor FROM vehiculos", conn), use_container_width=True); conn.close()

elif menu == "💸 Gastos":
    st.title("💸 Registro de Gastos")
    conn = conectar_db(); v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    if not v_data.empty:
        with st.form("form_g"):
            v_sel = st.selectbox("Vehículo", v_data['placa'])
            v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
            tipo = st.selectbox("Concepto", ["Combustible", "Peaje", "Mantenimiento", "Lavada", "Otros"])
            monto = st.number_input("Valor ($)", min_value=0); fecha = st.date_input("Fecha"); det = st.text_input("Detalle")
            if st.form_submit_button("💾 Guardar"):
                cur = conn.cursor(); cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", (int(v_id), tipo, monto, fecha, det))
                conn.commit(); st.success("Registrado"); st.rerun()
    conn.close()

elif menu == "📑 Hoja de Vida":
    st.title("📑 Vencimientos")
    conn = conectar_db(); v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    with st.form("form_hv"):
        v_sel = st.selectbox("Vehículo", v_data['placa']); v_id = v_data[v_data['placa'] == v_sel]['id'].values[0]
        c1, c2 = st.columns(2)
        s_v = c1.date_input("SOAT"); t_v = c1.date_input("Tecno"); p_v = c1.date_input("Preventivo")
        pc_v = c2.date_input("P. Contractual"); pe_v = c2.date_input("P. Extra"); ptr_v = c2.date_input("Todo Riesgo"); to_v = st.date_input("T. Operaciones")
        if st.form_submit_button("🔄 Actualizar"):
            cur = conn.cursor(); cur.execute('''INSERT INTO hoja_vida (vehiculo_id, soat_vence, tecno_vence, prev_vence, p_contractual, p_extracontractual, p_todoriesgo, t_operaciones) 
                                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (vehiculo_id) DO UPDATE SET soat_vence=EXCLUDED.soat_vence, tecno_vence=EXCLUDED.tecno_vence, prev_vence=EXCLUDED.prev_vence''', (int(v_id), s_v, t_v, p_v, pc_v, pe_v, ptr_v, to_v))
            conn.commit(); st.success("Actualizado"); st.rerun()
    conn.close()

elif menu == "⚙️ Usuarios" and st.session_state.u_rol == "admin":
    st.title("⚙️ Gestión de Usuarios")
    with st.form("form_u"):
        nom = st.text_input("Nombre"); usr = st.text_input("Usuario"); clv = st.text_input("Clave"); rol = st.selectbox("Rol", ["vendedor", "admin"])
        if st.form_submit_button("👤 Crear"):
            conn = conectar_db(); cur = conn.cursor(); cur.execute("INSERT INTO usuarios (nombre, usuario, clave, rol) VALUES (%s,%s,%s,%s)", (nom, usr, clv, rol))
            conn.commit(); conn.close(); st.success("Usuario creado")
