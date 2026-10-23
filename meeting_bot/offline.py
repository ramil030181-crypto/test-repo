# -*- coding: utf-8 -*-
"""Тот же конвейер без Telegram — для репетиции и проверки.

  python offline.py стенограмма.txt --date 2026-11-23
  python offline.py --audio папка_с_голосовыми --date 2026-11-23

Строки стенограммы — «Фамилия: текст». Аудиофайлы берутся по алфавиту;
каждое голосовое начинайте с фамилии говорящего. Результат — в data/results/.
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

from meeting import Directory  # noqa: E402
from service import MeetingService  # noqa: E402

DEMO = HERE.parent / "Входные_данные" / "Планёрка_23.11.2026_стенограмма.txt"
AUDIO = {".ogg", ".oga", ".opus", ".mp3", ".m4a", ".wav", ".webm", ".mp4"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript", nargs="?", help="стенограмма .txt")
    ap.add_argument("--audio", help="папка с аудиофайлами")
    ap.add_argument("--date", required=True, help="дата планёрки ГГГГ-ММ-ДД")
    ap.add_argument("--title", default="")
    ap.add_argument("--data", default=os.getenv("DATA_DIR", "data"))
    a = ap.parse_args(argv)
    if not a.transcript and not a.audio:
        a.transcript = str(DEMO)  # учебная планёрка 23.11.2026

    directory = Directory(HERE / "participants.json")
    svc = MeetingService(HERE / a.data, directory)  # относительный путь — от папки бота
    chat = 0  # «чат» офлайн-прогона
    y, m, d = a.date.split("-")
    svc.start(chat, f"{d}.{m}.{y} {a.title}".strip())
    if a.transcript:
        for i, line in enumerate(Path(a.transcript).read_text(encoding="utf-8-sig").splitlines()):
            if i == 0 and directory.split_speaker(line)[0] is None:
                continue  # первая строка без «Фамилия:» — шапка стенограммы
            if line.strip():
                svc.add(chat, 0, "Стенограмма", line, "file")
    if a.audio:
        import asr

        hint = ", ".join(directory.names()) + ". " + directory.glossary
        for f in sorted(Path(a.audio).iterdir()):
            if f.suffix.lower() in AUDIO:
                text, sec = asr.transcribe(str(f), os.getenv("WHISPER_MODEL", "small"), hint)
                _, who = svc.add(chat, 0, "Голос", text, "voice", sec)
                print(f"🎙 {f.name} ({sec:.0f} с) → {who}: {text}")
    res = svc.process(chat)
    print(res.summary)
    print("\n".join(res.personal.values()))
    print(f"\nФайлы: {res.folder}")
    return res


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
