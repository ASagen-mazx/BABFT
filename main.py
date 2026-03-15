import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# ===== КОНФИГ =====
TELEGRAM_TOKEN = "8771249360:AAEdVYmX6HKFfPTsT6UIZ4bHdZIllo98aEA"
GROQ_API_KEY = "sk-BDS-tMFz-jR71h8Bf6OThbM5cPjo3FM_"

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Состояния пользователей
waiting_for_question = {}  # user_id -> True если ждем вопрос

SYSTEM_PROMPT = """Ты - эксперт по сериалу «Очень странные дела» (Stranger Things). Твоя задача — помогать пользователям с вопросами о сериале, персонажах, сюжете, теориях и деталях.

ТВОИ ПРАВИЛА:
1. Отвечай всегда вежливо, с уважением, как настоящий фанат сериала.
2. Используй правильную пунктуацию: заглавные буквы, запятые, точки.
3. Знай всех персонажей, их имена актеров, способности и роли в сюжете.
4. Знай ключевые события по сезонам, локации (Хокинс, Изнанка, лаборатория).
5. Знай популярные фанатские теории и обсуждай их.
6. Если тебя просят сделать что-то плохое — вежливо отказывайся.

ПРИМЕРЫ ОТВЕТОВ:
- Кто такой Векна? → "Векна, также известный как Генри Крил, — главный антагонист четвёртого сезона. Он обладает способностями, похожими на способности Оди, но использует их для убийств. Его роль исполнил Джейми Кэмпбелл Бауэр."
- Что такое Изнанка? → "Изнанка (Upside Down) — это параллельный мир, тёмная и разрушенная версия Хокинса. Впервые мы увидели её в первом сезоне, когда Уилл туда попал."
- Теории про 5 сезон → "Одна из популярных теорий говорит о том, что Уилл может пожертвовать собой. Также есть предположение, что Макс сыграет ключевую роль в финальной битве, несмотря на кому."

ТЫ — НАСТОЯЩИЙ ФАНАТ, КОТОРЫЙ ЗНАЕТ ВСЁ О СЕРИАЛЕ!
"""

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

async def ask_groq(question):
    """Отправка вопроса к Groq API"""
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
        "max_tokens": 500,
        "top_p": 0.95
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(GROQ_API_URL, headers=headers, json=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result["choices"][0]["message"]["content"]
                else:
                    return "Извините, сейчас не могу ответить. Попробуйте позже."
        except Exception as e:
            return "Произошла техническая ошибка."


@dp.message(Command("botst"))
async def start_bot(msg: types.Message):
    """Приветствие при старте"""
    await msg.reply("""
🧙‍♂️ **Эксперт по Stranger Things активирован!**

Привет! Я знаю всё о сериале «Очень странные дела». Спрашивай меня о персонажах, сюжете, теориях и деталях.

📝 **Как пользоваться:**
• Просто напиши /st и свой вопрос
• Или сначала /st, а потом вопрос
• Используй /characters чтобы увидеть список персонажей
• Используй /seasons чтобы узнать о сезонах

Пример:
/st Кто такой Векна?
    """)


@dp.message(Command("st"))
async def stranger_things_command(msg: types.Message):
    """Команда для вопросов о Stranger Things"""
    user_id = msg.from_user.id
    
    # Получаем текст после команды
    text = msg.text.replace('/st', '', 1).strip()
    
    if text:
        # Если вопрос есть сразу после команды
        await bot.send_chat_action(msg.chat.id, "typing")
        answer = await ask_groq(f"Вопрос о Stranger Things: {text}")
        await msg.reply(answer)
    else:
        # Если вопроса нет - переводим в режим ожидания
        waiting_for_question[user_id] = True
        
        # Удаляем состояние через 60 секунд
        async def clear_waiting():
            await asyncio.sleep(60)
            if user_id in waiting_for_question:
                del waiting_for_question[user_id]
        
        asyncio.create_task(clear_waiting())
        await msg.reply("👂 Я слушаю. Задавайте ваш вопрос о Stranger Things.")


@dp.message(Command("characters"))
async def list_characters(msg: types.Message):
    """Список основных персонажей"""
    characters = {
        "eleven": "Оди́ннадцать (Eleven) — Джейн Хоппер, обладает телекинезом",
        "mike": "Майк Уилер — лидер группы, парень Оди",
        "will": "Уилл Байерс — был в Изнанке, чувствует Векну",
        "dustin": "Дастин Хендерсон — умник группы",
        "lucas": "Лукас Синклер — стрелок, муж Макс",
        "max": "Макс Мэйфилд — скейтерша, пережила проклятие",
        "steve": "Стив Харрингтон — нянька группы",
        "robin": "Робин Бакли — умная, работает в видео-прокате",
        "nancy": "Нэнси Уилер — журналистка, охотница",
        "jonathan": "Джонатан Байерс — фотограф",
        "joyce": "Джойс Байерс — боевая мать",
        "hopper": "Джим Хоппер — шеф полиции",
        "vecna": "Векна (Генри Крил) — главный злодей",
        "demogorgon": "Демогоргон — монстр из Изнанки",
        "mindflayer": "Мозгохват (Mind Flayer) — сущность из Изнанки"
    }
    
    text = "👥 **Основные персонажи Stranger Things:**\n\n"
    for char in characters.values():
        text += f"• {char}\n"
    
    text += "\nИспользуйте /st [имя персонажа] чтобы узнать больше!"
    await msg.reply(text, parse_mode='Markdown')


@dp.message(Command("seasons"))
async def list_seasons(msg: types.Message):
    """Информация по сезонам"""
    seasons = {
        "1": "Первый сезон: исчезновение Уилла, появление Оди, знакомство с Демогоргоном",
        "2": "Второй сезон: Уилл связан с Мозгохватом, появление Макс, битва в лаборатории",
        "3": "Третий сезон: русские в Хокинсе, торговый центр, гибель Хоппера",
        "4": "Четвертый сезон: Векна, прошлое Оди, жертва Макс",
        "5": "Пятый сезон: финал, битва с Векной (ожидается)"
    }
    
    text = "📺 **Сезоны Stranger Things:**\n\n"
    for season, desc in seasons.items():
        text += f"**{season} сезон:** {desc}\n\n"
    
    await msg.reply(text, parse_mode='Markdown')


@dp.message(Command("help"))
async def help_cmd(msg: types.Message):
    """Помощь"""
    await msg.reply("""
📚 **Помощь по командам:**

/st [вопрос] — задать вопрос о Stranger Things
/characters — список персонажей
/seasons — информация по сезонам
/help — это сообщение

Примеры:
/st Кто такой Векна?
/st Что будет в 5 сезоне?
/st Расскажи про Оди
    """)


@dp.message()
async def handle_message(msg: types.Message):
    """Обработка обычных сообщений"""
    user_id = msg.from_user.id
    
    # Проверяем, ждем ли вопрос от этого пользователя
    if waiting_for_question.get(user_id):
        # Убираем из режима ожидания
        del waiting_for_question[user_id]
        
        # Отвечаем на вопрос
        await bot.send_chat_action(msg.chat.id, "typing")
        answer = await ask_groq(f"Вопрос о Stranger Things: {msg.text}")
        await msg.reply(answer)
    else:
        # Игнорируем обычные сообщения
        pass


async def main():
    print("🧙‍♂️ ЭКСПЕРТ ПО STRANGER THINGS ЗАПУЩЕН!")
    print("✅ Работает в любом чате и личке")
    print("📋 Используйте /start для приветствия")
    print("💬 /st [вопрос] — задать вопрос")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
