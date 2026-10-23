# -*- coding: utf-8 -*-
"""Расшифровка голоса локально (faster-whisper). Аудио не покидает компьютер.

Первый запуск скачивает модель (small ≈ 0,5 ГБ, medium ≈ 1,5 ГБ) и дальше
работает без интернета. На обычном ноутбуке без видеокарты модель small
расшифровывает минуту речи примерно за 10–30 секунд.
"""
import logging

log = logging.getLogger(__name__)
_model = None


def _get_model(size: str):
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # тяжёлый импорт — только когда нужен

        log.info("Загружаю модель распознавания %s (первый раз — скачивание)…", size)
        _model = WhisperModel(size, device="cpu", compute_type="int8")
    return _model


def transcribe(path: str, size: str = "small", hint: str = "") -> tuple[str, float]:
    """Возвращает (текст, длительность в секундах).

    hint — подсказка распознаванию: имена и обозначения оборудования.
    Без неё «P-101B» превращается в «пэ сто один бэ», а «Сейткали» — во что угодно.
    """
    model = _get_model(size)
    segments, info = model.transcribe(path, language="ru", vad_filter=True, initial_prompt=hint or None, beam_size=5)
    text = " ".join(s.text.strip() for s in segments).strip()
    return text, float(info.duration)
