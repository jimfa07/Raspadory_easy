import streamlit as st
import pandas as pd
from datetime import datetime
from io import BytesIO
import os
import matplotlib.pyplot as plt

# --- 1. CONSTANTES ---
DATA_FILE = "registro_data.pkl"
DEPOSITS_FILE = "registro_depositos.pkl"
DEBIT_NOTES_FILE = "registro_notas_debito.pkl"

INITIAL_ACCUMULATED_BALANCE = -243.30
PRODUCT_NAME = "Pollo"
LBS_PER_KG = 2.20462

PROVEEDORES = ["LIRIS SA", "Gallina 1", "Monze Anzules", "Medina"]
TIPOS_DOCUMENTO = ["Factura", "Nota de debito", "Nota de credito"]
AGENCIAS = [
    "Cajero Automatico Pichincha", "Cajero Automatico Pacifico",
    "Cajero Automatico Guayaquil", "Cajero Automatico Bolivariano",
    "Banco Pichincha", "Banco del Pacifico", "Banco de Guayaquil",
    "Banco Bolivariano"
]

# Columnas esperadas para los DataFrames
COLUMNS_DATA = [
    "N", "Fecha", "Proveedor", "Producto", "Cantidad",
    "Peso Salida (kg)", "Peso Entrada (kg)", "Tipo Documento",
    "Cantidad de gavetas", "Precio Unitario ($)", "Promedio",
    "Kilos Restantes", "Libras Restantes", "Total ($)",
    "Monto Deposito", "Saldo diario", "Saldo Acumulado"
]
COLUMNS_DEPOSITS = ["Fecha", "Empresa", "Agencia", "Monto", "Documento", "N"]
COLUMNS_DEBIT_NOTES = ["Fecha", "Libras calculadas", "Descuento", "Descuento posible", "Descuento real"]

# --- 2. FUNCIONES DE CARGA Y GUARDADO DE DATOS ---
def load_dataframe(file_path, default_columns, date_columns=None):
    """Carga un DataFrame desde un archivo pickle o crea uno vacío."""
    if os.path.exists(file_path):
        try:
            df = pd.read_pickle(file_path)
            if date_columns:
                for col in date_columns:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
            return df
        except Exception as e:
            st.error(f"Error al cargar {file_path}: {e}")
            return pd.DataFrame(columns=default_columns)
    else:
        return pd.DataFrame(columns=default_columns)

def save_dataframe(df, file_path):
    """Guarda un DataFrame en un archivo pickle."""
    try:
        df.to_pickle(file_path)
        return True
    except Exception as e:
        st.error(f"Error al guardar {file_path}: {e}")
        return False

# --- 3. FUNCIONES DE INICIALIZACIÓN DEL ESTADO ---
def initialize_session_state():
    """Inicializa todos los DataFrames en st.session_state."""
    if "data" not in st.session_state:
        st.session_state.data = load_dataframe(DATA_FILE, COLUMNS_DATA, ["Fecha"])
        if st.session_state.data.empty:
            # Añadir fila inicial si el DF está vacío para el Saldo Acumulado
            fila_inicial = {col: None for col in COLUMNS_DATA}
            fila_inicial["Saldo diario"] = 0.00
            fila_inicial["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE
            st.session_state.data = pd.concat(
                [pd.DataFrame([fila_inicial]), st.session_state.data], ignore_index=True
            )

    if "df" not in st.session_state:
        st.session_state.df = load_dataframe(DEPOSITS_FILE, COLUMNS_DEPOSITS, ["Fecha"])

    if "notas" not in st.session_state:
        st.session_state.notas = load_dataframe(DEBIT_NOTES_FILE, COLUMNS_DEBIT_NOTES, ["Fecha"])

    # Recalcular saldos acumulados de forma robusta al inicio o cuando los datos cambian
    recalculate_accumulated_balances()

# --- 4. FUNCIONES DE LÓGICA DE NEGOCIO Y CÁLCULOS ---
def recalculate_accumulated_balances():
    """
    Recalcula el Saldo Acumulado para todo el DataFrame de registros
    basándose en los saldos diarios y las notas de débito.
    """
    df_data = st.session_state.data.copy()
    df_deposits = st.session_state.df.copy()
    df_notes = st.session_state.notas.copy()

    # Asegurarse de que las columnas de fecha sean datetime.date para comparaciones
    df_data["Fecha"] = pd.to_datetime(df_data["Fecha"], errors="coerce").dt.date
    df_deposits["Fecha"] = pd.to_datetime(df_deposits["Fecha"], errors="coerce").dt.date
    df_notes["Fecha"] = pd.to_datetime(df_notes["Fecha"], errors="coerce").dt.date

    # Calcular Monto Deposito para cada registro de datos
    # Suma los montos de depósito por Fecha y Empresa
    deposits_summary = df_deposits.groupby(["Fecha", "Empresa"])["Monto"].sum().reset_index()
    deposits_summary.rename(columns={"Monto": "Monto Deposito Calculado"}, inplace=True)

    # Fusionar los depósitos calculados con los datos de registro
    df_data = pd.merge(
        df_data,
        deposits_summary,
        on=["Fecha", "Proveedor"], # Asumimos 'Empresa' en depósitos es 'Proveedor' en datos
        how="left"
    )
    df_data["Monto Deposito Calculado"] = df_data["Monto Deposito Calculado"].fillna(0)

    # Actualizar la columna 'Monto Deposito' en df_data
    df_data["Monto Deposito"] = df_data["Monto Deposito Calculado"]
    df_data.drop(columns=["Monto Deposito Calculado"], inplace=True) # Eliminar columna temporal

    # Recalcular el Total ($) para asegurarnos de que sea preciso
    df_data["Kilos Restantes"] = df_data["Peso Salida (kg)"] - df_data["Peso Entrada (kg)"]
    df_data["Libras Restantes"] = df_data["Kilos Restantes"] * LBS_PER_KG
    df_data["Promedio"] = df_data.apply(lambda row: row["Libras Restantes"] / row["Cantidad"] if row["Cantidad"] != 0 else 0, axis=1)
    df_data["Total ($)"] = df_data["Libras Restantes"] * df_data["Precio Unitario ($)"]

    # Calcular Saldo diario inicial
    df_data["Saldo diario"] = df_data["Monto Deposito"] - df_data["Total ($)"]

    # Incorporar notas de débito al saldo diario
    if not df_notes.empty:
        # Agrupar notas de débito por fecha
        notes_by_date = df_notes.groupby("Fecha")["Descuento real"].sum().reset_index()
        notes_by_date.rename(columns={"Descuento real": "NotaDebitoAjuste"}, inplace=True)

        # Fusionar ajustes de notas de débito con el DataFrame de datos
        # Crear una columna temporal de fecha única para la fusión
        df_data_unique_dates = df_data[["Fecha"]].drop_duplicates().sort_values("Fecha")
        df_data_unique_dates = pd.merge(df_data_unique_dates, notes_by_date, on="Fecha", how="left")
        df_data_unique_dates["NotaDebitoAjuste"] = df_data_unique_dates["NotaDebitoAjuste"].fillna(0)

        # Aplicar el ajuste de nota de débito al saldo diario para las filas correspondientes
        # Esto es un poco más complejo si la nota de débito afecta un día específico y se debe distribuir.
        # Una forma simplista es añadir el ajuste a la primera entrada del día o a la suma total del día.
        # Para mantener el comportamiento original (sumar a Saldo Acumulado a partir de la fecha),
        # lo haremos como un ajuste directo al Saldo Acumulado cumulativo.

        # Para un cálculo preciso del Saldo Acumulado, sumamos todos los saldos diarios por fecha
        # y luego aplicamos los ajustes de las notas de débito cronológicamente.

        # Calcular la suma de Saldo diario por fecha para facilitar la acumulación
        daily_summary = df_data.groupby("Fecha")["Saldo diario"].sum().reset_index()
        daily_summary.rename(columns={"Saldo diario": "SaldoDiarioConsolidado"}, inplace=True)

        # Fusionar con los ajustes de notas de débito
        full_daily_balances = pd.merge(daily_summary, notes_by_date, on="Fecha", how="left")
        full_daily_balances["NotaDebitoAjuste"] = full_daily_balances["NotaDebitoAjuste"].fillna(0)

        # Calcular el saldo diario total ajustado
        full_daily_balances["SaldoDiarioAjustado"] = full_daily_balances["SaldoDiarioConsolidado"] + full_daily_balances["NotaDebitoAjuste"]

        # Calcular el Saldo Acumulado
        full_daily_balances = full_daily_balances.sort_values("Fecha")
        full_daily_balances["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE + full_daily_balances["SaldoDiarioAjustado"].cumsum()

        # Ahora, fusionar este Saldo Acumulado nuevamente con df_data.
        # Esto asignará el Saldo Acumulado del final del día a todas las entradas de ese día.
        df_data = pd.merge(df_data, full_daily_balances[["Fecha", "Saldo Acumulado"]], on="Fecha", how="left", suffixes=('', '_new'))
        df_data["Saldo Acumulado"] = df_data["Saldo Acumulado_new"]
        df_data.drop(columns=["Saldo Acumulado_new"], inplace=True)
    else:
        # Si no hay notas de débito, el saldo acumulado es solo la suma de los saldos diarios.
        df_data = df_data.sort_values("Fecha")
        df_data["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE + df_data.groupby("Fecha")["Saldo diario"].transform(lambda x: x.cumsum())

    # Asegurarse de que el orden sea consistente
    df_data = df_data.sort_values(["Fecha", "N"])

    # Finalmente, actualiza el st.session_state.data con los saldos recalculados
    st.session_state.data = df_data
    save_dataframe(st.session_state.data, DATA_FILE)


def add_deposit_record(fecha_d, empresa, agencia, monto):
    """Agrega un nuevo registro de depósito."""
    df_actual = st.session_state.df.copy()
    
    # Determinar el número 'N' para el depósito
    # Si hay depósitos para la misma fecha, usa el N existente, sino, un nuevo N
    coincidencia = df_actual[
        (df_actual["Fecha"] == fecha_d)
    ]
    if not coincidencia.empty:
        # Encuentra el 'N' más alto para esa fecha y lo incrementa, o usa el existente si ya hay un N para esa fecha/empresa
        existing_n_for_date = coincidencia["N"].max()
        numero = existing_n_for_date
    else:
        # Nuevo N basado en el número de fechas únicas + 1 en el histórico
        numero = f"{df_actual['Fecha'].nunique() + 1:02}"
    
    documento = "Deposito" if "Cajero" in agencia else "Transferencia"
    
    nuevo_registro = {
        "Fecha": fecha_d,
        "Empresa": empresa,
        "Agencia": agencia,
        "Monto": monto,
        "Documento": documento,
        "N": numero
    }
    st.session_state.df = pd.concat([df_actual, pd.DataFrame([nuevo_registro])], ignore_index=True)
    if save_dataframe(st.session_state.df, DEPOSITS_FILE):
        st.success("Deposito agregado exitosamente. Recalculando saldos...")
        recalculate_accumulated_balances() # Recalcula tras añadir un depósito
        st.experimental_rerun() # Refresca la página para limpiar el formulario y mostrar datos actualizados
    else:
        st.error("Error al guardar el depósito.")

def delete_deposit_record(deposito_info_to_delete):
    """Elimina un registro de depósito seleccionado."""
    df_to_delete_from = st.session_state.df.copy()
    index_eliminar = df_to_delete_from[df_to_delete_from["Mostrar"] == deposito_info_to_delete].index
    if not index_eliminar.empty:
        df_to_delete_from.drop(index=index_eliminar, inplace=True)
        df_to_delete_from.reset_index(drop=True, inplace=True)
        st.session_state.df = df_to_delete_from
        if save_dataframe(st.session_state.df, DEPOSITS_FILE):
            st.sidebar.success("Deposito eliminado correctamente. Recalculando saldos...")
            recalculate_accumulated_balances() # Recalcula tras eliminar un depósito
            st.experimental_rerun()
        else:
            st.sidebar.error("Error al eliminar el depósito.")
    else:
        st.sidebar.warning("No se encontró el depósito a eliminar.")

def add_supplier_record(fecha, proveedor, cantidad, peso_salida, peso_entrada, tipo_documento, gavetas, precio_unitario):
    """Agrega un nuevo registro de proveedor."""
    df = st.session_state.data.copy()

    # Validación básica de entradas
    if cantidad <= 0 and (peso_salida <= 0 or peso_entrada <= 0):
        st.error("Por favor, ingresa una Cantidad y/o Pesos válidos (mayores a cero).")
        return False

    kilos_restantes = peso_salida - peso_entrada
    libras_restantes = kilos_restantes * LBS_PER_KG
    promedio = libras_restantes / cantidad if cantidad != 0 else 0
    total = libras_restantes * precio_unitario

    # Determinar el número 'N' para el registro de datos
    # Si la fecha ya existe, usa su 'N', sino, el siguiente N
    if fecha in df["Fecha"].dropna().values:
        enumeracion = df[df["Fecha"] == fecha]["N"].iloc[0]
    else:
        # Calcular el próximo N basado en fechas únicas existentes
        max_n = df["N"].dropna().apply(lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0).max()
        enumeracion = f"{max_n + 1:02}" # Formato de dos dígitos

    # Monto Deposito, Saldo diario, Saldo Acumulado serán recalculados por `recalculate_accumulated_balances()`
    # No los calculamos aquí directamente para evitar redundancia y errores de estado.

    nueva_fila = {
        "N": enumeracion,
        "Fecha": fecha,
        "Proveedor": proveedor,
        "Producto": PRODUCT_NAME,
        "Cantidad": cantidad,
        "Peso Salida (kg)": peso_salida,
        "Peso Entrada (kg)": peso_entrada,
        "Tipo Documento": tipo_documento,
        "Cantidad de gavetas": gavetas,
        "Precio Unitario ($)": precio_unitario,
        "Promedio": promedio,
        "Kilos Restantes": kilos_restantes,
        "Libras Restantes": libras_restantes,
        "Total ($)": total,
        "Monto Deposito": 0.0, # Se llenará con el recalculado
        "Saldo diario": 0.0, # Se llenará con el recalculado
        "Saldo Acumulado": 0.0 # Se llenará con el recalculado
    }

    st.session_state.data = pd.concat([df, pd.DataFrame([nueva_fila])], ignore_index=True)
    if save_dataframe(st.session_state.data, DATA_FILE):
        st.success("Registro agregado correctamente. Recalculando saldos...")
        recalculate_accumulated_balances() # Recalcula tras añadir un registro
        st.experimental_rerun()
        return True
    else:
        st.error("Error al guardar el registro.")
        return False

def import_excel_data(archivo_excel):
    """Importa datos desde un archivo Excel y los añade a los registros."""
    try:
        df_importado = pd.read_excel(archivo_excel)
        st.write("Vista previa de los datos importados:", df_importado.head())

        columnas_requeridas = [
            "Fecha", "Proveedor", "Producto", "Cantidad",
            "Peso Salida (kg)", "Peso Entrada (kg)", "Tipo Documento",
            "Cantidad de gavetas", "Precio Unitario ($)"
        ]
        if not all(col in df_importado.columns for col in columnas_requeridas):
            st.error("El archivo no contiene todas las columnas requeridas. Asegúrate de tener: " + ", ".join(columnas_requeridas))
            return

        if st.button("Cargar datos a registros"):
            # Procesar datos importados de forma vectorizada
            df_importado["Fecha"] = pd.to_datetime(df_importado["Fecha"], errors="coerce").dt.date
            df_importado.dropna(subset=["Fecha"], inplace=True) # Eliminar filas con fechas no válidas

            df_importado["Kilos Restantes"] = df_importado["Peso Salida (kg)"] - df_importado["Peso Entrada (kg)"]
            df_importado["Libras Restantes"] = df_importado["Kilos Restantes"] * LBS_PER_KG
            df_importado["Promedio"] = df_importado.apply(lambda row: row["Libras Restantes"] / row["Cantidad"] if row["Cantidad"] != 0 else 0, axis=1)
            df_importado["Total ($)"] = df_importado["Libras Restantes"] * df_importado["Precio Unitario ($)"]

            # Asignar el número 'N' a cada fila importada
            current_n_values = st.session_state.data["N"].dropna().apply(lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0)
            next_n = current_n_values.max() + 1 if not current_n_values.empty else 1

            # Mapear 'N' existente para fechas ya registradas o asignar nuevo 'N'
            existing_n_map = st.session_state.data.set_index("Fecha")["N"].to_dict()
            df_importado["N"] = df_importado["Fecha"].apply(lambda x: existing_n_map.get(x, f"{next_n + df_importado[df_importado['Fecha'] <= x].index.get_loc(x):02}"))
            # Nota: La asignación de 'N' puede ser compleja si hay fechas repetidas
            # y se espera un 'N' incremental por cada _nueva_ fecha.
            # Para este ejemplo, si la fecha ya existe, usa su N. Si no, asigna el siguiente N disponible.
            # La lógica actual de N es un poco inconsistente entre add_supplier_record y la importación.
            # Se necesita una lógica única y clara para 'N'.
            # Simplificado: Asignamos 'N' en orden de fecha, si ya existe la fecha, usa el N.

            # Limpiar columnas de saldo antes de la concatenación para que `recalculate_accumulated_balances` las recalcule
            df_importado["Monto Deposito"] = 0.0
            df_importado["Saldo diario"] = 0.0
            df_importado["Saldo Acumulado"] = 0.0
            df_importado["Producto"] = PRODUCT_NAME # Asegurarse que el producto sea 'Pollo'

            # Concatenar el DataFrame importado al estado de sesión
            st.session_state.data = pd.concat([st.session_state.data, df_importado[COLUMNS_DATA]], ignore_index=True)
            st.session_state.data.drop_duplicates(subset=["Fecha", "Proveedor", "Peso Salida (kg)", "Peso Entrada (kg)"], keep="last", inplace=True) # Evitar duplicados simples

            if save_dataframe(st.session_state.data, DATA_FILE):
                st.success("Datos importados correctamente. Recalculando saldos...")
                recalculate_accumulated_balances() # Recalcula tras importar datos
                st.experimental_rerun()
            else:
                st.error("Error al guardar los datos importados.")

    except Exception as e:
        st.error(f"Error al cargar o procesar el archivo Excel: {e}")

def delete_record(record_info_to_delete):
    """Elimina un registro de la tabla principal."""
    df_to_delete_from = st.session_state.data.copy()
    index_eliminar = df_to_delete_from[df_to_delete_from["Mostrar"] == record_info_to_delete].index
    if not index_eliminar.empty:
        df_to_delete_from.drop(index=index_eliminar, inplace=True)
        df_to_delete_from.reset_index(drop=True, inplace=True)
        st.session_state.data = df_to_delete_from
        if save_dataframe(st.session_state.data, DATA_FILE):
            st.success("Registro eliminado correctamente. Recalculando saldos...")
            recalculate_accumulated_balances() # Recalcula tras eliminar un registro
            st.experimental_rerun()
        else:
            st.error("Error al eliminar el registro.")
    else:
        st.warning("No se encontró el registro a eliminar.")

def add_debit_note(fecha_nota, descuento, descuento_real):
    """Agrega una nueva nota de débito."""
    df = st.session_state.data.copy()
    
    # Validar que existan libras restantes para la fecha
    libras_calculadas = df[df["Fecha"] == fecha_nota]["Libras Restantes"].sum()
    if libras_calculadas == 0:
        st.warning(f"No hay 'Libras Restantes' registradas para la fecha {fecha_nota}. La nota de débito se agregará pero su 'Descuento posible' será 0.")

    descuento_posible = libras_calculadas * descuento
    nueva_nota = {
        "Fecha": fecha_nota,
        "Libras calculadas": libras_calculadas,
        "Descuento": descuento,
        "Descuento posible": descuento_posible,
        "Descuento real": descuento_real
    }
    st.session_state.notas = pd.concat([st.session_state.notas, pd.DataFrame([nueva_nota])], ignore_index=True)
    if save_dataframe(st.session_state.notas, DEBIT_NOTES_FILE):
        st.success("Nota de debito agregada correctamente. Recalculando saldos...")
        recalculate_accumulated_balances() # Recalcula tras añadir una nota de débito
        st.experimental_rerun()
    else:
        st.error("Error al guardar la nota de débito.")

def delete_debit_note_record(nota_info_to_delete):
    """Elimina una nota de débito seleccionada."""
    df_to_delete_from = st.session_state.notas.copy()
    index_eliminar = df_to_delete_from[df_to_delete_from["Mostrar"] == nota_info_to_delete].index
    if not index_eliminar.empty:
        df_to_delete_from.drop(index=index_eliminar, inplace=True)
        df_to_delete_from.reset_index(drop=True, inplace=True)
        st.session_state.notas = df_to_delete_from
        if save_dataframe(st.session_state.notas, DEBIT_NOTES_FILE):
            st.success("Nota de debito eliminada correctamente. Recalculando saldos...")
            recalculate_accumulated_balances() # Recalcula tras eliminar una nota
            st.experimental_rerun()
        else:
            st.error("Error al eliminar la nota de débito.")
    else:
        st.warning("No se encontró la nota de débito a eliminar.")

# --- 5. FUNCIONES DE INTERFAZ DE USUARIO (UI) ---
def render_deposit_registration_form():
    """Renderiza el formulario de registro de depósitos en el sidebar."""
    st.sidebar.header("Registro de Depósitos")
    with st.sidebar.form("registro_form", clear_on_submit=True):
        fecha_d = st.date_input("Fecha del registro", value=datetime.today(), key="fecha_d")
        empresa = st.selectbox("Empresa (Proveedor)", PROVEEDORES, key="empresa")
        agencia = st.selectbox("Agencia", AGENCIAS, key="agencia")
        monto = st.number_input("Monto", min_value=0.0, format="%.2f", key="monto")
        submit_d = st.form_submit_button("Agregar Depósito")

        if submit_d:
            if monto <= 0:
                st.error("El monto del depósito debe ser mayor que cero.")
            else:
                add_deposit_record(fecha_d, empresa, agencia, monto)

def render_delete_deposit_section():
    """Renderiza la sección para eliminar depósitos en el sidebar."""
    st.sidebar.subheader("Eliminar un Depósito")
    if not st.session_state.df.empty:
        st.session_state.df["Mostrar"] = st.session_state.df.apply(
            lambda row: f"{row['Fecha']} - {row['Empresa']} - ${row['Monto']:.2f}", axis=1
        )
        deposito_a_eliminar = st.sidebar.selectbox(
            "Selecciona un depósito a eliminar", st.session_state.df["Mostrar"], key="delete_deposit_select"
        )
        if st.sidebar.button("Eliminar depósito seleccionado", key="delete_deposit_button"):
            if st.sidebar.checkbox("Confirmar eliminación del depósito", key="confirm_delete_deposit"):
                delete_deposit_record(deposito_a_eliminar)
            else:
                st.sidebar.warning("Por favor, confirma la eliminación del depósito.")
    else:
        st.sidebar.write("No hay depósitos para eliminar.")

def render_import_excel_section():
    """Renderiza la sección para importar datos desde Excel."""
    st.subheader("Importar datos desde Excel")
    archivo_excel = st.file_uploader("Selecciona un archivo Excel", type=["xlsx"])
    if archivo_excel is not None:
        import_excel_data(archivo_excel)

def render_supplier_registration_form():
    """Renderiza el formulario de registro de proveedores."""
    st.subheader("Registro de Proveedores")
    with st.form("formulario", clear_on_submit=True):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            fecha = st.date_input("Fecha", value=datetime.today())
            proveedor = st.selectbox("Proveedor", PROVEEDORES)
        with col2:
            cantidad = st.number_input("Cantidad", min_value=0, step=1)
            peso_salida = st.number_input("Peso Salida (kg)", min_value=0.0, step=0.1)
        with col3:
            peso_entrada = st.number_input("Peso Entrada (kg)", min_value=0.0, step=0.1)
            documento = st.selectbox("Tipo Documento", TIPOS_DOCUMENTO)
        with col4:
            gavetas = st.number_input("Cantidad de gavetas", min_value=0, step=1)
            precio_unitario = st.number_input("Precio Unitario ($)", min_value=0.0, step=0.01)

        enviar = st.form_submit_button("Agregar Registro")

        if enviar:
            if cantidad == 0 and (peso_salida == 0 and peso_entrada == 0):
                st.error("No se puede agregar un registro con Cantidad y Pesos en cero.")
            elif peso_entrada > peso_salida:
                st.error("El Peso Entrada (kg) no puede ser mayor que el Peso Salida (kg).")
            else:
                add_supplier_record(fecha, proveedor, cantidad, peso_salida, peso_entrada, documento, gavetas, precio_unitario)

def render_debit_note_form():
    """Renderiza el formulario para agregar notas de débito."""
    st.subheader("Registro de Nota de Débito")
    with st.form("nota_debito", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            fecha_nota = st.date_input("Fecha de Nota")
        with col2:
            descuento = st.number_input("Descuento (%) (ej. 0.05 para 5%)", min_value=0.0, max_value=1.0, step=0.01)
        with col3:
            descuento_real = st.number_input("Descuento Real ($)", min_value=0.0, step=0.01)
        agregar_nota = st.form_submit_button("Agregar Nota de Débito")

        if agregar_nota:
            if descuento_real <= 0 and descuento <= 0:
                st.error("Debes ingresar un valor para Descuento (%) o Descuento Real ($).")
            else:
                add_debit_note(fecha_nota, descuento, descuento_real)

def display_formatted_dataframe(df_source, title, columns_to_format=None, exclude_mostrar=True):
    """Muestra un DataFrame con formato de moneda."""
    df_display = df_source.copy()
    if columns_to_format:
        for col in columns_to_format:
            if col in df_display.columns:
                df_display[col] = df_display[col].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
    
    if exclude_mostrar and "Mostrar" in df_display.columns:
        df_display = df_display.drop(columns=["Mostrar"])
        
    st.subheader(title)
    st.dataframe(df_display, use_container_width=True)


def render_tables_and_download():
    """Renderiza las tablas de registros, notas de débito y la opción de descarga."""
    
    # Tabla de Registros
    if not st.session_state.data.empty:
        # Añadir columna 'Mostrar' para la selección de eliminación
        st.session_state.data["Mostrar"] = st.session_state.data.apply(
            lambda row: f"{row['Fecha']} - {row['Proveedor']} - ${row['Total ($)']:.2f}"
            if pd.notna(row["Total ($)"]) else f"{row['Fecha']} - {row['Proveedor']} - Sin total",
            axis=1
        )
        display_formatted_dataframe(
            st.session_state.data,
            "Tabla de Registros",
            columns_to_format=["Saldo diario", "Saldo Acumulado", "Total ($)", "Monto Deposito", "Precio Unitario ($)"],
            exclude_mostrar=False # No excluir para la selección de eliminación
        )
        st.subheader("Eliminar un Registro")
        registro_a_eliminar = st.selectbox("Selecciona un registro para eliminar", st.session_state.data["Mostrar"], key="delete_record_select")
        if st.button("Eliminar Registro Seleccionado", key="delete_record_button"):
            if st.checkbox("Confirmar eliminación del registro", key="confirm_delete_record"):
                delete_record(registro_a_eliminar)
            else:
                st.warning("Por favor, confirma la eliminación del registro.")
    else:
        st.subheader("Tabla de Registros")
        st.info("No hay registros disponibles. Por favor, agrega algunos o importa desde Excel.")

    # Tabla de Notas de Débito
    if not st.session_state.notas.empty:
        st.session_state.notas["Mostrar"] = st.session_state.notas.apply(
            lambda row: f"{row['Fecha']} - Libras: {row['Libras calculadas']:.2f} - Descuento real: ${row['Descuento real']:.2f}", axis=1
        )
        display_formatted_dataframe(
            st.session_state.notas,
            "Tabla de Notas de Débito",
            columns_to_format=["Descuento posible", "Descuento real"],
            exclude_mostrar=False # No excluir para la selección de eliminación
        )
        st.subheader("Eliminar una Nota de Débito")
        nota_a_eliminar = st.selectbox("Selecciona una nota para eliminar", st.session_state.notas["Mostrar"], key="delete_debit_note_select")
        if st.button("Eliminar Nota de Débito seleccionada", key="delete_debit_note_button"):
            if st.checkbox("Confirmar eliminación de la nota de débito", key="confirm_delete_debit_note"):
                delete_debit_note_record(nota_a_eliminar)
            else:
                st.warning("Por favor, confirma la eliminación de la nota de débito.")
    else:
        st.subheader("Tabla de Notas de Débito")
        st.info("No hay notas de débito registradas.")


    # Descarga de Excel
    @st.cache_data # Caching para evitar recálculos innecesarios
    def convertir_excel(df):
        output = BytesIO()
        df_copy = df.copy()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_copy.to_excel(writer, index=False)
        output.seek(0)
        return output

    st.download_button(
        label="Descargar Registros en Excel",
        data=convertir_excel(st.session_state.data.drop(columns=["Mostrar"], errors="ignore")),
        file_name="registro_proveedores_depositos.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    with st.expander("Ver depósitos registrados"):
        display_formatted_dataframe(
            st.session_state.df,
            "Depósitos Registrados",
            columns_to_format=["Monto"]
        )

def render_weekly_report():
    """Renderiza el reporte semanal."""
    st.header("Reporte Semanal")
    df = st.session_state.data.copy()
    if not df.empty:
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        # Asegurarse de que el año también sea considerado para la semana
        df["YearWeek"] = df["Fecha"].dt.strftime('%Y-%U')
        semana_actual = df["YearWeek"].max()
        df_semana = df[df["YearWeek"] == semana_actual]
        display_formatted_dataframe(df_semana, f"Registros de la Semana {semana_actual}")
    else:
        st.info("No hay datos para generar el reporte semanal.")

def render_monthly_report():
    """Renderiza el reporte mensual."""
    st.header("Reporte Mensual")
    df = st.session_state.data.copy()
    if not df.empty:
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        mes_actual = datetime.today().month
        año_actual = datetime.today().year
        df_mes = df[(df["Fecha"].dt.month == mes_actual) & (df["Fecha"].dt.year == año_actual)]
        display_formatted_dataframe(df_mes, f"Registros del Mes {mes_actual}/{año_actual}")
    else:
        st.info("No hay datos para generar el reporte mensual.")

def render_charts():
    """Renderiza los gráficos de datos."""
    st.header("Gráficos de Proveedores y Saldo")
    df = st.session_state.data.copy()
    if df.empty:
        st.info("No hay datos suficientes para generar gráficos. Por favor, agregue registros.")
        return

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df.dropna(subset=["Fecha"], inplace=True)

    st.subheader("Total por Proveedor")
    total_por_proveedor = df.groupby("Proveedor")["Total ($)"].sum().sort_values(ascending=False)
    if not total_por_proveedor.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        total_por_proveedor.plot(kind="bar", ax=ax, color='skyblue')
        ax.set_ylabel("Total ($)")
        ax.set_title("Total ($) por Proveedor")
        ax.ticklabel_format(style='plain', axis='y') # Evita notación científica en el eje Y
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        st.pyplot(fig)
    else:
        st.info("No hay datos de 'Total ($)' por proveedor para graficar.")


    st.subheader("Evolución del Saldo Acumulado")
    df_ordenado = df.sort_values("Fecha")
    # Asegurarse de que el Saldo Acumulado sea numérico para graficar
    df_ordenado["Saldo Acumulado"] = pd.to_numeric(df_ordenado["Saldo Acumulado"], errors='coerce')
    df_ordenado.dropna(subset=["Saldo Acumulado"], inplace=True) # Eliminar NaN si los hay

    if not df_ordenado.empty:
        fig2, ax2 = plt.subplots(figsize=(12, 6))
        ax2.plot(df_ordenado["Fecha"], df_ordenado["Saldo Acumulado"], marker="o", linestyle='-', color='green')
        ax2.set_ylabel("Saldo Acumulado ($)")
        ax2.set_title("Evolución del Saldo Acumulado")
        ax2.grid(True, linestyle='--', alpha=0.7)
        ax2.ticklabel_format(style='plain', axis='y')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        st.pyplot(fig2)
    else:
        st.info("No hay datos de 'Saldo Acumulado' para graficar.")

# --- CONFIGURACIÓN PRINCIPAL DE LA PÁGINA ---
st.set_page_config(page_title="Registro Proveedores y Depósitos", layout="wide")
st.title("Sistema de Gestión de Proveedores - Producto Pollo")

# --- INICIALIZAR EL ESTADO DE LA SESIÓN ---
initialize_session_state()

# --- NAVEGACIÓN PRINCIPAL ---
opcion = st.sidebar.selectbox("Selecciona una vista", ["Registro", "Reporte Semanal", "Reporte Mensual", "Gráficos"])

# --- RENDERIZAR SECCIONES SEGÚN LA OPCIÓN SELECCIONADA ---
if opcion == "Registro":
    render_deposit_registration_form()
    render_delete_deposit_section()
    st.sidebar.markdown("---") # Separador visual

    render_import_excel_section()
    render_supplier_registration_form()
    render_debit_note_form()
    st.markdown("---") # Separador visual
    render_tables_and_download()

elif opcion == "Reporte Semanal":
    render_weekly_report()

elif opcion == "Reporte Mensual":
    render_monthly_report()

elif opcion == "Gráficos":
    render_charts()

