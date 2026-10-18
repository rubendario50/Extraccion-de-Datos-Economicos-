"""Asignación de códigos internos del script scripts/generar_paises.py."""

import importlib.util
from pathlib import Path

RUTA = Path(__file__).resolve().parents[1] / "scripts" / "generar_paises.py"
spec = importlib.util.spec_from_file_location("generar_paises", RUTA)
generar_paises = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generar_paises)


def fila(nombre, dm):
    return {"nombre": nombre, "fmi_dm": dm}


def test_primera_vez_en_orden_alfabetico_espanol():
    filas = generar_paises.asignar_codigos([fila("Uruguay", "URY"), fila("Álbania", "ALB"), fila("Brasil", "BRA")], {})
    assert [(f["codigo"], f["fmi_dm"]) for f in filas] == [("001", "ALB"), ("002", "BRA"), ("003", "URY")]


def test_respeta_codigos_existentes_y_agrega_al_final():
    existentes = {"URY": "001", "BRA": "002"}
    filas = generar_paises.asignar_codigos(
        [fila("Uruguay", "URY"), fila("Brasil", "BRA"), fila("Argentina", "ARG"), fila("Zambia", "ZMB")], existentes
    )
    assert {f["fmi_dm"]: f["codigo"] for f in filas} == {"URY": "001", "BRA": "002", "ARG": "003", "ZMB": "004"}
