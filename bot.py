import asyncio
import logging
import os
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import MessageOriginUser
from aiohttp import web, ClientSession

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = os.getenv('BOT_TOKEN')
raw_admin_id = os.getenv('ADMIN_ID', '0')
try:
    OWNER_ID = int(str(raw_admin_id).strip())
except ValueError:
    OWNER_ID = 0

BIN_ID = os.getenv('BIN_ID')
BIN_API_KEY = os.getenv('BIN_API_KEY')
if BIN_ID:
    BIN_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID.strip()}"
else:
    BIN_URL = ""

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- ФУНКЦИИ БАЗЫ ДАННЫХ ---
async def get_admins():
    admins = {OWNER_ID}
    if not BIN_URL or not BIN_API_KEY: return admins
    headers = {"X-Master-Key": BIN_API_KEY.strip()}
    try:
        async with ClientSession() as session:
            async with session.get(f"{BIN_URL}/latest", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    saved_list = data.get("record", [])
                    if isinstance(saved_list, list): admins.update(saved_list)
    except: pass
    return admins

async def save_admins_cloud(admin_list, message=None):
    if not BIN_URL: return
    headers = {"Content-Type": "application/json", "X-Master-Key": BIN_API_KEY.strip()}
    try:
        async with ClientSession() as session:
            await session.put(BIN_URL, json=list(admin_list), headers=headers)
    except Exception as e:
        if message: await message.answer(f"Ошибка сохранения: {e}")

# ==========================================
# 1. БЛОК КОМАНД (ОНИ ДОЛЖНЫ БЫТЬ ПЕРВЫМИ!)
# ==========================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    admins = await get_admins()
    if message.from_user.id in admins:
        await message.answer(f"👋 Привет, Админ!\n\n"
                             f"Теперь, когда пользователь напишет, вы получите 2 сообщения:\n"
                             f"1. Само сообщение.\n"
                             f"2. Информацию с ID.\n\n"
                             f"👉 Чтобы ответить, делайте **Reply на сообщение с ID**.")
    else:
        await message.answer("Приветствую! Если у вас есть чем поделиться или у вас есть идеи и предложения, как улучшить канал, — пишите сюда👇.")

@dp.message(Command("add"))
async def add_admin(message: types.Message, command: CommandObject):
    if message.from_user.id != OWNER_ID: return
    if not command.args: return
    try:
        new_id = int(command.args.strip())
        admins = await get_admins()
        admins.add(new_id)
        await save_admins_cloud(admins, message)
        await message.answer(f"✅ Админ {new_id} добавлен.")
    except: await message.answer("Ошибка ID")

@dp.message(Command("del"))
async def del_admin(message: types.Message, command: CommandObject):
    if message.from_user.id != OWNER_ID: return
    try:
        del_id = int(command.args.strip())
        admins = await get_admins()
        if del_id in admins:
            admins.discard(del_id)
            await save_admins_cloud(admins, message)
            await message.answer("Удален.")
    except: pass

@dp.message(Command("list"))
async def list_admins(message: types.Message):
    if message.from_user.id != OWNER_ID: return
    admins = await get_admins()
    await message.answer(f"Админы: {list(admins)}")
    
@dp.message(Command("check"))
async def debug_check(message: types.Message):
    await message.answer(f"Ваш ID: {message.from_user.id}\nOwner ID: {OWNER_ID}\nBin: {'OK' if BIN_URL else 'NO'}")


# ==========================================
# 2. БЛОК ЛОГИКИ (ПЕРЕСЫЛКА И ОТВЕТЫ)
# ==========================================

# Обработчик ответов админа (Reply)
@dp.message(F.reply_to_message)
async def handle_admin_reply(message: types.Message):
    admins = await get_admins()
    
    # Если это не админ - значит это обычный юзер делает reply, отправляем админам как обычное сообщение
    if message.from_user.id not in admins:
        await forward_to_admins(message, admins)
        return

    # ЛОГИКА АДМИНА
    reply_msg = message.reply_to_message
    target_user_id = None

    # Способ А: Ответ на техническое сообщение с ID
    if reply_msg.text and "🆔 ID:" in reply_msg.text:
        try:
            match = re.search(r"ID:\s*`?(\d+)`?", reply_msg.text)
            if match:
                target_user_id = int(match.group(1))
        except: pass

    # Способ Б: Ответ на пересланное (если профиль открыт)
    if not target_user_id and reply_msg.forward_origin:
        origin = reply_msg.forward_origin
        if isinstance(origin, MessageOriginUser):
            target_user_id = origin.sender_user.id

    if target_user_id:
        try:
            await message.copy_to(chat_id=target_user_id)
            await message.react([types.ReactionTypeEmoji(emoji="👍")])
        except Exception as e:
            await message.answer(f"❌ Не дошло: {e}")
    else:
        await message.answer("⚠️ Чтобы ответить пользователю со скрытым профилем, сделайте Reply на сообщение с текстом '🆔 ID: ...'")


# Обработчик всех остальных сообщений (от пользователей)
@dp.message()
async def user_message_handler(message: types.Message):
    admins = await get_admins()
    
    # Админы не должны спамить сами себе, если просто пишут текст без команды
    if message.from_user.id in admins:
        return

    # Пересылка
    await forward_to_admins(message, admins)

async def forward_to_admins(message: types.Message, admins):
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    
    # Текст для карточки
    info_text = (f"📩 Сообщение от {first_name}\n"
                 f"🆔 ID: `{user_id}`\n"
                 f"↘️ Ответьте на ЭТО сообщение.")

    for aid in admins:
        try:
            # 1. Пересылаем контент
            forwarded = await message.forward(chat_id=aid)
            # 2. Шлем карточку с ID ответом на контент
            await bot.send_message(chat_id=aid, text=info_text, reply_to_message_id=forwarded.message_id)
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
