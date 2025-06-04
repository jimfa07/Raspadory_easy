import streamlit as st
import pandas as pd
from datetime import datetime
from io import BytesIO
import os
import matplotlib.pyplot as plt
import base64 # For image embedding in HTML for printing

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
            # Ensure all default columns are present, add if missing with NaN
            for col in default_columns:
                if col not in df.columns:
                    df[col] = None # Or appropriate default value like 0 for numbers
            return df[default_columns] # Return with consistent column order
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
        
        # Ensure the initial balance row exists and is correctly structured
        if not any(st.session_state.data["Proveedor"] == "BALANCE_INICIAL"):
            fila_inicial_saldo = {col: None for col in COLUMNS_DATA}
            fila_inicial_saldo["Fecha"] = datetime(1900, 1, 1).date() # A very old date to ensure it's always first
            fila_inicial_saldo["Proveedor"] = "BALANCE_INICIAL"
            fila_inicial_saldo["Saldo diario"] = 0.00
            fila_inicial_saldo["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE
            fila_inicial_saldo["N"] = "00" # Unique identifier for initial balance
            fila_inicial_saldo["Monto Deposito"] = 0.0
            fila_inicial_saldo["Total ($)"] = 0.0
            
            # If the DataFrame is empty, just set it to the initial balance row
            if st.session_state.data.empty:
                st.session_state.data = pd.DataFrame([fila_inicial_saldo], columns=COLUMNS_DATA)
            else:
                # If there are existing data, concatenate it, placing the initial balance at the top
                st.session_state.data = pd.concat([pd.DataFrame([fila_inicial_saldo], columns=COLUMNS_DATA), st.session_state.data], ignore_index=True)
        else:
            # If "BALANCE_INICIAL" exists, ensure its accumulated balance is correct
            initial_balance_idx = st.session_state.data[st.session_state.data["Proveedor"] == "BALANCE_INICIAL"].index
            if not initial_balance_idx.empty:
                st.session_state.data.loc[initial_balance_idx[0], "Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE
                st.session_state.data.loc[initial_balance_idx[0], "Saldo diario"] = 0.0 # Ensure it doesn't affect daily sums
                st.session_state.data.loc[initial_balance_idx[0], "Monto Deposito"] = 0.0
                st.session_state.data.loc[initial_balance_idx[0], "Total ($)"] = 0.0
                st.session_state.data.loc[initial_balance_idx[0], "N"] = "00"

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

    # Ensure date columns are datetime.date for comparison
    df_data["Fecha"] = pd.to_datetime(df_data["Fecha"], errors="coerce").dt.date
    df_deposits["Fecha"] = pd.to_datetime(df_deposits["Fecha"], errors="coerce").dt.date
    df_notes["Fecha"] = pd.to_datetime(df_notes["Fecha"], errors="coerce").dt.date

    # --- Pre-processing and calculations for df_data ---
    # Ensure numeric columns are numeric
    for col in ["Cantidad", "Peso Salida (kg)", "Peso Entrada (kg)", "Precio Unitario ($)"]:
        df_data[col] = pd.to_numeric(df_data[col], errors='coerce').fillna(0)

    # Exclude the 'BALANCE_INICIAL' row from calculations of Kilos/Libras/Total
    df_data_operaciones = df_data[df_data["Proveedor"] != "BALANCE_INICIAL"].copy()
    df_initial_balance = df_data[df_data["Proveedor"] == "BALANCE_INICIAL"].copy()

    if not df_data_operaciones.empty:
        df_data_operaciones["Kilos Restantes"] = df_data_operaciones["Peso Salida (kg)"] - df_data_operaciones["Peso Entrada (kg)"]
        df_data_operaciones["Libras Restantes"] = df_data_operaciones["Kilos Restantes"] * LBS_PER_KG
        df_data_operaciones["Promedio"] = df_data_operaciones.apply(lambda row: row["Libras Restantes"] / row["Cantidad"] if row["Cantidad"] != 0 else 0, axis=1)
        df_data_operaciones["Total ($)"] = df_data_operaciones["Libras Restantes"] * df_data_operaciones["Precio Unitario ($)"]
    else:
        # If no operations, ensure these columns exist with default values
        for col in ["Kilos Restantes", "Libras Restantes", "Promedio", "Total ($)"]:
            df_data_operaciones[col] = 0.0

    # Calculate Monto Deposito for each data record
    # Group deposits by Fecha and Empresa (Proveedor) to sum the amounts
    deposits_summary = df_deposits.groupby(["Fecha", "Empresa"])["Monto"].sum().reset_index()
    deposits_summary.rename(columns={"Monto": "Monto Deposito Calculado"}, inplace=True)

    # Merge the calculated deposits with the operational data
    # Use a temporary column to avoid merging on 'Proveedor' for 'Empresa'
    df_data_operaciones = pd.merge(
        df_data_operaciones,
        deposits_summary,
        left_on=["Fecha", "Proveedor"],
        right_on=["Fecha", "Empresa"],
        how="left"
    )
    df_data_operaciones["Monto Deposito Calculado"] = df_data_operaciones["Monto Deposito Calculado"].fillna(0)
    df_data_operaciones["Monto Deposito"] = df_data_operaciones["Monto Deposito Calculado"]
    df_data_operaciones.drop(columns=["Monto Deposito Calculado", "Empresa"], inplace=True, errors='ignore') # Drop temporary column and 'Empresa' if it exists

    # Calculate Saldo diario for operations
    df_data_operaciones["Saldo diario"] = df_data_operaciones["Monto Deposito"] - df_data_operaciones["Total ($)"]

    # Consolidate daily balances by date for operations
    # Group by date to get a single daily sum for "Saldo diario"
    daily_summary_operaciones = df_data_operaciones.groupby("Fecha")["Saldo diario"].sum().reset_index()
    daily_summary_operaciones.rename(columns={"Saldo diario": "SaldoDiarioConsolidado"}, inplace=True)

    # Incorporate debit notes into the consolidated daily balance
    if not df_notes.empty:
        notes_by_date = df_notes.groupby("Fecha")["Descuento real"].sum().reset_index()
        notes_by_date.rename(columns={"Descuento real": "NotaDebitoAjuste"}, inplace=True)

        full_daily_balances = pd.merge(daily_summary_operaciones, notes_by_date, on="Fecha", how="left")
        full_daily_balances["NotaDebitoAjuste"] = full_daily_balances["NotaDebitoAjuste"].fillna(0)
        full_daily_balances["SaldoDiarioAjustado"] = full_daily_balances["SaldoDiarioConsolidado"] + full_daily_balances["NotaDebitoAjuste"]
    else:
        full_daily_balances = daily_summary_operaciones.copy()
        full_daily_balances["SaldoDiarioAjustado"] = full_daily_balances["SaldoDiarioConsolidado"]

    # Sort by date for cumulative sum
    full_daily_balances = full_daily_balances.sort_values("Fecha")

    # Calculate accumulated balance starting from INITIAL_ACCUMULATED_BALANCE
    full_daily_balances["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE + full_daily_balances["SaldoDiarioAjustado"].cumsum()

    # Merge the calculated daily and accumulated balances back into the main operations DataFrame
    # Need to merge "Saldo diario" and "Saldo Acumulado" values back to the original df_data_operaciones
    # We use a left merge to keep all original data rows and fill the balance info
    
    # First, let's create a temporary DataFrame with the calculated daily and accumulated balances per date
    # This ensures that each record within a day gets the correct daily/accumulated balance for that day.
    # The 'Saldo diario' at the record level is still the individual record's balance (Monto Deposito - Total ($))
    # The 'Saldo diario' used for accumulation is the daily sum.
    # So we need to re-assign the overall daily and accumulated sums back to the main dataframe
    
    # Create a mapping for Saldo Acumulado and Saldo Diario (from the daily sum) per date
    saldo_mapping = full_daily_balances[['Fecha', 'SaldoDiarioAjustado', 'Saldo Acumulado']].copy()
    saldo_mapping.rename(columns={'SaldoDiarioAjustado': 'Calculated_Saldo_Diario_Sum',
                                  'Saldo Acumulado': 'Calculated_Saldo_Acumulado'}, inplace=True)

    # Merge these calculated daily sums and accumulated balances back into df_data_operaciones
    # We only merge for the 'Fecha' to apply the correct daily summary and accumulated balance for each date.
    df_data_operaciones = pd.merge(
        df_data_operaciones.drop(columns=["Saldo diario", "Saldo Acumulado"], errors='ignore'), # Drop old balance columns
        saldo_mapping,
        on="Fecha",
        how="left"
    )
    
    # The individual 'Saldo diario' (Monto Deposito - Total ($)) should remain for each transaction.
    # The 'Saldo diario' from `saldo_mapping` (Calculated_Saldo_Diario_Sum) is for the daily summary.
    # We will use Calculated_Saldo_Acumulado for 'Saldo Acumulado'.
    # We need to re-calculate the individual 'Monto Deposito' and 'Saldo diario' for each row.
    
    # Re-calculate 'Monto Deposito' based on `deposits_summary` for individual rows
    df_data_operaciones["Monto Deposito"] = 0.0 # Reset for recalculation
    for index, row in df_data_operaciones.iterrows():
        matching_deposit = deposits_summary[(deposits_summary['Fecha'] == row['Fecha']) & 
                                            (deposits_summary['Empresa'] == row['Proveedor'])]
        if not matching_deposit.empty:
            df_data_operaciones.loc[index, "Monto Deposito"] = matching_deposit["Monto Deposito Calculado"].iloc[0]

    # Re-calculate individual 'Saldo diario'
    df_data_operaciones["Saldo diario"] = df_data_operaciones["Monto Deposito"] - df_data_operaciones["Total ($)"]

    # Assign the calculated accumulated balance
    df_data_operaciones["Saldo Acumulado"] = df_data_operaciones["Calculated_Saldo_Acumulado"].fillna(method='ffill').fillna(INITIAL_ACCUMULATED_BALANCE)
    
    # Drop temporary columns
    df_data_operaciones.drop(columns=["Calculated_Saldo_Diario_Sum", "Calculated_Saldo_Acumulado"], inplace=True, errors='ignore')


    # Reintegrate the initial balance row
    if not df_initial_balance.empty:
        df_initial_balance["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE
        df_initial_balance["Saldo diario"] = 0.0
        df_initial_balance["Monto Deposito"] = 0.0
        df_initial_balance["Total ($)"] = 0.0
        df_initial_balance["N"] = "00" # Ensure 'N' is "00" for the initial balance row
        df_data = pd.concat([df_initial_balance, df_data_operaciones], ignore_index=True)
    else:
        df_data = df_data_operaciones

    # Ensure all original columns are present and in order
    df_data = df_data[COLUMNS_DATA]
    
    # Sort the final DataFrame
    df_data = df_data.sort_values(["Fecha", "N"]).reset_index(drop=True)

    # Clean rows with NaN dates if generated by a merge with non-existent dates
    df_data.dropna(subset=["Fecha"], inplace=True)

    # Finally, update st.session_state.data with the recalculated balances
    st.session_state.data = df_data
    save_dataframe(st.session_state.data, DATA_FILE)


def add_deposit_record(fecha_d, empresa, agencia, monto):
    """Agrega un nuevo registro de depósito."""
    df_actual = st.session_state.df.copy()
    
    # Ensure 'N' column is string for proper formatting and sorting
    df_actual["N"] = df_actual["N"].astype(str) if "N" in df_actual.columns else ""

    # Determine 'N' number for the deposit
    # Filter deposits for the same date
    coincidencia_fecha = df_actual[df_actual["Fecha"] == fecha_d]

    if not coincidencia_fecha.empty:
        # If there's already a deposit for this date, use the highest existing 'N' for that date
        max_n_for_date = coincidencia_fecha["N"].apply(lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0).max()
        numero = f"{max_n_for_date + 1:02}" # Increment N for the same date
    else:
        # If no deposits for this date, find the overall max N and increment
        # This logic ensures 'N' is unique and sequential overall, not just by date
        max_n_global = df_actual["N"].apply(lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0).max()
        numero = f"{max_n_global + 1:02}" # Format as two digits
    
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
        st.session_state.deposit_added = True # Flag to indicate deposit was added
        st.success("Deposit added successfully. Recalculating balances...")
    else:
        st.error("Error saving deposit.")

def delete_deposit_record(deposito_info_to_delete):
    """Deletes a selected deposit record."""
    df_to_delete_from = st.session_state.df.copy()
    
    # Ensure 'Mostrar' exists for comparison
    if "Mostrar" not in df_to_delete_from.columns:
        df_to_delete_from["Mostrar"] = df_to_delete_from.apply(
            lambda row: f"{row['Fecha']} - {row['Empresa']} - ${row['Monto']:.2f} - N: {row['N']}", axis=1
        )

    index_eliminar = df_to_delete_from[df_to_delete_from["Mostrar"] == deposito_info_to_delete].index
    if not index_eliminar.empty:
        df_to_delete_from.drop(index=index_eliminar, inplace=True)
        df_to_delete_from.reset_index(drop=True, inplace=True)
        st.session_state.df = df_to_delete_from
        if save_dataframe(st.session_state.df, DEPOSITS_FILE):
            st.session_state.deposit_deleted = True # Flag to indicate deposit was deleted
            st.sidebar.success("Deposit deleted successfully. Recalculating balances...")
        else:
            st.sidebar.error("Error deleting deposit.")
    else:
        st.sidebar.warning("Deposit to delete not found.")

def add_supplier_record(fecha, proveedor, cantidad, peso_salida, peso_entrada, tipo_documento, gavetas, precio_unitario):
    """Agrega un nuevo registro de proveedor."""
    df = st.session_state.data.copy()

    # Basic input validation
    if cantidad < 0 or peso_salida < 0 or peso_entrada < 0 or precio_unitario < 0 or gavetas < 0:
        st.error("Numeric values cannot be negative.")
        return False
    if cantidad == 0 and peso_salida == 0 and peso_entrada == 0:
        st.error("Please enter a valid Quantity and/or Weights (cannot all be zero).")
        return False
    if peso_entrada > peso_salida:
        st.error("Entry Weight (kg) cannot be greater than Exit Weight (kg).")
        return False

    kilos_restantes = peso_salida - peso_entrada
    libras_restantes = kilos_restantes * LBS_PER_KG
    promedio = libras_restantes / cantidad if cantidad != 0 else 0
    total = libras_restantes * precio_unitario

    # Determine 'N' number for the data record
    # Ensure 'N' column is string for proper formatting and sorting
    df["N"] = df["N"].astype(str) if "N" in df.columns else ""

    # Filter out "BALANCE_INICIAL" row for 'N' calculation
    df_operaciones_existente = df[df["Proveedor"] != "BALANCE_INICIAL"]

    df_filtered_by_date = df_operaciones_existente[df_operaciones_existente["Fecha"] == fecha]
    if not df_filtered_by_date.empty:
        # If there's already a record for this date, use the highest existing 'N' for that date
        max_n_for_date = df_filtered_by_date["N"].apply(lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0).max()
        enumeracion = f"{max_n_for_date + 1:02}" # Increment N for the same date
    else:
        # If no records for this date, find the overall max N from operational records and increment
        max_n_global = df_operaciones_existente["N"].apply(lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0).max()
        enumeracion = f"{max_n_global + 1:02}" # Format as two digits

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
        "Monto Deposito": 0.0, # Will be filled by recalculation
        "Saldo diario": 0.0,  # Will be filled by recalculation
        "Saldo Acumulado": 0.0 # Will be filled by recalculation
    }

    # Separate the initial balance row
    df_balance = df[df["Proveedor"] == "BALANCE_INICIAL"].copy()
    df_temp = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()

    df_temp = pd.concat([df_temp, pd.DataFrame([nueva_fila], columns=COLUMNS_DATA)], ignore_index=True)
    df_temp.drop_duplicates(subset=["Fecha", "Proveedor", "Peso Salida (kg)", "Peso Entrada (kg)", "Tipo Documento"], keep='last', inplace=True)
    df_temp.reset_index(drop=True, inplace=True)

    st.session_state.data = pd.concat([df_balance, df_temp], ignore_index=True)
    
    if save_dataframe(st.session_state.data, DATA_FILE):
        st.session_state.record_added = True # Flag to indicate record was added
        st.success("Record added successfully. Recalculating balances...")
        return True
    else:
        st.error("Error saving record.")
        return False

def import_excel_data(archivo_excel):
    """Imports data from an Excel file and adds it to records."""
    try:
        df_importado = pd.read_excel(archivo_excel)
        st.write("Preview of imported data:", df_importado.head())

        columnas_requeridas = [
            "Fecha", "Proveedor", "Producto", "Cantidad",
            "Peso Salida (kg)", "Peso Entrada (kg)", "Tipo Documento",
            "Cantidad de gavetas", "Precio Unitario ($)"
        ]
        if not all(col in df_importado.columns for col in columnas_requeridas):
            st.error("The file does not contain all required columns. Please ensure you have: " + ", ".join(columnas_requeridas))
            return

        # Only show the load button if the file is valid
        if st.button("Load data to records"):
            # Process imported data in a vectorized way
            df_importado["Fecha"] = pd.to_datetime(df_importado["Fecha"], errors="coerce").dt.date
            df_importado.dropna(subset=["Fecha"], inplace=True) # Remove rows with invalid dates

            # Ensure numeric columns are numeric
            for col in ["Cantidad", "Peso Salida (kg)", "Peso Entrada (kg)", "Precio Unitario ($)"]:
                df_importado[col] = pd.to_numeric(df_importado[col], errors='coerce').fillna(0)
            
            df_importado["Kilos Restantes"] = df_importado["Peso Salida (kg)"] - df_importado["Peso Entrada (kg)"]
            df_importado["Libras Restantes"] = df_importado["Kilos Restantes"] * LBS_PER_KG
            # Handle division by zero
            df_importado["Promedio"] = df_importado.apply(lambda row: row["Libras Restantes"] / row["Cantidad"] if row["Cantidad"] != 0 else 0, axis=1)
            df_importado["Total ($)"] = df_importado["Libras Restantes"] * df_importado["Precio Unitario ($)"]

            # Assign 'N' number to each imported row
            current_data_df = st.session_state.data.copy()
            current_data_df["N"] = current_data_df["N"].astype(str) if "N" in current_data_df.columns else ""
            df_importado["N"] = "" # Initialize N in imported

            current_ops_data = current_data_df[current_data_df["Proveedor"] != "BALANCE_INICIAL"].copy()
            max_n_existing = current_ops_data["N"].apply(lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0).max()
            new_n_counter = max_n_existing + 1
            
            for idx, row in df_importado.iterrows():
                df_importado.loc[idx, "N"] = f"{new_n_counter:02}"
                new_n_counter += 1

            # Clean balance columns before concatenation so `recalculate_accumulated_balances` recalculates them
            df_importado["Monto Deposito"] = 0.0
            df_importado["Saldo diario"] = 0.0
            df_importado["Saldo Acumulado"] = 0.0
            df_importado["Producto"] = PRODUCT_NAME # Ensure product is 'Pollo'

            # Concatenate imported DataFrame to session state
            df_to_add = df_importado[COLUMNS_DATA]

            # Separate the initial balance row
            df_balance = current_data_df[current_data_df["Proveedor"] == "BALANCE_INICIAL"].copy()
            df_temp = current_data_df[current_data_df["Proveedor"] != "BALANCE_INICIAL"].copy()

            df_temp = pd.concat([df_temp, df_to_add], ignore_index=True)
            
            # Remove duplicates if the same entry is imported multiple times (based on Fecha, Proveedor, Weights, Doc Type)
            df_temp.drop_duplicates(subset=["Fecha", "Proveedor", "Peso Salida (kg)", "Peso Entrada (kg)", "Tipo Documento"], keep='last', inplace=True)
            df_temp.reset_index(drop=True, inplace=True)

            st.session_state.data = pd.concat([df_balance, df_temp], ignore_index=True)

            if save_dataframe(st.session_state.data, DATA_FILE):
                st.session_state.data_imported = True # Flag to indicate data was imported
                st.success("Data imported successfully. Recalculating balances...")
            else:
                st.error("Error saving imported data.")

    except Exception as e:
        st.error(f"Error loading or processing Excel file: {e}")
        st.exception(e) # Show full stack trace for debugging

def delete_record(record_info_to_delete):
    """Deletes a record from the main table."""
    df_to_delete_from = st.session_state.data.copy()

    # Ensure 'Mostrar' exists for comparison
    if "Mostrar" not in df_to_delete_from.columns:
        df_to_delete_from["Mostrar"] = df_to_delete_from.apply(
            lambda row: f"{row['Fecha']} - {row['Proveedor']} - ${row['Total ($)']:.2f} - N: {row['N']}"
            if pd.notna(row["Total ($)"]) else f"{row['Fecha']} - {row['Proveedor']} - Sin total - N: {row['N']}",
            axis=1
        )

    index_eliminar = df_to_delete_from[df_to_delete_from["Mostrar"] == record_info_to_delete].index
    if not index_eliminar.empty:
        # Prevent deleting the BALANCE_INICIAL row via this method
        if df_to_delete_from.loc[index_eliminar[0], "Proveedor"] == "BALANCE_INICIAL":
            st.warning("Cannot delete the initial balance row.")
            return

        df_to_delete_from.drop(index=index_eliminar, inplace=True)
        df_to_delete_from.reset_index(drop=True, inplace=True)
        st.session_state.data = df_to_delete_from
        if save_dataframe(st.session_state.data, DATA_FILE):
            st.session_state.record_deleted = True # Flag to indicate record was deleted
            st.success("Record deleted successfully. Recalculating balances...")
        else:
            st.error("Error deleting record.")
    else:
        st.warning("Record to delete not found.")

def add_debit_note(fecha_nota, descuento, descuento_real):
    """Agrega una nueva nota de débito."""
    df = st.session_state.data.copy()
    
    # Validate that there are remaining pounds for the date
    # Ensure 'Libras Restantes' is numeric for summing
    df["Libras Restantes"] = pd.to_numeric(df["Libras Restantes"], errors='coerce').fillna(0)
    
    # Exclude the BALANCE_INICIAL row from pound calculation
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
    st.session_state.notas = pd.concat([st.session_state.notas, pd.DataFrame([nueva_nota], columns=COLUMNS_DEBIT_NOTES)], ignore_index=True)
    if save_dataframe(st.session_state.notas, DEBIT_NOTES_FILE):
        st.session_state.debit_note_added = True # Flag to indicate debit note was added
        st.success("Debit note added successfully. Recalculating balances...")
    else:
        st.error("Error saving debit note.")

def delete_debit_note_record(nota_info_to_delete):
    """Deletes a selected debit note."""
    df_to_delete_from = st.session_state.notas.copy()
    
    # Ensure 'Mostrar' exists for comparison
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
            st.session_state.debit_note_deleted = True # Flag to indicate debit note was deleted
            st.success("Debit note deleted successfully. Recalculating balances...")
        else:
            st.error("Error deleting debit note.")
    else:
        st.warning("Debit note to delete not found.")

# --- 5. FUNCIONES DE INTERFAZ DE USUARIO (UI) ---

def format_dataframe_for_display(df_source, columns_to_format=None):
    """Applies currency formatting to specified columns for display in st.dataframe or st.data_editor."""
    df_display = df_source.copy()
    if columns_to_format:
        for col in columns_to_format:
            if col in df_display.columns:
                # Convert to numeric before formatting to avoid errors
                df_display[col] = pd.to_numeric(df_display[col], errors='coerce')
                # Replace NaN with empty string or 0.00 for display
                df_display[col] = df_display[col].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
    return df_display

def parse_formatted_dataframe_input(df_edited, original_df, columns_to_parse=None):
    """Parses currency formatted strings back to numeric for specified columns after editing."""
    df_parsed = df_edited.copy()
    if columns_to_parse:
        for col in columns_to_parse:
            if col in df_parsed.columns:
                # Convert string back to float, handling potential errors and missing values
                df_parsed[col] = df_parsed[col].astype(str).str.replace('$', '').str.replace(',', '').astype(float)
    
    # Ensure that any columns that were not meant for editing (e.g., calculated ones) retain their original values
    # Or recalculate them after the core data is updated.
    # For simplicity, we assume st.data_editor returns the entire DataFrame.
    
    return df_parsed

def render_deposit_registration_form():
    """Renders the deposit registration form in the sidebar."""
    st.sidebar.header("Deposit Registration")
    with st.sidebar.form("registro_form", clear_on_submit=True):
        fecha_d = st.date_input("Registration Date", value=datetime.today(), key="fecha_d_input")
        empresa = st.selectbox("Company (Supplier)", PROVEVEEDORES, key="empresa_select")
        agencia = st.selectbox("Agency", AGENCIAS, key="agencia_select")
        monto = st.number_input("Amount", min_value=0.0, format="%.2f", key="monto_input")
        submit_d = st.form_submit_button("Add Deposit")

        if submit_d:
            if monto <= 0:
                st.error("Deposit amount must be greater than zero.")
            else:
                add_deposit_record(fecha_d, empresa, agencia, monto)

def render_delete_deposit_section():
    """Renders the section to delete deposits in the sidebar."""
    st.sidebar.subheader("Delete a Deposit")
    if not st.session_state.df.empty:
        df_display_deposits = st.session_state.df.copy()
        df_display_deposits["Mostrar"] = df_display_deposits.apply(
            lambda row: f"{row['Fecha']} - {row['Empresa']} - ${row['Monto']:.2f} - N: {row['N']}", axis=1
        )
        deposito_a_eliminar = st.sidebar.selectbox(
            "Select a deposit to delete", df_display_deposits["Mostrar"], key="delete_deposit_select"
        )
        if st.sidebar.button("Delete selected deposit", key="delete_deposit_button"):
            # Add confirmation before deleting
            if st.sidebar.checkbox("Confirm deposit deletion", key="confirm_delete_deposit_checkbox"):
                delete_deposit_record(deposito_a_eliminar)
            else:
                st.sidebar.warning("Please check the box to confirm deletion.")
    else:
        st.sidebar.info("No deposits to delete.")

def render_import_excel_section():
    """Renders the section to import data from Excel."""
    st.subheader("Import data from Excel")
    archivo_excel = st.file_uploader("Select an Excel file", type=["xlsx"])
    if archivo_excel is not None:
        import_excel_data(archivo_excel)

def render_supplier_registration_form():
    """Renders the supplier registration form."""
    st.subheader("Supplier Registration")
    with st.form("formulario", clear_on_submit=True):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            fecha = st.date_input("Date", value=datetime.today(), key="fecha_input")
            proveedor = st.selectbox("Supplier", PROVEEDORES, key="proveedor_select")
        with col2:
            cantidad = st.number_input("Quantity", min_value=0, step=1, key="cantidad_input")
            peso_salida = st.number_input("Exit Weight (kg)", min_value=0.0, step=0.1, format="%.2f", key="peso_salida_input")
        with col3:
            peso_entrada = st.number_input("Entry Weight (kg)", min_value=0.0, step=0.1, format="%.2f", key="peso_entrada_input")
            documento = st.selectbox("Document Type", TIPOS_DOCUMENTO, key="documento_select")
        with col4:
            gavetas = st.number_input("Number of crates", min_value=0, step=1, key="gavetas_input")
            precio_unitario = st.number_input("Unit Price ($)", min_value=0.0, step=0.01, format="%.2f", key="precio_unitario_input")

        enviar = st.form_submit_button("Add Record")

        if enviar:
            add_supplier_record(fecha, proveedor, cantidad, peso_salida, peso_entrada, documento, gavetas, precio_unitario)

def render_debit_note_form():
    """Renders the form to add debit notes."""
    st.subheader("Debit Note Registration")
    with st.form("nota_debito", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            fecha_nota = st.date_input("Note Date", key="fecha_nota_input")
        with col2:
            descuento = st.number_input("Discount (%) (e.g., 0.05 for 5%)", min_value=0.0, max_value=1.0, step=0.01, format="%.2f", key="descuento_input")
        with col3:
            descuento_real = st.number_input("Actual Discount ($)", min_value=0.0, step=0.01, format="%.2f", key="descuento_real_input")
        agregar_nota = st.form_submit_button("Add Debit Note")

        if agregar_nota:
            if descuento_real <= 0 and descuento <= 0:
                st.error("You must enter a value for Discount (%) or Actual Discount ($) greater than zero.")
            else:
                add_debit_note(fecha_nota, descuento, descuento_real)

def render_tables_and_download():
    """Renders the registration tables, debit notes, and download option."""
    
    # Table of Records (Supplier Data)
    st.subheader("Supplier Records Table")
    # Exclude the BALANCE_INICIAL row for normal display and editing
    df_display_data = st.session_state.data[st.session_state.data["Proveedor"] != "BALANCE_INICIAL"].copy()
    
    if not df_display_data.empty:
        # Use st.data_editor for inline editing
        edited_data_df = st.data_editor(
            df_display_data,
            column_config={
                "Fecha": st.column_config.DateColumn("Fecha", format="YYYY/MM/DD"),
                "Monto Deposito": st.column_config.NumberColumn("Monto Deposito", format="$%.2f"),
                "Saldo diario": st.column_config.NumberColumn("Saldo diario", format="$%.2f"),
                "Saldo Acumulado": st.column_config.NumberColumn("Saldo Acumulado", format="$%.2f"),
                "Total ($)": st.column_config.NumberColumn("Total ($)", format="$%.2f"),
                "Precio Unitario ($)": st.column_config.NumberColumn("Precio Unitario ($)", format="$%.2f"),
                "Kilos Restantes": st.column_config.NumberColumn("Kilos Restantes", format="%.2f"),
                "Libras Restantes": st.column_config.NumberColumn("Libras Restantes", format="%.2f"),
                "Promedio": st.column_config.NumberColumn("Promedio", format="%.2f"),
                "Cantidad": st.column_config.NumberColumn("Cantidad", format="%d"),
                "Cantidad de gavetas": st.column_config.NumberColumn("Cantidad de gavetas", format="%d"),
            },
            key="supplier_data_editor",
            hide_index=True,
            num_rows="dynamic" # Allows adding rows directly
        )

        # Check if the edited DataFrame is different from the original (excluding new rows with all NaNs)
        if not edited_data_df.equals(df_display_data):
            # Convert back formatted columns to numeric
            # Ensure 'N' remains string and other relevant columns are correctly typed
            edited_data_df["N"] = edited_data_df["N"].astype(str)
            edited_data_df["Fecha"] = pd.to_datetime(edited_data_df["Fecha"]).dt.date

            # Recalculate derived columns based on edited inputs
            edited_data_df["Kilos Restantes"] = edited_data_df["Peso Salida (kg)"] - edited_data_df["Peso Entrada (kg)"]
            edited_data_df["Libras Restantes"] = edited_data_df["Kilos Restantes"] * LBS_PER_KG
            edited_data_df["Promedio"] = edited_data_df.apply(lambda row: row["Libras Restantes"] / row["Cantidad"] if row["Cantidad"] != 0 else 0, axis=1)
            edited_data_df["Total ($)"] = edited_data_df["Libras Restantes"] * edited_data_df["Precio Unitario ($)"]

            # Merge the edited operational data back with the initial balance row
            df_balance = st.session_state.data[st.session_state.data["Proveedor"] == "BALANCE_INICIAL"].copy()
            st.session_state.data = pd.concat([df_balance, edited_data_df], ignore_index=True)
            
            # Sort and save
            st.session_state.data = st.session_state.data.sort_values(["Fecha", "N"]).reset_index(drop=True)
            st.session_state.data.dropna(subset=["Fecha"], inplace=True) # Clean rows with NaN dates

            if save_dataframe(st.session_state.data, DATA_FILE):
                st.success("Supplier records updated successfully. Recalculating balances...")
                st.session_state.record_edited = True # Set a flag for rerun
            else:
                st.error("Error updating supplier records.")
        
        st.subheader("Delete a Supplier Record")
        # Ensure the selectbox has options if the DF is not empty
        df_for_deletion = df_display_data.copy()
        df_for_deletion["Mostrar"] = df_for_deletion.apply(
            lambda row: f"{row['Fecha']} - {row['Proveedor']} - ${row['Total ($)']:.2f} - N: {row['N']}"
            if pd.notna(row["Total ($)"]) else f"{row['Fecha']} - {row['Proveedor']} - Sin total - N: {row['N']}",
            axis=1
        )
        if not df_for_deletion["Mostrar"].empty:
            registro_a_eliminar = st.selectbox("Select a record to delete", df_for_deletion["Mostrar"], key="delete_record_select")
            if st.button("Delete Selected Record", key="delete_record_button"):
                if st.checkbox("Confirm record deletion", key="confirm_delete_record"):
                    delete_record(registro_a_eliminar)
                else:
                    st.warning("Please check the box to confirm deletion.")
        else:
            st.info("No records available to delete.")
    else:
        st.info("No supplier records available. Please add some or import from Excel.")

    st.markdown("---")

    # Table of Debit Notes
    st.subheader("Debit Notes Table")
    if not st.session_state.notas.empty:
        # Use st.data_editor for inline editing
        edited_notes_df = st.data_editor(
            st.session_state.notas,
            column_config={
                "Fecha": st.column_config.DateColumn("Fecha", format="YYYY/MM/DD"),
                "Libras calculadas": st.column_config.NumberColumn("Libras calculadas", format="%.2f"),
                "Descuento": st.column_config.NumberColumn("Descuento", format="%.2f"),
                "Descuento posible": st.column_config.NumberColumn("Descuento posible", format="$%.2f"),
                "Descuento real": st.column_config.NumberColumn("Descuento real", format="$%.2f"),
            },
            key="debit_notes_editor",
            hide_index=True,
            num_rows="dynamic" # Allows adding rows directly
        )

        if not edited_notes_df.equals(st.session_state.notas):
            # Convert back formatted columns to numeric
            edited_notes_df["Fecha"] = pd.to_datetime(edited_notes_df["Fecha"]).dt.date
            edited_notes_df["Libras calculadas"] = pd.to_numeric(edited_notes_df["Libras calculadas"], errors='coerce').fillna(0)
            edited_notes_df["Descuento"] = pd.to_numeric(edited_notes_df["Descuento"], errors='coerce').fillna(0)
            edited_notes_df["Descuento real"] = pd.to_numeric(edited_notes_df["Descuento real"], errors='coerce').fillna(0)
            
            # Recalculate 'Descuento posible' if 'Libras calculadas' or 'Descuento' changed
            edited_notes_df["Descuento posible"] = edited_notes_df["Libras calculadas"] * edited_notes_df["Descuento"]

            st.session_state.notas = edited_notes_df
            if save_dataframe(st.session_state.notas, DEBIT_NOTES_FILE):
                st.success("Debit notes updated successfully. Recalculating balances...")
                st.session_state.debit_note_edited = True # Set a flag for rerun
            else:
                st.error("Error updating debit notes.")

        st.subheader("Delete a Debit Note")
        df_for_deletion_notes = st.session_state.notas.copy()
        df_for_deletion_notes["Mostrar"] = df_for_deletion_notes.apply(
            lambda row: f"{row['Fecha']} - Libras: {row['Libras calculadas']:.2f} - Descuento real: ${row['Descuento real']:.2f}", axis=1
        )
        if not df_for_deletion_notes["Mostrar"].empty:
            nota_a_eliminar = st.selectbox("Select a note to delete", df_for_deletion_notes["Mostrar"], key="delete_debit_note_select")
            if st.button("Delete selected Debit Note", key="delete_debit_note_button"):
                if st.checkbox("Confirm debit note deletion", key="confirm_delete_debit_note"):
                    delete_debit_note_record(nota_a_eliminar)
                else:
                    st.warning("Please check the box to confirm deletion.")
        else:
            st.info("No debit notes available to delete.")

    else:
        st.info("No debit notes registered.")

    st.markdown("---")

    # Deposits Table (for viewing and editing)
    st.subheader("Registered Deposits Table")
    if not st.session_state.df.empty:
        # Use st.data_editor for inline editing
        edited_deposits_df = st.data_editor(
            st.session_state.df,
            column_config={
                "Fecha": st.column_config.DateColumn("Fecha", format="YYYY/MM/DD"),
                "Monto": st.column_config.NumberColumn("Monto", format="$%.2f"),
                "N": st.column_config.TextColumn("N") # Keep N as text for 0-padding
            },
            key="deposits_editor",
            hide_index=True,
            num_rows="dynamic" # Allows adding rows directly
        )

        if not edited_deposits_df.equals(st.session_state.df):
            # Convert back formatted columns to numeric and dates
            edited_deposits_df["Fecha"] = pd.to_datetime(edited_deposits_df["Fecha"]).dt.date
            edited_deposits_df["Monto"] = pd.to_numeric(edited_deposits_df["Monto"], errors='coerce').fillna(0)
            
            # Recalculate 'Documento' based on 'Agencia' if 'Agencia' changed
            edited_deposits_df["Documento"] = edited_deposits_df["Agencia"].apply(lambda x: "Deposito" if "Cajero" in str(x) else "Transferencia")
            
            st.session_state.df = edited_deposits_df
            if save_dataframe(st.session_state.df, DEPOSITS_FILE):
                st.success("Deposits updated successfully. Recalculating balances...")
                st.session_state.deposit_edited = True # Set a flag for rerun
            else:
                st.error("Error updating deposits.")
    else:
        st.info("No deposits registered.")

    st.markdown("---")

    # Download Excel
    @st.cache_data # Caching to avoid unnecessary recalculations
    def convertir_excel(df, sheet_name="Sheet1"):
        output = BytesIO()
        df_copy = df.copy()
        # Ensure to remove 'Mostrar' column before export if it exists
        if "Mostrar" in df_copy.columns:
            df_copy = df_copy.drop(columns=["Mostrar"])
        # Format date columns to string 'YYYY-MM-DD' for better Excel compatibility
        for col in df_copy.select_dtypes(include=['datetime64[ns]', 'object']).columns:
            if df_copy[col].apply(lambda x: isinstance(x, (datetime.date, datetime))).any():
                df_copy[col] = pd.to_datetime(df_copy[col], errors='coerce').dt.strftime('%Y-%m-%d')
        
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_copy.to_excel(writer, index=False, sheet_name=sheet_name)
        output.seek(0)
        return output

    st.download_button(
        label="Download All Records in Excel",
        data=convertir_excel(st.session_state.data[st.session_state.data["Proveedor"] != "BALANCE_INICIAL"], sheet_name="Supplier_Records"),
        file_name="supplier_records.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    st.download_button(
        label="Download Deposits in Excel",
        data=convertir_excel(st.session_state.df, sheet_name="Deposits"),
        file_name="deposits.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    st.download_button(
        label="Download Debit Notes in Excel",
        data=convertir_excel(st.session_state.notas, sheet_name="Debit_Notes"),
        file_name="debit_notes.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def render_weekly_report():
    """Renders the weekly report."""
    st.header("Weekly Report")
    df = st.session_state.data.copy()
    
    # Exclude the BALANCE_INICIAL row from the weekly report
    df = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()

    if not df.empty:
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        df.dropna(subset=["Fecha"], inplace=True)
        
        if not df.empty: # Re-check if there's data after dropping NaNs
            # Ensure the year is also considered for the week
            df["YearWeek"] = df["Fecha"].dt.strftime('%Y-%U')
            
            # Get unique sorted weeks
            unique_weeks = sorted(df["YearWeek"].unique(), reverse=True)
            
            selected_week = st.selectbox("Select Week", unique_weeks, index=0)

            df_semana = df[df["YearWeek"] == selected_week].drop(columns=["YearWeek"]) # Remove temporary column
            
            if not df_semana.empty:
                st.subheader(f"Records for Week {selected_week}")
                st.dataframe(df_semana.style.format({
                    "Total ($)": "$%.2f",
                    "Monto Deposito": "$%.2f",
                    "Saldo diario": "$%.2f",
                    "Saldo Acumulado": "$%.2f",
                    "Precio Unitario ($)": "$%.2f"
                }), use_container_width=True)
                
                # Print button for the report
                html_report = df_semana.style.format({
                    "Total ($)": "$%.2f",
                    "Monto Deposito": "$%.2f",
                    "Saldo diario": "$%.2f",
                    "Saldo Acumulado": "$%.2f",
                    "Precio Unitario ($)": "$%.2f"
                }).to_html()
                
                download_html_report(html_report, f"weekly_report_week_{selected_week}.html", "Print/Download Weekly Report")
            else:
                st.info(f"No data for the selected week ({selected_week}).")
        else:
            st.info("No data with valid dates to generate the weekly report after filtering invalid dates.")
    else:
        st.info("No data to generate the weekly report.")

def render_monthly_report():
    """Renders the monthly report."""
    st.header("Monthly Report")
    df = st.session_state.data.copy()

    # Exclude the BALANCE_INICIAL row from the monthly report
    df = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()

    if not df.empty:
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        df.dropna(subset=["Fecha"], inplace=True) # Remove invalid dates

        if not df.empty: # Re-check if there's data after dropping NaNs
            df["YearMonth"] = df["Fecha"].dt.strftime('%Y-%m')
            
            unique_months = sorted(df["YearMonth"].unique(), reverse=True)
            selected_month = st.selectbox("Select Month", unique_months, index=0)

            df_mes = df[df["YearMonth"] == selected_month].drop(columns=["YearMonth"])
            
            if not df_mes.empty:
                st.subheader(f"Records for Month {selected_month}")
                st.dataframe(df_mes.style.format({
                    "Total ($)": "$%.2f",
                    "Monto Deposito": "$%.2f",
                    "Saldo diario": "$%.2f",
                    "Saldo Acumulado": "$%.2f",
                    "Precio Unitario ($)": "$%.2f"
                }), use_container_width=True)

                # Print button for the report
                html_report = df_mes.style.format({
                    "Total ($)": "$%.2f",
                    "Monto Deposito": "$%.2f",
                    "Saldo diario": "$%.2f",
                    "Saldo Acumulado": "$%.2f",
                    "Precio Unitario ($)": "$%.2f"
                }).to_html()

                download_html_report(html_report, f"monthly_report_month_{selected_month}.html", "Print/Download Monthly Report")
            else:
                st.info(f"No data for the selected month ({selected_month}).")
        else:
            st.info("No data to generate the monthly report after filtering invalid dates.")
    else:
        st.info("No data to generate the monthly report.")

def download_html_report(html_content, filename, button_text):
    """Generates a button to download an HTML report."""
    b64_html = base64.b64encode(html_content.encode()).decode()
    href = f'<a href="data:text/html;base64,{b64_html}" download="{filename}" target="_blank">{button_text}</a>'
    st.markdown(href, unsafe_allow_html=True)

def get_image_download_link(fig, filename, text):
    """Generates a download link for a Matplotlib figure as PNG."""
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    b64_image = base64.b64encode(buf.read()).decode()
    href = f'<a href="data:image/png;base64,{b64_image}" download="{filename}" target="_blank">{text}</a>'
    return href

def render_charts():
    """Renders the data charts."""
    st.header("Supplier and Balance Charts")
    df = st.session_state.data.copy()
    
    # Exclude the BALANCE_INICIAL row from charts
    df = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()

    if df.empty:
        st.info("Not enough data to generate charts. Please add records.")
        return

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df.dropna(subset=["Fecha"], inplace=True)

    st.subheader("Total by Supplier")
    # Ensure 'Total ($)' is numeric
    df["Total ($)"] = pd.to_numeric(df["Total ($)"], errors='coerce').fillna(0)
    total_por_proveedor = df.groupby("Proveedor")["Total ($)"].sum().sort_values(ascending=False)
    if not total_por_proveedor.empty and total_por_proveedor.sum() > 0: # Only plot if there are values > 0
        fig, ax = plt.subplots(figsize=(10, 6))
        total_por_proveedor.plot(kind="bar", ax=ax, color='skyblue')
        ax.set_ylabel("Total ($)")
        ax.set_title("Total ($) by Supplier")
        ax.ticklabel_format(style='plain', axis='y') # Avoid scientific notation on Y-axis
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        st.pyplot(fig)
        st.markdown(get_image_download_link(fig, "total_by_supplier_chart.png", "Download Chart as PNG"), unsafe_allow_html=True)
    else:
        st.info("No 'Total ($)' data by supplier to plot or all are zero.")


    st.subheader("Accumulated Balance Evolution")
    df_ordenado = df.sort_values("Fecha")
    # Ensure Accumulated Balance is numeric for plotting
    df_ordenado["Saldo Acumulado"] = pd.to_numeric(df_ordenado["Saldo Acumulado"], errors='coerce').fillna(INITIAL_ACCUMULATED_BALANCE)
    
    # Filter out the initial row if it doesn't have a real date and is just a placeholder
    df_ordenado = df_ordenado[df_ordenado['Fecha'].notna()]

    if not df_ordenado.empty:
        # To plot, let's take the last accumulated balance for each day.
        daily_last_saldo = df_ordenado.groupby("Fecha")["Saldo Acumulado"].last().reset_index()

        fig2, ax2 = plt.subplots(figsize=(12, 6))
        ax2.plot(daily_last_saldo["Fecha"], daily_last_saldo["Saldo Acumulado"], marker="o", linestyle='-', color='green')
        ax2.set_ylabel("Accumulated Balance ($)")
        ax2.set_title("Accumulated Balance Evolution")
        ax2.grid(True, linestyle='--', alpha=0.7)
        ax2.ticklabel_format(style='plain', axis='y')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        st.pyplot(fig2)
        st.markdown(get_image_download_link(fig2, "accumulated_balance_chart.png", "Download Chart as PNG"), unsafe_allow_html=True)
    else:
        st.info("No 'Accumulated Balance' data to plot.")

# --- MAIN PAGE CONFIGURATION ---
st.set_page_config(page_title="Supplier and Deposit Registration", layout="wide")
st.title("Supplier Management System - Chicken Product")

# --- INITIALIZE SESSION STATE ---
initialize_session_state()

# --- MAIN NAVIGATION ---
opcion = st.sidebar.selectbox("Select a view", ["Registration", "Weekly Report", "Monthly Report", "Charts"])

# --- RENDER SECTIONS BASED ON SELECTED OPTION ---
if opcion == "Registration":
    render_deposit_registration_form()
    render_delete_deposit_section()
    st.sidebar.markdown("---") # Visual separator

    render_import_excel_section()
    render_supplier_registration_form()
    render_debit_note_form()
    st.markdown("---") # Visual separator
    render_tables_and_download()

elif opcion == "Weekly Report":
    render_weekly_report()

elif opcion == "Monthly Report":
    render_monthly_report()

elif opcion == "Charts":
    render_charts()

# --- Handle reruns after operations ---
# Flags to control when a rerun is needed
if "deposit_added" not in st.session_state:
    st.session_state.deposit_added = False
if "deposit_deleted" not in st.session_state:
    st.session_state.deposit_deleted = False
if "deposit_edited" not in st.session_state: # New flag for edited deposits
    st.session_state.deposit_edited = False
if "record_added" not in st.session_state:
    st.session_state.record_added = False
if "record_deleted" not in st.session_state:
    st.session_state.record_deleted = False
if "record_edited" not in st.session_state: # New flag for edited supplier records
    st.session_state.record_edited = False
if "data_imported" not in st.session_state:
    st.session_state.data_imported = False
if "debit_note_added" not in st.session_state:
    st.session_state.debit_note_added = False
if "debit_note_deleted" not in st.session_state:
    st.session_state.debit_note_deleted = False
if "debit_note_edited" not in st.session_state: # New flag for edited debit notes
    st.session_state.debit_note_edited = False


if st.session_state.deposit_added or st.session_state.deposit_deleted or st.session_state.deposit_edited or \
   st.session_state.record_added or st.session_state.record_deleted or st.session_state.record_edited or \
   st.session_state.data_imported or st.session_state.debit_note_added or st.session_state.debit_note_deleted or st.session_state.debit_note_edited:
    
    st.session_state.deposit_added = False
    st.session_state.deposit_deleted = False
    st.session_state.deposit_edited = False
    st.session_state.record_added = False
    st.session_state.record_deleted = False
    st.session_state.record_edited = False
    st.session_state.data_imported = False
    st.session_state.debit_note_added = False
    st.session_state.debit_note_deleted = False
    st.session_state.debit_note_edited = False
    
    recalculate_accumulated_balances()
    st.rerun()

