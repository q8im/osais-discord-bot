import os
import asyncio
import logging
from typing import Optional

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
song_queue = []
is_processing = False
queue_lock = asyncio.Lock()

sticky_enabled = False
sticky_channel_id: Optional[int] = None
sticky_guild_id: Optional[int] = None
sticky_lock = asyncio.Lock()

conversation_history = {}  # key = channel_id, value = list of dicts for memory

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

CREATOR_REPLY = "L1 | discord"

REAL_COMMANDS = {
    "join","اثبت","تحرر","play","شغل","pause","وقف","resume","كمل",
    "skip","تخطي","سكيب","queue","قائمة","حلل","help","مساعدة",
    "اوامر","أوامر","اسأل"
}

SPECIAL_USERS = {
    841779552979910746: "انت الهوى وانت النفس وانت بحياتي كلشي انت العمر وانت النبض بالروح حبك يمشي 🤴 امر تدلل حمودي ؟",
    1119049885254176798: "نواف آمر شتبي؟ اخلص",
    1463671451566608458: "نواف آمر شتبي؟ اخلص",
    767626889380233246: "حسوني يلوموني فيك 🤤 تفضل قول امر شاورما ؟",
    1137052965191041094: "فصيل افتح افتح نت تفضل قول امر ؟",
    970582370166116433: "علي تفضل قول امر شاورما ولا سيخ كباب ههههاها دمي؟",
    763667733933719573: "حمود يا هلا قول قول امر ؟",
    1401558038187344053: "ما ختمت رزدنت عبدالله يا هلا قول قول امر ؟",
    1330594901599191060: "فجوره فديتج اخخ اموت فيج قولي جعلني فداس",
    978909635270561822: "توب المهندسه قولي امري ؟",
    944979711581376542: "فصيل آمر شتبي؟ اخلص",
}

# =========================
# Helpers
# =========================
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
# AI helpers with memory
# =========================
async def ask_ai_with_memory(user_text: str, channel_id: int, user_name: str = "مستخدم") -> str:
    if asks_about_creator(user_text):
        return CREATOR_REPLY

    # استرجاع السياق
    history = conversation_history.get(channel_id, [])

    # إضافة السؤال الجديد
    history.append({"role": "user", "content": f"{user_name}: {user_text}"})

    loop = asyncio.get_running_loop()

    def _run():
        response = ai_client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "أنت بوت ديسكورد اسمه ابو قتاده، تتذكر سياق الكلام السابق بنفس القناة، "
                        "تجاوب باللهجة الكويتية وفكاهي، وتقدر تربط الأسئلة ببعض."
                    ),
                },
                *history
            ],
        )
        return response.output_text

    try:
        result = await loop.run_in_executor(None, _run)
        # حفظ الرد في الذاكرة
        history.append({"role": "assistant", "content": result})
        conversation_history[channel_id] = history[-10:]  # آخر 10 رسائل فقط
        return result
    except Exception as e:
        logger.exception("AI memory error: %s", e)
        return "ما قدرت أفهم السياق الحين، جرّب بعد شوي."


async def ask_ai_about_image_with_memory(image_url: str, user_text: str, channel_id: int, user_name: str = "مستخدم") -> str:
    history = conversation_history.get(channel_id, [])

    # إضافة الصورة للسجل
    history.append({
        "role": "user",
        "content": f"{user_name} أرسل صورة: {image_url}\nوكتب: {user_text}"
    })

    loop = asyncio.get_running_loop()

    def _run():
        response = ai_client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "أنت بوت ديسكورد اسمه ابو قتاده، تتذكر الصور والسياق السابق، "
                        "رد بالعربي باللهجة الكويتية وفكاهي، وعندك قدرة على شرح الصورة بدقة."
                    ),
                },
                *history
            ],
        )
        return response.output_text

    try:
        result = await loop.run_in_executor(None, _run)
        # حفظ الرد
        history.append({"role": "assistant", "content": result})
        conversation_history[channel_id] = history[-10:]
        return result
    except Exception as e:
        logger.exception("AI vision memory error: %s", e)
        return "ما قدرت أفهم الصورة الحين، جرّب بعد شوي."

# =========================
# (الأوامر، الموسيقى، الصوت، الأحداث) 
# نفس سكربتك الأصلي بدون تغيير، مع استبدال ask_ai بـ ask_ai_with_memory
# وأيضًا ask_ai_about_image بـ ask_ai_about_image_with_memory
# =========================
# مثال:
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

    if bot_mentioned and message.attachments:
        img = message.attachments[0]
        if img.content_type and img.content_type.startswith("image/"):
            clean_text = content
            if bot.user:
                clean_text = clean_text.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
            if not clean_text:
                clean_text = "اشرح الصورة وعط رأيك فيها"

            async with message.channel.typing():
                reply = await ask_ai_about_image_with_memory(
                    img.url,
                    clean_text,
                    message.channel.id,
                    message.author.display_name
                )
            await message.channel.send(reply[:1900])
            return

    if bot_mentioned:
        clean_text = content
        if bot.user:
            clean_text = clean_text.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        if not clean_text:
            await message.channel.send("هاه شتبي؟ لا تطولها بس.")
            return

        async with message.channel.typing():
            reply = await ask_ai_with_memory(clean_text, message.channel.id, message.author.display_name)

        if message.author.id in SPECIAL_USERS:
            final_reply = f"{SPECIAL_USERS[message.author.id]}\n\n{reply}"
        else:
            final_reply = reply

        await message.channel.send(final_reply[:1900])
        return

    if should_route_to_ai_from_bang(content):
        question = content[1:].strip()
        if not question:
            await message.channel.send("اكتب سؤالك عقب ! لا تصير مستعجل 😏")
            return

        async with message.channel.typing():
            reply = await ask_ai_with_memory(question, message.channel.id, message.author.display_name)

        if message.author.id in SPECIAL_USERS:
            final_reply = f"{SPECIAL_USERS[message.author.id]}\n\n{reply}"
        else:
            final_reply = reply

        await message.channel.send(final_reply[:1900])
        return

    await bot.process_commands(message)

# =========================
# أمر لمسح الذاكرة
# =========================
@bot.command(name="resetmemory")
async def reset_memory(ctx):
    conversation_history[ctx.channel.id] = []
    await ctx.send("تم مسح ذاكرة السياق حق القناة.")

# =========================
# باقي الأوامر (play, pause, skip, join, etc.) 
# خلك على السكربت الأصلي بدون تعديل
# فقط أي ask_ai تستبدل بـ ask_ai_with_memory
# ask_ai_about_image تستبدل بـ ask_ai_about_image_with_memory
# =========================

bot.run(TOKEN)
