from app.config import Settings, get_settings


def test_los_tests_no_leen_el_env_de_la_pc(tmp_path, monkeypatch):
    """La suite usa sus propios valores aunque el .env local tenga otros (por ejemplo un BASE_URL de un túnel)."""
    (tmp_path / ".env").write_text("BASE_URL=https://tunel.example\nGOOGLE_CLIENT_ID=real\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BASE_URL")
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    assert Settings().base_url == "http://localhost:8000"
    assert Settings().google_client_id == ""
    assert get_settings().base_url == "http://localhost:8000"


def test_fuera_de_los_tests_el_env_se_sigue_leyendo(tmp_path, monkeypatch):
    archivo = tmp_path / ".env"
    archivo.write_text("BASE_URL=https://tunel.example\n", encoding="utf-8")
    monkeypatch.delenv("BASE_URL")
    assert Settings(_env_file=archivo).base_url == "https://tunel.example"
