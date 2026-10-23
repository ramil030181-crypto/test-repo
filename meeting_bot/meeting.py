# -*- coding: utf-8 -*-
"""Планёрка как набор реплик: кто сказал, что сказал, откуда (текст или голос).

Здесь нет ни Telegram, ни модели — только данные. Поэтому этот слой легко
проверять тестами и запускать без интернета (offline.py).
"""
import datetime as dt
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WD_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


@dataclass
class Remark:
    speaker: str
    text: str
    source: str = "text"  # text | voice | audio | file
    at: str = ""  # время сообщения ЧЧ:ММ
    seconds: float = 0.0  # длительность голосового


@dataclass
class Meeting:
    date: str  # ГГГГ-ММ-ДД
    title: str = "Планёрка службы ТО"
    remarks: List[Remark] = field(default_factory=list)

    def add(self, speaker: str, text: str, source: str = "text", at: str = "", seconds: float = 0.0):
        text = (text or "").strip()
        if text:
            self.remarks.append(Remark(speaker, text, source, at, seconds))

    def transcript(self) -> str:
        lines = [f"{self.title}, {fmt_date(self.date)}. Стенограмма собрана ботом из сообщений участников."]
        for r in self.remarks:
            mark = " [голос]" if r.source in ("voice", "audio") else ""
            lines.append(f"{r.speaker}{mark}: {r.text}")
        return "\n".join(lines)

    def stats(self) -> dict:
        voice = [r for r in self.remarks if r.source in ("voice", "audio")]
        return {
            "remarks": len(self.remarks),
            "voice": len(voice),
            "voice_minutes": round(sum(r.seconds for r in voice) / 60, 1),
            "speakers": sorted({r.speaker for r in self.remarks}),
        }

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Meeting":
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(d["date"], d.get("title", "Планёрка службы ТО"), [Remark(**r) for r in d["remarks"]])


def fmt_date(iso: str) -> str:
    return dt.date.fromisoformat(iso).strftime("%d.%m.%Y")


def calendar_hint(iso: str, weeks: int = 6) -> str:
    """Календарь для модели: модели плохо считают дни недели, поэтому даём готовый."""
    start = dt.date.fromisoformat(iso)
    out = [f"Сегодня (дата планёрки): {start:%d.%m.%Y}, {WEEKDAYS[start.weekday()]}."]
    monday = start - dt.timedelta(days=start.weekday())
    for w in range(weeks):
        days = [monday + dt.timedelta(days=7 * w + i) for i in range(7)]
        label = "эта неделя" if w == 0 else ("следующая неделя" if w == 1 else f"через {w} нед.")
        out.append(f"{label}: " + ", ".join(f"{WD_SHORT[d.weekday()]} {d:%d.%m}" for d in days))
    return "\n".join(out)


# --- справочник участников -------------------------------------------------

class Directory:
    def __init__(self, path: Path):
        self.data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.people = self.data["participants"]

    @property
    def glossary(self) -> str:
        return self.data.get("glossary", "")

    def names(self) -> List[str]:
        return [p["name"] for p in self.people]

    def find(self, word: str) -> Optional[dict]:
        w = _norm(word)
        for p in self.people:
            if w in {_norm(a) for a in p["aliases"] + [p["name"], p["full"]]}:
                return p
        return None

    def split_speaker(self, text: str):
        """«Ахметов. Когда придут пальцы…» → ("Ахметов Р.С.", "Когда придут пальцы…").

        Так один человек может озвучить реплики разных участников: достаточно
        начать голосовое с фамилии. Возвращает (None, text), если фамилии в начале нет.
        """
        m = re.match(r"^\s*(?:говорит\s+)?([А-ЯЁа-яё][А-ЯЁа-яё\.\- ]{1,40}?)\s*[:.,—–-]\s+(.+)$", text, re.S)
        if m and (p := self._speaker_tag(m.group(1))):
            return p["name"], m.group(2).strip()
        # распознавание иногда теряет точку после фамилии: «Ахметов как придут пальцы»
        m = re.match(r"^\s*([А-ЯЁа-яё]+)\s+(.+)$", text, re.S)
        if m and (p := self._speaker_tag(m.group(1), surname_only=True)):
            return p["name"], m.group(2).strip()
        return None, text

    def _speaker_tag(self, head: str, surname_only: bool = False) -> Optional[dict]:
        head = _norm(head)
        for p in self.people:
            # только фамилия / полное имя: «Ирина, что по бюджету?» — обращение, а не говорящий
            surname = _norm(p["name"].split()[0])
            if surname_only:
                if head == surname and surname != "менеджер":
                    return p
                continue
            tags = {_norm(p["name"]), _norm(p["full"]), surname}
            tags |= {_norm(a) for a in p["aliases"] if _norm(a).split()[0] == surname}
            if head in tags:
                return p
        return None

    def describe(self) -> str:
        return "\n".join(f"- {p['name']} — {p['position']}" + (" (председатель)" if p.get("chair") else "")
                         for p in self.people)


def _norm(s: str) -> str:
    return re.sub(r"[^а-яёa-z0-9 ]", "", s.lower().replace("ё", "е")).strip()
