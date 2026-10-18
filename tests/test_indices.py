import pytest

from app.analisis.indices import ErrorIndice, a_base_100, a_base_100_promedio


def test_convierte_a_base_100():
    resultado = a_base_100({2009: 50.0, 2010: 200.0, 2011: 300.0}, 2010)
    assert resultado == {2009: 25.0, 2010: 100.0, 2011: 150.0}


def test_mantiene_valores_faltantes():
    assert a_base_100({2010: 4.0, 2011: None}, 2010) == {2010: 100.0, 2011: None}


def test_valores_negativos():
    assert a_base_100({2010: -2.0, 2011: -1.0}, 2010) == {2010: 100.0, 2011: 50.0}


def test_anio_base_faltante():
    with pytest.raises(ErrorIndice, match="2015"):
        a_base_100({2010: 1.0}, 2015)


def test_anio_base_con_valor_nulo():
    with pytest.raises(ErrorIndice, match="No hay dato"):
        a_base_100({2010: None, 2011: 1.0}, 2010)


def test_anio_base_con_valor_cero():
    with pytest.raises(ErrorIndice, match="es 0"):
        a_base_100({2010: 0.0, 2011: 1.0}, 2010)


# --- Series mensuales o diarias: el promedio del año base vale 100 ---

def test_base_100_promedio_del_anio():
    from datetime import date

    serie = {date(2009, 12, 1): 45.0, date(2010, 1, 1): 40.0, date(2010, 2, 1): 60.0, date(2011, 1, 1): None}
    resultado = a_base_100_promedio(serie, 2010)  # promedio de 2010: 50
    assert resultado == {date(2009, 12, 1): 90.0, date(2010, 1, 1): 80.0, date(2010, 2, 1): 120.0, date(2011, 1, 1): None}


def test_base_100_promedio_sin_datos_en_el_anio():
    from datetime import date

    with pytest.raises(ErrorIndice, match="año base 2015"):
        a_base_100_promedio({date(2010, 1, 1): 1.0, date(2015, 3, 1): None}, 2015)


def test_base_100_promedio_cero():
    from datetime import date

    with pytest.raises(ErrorIndice, match="es 0"):
        a_base_100_promedio({date(2010, 1, 1): 1.0, date(2010, 2, 1): -1.0}, 2010)
