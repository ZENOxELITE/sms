@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Student Management System setup
color 07
cls

echo.
echo  ==============================================================
echo   STUDENT MANAGEMENT SYSTEM
echo   LOCAL ENVIRONMENT INITIALIZATION
echo  ==============================================================
echo.
echo   ANALYZING SYSTEM...
echo   CHECKING HARDWARE CAPABILITIES...
echo   Processor architecture : %PROCESSOR_ARCHITECTURE%
echo   Logical processors     : %NUMBER_OF_PROCESSORS%
ver
echo.
echo   PREPARING LAUNCH SEQUENCE
echo.

set "bar="
for /L %%i in (0,1,10) do (
    set /a percent=%%i*10 >nul
    if %%i GTR 0 set "bar=!bar!##"
    echo   [!bar!] !percent!%%
    if %%i LSS 10 ping -n 2 127.0.0.1 >nul
)
echo.
echo   SYSTEM ANALYSIS COMPLETE
echo.
echo  --------------------------------------------------------------

if not exist ".env" (
    echo ERROR: .env is missing.
    echo Copy .env.example to .env and add your Supabase settings.
    goto failed
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/7] Creating local Python environment...
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

echo [2/7] Checking Python version...
python -c "import sys; print('Using Python', sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 (
    echo ERROR: Django 6 requires Python 3.12 or newer.
    goto failed
)

echo [3/7] Installing Python dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto failed

echo [4/7] Checking Django configuration...
python manage.py check
if errorlevel 1 goto failed

echo [5/7] Running Python tests...
python -m unittest discover -s tests
if errorlevel 1 goto failed

where node >nul 2>nul
if errorlevel 1 (
    echo ERROR: Node.js is required for the portal table tests. Install Node.js and try again.
    goto failed
)

echo [6/7] Running portal table tests...
node --test tests\test_portal_tables.js
if errorlevel 1 goto failed

echo [7/7] Checking Supabase connection...
python manage.py check_supabase
if errorlevel 1 goto failed

echo Collecting static files...
python manage.py collectstatic --noinput
if errorlevel 1 goto failed

echo.
echo  ==============================================================
echo   ALL CHECKS PASSED
echo   Starting the website: http://127.0.0.1:5000
echo  ==============================================================

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
