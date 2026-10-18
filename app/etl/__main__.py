"""CLI de carga de datos.

    python -m app.etl semillas
    python -m app.etl fmi [--indicadores NGDPD,NGDP_RPCH]
    python -m app.etl bm [--indicadores NY.GDP.MKTP.CD,SP.POP.TOTL]
    python -m app.etl todo        # semillas + fmi + bm
"""

import argparse
import logging
import sys

from app.db import SessionLocal
from app.etl import banco_mundial, fmi
from app.etl.semillas import cargar_semillas


def _codigos(texto: str | None) -> list[str] | None:
    return [c.strip() for c in texto.split(",") if c.strip()] if texto else None


def _cargar(modulo, cargador, sesion, codigos) -> None:
    with modulo.crear_cliente() as cliente:
        for codigo, cantidad in cargador(sesion, cliente, codigos).items():
            print(f"{codigo}: {cantidad} valores")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.etl", description="Carga de datos económicos.")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("semillas", help="Carga países, fuentes e indicadores desde data/seed/")
    p_fmi = sub.add_parser("fmi", help="Descarga indicadores del FMI DataMapper")
    p_fmi.add_argument("--indicadores", help="Códigos del FMI separados por coma (por defecto, todos los definidos)")
    p_bm = sub.add_parser("bm", help="Descarga indicadores del Banco Mundial")
    p_bm.add_argument("--indicadores", help="Códigos del BM separados por coma (por defecto, todos los definidos)")
    sub.add_parser("todo", help="Carga las semillas y todos los indicadores del FMI y del Banco Mundial")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with SessionLocal() as sesion:
        try:
            if args.comando in ("semillas", "todo"):
                for tabla, cantidad in cargar_semillas(sesion).items():
                    print(f"{tabla}: {cantidad}")
            if args.comando in ("fmi", "todo"):
                _cargar(fmi, fmi.cargar_fmi, sesion, _codigos(getattr(args, "indicadores", None)))
            if args.comando in ("bm", "todo"):
                _cargar(banco_mundial, banco_mundial.cargar_bm, sesion, _codigos(getattr(args, "indicadores", None)))
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
