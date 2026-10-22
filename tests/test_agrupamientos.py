import csv

import pytest

from app.analisis.agrupamientos import (
    PROMEDIO_PONDERADO_PBI,
    REGLAS,
    SUMA,
    ErrorAgregado,
    agregar,
)
from app.etl.semillas import DIR_SEMILLAS


def test_suma_de_los_miembros():
    r = agregar(SUMA, {"A": {2000: 1.0, 2001: 2.0}, "B": {2000: 10.0, 2001: 20.0}})
    assert r.valores == {2000: 11.0, 2001: 22.0}
    assert r.miembros == ["A", "B"] and r.fuera == [] and r.faltan == {}


def test_anio_incompleto_queda_sin_valor_y_dice_quien_falta():
    r = agregar(SUMA, {"A": {2000: 1.0, 2001: 2.0, 2002: 3.0}, "B": {2000: 10.0, 2001: None}, "C": {2000: 5.0, 2002: 1.0}})
    # 2001: B tiene None y C no tiene el año; 2002: falta B. No se suma lo que hay.
    assert r.valores == {2000: 16.0, 2001: None, 2002: None}
    assert r.faltan == {2001: ["B", "C"], 2002: ["B"]}


def test_miembro_sin_ningun_dato_queda_fuera_y_se_informa():
    r = agregar(SUMA, {"A": {2000: 1.0}, "B": {}, "C": {2000: None, 2001: None}, "D": {2000: 2.0}})
    assert r.valores == {2000: 3.0}
    assert r.miembros == ["A", "D"] and r.fuera == ["B", "C"]


def test_ningun_miembro_con_datos():
    r = agregar(SUMA, {"A": {}, "B": {2000: None}})
    assert r.valores == {} and r.miembros == [] and r.fuera == ["A", "B"]


def test_promedio_ponderado_por_el_pbi():
    valores = {"A": {2000: 10.0, 2001: 20.0}, "B": {2000: 40.0, 2001: -4.0}}
    pesos = {"A": {2000: 300.0, 2001: 100.0}, "B": {2000: 100.0, 2001: 100.0}}
    r = agregar(PROMEDIO_PONDERADO_PBI, valores, pesos)
    assert r.valores[2000] == pytest.approx((10 * 300 + 40 * 100) / 400)
    assert r.valores[2001] == pytest.approx(8.0)


def test_promedio_ponderado_sin_el_peso_de_un_miembro_queda_sin_valor():
    valores = {"A": {2000: 10.0, 2001: 20.0}, "B": {2000: 40.0, 2001: 30.0}}
    pesos = {"A": {2000: 1.0, 2001: 1.0}, "B": {2000: 1.0, 2001: None}}
    r = agregar(PROMEDIO_PONDERADO_PBI, valores, pesos)
    assert r.valores == {2000: 25.0, 2001: None}
    # B tiene el dato de 2001 pero no su PBI: se informa aparte.
    assert r.faltan == {} and r.faltan_pbi == {2001: ["B"]}


def test_promedio_ponderado_distingue_sin_dato_de_sin_pbi():
    valores = {"A": {2000: 10.0}, "B": {2000: 40.0}, "C": {2001: 1.0}}
    pesos = {"A": {2000: 1.0}, "B": {}, "C": {2001: 1.0}}
    r = agregar(PROMEDIO_PONDERADO_PBI, valores, pesos)
    assert r.valores == {2000: None, 2001: None}
    assert r.faltan == {2000: ["C"], 2001: ["A", "B"]}
    assert r.faltan_pbi == {2000: ["B"]}


def test_promedio_ponderado_sin_pesos_da_error():
    with pytest.raises(ErrorAgregado, match="PBI"):
        agregar(PROMEDIO_PONDERADO_PBI, {"A": {2000: 1.0}})


def test_metodo_desconocido():
    with pytest.raises(ErrorAgregado, match="desconocido"):
        agregar("mediana", {"A": {2000: 1.0}})


def test_anios_ordenados():
    r = agregar(SUMA, {"A": {2010: 1.0, 1990: 2.0}, "B": {2000: 3.0, 2010: 1.0, 1990: 1.0}})
    assert list(r.valores) == [1990, 2000, 2010]


def test_todos_los_indicadores_internacionales_anuales_tienen_regla():
    with (DIR_SEMILLAS / "indicadores.csv").open(encoding="utf-8") as f:
        internacionales = {
            fila["codigo"] for fila in csv.DictReader(f) if (fila["alcance"], fila["frecuencia"]) == ("internacional", "anual")
        }
    assert internacionales == set(REGLAS)
    # Niveles: suma. Porcentajes del PBI y tasas: promedio ponderado.
    assert {c for c, r in REGLAS.items() if r == SUMA} == {"PBI_USD_CORR", "POBLACION", "EXPORTACIONES_USD", "IMPORTACIONES_USD"}


# --- Casos límite agregados por el tester ---


def test_promedio_ponderado_con_peso_total_cero_queda_sin_valor():
    r = agregar(PROMEDIO_PONDERADO_PBI, {"A": {2000: 10.0}, "B": {2000: 20.0}}, {"A": {2000: 0.0}, "B": {2000: 0.0}})
    assert r.valores == {2000: None}


def test_promedio_ponderado_sin_la_clave_del_miembro_en_los_pesos():
    # Un miembro que no aparece en `pesos` se trata como sin PBI, no explota.
    r = agregar(PROMEDIO_PONDERADO_PBI, {"A": {2000: 10.0}, "B": {2000: 20.0}}, {"A": {2000: 1.0}})
    assert r.valores == {2000: None} and r.faltan_pbi == {2000: ["B"]}


def test_suma_con_ceros_y_negativos_no_se_confunde_con_falta():
    r = agregar(SUMA, {"A": {2000: 0.0}, "B": {2000: -5.0}})
    assert r.valores == {2000: -5.0} and r.faltan == {}


def test_suma_de_un_solo_miembro_es_su_serie():
    r = agregar(SUMA, {"A": {2000: 1.5, 2001: None, 2002: 3.0}})
    assert r.valores == {2000: 1.5, 2002: 3.0} and r.miembros == ["A"]


def test_promedio_ponderado_no_usa_pesos_de_miembros_fuera():
    # C no tiene ningún dato del indicador: queda fuera aunque tenga PBI, y su PBI no entra en el total.
    valores = {"A": {2000: 10.0}, "B": {2000: 30.0}, "C": {}}
    pesos = {"A": {2000: 1.0}, "B": {2000: 1.0}, "C": {2000: 1000.0}}
    r = agregar(PROMEDIO_PONDERADO_PBI, valores, pesos)
    assert r.valores == {2000: pytest.approx(20.0)} and r.fuera == ["C"]
