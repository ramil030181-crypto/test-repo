@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\installed.ok (
  echo Первый запуск: создаю окружение и ставлю библиотеки, 3-5 минут...
  if not exist .venv ( py -3 -m venv .venv || python -m venv .venv )
  if not exist .venv\Scripts\python.exe (
    echo ОШИБКА: не найден Python. Установите Python 3.12 с python.org, отметив "Add python.exe to PATH".
    pause
    exit /b 1
  )
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt && echo ok> .venv\installed.ok
  if not exist .venv\installed.ok (
    echo ОШИБКА: библиотеки не установились. Проверьте интернет и запустите файл ещё раз.
    pause
    exit /b 1
  )
)
if not exist .env (
  copy .env.example .env >nul
  echo Создан файл .env - впишите в него токен бота и ключ, сохраните и запустите этот файл снова.
  notepad .env
  exit /b
)
if "%1"=="rehearsal" (
  .venv\Scripts\python offline.py --date 2026-11-23
  pause
  exit /b
)
if "%1"=="test" (
  .venv\Scripts\python -m pytest -q tests
  pause
  exit /b
)
echo Бот запускается. Не закрывайте это окно, пока идёт занятие. Остановить: Ctrl+C.
.venv\Scripts\python bot.py
pause
