import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import MessageOriginUser
from aiohttp import web

# --- КОНФИГУРАЦИЯ ---
# Берем токен и ID из переменных Render (или вписываем вручную для теста)
API_TOKEN = os.getenv('BOT_TOKEN')
# Если переменная не задана, попробуем взять число, иначе 0
try:
    ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
except:
    ADMIN_ID = 0

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# Инициализация
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- ЛОГИКА БОТА ---

@dp.message(F.text == "/start")
async def cmd_start(message: types.Message):
    # Если пишет админ
    if message.from_user.id == ADMIN_ID:
        await message.answer("Привет, Админ! Просто отвечай (Reply) на пересланные сообщения, чтобы писать пользователям.")
    else:
        await message.answer("Приветствую! Напиши сообщение в чат, чтобы передать его администратору.")


# 1. Хэндлер: АДМИН ОТВЕЧАЕТ ПОЛЬЗОВАТЕЛЮ
# Срабатывает, если пишет Админ И это ответ (Reply) на какое-то сообщение
@dp.message(F.reply_to_message & (F.from_user.id == ADMIN_ID))
async def admin_reply(message: types.Message):
    # Получаем сообщение, на которое ответил админ
    original_message = message.reply_to_message
    
    # Пытаемся узнать, от кого было переслано сообщение
    # В aiogram 3.x информация о пересылке лежит в forward_origin
    origin = original_message.forward_origin
    
    if origin and isinstance(origin, MessageOriginUser):
        user_id = origin.sender_user.id
        
        try:
            # Метод copy_message отправляет точную копию (текст, фото, стикер...) пользователю
            await message.copy_to(chat_id=user_id)
            await message.react([types.ReactionTypeEmoji(emoji="👍")]) # Ставит лайк сообщению админа для подтверждения
        except Exception as e:
            await message.answer(f"Не удалось отправить (возможно, пользователь заблокировал бота): {e}")
    else:
        # Если у пользователя закрытый профиль (HiddenUser) или это не пересланное сообщение
        await message.answer("⚠️ Не могу ответить этому пользователю. Скорее всего, у него скрыт профиль в настройках приватности Telegram, и я не вижу его ID.")


# 2. Хэндлер: ПОЛЬЗОВАТЕЛЬ ПИШЕТ БОТУ (Пересылка админу)
# Срабатывает на все остальные сообщения
@dp.message()
async def forward_to_admin(message: types.Message):
    # Если пишет сам админ (но не через Reply), игнорируем, чтобы не заспамить личку
    if message.from_user.id == ADMIN_ID:
        return

    try:
        # Пересылаем сообщение админу
        await message.forward(chat_id=ADMIN_ID)
    except Exception as e:
        logging.error(f"Ошибка пересылки: {e}")


# --- ВЕБ-СЕРВЕР (ЧТОБЫ РЕНДЕР НЕ УБИВАЛ БОТА) ---
async def handle(request):
    return web.Response(text="I am alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- ЗАПУСК ---
async def main():
    if not API_TOKEN or not ADMIN_ID:
        print("ОШИБКА: Не задан BOT_TOKEN или ADMIN_ID в настройках Render Environment!")
        return

    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
