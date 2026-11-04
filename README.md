# PML MDA — Descarga CENACE

Script reutilizable para descargar **Precios Marginales Locales (PML)** del **MDA** (Mercado del Día en Adelanto) desde el Área Pública del SIM de CENACE para cualquiera de los tres sistemas interconectados (**SIN**, **BCA**, **BCS**) y consolidarlos en un archivo CSV.

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
python descargar_pml_mda.py
```

Te pedirá:

1. Fecha inicial (mes o día: `2025-01`, `2025-01-15`, `15/01/2025`)
2. Fecha final
3. Modo (`auto` / `mensual` / `diario`)
4. Sistema (`SIN` / `BCA` / `BCS`)
5. Directorio de salida (por defecto: el directorio actual)

## Uso con argumentos

### Meses completos y descargas masivas por sistema (`SIN`, `BCA`, `BCS`)

```bash
# Año completo (SIN)
python descargar_pml_mda.py --inicio 2025-01 --fin 2025-12 --sistema SIN

# Descarga masiva mensual para BCA y BCS (sin prompts interactivos)
python descargar_pml_mda.py --inicio 2025-09-01 --fin 2026-09-30 --modo mensual --sistema BCA --no-interactivo
python descargar_pml_mda.py --inicio 2025-09-01 --fin 2026-09-30 --modo mensual --sistema BCS --no-interactivo

# Especificando directorio de salida
python descargar_pml_mda.py --inicio 01/2024 --fin 03/2024 --sistema SIN --outdir ~/datos/pml
```

### Rango de días específicos

```bash
# Auto: detecta modo diario para rangos cortos (≤ 31 días)
python descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-01-20 --sistema SIN

# Un solo día
python descargar_pml_mda.py --inicio 2025-06-10 --fin 2025-06-10 --sistema BCA

# Forzar descarga diaria explícita
python descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-01-25 --modo diario --sistema BCS
```

### Rango parcial que cruza meses

Para periodos largos con días concretos, el modo `auto` descarga los meses completos que cubren el rango y **filtra** el CSV al consolidar:

```bash
python descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-03-10 --sistema SIN
```

También puedes forzar ese comportamiento con `--modo mensual`:

```bash
python descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-03-10 --modo mensual --sistema SIN
```

### Todas las opciones de línea de comandos

| Argumento | Descripción |
| :--- | :--- |
| `--inicio` | Fecha inicial (`YYYY-MM`, `YYYY-MM-DD`, `DD/MM/YYYY`, `MM/YYYY`, `YYYYMM`) |
| `--fin` | Fecha final (mismo formato que `--inicio`) |
| `--modo` | `auto` (default), `mensual` (ZIPs mensuales) o `diario` (tramos de máx. 7 días) |
| `--sistema` | Sistema interconectado: `SIN`, `BCA` o `BCS` |
| `--outdir` | Directorio base de salida (default: directorio actual) |
| `--solo-descarga` | Solo descarga y guarda los ZIPs en `raw/<SISTEMA>/`, sin consolidar CSV |
| `--solo-consolidar` | No descarga; consolida los ZIPs ya existentes en `raw/<SISTEMA>/` |
| `--forzar` | Vuelve a descargar los ZIPs aunque ya existan en disco |
| `--sleep` | Pausa en segundos entre descargas consecutivas (default: `1.5`) |
| `--reintentos` | Número máximo de intentos por descarga ante fallos (default: `3`) |
| `--no-interactivo` | No pide datos por consola; exige `--inicio` y `--fin` |

## Modos de descarga

| Modo | Cuándo usarlo | Qué descarga |
| :--- | :--- | :--- |
| `auto` (default) | La mayoría de casos | Meses completos si solo indicas mes o meses enteros; diario si el rango es ≤ 31 días; mensual + filtro si el rango es largo y parcial |
| `mensual` | Meses enteros o rangos parciales largos | Un ZIP por mes (con 2 CSV quincenales); filtra fechas al consolidar si el rango no cubre meses completos |
| `diario` | Rangos cortos de días | Un ZIP por tramo (máx. 7 días por petición a CENACE) |

## Estructura de salida

```text
<outdir>/
  raw/
    SIN/
      pml_mda_sin_2025_01.zip                       # mensual
      pml_mda_sin_20250115_20250120.zip             # diario (rango)
      pml_mda_sin_2025_01_15.zip                    # diario (un día)
    BCA/
      pml_mda_bca_2025_09.zip
    BCS/
      pml_mda_bcs_2025_09.zip
  output/
    pml_mda_sin_2025_01.csv                         # un solo mes completo
    pml_mda_sin_2025.csv                            # año calendario completo (ene–dic)
    pml_mda_bca_20250901_20260930.csv               # rango de varios meses o días
    pml_mda_bcs_20250901_20260930.csv
```

Columnas del CSV consolidado: `fecha,hora,clv_nodo,pml,pml_ene,pml_per,pml_cng`

## Manejo de errores y notas técnicas

- **Flujo ASP.NET WebForms (`SIN` / `BCA` / `BCS`)**: El formulario de CENACE requiere *postbacks* secuenciales independientes para cambiar la periodicidad (`ddlPeriodicidad`), luego el sistema (`ddlSistema`) y finalmente el periodo (`txtPeriodo`). Si se cambia `ddlPeriodicidad`, el servidor recarga `ddlSistema` y lo reinicia a `SIN`; y si se cambia `ddlSistema` en el mismo *postback* que `txtPeriodo`, el servidor reinicia `txtPeriodo` al último mes publicado. El script realiza cada cambio en su propio *postback* y verifica que tanto el sistema como el periodo hayan quedado fijados antes de solicitar el ZIP.
- **Reintentos automáticos**: Por defecto realiza hasta 3 intentos con espera progresiva ante errores de red o del formulario.
- **Reanudación inteligente**: Si un periodo falla, continúa con el siguiente y reporta los pendientes al final. Al volver a ejecutar, **omite** los ZIPs ya descargados (usa `--forzar` para volver a bajarlos).
- **Validación de contenido**: Verifica que cada respuesta sea un archivo ZIP válido y contenga archivos CSV correspondientes al periodo solicitado.

## SW-PML vs este script

| Método | Cuándo usarlo |
| :--- | :--- |
| **Este script (página web)** | Todo el sistema (`SIN`, `BCA`, `BCS`) / periodos largos / descargas masivas mensuales o por rangos de días |
| **SW-PML** (manual técnico) | Consultas puntuales de pocos nodos (máx. 7 días y 20 nodos por petición) |

---

# PML MDA — CENACE Downloader (English Version)

Reusable script to download **Local Marginal Prices (PML)** of the **MDA** (Day-Ahead Market) from CENACE's SIM Public Area for any of the three interconnected systems (**SIN**, **BCA**, **BCS**) and consolidate them into a single CSV file.

Source: https://www.cenace.gob.mx/Paginas/SIM/Reportes/PreEnerServConMDA.aspx

## Installation and Requirements

- Python 3.9 or higher
- Install the required dependencies using `requirements.txt`:

```bash
pip install -r requirements.txt
```

## Interactive Usage (prompts for dates)

Works from **any directory**:

```bash
python descargar_pml_mda.py
```

It will prompt you for:

1. Start date (month or day: `2025-01`, `2025-01-15`, `15/01/2025`)
2. End date
3. Mode (`auto` / `mensual` / `diario`)
4. Interconnected System (`SIN` / `BCA` / `BCS`)
5. Output directory (default: current working directory)

## Usage with Arguments

### Full Months and Bulk Downloads by System (`SIN`, `BCA`, `BCS`)

```bash
# Full year (SIN)
python descargar_pml_mda.py --inicio 2025-01 --fin 2025-12 --sistema SIN

# Monthly bulk downloads for BCA and BCS (non-interactive)
python descargar_pml_mda.py --inicio 2025-09-01 --fin 2026-09-30 --modo mensual --sistema BCA --no-interactivo
python descargar_pml_mda.py --inicio 2025-09-01 --fin 2026-09-30 --modo mensual --sistema BCS --no-interactivo

# Custom output directory
python descargar_pml_mda.py --inicio 01/2024 --fin 03/2024 --sistema SIN --outdir ~/data/pml
```

### Specific Date Ranges

```bash
# Auto: detects daily mode for short ranges (≤ 31 days)
python descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-01-20 --sistema SIN

# Single day
python descargar_pml_mda.py --inicio 2025-06-10 --fin 2025-06-10 --sistema BCA

# Force daily download explicitly
python descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-01-25 --modo diario --sistema BCS
```

### Partial Ranges Crossing Months

For long periods with specific days, `auto` mode downloads the full months covering the range and **filters** the CSV when consolidating:

```bash
python descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-03-10 --sistema SIN
```

You can also force this behavior with `--modo mensual`:

```bash
python descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-03-10 --modo mensual --sistema SIN
```

### CLI Options Reference

| Argument | Description |
| :--- | :--- |
| `--inicio` | Start date (`YYYY-MM`, `YYYY-MM-DD`, `DD/MM/YYYY`, `MM/YYYY`, `YYYYMM`) |
| `--fin` | End date (same formats as `--inicio`) |
| `--modo` | `auto` (default), `mensual` (monthly ZIPs), or `diario` (up to 7-day segments) |
| `--sistema` | Interconnected system: `SIN`, `BCA`, or `BCS` |
| `--outdir` | Base output directory (default: current directory) |
| `--solo-descarga` | Only download and store ZIPs under `raw/<SYSTEM>/`, skip CSV consolidation |
| `--solo-consolidar` | Skip downloading; consolidate existing ZIPs from `raw/<SYSTEM>/` |
| `--forzar` | Re-download ZIPs even if they already exist on disk |
| `--sleep` | Pause in seconds between consecutive downloads (default: `1.5`) |
| `--reintentos` | Maximum retries per download on failure (default: `3`) |
| `--no-interactivo` | Do not prompt via console; requires `--inicio` and `--fin` |

## Download Modes

| Mode | When to use | What it downloads |
| :--- | :--- | :--- |
| `auto` (default) | Most cases | Full months if only month or full-month range is given; daily if range is ≤ 31 days; monthly + filter if range is long and partial |
| `mensual` | Entire months or long partial ranges | One ZIP per month (containing 2 biweekly CSVs); filters dates during consolidation if range doesn't cover full months |
| `diario` | Short date ranges | One ZIP per segment (max 7 days per request to CENACE) |

## Output Structure

```text
<outdir>/
  raw/
    SIN/
      pml_mda_sin_2025_01.zip                       # monthly
      pml_mda_sin_20250115_20250120.zip             # daily (range)
      pml_mda_sin_2025_01_15.zip                    # daily (one day)
    BCA/
      pml_mda_bca_2025_09.zip
    BCS/
      pml_mda_bcs_2025_09.zip
  output/
    pml_mda_sin_2025_01.csv                         # single full month
    pml_mda_sin_2025.csv                            # full calendar year (Jan–Dec)
    pml_mda_bca_20250901_20260930.csv               # multi-month or custom date range
    pml_mda_bcs_20250901_20260930.csv
```

Consolidated CSV columns: `fecha,hora,clv_nodo,pml,pml_ene,pml_per,pml_cng`

## Error Handling and Technical Notes

- **ASP.NET WebForms Postback Flow (`SIN` / `BCA` / `BCS`)**: CENACE's form requires separate sequential postbacks to change periodicity (`ddlPeriodicidad`), then the system (`ddlSistema`), and finally the date range (`txtPeriodo`). Changing `ddlPeriodicidad` reloads `ddlSistema` and resets it to `SIN`; changing `ddlSistema` in the same postback as `txtPeriodo` resets `txtPeriodo` to the latest published month. The script performs each state transition in its own postback and verifies both the selected system and date period before requesting the ZIP.
- **Automatic retries**: Retries up to 3 times by default with linear backoff on network or form errors.
- **Resumable downloads**: If a period fails, it continues with the remaining ones and reports any failed periods at the end. Re-running **skips** already downloaded ZIPs (use `--forzar` to re-download).
- **Content validation**: Verifies that each downloaded file is a valid ZIP containing CSV data matching the requested period.

## SW-PML vs this script

| Method | When to use |
| :--- | :--- |
| **This script (web page)** | Whole system (`SIN`, `BCA`, `BCS`) / long periods / bulk monthly or date-range downloads |
| **SW-PML** (technical manual) | Targeted queries for a few nodes (max 7 days and 20 nodes per request) |
