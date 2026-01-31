import asyncio
import logging
import os
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import MessageOriginUser
from aiohttp import web, ClientSession

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = os.getenv('BOT_TOKEN')
# Владелец всегда загружается из переменных среды (самый главный)
try:
    OWNER_ID = int(os.getenv('ADMIN_ID', 0))
except:
    OWNER_ID = 0

# Настройки облачного файла (JSONBin)
BIN_ID = os.getenv('BIN_ID')
BIN_API_KEY = os.getenv('BIN_API_KEY')
BIN_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- РАБОТА С ОБЛАЧНЫМ ФАЙЛОМ ---

async def get_admins():
    """Скачивает список админов из облака"""
    admins = {OWNER_ID} # Владелец всегда в списке
    
    if not BIN_ID or not BIN_API_KEY:
        logging.warning("JSONBin не настроен, список админов не сохраняется!")
        return admins

    headers = {"X-Master-Key": BIN_API_KEY}
    
    try:
        async with ClientSession() as session:
            # Важно: добавляем /latest, чтобы читать последнюю версию
            async with session.get(f"{BIN_URL}/latest", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # JSONBin возвращает данные внутри ключа "record"
                    saved_list = data.get("record", [])
                    admins.update(saved_list)
                else:
                    logging.error(f"Ошибка чтения JSONBin: {resp.status}")
    except Exception as e:
        logging.error(f"Ошибка сети при чтении админов: {e}")
        
    return admins

async def save_admins_cloud(admin_list):
    """Отправляет новый список админов в облако"""
    if not BIN_ID or not BIN_API_KEY:
        return
        
    headers = {
        "Content-Type": "application/json",
        "X-Master-Key": BIN_API_KEY
    }
    # Превращаем множество в список для JSON
    data = list(admin_list)
    
    try:
        async with ClientSession() as session:
            async with session.put(BIN_URL, json=data, headers=headers) as resp:
                if resp.status == 200:
                    logging.info("Список админов сохранен в облако.")
                else:
                    logging.error(f"Ошибка записи в JSONBin: {resp.status}")
    except Exception as e:
        logging.error(f"Ошибка сети при записи админов: {e}")


# --- ХЭНДЛЕРЫ КОМАНД ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    admins = await get_admins() # Теперь это асинхронная функция, нужен await

    if user_id in admins:
        role = "Владелец" if user_id == OWNER_ID else "Админ"
        await message.answer(f"👑 Привет, {role}!\n"
                             "Команды:\n"
                             "/add ID — добавить\n"
                             "/del ID — удалить\n"
                             "/list — список\n"
                             "Отвечай (Reply) на сообщения для отправки.")
    else:
        await message.answer("Привет! Напиши мне, я передам администратору.")

# --- УПРАВЛЕНИЕ АДМИНАМИ ---

@dp.message(Command("add"))
async def add_admin(message: types.Message, command: CommandObject):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Только владелец может добавлять админов.")
        return

    if not command.args:
        await message.answer("Введите ID. Пример: `/add 12345`")
        return

    try:
        new_id = int(command.args.strip())
        admins = await get_admins()
        
        if new_id not in admins:
            admins.add(new_id)
            # Сохраняем обновленный список в облако
            await save_admins_cloud(admins)
            await message.answer(f"✅ Админ {new_id} сохранен в облако.")
        else:
            await message.answer("Он уже админ.")
            
    except ValueError:
        await message.answer("ID должен быть числом.")

@dp.message(Command("del"))
async def del_admin(message: types.Message, command: CommandObject):
    if message.from_user.id != OWNER_ID:
        return

    try:
        del_id = int(command.args.strip())
        if del_id == OWNER_ID:
            await message.answer("Себя удалить нельзя.")
            return
            
        admins = await get_admins()
        if del_id in admins:
            admins.discard(del_id)
            await save_admins_cloud(admins)
            await message.answer(f"🗑 Админ {del_id} удален из облака.")
        else:
            await message.answer("Такого ID нет.")
    except:
        await message.answer("Ошибка ввода ID.")

@dp.message(Command("list"))
async def list_admins(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    
    admins = await get_admins()
    text = "Список (из облака):\n" + "\n".join([f"`{uid}`" for uid in admins])
    await message.answer(text, parse_mode="Markdown")

# --- ПЕРЕСЫЛКА ---

# Админ отвечает
@dp.message(F.reply_to_message)
async def admin_reply(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins:
        await forward_to_admins(message, admins)
        return

    origin = message.reply_to_message.forward_origin
    if origin and isinstance(origin, MessageOriginUser):
        try:
            await message.copy_to(chat_id=origin.sender_user.id)
            await message.react([types.ReactionTypeEmoji(emoji="👍")])
        except Exception as e:
            await message.answer(f"Не удалось доставить: {e}")
    else:
        await message.answer("Не вижу ID пользователя.")

# Пользователь пишет
@dp.message()
async def forward_handler(message: types.Message):
    # Чтобы не вызывать get_admins каждый раз, можно кешировать, 
    # но для надежности здесь вызываем всегда
    admins = await get_admins()
    if message.from_user.id in admins:
        return
    await forward_to_admins(message, admins)

async def forward_to_admins(message: types.Message, admins):
    for admin_id in admins:
        try:
            await message.forward(chat_id=admin_id)
        except:
            pass

# --- SERVER ---
async def handle(request):
    return web.Response(text="Bot with Cloud Storage is running")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    await asyncio.gather(start_web_server(), dp.start_polling(bot))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
