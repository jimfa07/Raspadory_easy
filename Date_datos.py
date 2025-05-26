import streamlit as st
import pandas as pd
from datetime import datetime
from io import BytesIO
import os
import matplotlib.pyplot as plt

# Archivos
DATA_FILE = "registro_data.pkl"
DEPOSITS_FILE = "registro_depositos.pkl"
DEBIT_NOTES_FILE = "registro_notas_debito.pkl"

st.set_page_config(page_title="Registro Proveedores y Depositos", layout="wide")
st.title("Registro de Proveedores - Producto Pollo")

# Listas
proveedores = ["LIRIS SA", "Gallina 1", "Monze Anzules", "Medina"]
tipos_documento = ["Factura", "Nota de debito", "Nota de credito"]
agencias = [
    "Cajero Automatico Pichincha", "Cajero Automatico Pacifico",
    "Cajero Automatico Guayaquil", "Cajero Automatico Bolivariano",
    "Banco Pichincha", "Banco del Pacifico", "Banco de Guayaquil",
    "Banco Bolivariano"
]

# --- Inicializar estados ---

# Inicializar st.session_state.data
if "data" not in st.session_state:
    if os.path.exists(DATA_FILE):
        st.session_state.data = pd.read_pickle(DATA_FILE)
        # Asegúrate de que 'Fecha' sea tipo date para comparaciones
        st.session_state.data["Fecha"] = pd.to_datetime(
            st.session_state.data["Fecha"], errors="coerce").dt.date
    else:
        st.session_state.data = pd.DataFrame(columns=[
            "N", "Fecha", "Proveedor", "Producto", "Cantidad",
            "Peso Salida (kg)", "Peso Entrada (kg)", "Tipo Documento",
            "Cantidad de gavetas", "Precio Unitario ($)", "Promedio",
            "Kilos Restantes", "Libras Restantes", "Total ($)",
            "Monto Deposito", "Saldo diario", "Saldo Acumulado"
        ])
        # Fila inicial para el saldo acumulado (ajusta según necesites)
        fila_inicial = {col: None for col in st.session_state.data.columns}
        fila_inicial["Saldo diario"] = 0.00
        fila_inicial["Saldo Acumulado"] = -243.30 # Valor inicial de ejemplo
        st.session_state.data = pd.concat(
            [pd.DataFrame([fila_inicial]), st.session_state.data], ignore_index=True
        )

# Inicializar st.session_state.df (depósitos)
if "df" not in st.session_state:
    if os.path.exists(DEPOSITS_FILE):
        st.session_state.df = pd.read_pickle(DEPOSITS_FILE)
        st.session_state.df["Fecha"] = pd.to_datetime(
            st.session_state.df["Fecha"], errors="coerce").dt.date
    else:
        st.session_state.df = pd.DataFrame(columns=[
            "Fecha", "Empresa", "Agencia", "Monto", "Documento", "N"
        ])

# Inicializar st.session_state.notas (notas de débito)
if "notas" not in st.session_state:
    if os.path.exists(DEBIT_NOTES_FILE):
        st.session_state.notas = pd.read_pickle(DEBIT_NOTES_FILE)
        # Asegúrate de que 'Fecha' sea tipo date
        st.session_state.notas["Fecha"] = pd.to_datetime(
            st.session_state.notas["Fecha"], errors="coerce").dt.date
    else:
        st.session_state.notas = pd.DataFrame(columns=[
            "Fecha", "Libras calculadas", "Descuento", "Descuento posible", "Descuento real"
        ])

# --- Funciones Auxiliares ---
def calcular_saldos(df_registros, df_depositos, df_notas):
    """Recalcula los saldos diario y acumulado para todos los registros."""
    if df_registros.empty:
        return df_registros

    # Asegurarse de que las fechas sean del mismo tipo para la unión/merge
    df_registros['Fecha_dt'] = pd.to_datetime(df_registros['Fecha'])
    df_depositos['Fecha_dt'] = pd.to_datetime(df_depositos['Fecha'])
    df_notas['Fecha_dt'] = pd.to_datetime(df_notas['Fecha'])

    # Calcular Monto Deposito
    depositos_agrupados = df_depositos.groupby(['Fecha_dt', 'Empresa'])['Monto'].sum().reset_index()
    depositos_agrupados.rename(columns={'Monto': 'Monto Deposito Calculado'}, inplace=True)
    
    df_registros = pd.merge(
        df_registros,
        depositos_agrupados,
        left_on=['Fecha_dt', 'Proveedor'],
        right_on=['Fecha_dt', 'Empresa'],
        how='left'
    )
    df_registros['Monto Deposito'] = df_registros['Monto Deposito Calculado'].fillna(0)
    df_registros.drop(columns=['Monto Deposito Calculado', 'Empresa'], errors='ignore', inplace=True)

    # Calcular Saldo diario
    df_registros['Saldo diario'] = df_registros['Monto Deposito'] - df_registros['Total ($)']

    # Calcular Saldo Acumulado (requiere orden por fecha y luego N)
    df_registros = df_registros.sort_values(by=['Fecha_dt', 'N']).reset_index(drop=True)

    # Inicializar el primer Saldo Acumulado si no existe
    if df_registros.iloc[0]["Saldo Acumulado"] is None or pd.isna(df_registros.iloc[0]["Saldo Acumulado"]):
        df_registros.loc[0, "Saldo Acumulado"] = -243.30 + df_registros.loc[0, "Saldo diario"]
    
    # Recalcular saldos acumulados
    for i in range(1, len(df_registros)):
        df_registros.loc[i, "Saldo Acumulado"] = df_registros.loc[i-1, "Saldo Acumulado"] + df_registros.loc[i, "Saldo diario"]

    # Aplicar ajustes por notas de débito
    for _, nota in df_notas.iterrows():
        # Encuentra los registros desde la fecha de la nota en adelante
        indices_afectados = df_registros[df_registros['Fecha_dt'] >= nota['Fecha_dt']].index
        if not indices_afectados.empty:
            df_registros.loc[indices_afectados, 'Saldo Acumulado'] += nota['Descuento real']

    df_registros.drop(columns=['Fecha_dt'], inplace=True)
    return df_registros

@st.cache_data
def convertir_excel(df):
    output = BytesIO()
    df_copy = df.copy()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_copy.to_excel(writer, index=False)
    output.seek(0)
    return output

# --- Navegación entre secciones ---
opcion = st.sidebar.selectbox("Selecciona una vista", ["Registro", "Reporte Semanal", "Reporte Mensual", "Graficos"])

if opcion == "Registro":
    # --- Sidebar - Registro de Depositos ---
    st.sidebar.header("Registro de Depositos")
    with st.sidebar.form("registro_deposito_form"):
        fecha_d = st.date_input("Fecha del registro", value=datetime.today(), key="fecha_d")
        empresa = st.selectbox("Empresa (Proveedor)", proveedores, key="empresa_deposito")
        agencia = st.selectbox("Agencia", agencias, key="agencia")
        monto = st.number_input("Monto", min_value=0.0, format="%.2f", key="monto_deposito")
        submit_d = st.form_submit_button("Agregar Deposito")

    if submit_d:
        documento = "Deposito" if "Cajero" in agencia else "Transferencia"
        df_actual_depositos = st.session_state.df

        # Asignar un número N único por fecha si no existe, o usar el existente
        numero_n = df_actual_depositos[df_actual_depositos["Fecha"] == fecha_d]["N"].iloc[0] \
                   if not df_actual_depositos[df_actual_depositos["Fecha"] == fecha_d].empty \
                   else f"{df_actual_depositos['Fecha'].nunique() + 1:02}" # Genera un N si no existe la fecha

        nuevo_registro_deposito = {
            "Fecha": fecha_d,
            "Empresa": empresa,
            "Agencia": agencia,
            "Monto": monto,
            "Documento": documento,
            "N": numero_n
        }

        st.session_state.df = pd.concat([df_actual_depositos, pd.DataFrame([nuevo_registro_deposito])], ignore_index=True)
        st.session_state.df.to_pickle(DEPOSITS_FILE)
        # Recalcular saldos después de un cambio en los depósitos
        st.session_state.data = calcular_saldos(st.session_state.data.copy(), st.session_state.df.copy(), st.session_state.notas.copy())
        st.session_state.data.to_pickle(DATA_FILE) # Guardar los datos actualizados
        st.sidebar.success("Deposito agregado exitosamente y saldos actualizados.")
        st.rerun() # Volver a ejecutar para mostrar los cambios

    # --- Eliminar deposito ---
    st.sidebar.subheader("Eliminar un Deposito")
    if not st.session_state.df.empty:
        st.session_state.df["Mostrar"] = st.session_state.df.apply(
            lambda row: f"{row['Fecha']} - {row['Empresa']} - ${row['Monto']:.2f}", axis=1
        )
        deposito_a_eliminar = st.sidebar.selectbox(
            "Selecciona un deposito a eliminar", st.session_state.df["Mostrar"], key="eliminar_deposito_select"
        )
        if st.sidebar.button("Eliminar deposito seleccionado", key="eliminar_deposito_btn"):
            index_eliminar = st.session_state.df[st.session_state.df["Mostrar"] == deposito_a_eliminar].index[0]
            st.session_state.df.drop(index=index_eliminar, inplace=True)
            st.session_state.df.reset_index(drop=True, inplace=True)
            st.session_state.df.to_pickle(DEPOSITS_FILE)
            # Recalcular saldos después de un cambio en los depósitos
            st.session_state.data = calcular_saldos(st.session_state.data.copy(), st.session_state.df.copy(), st.session_state.notas.copy())
            st.session_state.data.to_pickle(DATA_FILE) # Guardar los datos actualizados
            st.sidebar.success("Deposito eliminado correctamente y saldos actualizados.")
            st.rerun() # Volver a ejecutar para mostrar los cambios
    else:
        st.sidebar.write("No hay depósitos para eliminar.")
    
    # --- Registro de Proveedores ---
    st.subheader("Registro de Proveedores")
    
    # --- Importar datos desde Excel ---
    st.subheader("Importar datos desde Excel")
    archivo_excel = st.file_uploader("Selecciona un archivo Excel", type=["xlsx"], key="excel_uploader")

    if archivo_excel is not None:
        try:
            df_importado = pd.read_excel(archivo_excel)
            st.write("Vista previa de los datos importados:", df_importado.head())

            if st.button("Cargar datos a registros", key="cargar_excel_btn"):
                columnas_requeridas = [
                    "Fecha", "Proveedor", "Producto", "Cantidad",
                    "Peso Salida (kg)", "Peso Entrada (kg)", "Tipo Documento",
                    "Cantidad de gavetas", "Precio Unitario ($)"
                ]
                if all(col in df_importado.columns for col in columnas_requeridas):
                    df_importado["Fecha"] = pd.to_datetime(df_importado["Fecha"]).dt.date
                    
                    # Eliminar la fila inicial si existe antes de añadir nuevos registros
                    if st.session_state.data["Fecha"].iloc[0] is None:
                        st.session_state.data = st.session_state.data.iloc[1:].copy()

                    for _, fila in df_importado.iterrows():
                        cantidad = fila["Cantidad"]
                        peso_salida = fila["Peso Salida (kg)"]
                        peso_entrada = fila["Peso Entrada (kg)"]
                        libras_restantes = (peso_salida - peso_entrada) * 2.20462
                        promedio = libras_restantes / cantidad if cantidad != 0 else 0
                        total = libras_restantes * fila["Precio Unitario ($)"]

                        # Generar N para el nuevo registro importado
                        fecha_registro = fila["Fecha"]
                        enumeracion = st.session_state.data[st.session_state.data["Fecha"] == fecha_registro]["N"].iloc[0] \
                                      if not st.session_state.data[st.session_state.data["Fecha"] == fecha_registro].empty \
                                      else st.session_state.data["Fecha"].nunique() + 1
                        
                        nueva_fila = {
                            "N": enumeracion,
                            "Fecha": fecha_registro,
                            "Proveedor": fila["Proveedor"],
                            "Producto": fila["Producto"],
                            "Cantidad": cantidad,
                            "Peso Salida (kg)": peso_salida,
                            "Peso Entrada (kg)": peso_entrada,
                            "Tipo Documento": fila["Tipo Documento"],
                            "Cantidad de gavetas": fila["Cantidad de gavetas"],
                            "Precio Unitario ($)": fila["Precio Unitario ($)"],
                            "Promedio": promedio,
                            "Kilos Restantes": peso_salida - peso_entrada,
                            "Libras Restantes": libras_restantes,
                            "Total ($)": total,
                            "Monto Deposito": 0.0, # Se calculará después
                            "Saldo diario": 0.0,  # Se calculará después
                            "Saldo Acumulado": 0.0 # Se calculará después
                        }
                        st.session_state.data = pd.concat([st.session_state.data, pd.DataFrame([nueva_fila])], ignore_index=True)

                    st.session_state.data = calcular_saldos(st.session_state.data.copy(), st.session_state.df.copy(), st.session_state.notas.copy())
                    st.session_state.data.to_pickle(DATA_FILE)
                    st.success("Datos importados correctamente y saldos actualizados.")
                    st.rerun()
                else:
                    st.error("El archivo no contiene todas las columnas requeridas. Asegúrate de que estén: 'Fecha', 'Proveedor', 'Producto', 'Cantidad', 'Peso Salida (kg)', 'Peso Entrada (kg)', 'Tipo Documento', 'Cantidad de gavetas', 'Precio Unitario ($)'.")
        except Exception as e:
            st.error(f"Error al cargar el archivo: {e}")
                        
    # --- Formulario de Registro Manual ---
    with st.form("formulario_registro_manual"):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            fecha_manual = st.date_input("Fecha", value=datetime.today(), key="fecha_manual")
            proveedor_manual = st.selectbox("Proveedor", proveedores, key="proveedor_manual")
        with col2:
            cantidad_manual = st.number_input("Cantidad", min_value=0, step=1, key="cantidad_manual")
            peso_salida_manual = st.number_input("Peso Salida (kg)", min_value=0.0, step=0.1, key="peso_salida_manual")
        with col3:
            peso_entrada_manual = st.number_input("Peso Entrada (kg)", min_value=0.0, step=0.1, key="peso_entrada_manual")
            documento_manual = st.selectbox("Tipo Documento", tipos_documento, key="documento_manual")
        with col4:
            gavetas_manual = st.number_input("Cantidad de gavetas", min_value=0, step=1, key="gavetas_manual")
            precio_unitario_manual = st.number_input("Precio Unitario ($)", min_value=0.0, step=0.01, key="precio_unitario_manual")

        enviar_manual = st.form_submit_button("Agregar Registro")

    if enviar_manual:
        # Eliminar la fila inicial si existe antes de añadir nuevos registros
        if st.session_state.data["Fecha"].iloc[0] is None:
            st.session_state.data = st.session_state.data.iloc[1:].copy()

        producto = "Pollo"
        kilos_restantes = peso_salida_manual - peso_entrada_manual
        libras_restantes = kilos_restantes * 2.20462
        promedio = libras_restantes / cantidad_manual if cantidad_manual != 0 else 0
        total = libras_restantes * precio_unitario_manual
        
        # Generar N para el nuevo registro manual
        enumeracion_manual = st.session_state.data[st.session_state.data["Fecha"] == fecha_manual]["N"].iloc[0] \
                             if not st.session_state.data[st.session_state.data["Fecha"] == fecha_manual].empty \
                             else st.session_state.data["Fecha"].nunique() + 1
        
        nueva_fila_manual = {
            "N": enumeracion_manual,
            "Fecha": fecha_manual,
            "Proveedor": proveedor_manual,
            "Producto": producto,
            "Cantidad": cantidad_manual,
            "Peso Salida (kg)": peso_salida_manual,
            "Peso Entrada (kg)": peso_entrada_manual,
            "Tipo Documento": documento_manual,
            "Cantidad de gavetas": gavetas_manual,
            "Precio Unitario ($)": precio_unitario_manual,
            "Promedio": promedio,
            "Kilos Restantes": kilos_restantes,
            "Libras Restantes": libras_restantes,
            "Total ($)": total,
            "Monto Deposito": 0.0, # Se calculará después
            "Saldo diario": 0.0,  # Se calculará después
            "Saldo Acumulado": 0.0 # Se calculará después
        }

        st.session_state.data = pd.concat([st.session_state.data, pd.DataFrame([nueva_fila_manual])], ignore_index=True)
        st.session_state.data = calcular_saldos(st.session_state.data.copy(), st.session_state.df.copy(), st.session_state.notas.copy())
        st.session_state.data.to_pickle(DATA_FILE)
        st.success("Registro agregado correctamente y saldos actualizados.")
        st.rerun()

    # --- Registro de Nota de Debito ---
    st.subheader("Registro de Nota de Debito")
    with st.form("nota_debito_form"):
        col1_nota, col2_nota, col3_nota = st.columns(3)
        with col1_nota:
            fecha_nota = st.date_input("Fecha de Nota", key="fecha_nota")
        with col2_nota:
            descuento = st.number_input("Descuento (%)", min_value=0.0, max_value=1.0, step=0.01, key="descuento_nota")
        with col3_nota:
            descuento_real = st.number_input("Descuento Real ($)", min_value=0.0, step=0.01, key="descuento_real_nota")
        agregar_nota = st.form_submit_button("Agregar Nota de Debito")

    if agregar_nota:
        df_registros_actual = st.session_state.data.copy()
        # Sumar libras restantes solo de la fecha de la nota
        libras_calculadas = df_registros_actual[df_registros_actual["Fecha"] == fecha_nota]["Libras Restantes"].sum()
        descuento_posible = libras_calculadas * descuento
        nueva_nota = {
            "Fecha": fecha_nota,
            "Libras calculadas": libras_calculadas,
            "Descuento": descuento,
            "Descuento posible": descuento_posible,
            "Descuento real": descuento_real
        }
        st.session_state.notas = pd.concat([st.session_state.notas, pd.DataFrame([nueva_nota])], ignore_index=True)
        st.session_state.notas.to_pickle(DEBIT_NOTES_FILE)
        # Recalcular saldos después de un cambio en las notas de débito
        st.session_state.data = calcular_saldos(st.session_state.data.copy(), st.session_state.df.copy(), st.session_state.notas.copy())
        st.session_state.data.to_pickle(DATA_FILE) # Guardar los datos actualizados
        st.success("Nota de débito agregada correctamente y saldos actualizados.")
        st.rerun()

    # --- Mostrar y Eliminar Registros ---
    st.subheader("Tabla de Registros")
    df_display_registros = st.session_state.data.copy()
    
    # Manejar el caso de la fila inicial con None en "Total ($)"
    df_display_registros["Mostrar"] = df_display_registros.apply(
        lambda row: f"{row['Fecha']} - {row['Proveedor']} - ${row['Total ($)']:.2f}"
        if pd.notna(row["Total ($)"]) else f"{row['Fecha']} - {row['Proveedor']} - Sin total",
        axis=1
    )
    
    if not df_display_registros.empty:
        registro_a_eliminar = st.selectbox("Selecciona un registro para eliminar", df_display_registros["Mostrar"], key="select_eliminar_registro")
        if st.button("Eliminar Registro Seleccionado", key="btn_eliminar_registro"):
            index_eliminar = df_display_registros[df_display_registros["Mostrar"] == registro_a_eliminar].index[0]
            st.session_state.data.drop(index=index_eliminar, inplace=True)
            st.session_state.data.reset_index(drop=True, inplace=True)
            # Recalcular saldos después de eliminar un registro
            st.session_state.data = calcular_saldos(st.session_state.data.copy(), st.session_state.df.copy(), st.session_state.notas.copy())
            st.session_state.data.to_pickle(DATA_FILE)
            st.success("Registro eliminado correctamente y saldos actualizados.")
            st.rerun()
    else:
        st.write("No hay registros para mostrar o eliminar.")

    # Formatear columnas para la visualización
    df_display_registros["Saldo diario"] = df_display_registros["Saldo diario"].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
    df_display_registros["Saldo Acumulado"] = df_display_registros["Saldo Acumulado"].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
    st.dataframe(df_display_registros.drop(columns=["Mostrar"], errors="ignore"), use_container_width=True)

    # --- Tabla de Notas de Debito ---
    st.subheader("Tabla de Notas de Debito")
    df_display_notas = st.session_state.notas.copy()
    if not df_display_notas.empty:
        df_display_notas["Mostrar"] = df_display_notas.apply(
            lambda row: f"{row['Fecha']} - Libras: {row['Libras calculadas']:.2f} - Descuento real: ${row['Descuento real']:.2f}", axis=1
        )
        st.dataframe(df_display_notas.drop(columns=["Mostrar"], errors="ignore"), use_container_width=True)
    else:
        st.write("No hay notas de débito para mostrar.")

    # --- Eliminar Nota de Debito ---
    st.subheader("Eliminar una Nota de Debito")
    if not st.session_state.notas.empty:
        nota_a_eliminar_select = st.selectbox("Selecciona una nota para eliminar", st.session_state.notas["Mostrar"], key="select_eliminar_nota")
        if st.button("Eliminar Nota de Debito seleccionada", key="btn_eliminar_nota"):
            index_eliminar_nota = st.session_state.notas[st.session_state.notas["Mostrar"] == nota_a_eliminar_select].index[0]
            st.session_state.notas.drop(index=index_eliminar_nota, inplace=True)
            st.session_state.notas.reset_index(drop=True, inplace=True)
            st.session_state.notas.to_pickle(DEBIT_NOTES_FILE)
            # Recalcular saldos después de eliminar una nota de débito
            st.session_state.data = calcular_saldos(st.session_state.data.copy(), st.session_state.df.copy(), st.session_state.notas.copy())
            st.session_state.data.to_pickle(DATA_FILE) # Guardar los datos actualizados
            st.success("Nota de débito eliminada correctamente y saldos actualizados.")
            st.rerun()
    else:
        st.write("No hay notas de débito para eliminar.")

    # --- Descargar Excel ---
    st.download_button(
        label="Descargar Registros Excel",
        data=convertir_excel(st.session_state.data.drop(columns=["Mostrar"], errors="ignore")),
        file_name="registro_proveedores_depositos.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    with st.expander("Ver depósitos registrados"):
        st.dataframe(st.session_state.df.drop(columns=["Mostrar"], errors="ignore"), use_container_width=True)

# --- Secciones de Reportes y Gráficos ---
elif opcion == "Reporte Semanal":
    st.header("Reporte Semanal")
    df_reporte = st.session_state.data.copy()
    df_reporte["Fecha"] = pd.to_datetime(df_reporte["Fecha"], errors="coerce")
    
    if not df_reporte.empty:
        semana_actual = df_reporte["Fecha"].dt.isocalendar().week.max()
        df_semana = df_reporte[df_reporte["Fecha"].dt.isocalendar().week == semana_actual]
        st.dataframe(df_semana.drop(columns=["Mostrar"], errors="ignore"), use_container_width=True)
    else:
        st.write("No hay datos para generar un reporte semanal.")

elif opcion == "Reporte Mensual":
    st.header("Reporte Mensual")
    df_reporte = st.session_state.data.copy()
    df_reporte["Fecha"] = pd.to_datetime(df_reporte["Fecha"], errors="coerce")
    
    if not df_reporte.empty:
        mes_actual = datetime.today().month
        df_mes = df_reporte[df_reporte["Fecha"].dt.month == mes_actual]
        st.dataframe(df_mes.drop(columns=["Mostrar"], errors="ignore"), use_container_width=True)
    else:
        st.write("No hay datos para generar un reporte mensual.")

elif opcion == "Graficos":
    st.header("Gráficos de Proveedores")
    df_graficos = st.session_state.data.copy()
    df_graficos["Fecha"] = pd.to_datetime(df_graficos["Fecha"], errors="coerce")

    if not df_graficos.empty:
        # Gráfico Total por Proveedor
        total_por_proveedor = df_graficos.groupby("Proveedor")["Total ($)"].sum().sort_values(ascending=False)
        fig, ax = plt.subplots()
        total_por_proveedor.plot(kind="bar", ax=ax)
        ax.set_ylabel("Total ($)")
        ax.set_title("Total por Proveedor")
        st.pyplot(fig)

        # Gráfico Saldo Acumulado
        st.subheader("Saldo Acumulado a lo largo del tiempo")
        df_ordenado = df_graficos.sort_values("Fecha")
        fig2, ax2 = plt.subplots()
        ax2.plot(df_ordenado["Fecha"], df_ordenado["Saldo Acumulado"], marker="o")
        ax2.set_ylabel("Saldo Acumulado ($)")
        ax2.set_title("Evolución del Saldo Acumulado")
        plt.xticks(rotation=45) # Rotar las etiquetas del eje X para mejor legibilidad
        st.pyplot(fig2)
    else:
        st.write("No hay datos para generar gráficos.")

