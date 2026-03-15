import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp_socks import ProxyConnector
import logging
import os

logging.basicConfig(level=logging.INFO)

TOKEN = "8745386740:AAGdHJViFrQVcmzI968E0i5hyNvRtHaKDw4"

# Список SOCKS5 прокси (найди рабочие на https://spys.one/en/socks-proxy-list/)
PROXIES = [
    "socks5://45.86.209.107:1080",
    "socks5://185.224.105.177:1080",
    "socks5://45.155.93.134:1080",
    "socks5://51.158.121.139:16379",
]

async def main():
    for proxy in PROXIES:
        try:
            print(f"🔄 Пробую прокси: {proxy}")
            
            connector = ProxyConnector.from_url(proxy)
            session = AiohttpSession(
                timeout=aiohttp.ClientTimeout(total=30),
                connector=connector
            )
            
            bot = Bot(token=TOKEN, session=session)
            dp = Dispatcher()
            
            @dp.message(Command("ping"))
            async def ping(msg: types.Message):
                await msg.reply("pong 🏓")
            
            # Проверяем соединение
            me = await bot.me()
            print(f"✅ Успешно подключился как @{me.username}")
            
            await dp.start_polling(bot)
            break
            
        except Exception as e:
            print(f"❌ Прокси не работает: {e}")
            continue

if __name__ == "__main__":
    asyncio.run(main())
