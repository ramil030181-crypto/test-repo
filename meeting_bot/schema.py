# -*- coding: utf-8 -*-
"""Структура протокола, которую модель обязана вернуть (JSON по этой схеме).

Схема — это «контракт» между ботом и моделью: модель заполняет поля,
бот проверяет и оформляет. Поменяли поле здесь — поменяйте и инструкцию
в prompt_protocol.txt.
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class Attendee(BaseModel):
    name: str = Field(description="Фамилия И.О. как в справочнике участников")
    role: str = Field(description="Должность или роль на планёрке")


class Task(BaseModel):
    task: str = Field(description="Поручение: глагол + объект + результат")
    assignees: List[str] = Field(description="Ответственные (Фамилия И.О.); пусто, если не назначен")
    due_date: Optional[str] = Field(description="Итоговый срок ГГГГ-ММ-ДД; null, если срок не прозвучал")
    due_text: str = Field(description="Как срок прозвучал на планёрке, дословно ('до пятницы')")
    quote: str = Field(description="Дословная цитата из стенограммы, на которой основано поручение")


class OpenQuestion(BaseModel):
    question: str
    why_open: str = Field(description="Почему не стало поручением: нет ответственного, нет срока, отложено")


class Protocol(BaseModel):
    title: str
    date: str = Field(description="Дата планёрки ГГГГ-ММ-ДД")
    chair: str = Field(description="Председатель (Фамилия И.О.)")
    attendees: List[Attendee]
    agenda: List[str] = Field(description="Вопросы повестки, 3–6 пунктов")
    decisions: List[str] = Field(description="Принятые решения (не поручения), коротко")
    tasks: List[Task]
    open_questions: List[OpenQuestion]
    skipped: List[str] = Field(description="Что сознательно не вошло в протокол (шутки, реплики вне повестки)")
