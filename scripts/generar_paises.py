"""Genera data/seed/paises.csv a partir del FMI DataMapper y la planilla WEO del cliente.

Uso:
    .venv/bin/python scripts/generar_paises.py

El CSV generado es la fuente de verdad y se versiona. Si ya existe, se respetan
los códigos internos asignados (clave: código DataMapper) y los países nuevos
reciben los números siguientes, en orden alfabético del nombre en español.

Fuentes:
- https://www.imf.org/external/datamapper/api/v1/{countries,regions,groups}
- docs/cliente/03 01 Plantilla 1- ... .ods, hojas "WEO_Data-GDP" (países) y
  "WEO_Data-mundo" (agregados): código numérico WEO y nombre en inglés.
"""

import csv
import gettext
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import httpx
import pycountry

RAIZ = Path(__file__).resolve().parent.parent
CSV_SALIDA = RAIZ / "data" / "seed" / "paises.csv"
PLANILLA = RAIZ / "docs" / "cliente" / "03 01 Plantilla 1- Extraccion datos WEO PBI USD Corrientes-2025 10.ods"
API = "https://www.imf.org/external/datamapper/api/v1"
COLUMNAS = ["codigo", "nombre", "nombre_en", "iso2", "iso3", "es_agregado", "fmi_dm", "fmi_weo", "bm"]

# Códigos del DataMapper que se omiten: sin nombre (ATI, ATL) o duplicados (KOS
# repite Kosovo; el FMI publica los datos bajo UVK).
OMITIR = {"ATI", "ATL", "KOS"}

# Nombres en español corregidos a mano (pycountry no traduce o usa la forma oficial larga).
NOMBRES_PAISES = {
    "BOL": "Bolivia", "BRN": "Brunéi", "BFA": "Burkina Faso", "BGD": "Bangladés",
    "CHI": "Islas del Canal", "CIV": "Costa de Marfil", "COG": "Congo, República del",
    "COD": "Congo, República Democrática del", "COM": "Comoras", "DZA": "Argelia",
    "FLK": "Islas Malvinas", "FSM": "Micronesia", "IMY": "Isla de Man", "IRN": "Irán",
    "KOR": "Corea del Sur", "PRK": "Corea del Norte", "LAO": "Laos", "MDA": "Moldavia",
    "MFX": "San Martín (Francia)", "SAU": "Arabia Saudita", "SUR": "Surinam", "SYR": "Siria",
    "TZA": "Tanzania", "TUN": "Túnez", "TWN": "Taiwán", "UVK": "Kosovo", "VAT": "Santa Sede",
    "VEN": "Venezuela", "VGB": "Islas Vírgenes Británicas",
    "VIR": "Islas Vírgenes de los Estados Unidos", "WBG": "Cisjordania y Gaza",
    "SXM": "San Martín (Países Bajos)", "BES": "Bonaire, San Eustaquio y Saba",
    "SHN": "Santa Elena", "MDV": "Maldivas", "BMU": "Bermudas", "HKG": "Hong Kong (RAE)",
    "MAC": "Macao (RAE)", "NER": "Níger", "BHS": "Bahamas", "GMB": "Gambia",
    "TLS": "Timor Oriental", "MMR": "Myanmar", "SWZ": "Esuatini", "RUS": "Rusia",
}

# Agregados (regiones y grupos): traducción a mano, clave código DataMapper.
# Donde el FMI repite el nombre en inglés se agrega el contexto entre paréntesis.
NOMBRES_AGREGADOS = {
    # /regions
    "AFQ": "África (región)", "AFRREO": "Perspectivas Económicas Regionales: África",
    "APQ": "Asia y el Pacífico", "AZQ": "Australia y Nueva Zelanda",
    "CAQ": "Asia Central y el Cáucaso", "CBQ": "Caribe", "CMQ": "Centroamérica",
    "EAQ": "Asia Oriental", "EEQ": "Europa del Este", "EUQ": "Europa (región)",
    "MEQ": "Oriente Medio (región)", "NAQ": "Norte de África", "NMQ": "América del Norte",
    "PIQ": "Islas del Pacífico", "SAQ": "Asia Meridional", "SEQ": "Sudeste Asiático",
    "SMQ": "América del Sur", "SSQ": "África Subsahariana (región)",
    "WEQ": "Europa Occidental", "WHQ": "Hemisferio Occidental (región)",
    "AFR_SSQ": "África Subsahariana (región, SPR)",
    "SPR_GD_MECA": "Oriente Medio y Asia Central (SPR)", "SPR_GD_EUR": "Europa (SPR)",
    "SPR_GD_AFR": "África (SPR)", "SPR_GD_CPI": "Caribe e Islas del Pacífico (SPR)",
    "SPR_GD_WHD": "Hemisferio Occidental (SPR)", "SPR_GD_Asia": "Asia (SPR)",
    # /groups
    "ADVEC": "Economías avanzadas",
    "AEEUEJ": "Economías avanzadas excl. EE.UU., zona euro y Japón",
    "AFR": "África (analítico)", "AS5": "ASEAN-5", "CEE": "Europa Central y del Este",
    "CEMAC": "CEMAC", "CFAFZ": "Zona del franco CFA",
    "CISM": "Comunidad de Estados Independientes y Mongolia",
    "COMESA": "COMESA (miembros de África Subsahariana)",
    "DA": "Economías emergentes y en desarrollo de Asia",
    "EAC": "Comunidad de África Oriental", "EAC-5": "Comunidad de África Oriental (5)",
    "EEF": "Exportadores de combustibles", "EENF": "Exportadores de no combustibles",
    "EU": "Unión Europea", "EUR": "Europa", "EURO": "Zona euro",
    "EUROAREA": "Zona euro (grupo alternativo)",
    "FLERRC": "Países sin tipo de cambio fijo convencional",
    "FRC": "Países en situación frágil y afectados por conflictos",
    "FXERRC": "Países con tipo de cambio fijo convencional",
    "LIC": "Países de ingreso bajo", "LL": "Países sin litoral",
    "MAE": "Principales economías avanzadas (G7)",
    "MAF": "Asia emergente excl. Japón incl. NIE",
    "MCA": "Economías emergentes y en desarrollo incl. algunas avanzadas",
    "MDRI": "Países de la MDRI", "ME": "Oriente Medio (analítico)",
    "MENA": "Oriente Medio y Norte de África", "MIC": "Países de ingreso medio",
    "MIC854": "Países de ingreso medio excl. Nigeria y Sudáfrica",
    "NO824": "No petroleros", "NONC872": "Costeros",
    "NONRESINT": "Países no intensivos en recursos", "OAE": "Otras economías avanzadas",
    "OEMDC": "Economías emergentes y en desarrollo", "OEXP": "Países exportadores de petróleo",
    "OIM808": "Países importadores de petróleo excl. Sudáfrica",
    "OIMP": "Países importadores de petróleo", "OTH": "Otros grupos",
    "OXEN853": "Países exportadores de petróleo excl. Nigeria",
    "PRGF": "Países elegibles para el SCLP (PRGF)",
    "RESINT": "Países intensivos en recursos", "SACU": "SACU", "SADC": "SADC",
    "SSA": "África Subsahariana", "WAEMU": "UEMAO",
    "WE": "América Latina y el Caribe", "WEOWORLD": "Mundo",
    "FAD_WORLD": "Mundo (Monitor Fiscal)", "FAD_G20": "G-20 (Monitor Fiscal)",
    "FAD_G20Adv": "G-20 avanzados (Monitor Fiscal)",
    "FAD_G20Emg": "G-20 emergentes (Monitor Fiscal)",
    "FAD_LIC": "Ingreso bajo (Monitor Fiscal)",
    "LICXF": "Países de ingreso bajo excl. los frágiles y afectados por conflictos",
    "SSENS": "África Subsahariana excl. Nigeria y Sudáfrica",
    "FM_EMG": "Economías emergentes y de ingreso medio (Monitor Fiscal)",
    "SSXZ": "África Subsahariana excl. Zimbabue",
    "SSXSD": "África Subsahariana excl. Sudán del Sur",
    "MENAP": "Oriente Medio, Norte de África, Afganistán y Pakistán",
    "ECOWAS": "Comunidad Económica de Estados de África Occidental",
    "BOPWORLD": "Mundo (balanza de pagos)", "IIO": "Organismos internacionales",
    "EDE": "Economías emergentes y en desarrollo de Europa",
    "FM_LIC": "Países de ingreso bajo (Monitor Fiscal)",
    "FM_AdvG20": "G-20 avanzados (Monitor Fiscal, FM)",
    "FM_EMEG20": "G-20 emergentes (Monitor Fiscal, FM)",
    "FM_EMEEU": "Europa emergente y de ingreso medio",
    "FM_EMEAsia": "Asia emergente y de ingreso medio",
    "FM_EMELA": "América Latina emergente y de ingreso medio",
    "FM_EMEME": "Oriente Medio, Norte de África y Pakistán emergentes y de ingreso medio",
    "FM_LICAsia": "Asia en desarrollo de ingreso bajo",
    "FM_LICLA": "América Latina en desarrollo de ingreso bajo",
    "FM_LICSSA": "África Subsahariana en desarrollo de ingreso bajo",
    "FM_LICO": "Otros países en desarrollo de ingreso bajo",
    "FM_LICOP": "Productores de petróleo en desarrollo de ingreso bajo",
    "FM_LIDC": "Países en desarrollo de ingreso bajo",
    "CIS": "Comunidad de Estados Independientes",
    "CFWORLD": "Mundo (Fiscal Monitor, CF)", "ARAWORLD": "Mundo (ARA)",
    "SPR_HIC": "Países de ingreso alto (mediana)",
    "SPR_LIDC": "Países en desarrollo de ingreso bajo (mediana)",
    "SPR_FLIDC": "Países en desarrollo de ingreso bajo de frontera (mediana)",
    "SPR_GD_AM": "Economías avanzadas (SPR)",
    "SPR_GD_LIDC": "Países en desarrollo de ingreso bajo (SPR)",
    "SPR_GD_EM": "Mercados emergentes (SPR)",
    "gbtier_1": "Presupuesto con perspectiva de género: países destacados",
    "gbtier_2": "Presupuesto con perspectiva de género: otros países relevados",
    "gbcasestudy": "Presupuesto con perspectiva de género: países en encuestas regionales",
    "gb_othersource": "Presupuesto con perspectiva de género: otros países",
    "GDWORLD": "Mundo (Deuda Global)", "ECCU": "Unión Monetaria del Caribe Oriental",
    "FAD_C1": "Categoría I (Monitor Fiscal)", "FAD_NG20": "No G-20 (Monitor Fiscal)",
    "FAD_C2": "Categoría II (Monitor Fiscal)",
    "FAD_OP": "Productores de petróleo (Monitor Fiscal)",
    "FAD_NOHIC": "No petroleros de ingreso alto", "FAD_NOMIC": "No petroleros de ingreso medio",
    "FAD_NOLIC": "No petroleros de ingreso bajo", "FAD_C3": "Categoría III (Monitor Fiscal)",
    "FAD_NOFAST": "No petroleros de crecimiento rápido",
    "FAD_NOMED": "No petroleros de crecimiento medio",
    "FAD_NOSLOW": "No petroleros de crecimiento lento",
    "FAD_C4": "Categoría IV (Monitor Fiscal)", "FAD_G7": "G-7 (Monitor Fiscal)",
    "FAD_NG7": "No G-7 (Monitor Fiscal)", "FAD_C5": "Categoría V (Monitor Fiscal)",
    "FAD_EuroArea": "Zona euro (Monitor Fiscal)", "FAD_EMAsia": "Asia emergente (Monitor Fiscal)",
    "FAD_OtherAdv": "Otras avanzadas (Monitor Fiscal)", "FAD_Rest": "Resto (Monitor Fiscal)",
    "FAD_C6": "Categoría VI (Monitor Fiscal)",
    "FAD_WHD": "Grupo Hemisferio Occidental (Monitor Fiscal)",
    "FAD_MCD": "Grupo Oriente Medio y Asia Central (Monitor Fiscal)",
    "FAD_APD": "Grupo Asia y Pacífico (Monitor Fiscal)",
    "FAD_AFR": "Grupo África (Monitor Fiscal)", "FAD_EUR": "Grupo Europa (Monitor Fiscal)",
    "FAD_ADV": "Economías avanzadas (Monitor Fiscal)",
    "FAD_EME": "Mercados emergentes (Monitor Fiscal)",
    "FAD_EMD": "Países emergentes y en desarrollo (Monitor Fiscal)",
    "FADGDWORLD": "Todos los países (Deuda Global)",
    "MECA": "Oriente Medio y Asia Central", "CCWORLD": "Mundo (CC)",
    "FR_FCWORLD": "Todos los países (reglas y consejos fiscales)",
    "FR_FC_ADV": "Economías avanzadas (reglas y consejos fiscales)",
    "FR_FC_EME": "Economías emergentes y en desarrollo (reglas y consejos fiscales)",
    "FR_FC_EU": "Unión Europea (reglas y consejos fiscales)",
    "FR_FC_NonEU": "No Unión Europea (reglas y consejos fiscales)",
    "EME": "Economías de mercados emergentes",
}

# Códigos WEO de agregados (hoja "WEO_Data-mundo"), por código DataMapper.
WEO_AGREGADOS = {
    "WEOWORLD": "1", "ADVEC": "110", "EURO": "163", "MAE": "119", "OAE": "123",
    "EU": "998", "AS5": "510", "OEMDC": "200", "DA": "505", "EDE": "903",
    "WE": "205", "MECA": "400", "SSA": "603",
}

# Códigos del Banco Mundial que no son el ISO3 (o agregados equivalentes), por código DataMapper.
# Los demás países usan el ISO3. Los agregados del BM sin equivalente en el FMI no se mapean.
BM_CODIGOS = {
    "WBG": "PSE", "IMY": "IMN", "CHI": "CHI", "MFX": "MAF", "UVK": "XKX",
    "WEOWORLD": "WLD", "EURO": "EMU", "EU": "EUU",
}

# Nombres en inglés que difieren entre la planilla y el DataMapper.
WEO_AJUSTES = {"CHN": "China", "NRU": "Nauru"}

T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"


def normalizar(texto: str) -> str:
    return " ".join(texto.split()).casefold()


def clave_orden(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.casefold()


def leer_hoja_ods(ruta: Path, hoja: str) -> list[list[str]]:
    """Devuelve las filas de una hoja de un .ods como listas de texto."""
    with zipfile.ZipFile(ruta) as z:
        raiz = ET.fromstring(z.read("content.xml"))
    for tabla in raiz.iter(T + "table"):
        if tabla.get(T + "name") == hoja:
            filas = []
            for fila in tabla.iter(T + "table-row"):
                celdas = []
                for celda in fila.findall(T + "table-cell")[:3]:
                    celdas.append("".join(celda.itertext()).strip())
                filas.append(celdas)
            return filas
    raise ValueError(f"No existe la hoja {hoja!r} en {ruta}")


def codigos_weo_paises() -> dict[str, str]:
    """Nombre en inglés normalizado -> código WEO, desde la hoja WEO_Data-GDP."""
    resultado = {}
    for fila in leer_hoja_ods(PLANILLA, "WEO_Data-GDP"):
        if len(fila) >= 2 and fila[0].isdigit() and fila[0] != "0":
            resultado[normalizar(fila[1])] = fila[0]
    return resultado


def descargar(endpoint: str) -> dict:
    respuesta = httpx.get(f"{API}/{endpoint}", timeout=60)
    respuesta.raise_for_status()
    return respuesta.json()[endpoint]


def nombre_es_pais(codigo: str, nombre_en: str) -> tuple[str, str, str]:
    """Devuelve (nombre en español, iso2, iso3)."""
    pais = pycountry.countries.get(alpha_3=codigo)
    if codigo in NOMBRES_PAISES:
        nombre = NOMBRES_PAISES[codigo]
    elif pais:
        es = gettext.translation("iso3166-1", pycountry.LOCALES_DIR, languages=["es"])
        nombre = es.gettext(pais.name)
    else:
        raise ValueError(f"Falta traducción para {codigo} ({nombre_en})")
    if pais:
        return nombre, pais.alpha_2, pais.alpha_3
    return nombre, "", ""


def generar() -> list[dict]:
    weo = codigos_weo_paises()
    filas = []
    for codigo, datos in descargar("countries").items():
        if codigo in OMITIR:
            continue
        nombre_en = " ".join((datos["label"] or "").split())
        nombre, iso2, iso3 = nombre_es_pais(codigo, nombre_en)
        clave_weo = normalizar(WEO_AJUSTES.get(codigo, nombre_en))
        filas.append({
            "nombre": nombre, "nombre_en": nombre_en, "iso2": iso2, "iso3": iso3,
            "es_agregado": "0", "fmi_dm": codigo, "fmi_weo": weo.pop(clave_weo, ""),
            "bm": BM_CODIGOS.get(codigo, iso3),
        })
    for endpoint in ("regions", "groups"):
        for codigo, datos in descargar(endpoint).items():
            if codigo not in NOMBRES_AGREGADOS:
                raise ValueError(f"Falta traducción para el agregado {codigo} ({datos['label']})")
            filas.append({
                "nombre": NOMBRES_AGREGADOS[codigo],
                "nombre_en": " ".join((datos["label"] or "").split()),
                "iso2": "", "iso3": "", "es_agregado": "1", "fmi_dm": codigo,
                "fmi_weo": WEO_AGREGADOS.get(codigo, ""), "bm": BM_CODIGOS.get(codigo, ""),
            })
    if weo:
        print("Aviso: códigos WEO de la planilla sin país asociado:", weo, file=sys.stderr)
    return filas


def asignar_codigos(filas: list[dict], existentes: dict[str, str]) -> list[dict]:
    """Respeta los códigos ya asignados; los nuevos van al final en orden alfabético."""
    siguiente = max((int(c) for c in existentes.values()), default=0) + 1
    for fila in sorted(filas, key=lambda f: (clave_orden(f["nombre"]), f["fmi_dm"])):
        if fila["fmi_dm"] in existentes:
            fila["codigo"] = existentes[fila["fmi_dm"]]
        else:
            fila["codigo"] = f"{siguiente:03d}"
            siguiente += 1
    return sorted(filas, key=lambda f: f["codigo"])


def main() -> None:
    existentes, bm_existentes = {}, {}
    if CSV_SALIDA.exists():
        with CSV_SALIDA.open(encoding="utf-8") as f:
            anteriores = list(csv.DictReader(f))
        existentes = {fila["fmi_dm"]: fila["codigo"] for fila in anteriores}
        # El código del BM se revisó a mano contra la API del BM: se conserva el que ya estaba.
        bm_existentes = {fila["fmi_dm"]: fila.get("bm", "") for fila in anteriores if "bm" in fila}
    filas = generar()
    for fila in filas:
        if fila["fmi_dm"] in bm_existentes:
            fila["bm"] = bm_existentes[fila["fmi_dm"]]
    filas = asignar_codigos(filas, existentes)
    CSV_SALIDA.parent.mkdir(parents=True, exist_ok=True)
    with CSV_SALIDA.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS)
        escritor.writeheader()
        escritor.writerows(filas)
    print(f"{len(filas)} filas escritas en {CSV_SALIDA}")


if __name__ == "__main__":
    main()
