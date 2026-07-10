#!/usr/bin/env python3
"""
Descarga Precios Marginales Locales (PML) MDA del CENACE y consolida a CSV.

Fuente:
  https://www.cenace.gob.mx/Paginas/SIM/Reportes/PreEnerServConMDA.aspx

Periodicidad Mensual: cada ZIP trae 2 CSV (quincenas 01 y 02).
Periodicidad Diaria: un ZIP por rango de días (máx. 7 días por petición).

Uso interactivo (pide fechas):
  python3 descargar_pml_mda.py

Uso con argumentos:
  python3 descargar_pml_mda.py --inicio 2025-01 --fin 2025-12 --sistema SIN
  python3 descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-01-20
  python3 descargar_pml_mda.py --inicio 2025-01-15 --fin 2025-03-10 --modo diario

Funciona desde cualquier directorio: por defecto escribe en el cwd actual.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import io
import re
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Literal

try:
    import requests
    from requests import RequestException
except ImportError:
    print(
        "ERROR: falta el paquete 'requests'.\n"
        "  Instálalo con:  pip install requests\n"
        "  o en Arch/CachyOS:  sudo pacman -S python-requests",
        file=sys.stderr,
    )
    raise SystemExit(1)

URL = "https://www.cenace.gob.mx/Paginas/SIM/Reportes/PreEnerServConMDA.aspx"
REPORTE_PML = "359,322"
SISTEMAS = ("SIN", "BCA", "BCS")
MAX_REINTENTOS = 3
PAUSA_REINTENTO_S = 3.0
MAX_DIAS_POR_DESCARGA = 7
MODOS = ("auto", "mensual", "diario")

SKIP_INPUTS = {
    "ctl00$ContentPlaceHolder1$btnDescargarZIP",
    "ctl00$ContentPlaceHolder1$btnCerrarPanel",
}

COLUMNAS = [
    "fecha",
    "hora",
    "clv_nodo",
    "pml",
    "pml_ene",
    "pml_per",
    "pml_cng",
]

MESES_ES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}

MESES_ABREV_ES = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}


class CenaceError(Exception):
    """Error recuperable o de negocio al hablar con CENACE."""


# ---------------------------------------------------------------------------
# Utilidades de fechas / input
# ---------------------------------------------------------------------------

_FORMATOS_CON_DIA = ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d")
_FORMATOS_SOLO_MES = ("%Y-%m", "%Y/%m", "%m/%Y", "%Y%m")


def _texto_tiene_dia(texto: str) -> bool:
    raw = (texto or "").strip()
    for fmt in _FORMATOS_CON_DIA:
        try:
            datetime.strptime(raw, fmt)
            return True
        except ValueError:
            continue
    return False


def parse_fecha(texto: str, *, es_fin: bool = False) -> date:
    """
    Acepta: YYYY-MM, YYYY/MM, MM/YYYY, YYYY-MM-DD, DD/MM/YYYY, YYYYMM.
    Si solo viene mes, usa día 1 (inicio) o último día del mes (fin).
    """
    raw = (texto or "").strip()
    if not raw:
        raise ValueError("La fecha no puede estar vacía.")

    for fmt in _FORMATOS_CON_DIA:
        try:
            dt = datetime.strptime(raw, fmt)
            return date(dt.year, dt.month, dt.day)
        except ValueError:
            continue

    for fmt in _FORMATOS_SOLO_MES:
        try:
            dt = datetime.strptime(raw, fmt)
            if es_fin:
                ultimo = calendar.monthrange(dt.year, dt.month)[1]
                return date(dt.year, dt.month, ultimo)
            return date(dt.year, dt.month, 1)
        except ValueError:
            continue

    raise ValueError(
        f"Fecha no reconocida: {texto!r}. "
        "Usa p.ej. 2025-01, 01/2025, 2025-01-01 o 01/01/2025."
    )


def parse_fecha_mes(texto: str) -> date:
    """Compatibilidad: devuelve el día 1 del mes."""
    return parse_fecha(texto, es_fin=False).replace(day=1)


def formato_cenace(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def parse_fecha_csv(texto: str) -> date | None:
    raw = (texto or "").strip().strip('"')
    if not raw:
        return None
    if raw.lower().startswith("fecha:"):
        raw = raw.split(":", 1)[1].strip()

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return date(dt.year, dt.month, dt.day)
        except ValueError:
            continue

    # Formato diario CENACE: 15/feb/2026
    m = re.match(r"^(\d{1,2})/([A-Za-z]{3})/(\d{4})$", raw)
    if m:
        dia = int(m.group(1))
        mes = MESES_ABREV_ES.get(m.group(2).lower())
        anio = int(m.group(3))
        if mes is not None:
            try:
                return date(anio, mes, dia)
            except ValueError:
                return None
    return None


def formato_fecha_csv(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def meses_entre(inicio: date, fin: date) -> list[tuple[int, int]]:
    inicio_mes = date(inicio.year, inicio.month, 1)
    fin_mes = date(fin.year, fin.month, 1)
    if (fin_mes.year, fin_mes.month) < (inicio_mes.year, inicio_mes.month):
        raise ValueError(
            f"La fecha fin ({fin.isoformat()}) es anterior "
            f"al inicio ({inicio.isoformat()})."
        )
    out: list[tuple[int, int]] = []
    y, m = inicio_mes.year, inicio_mes.month
    while (y, m) <= (fin_mes.year, fin_mes.month):
        out.append((y, m))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out


def rangos_diarios(
    inicio: date,
    fin: date,
    max_dias: int = MAX_DIAS_POR_DESCARGA,
) -> list[tuple[date, date]]:
    if fin < inicio:
        raise ValueError(
            f"La fecha fin ({fin.isoformat()}) es anterior "
            f"al inicio ({inicio.isoformat()})."
        )
    if max_dias < 1:
        raise ValueError("max_dias debe ser al menos 1.")

    out: list[tuple[date, date]] = []
    cursor = inicio
    while cursor <= fin:
        fin_tramo = min(cursor + timedelta(days=max_dias - 1), fin)
        out.append((cursor, fin_tramo))
        cursor = fin_tramo + timedelta(days=1)
    return out


def es_rango_meses_completos(inicio: date, fin: date) -> bool:
    if inicio.day != 1:
        return False
    ultimo = calendar.monthrange(fin.year, fin.month)[1]
    if fin.day != ultimo:
        return False
    meses = meses_entre(inicio, fin)
    dias_esperados = sum(calendar.monthrange(y, m)[1] for y, m in meses)
    return (fin - inicio).days + 1 == dias_esperados


def detectar_modo(
    inicio: date,
    fin: date,
    inicio_raw: str | None,
    fin_raw: str | None,
    modo: str,
) -> Literal["mensual", "diario"]:
    if modo == "mensual":
        return "mensual"
    if modo == "diario":
        return "diario"

    tiene_dia = _texto_tiene_dia(inicio_raw or "") or _texto_tiene_dia(fin_raw or "")
    if not tiene_dia or es_rango_meses_completos(inicio, fin):
        return "mensual"
    if (fin - inicio).days <= 31:
        return "diario"
    return "mensual"


def pedir(texto: str, default: str | None = None) -> str:
    if default is not None:
        prompt = f"{texto} [{default}]: "
    else:
        prompt = f"{texto}: "
    try:
        valor = input(prompt).strip()
    except EOFError:
        valor = ""
    if not valor and default is not None:
        return default
    return valor


def pedir_fecha(etiqueta: str, default: str | None = None, *, es_fin: bool = False) -> date:
    while True:
        raw = pedir(etiqueta, default)
        try:
            return parse_fecha(raw, es_fin=es_fin)
        except ValueError as exc:
            print(f"  → {exc}")


def pedir_modo(default: str = "auto") -> str:
    while True:
        raw = pedir(f"Modo ({'/'.join(MODOS)})", default).lower()
        if raw in MODOS:
            return raw
        print(f"  → Modo inválido. Elige entre {', '.join(MODOS)}.")


def pedir_sistema(default: str = "SIN") -> str:
    while True:
        raw = pedir(f"Sistema ({'/'.join(SISTEMAS)})", default).upper()
        if raw in SISTEMAS:
            return raw
        print(f"  → Sistema inválido. Elige entre {', '.join(SISTEMAS)}.")


def pedir_ruta(etiqueta: str, default: Path) -> Path:
    while True:
        raw = pedir(etiqueta, str(default))
        try:
            path = Path(raw).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError as exc:
            print(f"  → No se pudo usar esa ruta: {exc}")


# ---------------------------------------------------------------------------
# Parsing del formulario ASP.NET
# ---------------------------------------------------------------------------


def extract_fields(html: str) -> dict[str, str]:
    if not html or "<html" not in html.lower():
        raise CenaceError("La respuesta de CENACE no parece HTML válido.")

    fields: dict[str, str] = {}
    for tag in re.findall(r"<input[^>]+>", html, re.I):
        n = re.search(r'name="([^"]+)"', tag)
        if not n:
            continue
        name = n.group(1)
        if name in SKIP_INPUTS:
            continue
        typ = re.search(r'type="([^"]*)"', tag, re.I)
        t = (typ.group(1).lower() if typ else "text")
        if t in ("submit", "button", "image"):
            continue
        v = re.search(r'value="([^"]*)"', tag)
        fields[name] = v.group(1) if v else ""

    for sid, body in re.findall(
        r'<select[^>]+name="([^"]+)"[^>]*>(.*?)</select>', html, re.S | re.I
    ):
        m = re.search(
            r'<option[^>]*selected="selected"[^>]*value="([^"]*)"', body, re.I
        )
        if not m:
            m = re.search(r'<option[^>]*value="([^"]*)"', body, re.I)
        if m:
            fields[sid] = m.group(1)

    if "__VIEWSTATE" not in fields:
        raise CenaceError(
            "No se encontró __VIEWSTATE. La página de CENACE pudo haber cambiado."
        )
    return fields


# ---------------------------------------------------------------------------
# Cliente CENACE
# ---------------------------------------------------------------------------


class CenacePmlDownloader:
    def __init__(self, sistema: str = "SIN", timeout: int = 300):
        self.sistema = sistema.upper()
        if self.sistema not in SISTEMAS:
            raise ValueError(f"Sistema inválido: {sistema}")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,*/*;q=0.8"
                ),
            }
        )

    def _post(self, fields: dict[str, str], extra: dict[str, str]) -> requests.Response:
        data = dict(fields)
        data.update(extra)
        data.setdefault("__EVENTTARGET", "")
        data.setdefault("__EVENTARGUMENT", "")
        data.setdefault("__LASTFOCUS", "")
        try:
            return self.session.post(
                URL,
                data=data,
                headers={
                    "Referer": URL,
                    "Origin": "https://www.cenace.gob.mx",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=self.timeout,
                allow_redirects=True,
            )
        except RequestException as exc:
            raise CenaceError(f"Error de red al consultar CENACE: {exc}") from exc

    @staticmethod
    def _is_zip(resp: requests.Response) -> bool:
        cd = (resp.headers.get("Content-Disposition") or "").lower()
        ctype = (resp.headers.get("Content-Type") or "").lower()
        return (
            resp.content[:2] == b"PK"
            or "attachment" in cd
            or "zip" in ctype
            or "octet-stream" in ctype and resp.content[:2] == b"PK"
        )

    def _get_inicial(self) -> dict[str, str]:
        try:
            r = self.session.get(URL, timeout=self.timeout)
            r.raise_for_status()
        except RequestException as exc:
            raise CenaceError(f"No se pudo abrir la página de CENACE: {exc}") from exc
        return extract_fields(r.text)

    def download_periodo(
        self,
        inicio: date,
        fin: date,
        periodicidad: Literal["M", "D"] = "M",
    ) -> bytes:
        """Descarga ZIP de PML MDA para un periodo mensual o diario."""
        if periodicidad == "M":
            if inicio.year != fin.year or inicio.month != fin.month or inicio.day != fin.day:
                last_day = calendar.monthrange(inicio.year, inicio.month)[1]
                fecha = f"{last_day:02d}/{inicio.month:02d}/{inicio.year}"
            else:
                fecha = formato_cenace(inicio)
        else:
            fecha_inicio = formato_cenace(inicio)
            fecha_fin = formato_cenace(fin)
            fecha = fecha_fin
            periodo = f"{fecha_inicio}-{fecha_fin}"

        if periodicidad == "M":
            periodo = f"{fecha}-{fecha}"

        etiqueta = (
            f"{inicio.year}-{inicio.month:02d}"
            if periodicidad == "M"
            else f"{inicio.isoformat()}→{fin.isoformat()}"
        )

        fields = self._get_inicial()

        # 1) Periodicidad
        resp = self._post(
            fields,
            {
                "__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlPeriodicidad",
                "ctl00$ContentPlaceHolder1$ddlReporte": REPORTE_PML,
                "ctl00$ContentPlaceHolder1$ddlPeriodicidad": periodicidad,
                "ctl00$ContentPlaceHolder1$ddlSistema": self.sistema,
            },
        )
        if resp.status_code >= 400:
            raise CenaceError(f"HTTP {resp.status_code} al cambiar periodicidad")
        if self._is_zip(resp):
            raise CenaceError("Respuesta ZIP inesperada al cambiar periodicidad")
        fields = extract_fields(resp.text)

        # 2) Fijar periodo
        if periodicidad == "M":
            extra_periodo = {
                "ctl00$ContentPlaceHolder1$hdfStartDateSelected": fecha,
                "ctl00$ContentPlaceHolder1$hdfEndDateSelected": fecha,
            }
        else:
            extra_periodo = {
                "ctl00$ContentPlaceHolder1$hdfStartDateSelected": fecha_inicio,
                "ctl00$ContentPlaceHolder1$hdfEndDateSelected": fecha_fin,
            }

        resp = self._post(
            fields,
            {
                "__EVENTTARGET": "ctl00$ContentPlaceHolder1$txtPeriodo",
                "ctl00$ContentPlaceHolder1$ddlReporte": REPORTE_PML,
                "ctl00$ContentPlaceHolder1$ddlPeriodicidad": periodicidad,
                "ctl00$ContentPlaceHolder1$ddlSistema": self.sistema,
                "ctl00$ContentPlaceHolder1$txtPeriodo": periodo,
                **extra_periodo,
            },
        )
        if resp.status_code >= 400:
            raise CenaceError(f"HTTP {resp.status_code} al fijar periodo")
        if self._is_zip(resp):
            raise CenaceError("Respuesta ZIP inesperada al fijar periodo")
        fields = extract_fields(resp.text)

        periodo_ok = fields.get("ctl00$ContentPlaceHolder1$txtPeriodo", "")
        if periodo not in periodo_ok and periodicidad == "M":
            raise CenaceError(
                f"No se pudo fijar el periodo {periodo}; el formulario quedó en "
                f"{periodo_ok!r}. ¿El mes ya está publicado en CENACE?"
            )
        if periodicidad == "D" and fecha_inicio not in periodo_ok:
            raise CenaceError(
                f"No se pudo fijar el periodo {periodo}; el formulario quedó en "
                f"{periodo_ok!r}. ¿Las fechas ya están publicadas en CENACE?"
            )

        # 3) Descargar ZIP
        resp = self._post(
            fields,
            {
                "__EVENTTARGET": "",
                "ctl00$ContentPlaceHolder1$ddlReporte": REPORTE_PML,
                "ctl00$ContentPlaceHolder1$ddlPeriodicidad": periodicidad,
                "ctl00$ContentPlaceHolder1$ddlSistema": self.sistema,
                "ctl00$ContentPlaceHolder1$txtPeriodo": fields.get(
                    "ctl00$ContentPlaceHolder1$txtPeriodo", periodo
                ),
                "ctl00$ContentPlaceHolder1$hdfStartDateSelected": fields.get(
                    "ctl00$ContentPlaceHolder1$hdfStartDateSelected",
                    extra_periodo["ctl00$ContentPlaceHolder1$hdfStartDateSelected"],
                ),
                "ctl00$ContentPlaceHolder1$hdfEndDateSelected": fields.get(
                    "ctl00$ContentPlaceHolder1$hdfEndDateSelected",
                    extra_periodo["ctl00$ContentPlaceHolder1$hdfEndDateSelected"],
                ),
                "ctl00$ContentPlaceHolder1$btnDescargarZIP": "Descargar ZIP",
            },
        )
        if resp.status_code >= 400:
            raise CenaceError(f"HTTP {resp.status_code} al descargar ZIP")
        if not self._is_zip(resp):
            raise CenaceError(
                f"La descarga de {etiqueta} no devolvió ZIP "
                f"(Content-Type={resp.headers.get('Content-Type')!r}). "
                "Es posible que el periodo aún no esté disponible."
            )
        if len(resp.content) < 1000:
            raise CenaceError(
                f"ZIP de {etiqueta} demasiado pequeño "
                f"({len(resp.content)} bytes); posible respuesta vacía."
            )
        if periodicidad == "M":
            self._validar_zip_mensual(resp.content, inicio.year, inicio.month)
        else:
            self._validar_zip_diario(resp.content, inicio, fin)
        return resp.content

    def download_month(self, year: int, month: int) -> bytes:
        """Descarga el ZIP mensual (2 CSV quincenales) de PML MDA."""
        last_day = calendar.monthrange(year, month)[1]
        return self.download_periodo(
            date(year, month, last_day),
            date(year, month, last_day),
            periodicidad="M",
        )

    @staticmethod
    def _validar_zip_mensual(content: bytes, year: int, month: int) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not names:
                    raise CenaceError(
                        f"El ZIP de {year}-{month:02d} no contiene CSV."
                    )
                sample = zf.read(names[0])[:800].decode("latin-1", "replace")
        except zipfile.BadZipFile as exc:
            raise CenaceError(
                f"El archivo de {year}-{month:02d} no es un ZIP válido."
            ) from exc

        mes_nombre = MESES_ES[month]
        if str(year) not in sample and f"{year}" not in sample:
            pass
        if mes_nombre not in sample.lower() and f"{month:02d}" not in sample:
            raise CenaceError(
                f"El ZIP descargado no parece corresponder a "
                f"{mes_nombre} {year}. Encabezado: {sample.splitlines()[:5]}"
            )

    @staticmethod
    def _validar_zip_diario(content: bytes, inicio: date, fin: date) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not names:
                    raise CenaceError(
                        f"El ZIP de {inicio.isoformat()}→{fin.isoformat()} "
                        "no contiene CSV."
                    )
        except zipfile.BadZipFile as exc:
            raise CenaceError(
                f"El archivo de {inicio.isoformat()}→{fin.isoformat()} "
                "no es un ZIP válido."
            ) from exc


def download_periodo_con_reintentos(
    dl: CenacePmlDownloader,
    inicio: date,
    fin: date,
    periodicidad: Literal["M", "D"] = "M",
    reintentos: int = MAX_REINTENTOS,
) -> bytes:
    etiqueta = (
        f"{inicio.year}-{inicio.month:02d}"
        if periodicidad == "M"
        else f"{inicio.isoformat()}→{fin.isoformat()}"
    )
    ultimo: Exception | None = None
    for intento in range(1, reintentos + 1):
        try:
            return dl.download_periodo(inicio, fin, periodicidad=periodicidad)
        except (CenaceError, RequestException, OSError) as exc:
            ultimo = exc
            if intento < reintentos:
                espera = PAUSA_REINTENTO_S * intento
                print(
                    f"  [reintento {intento}/{reintentos}] {exc} "
                    f"— esperando {espera:.0f}s...",
                    flush=True,
                )
                time.sleep(espera)
            else:
                break
    assert ultimo is not None
    raise CenaceError(
        f"Falló {etiqueta} tras {reintentos} intentos: {ultimo}"
    ) from ultimo


def download_month_con_reintentos(
    dl: CenacePmlDownloader,
    year: int,
    month: int,
    reintentos: int = MAX_REINTENTOS,
) -> bytes:
    ultimo: Exception | None = None
    for intento in range(1, reintentos + 1):
        try:
            return dl.download_month(year, month)
        except (CenaceError, RequestException, OSError) as exc:
            ultimo = exc
            if intento < reintentos:
                espera = PAUSA_REINTENTO_S * intento
                print(
                    f"  [reintento {intento}/{reintentos}] {exc} "
                    f"— esperando {espera:.0f}s...",
                    flush=True,
                )
                time.sleep(espera)
            else:
                break
    assert ultimo is not None
    raise CenaceError(
        f"Falló {year}-{month:02d} tras {reintentos} intentos: {ultimo}"
    ) from ultimo


# ---------------------------------------------------------------------------
# Consolidación CSV
# ---------------------------------------------------------------------------


def iter_pml_rows(csv_bytes: bytes) -> Iterable[dict[str, str]]:
    """
    Itera filas PML.

    Formato mensual: Fecha, Hora, Clave, PML, ...
    Formato diario:  metadatos con "Fecha: DD/mmm/YYYY" y luego
                     Hora, Clave, PML, ... (sin columna fecha).
    """
    text = csv_bytes.decode("latin-1")
    reader = csv.reader(io.StringIO(text))
    header_seen = False
    modo: Literal["mensual", "diario"] | None = None
    fecha_diaria: str | None = None

    for row in reader:
        if not row:
            continue
        first = row[0].strip().strip('"')
        first_l = first.lower()

        if not header_seen:
            # Metadato diario: "Fecha: 15/feb/2026"
            if first_l.startswith("fecha:") and len(row) == 1:
                f = parse_fecha_csv(first)
                if f is not None:
                    fecha_diaria = formato_fecha_csv(f)
                continue

            if first_l.startswith("fecha") and "hora" in " ".join(row).lower():
                header_seen = True
                modo = "mensual"
                continue

            if first_l.startswith("hora"):
                header_seen = True
                modo = "diario"
                continue
            continue

        if modo == "mensual":
            if len(row) < 7:
                continue
            yield {
                "fecha": row[0].strip(),
                "hora": row[1].strip(),
                "clv_nodo": row[2].strip(),
                "pml": row[3].strip(),
                "pml_ene": row[4].strip(),
                "pml_per": row[5].strip(),
                "pml_cng": row[6].strip(),
            }
        elif modo == "diario":
            if len(row) < 6 or fecha_diaria is None:
                continue
            yield {
                "fecha": fecha_diaria,
                "hora": row[0].strip(),
                "clv_nodo": row[1].strip(),
                "pml": row[2].strip(),
                "pml_ene": row[3].strip(),
                "pml_per": row[4].strip(),
                "pml_cng": row[5].strip(),
            }


def consolidar_zips(
    zip_paths: list[Path],
    out_csv: Path,
    fecha_min: date | None = None,
    fecha_max: date | None = None,
) -> int:
    if not zip_paths:
        raise CenaceError("No hay ZIPs para consolidar.")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    omitidas = 0
    with out_csv.open("w", newline="", encoding="utf-8") as fout:
        writer = csv.DictWriter(fout, fieldnames=COLUMNAS)
        writer.writeheader()
        for zp in zip_paths:
            try:
                with zipfile.ZipFile(zp) as zf:
                    csv_names = sorted(
                        n for n in zf.namelist() if n.lower().endswith(".csv")
                    )
                    if not csv_names:
                        print(f"  ! {zp.name}: sin CSV, se omite", flush=True)
                        continue
                    for name in csv_names:
                        with zf.open(name) as f:
                            data = f.read()
                        n = 0
                        for row in iter_pml_rows(data):
                            if fecha_min is not None or fecha_max is not None:
                                f_row = parse_fecha_csv(row["fecha"])
                                if f_row is None:
                                    continue
                                if fecha_min is not None and f_row < fecha_min:
                                    omitidas += 1
                                    continue
                                if fecha_max is not None and f_row > fecha_max:
                                    omitidas += 1
                                    continue
                            writer.writerow(row)
                            n += 1
                        total += n
                        print(f"  + {zp.name} / {name}: {n:,} filas", flush=True)
            except zipfile.BadZipFile as exc:
                raise CenaceError(f"ZIP corrupto: {zp}") from exc
            except OSError as exc:
                raise CenaceError(f"No se pudo leer {zp}: {exc}") from exc
    if omitidas:
        print(f"  (filtradas {omitidas:,} filas fuera del rango)", flush=True)
    return total


# ---------------------------------------------------------------------------
# CLI / interactivo
# ---------------------------------------------------------------------------


def construir_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Descarga PML MDA del CENACE (mensual, diario o rango parcial) "
            "y consolida a CSV. Sin argumentos, pide las fechas de forma interactiva."
        )
    )
    ap.add_argument(
        "--inicio",
        help="Fecha inicial (YYYY-MM, YYYY-MM-DD, DD/MM/YYYY, ...)",
    )
    ap.add_argument(
        "--fin",
        help="Fecha final (mismo formato que --inicio)",
    )
    ap.add_argument(
        "--modo",
        choices=MODOS,
        default="auto",
        help=(
            "auto: detecta según fechas (default); mensual: ZIPs mensuales; "
            "diario: ZIPs por rango de días (máx. 7 días por petición)"
        ),
    )
    ap.add_argument(
        "--sistema",
        choices=SISTEMAS,
        help="Sistema interconectado (SIN, BCA, BCS)",
    )
    ap.add_argument(
        "--outdir",
        type=Path,
        help="Directorio base de salida (default: directorio actual)",
    )
    ap.add_argument(
        "--solo-descarga",
        action="store_true",
        help="Solo guarda ZIPs, no consolida CSV",
    )
    ap.add_argument(
        "--solo-consolidar",
        action="store_true",
        help="No descarga; consolida ZIPs ya existentes",
    )
    ap.add_argument(
        "--forzar",
        action="store_true",
        help="Vuelve a descargar aunque el ZIP ya exista",
    )
    ap.add_argument(
        "--sleep",
        type=float,
        default=1.5,
        help="Pausa entre descargas en segundos (default: 1.5)",
    )
    ap.add_argument(
        "--reintentos",
        type=int,
        default=MAX_REINTENTOS,
        help=f"Reintentos por descarga ante fallo (default: {MAX_REINTENTOS})",
    )
    ap.add_argument(
        "--no-interactivo",
        action="store_true",
        help="No pedir datos por consola; exige --inicio y --fin",
    )
    return ap


def obtener_parametros(args: argparse.Namespace) -> dict:
    """Combina CLI + prompts interactivos."""
    interactivo = not args.no_interactivo and (
        args.inicio is None or args.fin is None or args.sistema is None
    )

    if args.no_interactivo and (not args.inicio or not args.fin):
        raise SystemExit(
            "Con --no-interactivo debes indicar --inicio y --fin."
        )

    if interactivo:
        print("=" * 60)
        print("  Descarga PML MDA — CENACE")
        print("  (Precios Marginales Locales, Mercado del Día en Adelanto)")
        print("=" * 60)
        print()

    inicio_raw = args.inicio
    fin_raw = args.fin

    if inicio_raw:
        inicio = parse_fecha(inicio_raw, es_fin=False)
    else:
        inicio = pedir_fecha(
            "Fecha inicial (ej. 2025-01, 2025-01-15 o 15/01/2025)"
        )
        inicio_raw = inicio.isoformat()

    if fin_raw:
        fin = parse_fecha(fin_raw, es_fin=True)
    else:
        default_fin = inicio_raw or f"{inicio.year}-{inicio.month:02d}"
        fin = pedir_fecha("Fecha final", default_fin, es_fin=True)
        fin_raw = fin.isoformat()

    if fin < inicio:
        raise ValueError(
            f"La fecha fin ({fin.isoformat()}) es anterior "
            f"al inicio ({inicio.isoformat()})."
        )

    modo_cli = args.modo
    if interactivo and modo_cli == "auto":
        modo_cli = pedir_modo("auto")

    modo_efectivo = detectar_modo(inicio, fin, inicio_raw, fin_raw, modo_cli)

    if args.sistema:
        sistema = args.sistema.upper()
    elif interactivo:
        sistema = pedir_sistema("SIN")
    else:
        sistema = "SIN"

    if args.outdir:
        outdir = args.outdir.expanduser().resolve()
        outdir.mkdir(parents=True, exist_ok=True)
    elif interactivo:
        outdir = pedir_ruta(
            "Directorio de salida",
            Path.cwd().resolve(),
        )
    else:
        outdir = Path.cwd().resolve()

    meses = meses_entre(inicio, fin)
    rangos = rangos_diarios(inicio, fin) if modo_efectivo == "diario" else []
    filtrar_fechas = modo_efectivo == "mensual" and (
        inicio.day != 1
        or fin.day != calendar.monthrange(fin.year, fin.month)[1]
        or not es_rango_meses_completos(inicio, fin)
    )

    return {
        "inicio": inicio,
        "fin": fin,
        "inicio_raw": inicio_raw,
        "fin_raw": fin_raw,
        "modo": modo_efectivo,
        "modo_cli": modo_cli,
        "sistema": sistema,
        "outdir": outdir,
        "meses": meses,
        "rangos": rangos,
        "filtrar_fechas": filtrar_fechas,
        "solo_descarga": args.solo_descarga,
        "solo_consolidar": args.solo_consolidar,
        "forzar": args.forzar,
        "sleep": max(0.0, args.sleep),
        "reintentos": max(1, args.reintentos),
    }


def nombre_zip_mensual(sistema: str, year: int, month: int) -> str:
    return f"pml_mda_{sistema.lower()}_{year}_{month:02d}.zip"


def nombre_zip_diario(sistema: str, inicio: date, fin: date) -> str:
    if inicio == fin:
        return (
            f"pml_mda_{sistema.lower()}_"
            f"{inicio.year}_{inicio.month:02d}_{inicio.day:02d}.zip"
        )
    return (
        f"pml_mda_{sistema.lower()}_"
        f"{inicio.strftime('%Y%m%d')}_{fin.strftime('%Y%m%d')}.zip"
    )


def nombre_zip(sistema: str, year: int, month: int) -> str:
    return nombre_zip_mensual(sistema, year, month)


def nombre_csv(sistema: str, inicio: date, fin: date) -> str:
    solo_mes = (
        inicio.day == 1
        and fin.day == calendar.monthrange(fin.year, fin.month)[1]
        and inicio.year == fin.year
        and inicio.month == fin.month
    )
    if solo_mes:
        return f"pml_mda_{sistema.lower()}_{inicio.year}_{inicio.month:02d}.csv"
    if (
        inicio.day == 1
        and fin.day == calendar.monthrange(fin.year, fin.month)[1]
        and inicio.year == fin.year
        and inicio.month == 1
        and fin.month == 12
    ):
        return f"pml_mda_{sistema.lower()}_{inicio.year}.csv"
    if inicio.year == fin.year and inicio.month == fin.month:
        return (
            f"pml_mda_{sistema.lower()}_"
            f"{inicio.strftime('%Y%m%d')}_"
            f"{fin.strftime('%Y%m%d')}.csv"
        )
    return (
        f"pml_mda_{sistema.lower()}_"
        f"{inicio.strftime('%Y%m%d')}_"
        f"{fin.strftime('%Y%m%d')}.csv"
    )


def main() -> int:
    ap = construir_parser()
    args = ap.parse_args()

    try:
        params = obtener_parametros(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    sistema: str = params["sistema"]
    outdir: Path = params["outdir"]
    meses: list[tuple[int, int]] = params["meses"]
    rangos: list[tuple[date, date]] = params["rangos"]
    inicio: date = params["inicio"]
    fin: date = params["fin"]
    modo: str = params["modo"]
    filtrar_fechas: bool = params["filtrar_fechas"]

    raw_dir = outdir / "raw" / sistema
    out_csv = outdir / "output" / nombre_csv(sistema, inicio, fin)

    def info(msg: str = "") -> None:
        print(msg, flush=True)

    info()
    info(f"Sistema : {sistema}")
    info(f"Modo    : {modo}" + (f" (solicitado: {params['modo_cli']})" if params["modo_cli"] != modo else ""))
    if modo == "diario":
        info(
            f"Periodo : {inicio.isoformat()} → {fin.isoformat()} "
            f"({len(rangos)} tramo(s) de máx. {MAX_DIAS_POR_DESCARGA} días)"
        )
    else:
        info(
            f"Periodo : {inicio.isoformat()} → {fin.isoformat()} "
            f"({len(meses)} mes(es))"
        )
        if filtrar_fechas:
            info("Filtro  : solo filas dentro del rango de fechas indicado")
    info(f"Salida  : {outdir}")
    info(f"ZIPs    : {raw_dir}")
    if not params["solo_descarga"]:
        info(f"CSV     : {out_csv}")
    info()

    try:
        raw_dir.mkdir(parents=True, exist_ok=True)
        (outdir / "output").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR: no se pudo crear directorios en {outdir}: {exc}", file=sys.stderr)
        return 1

    zip_paths: list[Path] = []
    fallidos: list[str] = []

    if not params["solo_consolidar"]:
        try:
            dl = CenacePmlDownloader(sistema=sistema)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

        if modo == "diario":
            for inicio_tramo, fin_tramo in rangos:
                dest = raw_dir / nombre_zip_diario(sistema, inicio_tramo, fin_tramo)
                etiqueta = f"{inicio_tramo.isoformat()}→{fin_tramo.isoformat()}"

                if (
                    dest.exists()
                    and dest.stat().st_size > 1000
                    and not params["forzar"]
                ):
                    print(
                        f"[skip] {dest.name} ya existe "
                        f"({dest.stat().st_size:,} bytes)"
                    )
                    zip_paths.append(dest)
                    continue

                print(f"[descarga] {sistema} MDA {etiqueta} ...", flush=True)
                t0 = time.time()
                try:
                    content = download_periodo_con_reintentos(
                        dl,
                        inicio_tramo,
                        fin_tramo,
                        periodicidad="D",
                        reintentos=params["reintentos"],
                    )
                    dest.write_bytes(content)
                    with zipfile.ZipFile(io.BytesIO(content)) as zf:
                        n_archivos = len(
                            [n for n in zf.namelist() if n.lower().endswith(".csv")]
                        )
                    print(
                        f"[ok] {dest.name} ({len(content):,} bytes, "
                        f"{n_archivos} CSV, {time.time() - t0:.1f}s)"
                    )
                    zip_paths.append(dest)
                except (CenaceError, OSError) as exc:
                    print(f"[error] {etiqueta}: {exc}", file=sys.stderr)
                    fallidos.append(etiqueta)
                if params["sleep"] > 0:
                    time.sleep(params["sleep"])
        else:
            for year, month in meses:
                dest = raw_dir / nombre_zip_mensual(sistema, year, month)
                etiqueta = f"{year}-{month:02d}"

                if (
                    dest.exists()
                    and dest.stat().st_size > 1000
                    and not params["forzar"]
                ):
                    print(
                        f"[skip] {dest.name} ya existe "
                        f"({dest.stat().st_size:,} bytes)"
                    )
                    zip_paths.append(dest)
                    continue

                print(f"[descarga] {sistema} MDA {etiqueta} ...", flush=True)
                t0 = time.time()
                try:
                    content = download_month_con_reintentos(
                        dl, year, month, reintentos=params["reintentos"]
                    )
                    dest.write_bytes(content)
                    with zipfile.ZipFile(io.BytesIO(content)) as zf:
                        n_archivos = len(
                            [n for n in zf.namelist() if n.lower().endswith(".csv")]
                        )
                    print(
                        f"[ok] {dest.name} ({len(content):,} bytes, "
                        f"{n_archivos} CSV, {time.time() - t0:.1f}s)"
                    )
                    zip_paths.append(dest)
                except (CenaceError, OSError) as exc:
                    print(f"[error] {etiqueta}: {exc}", file=sys.stderr)
                    fallidos.append(etiqueta)
                if params["sleep"] > 0:
                    time.sleep(params["sleep"])
    else:
        if modo == "diario":
            for inicio_tramo, fin_tramo in rangos:
                dest = raw_dir / nombre_zip_diario(sistema, inicio_tramo, fin_tramo)
                etiqueta = f"{inicio_tramo.isoformat()}→{fin_tramo.isoformat()}"
                if not dest.exists():
                    print(f"[error] falta {dest}", file=sys.stderr)
                    fallidos.append(etiqueta)
                else:
                    zip_paths.append(dest)
        else:
            for year, month in meses:
                dest = raw_dir / nombre_zip_mensual(sistema, year, month)
                if not dest.exists():
                    print(f"[error] falta {dest}", file=sys.stderr)
                    fallidos.append(f"{year}-{month:02d}")
                else:
                    zip_paths.append(dest)

    if params["solo_descarga"]:
        print()
        print(f"Listo. ZIPs en: {raw_dir}")
        if fallidos:
            print(f"Descargas fallidas: {', '.join(fallidos)}", file=sys.stderr)
            return 1
        return 0

    if not zip_paths:
        print(
            "ERROR: no hay ZIPs para consolidar. "
            "Revisa fechas, conectividad o errores anteriores.",
            file=sys.stderr,
        )
        return 1

    print()
    print(f"[consolida] → {out_csv}")
    fecha_min = inicio if filtrar_fechas else None
    fecha_max = fin if filtrar_fechas else None
    try:
        total = consolidar_zips(
            zip_paths,
            out_csv,
            fecha_min=fecha_min,
            fecha_max=fecha_max,
        )
    except CenaceError as exc:
        print(f"ERROR al consolidar: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR de escritura en {out_csv}: {exc}", file=sys.stderr)
        return 1

    size_mb = out_csv.stat().st_size / (1024 * 1024)
    print()
    print(f"[listo] {total:,} filas · {size_mb:.1f} MB")
    print(f"        {out_csv}")

    if fallidos:
        print()
        print(
            f"AVISO: {len(fallidos)} descarga(s) no se completaron: "
            f"{', '.join(fallidos)}",
            file=sys.stderr,
        )
        print(
            "       El CSV incluye solo los periodos disponibles. "
            "Vuelve a ejecutar el script para reintentar los faltantes.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelado por el usuario.", file=sys.stderr)
        raise SystemExit(130)
