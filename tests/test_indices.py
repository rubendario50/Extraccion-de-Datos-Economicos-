import pytest

from app.analisis.indices import ErrorIndice, a_base_100


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
