# -*- coding: utf-8 -*-
"""Логика бота без Telegram: планёрки по чатам, привязка участников, обработка.

bot.py только передаёт сюда сообщения и отправляет результат обратно.
"""
import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import llm
import render
import verify
from meeting import Directory, Meeting, fmt_date
from schema import Protocol

HERE = Path(__file__).parent


@dataclass
class Result:
    protocol: Protocol
    checks: List[verify.TaskCheck]
    folder: Path
    docx: Path
    xlsx: Path
    transcript: Path
    summary: str
    personal: Dict[str, str]  # участник → текст личного плана


class MeetingService:
    def __init__(self, data_dir: Path, directory: Directory, tz_offset_hours: int = 5):
        self.data = Path(data_dir)
        self.dir = directory
        self.tz = dt.timezone(dt.timedelta(hours=tz_offset_hours))  # Казахстан: UTC+5
        self.bindings_path = self.data / "bindings.json"
        self.bindings: Dict[str, int] = self._load_bindings()

    # --- планёрка в чате ------------------------------------------------
    def _path(self, chat_id: int) -> Path:
        return self.data / "active" / f"{chat_id}.json"

    def active(self, chat_id: int) -> Optional[Meeting]:
        p = self._path(chat_id)
        return Meeting.load(p) if p.exists() else None

    def start(self, chat_id: int, arg: str = "") -> Meeting:
        """/new [ДД.ММ.ГГГГ] [название] — дата по умолчанию сегодня."""
        date = dt.datetime.now(self.tz).date()
        title = self.dir.data.get("meeting_name", "Планёрка")
        m = re.match(r"\s*(\d{2})\.(\d{2})\.(\d{4})\s*(.*)$", arg or "")
        if m:
            date = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            arg = m.group(4)
        if arg.strip():
            title = arg.strip()
        meeting = Meeting(date.isoformat(), title)
        meeting.save(self._path(chat_id))
        return meeting

    def add(self, chat_id: int, user_id: int, display: str, text: str, source: str = "text",
            seconds: float = 0.0) -> tuple[Meeting, str]:
        meeting = self.active(chat_id) or self.start(chat_id)
        speaker, body = self.dir.split_speaker(text)
        speaker = speaker or self.speaker_for(user_id, display)
        meeting.add(speaker, body, source, dt.datetime.now(self.tz).strftime("%H:%M"), seconds)
        meeting.save(self._path(chat_id))
        return meeting, speaker

    def undo(self, chat_id: int) -> Optional[str]:
        meeting = self.active(chat_id)
        if not meeting or not meeting.remarks:
            return None
        r = meeting.remarks.pop()
        meeting.save(self._path(chat_id))
        return f"{r.speaker}: {r.text[:80]}"

    def cancel(self, chat_id: int) -> bool:
        p = self._path(chat_id)
        if p.exists():
            p.unlink()
            return True
        return False

    # --- участники -------------------------------------------------------
    def _load_bindings(self) -> Dict[str, int]:
        if self.bindings_path.exists():
            return json.loads(self.bindings_path.read_text(encoding="utf-8"))
        return {}

    def bind(self, user_id: int, who: str) -> Optional[str]:
        p = self.dir.find(who)
        if not p:
            return None
        self.bindings[p["name"]] = user_id
        self.bindings_path.parent.mkdir(parents=True, exist_ok=True)
        self.bindings_path.write_text(json.dumps(self.bindings, ensure_ascii=False, indent=1), encoding="utf-8")
        return p["name"]

    def speaker_for(self, user_id: int, display: str) -> str:
        """Автор сообщения → участник: сначала по привязке /iam, потом по имени в Telegram."""
        for name, uid in self.bindings.items():
            if uid == user_id:
                return name
        p = self.dir.find(display)
        return p["name"] if p else display

    # --- обработка -------------------------------------------------------
    def process(self, chat_id: int) -> Result:
        meeting = self.active(chat_id)
        if not meeting or not meeting.remarks:
            raise llm.LLMError("В планёрке нет ни одной реплики")
        protocol = llm.make_protocol(meeting, self.dir)
        checks = verify.check(protocol, meeting, self.dir)
        stamp = dt.datetime.now(self.tz).strftime("%H%M%S")
        folder = self.data / "results" / f"{meeting.date}_{stamp}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "стенограмма.txt").write_text(meeting.transcript(), encoding="utf-8")
        (folder / "ответ_модели.json").write_text(protocol.model_dump_json(indent=1), encoding="utf-8")
        meeting.save(folder / "реплики.json")
        d = fmt_date(meeting.date)
        docx = folder / f"Протокол_планёрки_{d}.docx"
        xlsx = folder / f"Планы_работ_{d}.xlsx"
        render.protocol_docx(protocol, checks, meeting, self.dir.data.get("organization", ""), docx)
        render.plans_xlsx(protocol, checks, xlsx)
        personal = {p: render.person_message(p, items, protocol) for p, items in render.plans_by_person(protocol).items()}
        return Result(protocol, checks, folder, docx, xlsx, folder / "стенограмма.txt",
                      render.summary_message(protocol, checks), personal)
