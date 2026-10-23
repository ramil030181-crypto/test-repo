# -*- coding: utf-8 -*-
"""Проверка ответа модели обычным кодом, без ИИ.

Модель может ошибиться: выдумать поручение, перепутать дату, назначить
не того. Проверка не исправляет молча — она ставит отметку, и человек решает.
"""
import datetime as dt
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List

from meeting import WEEKDAYS, Directory, Meeting
from schema import Protocol


@dataclass
class TaskCheck:
    n: int
    flags: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.flags


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\wё ]", " ", s.lower().replace("ё", "е"))).strip()


def quote_score(quote: str, transcript: str) -> float:
    """Насколько цитата похожа на какой-то кусок стенограммы (1.0 — дословно)."""
    q, t = _norm(quote), _norm(transcript)
    if not q:
        return 0.0
    if q in t:
        return 1.0
    words, n = t.split(), len(q.split())
    best = 0.0
    for i in range(0, max(1, len(words) - n + 1)):
        window = " ".join(words[i:i + n])
        best = max(best, SequenceMatcher(None, q, window).ratio())
    return best


def check(protocol: Protocol, meeting: Meeting, directory: Directory) -> List[TaskCheck]:
    transcript = meeting.transcript()
    known = set(directory.names())
    day0 = dt.date.fromisoformat(meeting.date)
    out = []
    for i, t in enumerate(protocol.tasks, 1):
        c = TaskCheck(i)
        if not t.assignees:
            c.flags.append("нет ответственного")
        for a in t.assignees:
            if a not in known:
                c.flags.append(f"«{a}» нет в справочнике участников")
        if not t.due_date:
            c.flags.append("срок не назван — уточнить")
        else:
            try:
                d = dt.date.fromisoformat(t.due_date)
                if d < day0:
                    c.flags.append(f"срок {d:%d.%m.%Y} раньше даты планёрки")
                elif d.weekday() >= 5:
                    c.flags.append(f"срок выпал на выходной ({WEEKDAYS[d.weekday()]})")
            except ValueError:
                c.flags.append(f"срок «{t.due_date}» не похож на дату")
        score = quote_score(t.quote, transcript)
        if score < 0.75:
            c.flags.append(f"цитаты нет в стенограмме (совпадение {score:.0%}) — возможно, выдумано")
        out.append(c)
    return out


def due_sort_key(task) -> str:
    return task.due_date or "9999-99-99"
