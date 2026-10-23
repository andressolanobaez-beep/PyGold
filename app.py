import os
import re
import secrets
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import inspect, or_, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, login_manager
from models import Conversation, ConversationMember, FriendRequest, Friendship, Game, Message, User


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("PYGOLD_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "games"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UNPACKED_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_FILES = 500

app = Flask(__name__)
secret_key = os.environ.get("SECRET_KEY")
if not secret_key and os.environ.get("RENDER"):
    raise RuntimeError("Configura SECRET_KEY como variable de entorno en Render.")
app.config["SECRET_KEY"] = secret_key or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + 1024 * 1024
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"

database_url = os.environ.get("DATABASE_URL")
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
else:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite:///{(DATA_DIR / 'pygold.db').as_posix()}"
app.config["SQLALCHEMY_DATABASE_URI"] = database_url

db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Inicia sesión para continuar."
login_manager.login_message_category = "error"
CSRFProtect(app)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def init_db():
    with app.app_context():
        db.create_all()
        game_columns = {
            column["name"] for column in inspect(db.engine).get_columns("games")
        }
        if "owner_id" not in game_columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        'ALTER TABLE games ADD COLUMN owner_id INTEGER '
                        'REFERENCES "user"(id) ON DELETE SET NULL'
                    )
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
    app.logger.warning("Upload rejected by request size limit: %s", _error)
    flash("El archivo supera el límite de 20 MB.", "error")
    return redirect(url_for("upload_game"))


@app.route("/")
def home():
    games = Game.query.order_by(Game.created_at.desc()).all()
    return render_template("home.html", games=games)


@app.route("/CREATE")
@login_required
def create():
    return render_template("create.html")


@app.route("/CREAR/VIDEOJUEGO", methods=["GET", "POST"])
@login_required
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
        game = Game(
            id=uuid.uuid4().hex[:12],
            name=name,
            description=description,
            filename=archive_filename,
            owner_id=current_user.id,
        )
        db.session.add(game)
        db.session.commit()
        flash("Tu juego se publicó en la comunidad.", "success")
        return redirect(url_for("game_detail", game_id=game.id))

    return render_template("upload.html")


@app.route("/JUEGO/<game_id>")
def game_detail(game_id):
    if not re.fullmatch(r"[a-f0-9]{12}", game_id):
        abort(404)
    game = db.session.get(Game, game_id)
    if game is None:
        abort(404)
    return render_template("game.html", game=game)


@app.route("/CONFIGURACION")
@login_required
def settings():
    return render_template("settings.html")


@app.route("/PERFIL", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        username = request.form.get("nickname", "").strip()
        bio = request.form.get("bio", "").strip()
        if not username or not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", username):
            flash("El apodo debe tener entre 1 y 24 letras, números, guiones o guiones bajos.", "error")
            return redirect(url_for("profile"))
        if len(bio) > 180:
            flash("La bio no puede superar los 180 caracteres.", "error")
            return redirect(url_for("profile"))
        existing_user = User.query.filter(
            User.username == username,
            User.id != current_user.id,
        ).first()
        if existing_user:
            flash("Ese apodo ya está en uso.", "error")
            return redirect(url_for("profile"))
        current_user.username = username.lower()
        current_user.bio = bio
        db.session.commit()
        flash("Tu perfil se guardó.", "success")
        return redirect(url_for("profile"))

    friendships = Friendship.query.filter(
        or_(Friendship.user_low_id == current_user.id, Friendship.user_high_id == current_user.id)
    ).all()
    friend_ids = [
        friendship.user_high_id
        if friendship.user_low_id == current_user.id
        else friendship.user_low_id
        for friendship in friendships
    ]
    friends = User.query.filter(User.id.in_(friend_ids)).order_by(User.username).all() if friend_ids else []
    incoming_requests = FriendRequest.query.filter_by(
        recipient_id=current_user.id, status="pending"
    ).order_by(FriendRequest.created_at.desc()).all()
    search_term = request.args.get("q", "").strip()
    search_results = []
    if search_term:
        search_results = User.query.filter(
            User.username.ilike(f"%{search_term[:24]}%"),
            User.id != current_user.id,
        ).limit(20).all()
    return render_template(
        "profile.html",
        friends=friends,
        incoming_requests=incoming_requests,
        search_term=search_term,
        search_results=search_results,
    )


@app.post("/AMIGOS/SOLICITUD")
@login_required
def send_friend_request():
    username = request.form.get("username", "").strip()
    recipient = User.query.filter_by(username=username).first()
    if recipient is None or recipient.id == current_user.id:
        flash("No encontramos ese usuario.", "error")
        return redirect(url_for("profile"))
    low_id, high_id = sorted((current_user.id, recipient.id))
    if Friendship.query.filter_by(user_low_id=low_id, user_high_id=high_id).first():
        flash("Ya son amigos.", "error")
    elif FriendRequest.query.filter(
        FriendRequest.status == "pending",
        or_(
            (FriendRequest.sender_id == current_user.id) & (FriendRequest.recipient_id == recipient.id),
            (FriendRequest.sender_id == recipient.id) & (FriendRequest.recipient_id == current_user.id),
        ),
    ).first():
        flash("Ya hay una solicitud pendiente entre ustedes.", "error")
    else:
        db.session.add(FriendRequest(sender_id=current_user.id, recipient_id=recipient.id))
        db.session.commit()
        flash("Solicitud de amistad enviada.", "success")
    return redirect(url_for("profile"))


@app.post("/AMIGOS/SOLICITUD/<int:request_id>/ACEPTAR")
@login_required
def accept_friend_request(request_id):
    friend_request = db.session.get(FriendRequest, request_id)
    if (
        friend_request is None
        or friend_request.recipient_id != current_user.id
        or friend_request.status != "pending"
    ):
        abort(404)
    low_id, high_id = sorted((friend_request.sender_id, friend_request.recipient_id))
    db.session.add(Friendship(user_low_id=low_id, user_high_id=high_id))
    friend_request.status = "accepted"
    db.session.commit()
    flash("Solicitud aceptada. Ya son amigos.", "success")
    return redirect(url_for("profile"))


@app.route("/MENSAJES", methods=["GET", "POST"])
@login_required
def messages():
    if request.method == "POST":
        title = request.form.get("group_name", "").strip()
        raw_ids = request.form.getlist("participant_ids")
        try:
            participant_ids = {int(value) for value in raw_ids}
        except ValueError:
            flash("Selecciona participantes válidos.", "error")
            return redirect(url_for("messages"))
        participant_ids.discard(current_user.id)
        if not participant_ids:
            flash("Selecciona al menos un amigo para iniciar el chat.", "error")
            return redirect(url_for("messages"))
        if len(title) > 50:
            flash("El nombre del grupo no puede superar los 50 caracteres.", "error")
            return redirect(url_for("messages"))
        friendships = Friendship.query.filter(
            or_(
                Friendship.user_low_id == current_user.id,
                Friendship.user_high_id == current_user.id,
            )
        ).all()
        friend_ids = {
            item.user_high_id if item.user_low_id == current_user.id else item.user_low_id
            for item in friendships
        }
        if not participant_ids.issubset(friend_ids):
            flash("Solo puedes iniciar chats con tus amigos.", "error")
            return redirect(url_for("messages"))
        is_group = len(participant_ids) > 1
        conversation = Conversation(
            name=title or None,
            is_group=is_group,
            created_by_id=current_user.id,
            updated_at=datetime.now(timezone.utc),
        )
        db.session.add(conversation)
        db.session.flush()
        db.session.add_all(
            ConversationMember(conversation_id=conversation.id, user_id=user_id)
            for user_id in participant_ids | {current_user.id}
        )
        db.session.commit()
        return redirect(url_for("messages", conversation=conversation.id))

    friendships = Friendship.query.filter(
        or_(Friendship.user_low_id == current_user.id, Friendship.user_high_id == current_user.id)
    ).all()
    friend_ids = {
        item.user_high_id if item.user_low_id == current_user.id else item.user_low_id
        for item in friendships
    }
    friends = User.query.filter(User.id.in_(friend_ids)).order_by(User.username).all() if friend_ids else []
    conversations = (
        Conversation.query.join(ConversationMember)
        .filter(ConversationMember.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .all()
    )
    conversation_id = request.args.get("conversation", type=int)
    active_conversation = None
    conversation_messages = []
    if conversation_id is not None:
        active_conversation = (
            Conversation.query.join(ConversationMember)
            .filter(
                Conversation.id == conversation_id,
                ConversationMember.user_id == current_user.id,
            )
            .first()
        )
        if active_conversation is None:
            abort(404)
        conversation_messages = (
            Message.query.filter_by(conversation_id=active_conversation.id)
            .order_by(Message.id.desc())
            .limit(100)
            .all()
        )[::-1]
    return render_template(
        "messages.html",
        friends=friends,
        conversations=conversations,
        active_conversation=active_conversation,
        conversation_messages=conversation_messages,
        now=datetime.now(timezone.utc),
    )


@app.post("/MENSAJES/<int:conversation_id>")
@login_required
def send_message(conversation_id):
    membership = ConversationMember.query.filter_by(
        conversation_id=conversation_id, user_id=current_user.id
    ).first()
    if membership is None:
        abort(404)
    body = request.form.get("body", "").strip()
    if not body or len(body) > 2000:
        flash("El mensaje debe tener entre 1 y 2000 caracteres.", "error")
        return redirect(url_for("messages", conversation=conversation_id))
    db.session.add(
        Message(
            conversation_id=conversation_id,
            sender_id=current_user.id,
            body=body,
        )
    )
    conversation = db.session.get(Conversation, conversation_id)
    conversation.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return redirect(url_for("messages", conversation=conversation_id))


@app.get("/MENSAJES/<int:conversation_id>/NUEVOS")
@login_required
def new_messages(conversation_id):
    if not ConversationMember.query.filter_by(
        conversation_id=conversation_id, user_id=current_user.id
    ).first():
        abort(404)
    after_id = request.args.get("after", 0, type=int)
    messages_after = (
        Message.query.filter(
            Message.conversation_id == conversation_id,
            Message.id > after_id,
        )
        .order_by(Message.id.asc())
        .limit(100)
        .all()
    )
    return jsonify(
        [
            {
                "id": message.id,
                "sender": message.sender.username,
                "body": message.body,
                "created_at": message.created_at.isoformat(),
            }
            for message in messages_after
        ]
    )


@app.route("/INICIAR-SESION", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user is None or not check_password_hash(user.password_hash, password):
            flash("Correo o contraseña incorrectos.", "error")
            return render_template("login.html"), 401
        login_user(user, remember=True, fresh=True)
        return redirect(url_for("home"))
    return render_template("login.html")


@app.route("/REGISTRO", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 254:
            flash("Escribe un correo electrónico válido.", "error")
            return render_template("register.html"), 400
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,24}", username):
            flash("El usuario debe tener entre 3 y 24 letras, números, guiones o guiones bajos.", "error")
            return render_template("register.html"), 400
        if len(password) < 12 or len(password) > 128:
            flash("La contraseña debe tener entre 12 y 128 caracteres.", "error")
            return render_template("register.html"), 400
        username = username.lower()
        if User.query.filter(or_(User.email == email, User.username == username)).first():
            flash("Ese correo o nombre de usuario ya está registrado.", "error")
            return render_template("register.html"), 409
        user = User(
            email=email,
            username=username,
            password_hash=generate_password_hash(password),
        )
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Ese correo o nombre de usuario ya está registrado.", "error")
            return render_template("register.html"), 409
        login_user(user, remember=True, fresh=True)
        flash("Tu cuenta ya está lista.", "success")
        return redirect(url_for("home"))
    return render_template("register.html")


@app.post("/CUENTA/ELIMINAR")
@login_required
def delete_account():
    password = request.form.get("password", "")
    if not check_password_hash(current_user.password_hash, password):
        flash("La contraseña no coincide. La cuenta sigue activa.", "error")
        return redirect(url_for("settings"))

    user_id = current_user.id
    owned_games = Game.query.filter_by(owner_id=user_id).all()
    archive_paths = [UPLOAD_DIR / game.filename for game in owned_games]
    for game in owned_games:
        db.session.delete(game)
    conversations = (
        Conversation.query.join(ConversationMember)
        .filter(ConversationMember.user_id == user_id)
        .all()
    )
    Message.query.filter_by(sender_id=user_id).delete(synchronize_session=False)
    ConversationMember.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    FriendRequest.query.filter(
        or_(FriendRequest.sender_id == user_id, FriendRequest.recipient_id == user_id)
    ).delete(synchronize_session=False)
    Friendship.query.filter(
        or_(Friendship.user_low_id == user_id, Friendship.user_high_id == user_id)
    ).delete(synchronize_session=False)
    for conversation in conversations:
        if not ConversationMember.query.filter_by(conversation_id=conversation.id).first():
            db.session.delete(conversation)
    user = db.session.get(User, user_id)
    db.session.delete(user)
    logout_user()
    db.session.commit()
    cleanup_errors = []
    for archive_path in archive_paths:
        try:
            archive_path.unlink(missing_ok=True)
        except OSError as error:
            app.logger.error("No se pudo borrar el juego %s: %s", archive_path.name, error)
            cleanup_errors.append(archive_path.name)
    if cleanup_errors:
        flash("La cuenta se eliminó, pero algunos archivos de juego requieren limpieza.", "error")
    else:
        flash("La cuenta y sus datos personales y juegos publicados se eliminaron.", "success")
    return redirect(url_for("home"))


@app.post("/CERRAR-SESION")
@login_required
def logout():
    logout_user()
    flash("Has cerrado sesión.", "success")
    return redirect(url_for("home"))


@app.errorhandler(500)
def internal_error(error):
    app.logger.exception("Error interno al procesar la solicitud: %s", error)
    return "Ocurrió un error interno. Inténtalo de nuevo.", 500


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
