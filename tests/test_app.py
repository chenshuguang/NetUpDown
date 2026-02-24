import io
import zipfile
from pathlib import Path

import app as app_module


def setup_temp(tmp_path):
    app_module.DB_PATH = tmp_path / "test.db"
    app_module.DATA_ROOT = tmp_path / "storage"
    app_module.init_db()
    flask_app = app_module.create_app()
    flask_app.config.update(TESTING=True, SECRET_KEY="test")
    return flask_app.test_client()


def register_and_login(client):
    client.post("/register", data={"username": "u123", "password": "123456"})
    client.post("/login", data={"username": "u123", "password": "123456"})


def test_resumable_upload_and_range_download(tmp_path):
    client = setup_temp(tmp_path)
    register_and_login(client)

    data1 = {"file": (io.BytesIO(b"hello"), "a.txt"), "filename": "a.txt"}
    r1 = client.post("/upload", data=data1, headers={"Content-Range": "bytes 0-4/11"}, content_type="multipart/form-data")
    assert r1.status_code == 200

    data2 = {"file": (io.BytesIO(b" world"), "a.txt"), "filename": "a.txt"}
    r2 = client.post("/upload", data=data2, headers={"Content-Range": "bytes 5-10/11"}, content_type="multipart/form-data")
    assert r2.json["complete"] is True

    rd = client.get("/download/a.txt", headers={"Range": "bytes=6-10"})
    assert rd.status_code == 206
    assert rd.data == b"world"


def test_download_directory_as_zip(tmp_path):
    client = setup_temp(tmp_path)
    register_and_login(client)

    user_dir = next((tmp_path / "storage").iterdir())
    folder = user_dir / "docs"
    folder.mkdir()
    (folder / "x.txt").write_text("zip me", encoding="utf-8")

    resp = client.get("/download/docs")
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    assert "docs/x.txt" in zf.namelist()
