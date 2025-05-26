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
                        # Convertir a datetime y luego a date para uniformidad
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
            # Si el DF está vacío, inicializarlo con solo la fila de saldo acumulado inicial
            # Esta fila no debe ser una entrada de registro normal
            fila_inicial_saldo = {col: None for col in COLUMNS_DATA}
            fila_inicial_saldo["Fecha"] = datetime(1900, 1, 1).date() # Fecha muy antigua para que siempre sea la primera
            fila_inicial_saldo["Proveedor"] = "BALANCE_INICIAL"
            fila_inicial_saldo["Saldo diario"] = 0.00
            fila_inicial_saldo["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE
            st.session_state.data = pd.DataFrame([fila_inicial_saldo])
        else:
            # Asegurarse de que el balance inicial exista si ya hay datos
            if not any(st.session_state.data["Proveedor"] == "BALANCE_INICIAL"):
                fila_inicial_saldo = {col: None for col in COLUMNS_DATA}
                fila_inicial_saldo["Fecha"] = datetime(1900, 1, 1).date()
                fila_inicial_saldo["Proveedor"] = "BALANCE_INICIAL"
                fila_inicial_saldo["Saldo diario"] = 0.00
                fila_inicial_saldo["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE
                st.session_state.data = pd.concat([pd.DataFrame([fila_inicial_saldo]), st.session_state.data], ignore_index=True)


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

    # --- Pre-procesamiento y cálculos para df_data ---
    # Asegurarse que las columnas de números son numéricas
    for col in ["Cantidad", "Peso Salida (kg)", "Peso Entrada (kg)", "Precio Unitario ($)"]:
        df_data[col] = pd.to_numeric(df_data[col], errors='coerce').fillna(0)

    df_data["Kilos Restantes"] = df_data["Peso Salida (kg)"] - df_data["Peso Entrada (kg)"]
    df_data["Libras Restantes"] = df_data["Kilos Restantes"] * LBS_PER_KG
    df_data["Promedio"] = df_data.apply(lambda row: row["Libras Restantes"] / row["Cantidad"] if row["Cantidad"] != 0 else 0, axis=1)
    df_data["Total ($)"] = df_data["Libras Restantes"] * df_data["Precio Unitario ($)"]

    # Excluir la fila de 'BALANCE_INICIAL' de los cálculos diarios y de depósito
    df_data_operaciones = df_data[df_data["Proveedor"] != "BALANCE_INICIAL"].copy()
    df_initial_balance = df_data[df_data["Proveedor"] == "BALANCE_INICIAL"].copy()


    # Calcular Monto Deposito para cada registro de datos
    deposits_summary = df_deposits.groupby(["Fecha", "Empresa"])["Monto"].sum().reset_index()
    deposits_summary.rename(columns={"Monto": "Monto Deposito Calculado"}, inplace=True)

    # Fusionar los depósitos calculados con los datos de registro (solo para operaciones)
    df_data_operaciones = pd.merge(
        df_data_operaciones,
        deposits_summary,
        left_on=["Fecha", "Proveedor"],
        right_on=["Fecha", "Empresa"],
        how="left"
    )
    df_data_operaciones["Monto Deposito Calculado"] = df_data_operaciones["Monto Deposito Calculado"].fillna(0)
    df_data_operaciones["Monto Deposito"] = df_data_operaciones["Monto Deposito Calculado"]
    df_data_operaciones.drop(columns=["Monto Deposito Calculado", "Empresa"], inplace=True, errors='ignore') # Eliminar columna temporal y 'Empresa' si existe

    # Calcular Saldo diario para operaciones
    df_data_operaciones["Saldo diario"] = df_data_operaciones["Monto Deposito"] - df_data_operaciones["Total ($)"]

    # Consolidar saldos diarios por fecha para las operaciones
    daily_summary_operaciones = df_data_operaciones.groupby("Fecha")["Saldo diario"].sum().reset_index()
    daily_summary_operaciones.rename(columns={"Saldo diario": "SaldoDiarioConsolidado"}, inplace=True)

    # Incorporar notas de débito al saldo diario consolidado
    if not df_notes.empty:
        notes_by_date = df_notes.groupby("Fecha")["Descuento real"].sum().reset_index()
        notes_by_date.rename(columns={"Descuento real": "NotaDebitoAjuste"}, inplace=True)

        full_daily_balances = pd.merge(daily_summary_operaciones, notes_by_date, on="Fecha", how="left")
        full_daily_balances["NotaDebitoAjuste"] = full_daily_balances["NotaDebitoAjuste"].fillna(0)
        full_daily_balances["SaldoDiarioAjustado"] = full_daily_balances["SaldoDiarioConsolidado"] + full_daily_balances["NotaDebitoAjuste"]
    else:
        full_daily_balances = daily_summary_operaciones.copy()
        full_daily_balances["SaldoDiarioAjustado"] = full_daily_balances["SaldoDiarioConsolidado"]

    # Calcular el Saldo Acumulado
    full_daily_balances = full_daily_balances.sort_values("Fecha")
    full_daily_balances["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE + full_daily_balances["SaldoDiarioAjustado"].cumsum()

    # Fusionar el Saldo Acumulado de vuelta a df_data_operaciones
    df_data_operaciones = pd.merge(df_data_operaciones, full_daily_balances[["Fecha", "Saldo Acumulado"]], on="Fecha", how="left", suffixes=('', '_new'))
    df_data_operaciones["Saldo Acumulado"] = df_data_operaciones["Saldo Acumulado_new"]
    df_data_operaciones.drop(columns=["Saldo Acumulado_new"], inplace=True)

    # Reintegrar la fila de BALANCE_INICIAL al DataFrame principal
    # Asegurarse de que la fila inicial tenga el saldo acumulado correcto
    if not df_initial_balance.empty:
        df_initial_balance["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE
        # Para las otras columnas de saldo diario/deposito/total, pueden ser 0 o NaN según el diseño
        df_initial_balance["Monto Deposito"] = 0.0
        df_initial_balance["Saldo diario"] = 0.0
        df_initial_balance["Total ($)"] = 0.0
        
        # Concatenar la fila inicial de nuevo
        df_data = pd.concat([df_initial_balance, df_data_operaciones], ignore_index=True)
    else:
        df_data = df_data_operaciones

    # Asegurarse de que el orden sea consistente para la visualización
    df_data = df_data.sort_values(["Fecha", "N"]).reset_index(drop=True)

    # Limpiar filas con Nulos de fechas si se generaron por un merge con fechas inexistentes
    df_data.dropna(subset=["Fecha"], inplace=True)

    # Finalmente, actualiza el st.session_state.data con los saldos recalculados
    st.session_state.data = df_data
    save_dataframe(st.session_state.data, DATA_FILE)


def add_deposit_record(fecha_d, empresa, agencia, monto):
    """Agrega un nuevo registro de depósito."""
    df_actual = st.session_state.df.copy()
    
    # Asegurarse que la columna 'N' sea string para poder trabajar con '01', '02', etc.
    df_actual["N"] = df_actual["N"].astype(str)

    # Determinar el número 'N' para el depósito
    # Filtrar depósitos para la misma fecha
    coincidencia_fecha = df_actual[df_actual["Fecha"] == fecha_d]

    if not coincidencia_fecha.empty:
        # Si ya hay un depósito para esta fecha, usa el 'N' más alto existente para esa fecha
        # Convertir 'N' a entero para MAX y luego a string de nuevo
        max_n_for_date = coincidencia_fecha["N"].apply(lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0).max()
        numero = f"{max_n_for_date:02}" # Formato de dos dígitos
    else:
        # Si no hay depósitos para esta fecha, crea un nuevo N basado en el número de fechas únicas
        # Obtener el máximo N global
        max_n_global = df_actual["N"].apply(lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0).max()
        numero = f"{max_n_global + 1:02}" # Formato de dos dígitos
    
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
        st.session_state.deposit_added = True # Flag para indicar que se añadió un depósito
        st.success("Deposito agregado exitosamente. Recalculando saldos...")
    else:
        st.error("Error al guardar el depósito.")

def delete_deposit_record(deposito_info_to_delete):
    """Elimina un registro de depósito seleccionado."""
    df_to_delete_from = st.session_state.df.copy()
    
    # Asegurarse de que 'Mostrar' exista para la comparación
    if "Mostrar" not in df_to_delete_from.columns:
        df_to_delete_from["Mostrar"] = df_to_delete_from.apply(
            lambda row: f"{row['Fecha']} - {row['Empresa']} - ${row['Monto']:.2f}", axis=1
        )

    index_eliminar = df_to_delete_from[df_to_delete_from["Mostrar"] == deposito_info_to_delete].index
    if not index_eliminar.empty:
        df_to_delete_from.drop(index=index_eliminar, inplace=True)
        df_to_delete_from.reset_index(drop=True, inplace=True)
        st.session_state.df = df_to_delete_from
        if save_dataframe(st.session_state.df, DEPOSITS_FILE):
            st.session_state.deposit_deleted = True # Flag para indicar que se eliminó un depósito
            st.sidebar.success("Deposito eliminado correctamente. Recalculando saldos...")
        else:
            st.sidebar.error("Error al eliminar el depósito.")
    else:
        st.sidebar.warning("No se encontró el depósito a eliminar.")

def add_supplier_record(fecha, proveedor, cantidad, peso_salida, peso_entrada, tipo_documento, gavetas, precio_unitario):
    """Agrega un nuevo registro de proveedor."""
    df = st.session_state.data.copy()

    # Validación básica de entradas
    if cantidad < 0 or peso_salida < 0 or peso_entrada < 0 or precio_unitario < 0 or gavetas < 0:
        st.error("Los valores numéricos no pueden ser negativos.")
        return False
    if cantidad == 0 and peso_salida == 0 and peso_entrada == 0:
        st.error("Por favor, ingresa una Cantidad y/o Pesos válidos (no pueden ser todos cero).")
        return False
    if peso_entrada > peso_salida:
        st.error("El Peso Entrada (kg) no puede ser mayor que el Peso Salida (kg).")
        return False

    kilos_restantes = peso_salida - peso_entrada
    libras_restantes = kilos_restantes * LBS_PER_KG
    promedio = libras_restantes / cantidad if cantidad != 0 else 0
    total = libras_restantes * precio_unitario

    # Determinar el número 'N' para el registro de datos
    # Asegurarse que la columna 'N' sea string para poder trabajar con '01', '02', etc.
    df["N"] = df["N"].astype(str)

    # Filtrar filas que NO son el "BALANCE_INICIAL" para calcular el N
    df_operaciones_existente = df[df["Proveedor"] != "BALANCE_INICIAL"]

    df_filtered_by_date = df_operaciones_existente[df_operaciones_existente["Fecha"] == fecha]
    if not df_filtered_by_date.empty:
        # Si ya hay un registro para esta fecha, usa el 'N' más alto existente para esa fecha
        # Convertir 'N' a entero para MAX y luego a string de nuevo
        max_n_for_date = df_filtered_by_date["N"].apply(lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0).max()
        enumeracion = f"{max_n_for_date:02}"
    else:
        # Si no hay registros para esta fecha, crea un nuevo N basado en el número de fechas únicas
        # Obtener el máximo N global de registros de operaciones (excluyendo la fila inicial)
        max_n_global = df_operaciones_existente["N"].apply(lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0).max()
        enumeracion = f"{max_n_global + 1:02}" # Formato de dos dígitos

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
        "Saldo diario": 0.0,  # Se llenará con el recalculado
        "Saldo Acumulado": 0.0 # Se llenará con el recalculado
    }

    # Asegurarse de que la fila de balance inicial no sea eliminada por drop_duplicates
    if "BALANCE_INICIAL" in df["Proveedor"].values:
        df_temp = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()
        df_balance = df[df["Proveedor"] == "BALANCE_INICIAL"].copy()
    else:
        df_temp = df.copy()
        df_balance = pd.DataFrame(columns=COLUMNS_DATA) # DataFrame vacío si no hay balance inicial

    df_temp = pd.concat([df_temp, pd.DataFrame([nueva_fila])], ignore_index=True)
    df_temp.drop_duplicates(subset=["Fecha", "Proveedor", "Peso Salida (kg)", "Peso Entrada (kg)", "Tipo Documento"], keep='last', inplace=True)
    df_temp.reset_index(drop=True, inplace=True)

    st.session_state.data = pd.concat([df_balance, df_temp], ignore_index=True)
    
    if save_dataframe(st.session_state.data, DATA_FILE):
        st.session_state.record_added = True # Flag para indicar que se añadió un registro
        st.success("Registro agregado correctamente. Recalculando saldos...")
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

        # Solo mostrar el botón de carga si el archivo es válido
        if st.button("Cargar datos a registros"):
            # Procesar datos importados de forma vectorizada
            df_importado["Fecha"] = pd.to_datetime(df_importado["Fecha"], errors="coerce").dt.date
            df_importado.dropna(subset=["Fecha"], inplace=True) # Eliminar filas con fechas no válidas

            # Asegurarse que las columnas numéricas son de tipo numérico
            for col in ["Cantidad", "Peso Salida (kg)", "Peso Entrada (kg)", "Precio Unitario ($)"]:
                df_importado[col] = pd.to_numeric(df_importado[col], errors='coerce').fillna(0)
            
            df_importado["Kilos Restantes"] = df_importado["Peso Salida (kg)"] - df_importado["Peso Entrada (kg)"]
            df_importado["Libras Restantes"] = df_importado["Kilos Restantes"] * LBS_PER_KG
            # Manejar división por cero
            df_importado["Promedio"] = df_importado.apply(lambda row: row["Libras Restantes"] / row["Cantidad"] if row["Cantidad"] != 0 else 0, axis=1)
            df_importado["Total ($)"] = df_importado["Libras Restantes"] * df_importado["Precio Unitario ($)"]

            # Asignar el número 'N' a cada fila importada
            current_data_df = st.session_state.data.copy()
            # Asegurarse que 'N' sea string para ambas DataFrames
            current_data_df["N"] = current_data_df["N"].astype(str)
            df_importado["N"] = "" # Inicializar N en importado

            # Filtrar registros de operaciones (excluir BALANCE_INICIAL)
            current_ops_data = current_data_df[current_data_df["Proveedor"] != "BALANCE_INICIAL"].copy()

            # Mapeo de fechas existentes a sus N asignados
            existing_date_n_map = current_ops_data.set_index('Fecha')['N'].to_dict()

            # Obtener el máximo N actual de las operaciones
            max_n_existing = current_ops_data["N"].apply(lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0).max()
            new_n_counter = max_n_existing + 1
            
            for idx, row in df_importado.iterrows():
                date = row["Fecha"]
                if date in existing_date_n_map:
                    df_importado.loc[idx, "N"] = existing_date_n_map[date]
                else:
                    df_importado.loc[idx, "N"] = f"{new_n_counter:02}"
                    existing_date_n_map[date] = df_importado.loc[idx, "N"] # Guardar para futuras filas importadas en el mismo archivo
                    new_n_counter += 1

            # Limpiar columnas de saldo antes de la concatenación para que `recalculate_accumulated_balances` las recalcule
            df_importado["Monto Deposito"] = 0.0
            df_importado["Saldo diario"] = 0.0
            df_importado["Saldo Acumulado"] = 0.0
            df_importado["Producto"] = PRODUCT_NAME # Asegurarse que el producto sea 'Pollo'

            # Concatenar el DataFrame importado al estado de sesión
            # Asegurarse de que el orden de las columnas sea el mismo que COLUMNS_DATA
            df_to_add = df_importado[COLUMNS_DATA]

            # Separar la fila de balance inicial para no eliminarla al hacer drop_duplicates
            if "BALANCE_INICIAL" in current_data_df["Proveedor"].values:
                df_temp = current_data_df[current_data_df["Proveedor"] != "BALANCE_INICIAL"].copy()
                df_balance = current_data_df[current_data_df["Proveedor"] == "BALANCE_INICIAL"].copy()
            else:
                df_temp = current_data_df.copy()
                df_balance = pd.DataFrame(columns=COLUMNS_DATA) # DataFrame vacío

            df_temp = pd.concat([df_temp, df_to_add], ignore_index=True)
            
            # Eliminar duplicados si una misma entrada se importa varias veces (basado en Fecha, Proveedor, Pesos, Tipo Doc)
            df_temp.drop_duplicates(subset=["Fecha", "Proveedor", "Peso Salida (kg)", "Peso Entrada (kg)", "Tipo Documento"], keep='last', inplace=True)
            df_temp.reset_index(drop=True, inplace=True)

            st.session_state.data = pd.concat([df_balance, df_temp], ignore_index=True)


            if save_dataframe(st.session_state.data, DATA_FILE):
                st.session_state.data_imported = True # Flag para indicar que se importaron datos
                st.success("Datos importados correctamente. Recalculando saldos...")
            else:
                st.error("Error al guardar los datos importados.")

    except Exception as e:
        st.error(f"Error al cargar o procesar el archivo Excel: {e}")
        st.exception(e) # Mostrar el stack trace completo para depuración

def delete_record(record_info_to_delete):
    """Elimina un registro de la tabla principal."""
    df_to_delete_from = st.session_state.data.copy()

    # Asegurarse de que 'Mostrar' exista para la comparación
    if "Mostrar" not in df_to_delete_from.columns:
        df_to_delete_from["Mostrar"] = df_to_delete_from.apply(
            lambda row: f"{row['Fecha']} - {row['Proveedor']} - ${row['Total ($)']:.2f}"
            if pd.notna(row["Total ($)"]) else f"{row['Fecha']} - {row['Proveedor']} - Sin total",
            axis=1
        )

    index_eliminar = df_to_delete_from[df_to_delete_from["Mostrar"] == record_info_to_delete].index
    if not index_eliminar.empty:
        df_to_delete_from.drop(index=index_eliminar, inplace=True)
        df_to_delete_from.reset_index(drop=True, inplace=True)
        st.session_state.data = df_to_delete_from
        if save_dataframe(st.session_state.data, DATA_FILE):
            st.session_state.record_deleted = True # Flag para indicar que se eliminó un registro
            st.success("Registro eliminado correctamente. Recalculando saldos...")
        else:
            st.error("Error al eliminar el registro.")
    else:
        st.warning("No se encontró el registro a eliminar.")

def add_debit_note(fecha_nota, descuento, descuento_real):
    """Agrega una nueva nota de débito."""
    df = st.session_state.data.copy()
    
    # Validar que existan libras restantes para la fecha
    # Asegurarse que 'Libras Restantes' sea numérico para sumar
    df["Libras Restantes"] = pd.to_numeric(df["Libras Restantes"], errors='coerce').fillna(0)
    
    # Excluir la fila de BALANCE_INICIAL del cálculo de libras
    libras_calculadas = df[
        (df["Fecha"] == fecha_nota) & 
        (df["Proveedor"] != "BALANCE_INICIAL")
    ]["Libras Restantes"].sum()
    
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
        st.session_state.debit_note_added = True # Flag para indicar que se añadió una nota de débito
        st.success("Nota de debito agregada correctamente. Recalculando saldos...")
    else:
        st.error("Error al guardar la nota de débito.")

def delete_debit_note_record(nota_info_to_delete):
    """Elimina una nota de débito seleccionada."""
    df_to_delete_from = st.session_state.notas.copy()
    
    # Asegurarse de que 'Mostrar' exista para la comparación
    if "Mostrar" not in df_to_delete_from.columns:
        df_to_delete_from["Mostrar"] = df_to_delete_from.apply(
            lambda row: f"{row['Fecha']} - Libras: {row['Libras calculadas']:.2f} - Descuento real: ${row['Descuento real']:.2f}", axis=1
        )

    index_eliminar = df_to_delete_from[df_to_delete_from["Mostrar"] == nota_info_to_delete].index
    if not index_eliminar.empty:
        df_to_delete_from.drop(index=index_eliminar, inplace=True)
        df_to_delete_from.reset_index(drop=True, inplace=True)
        st.session_state.notas = df_to_delete_from
        if save_dataframe(st.session_state.notas, DEBIT_NOTES_FILE):
            st.session_state.debit_note_deleted = True # Flag para indicar que se eliminó una nota de débito
            st.success("Nota de debito eliminada correctamente. Recalculando saldos...")
        else:
            st.error("Error al eliminar la nota de débito.")
    else:
        st.warning("No se encontró la nota de débito a eliminar.")

# --- 5. FUNCIONES DE INTERFAZ DE USUARIO (UI) ---
def render_deposit_registration_form():
    """Renderiza el formulario de registro de depósitos en el sidebar."""
    st.sidebar.header("Registro de Depósitos")
    with st.sidebar.form("registro_form", clear_on_submit=True):
        fecha_d = st.date_input("Fecha del registro", value=datetime.today(), key="fecha_d_input")
        empresa = st.selectbox("Empresa (Proveedor)", PROVEEDORES, key="empresa_select")
        agencia = st.selectbox("Agencia", AGENCIAS, key="agencia_select")
        monto = st.number_input("Monto", min_value=0.0, format="%.2f", key="monto_input")
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
        df_display_deposits = st.session_state.df.copy()
        df_display_deposits["Mostrar"] = df_display_deposits.apply(
            lambda row: f"{row['Fecha']} - {row['Empresa']} - ${row['Monto']:.2f}", axis=1
        )
        deposito_a_eliminar = st.sidebar.selectbox(
            "Selecciona un depósito a eliminar", df_display_deposits["Mostrar"], key="delete_deposit_select"
        )
        if st.sidebar.button("Eliminar depósito seleccionado", key="delete_deposit_button"):
            # Añadir confirmación antes de eliminar
            if st.sidebar.checkbox("Confirmar eliminación del depósito", key="confirm_delete_deposit_checkbox"):
                delete_deposit_record(deposito_a_eliminar)
            else:
                st.sidebar.warning("Por favor, marca la casilla para confirmar la eliminación.")
    else:
        st.sidebar.info("No hay depósitos para eliminar.")

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
            fecha = st.date_input("Fecha", value=datetime.today(), key="fecha_input")
            proveedor = st.selectbox("Proveedor", PROVEEDORES, key="proveedor_select")
        with col2:
            cantidad = st.number_input("Cantidad", min_value=0, step=1, key="cantidad_input")
            peso_salida = st.number_input("Peso Salida (kg)", min_value=0.0, step=0.1, format="%.2f", key="peso_salida_input")
        with col3:
            peso_entrada = st.number_input("Peso Entrada (kg)", min_value=0.0, step=0.1, format="%.2f", key="peso_entrada_input")
            documento = st.selectbox("Tipo Documento", TIPOS_DOCUMENTO, key="documento_select")
        with col4:
            gavetas = st.number_input("Cantidad de gavetas", min_value=0, step=1, key="gavetas_input")
            precio_unitario = st.number_input("Precio Unitario ($)", min_value=0.0, step=0.01, format="%.2f", key="precio_unitario_input")

        enviar = st.form_submit_button("Agregar Registro")

        if enviar:
            add_supplier_record(fecha, proveedor, cantidad, peso_salida, peso_entrada, documento, gavetas, precio_unitario)

def render_debit_note_form():
    """Renderiza el formulario para agregar notas de débito."""
    st.subheader("Registro de Nota de Débito")
    with st.form("nota_debito", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            fecha_nota = st.date_input("Fecha de Nota", key="fecha_nota_input")
        with col2:
            descuento = st.number_input("Descuento (%) (ej. 0.05 para 5%)", min_value=0.0, max_value=1.0, step=0.01, format="%.2f", key="descuento_input")
        with col3:
            descuento_real = st.number_input("Descuento Real ($)", min_value=0.0, step=0.01, format="%.2f", key="descuento_real_input")
        agregar_nota = st.form_submit_button("Agregar Nota de Débito")

        if agregar_nota:
            if descuento_real <= 0 and descuento <= 0:
                st.error("Debes ingresar un valor para Descuento (%) o Descuento Real ($) mayor que cero.")
            else:
                add_debit_note(fecha_nota, descuento, descuento_real)

def display_formatted_dataframe(df_source, title, columns_to_format=None, exclude_mostrar=True):
    """Muestra un DataFrame con formato de moneda."""
    df_display = df_source.copy()
    if columns_to_format:
        for col in columns_to_format:
            if col in df_display.columns:
                # Convertir a numérico antes de formatear para evitar errores
                df_display[col] = pd.to_numeric(df_display[col], errors='coerce')
                df_display[col] = df_display[col].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "" if x is not None else "")
    
    if exclude_mostrar and "Mostrar" in df_display.columns:
        df_display = df_display.drop(columns=["Mostrar"])
        
    st.subheader(title)
    st.dataframe(df_display, use_container_width=True)


def render_tables_and_download():
    """Renderiza las tablas de registros, notas de débito y la opción de descarga."""
    
    # Tabla de Registros
    # Excluir la fila de BALANCE_INICIAL para la visualización normal y eliminación
    df_display_data = st.session_state.data[st.session_state.data["Proveedor"] != "BALANCE_INICIAL"].copy()

    if not df_display_data.empty:
        # Añadir columna 'Mostrar' para la selección de eliminación
        df_display_data["Mostrar"] = df_display_data.apply(
            lambda row: f"{row['Fecha']} - {row['Proveedor']} - ${row['Total ($)']:.2f}"
            if pd.notna(row["Total ($)"]) else f"{row['Fecha']} - {row['Proveedor']} - Sin total",
            axis=1
        )
        display_formatted_dataframe(
            df_display_data,
            "Tabla de Registros",
            columns_to_format=["Saldo diario", "Saldo Acumulado", "Total ($)", "Monto Deposito", "Precio Unitario ($)"],
            exclude_mostrar=False # No excluir para la selección de eliminación
        )
        st.subheader("Eliminar un Registro")
        # Asegurarse de que el selectbox tenga opciones si el DF no está vacío
        if not df_display_data["Mostrar"].empty:
            registro_a_eliminar = st.selectbox("Selecciona un registro para eliminar", df_display_data["Mostrar"], key="delete_record_select")
            if st.button("Eliminar Registro Seleccionado", key="delete_record_button"):
                if st.checkbox("Confirmar eliminación del registro", key="confirm_delete_record"):
                    delete_record(registro_a_eliminar)
                else:
                    st.warning("Por favor, marca la casilla para confirmar la eliminación.")
        else:
            st.info("No hay registros disponibles para eliminar.")
    else:
        st.subheader("Tabla de Registros")
        st.info("No hay registros disponibles. Por favor, agrega algunos o importa desde Excel.")

    # Tabla de Notas de Débito
    if not st.session_state.notas.empty:
        df_display_notes = st.session_state.notas.copy()
        df_display_notes["Mostrar"] = df_display_notes.apply(
            lambda row: f"{row['Fecha']} - Libras: {row['Libras calculadas']:.2f} - Descuento real: ${row['Descuento real']:.2f}", axis=1
        )
        display_formatted_dataframe(
            df_display_notes,
            "Tabla de Notas de Débito",
            columns_to_format=["Descuento posible", "Descuento real"],
            exclude_mostrar=False # No excluir para la selección de eliminación
        )
        st.subheader("Eliminar una Nota de Débito")
        # Asegurarse de que el selectbox tenga opciones si el DF no está vacío
        if not df_display_notes["Mostrar"].empty:
            nota_a_eliminar = st.selectbox("Selecciona una nota para eliminar", df_display_notes["Mostrar"], key="delete_debit_note_select")
            if st.button("Eliminar Nota de Débito seleccionada", key="delete_debit_note_button"):
                if st.checkbox("Confirmar eliminación de la nota de débito", key="confirm_delete_debit_note"):
                    delete_debit_note_record(nota_a_eliminar)
                else:
                    st.warning("Por favor, marca la casilla para confirmar la eliminación.")
        else:
            st.info("No hay notas de débito disponibles para eliminar.")

    else:
        st.subheader("Tabla de Notas de Débito")
        st.info("No hay notas de débito registradas.")


    # Descarga de Excel
    @st.cache_data # Caching para evitar recálculos innecesarios
    def convertir_excel(df):
        output = BytesIO()
        df_copy = df.copy()
        # Asegurarse de quitar la columna 'Mostrar' antes de exportar
        if "Mostrar" in df_copy.columns:
            df_copy = df_copy.drop(columns=["Mostrar"])
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_copy.to_excel(writer, index=False)
        output.seek(0)
        return output

    if not st.session_state.data.empty:
        st.download_button(
            label="Descargar Registros en Excel",
            data=convertir_excel(st.session_state.data),
            file_name="registro_proveedores_depositos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    with st.expander("Ver depósitos registrados"):
        if not st.session_state.df.empty:
            display_formatted_dataframe(
                st.session_state.df,
                "Depósitos Registrados",
                columns_to_format=["Monto"]
            )
        else:
            st.info("No hay depósitos registrados.")


def render_weekly_report():
    """Renderiza el reporte semanal."""
    st.header("Reporte Semanal")
    df = st.session_state.data.copy()
    
    # Excluir la fila de BALANCE_INICIAL del reporte semanal
    df = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()

    if not df.empty:
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        df.dropna(subset=["Fecha"], inplace=True)
        
        if not df.empty: # Volver a verificar si hay datos después de dropear NaNs
            # Asegurarse de que el año también sea considerado para la semana
            df["YearWeek"] = df["Fecha"].dt.strftime('%Y-%U')
            # Filtrar solo si hay semanas válidas
            if not df["YearWeek"].empty:
                semana_actual = df["YearWeek"].max()
                df_semana = df[df["YearWeek"] == semana_actual].drop(columns=["YearWeek"]) # Eliminar columna temporal
                
                if not df_semana.empty:
                    display_formatted_dataframe(
                        df_semana, 
                        f"Registros de la Semana {semana_actual}",
                        columns_to_format=["Total ($)", "Monto Deposito", "Saldo diario", "Saldo Acumulado"]
                    )
                else:
                    st.info(f"No hay datos para la semana actual ({semana_actual}).")
            else:
                st.info("No hay datos con fecha válida para generar el reporte semanal.")
        else:
            st.info("No hay datos para generar el reporte semanal después de filtrar fechas no válidas.")
    else:
        st.info("No hay datos para generar el reporte semanal.")

def render_monthly_report():
    """Renderiza el reporte mensual."""
    st.header("Reporte Mensual")
    df = st.session_state.data.copy()

    # Excluir la fila de BALANCE_INICIAL del reporte mensual
    df = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()

    if not df.empty:
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        df.dropna(subset=["Fecha"], inplace=True) # Eliminar fechas no válidas

        if not df.empty: # Volver a verificar si hay datos después de dropear NaNs
            mes_actual = datetime.today().month
            año_actual = datetime.today().year
            df_mes = df[(df["Fecha"].dt.month == mes_actual) & (df["Fecha"].dt.year == año_actual)]
            
            if not df_mes.empty:
                display_formatted_dataframe(
                    df_mes, 
                    f"Registros del Mes {mes_actual}/{año_actual}",
                    columns_to_format=["Total ($)", "Monto Deposito", "Saldo diario", "Saldo Acumulado"]
                )
            else:
                st.info(f"No hay datos para el mes actual ({mes_actual}/{año_actual}).")
        else:
            st.info("No hay datos para generar el reporte mensual después de filtrar fechas no válidas.")
    else:
        st.info("No hay datos para generar el reporte mensual.")

def render_charts():
    """Renderiza los gráficos de datos."""
    st.header("Gráficos de Proveedores y Saldo")
    df = st.session_state.data.copy()
    
    # Excluir la fila de BALANCE_INICIAL de los gráficos
    df = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()

    if df.empty:
        st.info("No hay datos suficientes para generar gráficos. Por favor, agregue registros.")
        return

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df.dropna(subset=["Fecha"], inplace=True)

    st.subheader("Total por Proveedor")
    # Asegurarse que 'Total ($)' sea numérico
    df["Total ($)"] = pd.to_numeric(df["Total ($)"], errors='coerce').fillna(0)
    total_por_proveedor = df.groupby("Proveedor")["Total ($)"].sum().sort_values(ascending=False)
    if not total_por_proveedor.empty and total_por_proveedor.sum() > 0: # Solo graficar si hay valores > 0
        fig, ax = plt.subplots(figsize=(10, 6))
        total_por_proveedor.plot(kind="bar", ax=ax, color='skyblue')
        ax.set_ylabel("Total ($)")
        ax.set_title("Total ($) por Proveedor")
        ax.ticklabel_format(style='plain', axis='y') # Evita notación científica en el eje Y
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        st.pyplot(fig)
    else:
        st.info("No hay datos de 'Total ($)' por proveedor para graficar o todos son cero.")


    st.subheader("Evolución del Saldo Acumulado")
    df_ordenado = df.sort_values("Fecha")
    # Asegurarse de que el Saldo Acumulado sea numérico para graficar
    df_ordenado["Saldo Acumulado"] = pd.to_numeric(df_ordenado["Saldo Acumulado"], errors='coerce').fillna(INITIAL_ACCUMULATED_BALANCE)
    
    # Filtra la fila inicial si no tiene una fecha real y solo es un marcador
    df_ordenado = df_ordenado[df_ordenado['Fecha'].notna()]

    if not df_ordenado.empty:
        # Para graficar, tomemos el último saldo acumulado de cada día.
        daily_last_saldo = df_ordenado.groupby("Fecha")["Saldo Acumulado"].last().reset_index()

        fig2, ax2 = plt.subplots(figsize=(12, 6))
        ax2.plot(daily_last_saldo["Fecha"], daily_last_saldo["Saldo Acumulado"], marker="o", linestyle='-', color='green')
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

# --- Manejo de reruns después de las operaciones ---
# Flags para controlar cuándo se necesita un rerun
if "deposit_added" not in st.session_state:
    st.session_state.deposit_added = False
if "deposit_deleted" not in st.session_state:
    st.session_state.deposit_deleted = False
if "record_added" not in st.session_state:
    st.session_state.record_added = False
if "record_deleted" not in st.session_state:
    st.session_state.record_deleted = False
if "data_imported" not in st.session_state:
    st.session_state.data_imported = False
if "debit_note_added" not in st.session_state:
    st.session_state.debit_note_added = False
if "debit_note_deleted" not in st.session_state:
    st.session_state.debit_note_deleted = False


if st.session_state.deposit_added or st.session_state.deposit_deleted or \
   st.session_state.record_added or st.session_state.record_deleted or \
   st.session_state.data_imported or st.session_state.debit_note_added or \
   st.session_state.debit_note_deleted:
    
    st.session_state.deposit_added = False
    st.session_state.deposit_deleted = False
    st.session_state.record_added = False
    st.session_state.record_deleted = False
    st.session_state.data_imported = False
    st.session_state.debit_note_added = False
    st.session_state.debit_note_deleted = False
    
    recalculate_accumulated_balances()
    st.experimental_rerun()
