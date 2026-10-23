#!/usr/bin/env bash
# Запуск бота на macOS / Linux.  ./start_mac_linux.sh           — бот
#                                ./start_mac_linux.sh rehearsal — репетиция без Telegram
#                                ./start_mac_linux.sh test      — самопроверка (тесты)
set -e
cd "$(dirname "$0")"
if [ ! -f .venv/installed.ok ]; then
  echo "Первый запуск: создаю окружение и ставлю библиотеки, 3–5 минут…"
  [ -d .venv ] || python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt && echo ok > .venv/installed.ok
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Создан файл .env — впишите в него токен бота и ключ, затем запустите снова (open -e .env)."
  exit 0
fi
case "$1" in
  rehearsal) exec .venv/bin/python offline.py --date 2026-11-23 ;;
  test) exec .venv/bin/python -m pytest -q tests ;;
esac
echo "Бот запускается. Не закрывайте окно Терминала. Остановить: Ctrl+C."
exec .venv/bin/python bot.py
