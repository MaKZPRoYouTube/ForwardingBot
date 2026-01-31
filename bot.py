import asyncio
import logging
import os
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import MessageOriginUser
from aiohttp import web, ClientSession

# --- НАСТРОЙКИ ---
API_TOKEN = os.getenv('BOT_TOKEN')

# ПРАВИЛЬНАЯ ЗАГРУЗКА ID ВЛАДЕЛЬЦА
# Мы убираем пробелы (.strip), чтобы "123 " не вызвало ошибку
raw_admin_id = os.getenv('ADMIN_ID', '0')
try:
    OWNER_ID = int(str(raw_admin_id).strip())
except ValueError:
    OWNER_ID = 0
    print("ОШИБКА: ADMIN_ID в Render задан не числом!")

# НАСТРОЙКИ ОБЛАКА (JSONBIN)
BIN_ID = os.getenv('BIN_ID')
BIN_API_KEY = os.getenv('BIN_API_KEY')
# Генерируем ссылку, убирая лишние пробелы, если они есть
if BIN_ID:
    BIN_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID.strip()}"
else:
    BIN_URL = ""

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- ФУНКЦИИ БАЗЫ ДАННЫХ ---

async def get_admins(debug_msg=None):
    """Возвращает множество ID админов (Владелец + те, кто в облаке)"""
    admins = {OWNER_ID}  # Владелец всегда админ

    if not BIN_ID or not BIN_API_KEY:
        return admins # Если облако не настроено, возвращаем только владельца
    
    headers = {"X-Master-Key": BIN_API_KEY.strip()}
    
    try:
        async with ClientSession() as session:
            async with session.get(f"{BIN_URL}/latest", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    saved_list = data.get("record", [])
                    if isinstance(saved_list, list):
                        admins.update(saved_list)
                else:
                    if debug_msg:
                        error_text = await resp.text()
                        await debug_msg.answer(f"⚠️ Ошибка облака: {resp.status}\n{error_text}")
    except Exception as e:
        if debug_msg: await debug_msg.answer(f"⚠️ Ошибка соединения: {e}")
        
    return admins

async def save_admins_cloud(admin_list, message=None):
    if not BIN_URL: return
    headers = {"Content-Type": "application/json", "X-Master-Key": BIN_API_KEY.strip()}
    try:
        async with ClientSession() as session:
            # Важно: В облако пишем список, в коде работаем с множеством
            await session.put(BIN_URL, json=list(admin_list), headers=headers)
    except Exception as e:
        if message: await message.answer(f"Не удалось сохранить: {e}")

# --- КОМАНДА ДИАГНОСТИКИ (ГЛАВНАЯ ДЛЯ ВАС СЕЙЧАС) ---

@dp.message(Command("check"))
async def debug_handler(message: types.Message):
    user_id = message.from_user.id
    
    status_text = (
        f"🕵️‍♂️ **Диагностика:**\n\n"
        f"Ваш Telegram ID: `{user_id}`\n"
        f"ID Владельца (в Render): `{OWNER_ID}`\n"
    )
    
    if user_id == OWNER_ID:
        status_text += "✅ **ВЫ ВЛАДЕЛЕЦ** (ID совпадают).\n"
    else:
        status_text += "❌ **Вы НЕ владелец** (ID не совпадают).\n"
        status_text += "👉 Проверьте переменную `ADMIN_ID` в Render.\n"

    # Проверка облака
    if BIN_ID and BIN_API_KEY:
        status_text += f"\n☁️ Облако настроено (ID: {BIN_ID[:4]}...)"
    else:
        status_text += "\n⚠️ Облако НЕ настроено (список других админов не будет сохраняться)."
        
    await message.answer(status_text, parse_mode="Markdown")

# --- СТАНДАРТНЫЕ КОМАНДЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    admins = await get_admins()
    if message.from_user.id in admins:
        await message.answer(f"Привет, Админ! Твой ID: `{message.from_user.id}`\n\n"
                             "Жду сообщений от пользователей.")
    else:
        await message.answer(f"Привет! Это бот обратной связи. Твой ID: `{message.from_user.id}`")

@dp.message(Command("add"))
async def add_admin(message: types.Message, command: CommandObject):
    if message.from_user.id != OWNER_ID: return
    
    if not command.args:
        await message.answer("Пиши: /add 12345678")
        return
    try:
        new_id = int(command.args.strip())
        admins = await get_admins(message)
        admins.add(new_id)
        await save_admins_cloud(admins, message)
        await message.answer(f"✅ Админ {new_id} добавлен.")
    except ValueError:
        await message.answer("Нужны только цифры.")

@dp.message(Command("del"))
async def del_admin(message: types.Message, command: CommandObject):
    if message.from_user.id != OWNER_ID: return
    try:
        del_id = int(command.args.strip())
        admins = await get_admins(message)
        if del_id in admins and del_id != OWNER_ID:
            admins.discard(del_id)
            await save_admins_cloud(admins, message)
            await message.answer(f"🗑 Удален.")
        else:
            await message.answer("Нельзя удалить себя или такого админа нет.")
    except: pass

@dp.message(Command("list"))
async def list_admins(message: types.Message):
    if message.from_user.id != OWNER_ID: return
    admins = await get_admins(message)
    await message.answer(f"Список админов: {list(admins)}")

# --- ЛОГИКА ПЕРЕСЫЛКИ ---

@dp.message(F.reply_to_message)
async def admin_reply_handler(message: types.Message):
    admins = await get_admins()
    # Если пишет не админ — считаем это обычным сообщением
    if message.from_user.id not in admins:
        await forward_to_admins(message, admins)
        return

    # Это ответ админа пользователю
    origin = message.reply_to_message.forward_origin
    if origin and isinstance(origin, MessageOriginUser):
        try:
            await message.copy_to(chat_id=origin.sender_user.id)
            await message.react([types.ReactionTypeEmoji(emoji="👍")])
        except Exception as e:
            await message.answer(f"Не удалось отправить: {e}")
    else:
        await message.answer("Не могу найти пользователя (профиль скрыт).")

@dp.message()
async def user_message_handler(message: types.Message):
    admins = await get_admins()
    # Админы не спамят сами себе (если это не реплай)
    if message.from_user.id in admins: return
    
    await forward_to_admins(message, admins)

async def forward_to_admins(message, admins):
    for aid in admins:
        try: await message.forward(chat_id=aid)
        except: pass

# --- SERVER ---
async def handle(request): return web.Response(text="Bot is running")
async def start_web():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080))).start()

async def main():
    await asyncio.gather(start_web(), dp.start_polling(bot))

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
