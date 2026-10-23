@echo off
setlocal
pushd "%~dp0"

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo Error: esta carpeta no es un repositorio Git.
    goto :fail
)

git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo Error: no existe el remoto "origin".
    goto :fail
)

git add -A
if errorlevel 1 (
    echo Error al preparar los archivos.
    goto :fail
)

git diff --cached --quiet
if not errorlevel 1 (
    echo No hay cambios para publicar.
    popd
    exit /b 0
)

for /f "delims=" %%F in ('git diff --cached --name-only') do (
    call :check_sensitive "%%F"
    if errorlevel 1 (
        echo.
        echo Publicacion cancelada: revisa o retira los archivos sensibles.
        goto :fail
    )
)

git diff --cached --check
if errorlevel 1 (
    echo Error: corrige los espacios o conflictos indicados antes de publicar.
    goto :fail
)

echo.
echo Archivos que se publicaran:
git diff --cached --name-only
echo.
set "CONFIRM="
set /p "CONFIRM=Crear el commit y subirlo a GitHub? [s/N]: "
if /i not "%CONFIRM%"=="s" (
    echo Publicacion cancelada. Los cambios permanecen preparados en Git.
    popd
    exit /b 0
)

git commit -m "Actualiza PyGold" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
if errorlevel 1 goto :fail

git push origin HEAD
if errorlevel 1 (
    echo Error al subir los cambios. El commit local se conserva; vuelve a ejecutar este archivo para reintentar.
    goto :fail
)

echo.
echo Cambios publicados correctamente.
popd
exit /b 0

:check_sensitive
set "FILE=%~1"
for %%A in ("%FILE%") do (
    set "BASENAME=%%~nxA"
    set "EXT=%%~xA"
)
if /i "%BASENAME%"==".env" exit /b 1
if /i "%BASENAME:~0,5%"==".env." if /i not "%BASENAME%"==".env.example" exit /b 1
if /i "%EXT%"==".db" exit /b 1
if /i "%EXT%"==".sqlite" exit /b 1
if /i "%EXT%"==".sqlite3" exit /b 1
if /i "%EXT%"==".pem" exit /b 1
if /i "%EXT%"==".key" exit /b 1
if /i "%BASENAME%"=="id_rsa" exit /b 1
if /i "%BASENAME%"=="id_ed25519" exit /b 1
exit /b 0

:fail
popd
exit /b 1
