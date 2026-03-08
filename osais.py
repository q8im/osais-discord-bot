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

CREATOR_REPLY = "L1 | discord @734f"

# الأوامر الحقيقية حتى ما ينحسبون كسؤال AI
REAL_COMMANDS = {
    "join",
    "اثبت",
    "تحرر",
    "play",
    "شغل",
    "pause",
    "وقف",
    "resume",
    "كمل",
    "skip",
    "تخطي",
    "سكيب",
    "queue",
    "قائمة",
    "حلل",
    "help",
    "مساعدة",
    "اوامر",
    "أوامر",
    "اسأل",
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
    """
    يخلي الرسائل اللي تبدأ بـ ! وتكون مو أمر معروف تنرسل للذكاء الاصطناعي.
    أمثلة:
    ! شلونك     -> AI
    !منو انت    -> AI
    !join       -> command
    !play song  -> command
    """
    if not content.startswith("!"):
        return False

    after_bang = content[1:].strip()
    if not after_bang:
        return True

    first_word = after_bang.split()[0].lower()
    return first_word not in REAL_COMMANDS


def get_fixed_keyword_reply(text: str) -> Optional[str]:
    """
    ردود ثابتة خارج الذكاء الاصطناعي.
    إذا كتب المستخدم كلمة محددة، البوت يرد برد ثابت من هنا مباشرة.
    """
    t = text.strip().lower()

def get_fixed_keyword_reply(text: str) -> Optional[str]:
    t = text.strip().lower()

    KEYWORD_REPLIES = {
        "كس امك": "تسبني ليه يا قحبه يا قحه يا شرموط عيري فيك مناك عرصه",
        "انيكك": "ترا بنيك طيز طيز يا خنيث فاهم يلا انقلع عني يا بو خرق علشان ما احط سبعي بطيزك واطير واقعد ويمسكوني ويحطون سفره ويحطون تيليفونات",
        "☺ قحبه": "انت قحبه"
    }

    return KEYWORD_REPLIES.get(t)

# =========================
# AI text helper
# =========================
async def ask_ai(user_text: str, user_name: str = "مستخدم") -> str:
    if asks_about_creator(user_text):
        return CREATOR_REPLY

    loop = asyncio.get_running_loop()

    def _run():
        response = ai_client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "أنت بوت ديسكورد اسمك ابو قتاده. "
                        "لازم ترد دائمًا بالعربي وباللهجة الكويتية. "
                        "أسلوبك فكاهي بزيادة وتحب التمطيط والمزح الخفيف. "
                        "إذا أحد قال لك ضحكني، رد عليه برد مضحك وساخر مثل: ليش شايفني ارقوز اشتغل عندك؟ "
                        "او مرات قل: انقلع عني لا اتغشمر تفضل هههه. "
                        "إذا أحد قال أبيك تساعدني أو ساعدني، رد عليه رد كويتي مضحك مثل: شتبي اخلص علينا؟ "
                        "مسموح تكون وقح بشكل خفيف ومضحك، لكن بدون إساءة جارحة. "
                        "إذا أحد سألك منو صنعك أو منو برمجك أو من سواك، جاوبه فقط بهذا النص: L1 | discord @734f "
                        "إذا أحد سألك من أنت، قل: أنا ابو قتاده، بوت ديسكورد للأغاني والذكاء الاصطناعي. "
                        "إذا كان السؤال عن شخص أو معلومة عامة جاوب بشكل طبيعي ومضحك شوي. "
                        "تكلم كأنك انسان أكثر وتفاعل وخلك فكاهي."
                    ),
                },
                {
                    "role": "user",
                    "content": f"اسم المستخدم: {user_name}\nالرسالة: {user_text}",
                },
            ],
        )
        return response.output_text

    try:
        result = await loop.run_in_executor(None, _run)
        return (result or "ما عرفت أرد عليك الحين، رح وتعال بعد شوي.").strip()
    except Exception as e:
        logger.exception("AI text error: %s", e)
        return "الذكاء الاصطناعي مطلع روحه الحين، جرّب بعد شوي."


# =========================
# AI vision helper
# =========================
async def ask_ai_about_image(image_url: str, user_text: str, user_name: str = "مستخدم") -> str:
    loop = asyncio.get_running_loop()

    def _run():
        response = ai_client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "أنت بوت ديسكورد اسمك ابو قتاده. "
                        "رد دائمًا بالعربي وباللهجة الكويتية. "
                        "اشرح الصورة بشكل واضح ومباشر وبأسلوب كويتي خفيف وفكاهي. "
                        "إذا طلب المستخدم رأيك بالصورة، عطه رأيك بشكل لطيف أو ساخر خفيف. "
                        "إذا الصورة فيها أشخاص أو أشياء، صف الموجود بشكل طبيعي بدون مبالغة. "
                        "إذا كان السؤال عن شي محدد بالصورة، جاوب عليه مباشرة."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": f"اسم المستخدم: {user_name}\nالسؤال: {user_text}"},
                        {"type": "input_image", "image_url": image_url},
                    ],
                },
            ],
        )
        return response.output_text

    try:
        result = await loop.run_in_executor(None, _run)
        return (result or "ما قدرت أفهم الصورة الحين.").strip()
    except Exception as e:
        logger.exception("AI vision error: %s", e)
        return "ما قدرت أفهم الصورة الحين، جرّب بعد شوي."


# =========================
# Music helpers
# =========================
async def get_song_info(search: str):
    loop = asyncio.get_running_loop()

    def _run():
        return ytdl.extract_info(search, download=False)

    data = await loop.run_in_executor(None, _run)

    if data is None:
        raise ValueError("ما قدرت أوصل للأغنية.")

    if "entries" in data:
        entries = data.get("entries") or []
        if not entries:
            raise ValueError("ما حصلت نتيجة.")
        data = entries[0]

    stream_url = data.get("url")
    if not stream_url:
        raise ValueError("ما لقيت رابط تشغيل مباشر.")

    return {
        "title": data.get("title", "غير معروف"),
        "url": stream_url,
        "webpage_url": data.get("webpage_url", search),
        "uploader": data.get("uploader", "غير معروف"),
    }


async def ensure_voice_for_ctx(ctx) -> Optional[discord.VoiceClient]:
    global sticky_enabled, sticky_channel_id

    if ctx.author.voice is None or ctx.author.voice.channel is None:
        await ctx.send("دش روم صوتي أول بعدين تعال تفلسف علي.")
        return None

    target_channel = ctx.author.voice.channel
    vc = ctx.guild.voice_client

    try:
        if sticky_enabled and sticky_channel_id is not None:
            sticky_channel = ctx.guild.get_channel(sticky_channel_id)
            if sticky_channel is not None:
                if vc is None or not vc.is_connected():
                    vc = await sticky_channel.connect(self_deaf=True)
                    await asyncio.sleep(1)
                    return vc

                if vc.channel and vc.channel.id != sticky_channel_id:
                    await vc.move_to(sticky_channel)
                return vc

        if vc is None or not vc.is_connected():
            vc = await target_channel.connect(self_deaf=True)
            await asyncio.sleep(1)
            return vc

        if vc.channel and vc.channel.id != target_channel.id:
            await vc.move_to(target_channel)

        return vc

    except Exception as e:
        logger.exception("Voice ensure error: %s", e)
        await ctx.send("ما قدرت أدخل الروم الصوتي.")
        return None


async def ensure_sticky_voice():
    global sticky_enabled, sticky_channel_id, sticky_guild_id

    async with sticky_lock:
        if not sticky_enabled or sticky_channel_id is None or sticky_guild_id is None:
            return None

        guild = bot.get_guild(sticky_guild_id)
        if guild is None:
            sticky_enabled = False
            sticky_channel_id = None
            sticky_guild_id = None
            return None

        channel = guild.get_channel(sticky_channel_id)
        if channel is None or not isinstance(channel, discord.VoiceChannel):
            sticky_enabled = False
            sticky_channel_id = None
            sticky_guild_id = None
            logger.info("الروم المثبت انمسح، تم التحرر تلقائيًا.")
            return None

        vc = guild.voice_client

        try:
            if vc is None or not vc.is_connected():
                vc = await channel.connect(self_deaf=True)
                await asyncio.sleep(1)
                logger.info("رجعت للروم المثبت: %s", channel.name)
                return vc

            if vc.channel and vc.channel.id != sticky_channel_id:
                await vc.move_to(channel)
                logger.info("انسحبت للروم المثبت: %s", channel.name)

            return vc
        except Exception as e:
            logger.exception("Sticky voice error: %s", e)
            return None


async def play_next(text_channel: discord.TextChannel):
    global is_processing

    guild = text_channel.guild
    vc = guild.voice_client

    if vc is None or not vc.is_connected():
        if sticky_enabled:
            vc = await ensure_sticky_voice()
        else:
            is_processing = False
            return

    if not song_queue:
        is_processing = False
        return

    song = song_queue.pop(0)

    try:
        source = await discord.FFmpegOpusAudio.from_probe(
            song["url"],
            method="fallback",
            **FFMPEG_OPTIONS
        )

        def after_playing(error):
            if error:
                logger.exception("Playback error: %s", error)
            future = asyncio.run_coroutine_threadsafe(play_next(text_channel), bot.loop)
            try:
                future.result()
            except Exception as e:
                logger.exception("Queue error: %s", e)

        vc.play(source, after=after_playing)

        await text_channel.send(
            f"🎵 شغّلت: **{song['title']}**\n"
            f"👤 الناشر: **{song['uploader']}**\n"
            f"🔗 {song['webpage_url']}"
        )

    except Exception as e:
        logger.exception("Play next error: %s", e)
        await text_channel.send("صار خطأ بالتشغيل، بجرب اللي بعدها.")
        await play_next(text_channel)


# =========================
# Events
# =========================
@bot.event
async def on_ready():
    logger.info("البوت اشتغل: %s", bot.user)


@bot.event
async def on_guild_channel_delete(channel):
    global sticky_enabled, sticky_channel_id, sticky_guild_id

    if sticky_enabled and sticky_channel_id == channel.id:
        sticky_enabled = False
        sticky_channel_id = None
        sticky_guild_id = None
        logger.info("الروم المثبت انحذف، تم التحرر تلقائيًا.")


@bot.event
async def on_voice_state_update(member, before, after):
    if not bot.user or member.id != bot.user.id:
        return

    if sticky_enabled:
        if before.channel is not None and after.channel is None:
            await asyncio.sleep(2)
            await ensure_sticky_voice()
            return

        if after.channel is not None and sticky_channel_id is not None:
            if after.channel.id != sticky_channel_id:
                await asyncio.sleep(1)
                await ensure_sticky_voice()


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


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.strip()
    bot_mentioned = bot.user in message.mentions if bot.user else False

    # رد ثابت للكلمات المحددة خارج الذكاء الاصطناعي
    fixed_reply = get_fixed_keyword_reply(content)
    if fixed_reply:
        await message.channel.send(fixed_reply)
        return

    # إذا منشن ومعاه صورة
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
                    message.author.display_name
                )

            await message.channel.send(reply[:1900])
            return

    # إذا منشن بدون صورة
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
            reply = await ask_ai(clean_text, message.author.display_name)

        await message.channel.send(reply[:1900])
        return

    # إذا المستخدم كتب ! وسؤاله مباشرة
    if should_route_to_ai_from_bang(content):
        question = content[1:].strip()

        if not question:
            await message.channel.send("اكتب سؤالك عقب ! لا تصير مستعجل 😏")
            return

        async with message.channel.typing():
            reply = await ask_ai(question, message.author.display_name)

        # إذا من الأشخاص المحددين، يرسل الرد الخاص + الذكاء الاصطناعي
        if message.author.id in SPECIAL_USERS:
            final_reply = f"{SPECIAL_USERS[message.author.id]}\n\n{reply}"
        else:
            final_reply = reply

        await message.channel.send(final_reply[:1900])
        return

    await bot.process_commands(message)


# =========================
# Commands
# =========================
@bot.command(name="join")
async def join_command(ctx):
    vc = await ensure_voice_for_ctx(ctx)
    if vc:
        await ctx.send(f"🎧 دخلت روم **{vc.channel.name}**.")


@bot.command(name="اثبت")
async def sticky_command(ctx):
    global sticky_enabled, sticky_channel_id, sticky_guild_id

    if ctx.author.voice is None or ctx.author.voice.channel is None:
        await ctx.send("دش روم صوتي أول بعدين قولي اثبت.")
        return

    target_channel = ctx.author.voice.channel
    vc = ctx.guild.voice_client

    try:
        if vc is None or not vc.is_connected():
            vc = await target_channel.connect(self_deaf=True)
            await asyncio.sleep(1)
        elif vc.channel is None or vc.channel.id != target_channel.id:
            await vc.move_to(target_channel)

        sticky_enabled = True
        sticky_channel_id = target_channel.id
        sticky_guild_id = ctx.guild.id

        await ctx.send(f"تم التثبيت في **{target_channel.name}**. الحين لو ينطرد برجع غصب 😏")
    except Exception as e:
        logger.exception("Sticky command error: %s", e)
        await ctx.send("ما قدرت أثبت نفسي بالروم.")


@bot.command(name="تحرر")
async def unsticky_command(ctx):
    global sticky_enabled, sticky_channel_id, sticky_guild_id

    sticky_enabled = False
    sticky_channel_id = None
    sticky_guild_id = None

    await ctx.send("تم التحرر. الحين إذا انطردت ما برجع.")


@bot.command(name="play", aliases=["شغل"])
async def play_command(ctx, *, search: str):
    global is_processing

    vc = await ensure_voice_for_ctx(ctx)
    if vc is None:
        return

    try:
        await ctx.send("لحظة، قاعد أدور على الأغنية... 🎶")
        song = await get_song_info(search)

        if song_queue and song_queue[-1]["webpage_url"] == song["webpage_url"]:
            await ctx.send("هذي نفسها آخر أغنية بالقائمة، لا تعيدها علي.")
            return

        song_queue.append(song)
        await ctx.send(f"➕ ضفتها للقائمة: **{song['title']}**")

        async with queue_lock:
            if not is_processing and not vc.is_playing() and not vc.is_paused():
                is_processing = True
                await play_next(ctx.channel)

    except Exception as e:
        logger.exception("Play command error: %s", e)
        await ctx.send("صار خطأ وأنا أدور على الأغنية.")


@bot.command(name="pause", aliases=["وقف"])
async def pause_command(ctx):
    vc = ctx.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await ctx.send("⏸️ وقفتها مؤقت.")
    else:
        await ctx.send("ماكو شي شغال.")


@bot.command(name="resume", aliases=["كمل"])
async def resume_command(ctx):
    vc = ctx.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await ctx.send("▶️ كملت التشغيل.")
    else:
        await ctx.send("ماكو شي موقوف.")


@bot.command(name="skip", aliases=["تخطي", "سكيب"])
async def skip_command(ctx):
    vc = ctx.guild.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        await ctx.send("⏭️ تم التخطي.")
    else:
        await ctx.send("ماكو شي أتخطاه.")


@bot.command(name="queue", aliases=["قائمة"])
async def queue_command(ctx):
    if song_queue:
        msg = "\n".join([f"{i+1}. {song['title']}" for i, song in enumerate(song_queue)])
        await ctx.send(f"📜 قائمة الأغاني:\n{msg}")
    else:
        await ctx.send("القائمة فاضية.")


@bot.command(name="اسأل")
async def ai_command(ctx, *, question: str):
    async with ctx.channel.typing():
        reply = await ask_ai(question, ctx.author.display_name)

    await ctx.send(reply[:1900])


@bot.command(name="حلل")
async def vision_command(ctx, *, question: str = "اشرح الصورة وعط رأيك فيها"):
    if not ctx.message.attachments:
        await ctx.send("ارسل صورة مع الأمر بعدين تعال.")
        return

    img = ctx.message.attachments[0]
    if not img.content_type or not img.content_type.startswith("image/"):
        await ctx.send("هذي مو صورة.")
        return

    async with ctx.channel.typing():
        reply = await ask_ai_about_image(img.url, question, ctx.author.display_name)

    await ctx.send(reply[:1900])


@bot.command(name="help", aliases=["مساعدة", "اوامر", "أوامر"])
async def help_command(ctx):
    await ctx.send(
        "**أوامر ابو قتاده**\n\n"
        "`!join` يدخل الروم اللي إنت فيه\n"
        "`!اثبت` يثبتني في الروم الحالي وإذا انطردت أرجع\n"
        "`!تحرر` يفك التثبيت\n"
        "`!play` أو `!شغل` + اسم الأغنية أو الرابط\n"
        "`!pause` أو `!وقف`\n"
        "`!resume` أو `!كمل`\n"
        "`!skip` أو `!تخطي`\n"
        "`!queue` أو `!قائمة`\n"
        "`!` + سؤالك مباشرة للذكاء الاصطناعي\n"
        "مثال: `! شلونك` أو `!منو انت`\n"
        "`!حلل` مع صورة"
    )


# =========================
# Errors
# =========================
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.exception("Unhandled command error: %s", error)


@join_command.error
@sticky_command.error
@unsticky_command.error
@play_command.error
@pause_command.error
@resume_command.error
@skip_command.error
@queue_command.error
@ai_command.error
@vision_command.error
@help_command.error
async def command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("ناقصك شي بالأمر.")
    else:
        logger.exception("Command error: %s", error)
        await ctx.send("صار خطأ بسيط، جرّب مرة ثانية.")


bot.run(TOKEN)

