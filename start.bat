@echo off
REM Lance le Command Center et ouvre l'interface dans le navigateur.
cd /d "%~dp0"
python -c "import fastapi, uvicorn" 2>nul || python -m pip install -r requirements.txt
python server.py
pause
