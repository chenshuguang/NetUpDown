from __future__ import annotations

import io
import os
import sqlite3
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Optional

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATA_ROOT = BASE_DIR / "storage"
DB_PATH = BASE_DIR / "app.db"


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )

    DATA_ROOT.mkdir(exist_ok=True)

    @app.before_request
    def load_user() -> None:
        user_id = session.get("user_id")
        g.user = None
        if user_id is not None:
            g.user = query_db("SELECT id, username FROM users WHERE id = ?", (user_id,), one=True)

    @app.route("/")
    def index():
        if not g.user:
            return redirect(url_for("login"))
        user_dir = user_storage_dir(g.user["id"])
        files = []
        for item in sorted(user_dir.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            files.append(
                {
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "size": human_size(item.stat().st_size if item.is_file() else folder_size(item)),
                }
            )
        return render_template("index.html", files=files, username=g.user["username"])

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if len(username) < 3 or len(password) < 6:
                flash("用户名至少3位，密码至少6位", "error")
            elif query_db("SELECT id FROM users WHERE username = ?", (username,), one=True):
                flash("用户名已存在", "error")
            else:
                execute_db(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password)),
                )
                flash("注册成功，请登录", "success")
                return redirect(url_for("login"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = query_db("SELECT id, username, password_hash FROM users WHERE username = ?", (username,), one=True)
            if not user or not check_password_hash(user["password_hash"], password):
                flash("用户名或密码错误", "error")
            else:
                session.clear()
                session["user_id"] = user["id"]
                session.permanent = True
                return redirect(url_for("index"))
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/upload", methods=["POST"])
    def upload():
        require_login()

        file = request.files.get("file")
        filename = secure_filename(request.form.get("filename") or (file.filename if file else ""))
        if not filename:
            return {"error": "缺少文件名"}, 400

        user_dir = user_storage_dir(g.user["id"])
        target = user_dir / filename
        range_header = request.headers.get("Content-Range", "")

        if file is None:
            return {"error": "缺少文件"}, 400

        if range_header:
            start, end, total = parse_content_range(range_header)
            mode = "r+b" if target.exists() else "wb"
            with open(target, mode) as f:
                f.seek(start)
                f.write(file.stream.read())
            current_size = target.stat().st_size
            complete = current_size >= total and end + 1 >= total
            return {"filename": filename, "uploaded": current_size, "total": total, "complete": complete}

        file.save(target)
        return {"filename": filename, "uploaded": target.stat().st_size, "complete": True}

    @app.route("/download/<path:name>")
    def download(name: str):
        require_login()
        base = user_storage_dir(g.user["id"])
        safe_name = secure_filename(name)
        if safe_name != name:
            abort(400, "无效路径")

        target = base / safe_name
        if not target.exists():
            abort(404)

        if target.is_dir():
            temp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
            temp.close()
            zip_path = Path(temp.name)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for item in target.rglob("*"):
                    if item.is_file():
                        zf.write(item, arcname=str(item.relative_to(target.parent)))
            return range_file_response(zip_path, f"{target.name}.zip", cleanup_after=True)

        return range_file_response(target, target.name)

    return app


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


def query_db(query: str, args: tuple = (), one: bool = False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def execute_db(query: str, args: tuple = ()) -> None:
    db = get_db()
    db.execute(query, args)
    db.commit()


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def user_storage_dir(user_id: int) -> Path:
    p = DATA_ROOT / str(user_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def require_login() -> None:
    if not g.user:
        abort(401, "请先登录")


def parse_content_range(header: str) -> tuple[int, int, int]:
    # bytes start-end/total
    try:
        units, payload = header.split(" ", 1)
        if units.lower() != "bytes":
            raise ValueError
        range_part, total_part = payload.split("/")
        start_str, end_str = range_part.split("-")
        return int(start_str), int(end_str), int(total_part)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("无效Content-Range") from exc


def parse_range_header(range_header: str, file_size: int) -> Optional[tuple[int, int]]:
    try:
        units, ranges = range_header.split("=", 1)
        if units != "bytes":
            return None
        start_str, end_str = ranges.split("-")
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        if start > end or end >= file_size:
            return None
        return start, end
    except Exception:
        return None


def range_file_response(path: Path, download_name: str, cleanup_after: bool = False):
    file_size = path.stat().st_size
    range_header = request.headers.get("Range")

    if range_header:
        parsed = parse_range_header(range_header, file_size)
        if not parsed:
            abort(416)
        start, end = parsed
        length = end - start + 1
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read(length)

        def cleanup():
            if cleanup_after:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

        response = Response(data, 206, mimetype="application/octet-stream")
        response.headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        response.headers["Accept-Ranges"] = "bytes"
        response.headers["Content-Length"] = str(length)
        response.headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
        response.call_on_close(cleanup)
        return response

    response = send_file(path, as_attachment=True, download_name=download_name)
    if cleanup_after:
        response.call_on_close(lambda: path.unlink(missing_ok=True))
    response.headers["Accept-Ranges"] = "bytes"
    return response


def folder_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def human_size(num: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


app = create_app()


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000, debug=True)
