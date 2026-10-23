import os
import re
import sqlite3
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from flask import Flask, abort, flash, redirect, render_template, request, url_for


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("PYGOLD_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "games"
DATABASE = DATA_DIR / "pygold.db"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UNPACKED_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_FILES = 500

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "development-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + 1024 * 1024


@contextmanager
def get_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with get_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def validate_game_archive(file_storage) -> tuple[str | None, str | None]:
    if not file_storage.filename or not file_storage.filename.lower().endswith(".zip"):
        return None, "Selecciona un archivo .zip."

    archive_path = UPLOAD_DIR / f"{uuid.uuid4().hex}.zip"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_storage.save(archive_path)
    if archive_path.stat().st_size > MAX_UPLOAD_BYTES:
        archive_path.unlink(missing_ok=True)
        return None, "El archivo supera el límite de 20 MB."

    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_FILES:
                raise ValueError("El ZIP contiene demasiados archivos.")
            total_size = 0
            paths = set()
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in entry.filename:
                    raise ValueError("El ZIP contiene una ruta no permitida.")
                if entry.flag_bits & 0x1:
                    raise ValueError("No se aceptan archivos ZIP cifrados.")
                if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("El ZIP contiene un enlace simbólico no permitido.")
                paths.add(entry.filename.rstrip("/"))
                total_size += entry.file_size
                if total_size > MAX_UNPACKED_BYTES:
                    raise ValueError("El contenido descomprimido supera el límite de 50 MB.")

            required = {"Main/main.py", "Main/icono.png", "Main/BASE.pow"}
            missing = required - paths
            if missing:
                raise ValueError(
                    "Faltan elementos requeridos: " + ", ".join(sorted(missing))
                )
            for directory in ("Texturas", "Main"):
                if not any(name.startswith(directory + "/") for name in paths):
                    raise ValueError(f"La carpeta {directory} debe contener archivos.")
            with archive.open("Main/icono.png") as icon:
                if icon.read(8) != b"\x89PNG\r\n\x1a\n":
                    raise ValueError("Main/icono.png no es una imagen PNG válida.")
            with archive.open("Main/BASE.pow") as world:
                signature = world.read(8)
                if not (
                    signature.startswith(b"Rar!\x1a\x07\x00")
                    or signature.startswith(b"Rar!\x1a\x07\x01\x00")
                ):
                    raise ValueError("Main/BASE.pow debe contener un archivo RAR válido.")
    except (zipfile.BadZipFile, OSError, ValueError) as error:
        archive_path.unlink(missing_ok=True)
        message = (
            str(error)
            if not isinstance(error, zipfile.BadZipFile)
            else "El archivo no es un ZIP válido."
        )
        return None, message

    return archive_path.name, None


@app.errorhandler(413)
def upload_too_large(_error):
    flash("El archivo supera el límite de 20 MB.", "error")
    return redirect(url_for("upload_game"))


@app.route("/")
def home():
    with get_db() as connection:
        games = connection.execute(
            "SELECT id, name, description, created_at FROM games ORDER BY created_at DESC"
        ).fetchall()
    return render_template("home.html", games=games)


@app.route("/CREATE")
def create():
    return render_template("create.html")


@app.route("/CREAR/VIDEOJUEGO", methods=["GET", "POST"])
def upload_game():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        uploaded_file = request.files.get("game_zip")
        if not name or len(name) > 60:
            flash("Escribe un nombre de hasta 60 caracteres.", "error")
            return redirect(url_for("upload_game"))
        if len(description) > 500:
            flash("La descripción no puede superar los 500 caracteres.", "error")
            return redirect(url_for("upload_game"))
        if not uploaded_file:
            flash("Selecciona el ZIP de tu juego.", "error")
            return redirect(url_for("upload_game"))

        archive_filename, validation_error = validate_game_archive(uploaded_file)
        if validation_error is not None:
            flash(validation_error, "error")
            return redirect(url_for("upload_game"))
        if archive_filename is None:
            raise RuntimeError("La validación no devolvió el nombre del archivo.")
        game_id = uuid.uuid4().hex[:12]
        with get_db() as connection:
            connection.execute(
                "INSERT INTO games (id, name, description, filename) VALUES (?, ?, ?, ?)",
                (game_id, name, description, archive_filename),
            )
        flash("Tu juego se publicó en la comunidad.", "success")
        return redirect(url_for("game_detail", game_id=game_id))

    return render_template("upload.html")


@app.route("/JUEGO/<game_id>")
def game_detail(game_id):
    if not re.fullmatch(r"[a-f0-9]{12}", game_id):
        abort(404)
    with get_db() as connection:
        game = connection.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    if game is None:
        abort(404)
    return render_template("game.html", game=game)


@app.route("/CONFIGURACION")
def settings():
    return render_template("settings.html")


@app.route("/PERFIL")
def profile():
    return render_template("profile.html")


@app.route("/MENSAJES")
def messages():
    return render_template("messages.html")


@app.errorhandler(500)
def internal_error(error):
    app.logger.exception("Error interno al procesar la solicitud: %s", error)
    return "Ocurrió un error interno. Inténtalo de nuevo.", 500


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
