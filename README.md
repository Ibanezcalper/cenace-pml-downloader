PML MDA — descarga CENACE

Script reutilizable para descargar **Precios Marginales Locales (PML)** del **MDA**
desde el Área Pública del SIM y consolidarlos en un CSV.

Fuente: https://www.cenace.gob.mx/Paginas/SIM/Reportes/PreEnerServConMDA.aspx

## Instalación y Requisitos

- Python 3.9 o superior
- Instalar las dependencias necesarias mediante `requirements.txt`:

```bash
pip install -r requirements.txt
```

## Uso interactivo (pide fechas)

Funciona desde **cualquier directorio**:

```bash
python3 /ruta/a/descargar_pml_mda.py
```

Te pedirá:

1. Fecha inicial (mes o día: `2025-01`, `2025-01-15`, `15/01/2025`)
2. Fecha final
3. Modo (`auto` / `mensual` / `diario`)
4. Sistema (`SIN` / `BCA` / `BCS`)
5. Directorio de salida (por defecto: el directorio actual)

## Uso con argumentos

### Meses completos (comportamiento original)

```bash
python3 descargar_pml_mda.py --inicio 2025-01 --fin 2025-12 --sistema SIN
python3 descargar_pml_mda.py --inicio 01/2024 --fin 03/2024 --outdir ~/datos/pml
```

### Rango de días específicos

```bash
# Auto: detecta modo diario para rangos cortos (≤ 31 días)
python3 descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-01-20

# Un solo día
python3 descargar_pml_mda.py --inicio 2025-06-10 --fin 2025-06-10

# Forzar descarga diaria explícita
python3 descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-01-25 --modo diario
```

### Rango parcial que cruza meses

Para periodos largos con días concretos, el modo `auto` descarga los meses
completos que cubren el rango y **filtra** el CSV al consolidar:

```bash
python3 descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-03-10
```

También puedes forzar ese comportamiento:

```bash
python3 descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-03-10 --modo mensual
```

### Otras opciones

```bash
python3 descargar_pml_mda.py --inicio 2025-06 --fin 2025-06 --solo-descarga
python3 descargar_pml_mda.py --inicio 2025-01 --fin 2025-12 --solo-consolidar
python3 descargar_pml_mda.py --inicio 2025-01 --fin 2025-12 --forzar   # re-descarga
```

## Modos de descarga

| Modo               | Cuándo usarlo                          | Qué descarga                                                                                                           |
| ------------------ | --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `auto` (default) | La mayoría de casos                    | Meses completos si solo indicas mes; diario si el rango es ≤ 31 días; mensual + filtro si el rango es largo y parcial |
| `mensual`        | Meses enteros o rangos parciales largos | Un ZIP por mes; filtra fechas al consolidar si el rango no cubre meses completos                                        |
| `diario`         | Rangos cortos de días                  | ZIP por tramo (máx. 7 días por petición a CENACE)                                                                    |

## Salida

```text
<outdir>/
  raw/<SISTEMA>/pml_mda_sin_2025_01.zip              # mensual
  raw/<SISTEMA>/pml_mda_sin_20250115_20250120.zip    # diario (rango)
  raw/<SISTEMA>/pml_mda_sin_2025_01_15.zip           # diario (un día)
  output/pml_mda_sin_2025.csv                        # CSV consolidado
  output/pml_mda_sin_20250115_20250120.csv           # CSV de rango parcial
```

Columnas del CSV: `fecha,hora,clv_nodo,pml,pml_ene,pml_per,pml_cng`

## Manejo de errores

- Reintentos automáticos por descarga (default 3) ante fallos de red o del formulario
- Si un periodo falla, continúa con el siguiente y avisa al final
- Al volver a ejecutar, **omite** ZIPs ya descargados (usa `--forzar` para regenerarlos)
- Valida que el ZIP contenga CSV del periodo solicitado

## SW-PML vs este script

| Método                             | Cuándo usarlo                                      |
| ----------------------------------- | --------------------------------------------------- |
| **Este script (página web)** | Todo el sistema / periodos largos / rangos de días |
| **SW-PML** (manual técnico)  | Pocos nodos; máx. 7 días y 20 nodos por petición |

---

# PML MDA — CENACE Downloader (English Version)

Reusable script to download **Local Marginal Prices (PML)** of the **MDA** (Day-Ahead Market) from CENACE's SIM Public Area and consolidate them into a single CSV.

Source: https://www.cenace.gob.mx/Paginas/SIM/Reportes/PreEnerServConMDA.aspx

## Installation and Requirements

- Python 3.9 or higher
- Install the required dependencies using the `requirements.txt` file:

```bash
pip install -r requirements.txt
```

## Interactive Usage (prompts for dates)

Works from **any directory**:

```bash
python3 /path/to/descargar_pml_mda.py
```

It will prompt you for:

1. Start date (month or day: `2025-01`, `2025-01-15`, `15/01/2025`)
2. End date
3. Mode (`auto` / `mensual` / `diario`)
4. Interconnected System (`SIN` / `BCA` / `BCS`)
5. Output directory (default: current working directory)

## Usage with Arguments

### Full Months (original behavior)

```bash
python3 descargar_pml_mda.py --inicio 2025-01 --fin 2025-12 --sistema SIN
python3 descargar_pml_mda.py --inicio 01/2024 --fin 03/2024 --outdir ~/data/pml
```

### Specific Date Ranges

```bash
# Auto: detects daily mode for short ranges (≤ 31 days)
python3 descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-01-20

# Single day
python3 descargar_pml_mda.py --inicio 2025-06-10 --fin 2025-06-10

# Force daily download explicitly
python3 descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-01-25 --modo diario
```

### Partial Ranges Crossing Months

For long periods with specific days, `auto` mode downloads the full months covering the range and **filters** the CSV when consolidating:

```bash
python3 descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-03-10
```

You can also force this behavior:

```bash
python3 descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-03-10 --modo mensual
```

### Other Options

```bash
python3 descargar_pml_mda.py --inicio 2025-06 --fin 2025-06 --solo-descarga
python3 descargar_pml_mda.py --inicio 2025-01 --fin 2025-12 --solo-consolidar
python3 descargar_pml_mda.py --inicio 2025-01 --fin 2025-12 --forzar   # re-download
```

## Download Modes

| Mode               | When to use                          | What it downloads                                                                                                   |
| ------------------ | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `auto` (default) | Most cases                           | Full months if only month is specified; daily if range is ≤ 31 days; monthly + filter if range is long and partial |
| `mensual`        | Entire months or long partial ranges | One ZIP per month; filters dates during consolidation if range doesn't cover full months                            |
| `diario`         | Short date ranges                    | ZIP per segment (max 7 days per request to CENACE)                                                                  |

## Output

```text
<outdir>/
  raw/<SYSTEM>/pml_mda_sin_2025_01.zip              # monthly
  raw/<SYSTEM>/pml_mda_sin_20250115_20250120.zip    # daily (range)
  raw/<SYSTEM>/pml_mda_sin_2025_01_15.zip           # daily (one day)
  output/pml_mda_sin_2025.csv                        # consolidated CSV
  output/pml_mda_sin_20250115_20250120.csv           # partial range CSV
```

CSV Columns: `fecha,hora,clv_nodo,pml,pml_ene,pml_per,pml_cng`

## Error Handling

- Automatic retries per download (default 3) on network or form validation failures.
- If a period fails, it continues with the next and displays a summary at the end.
- When re-run, it **skips** already downloaded ZIPs (use `--forzar` to re-download).
- Validates that the downloaded ZIP contains CSVs for the requested period.

## SW-PML vs this script

| Method                              | When to use                                        |
| ----------------------------------- | -------------------------------------------------- |
| **This script (web page)**    | Whole system / long periods / specific date ranges |
| **SW-PML** (technical manual) | Few nodes; max 7 days and 20 nodes per request     |
