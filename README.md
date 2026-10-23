# PyGold

PyGold is a Python web app for a community game platform. It includes accounts,
persistent friend relationships and text conversations, community game listings,
a canvas-based drawing editor, and validation for game ZIP uploads.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`.

The ZIP upload accepts files up to 20 MB. Each archive must contain non-empty
`Texturas/` and `Main/` directories plus `Main/main.py`, `Main/icono.png`, and
`Main/BASE.pow`. The icon must be PNG and `BASE.pow` must have a RAR signature.
Archives are checked for unsafe paths, symbolic links, file count, and
uncompressed size. Uploaded game code is **not executed**. A restricted
`open()` wrapper is not a security boundary; untrusted Python needs a separate,
disposable sandbox service with OS-level isolation, resource limits, and no
network access. Do not enable game execution in the web process.

Profiles, account passwords, friend requests, friendships, group membership,
and text messages are stored in the configured database. Passwords are hashed;
the raw password is never stored. Sign-up currently does not include email
verification or password recovery. Messages are plain text; attachments and
audio/video calls are not implemented. Profile preference toggles still use
browser-local storage. Never store user passwords, uploads, or other private
data in Git or commit credentials.

For local development the app uses SQLite under `data/`. In production,
configure a Render PostgreSQL database and set the web service's `DATABASE_URL`
to its **internal connection string**. Set a strong `SECRET_KEY` and
`SESSION_COOKIE_SECURE=true`. The persistent disk in the Render blueprint
stores uploaded game archives; it does not replace PostgreSQL for user data.
When creating a Render PostgreSQL database, add the database's internal
connection string as `DATABASE_URL` in the web service's environment. The app
accepts Render's `postgres://` URL and uses the psycopg driver.
The blueprint requests `DATABASE_URL` during setup. If the existing Render
service was created manually, add it under **Environment** yourself. Production
startup refuses to use a predictable development secret.

For a manually configured Render web service, set **Start Command** to
`gunicorn --bind 0.0.0.0:$PORT app:app`. Do not use the placeholder
`your_application.wsgi`; this repository's Flask application is `app:app`.
The blueprint pins Python to 3.12.3. If the service is configured manually,
select Python 3.12 in its environment settings or sync the service from
`render.yaml` so it does not unexpectedly use a different runtime.
