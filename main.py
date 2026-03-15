import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import logging
import os

logging.basicConfig(level=logging.INFO)

TOKEN = "8745386740:AAGdHJViFrQVcmzI968E0i5hyNvRtHaKDw4"

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("ping"))
async def ping(msg: types.Message):
    await msg.reply("pong 🏓")

@dp.message(Command("start"))
async def start(msg: types.Message):
    await msg.reply("Бот работает!")

async def main():
    print("🚀 Тестовый бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
