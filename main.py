import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import web, ClientTimeout, ClientConnectorError, ServerDisconnectedError, TCPConnector
import logging
import sys
import os
import time
from datetime import datetime, timedelta
import traceback

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# ===== КОНФИГ =====
TELEGRAM_TOKEN = "8745386740:AAGdHJViFrQVcmzI968E0i5hyNvRtHaKDw4"
GROQ_API_KEY = "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"

# Состояния
class BotStates(StatesGroup):
    active = State()
    inactive = State()

# Для антиспама
hint_sent = {}
last_command_time = {}
last_response_cache = {}
reconnect_attempts = 0
max_reconnect_attempts = 50

SYSTEM_PROMPT = """Ты - эксперт по сериалу «Очень странные дела» (Stranger Things). Твоя задача — помогать пользователям с вопросами о сериале, персонажах, сюжете, теориях и деталях.

ТВОИ ПРАВИЛА:
1. Отвечай всегда вежливо, с уважением, как настоящий фанат сериала.
2. Используй правильную пунктуацию: заглавные буквы, запятые, точки.
3. Знай всех персонажей, их имена актеров, способности и роли в сюжете.
4. Знай ключевые события по сезонам, локации (Хокинс, Изнанка, лаборатория).
5. Знай популярные фанатские теории и обсуждай их.
"""

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


class ResilientBot:
    def __init__(self):
        self.bot = None
        self.dp = None
        self.storage = None
        self.session = None
        self.running = True
        self.connector = None
        
    async def create_bot(self):
        """Создание бота с защитой от таймаутов"""
        try:
            # Создаем ClientTimeout
            timeout = aiohttp.ClientTimeout(
                total=60,
                connect=30,
                sock_read=30
            )
            
            # В новой версии aiogram AiohttpSession принимает timeout
            self.session = AiohttpSession(
                timeout=timeout
            )
            
            self.storage = MemoryStorage()
            self.bot = Bot(token=TELEGRAM_TOKEN, session=self.session)
            self.dp = Dispatcher(storage=self.storage)
            
            logger.info("✅ Бот создан успешно")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка создания бота: {e}")
            logger.error(traceback.format_exc())
            return False
    
    async def setup_handlers(self):
        """Настройка обработчиков команд"""
        
        @self.dp.message(CommandStart())
        async def start_bot(msg: Message, state: FSMContext):
            await state.set_state(BotStates.inactive)
            await msg.answer(
                "👋 Привет! Я бот по сериалу **Stranger Things**.\n\n"
                "🔹 Напиши `/botst` чтобы активировать меня\n"
                "🔹 После активации смогу отвечать на вопросы о сериале\n"
                "🔹 `/botoff` - выключить меня"
            )

        @self.dp.message(Command("botst"))
        async def activate_bot(msg: Message, state: FSMContext):
            user_id = msg.from_user.id
            
            current_state = await state.get_state()
            if current_state == BotStates.active:
                await msg.reply("🤖 Бот уже активен! Используй /st чтобы задать вопрос.")
                return
            
            await state.set_state(BotStates.active)
            
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
            logger.info(f"✅ Бот включен для {user_id}")

        @self.dp.message(Command("botoff"))
        async def deactivate_bot(msg: Message, state: FSMContext):
            user_id = msg.from_user.id
            
            current_state = await state.get_state()
            if current_state != BotStates.active:
                await msg.reply("🔴 Бот и так неактивен. Чтобы включить - /botst")
                return
            
            await state.set_state(BotStates.inactive)
            if user_id in hint_sent:
                del hint_sent[user_id]
            
            await msg.reply("🔴 **Бот выключен**\n\nЧтобы снова активировать - /botst", parse_mode=ParseMode.MARKDOWN)
            logger.info(f"🔴 Бот выключен для {user_id}")

        @self.dp.message(Command("st"))
        async def st_command(msg: Message, state: FSMContext):
            user_id = msg.from_user.id
            
            current_state = await state.get_state()
            if current_state != BotStates.active:
                return
            
            # Антиспам
            current_time = datetime.now()
            if user_id in last_command_time:
                if current_time - last_command_time[user_id] < timedelta(seconds=2):
                    await msg.reply("⏳ Слишком быстро, дай секунду...")
                    return
            
            last_command_time[user_id] = current_time
            
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
            
            logger.info(f"💬 Вопрос от {user_id}: {question}")
            
            await self.bot.send_chat_action(msg.chat.id, action="typing")
            
            # Получаем ответ с повторными попытками
            answer = await self.ask_groq_with_retry(f"Вопрос о Stranger Things: {question}")
            
            await msg.reply(answer)
            logger.info(f"✅ Ответ отправлен {user_id}")

        @self.dp.message(Command("characters"))
        async def characters_cmd(msg: Message, state: FSMContext):
            current_state = await state.get_state()
            if current_state != BotStates.active:
                return
            
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

        @self.dp.message(Command("seasons"))
        async def seasons_cmd(msg: Message, state: FSMContext):
            current_state = await state.get_state()
            if current_state != BotStates.active:
                return
            
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

        @self.dp.message(Command("help"))
        async def help_cmd(msg: Message, state: FSMContext):
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

        @self.dp.message()
        async def handle_other(msg: Message, state: FSMContext):
            user_id = msg.from_user.id
            current_state = await state.get_state()
            
            if current_state == BotStates.active:
                return
            
            if current_state != BotStates.active:
                if user_id not in hint_sent:
                    await msg.reply("🤖 Я бот по Stranger Things. Напиши /botst чтобы включить меня!")
                    hint_sent[user_id] = True
                    logger.info(f"💡 Подсказка отправлена {user_id}")

    async def ask_groq_with_retry(self, question, max_retries=3):
        """Отправка вопроса к Groq API с повторными попытками"""
        cache_key = question[:100]
        if cache_key in last_response_cache:
            cache_time, cache_answer = last_response_cache[cache_key]
            if datetime.now() - cache_time < timedelta(minutes=5):
                return cache_answer
        
        for attempt in range(max_retries):
            try:
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

                # Создаем сессию с connector
                timeout = aiohttp.ClientTimeout(total=30)
                connector = aiohttp.TCPConnector(ssl=False)
                
                async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
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
                            logger.warning(f"⚠️ Groq API error (attempt {attempt+1}): {resp.status}")
                            
            except Exception as e:
                logger.warning(f"⚠️ Groq API exception (attempt {attempt+1}): {e}")
            
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                await asyncio.sleep(wait_time)
        
        return "⚠️ Не могу получить ответ от API. Попробуй позже."

    async def health_check_handler(self, request):
        """Обработчик для health checks"""
        return web.Response(text=f"OK - {datetime.now().isoformat()}")

    async def run_web_server(self):
        """Запуск HTTP сервера для health checks"""
        app = web.Application()
        app.router.add_get('/', self.health_check_handler)
        app.router.add_get('/health', self.health_check_handler)
        
        port = int(os.getenv('PORT', 8080))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        logger.info(f"🌐 Health check server running on port {port}")

    async def run_bot_with_reconnect(self):
        """Запуск бота с автоматическим переподключением"""
        global reconnect_attempts
        
        # Сразу запускаем health check сервер
        asyncio.create_task(self.run_web_server())
        
        while self.running:
            try:
                # Создаем бота
                if not await self.create_bot():
                    logger.error("❌ Не удалось создать бота, жду 10 секунд...")
                    await asyncio.sleep(10)
                    continue
                
                # Настраиваем обработчики
                await self.setup_handlers()
                
                logger.info("🎬 STRANGER THINGS BOT ЗАПУЩЕН!")
                logger.info("✅ Включение: /botst")
                logger.info("✅ Выключение: /botoff")
                logger.info("✅ Вопросы: /st")
                logger.info("💬 Режим: самовосстанавливающийся")
                
                # Запускаем поллинг - УБРАЛ polling_timeout и allowed_updates
                await self.dp.start_polling(
                    self.bot
                )
                
            except (ClientConnectorError, ServerDisconnectedError, TimeoutError, 
                   asyncio.TimeoutError, ConnectionError) as e:
                reconnect_attempts += 1
                wait_time = min(30, 5 * (reconnect_attempts ** 0.5))
                
                logger.error(f"❌ Сетевая ошибка: {e}")
                logger.info(f"🔄 Попытка переподключения {reconnect_attempts}/{max_reconnect_attempts} через {wait_time:.0f} сек...")
                
                # Очищаем старые сессии
                if self.bot:
                    try:
                        await self.bot.session.close()
                    except:
                        pass
                
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                logger.error(f"❌ Неожиданная ошибка: {e}")
                logger.error(traceback.format_exc())
                
                reconnect_attempts += 1
                await asyncio.sleep(10)
                
                if reconnect_attempts > max_reconnect_attempts:
                    logger.critical("💀 Слишком много ошибок, останавливаюсь...")
                    break
            
            else:
                # Если поллинг остановился без ошибки
                reconnect_attempts = 0
                logger.warning("⚠️ Поллинг остановлен, перезапуск...")
                await asyncio.sleep(3)
        
        logger.info("👋 Бот завершил работу")
    
    async def setup_handlers(self):
        """Настройка обработчиков команд"""
        
        @self.dp.message(CommandStart())
        async def start_bot(msg: Message, state: FSMContext):
            await state.set_state(BotStates.inactive)
            await msg.answer(
                "👋 Привет! Я бот по сериалу **Stranger Things**.\n\n"
                "🔹 Напиши `/botst` чтобы активировать меня\n"
                "🔹 После активации смогу отвечать на вопросы о сериале\n"
                "🔹 `/botoff` - выключить меня"
            )

        @self.dp.message(Command("botst"))
        async def activate_bot(msg: Message, state: FSMContext):
            user_id = msg.from_user.id
            
            current_state = await state.get_state()
            if current_state == BotStates.active:
                await msg.reply("🤖 Бот уже активен! Используй /st чтобы задать вопрос.")
                return
            
            await state.set_state(BotStates.active)
            
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
            logger.info(f"✅ Бот включен для {user_id}")

        @self.dp.message(Command("botoff"))
        async def deactivate_bot(msg: Message, state: FSMContext):
            user_id = msg.from_user.id
            
            current_state = await state.get_state()
            if current_state != BotStates.active:
                await msg.reply("🔴 Бот и так неактивен. Чтобы включить - /botst")
                return
            
            await state.set_state(BotStates.inactive)
            if user_id in hint_sent:
                del hint_sent[user_id]
            
            await msg.reply("🔴 **Бот выключен**\n\nЧтобы снова активировать - /botst", parse_mode=ParseMode.MARKDOWN)
            logger.info(f"🔴 Бот выключен для {user_id}")

        @self.dp.message(Command("st"))
        async def st_command(msg: Message, state: FSMContext):
            user_id = msg.from_user.id
            
            current_state = await state.get_state()
            if current_state != BotStates.active:
                return
            
            # Антиспам
            current_time = datetime.now()
            if user_id in last_command_time:
                if current_time - last_command_time[user_id] < timedelta(seconds=2):
                    await msg.reply("⏳ Слишком быстро, дай секунду...")
                    return
            
            last_command_time[user_id] = current_time
            
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
            
            logger.info(f"💬 Вопрос от {user_id}: {question}")
            
            await self.bot.send_chat_action(msg.chat.id, action="typing")
            
            # Получаем ответ с повторными попытками
            answer = await self.ask_groq_with_retry(f"Вопрос о Stranger Things: {question}")
            
            await msg.reply(answer)
            logger.info(f"✅ Ответ отправлен {user_id}")

        @self.dp.message(Command("characters"))
        async def characters_cmd(msg: Message, state: FSMContext):
            current_state = await state.get_state()
            if current_state != BotStates.active:
                return
            
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

        @self.dp.message(Command("seasons"))
        async def seasons_cmd(msg: Message, state: FSMContext):
            current_state = await state.get_state()
            if current_state != BotStates.active:
                return
            
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

        @self.dp.message(Command("help"))
        async def help_cmd(msg: Message, state: FSMContext):
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

        @self.dp.message()
        async def handle_other(msg: Message, state: FSMContext):
            user_id = msg.from_user.id
            current_state = await state.get_state()
            
            if current_state == BotStates.active:
                return
            
            if current_state != BotStates.active:
                if user_id not in hint_sent:
                    await msg.reply("🤖 Я бот по Stranger Things. Напиши /botst чтобы включить меня!")
                    hint_sent[user_id] = True
                    logger.info(f"💡 Подсказка отправлена {user_id}")

    async def ask_groq_with_retry(self, question, max_retries=3):
        """Отправка вопроса к Groq API с повторными попытками"""
        cache_key = question[:100]
        if cache_key in last_response_cache:
            cache_time, cache_answer = last_response_cache[cache_key]
            if datetime.now() - cache_time < timedelta(minutes=5):
                return cache_answer
        
        for attempt in range(max_retries):
            try:
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

                # Создаем сессию с connector
                timeout = aiohttp.ClientTimeout(total=30)
                connector = aiohttp.TCPConnector(ssl=False)
                
                async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
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
                            logger.warning(f"⚠️ Groq API error (attempt {attempt+1}): {resp.status}")
                            
            except Exception as e:
                logger.warning(f"⚠️ Groq API exception (attempt {attempt+1}): {e}")
            
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                await asyncio.sleep(wait_time)
        
        return "⚠️ Не могу получить ответ от API. Попробуй позже."

    async def health_check_handler(self, request):
        """Обработчик для health checks"""
        return web.Response(text=f"OK - {datetime.now().isoformat()}")

    async def run_web_server(self):
        """Запуск HTTP сервера для health checks"""
        app = web.Application()
        app.router.add_get('/', self.health_check_handler)
        app.router.add_get('/health', self.health_check_handler)
        
        port = int(os.getenv('PORT', 8080))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        logger.info(f"🌐 Health check server running on port {port}")

    async def run_bot_with_reconnect(self):
        """Запуск бота с автоматическим переподключением"""
        global reconnect_attempts
        
        # Сразу запускаем health check сервер
        asyncio.create_task(self.run_web_server())
        
        while self.running:
            try:
                # Создаем бота
                if not await self.create_bot():
                    logger.error("❌ Не удалось создать бота, жду 10 секунд...")
                    await asyncio.sleep(10)
                    continue
                
                # Настраиваем обработчики
                await self.setup_handlers()
                
                logger.info("🎬 STRANGER THINGS BOT ЗАПУЩЕН!")
                logger.info("✅ Включение: /botst")
                logger.info("✅ Выключение: /botoff")
                logger.info("✅ Вопросы: /st")
                logger.info("💬 Режим: самовосстанавливающийся")
                
                # Запускаем поллинг
                await self.dp.start_polling(
                    self.bot,
                    allowed_updates=['message', 'chat_member'],
                    timeout=30
                )
                
            except (ClientConnectorError, ServerDisconnectedError, TimeoutError, 
                   asyncio.TimeoutError, ConnectionError) as e:
                reconnect_attempts += 1
                wait_time = min(30, 5 * (reconnect_attempts ** 0.5))
                
                logger.error(f"❌ Сетевая ошибка: {e}")
                logger.info(f"🔄 Попытка переподключения {reconnect_attempts}/{max_reconnect_attempts} через {wait_time:.0f} сек...")
                
                # Очищаем старые сессии
                if self.bot:
                    try:
                        await self.bot.session.close()
                    except:
                        pass
                
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                logger.error(f"❌ Неожиданная ошибка: {e}")
                logger.error(traceback.format_exc())
                
                reconnect_attempts += 1
                await asyncio.sleep(10)
                
                if reconnect_attempts > max_reconnect_attempts:
                    logger.critical("💀 Слишком много ошибок, останавливаюсь...")
                    break
            
            else:
                # Если поллинг остановился без ошибки
                reconnect_attempts = 0
                logger.warning("⚠️ Поллинг остановлен, перезапуск...")
                await asyncio.sleep(3)
        
        logger.info("👋 Бот завершил работу")


async def main():
    """Главная функция"""
    bot = ResilientBot()
    
    try:
        await bot.run_bot_with_reconnect()
    except KeyboardInterrupt:
        logger.info("\n👋 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        logger.error(traceback.format_exc())
    finally:
        bot.running = False


if __name__ == "__main__":
    asyncio.run(main())
