import asyncio
import csv
import html
import logging
import os
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    CallbackQuery,
    ChatJoinRequest,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("")  # токен от @BotFather
if not TOKEN:
    raise SystemExit("Задай переменную окружения BOT_TOKEN")

# ============================================================
#  ЗАГЛУШКИ — ЗАПОЛНИ ПОД СЕБЯ
# ============================================================

# Ссылки на страницы в Telegraph (telegra.ph). Пока пусто — ссылка просто не показывается.
TERMS_URL = "https://www.softpaws.fun/"  # «Условия доступа и подтверждение возраста»
RULES_URL = "https://www.softpaws.fun/"  # «Правила чата» (полная версия)

# Меняй дату каждый раз, когда правишь текст условий на Telegraph.
# Она пишется в лог согласий — так видно, с какой версией текста человек согласился.
TERMS_VERSION = "18.11.2026"

# Короткие правила — бот покажет их человеку сразу после одобрения заявки.
# Поддерживается HTML: <b>жирный</b>, <i>курсив</i>
RULES_SHORT = """📜 <b>Правила чата</b>

1. [вписать правило — что можно]
2. [вписать правило — что нельзя]
3. [вписать правило — как общаться]
4. [вписать последствия: предупреждение / бан]

Если что-то непонятно — пиши администрации: [@контакт]"""

# Контакт администратора — показывается тем, кому отказали (нажали «Мне нет 18»).
ADMIN_CONTACT = "[@контакт_админа]"

# Telegram ID тех, кто может пользоваться командами /status, /check, /unban, /log.
# Свой ID можно узнать, отправив боту в личку команду /id.
# Чтобы добавить админа/модератора — впиши его ID новой строкой (не забудь запятую в конце).
ADMIN_IDS: set[int] = {
    999010272,  # владелец
    # 000000000,  # ЗАГЛУШКА: ID второго админа или модератора (убери # и впиши ID)
    # 000000000,  # ЗАГЛУШКА: ID ещё одного админа
}

# Файл, куда пишутся ответы пользователей (кто, когда, что нажал, какая версия условий)
CONSENT_LOG = "consent_log.csv"

# ============================================================

dp = Dispatcher()
START_TIME = datetime.now(timezone.utc)


def links_block() -> str:
    parts = []
    if TERMS_URL:
        parts.append(f'📄 <a href="{TERMS_URL}">Условия доступа и подтверждение возраста</a>')
    if RULES_URL:
        parts.append(f'📜 <a href="{RULES_URL}">Правила чата</a>')
    return "\n".join(parts)


def log_event(user_id: int, username: str, chat_id: int, answer: str) -> None:
    """Дописываем строку в лог. Это твоё доказательство добросовестности."""
    is_new = not os.path.exists(CONSENT_LOG)
    with open(CONSENT_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["utc_time", "user_id", "username", "chat_id", "terms_version", "answer"])
        w.writerow(
            [
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                user_id,
                username,
                chat_id,
                TERMS_VERSION,
                answer,
            ]
        )


def log_consent(user, chat_id: int, answer: str) -> None:
    """Записываем факт подтверждения/отказа."""
    log_event(user.id, user.username or "", chat_id, answer)


def find_declined(query: str) -> list[tuple[int, int, str]]:
    """Ищем в логе тех, кому отказали. query — Telegram ID или @username.
    Возвращает список (user_id, chat_id, username)."""
    if not os.path.exists(CONSENT_LOG):
        return []
    q = query.lstrip("@").lower()
    found: dict[tuple[int, int], str] = {}
    with open(CONSENT_LOG, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["answer"] != "declined_under18":
                continue
            if row["user_id"] == q or (row["username"] and row["username"].lower() == q):
                found[(int(row["user_id"]), int(row["chat_id"]))] = row["username"]
    return [(u, c, n) for (u, c), n in found.items()]


@dp.chat_join_request()
async def on_join_request(req: ChatJoinRequest, bot: Bot):
    """Кто-то подал заявку на вступление — пишем ему в личку."""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Мне есть 18, принимаю условия",
                    callback_data=f"age:yes:{req.chat.id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Мне нет 18",
                    callback_data=f"age:no:{req.chat.id}",
                )
            ],
        ]
    )

    text = (
        f"Привет! Ты подал(а) заявку в «{html.escape(req.chat.title or '')}».\n\n"
        "🔞 Здесь обсуждаются темы для взрослых (18+).\n"
        "Нажимая «Мне есть 18, принимаю условия», ты заявляешь, что:\n"
        "• тебе исполнилось 18 лет (или возраст совершеннолетия по закону твоей страны, если он выше);\n"
        "• ты ознакомился(ась) с Условиями и Правилами и принимаешь их;\n"
        "• ты сообщаешь свой возраст добровольно и правдиво. Администрация не проверяет документы "
        "и полагается на твоё заявление.\n\n"
        "Заведомо ложное подтверждение — нарушение условий; ответственность за него лежит на тебе.\n"
    )
    links = links_block()
    if links:
        text += "\n" + links

    try:
        await bot.send_message(
            req.user_chat_id,
            text,
            reply_markup=kb,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except TelegramForbiddenError:
        logging.warning("Не смог написать пользователю %s", req.from_user.id)


@dp.callback_query(F.data.startswith("age:"))
async def on_answer(cb: CallbackQuery, bot: Bot):
    _, answer, chat_id = cb.data.split(":")
    chat_id = int(chat_id)
    user = cb.from_user  # заявку обрабатываем для того, кто нажал кнопку

    try:
        if answer == "yes":
            await bot.approve_chat_join_request(chat_id, user.id)
            log_consent(user, chat_id, "confirmed_18plus")
            text = "✅ Спасибо! Заявка одобрена, добро пожаловать!\n\n" + RULES_SHORT
        else:
            await bot.decline_chat_join_request(chat_id, user.id)
            await bot.ban_chat_member(chat_id, user.id)  # блокируем повторный вход
            log_consent(user, chat_id, "declined_under18")
            text = (
                "❌ Заявка отклонена, доступ закрыт.\n\n"
                f"Если у тебя есть вопросы, напиши администрации: {ADMIN_CONTACT}"
            )
    except TelegramBadRequest as e:
        logging.warning("Ошибка обработки заявки: %s", e)
        text = "Заявка уже обработана или истекла."

    await cb.message.edit_text(
        text, link_preview_options=LinkPreviewOptions(is_disabled=True)
    )  # убираем кнопки
    await cb.answer()


async def require_admin(msg: Message) -> bool:
    """Пропускаем только тех, кто в ADMIN_IDS."""
    if msg.from_user.id in ADMIN_IDS:
        return True
    await msg.answer("⛔ Нет доступа.")
    return False


def read_log() -> list[dict]:
    if not os.path.exists(CONSENT_LOG):
        return []
    with open(CONSENT_LOG, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_time(value: str):
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def fmt_duration(td) -> str:
    total = int(td.total_seconds())
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    return (f"{days} д " if days else "") + f"{hours} ч {minutes} мин"


def event_kind(answer: str):
    if answer == "confirmed_18plus":
        return "yes"
    if answer == "declined_under18":
        return "no"
    if answer.startswith("unbanned_by_"):
        return "unban"
    return None


def describe(answer: str) -> str:
    kind = event_kind(answer)
    if kind == "yes":
        return "✅ подтвердил(а) 18+"
    if kind == "no":
        return "❌ отказ (нет 18), бан"
    if kind == "unban":
        return f"♻️ разбан (админ {answer.removeprefix('unbanned_by_')})"
    return html.escape(answer)


async def bot_rights(bot: Bot, chat_id: int) -> str:
    """Проверяем, что у бота в чате есть нужные права."""
    try:
        title = (await bot.get_chat(chat_id)).title or str(chat_id)
        me = await bot.get_chat_member(chat_id, bot.id)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        return f"• {chat_id}: ⚠️ нет доступа ({html.escape(e.message)})"
    name = html.escape(title)
    if me.status == "creator":
        return f"• {name}: ✅ владелец"
    if me.status != "administrator":
        return f"• {name}: ⚠️ бот не админ"
    missing = []
    if not me.can_invite_users:
        missing.append("приглашение пользователей")
    if not me.can_restrict_members:
        missing.append("блокировка пользователей")
    if missing:
        return f"• {name}: ⚠️ нет прав: {', '.join(missing)}"
    return f"• {name}: ✅ права в порядке"


ADMIN_COMMANDS = [
    BotCommand(command="status", description="Статус бота и статистика"),
    BotCommand(command="check", description="История человека: /check @username или ID"),
    BotCommand(command="unban", description="Разбанить: /unban @username или ID"),
    BotCommand(command="log", description="Скачать журнал согласий (CSV)"),
    BotCommand(command="id", description="Показать мой Telegram ID"),
    BotCommand(command="help", description="Список команд"),
]


@dp.message(Command("start", "help"), F.chat.type == "private")
async def cmd_start(msg: Message):
    """Для обычных людей — короткая подсказка, для админов — список команд."""
    if msg.from_user.id in ADMIN_IDS:
        await msg.answer(
            "Команды администратора:\n"
            "/status — статус бота, статистика, проверка прав в чатах\n"
            "/check <code>@username</code> или <code>ID</code> — история человека\n"
            "/unban <code>@username</code> или <code>ID</code> — разбанить\n"
            "/log — скачать журнал согласий (CSV)\n"
            "/id — показать твой Telegram ID"
        )
    else:
        await msg.answer(
            "Привет! Я бот проверки возраста.\n"
            "Чтобы вступить в чат, подай заявку по пригласительной ссылке "
            "Я сам напишу тебе и задам вопрос."
        )


@dp.message(Command("status"), F.chat.type == "private")
async def cmd_status(msg: Message, bot: Bot):
    """Работает ли бот, сколько заявок обработано, всё ли настроено."""
    if not await require_admin(msg):
        return

    rows = read_log()
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    def count(kind: str, since=None) -> int:
        n = 0
        for r in rows:
            if event_kind(r["answer"]) != kind:
                continue
            if since is not None:
                t = parse_time(r["utc_time"])
                if t is None or t < since:
                    continue
            n += 1
        return n

    def flag(done: bool) -> str:
        return "✅" if done else "⚠️ не заполнено"

    lines = [
        "📊 <b>Статус бота</b>",
        f"⏱ Работает: {fmt_duration(now - START_TIME)}",
        f"🔖 Версия условий: {html.escape(TERMS_VERSION)}",
        "",
        "<b>Всего:</b> "
        f"✅ {count('yes')} подтвердили · ❌ {count('no')} отказов · ♻️ {count('unban')} разбанов",
        "<b>За 24 часа:</b> "
        f"✅ {count('yes', day_ago)} · ❌ {count('no', day_ago)} · ♻️ {count('unban', day_ago)}",
    ]
    if rows:
        last = rows[-1]
        lines.append(f"🕒 Последнее событие: {last['utc_time']} UTC ({describe(last['answer'])})")
    else:
        lines.append("🕒 Журнал пока пуст.")

    lines += [
        "",
        "<b>Настройки:</b>",
        f"• Условия (TERMS_URL): {flag(bool(TERMS_URL))}",
        f"• Правила (RULES_URL): {flag(bool(RULES_URL))}",
        f"• Короткие правила (RULES_SHORT): {flag('[' not in RULES_SHORT)}",
        f"• Контакт админа (ADMIN_CONTACT): {flag('[' not in ADMIN_CONTACT)}",
        f"• Админов в списке: {len(ADMIN_IDS)}",
    ]

    chat_ids = sorted({int(r["chat_id"]) for r in rows if r.get("chat_id")})[:10]
    if chat_ids:
        lines += ["", "<b>Чаты из журнала (права бота):</b>"]
        for chat_id in chat_ids:
            lines.append(await bot_rights(bot, chat_id))
    else:
        lines += ["", "Чаты появятся здесь после первой обработанной заявки."]

    await msg.answer("\n".join(lines), link_preview_options=LinkPreviewOptions(is_disabled=True))


@dp.message(Command("log"), F.chat.type == "private")
async def cmd_log(msg: Message):
    """Присылает файл журнала согласий — готовая резервная копия."""
    if not await require_admin(msg):
        return
    if not os.path.exists(CONSENT_LOG):
        await msg.answer("Журнал пока пуст.")
        return
    await msg.answer_document(FSInputFile(CONSENT_LOG), caption="Журнал согласий (UTC)")


@dp.message(Command("check"), F.chat.type == "private")
async def cmd_check(msg: Message, command: CommandObject):
    """/check @username или /check USER_ID — что бот знает об этом человеке."""
    if not await require_admin(msg):
        return
    if not command.args:
        await msg.answer(
            "Как пользоваться:\n<code>/check @username</code>\n<code>/check 123456789</code>"
        )
        return
    q = command.args.strip().lstrip("@").lower()
    found = [
        r
        for r in read_log()
        if r["user_id"] == q or (r["username"] and r["username"].lower() == q)
    ]
    if not found:
        await msg.answer("Ничего не найдено в журнале.")
        return
    lines = [f"🔎 Записей: {len(found)} (последние 10)"]
    for r in found[-10:]:
        who = f"@{html.escape(r['username'])}" if r["username"] else r["user_id"]
        lines.append(f"{r['utc_time']} · {who} · чат {r['chat_id']} · {describe(r['answer'])}")
    await msg.answer("\n".join(lines))


@dp.message(Command("id"), F.chat.type == "private")
async def cmd_id(msg: Message):
    """Показывает твой Telegram ID — его нужно вписать в ADMIN_IDS."""
    await msg.answer(f"Твой Telegram ID: <code>{msg.from_user.id}</code>")


@dp.message(Command("unban"), F.chat.type == "private")
async def cmd_unban(msg: Message, command: CommandObject, bot: Bot):
    """/unban @username   или   /unban USER_ID   или   /unban USER_ID CHAT_ID"""
    if not await require_admin(msg):
        return

    usage = (
        "Как пользоваться:\n"
        "<code>/unban @username</code>\n"
        "<code>/unban 123456789</code>\n"
        "<code>/unban 123456789 -1001234567890</code> (ID человека и ID чата)\n\n"
        "Первые два варианта ищут человека в логе отказов (consent_log.csv)."
    )
    args = (command.args or "").split()
    if not args or len(args) > 2:
        await msg.answer(usage)
        return

    targets: list[tuple[int, int, str]] = []
    if len(args) == 2:
        if all(a.lstrip("-").isdigit() for a in args):
            targets = [(int(args[0]), int(args[1]), "")]
    else:
        targets = find_declined(args[0])

    if not targets:
        await msg.answer(
            "Не нашла такого человека в логе отказов.\n"
            "Укажи ID человека и ID чата вручную.\n\n" + usage
        )
        return

    lines = []
    for user_id, chat_id, username in targets:
        try:
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            log_event(user_id, username, chat_id, f"unbanned_by_{msg.from_user.id}")
            lines.append(f"✅ {user_id} разбанен в чате {chat_id}")
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            lines.append(f"⚠️ {user_id} / чат {chat_id}: {e.message}")

    lines.append("\nТеперь человек может снова подать заявку по ссылке, и бот спросит про возраст ещё раз.")
    await msg.answer("\n".join(lines))


async def main():
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    for admin_id in ADMIN_IDS:  # меню команд (кнопка «/») только у админов
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logging.warning("Не удалось выставить меню для админа %s: %s", admin_id, e)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
