import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiohttp import web
from threading import Thread

# --- КОНФИГУРАЦИЯ ---
# Токен можно оставить здесь или (лучше) задать в настройках сервера как переменную окружения
API_TOKEN = os.getenv('BOT_TOKEN', 'ВСТАВЬТЕ_ВАШ_ТОКЕН_ПРЯМО_СЮДА_ЕСЛИ_ТЕСТИРУЕТЕ_ЛОКАЛЬНО')
ADMIN_ID = 1628455065  # Ваш ID

# Инициализация
logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- ЛОГИКА БОТА ---
@dp.message(F.text == "/start")
async def cmd_start(message: types.Message):
    await message.answer("Я работаю и готов пересылать сообщения!")

@dp.message()
async def forward_everything(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Сообщения пересылаются вам.")
        return
    try:
        await message.forward(chat_id=ADMIN_ID)
        # await message.answer("Отправлено!") # Раскомментируйте, если нужно подтверждение
    except Exception as e:
        logging.error(f"Ошибка: {e}")

# --- ВЕБ-СЕРВЕР (ЧТОБЫ БОТ НЕ СПАЛ) ---
async def handle(request):
    return web.Response(text="I am alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render выдает порт через переменную окружения PORT, по умолчанию 8080
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- ЗАПУСК ---
async def main():
    # Запускаем веб-сервер и поллинг бота параллельно
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
