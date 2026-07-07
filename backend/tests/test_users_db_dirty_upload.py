"""
Regresión del incidente ur7zf7 (2026-07-07): el upload de users.duckdb en el
shutdown graceful (main.py lifespan) era INCONDICIONAL — cualquier contenedor
duplicado/stale que muriera con gracia pisaba GCS con su copia de arranque
(modelo último-que-sube-gana), perdiendo las escrituras de usuario del día.

Contrato nuevo:
- upload_user_db(only_if_dirty=True) [shutdown] solo sube si hubo escrituras
  locales pendientes (mark_user_db_dirty() o un upload de write-path fallido).
- upload_user_db() [write-path] sube siempre y limpia el flag al tener éxito.
- Un upload fallido deja el flag puesto para que el shutdown lo reintente.
"""
import pytest

import app.gcs_sync as gcs_sync


class _FakeBlob:
    def __init__(self, calls):
        self._calls = calls

    def upload_from_filename(self, path, timeout=None):
        self._calls.append(path)


class _FakeBucket:
    def __init__(self, calls):
        self._calls = calls

    def blob(self, name):
        return _FakeBlob(self._calls)


class _FakeClient:
    def __init__(self, calls):
        self._calls = calls

    def bucket(self, name):
        return _FakeBucket(self._calls)


@pytest.fixture()
def gcs_env(tmp_path, monkeypatch):
    """users.duckdb real (el upload hace FORCE CHECKPOINT) + cliente GCS falso.

    Devuelve la lista de paths subidos por el cliente falso.
    """
    monkeypatch.chdir(tmp_path)
    import duckdb

    con = duckdb.connect(str(tmp_path / "users.duckdb"))
    con.execute("CREATE TABLE t (x INTEGER)")
    con.close()

    monkeypatch.setenv("DB_PROVIDER", "gcs")
    monkeypatch.delenv("DISABLE_GCS_SYNC", raising=False)
    calls = []
    monkeypatch.setattr(gcs_sync, "_get_cached_client", lambda: _FakeClient(calls))
    monkeypatch.setattr(gcs_sync, "_startup_download_ok", True)
    monkeypatch.setattr(gcs_sync, "_dirty_since_upload", False)
    return calls


def test_shutdown_skips_upload_when_clean(gcs_env):
    assert gcs_sync.upload_user_db(only_if_dirty=True) is False
    assert gcs_env == []


def test_shutdown_uploads_after_marked_dirty(gcs_env):
    gcs_sync.mark_user_db_dirty()
    assert gcs_sync.upload_user_db(only_if_dirty=True) is True
    assert gcs_env == ["users.duckdb"]
    # El éxito limpia el flag: el siguiente shutdown no vuelve a subir.
    assert gcs_sync.upload_user_db(only_if_dirty=True) is False
    assert gcs_env == ["users.duckdb"]


def test_write_path_upload_always_uploads_and_clears_flag(gcs_env):
    assert gcs_sync.upload_user_db() is True
    assert gcs_env == ["users.duckdb"]
    assert gcs_sync.upload_user_db(only_if_dirty=True) is False


def test_failed_upload_leaves_flag_for_shutdown_retry(gcs_env, monkeypatch):
    class _Boom:
        def bucket(self, name):
            raise RuntimeError("gcs down")

    monkeypatch.setattr(gcs_sync, "_get_cached_client", lambda: _Boom())
    assert gcs_sync.upload_user_db() is False
    assert gcs_sync._dirty_since_upload is True
