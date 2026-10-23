# -*- coding: utf-8 -*-
"""Telegram-бот «Протоколист планёрок».

Запуск: python bot.py   (настройки — в файле .env рядом, образец .env.example)

Команды:
  /new [ДД.ММ.ГГГГ] [название] — начать планёрку
  (дальше просто пишите или наговаривайте голосовые; начните реплику с фамилии,
   например «Ахметов. Пальцы муфты придут завтра», — и она запишется за Ахметовым)
  /status   — что уже собрано
  /undo     — убрать последнюю реплику
  /protocol — составить протокол и планы работ
  /iam Фамилия — привязать себя к участнику, чтобы получать личный план
  /cancel   — сбросить планёрку
"""
import asyncio
import logging
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
                          filters)

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

import asr  # noqa: E402  (после load_dotenv)
import llm  # noqa: E402
from meeting import Directory, fmt_date  # noqa: E402
from service import MeetingService  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

DIRECTORY = Directory(HERE / "participants.json")
SERVICE = MeetingService(HERE / os.getenv("DATA_DIR", "data"), DIRECTORY)  # относительный — от папки бота
WHISPER_SIZE = os.getenv("WHISPER_MODEL", "small")
ASR_HINT = ", ".join(DIRECTORY.names()) + ". " + DIRECTORY.glossary
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x}
LAST_RESULT = {}  # chat_id → Result последней обработки (для кнопки «Разослать»)


def allowed(update: Update) -> bool:
    return not ALLOWED or update.effective_user.id in ALLOWED


def display_name(update: Update) -> str:
    u = update.effective_user
    return " ".join(x for x in [u.last_name, u.first_name] if x) or u.username or str(u.id)


async def deny(update: Update):
    await update.effective_message.reply_text(
        f"Нет доступа. Ваш Telegram id: {update.effective_user.id} — передайте его лектору, "
        "чтобы он добавил его в ALLOWED_USER_IDS.")


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Я веду протокол планёрки.\n\n"
        "1) /new — начать (можно /new 23.11.2026 Планёрка службы ТО)\n"
        "2) Пишите или отправляйте голосовые. Начните с фамилии — «Ахметов. …» — и реплика запишется за ним.\n"
        "   Можно прислать и запись всей планёрки аудиофайлом или стенограмму .txt.\n"
        "3) /protocol — получите протокол .docx, планы работ .xlsx и личные планы участникам.\n\n"
        "/status — что собрано, /undo — убрать последнюю реплику, /iam Фамилия — получать свой план в личку.\n"
        f"Ваш Telegram id: {update.effective_user.id}")


async def cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    m = SERVICE.start(update.effective_chat.id, " ".join(ctx.args))
    await update.message.reply_text(f"🟢 Начата: {m.title}, {fmt_date(m.date)}. Жду реплики — текстом или голосом.")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m = SERVICE.active(update.effective_chat.id)
    if not m:
        return await update.message.reply_text("Планёрка не начата. Команда /new.")
    s = m.stats()
    last = "\n".join(f"• {r.speaker}: {r.text[:60]}" for r in m.remarks[-5:])
    await update.message.reply_text(
        f"{m.title}, {fmt_date(m.date)}\nРеплик: {s['remarks']} (голосом {s['voice']}, {s['voice_minutes']} мин)\n"
        f"Говорили: {', '.join(s['speakers']) or '—'}\n\nПоследние:\n{last}")


async def cmd_undo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    r = SERVICE.undo(update.effective_chat.id)
    await update.message.reply_text(f"↩ Убрал: {r}" if r else "Убирать нечего.")


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    ok = SERVICE.cancel(update.effective_chat.id)
    await update.message.reply_text("Планёрка сброшена." if ok else "Активной планёрки нет.")


async def cmd_iam(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    who = " ".join(ctx.args)
    name = SERVICE.bind(update.effective_user.id, who) if who else None
    if not name:
        return await update.message.reply_text("Напишите так: /iam Ахметов\nУчастники: " + ", ".join(DIRECTORY.names()))
    await update.message.reply_text(f"Готово: вы — {name}. Личные планы буду присылать сюда.")


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    _, speaker = SERVICE.add(update.effective_chat.id, update.effective_user.id, display_name(update),
                             update.message.text, "text")
    await update.message.reply_text(f"✍ {speaker}", disable_notification=True)


async def on_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Голосовое, кружок, аудиофайл: скачать → расшифровать локально → добавить реплику."""
    if not allowed(update):
        return await deny(update)
    msg = update.message
    media = msg.voice or msg.audio or msg.video_note or msg.document
    source = "voice" if (msg.voice or msg.video_note) else "audio"
    await ctx.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audio"
        f = await media.get_file()  # лимит Telegram для ботов — 20 МБ
        await f.download_to_drive(path)
        try:
            text, seconds = await asyncio.to_thread(asr.transcribe, str(path), WHISPER_SIZE, ASR_HINT)
        except Exception as e:  # битый файл, нет ffmpeg/модели
            log.exception("Ошибка распознавания")
            return await msg.reply_text(f"Не смог расшифровать: {e}")
    if not text:
        return await msg.reply_text("Речь не распознана — попробуйте ближе к микрофону.")
    _, speaker = SERVICE.add(msg.chat_id, update.effective_user.id, display_name(update), text, source, seconds)
    await msg.reply_text(f"🎙 {speaker} ({seconds:.0f} с): {text}", disable_notification=True)


async def on_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """.txt — готовая стенограмма (строки «Фамилия: текст»); аудиофайл — как голосовое."""
    if not allowed(update):
        return await deny(update)
    doc = update.message.document
    if (doc.mime_type or "").startswith(("audio/", "video/")):
        return await on_audio(update, ctx)
    if not (doc.file_name or "").lower().endswith(".txt"):
        return await update.message.reply_text("Принимаю .txt со стенограммой или аудиофайл.")
    data = await (await doc.get_file()).download_as_bytearray()
    text = data.decode("utf-8-sig", errors="replace")
    n = 0
    for line in text.splitlines():
        if line.strip():
            SERVICE.add(update.effective_chat.id, update.effective_user.id, display_name(update), line, "file")
            n += 1
    await update.message.reply_text(f"📄 Добавил строк из файла: {n}. Дальше /protocol.")


async def cmd_protocol(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    chat = update.effective_chat.id
    await update.message.reply_text("⏳ Составляю протокол… (обычно 20–60 секунд)")
    await ctx.bot.send_chat_action(chat, ChatAction.UPLOAD_DOCUMENT)
    try:
        res = await asyncio.to_thread(SERVICE.process, chat)
    except llm.LLMError as e:
        return await update.message.reply_text(f"❌ {e}")
    LAST_RESULT[chat] = res
    await update.message.reply_text(res.summary)
    for p in (res.docx, res.xlsx, res.transcript):
        with open(p, "rb") as fh:
            await ctx.bot.send_document(chat, fh, filename=p.name)
    bound = [p for p in res.personal if p in SERVICE.bindings]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"📨 Разослать личные планы ({len(bound)})", callback_data="send")],
                               [InlineKeyboardButton("👀 Показать планы здесь", callback_data="show")]])
    await update.message.reply_text(
        "Проверьте протокол. Отметки ⚠ — места, где ИИ мог ошибиться.\n"
        f"Участники с привязкой /iam: {', '.join(bound) or 'пока никого'}.", reply_markup=kb)


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if ALLOWED and q.from_user.id not in ALLOWED:
        return
    res = LAST_RESULT.get(q.message.chat_id)
    if not res:
        return await q.message.reply_text("Сначала /protocol.")
    if q.data == "show":
        for text in res.personal.values():
            await q.message.reply_text(text)
        return
    sent, failed = [], []
    for person, text in res.personal.items():
        uid = SERVICE.bindings.get(person)
        if not uid:
            continue
        try:
            await ctx.bot.send_message(uid, text)
            sent.append(person)
        except Exception:  # человек не нажимал /start у бота — писать ему бот не может
            log.exception("Не отправлено %s", person)
            failed.append(person)
    await q.message.reply_text(f"📨 Отправлено: {', '.join(sent) or 'никому'}"
                               + (f"\nНе дошло: {', '.join(failed)} (пусть откроют бота и нажмут /start)" if failed else ""))


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Нет TELEGRAM_BOT_TOKEN в .env — получите токен у @BotFather")
    app = build_app(token)
    log.info("Бот запущен. LLM: %s, распознавание: whisper-%s", os.getenv("LLM_BACKEND", "claude"), WHISPER_SIZE)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


def build_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("undo", cmd_undo))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("iam", cmd_iam))
    app.add_handler(CommandHandler("protocol", cmd_protocol))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE, on_audio))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


if __name__ == "__main__":
    main()
