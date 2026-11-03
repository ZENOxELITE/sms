@echo off
setlocal
cd /d "%~dp0"
title Student Management System setup

echo ========================================
echo Student Management System
echo ========================================

if not exist ".env" (
    echo ERROR: .env is missing.
    echo Copy .env.example to .env and add your Supabase settings.
    goto failed
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating local Python environment...
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        where python >nul 2>nul
        if errorlevel 1 (
            echo ERROR: Install Python 3 and try again.
            goto failed
        )
        python -m venv .venv
    )
    if errorlevel 1 goto failed
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo ERROR: Could not activate .venv.
    goto failed
)

python -c "import sys; print('Using Python', sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 (
    echo ERROR: Django 6 requires Python 3.12 or newer.
    goto failed
)

echo.
echo Installing Python dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto failed

echo.
echo Checking Django configuration...
python manage.py check
if errorlevel 1 goto failed

echo.
echo Running Python tests...
python -m unittest discover -s tests
if errorlevel 1 goto failed

where node >nul 2>nul
if errorlevel 1 (
    echo ERROR: Node.js is required for the portal table tests. Install Node.js and try again.
    goto failed
)

echo.
echo Running portal table tests...
node --test tests\test_portal_tables.js
if errorlevel 1 goto failed

echo.
echo Checking Supabase connection...
python manage.py check_supabase
if errorlevel 1 goto failed

echo.
echo Collecting static files...
python manage.py collectstatic --noinput
if errorlevel 1 goto failed

echo.
echo ========================================
echo All checks passed. Starting the website.
echo Open: http://127.0.0.1:5000
echo ========================================

start "Student Management System" "%CD%\.venv\Scripts\python.exe" manage.py runserver 127.0.0.1:5000
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:5000"
echo The Django server is running in its own window. Close that window to stop it.
pause
exit /b 0

:failed
echo.
echo Setup or a check failed. Review the error above, fix it, and run this file again.
pause
exit /b 1
