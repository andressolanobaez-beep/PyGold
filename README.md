# PyGold

PyGold is a Python web-app prototype for a community game platform. It includes
community game listings, Spanish-language profile/settings/messages pages, a
canvas-based drawing editor, and validation for game ZIP uploads.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`.

The ZIP upload accepts files up to 20 MB. Each archive must contain non-empty
`Texturas/` and `Main/` directories plus `Main/main.py`, `Main/icono.png`, and
`Main/BASE.pow`. The icon must be PNG and `BASE.pow` must have a RAR signature.
Archives are checked for unsafe paths, symbolic links, file count, and
uncompressed size. Uploaded game code is **not executed**.

Profile edits and preference toggles are browser-local demo data. User accounts,
friend relationships, persistent messaging, image sharing, garment publishing,
game execution, and local game hosting are not implemented. Never store user
passwords, uploads, or other private data in Git or commit credentials. Running
creator-provided Python requires a separately designed, isolated execution
service; it must not run inside the web application process.

The Render blueprint provisions a persistent disk for the SQLite game catalog
and uploaded ZIPs. Set a strong `SECRET_KEY` in the deployment environment.

For a manually configured Render web service, set **Start Command** to
`gunicorn --bind 0.0.0.0:$PORT app:app`. Do not use the placeholder
`your_application.wsgi`; this repository's Flask application is `app:app`.
The blueprint pins Python to 3.12.3. If the service is configured manually,
select Python 3.12 in its environment settings or sync the service from
`render.yaml` so it does not unexpectedly use a different runtime.
