import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from aiogram.enums import ParseMode
import logging
import sys
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# ===== КОНФИГ =====
TELEGRAM_TOKEN = "8745386740:AAGdHJViFrQVcmzI968E0i5hyNvRtHaKDw4"
GROQ_API_KEY = "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"

storage = MemoryStorage()
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=storage)

# Состояния
class BotStates(StatesGroup):
    active = State()  # Бот активен
    inactive = State()  # Бот неактивен

# Для антиспама (чтоб не флудить подсказками)
hint_sent = {}  # Кому уже отправляли подсказку
last_command_time = {}
last_response_cache = {}

SYSTEM_PROMPT = """Ты - эксперт по сериалу «Очень странные дела» (Stranger Things). Твоя задача — помогать пользователям с вопросами о сериале, персонажах, сюжете, теориях и деталях.

ТВОИ ПРАВИЛА:
1. Отвечай всегда вежливо, с уважением, как настоящий фанат сериала.
2. Используй правильную пунктуацию: заглавные буквы, запятые, точки.
3. Знай всех персонажей, их имена актеров, способности и роли в сюжете.
4. Знай ключевые события по сезонам, локации (Хокинс, Изнанка, лаборатория).
5. Знай популярные фанатские теории и обсуждай их.
"""

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


async def ask_groq(question):
    """Отправка вопроса к Groq API"""
    cache_key = question[:100]
    if cache_key in last_response_cache:
        cache_time, cache_answer = last_response_cache[cache_key]
        if datetime.now() - cache_time < timedelta(minutes=5):
            return cache_answer
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question}
        ],
        "temperature": 0.9,
        "max_tokens": 500
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GROQ_API_URL, headers=headers, json=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    answer = result["choices"][0]["message"]["content"]
                    
                    last_response_cache[cache_key] = (datetime.now(), answer)
                    if len(last_response_cache) > 100:
                        oldest = min(last_response_cache.keys(), 
                                   key=lambda k: last_response_cache[k][0])
                        del last_response_cache[oldest]
                    
                    return answer
                else:
                    return "⚠️ Ошибка API, попробуй позже."
    except Exception as e:
        print(f"API Error: {e}")
        return "⚠️ Технические шоколадки."


@dp.message(CommandStart())
async def start_bot(msg: Message, state: FSMContext):
    """Старт"""
    await state.set_state(BotStates.inactive)
    await msg.answer(
        "👋 Привет! Я бот по сериалу **Stranger Things**.\n\n"
        "🔹 Напиши `/botst` чтобы активировать меня\n"
        "🔹 После активации смогу отвечать на вопросы о сериале\n"
        "🔹 `/botoff` - выключить меня"
    )


@dp.message(Command("botst"))
async def activate_bot(msg: Message, state: FSMContext):
    """Включение бота"""
    user_id = msg.from_user.id
    
    # Проверяем, может уже включен
    current_state = await state.get_state()
    if current_state == BotStates.active:
        await msg.reply("🤖 Бот уже активен! Используй /st чтобы задать вопрос.")
        return
    
    # Активируем
    await state.set_state(BotStates.active)
    
    # Красивое приветствие как ты просил
    await msg.reply(
        "🧙‍♂️ **Эксперт по Stranger Things активирован!**\n\n"
        "Привет! Я знаю всё о сериале «Очень странные дела». Спрашивай меня о персонажах, сюжете, теориях и деталях.\n\n"
        "📝 **Как пользоваться:**\n"
        "• Просто напиши `/st` и свой вопрос\n"
        "• Используй `/characters` чтобы увидеть список персонажей\n"
        "• Используй `/seasons` чтобы узнать о сезонах\n\n"
        "**Пример:**\n"
        "`/st Кто такой Векна?`",
        parse_mode=ParseMode.MARKDOWN
    )
    print(f"✅ Бот включен для {user_id}")


@dp.message(Command("botoff"))
async def deactivate_bot(msg: Message, state: FSMContext):
    """Выключение бота"""
    user_id = msg.from_user.id
    
    # Проверяем, может уже выключен
    current_state = await state.get_state()
    if current_state != BotStates.active:
        await msg.reply("🔴 Бот и так неактивен. Чтобы включить - /botst")
        return
    
    # Выключаем
    await state.set_state(BotStates.inactive)
    # Очищаем подсказки для этого юзера
    if user_id in hint_sent:
        del hint_sent[user_id]
    
    await msg.reply("🔴 **Бот выключен**\n\nЧтобы снова активировать - /botst", parse_mode=ParseMode.MARKDOWN)
    print(f"🔴 Бот выключен для {user_id}")


@dp.message(Command("st"))
async def st_command(msg: Message, state: FSMContext):
    """Команда для вопроса"""
    user_id = msg.from_user.id
    
    # Проверяем активен ли бот
    current_state = await state.get_state()
    if current_state != BotStates.active:
        # Не отвечаем вообще, просто игнорим
        return
    
    # Антиспам
    current_time = datetime.now()
    if user_id in last_command_time:
        if current_time - last_command_time[user_id] < timedelta(seconds=2):
            await msg.reply("⏳ Слишком быстро, дай секунду...")
            return
    
    last_command_time[user_id] = current_time
    
    # Получаем текст вопроса
    question = msg.text.replace('/st', '', 1).strip()
    
    if not question:
        await msg.reply(
            "❓ **Где вопрос?**\n\n"
            "Пример: `/st Кто такой Векна?`\n"
            "Или: `/st Расскажи про Оди`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if len(question) < 3:
        await msg.reply("❓ Слишком короткий вопрос. Задай нормальный!")
        return
    
    print(f"💬 Вопрос от {user_id}: {question}")
    
    # Показываем печать
    await bot.send_chat_action(msg.chat.id, action="typing")
    
    # Получаем ответ
    answer = await ask_groq(f"Вопрос о Stranger Things: {question}")
    
    # Отправляем
    await msg.reply(answer)
    print(f"✅ Ответ отправлен {user_id}")


@dp.message(Command("characters"))
async def characters_cmd(msg: Message, state: FSMContext):
    """Список персонажей"""
    # Проверяем активен ли бот
    current_state = await state.get_state()
    if current_state != BotStates.active:
        return  # Просто игнорим если неактивен
    
    characters = [
        "👧 **Eleven (Оди́ннадцать)** — Джейн Хоппер, телекинез",
        "👦 **Mike Wheeler** — лидер группы, парень Оди",
        "👦 **Will Byers** — был в Изнанке, чувствует Векну",
        "👦 **Dustin Henderson** — умник группы",
        "👦 **Lucas Sinclair** — стрелок, муж Макс",
        "👧 **Max Mayfield** — скейтерша, пережила проклятие",
        "👨 **Steve Harrington** — нянька группы",
        "👩 **Robin Buckley** — умная, работница видео-проката",
        "👩 **Nancy Wheeler** — журналистка, охотница",
        "👨 **Jonathan Byers** — фотограф",
        "👩 **Joyce Byers** — боевая мать",
        "👨 **Jim Hopper** — шеф полиции",
        "👿 **Vecna (Векна)** — Генри Крил, главный злодей",
        "👾 **Demogorgon** — монстр из Изнанки",
        "🐙 **Mind Flayer** — Мозгохват, сущность из Изнанки"
    ]
    
    text = "**👥 Персонажи Stranger Things:**\n\n"
    for char in characters:
        text += f"• {char}\n"
    
    text += "\n❓ Хочешь узнать больше? Используй `/st [имя]`"
    
    await msg.reply(text, parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("seasons"))
async def seasons_cmd(msg: Message, state: FSMContext):
    """Инфо по сезонам"""
    # Проверяем активен ли бот
    current_state = await state.get_state()
    if current_state != BotStates.active:
        return  # Просто игнорим если неактивен
    
    seasons = [
        "**1 сезон (2016):** Исчезновение Уилла Байерса, появление Оди, знакомство с Демогоргоном",
        "**2 сезон (2017):** Уилл связан с Мозгохватом, появление Макс, битва в лаборатории Хокинса",
        "**3 сезон (2019):** Русские в Хокинсе, открытие торгового центра Starcourt, гибель Хоппера",
        "**4 сезон (2022):** Векна раскрывает себя, прошлое Оди в лаборатории, жертва Макс",
        "**5 сезон (2025):** Финальная битва с Векной, возвращение в Изнанку (ожидается)"
    ]
    
    text = "**📺 Сезоны Stranger Things:**\n\n"
    for season in seasons:
        text += f"• {season}\n\n"
    
    await msg.reply(text, parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("help"))
async def help_cmd(msg: Message, state: FSMContext):
    """Помощь"""
    current_state = await state.get_state()
    
    if current_state != BotStates.active:
        await msg.reply(
            "🔹 **Доступные команды:**\n\n"
            "/botst - включить бота\n"
            "/botoff - выключить бота\n\n"
            "❗ Остальные команды работают только после `/botst`"
        )
        return
    
    await msg.reply(
        "**📚 Команды бота:**\n\n"
        "/botst - включить бота (если выключен)\n"
        "/botoff - выключить бота\n"
        "/st [вопрос] - задать вопрос о сериале\n"
        "/characters - список персонажей\n"
        "/seasons - информация по сезонам\n"
        "/help - это сообщение\n\n"
        "**Примеры вопросов:**\n"
        "• `/st Кто такой Векна?`\n"
        "• `/st Что такое Изнанка?`\n"
        "• `/st Расскажи про Оди`",
        parse_mode=ParseMode.MARKDOWN
    )


@dp.message()
async def handle_other(msg: Message, state: FSMContext):
    """Обработка всех остальных сообщений"""
    user_id = msg.from_user.id
    current_state = await state.get_state()
    
    # Если бот активен - игнорим все обычные сообщения (не отвечаем вообще)
    if current_state == BotStates.active:
        # Полное игнорирование, никаких подсказок
        return
    
    # Если бот неактивен - только одна подсказка за всё время
    if current_state != BotStates.active:
        # Проверяли ли мы уже этого пользователя
        if user_id not in hint_sent:
            # Отправляем одну подсказку и запоминаем
            await msg.reply("🤖 Я бот по Stranger Things. Напиши /botst чтобы включить меня!")
            hint_sent[user_id] = True
            print(f"💡 Подсказка отправлена {user_id}")
        # Иначе - игнорим


async def main():
    print("🎬 STRANGER THINGS BOT ЗАПУЩЕН!")
    print("✅ Включение: /botst")
    print("✅ Выключение: /botoff")
    print("✅ Вопросы: /st")
    print("💬 Режим: не спамит, подсказывает 1 раз")
    
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
