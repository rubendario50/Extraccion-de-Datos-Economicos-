import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.models import DatoInternacionalAnual, Fuente, Indicador, Pais, PaisCodigoExterno

TABLAS = {
    "pais", "pais_codigo_externo", "fuente", "indicador", "indicador_serie_externa",
    "dato_internacional_anual", "dato_internacional_mensual",
    "dato_nacional_anual", "dato_nacional_mensual", "cotizacion_diaria",
}


def test_se_crean_todas_las_tablas(sesion):
    assert TABLAS <= set(inspect(sesion.get_bind()).get_table_names())


def test_claves_de_las_tablas_de_valores(sesion):
    insp = inspect(sesion.get_bind())
    assert insp.get_pk_constraint("dato_internacional_anual")["constrained_columns"] == [
        "pais_id", "indicador_id", "fuente_id", "anio"]
    assert insp.get_pk_constraint("dato_internacional_mensual")["constrained_columns"] == [
        "pais_id", "indicador_id", "fuente_id", "periodo"]
    assert insp.get_pk_constraint("dato_nacional_anual")["constrained_columns"] == [
        "indicador_id", "fuente_id", "anio"]
    assert insp.get_pk_constraint("dato_nacional_mensual")["constrained_columns"] == [
        "indicador_id", "fuente_id", "periodo"]
    assert insp.get_pk_constraint("cotizacion_diaria")["constrained_columns"] == [
        "indicador_id", "fuente_id", "fecha"]


def test_relacion_pais_codigos_externos(sesion):
    pais = Pais(codigo="001", nombre="Uruguay", nombre_en="Uruguay", iso2="UY", iso3="URY")
    pais.codigos_externos.append(PaisCodigoExterno(organismo="FMI_WEO", codigo="298"))
    sesion.add(pais)
    sesion.commit()
    assert sesion.scalar(select(PaisCodigoExterno.codigo).where(PaisCodigoExterno.pais_id == pais.id)) == "298"


def test_codigo_externo_unico_por_organismo(sesion):
    a = Pais(codigo="001", nombre="A", nombre_en="A")
    b = Pais(codigo="002", nombre="B", nombre_en="B")
    a.codigos_externos.append(PaisCodigoExterno(organismo="ISO3", codigo="AAA"))
    b.codigos_externos.append(PaisCodigoExterno(organismo="ISO3", codigo="AAA"))
    sesion.add_all([a, b])
    with pytest.raises(IntegrityError):
        sesion.commit()


def test_dato_guarda_fecha_de_actualizacion(sesion):
    pais = Pais(codigo="001", nombre="A", nombre_en="A")
    ind = Indicador(codigo="X", nombre="X", unidad="u", alcance="internacional", frecuencia="anual")
    fte = Fuente(codigo="F", nombre="F")
    sesion.add_all([pais, ind, fte])
    sesion.flush()
    sesion.add(DatoInternacionalAnual(pais_id=pais.id, indicador_id=ind.id, fuente_id=fte.id, anio=2000, valor=1.5))
    sesion.commit()
    dato = sesion.scalar(select(DatoInternacionalAnual))
    assert dato.valor == 1.5 and dato.actualizado_en is not None


def test_migracion_alembic_crea_las_tablas(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path / 'migracion.sqlite'}"
    from pathlib import Path

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    assert TABLAS <= set(inspect(engine).get_table_names())
    command.downgrade(config, "base")
    assert not TABLAS & set(inspect(engine).get_table_names())
    engine.dispose()
