"""CLI de carga de datos.

    python -m app.etl semillas
    python -m app.etl fmi [--indicadores NGDPD,NGDP_RPCH]
"""

import argparse
import logging
import sys

from app.db import SessionLocal
from app.etl.fmi import cargar_fmi, crear_cliente
from app.etl.semillas import cargar_semillas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.etl", description="Carga de datos económicos.")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("semillas", help="Carga países, fuentes e indicadores desde data/seed/")
    fmi = sub.add_parser("fmi", help="Descarga indicadores del FMI DataMapper")
    fmi.add_argument("--indicadores", help="Códigos del FMI separados por coma (por defecto, todos los definidos)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with SessionLocal() as sesion:
        try:
            if args.comando == "semillas":
                for tabla, cantidad in cargar_semillas(sesion).items():
                    print(f"{tabla}: {cantidad}")
            else:
                codigos = [c.strip() for c in args.indicadores.split(",") if c.strip()] if args.indicadores else None
                with crear_cliente() as cliente:
                    for codigo, cantidad in cargar_fmi(sesion, cliente, codigos).items():
                        print(f"{codigo}: {cantidad} valores")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
