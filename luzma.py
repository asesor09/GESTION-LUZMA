import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import io

# --- 1. CONFIGURACIÓN Y CONEXIÓN ---
st.set_page_config(page_title="Transportes Luzma - Gestión Total", layout="wide", page_icon="🚐")

def conectar_db():
    if "url_luzma" not in st.secrets:
        st.error("❌ Falta 'url_luzma' en Secrets de Streamlit.")
        return None
    try:
        conn = psycopg2.connect(st.secrets["url_luzma"])
        return conn
    except Exception as e:
        st.error(f"❌ Error de conexión: {e}")
        return None

# --- 2. FUNCIÓN PARA GENERAR EXCEL ---
def generar_excel(df_ventas, df_gastos):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_ventas.to_excel(writer, index=False, sheet_name='Ventas_Ingresos')
        df_gastos.to_excel(writer, index=False, sheet_name='Gastos_Egresos')
    return output.getvalue()

# --- 3. LOGIN ---
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
            else: st.sidebar.error("Credenciales incorrectas")
    st.stop()

# --- 4. MENÚ LATERAL ---
st.sidebar.write(f"👤 **{st.session_state.u_name}**")
menu = st.sidebar.selectbox("📂 MÓDULOS", ["📊 Dashboard", "🚐 Flota", "💸 Gastos", "💰 Ventas", "📑 Hoja de Vida", "⚙️ Tarifas"])

if st.sidebar.button("🚪 Cerrar Sesión"):
    st.session_state.logged_in = False
    st.rerun()

conn = conectar_db()
if not conn: st.stop()

# --- MODULO: DASHBOARD (RESUMEN Y EXCEL) ---
if menu == "📊 Dashboard":
    st.title("📊 Resumen General de Operaciones")
    
    # Consultas para el reporte
    df_v_all = pd.read_sql("SELECT s.fecha, v.placa, s.cliente as servicio, s.valor_viaje as monto, s.descripcion FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id", conn)
    df_g_all = pd.read_sql("SELECT g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id", conn)

    c1, c2, c3 = st.columns(3)
    ingresos = df_v_all['monto'].sum()
    egresos = df_g_all['monto'].sum()
    c1.metric("Ingresos (Ventas)", f"${ingresos:,.0f}")
    c2.metric("Egresos (Gastos)", f"${egresos:,.0f}", delta_color="inverse")
    c3.metric("Utilidad", f"${ingresos - egresos:,.0f}")

    st.divider()
    st.subheader("📥 Exportar Datos a Excel")
    excel_data = generar_excel(df_v_all, df_g_all)
    st.download_button(label="Click aquí para descargar Reporte.xlsx", data=excel_data, file_name=f"Reporte_Luzma_{datetime.now().date()}.xlsx", mime="application/vnd.ms-excel")

# --- MODULO: VENTAS (DETALLES INCLUIDOS) ---
elif menu == "💰 Ventas":
    st.title("💰 Registro y Detalle de Ventas")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    t_data = pd.read_sql("SELECT servicio, precio_unidad FROM tarifario", conn)

    with st.form("f_v"):
        v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
        s_sel = st.selectbox("Servicio", t_data['servicio'].tolist() if not t_data.empty else [])
        cant = st.number_input("Cantidad", min_value=1)
        desc = st.text_input("Descripción (Ej: Lote #, Destino)")
        if st.form_submit_button("Guardar Venta"):
            v_id = int(v_data[v_data['placa'] == v_sel]['id'].values[0])
            precio = float(t_data[t_data['servicio'] == s_sel]['precio_unidad'].values[0])
            cur = conn.cursor()
            cur.execute("INSERT INTO ventas (vehiculo_id, cliente, valor_viaje, fecha, descripcion, cantidad) VALUES (%s,%s,%s,%s,%s,%s)", 
                        (v_id, s_sel, cant*precio, datetime.now().date(), desc, cant))
            conn.commit(); st.success("Venta guardada"); st.rerun()

    st.subheader("🔍 Historial de Ventas (Detalle)")
    df_v_det = pd.read_sql("SELECT s.id, s.fecha, v.placa, s.cliente, s.cantidad, s.valor_viaje, s.descripcion FROM ventas s JOIN vehiculos v ON s.vehiculo_id = v.id ORDER BY s.id DESC", conn)
    st.dataframe(df_v_det, use_container_width=True, hide_index=True)

# --- MODULO: GASTOS (DETALLES INCLUIDOS) ---
elif menu == "💸 Gastos":
    st.title("💸 Registro y Detalle de Gastos")
    v_data = pd.read_sql("SELECT id, placa FROM vehiculos", conn)

    with st.form("f_g"):
        v_sel = st.selectbox("Vehículo", v_data['placa'] if not v_data.empty else [])
        tipo = st.selectbox("Concepto", ["Combustible", "Mantenimiento", "Peaje", "Otros"])
        monto = st.number_input("Valor", min_value=0)
        det = st.text_input("Detalle del gasto")
        if st.form_submit_button("Guardar Gasto"):
            v_id = int(v_data[v_data['placa'] == v_sel]['id'].values[0])
            cur = conn.cursor()
            cur.execute("INSERT INTO gastos (vehiculo_id, tipo_gasto, monto, fecha, detalle) VALUES (%s,%s,%s,%s,%s)", (v_id, tipo, monto, datetime.now().date(), det))
            conn.commit(); st.success("Gasto guardado"); st.rerun()

    st.subheader("🔍 Historial de Gastos (Detalle)")
    df_g_det = pd.read_sql("SELECT g.id, g.fecha, v.placa, g.tipo_gasto, g.monto, g.detalle FROM gastos g JOIN vehiculos v ON g.vehiculo_id = v.id ORDER BY g.id DESC", conn)
    st.dataframe(df_g_det, use_container_width=True, hide_index=True)

# --- MODULO: HOJA DE VIDA (ALERTAS) ---
elif menu == "📑 Hoja de Vida":
    st.title("📑 Alertas de Documentación")
    v_data_h = pd.read_sql("SELECT id, placa FROM vehiculos", conn)
    
    if not v_data_h.empty:
        with st.expander("📅 Actualizar Vencimientos"):
            with st.form("f_hv"):
                v_sel = st.selectbox("Vehículo", v_data_h['placa'])
                v_id = int(v_data_h[v_data_h['placa'] == v_sel]['id'].values[0])
                c1, c2 = st.columns(2)
                s_v = c1.date_input("SOAT")
                t_v = c1.date_input("Tecno")
                pc_v = c2.date_input("P. Contractual")
                ptr_v = c2.date_input("Todo Riesgo")
                if st.form_submit_button("Actualizar Fechas"):
                    cur = conn.cursor()
                    cur.execute("INSERT INTO hoja_vida (vehiculo_id, soat_vence, tecno_vence, p_contractual, p_todoriesgo) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (vehiculo_id) DO UPDATE SET soat_vence=EXCLUDED.soat_vence, tecno_vence=EXCLUDED.tecno_vence", (v_id, s_v, t_v, pc_v, ptr_v))
                    conn.commit(); st.success("Fechas actualizadas"); st.rerun()

        st.divider()
        df_hv = pd.read_sql("SELECT v.placa, h.* FROM vehiculos v LEFT JOIN hoja_vida h ON v.id = h.vehiculo_id", conn)
        hoy = datetime.now().date()
        for _, row in df_hv.iterrows():
            st.subheader(f"🚚 {row['placa']}")
            cols = st.columns(4)
            for i, (name, fecha) in enumerate([("SOAT", row['soat_vence']), ("TECNO", row['tecno_vence']), ("P.CONT", row['p_contractual']), ("TODO RIESGO", row['p_todoriesgo'])]):
                if fecha:
                    d = (fecha - hoy).days
                    if d < 0: cols[i].error(f"❌ {name}\nVENCIDO")
                    elif d <= 15: cols[i].warning(f"⚠️ {name}\n{d} días")
                    else: cols[i].success(f"✅ {name}\nAl día")
                else: cols[i].info(f"⚪ {name}\nS/D")

# --- MODULO: FLOTA (AGREGAR CARROS) ---
elif menu == "🚐 Flota":
    st.title("🚐 Control de Flota (25 Carros)")
    with st.form("f_flota"):
        p = st.text_input("Placa").upper()
        m = st.text_input("Marca")
        if st.form_submit_button("Registrar Nuevo Vehículo"):
            cur = conn.cursor()
            cur.execute("INSERT INTO vehiculos (placa, marca) VALUES (%s,%s)", (p, m))
            conn.commit(); st.success(f"Vehículo {p} agregado"); st.rerun()
    
    st.dataframe(pd.read_sql("SELECT * FROM vehiculos", conn), use_container_width=True)

# --- MODULO: TARIFAS ---
elif menu == "⚙️ Tarifas":
    st.title("⚙️ Configuración de Precios")
    with st.form("f_t"):
        s = st.text_input("Servicio")
        p = st.number_input("Precio ($)", min_value=0)
        if st.form_submit_button("Guardar Tarifa"):
            cur = conn.cursor()
            cur.execute("INSERT INTO tarifario (servicio, precio_unidad) VALUES (%s,%s) ON CONFLICT (servicio) DO UPDATE SET precio_unidad=EXCLUDED.precio_unidad", (s, p))
            conn.commit(); st.rerun()
    st.table(pd.read_sql("SELECT * FROM tarifario", conn))

conn.close()
