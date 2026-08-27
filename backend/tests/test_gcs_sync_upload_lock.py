"""La subida de users.duckdb a GCS no puede retener el lock de la DB.

Regresion de produccion (2026-08-26): upload_user_db envolvia la transferencia de
red en `with get_user_db_lock()`, con 3 intentos de 5 s + esperas de 2 s. Cada
guardado de estrategia programaba una subida, y el POST siguiente —guardar el
backtest— se quedaba esperando ese lock. El cliente aborta a los 20 s, el error se
tragaba en un console.warn, y la estrategia acababa en el Baul sin metricas.

El lock es un RLock, asi que sondearlo desde ESTE hilo daria siempre verde aunque
estuviese retenido. Por eso el sondeo va desde otro hilo.
"""
import os
import threading

import pytest

from app import gcs_sync
from app.database import get_user_db_lock


def _lock_free_from_another_thread(timeout=5.0):
    """True si otro hilo puede coger el lock de la DB ahora mismo."""
    result = {}

    def probe():
        lock = get_user_db_lock()
        acquired = lock.acquire(blocking=False)
        result["free"] = acquired
        if acquired:
            lock.release()

    t = threading.Thread(target=probe)
    t.start()
    t.join(timeout)
    return result.get("free", False)


class _FakeBlob:
    def __init__(self, observed):
        self._observed = observed

    def upload_from_filename(self, filename, timeout=None):
        # El momento clave: mientras "viaja" el fichero, nadie debe estar bloqueado.
        self._observed["lock_free_during_upload"] = _lock_free_from_another_thread()
        self._observed["uploaded_path"] = filename
        self._observed["timeout"] = timeout


class _FakeBucket:
    def __init__(self, observed):
        self._observed = observed

    def blob(self, _name):
        return _FakeBlob(self._observed)


class _FakeClient:
    def __init__(self, observed):
        self._observed = observed

    def bucket(self, _name):
        return _FakeBucket(self._observed)


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    """users.duckdb local por encima del umbral de los 50 KB."""
    path = tmp_path / "users.duckdb"
    path.write_bytes(b"\0" * 60_000)
    monkeypatch.setattr("app.database.user_db_path", lambda: str(path))
    monkeypatch.setenv("DB_PROVIDER", "gcs")
    monkeypatch.setenv("DISABLE_GCS_SYNC", "false")
    return path


def test_db_lock_is_free_while_uploading(db_file, monkeypatch):
    observed = {}
    monkeypatch.setattr(gcs_sync, "_get_cached_client", lambda: _FakeClient(observed))

    assert gcs_sync.upload_user_db() is True
    assert observed["lock_free_during_upload"] is True, (
        "el lock de la DB seguia retenido durante la subida: los guardados que "
        "lleguen detras se atascaran igual que en la incidencia original"
    )


def test_uploads_a_snapshot_not_the_live_file(db_file, monkeypatch):
    """Se sube una copia, no el fichero vivo: al soltar el lock puede estar
    escribiendose, y subirlo a medias daria una DB corrupta en GCS."""
    observed = {}
    monkeypatch.setattr(gcs_sync, "_get_cached_client", lambda: _FakeClient(observed))

    gcs_sync.upload_user_db()
    assert observed["uploaded_path"] != str(db_file)
    # y la copia temporal no se queda tirada en disco
    assert not os.path.exists(observed["uploaded_path"])


def test_timeout_is_not_the_old_five_seconds(db_file, monkeypatch):
    observed = {}
    monkeypatch.setattr(gcs_sync, "_get_cached_client", lambda: _FakeClient(observed))

    gcs_sync.upload_user_db()
    assert observed["timeout"] >= 60, (
        "5 s no alcanzan para subir la DB entera; era lo que hacia fallar los "
        "3 intentos seguidos y dejaba los datos solo en el contenedor"
    )


def test_concurrent_upload_is_skipped_not_duplicated(db_file, monkeypatch):
    """Con la red fuera del lock, dos subidas podrian solaparse y pisarse en el
    bucket. La segunda debe descartarse y dejar la DB marcada como sucia."""
    observed = {}
    monkeypatch.setattr(gcs_sync, "_get_cached_client", lambda: _FakeClient(observed))

    gcs_sync._upload_in_flight.acquire()
    try:
        assert gcs_sync.upload_user_db() is False
        assert "uploaded_path" not in observed
    finally:
        gcs_sync._upload_in_flight.release()

    assert gcs_sync._dirty_since_upload is True
