"""CLI de carga de datos.

    python -m app.etl semillas
    python -m app.etl fmi [--indicadores NGDPD,NGDP_RPCH]
    python -m app.etl bm [--indicadores NY.GDP.MKTP.CD,SP.POP.TOTL]
    python -m app.etl ine [--indicadores IPC_GENERAL,ECH0013]
    python -m app.etl bcu [--indicadores 2225] [--desde 2000-01-01]
    python -m app.etl todo        # semillas + fmi + bm + ine + bcu
"""

import argparse
import logging
import sys
from datetime import date

import httpx

from app.db import SessionLocal
from app.etl import banco_mundial, bcu, fmi, ine
from app.etl.semillas import cargar_semillas


def _codigos(texto: str | None) -> list[str] | None:
    return [c.strip() for c in texto.split(",") if c.strip()] if texto else None


def _cargar(modulo, cargador, sesion, codigos, **opciones) -> None:
    with modulo.crear_cliente() as cliente:
        for codigo, cantidad in cargador(sesion, cliente, codigos, **opciones).items():
            print(f"{codigo}: {cantidad} valores")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.etl", description="Carga de datos económicos.")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("semillas", help="Carga países, fuentes e indicadores desde data/seed/")
    p_fmi = sub.add_parser("fmi", help="Descarga indicadores del FMI DataMapper")
    p_fmi.add_argument("--indicadores", help="Códigos del FMI separados por coma (por defecto, todos los definidos)")
    p_bm = sub.add_parser("bm", help="Descarga indicadores del Banco Mundial")
    p_bm.add_argument("--indicadores", help="Códigos del BM separados por coma (por defecto, todos los definidos)")
    p_ine = sub.add_parser("ine", help="Descarga las planillas del INE (IPC, desempleo)")
    p_ine.add_argument("--indicadores", help="Códigos del INE separados por coma (por defecto, todos los definidos)")
    p_bcu = sub.add_parser("bcu", help="Descarga cotizaciones del BCU (dólar interbancario)")
    p_bcu.add_argument("--indicadores", help="Códigos de moneda del BCU separados por coma (por defecto, todos los definidos)")
    p_bcu.add_argument(
        "--desde", type=date.fromisoformat,
        help="Primera fecha (AAAA-MM-DD). Por defecto retoma desde la última cotización guardada, o desde 2000",
    )
    sub.add_parser("todo", help="Carga las semillas y todos los indicadores (FMI, Banco Mundial, INE y BCU)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    codigos = _codigos(getattr(args, "indicadores", None))
    # (comando, nombre para el informe, función que carga). En `todo` se corren todos.
    pasos = [
        ("semillas", "Semillas", lambda s: [print(f"{t}: {c}") for t, c in cargar_semillas(s).items()]),
        ("fmi", "FMI", lambda s: _cargar(fmi, fmi.cargar_fmi, s, codigos)),
        ("bm", "Banco Mundial", lambda s: _cargar(banco_mundial, banco_mundial.cargar_bm, s, codigos)),
        ("ine", "INE", lambda s: _cargar(ine, ine.cargar_ine, s, codigos)),
        ("bcu", "BCU", lambda s: _cargar(bcu, bcu.cargar_bcu, s, codigos, desde=getattr(args, "desde", None))),
    ]
    fallaron, cargadas = [], []
    with SessionLocal() as sesion:
        for comando, nombre, cargar in pasos:
            if args.comando not in (comando, "todo"):
                continue
            try:
                cargar(sesion)
                if comando != "semillas":
                    cargadas.append(nombre)
            except (ValueError, httpx.HTTPError) as e:
                sesion.rollback()
                print(f"Error ({nombre}): {e}", file=sys.stderr)
                fallaron.append(nombre)
                # Sin semillas no tiene sentido seguir; en `todo`, el fallo de una fuente no frena las demás.
                if comando == "semillas":
                    break
    if fallaron:
        if args.comando == "todo":
            print(resumen_todo(fallaron, cargadas), file=sys.stderr)
        return 1
    return 0


def resumen_todo(fallaron: list[str], cargadas: list[str]) -> str:
    """Resumen final de `todo` cuando algo falló, con los nombres concretos de cada fuente."""
    if "Semillas" in fallaron:
        return "Fallaron las semillas: no se cargó ninguna fuente."
    texto = f"Fallaron: {', '.join(fallaron)}."
    return f"{texto} Se cargaron: {', '.join(cargadas)}." if cargadas else f"{texto} No se cargó ninguna fuente."

if __name__ == "__main__":
    sys.exit(main())
