import asyncio
import logging
import os
import re # Нужен для поиска цифр ID в тексте
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

# Настройки облака (JSONBin)
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

# --- ОБРАБОТКА СООБЩЕНИЙ ОТ ПОЛЬЗОВАТЕЛЕЙ ---

@dp.message(F.chat.type == "private")
async def user_message_handler(message: types.Message):
    admins = await get_admins()
    
    # 1. Если пишет админ (Владелец или из списка)
    if message.from_user.id in admins:
        # Проверяем, является ли это ответом (Reply)
        if message.reply_to_message:
            await handle_admin_reply(message)
        else:
            # Если админ просто пишет (не reply), обрабатываем как команды или игнорим
             pass 
        return

    # 2. Если пишет обычный пользователь -> Пересылаем админам
    await forward_to_admins(message, admins)

async def forward_to_admins(message: types.Message, admins):
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    
    # Формируем техническое сообщение (невидимку), чтобы админ мог ответить
    info_text = (f"📩 Сообщение от {first_name}\n"
                 f"🆔 ID: `{user_id}`\n"
                 f"↘️ Ответьте (Reply) на ЭТО сообщение, чтобы отправить ответ пользователю.")

    for aid in admins:
        try:
            # Сначала пересылаем само сообщение (фото, видео, текст)
            forwarded_msg = await message.forward(chat_id=aid)
            
            # Следом отправляем "Карточку пользователя", привязывая её ответом к пересланному сообщению
            await bot.send_message(
                chat_id=aid, 
                text=info_text, 
                reply_to_message_id=forwarded_msg.message_id,
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Не удалось переслать админу {aid}: {e}")

# --- ОБРАБОТКА ОТВЕТА АДМИНА ---

async def handle_admin_reply(message: types.Message):
    reply_msg = message.reply_to_message
    target_user_id = None

    # ВАРИАНТ 1: Админ ответил на нашу "Техническую карточку" (где написано ID: 123...)
    if reply_msg.text and "🆔 ID:" in reply_msg.text:
        try:
            # Ищем цифры ID в тексте сообщения с помощью регулярного выражения
            match = re.search(r"ID:\s*`?(\d+)`?", reply_msg.text)
            if match:
                target_user_id = int(match.group(1))
        except:
            pass

    # ВАРИАНТ 2: Админ ответил прямо на пересланное сообщение (Старый способ, работает если профиль открыт)
    if not target_user_id and reply_msg.forward_origin:
        origin = reply_msg.forward_origin
        if isinstance(origin, MessageOriginUser):
            target_user_id = origin.sender_user.id

    # ОТПРАВКА
    if target_user_id:
        try:
            # Отправляем копию сообщения (copy_message поддерживает фото, видео, голосовые)
            await message.copy_to(chat_id=target_user_id)
            await message.react([types.ReactionTypeEmoji(emoji="👍")]) # Подтверждение лайком
        except Exception as e:
            await message.answer(f"❌ Не удалось отправить (пользователь заблокировал бота?): {e}")
    else:
        await message.answer("⚠️ Не могу определить получателя.\n"
                             "Пожалуйста, отвечайте (Reply) на сообщение с текстом '🆔 ID: ...', которое приходит следом за фото/текстом.")

# --- КОМАНДЫ ---

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
        await message.answer("Здравствуйте! Пришлите вашу историю или видео, и мы опубликуем это.")

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
