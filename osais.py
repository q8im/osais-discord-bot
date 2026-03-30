
import os
import asyncio
import logging
from typing import Optional, Dict, List

import discord
from discord.ext import commands
import yt_dlp
from openai import OpenAI

# =========================
# Logging
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("abu-qatadah-bot")

# =========================
# Env vars
# =========================
TOKEN = os.getenv("TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

if not TOKEN:
    raise ValueError("TOKEN مو موجود. حطه في Variables.")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY مو موجود. حطه في Variables.")

ai_client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# Discord setup
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# =========================
# State
# =========================
song_queue: List[Dict] = []
is_processing = False
queue_lock = asyncio.Lock()

sticky_enabled = False
sticky_channel_id: Optional[int] = None
sticky_guild_id: Optional[int] = None
sticky_lock = asyncio.Lock()

# =========================
# Conversation memory per user
# =========================
# هذا يخلي البوت يتذكر آخر 10 رسائل لكل مستخدم
user_contexts: Dict[int, List[Dict]] = {}

MAX_CONTEXT = 10

# =========================
# YouTube/Audio
# =========================
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "default_search": "ytsearch",
    "noplaylist": True,
    "extract_flat": False,
    "skip_download": True,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

# =========================
# Fixed replies
# =========================
CREATOR_REPLY = "L1 | discord"

REAL_COMMANDS = {
    "join", "اثبت", "تحرر", "play", "شغل", "pause", "وقف",
    "resume", "كمل", "skip", "تخطي", "سكيب", "queue", "قائمة",
    "حلل", "help", "مساعدة", "اوامر", "أوامر", "اسأل"
}

def asks_about_creator(text: str) -> bool:
    t = text.strip().lower()
    triggers = [
        "منو صنعك", "من صنعك", "منو برمجك", "من برمجك",
        "منو سواك", "من سواك", "مين صنعك", "مين برمجك",
        "مين سواك", "who made you", "who created you", "who programmed you"
    ]
    return any(x in t for x in triggers)

def should_route_to_ai_from_bang(content: str) -> bool:
    if not content.startswith("!"):
        return False
    after_bang = content[1:].strip()
    if not after_bang:
        return True
    first_word = after_bang.split()[0].lower()
    return first_word not in REAL_COMMANDS

def get_fixed_keyword_reply(text: str) -> Optional[str]:
    t = text.strip().lower()
    KEYWORD_REPLIES = {
        "كس امك": "تسبني ليه يا قحبه يا قحه يا شرموط عيري فيك مناك عرصه",
        "انيكك": "ترا بنيك طيز طيز يا خنيث فاهم يلا انقلع عني يا بو خرق علشان ما احط سبعي بطيزك واطير واقعد ويمسكوني ويحطون سفره ويحطون تيليفونات",
        "☺ قحبه": "انت قحبه"
    }
    return KEYWORD_REPLIES.get(t)

# =========================
# AI helpers
# =========================
async def ask_ai(user_text: str, user_id: int, user_name: str = "مستخدم") -> str:
    if asks_about_creator(user_text):
        return CREATOR_REPLY

    # نحافظ على سياق المحادثة
    ctx_list = user_contexts.get(user_id, [])

    ctx_list.append({"role": "user", "content": user_text})
    if len(ctx_list) > MAX_CONTEXT:
        ctx_list = ctx_list[-MAX_CONTEXT:]

    user_contexts[user_id] = ctx_list

    loop = asyncio.get_running_loop()

    def _run():
        response = ai_client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system",
                 "content": (
                     "أنت بوت ديسكورد اسمك ابو قتاده. "
                     "تتكلم بالعربي باللهجة الكويتية، فكاهي شوي، وتجاوب بأسلوب طبيعي. "
                     "تتذكر كل المحادثة السابقة مع كل مستخدم وتجاوب على سياق السؤال. "
                     "إذا أحد سأل عن الصورة الأخيرة أو موضوع سابق، تقدر تربط الإجابة بالسياق. "
                     "تجنب إضافة ردود ثابتة للمستخدمين، ركّز على محتوى السؤال."
                 )},
                *ctx_list
            ]
        )
        return response.output_text

    try:
        result = await loop.run_in_executor(None, _run)
        return (result or "ما عرفت أرد عليك الحين، جرّب بعد شوي.").strip()
    except Exception as e:
        logger.exception("AI text error: %s", e)
        return "الذكاء الاصطناعي مطلع روحه الحين، جرّب بعد شوي."

async def ask_ai_about_image(image_url: str, user_text: str, user_id: int, user_name: str = "مستخدم") -> str:
    ctx_list = user_contexts.get(user_id, [])

    ctx_list.append({"role": "user", "content": f"{user_text}\n[صورة: {image_url}]"})
    if len(ctx_list) > MAX_CONTEXT:
        ctx_list = ctx_list[-MAX_CONTEXT:]

    user_contexts[user_id] = ctx_list

    loop = asyncio.get_running_loop()

    def _run():
        response = ai_client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system",
                 "content": (
                     "أنت بوت ديسكورد اسمك ابو قتاده. "
                     "اشرح الصور وأجاوب على الأسئلة بشكل واضح ومباشر وبأسلوب كويتي خفيف وفكاهي. "
                     "تتذكر كل الصور السابقة وسياق المحادثة مع كل مستخدم."
                 )},
                *ctx_list
            ]
        )
        return response.output_text

    try:
        result = await loop.run_in_executor(None, _run)
        return (result or "ما قدرت أفهم الصورة الحين.").strip()
    except Exception as e:
        logger.exception("AI vision error: %s", e)
        return "ما قدرت أفهم الصورة الحين، جرّب بعد شوي."

# =========================
# باقي كود الموسيقى والأوامر كما كان
# =========================

# (يمكنك نسخ كل أوامر join, play, pause, queue, sticky إلخ بدون تعديل، 
#  لكن فقط استبدل ask_ai و ask_ai_about_image بالنسخة الجديدة اللي تحفظ السياق)

# =========================
# تعديل on_message
# =========================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.strip()
    bot_mentioned = bot.user in message.mentions if bot.user else False

    fixed_reply = get_fixed_keyword_reply(content)
    if fixed_reply:
        await message.channel.send(fixed_reply)
        return

    # صورة + منشن
    if bot_mentioned and message.attachments:
        img = message.attachments[0]
        if img.content_type and img.content_type.startswith("image/"):
            clean_text = content
            if bot.user:
                clean_text = clean_text.replace(f"<@{bot.user.id}>", "")
                clean_text = clean_text.replace(f"<@!{bot.user.id}>", "")
                clean_text = clean_text.strip()
            if not clean_text:
                clean_text = "اشرح الصورة وعط رأيك فيها"

            async with message.channel.typing():
                reply = await ask_ai_about_image(
                    img.url,
                    clean_text,
                    message.author.id,
                    message.author.display_name
                )
            await message.channel.send(reply[:1900])
            return

    # منشن بدون صورة
    if bot_mentioned:
        clean_text = content
        if bot.user:
            clean_text = clean_text.replace(f"<@{bot.user.id}>", "")
            clean_text = clean_text.replace(f"<@!{bot.user.id}>", "")
            clean_text = clean_text.strip()

        if not clean_text:
            await message.channel.send("هاه شتبي؟ لا تطولها بس.")
            return

        async with message.channel.typing():
            reply = await ask_ai(clean_text, message.author.id, message.author.display_name)
        await message.channel.send(reply[:1900])
        return

    # رسالة ! routed to AI
    if should_route_to_ai_from_bang(content):
        question = content[1:].strip()
        if not question:
            await message.channel.send("اكتب سؤالك عقب ! لا تصير مستعجل 😏")
            return

        async with message.channel.typing():
            reply = await ask_ai(question, message.author.id, message.author.display_name)
        await message.channel.send(reply[:1900])
        return

    await bot.process_commands(message)

# =========================
# تشغيل البوت
# =========================
bot.run(TOKEN)
