import os
import asyncio
import discord
from discord.ext import commands
import yt_dlp

TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
STICKY_VOICE_ID = int(os.getenv("STICKY_VOICE_ID", "0"))

if not TOKEN:
    raise ValueError("TOKEN مو موجود. حطه في Variables.")
if not GUILD_ID:
    raise ValueError("GUILD_ID مو موجود. حطه في Variables.")
if not STICKY_VOICE_ID:
    raise ValueError("STICKY_VOICE_ID مو موجود. حطه في Variables.")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

song_queue = []
is_processing = False
queue_lock = asyncio.Lock()
sticky_lock = asyncio.Lock()

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "default_search": "ytsearch",
    "noplaylist": True,
    "extract_flat": False,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


async def get_guild_and_channel():
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return None, None

    channel = guild.get_channel(STICKY_VOICE_ID)
    if channel is None or not isinstance(channel, discord.VoiceChannel):
        return guild, None

    return guild, channel


async def ensure_sticky_voice():
    async with sticky_lock:
        guild, channel = await get_guild_and_channel()

        if guild is None:
            print("ما حصلت السيرفر. تأكد من GUILD_ID.")
            return None

        if channel is None:
            print("ما حصلت الروم الصوتي. تأكد من STICKY_VOICE_ID.")
            return None

        vc = guild.voice_client

        try:
            if vc is None:
                vc = await channel.connect(self_deaf=True)
                print(f"دخلت الروم الثابت: {channel.name}")
                return vc

            if vc.channel.id != STICKY_VOICE_ID:
                await vc.move_to(channel)
                print(f"رجعت للروم الثابت: {channel.name}")

            return vc

        except Exception as e:
            print(f"Sticky voice error: {e}")
            return None


async def get_song_info(search: str):
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(
        None,
        lambda: ytdl.extract_info(search, download=False)
    )

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


async def play_next(text_channel: discord.TextChannel):
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return

    vc = guild.voice_client
    if vc is None:
        vc = await ensure_sticky_voice()
        if vc is None:
            return

    if not song_queue:
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
                print(f"Playback error: {error}")
            future = asyncio.run_coroutine_threadsafe(play_next(text_channel), bot.loop)
            try:
                future.result()
            except Exception as e:
                print(f"Queue error: {e}")

        vc.play(source, after=after_playing)

        await text_channel.send(
            f"🎵 الحين شغّلت: **{song['title']}**\n"
            f"👤 الناشر: **{song['uploader']}**\n"
            f"🔗 {song['webpage_url']}"
        )

    except Exception as e:
        await text_channel.send(f"صار خطأ بالتشغيل: `{e}`")
        await play_next(text_channel)


async def ensure_voice():
    guild, channel = await get_guild_and_channel()

    if guild is None or channel is None:
        return None

    vc = guild.voice_client

    try:
        if vc is None:
            return await channel.connect(self_deaf=True)

        if vc.channel.id != STICKY_VOICE_ID:
            await vc.move_to(channel)

        return vc

    except Exception as e:
        print(f"Voice ensure error: {e}")
        return None


@bot.event
async def on_ready():
    print(f"البوت اشتغل: {bot.user}")
    await ensure_sticky_voice()


@bot.event
async def on_voice_state_update(member, before, after):
    if member.id != bot.user.id:
        return

    if before.channel is not None and after.channel is None:
        await asyncio.sleep(2)
        await ensure_sticky_voice()

    elif after.channel is not None and after.channel.id != STICKY_VOICE_ID:
        await asyncio.sleep(2)
        await ensure_sticky_voice()


@bot.command(name="join", aliases=["ادخل"])
async def join_command(ctx):
    vc = await ensure_sticky_voice()
    if vc:
        await ctx.send("🎧 تم، دشّيت الروم الثابت.")
    else:
        await ctx.send("ما قدرت أدخل الروم الثابت. تأكد من الآيديات والصلاحيات.")


@bot.command(name="play", aliases=["شغل"])
async def play_command(ctx, *, search: str):
    global is_processing

    vc = await ensure_voice()
    if vc is None:
        await ctx.send("ما قدرت أدخل الروم الثابت.")
        return

    try:
        await ctx.send("لحظة، قاعد أدور على الأغنية... 🎶")
        song = await get_song_info(search)
        song_queue.append(song)
        await ctx.send(f"➕ ضفتها للقائمة: **{song['title']}**")

        async with queue_lock:
            if not is_processing and not vc.is_playing() and not vc.is_paused():
                is_processing = True
                await play_next(ctx.channel)

    except Exception as e:
        await ctx.send(f"صار خطأ: `{e}`")


@bot.command(name="pause", aliases=["وقف"])
async def pause_command(ctx):
    guild = bot.get_guild(GUILD_ID)
    vc = guild.voice_client if guild else None

    if vc and vc.is_playing():
        vc.pause()
        await ctx.send("⏸️ وقفتها مؤقت.")
    else:
        await ctx.send("ماكو شي شغال.")


@bot.command(name="resume", aliases=["كمل"])
async def resume_command(ctx):
    guild = bot.get_guild(GUILD_ID)
    vc = guild.voice_client if guild else None

    if vc and vc.is_paused():
        vc.resume()
        await ctx.send("▶️ كملت التشغيل.")
    else:
        await ctx.send("ماكو شي موقوف.")


@bot.command(name="skip", aliases=["تخطي", "سكيب"])
async def skip_command(ctx):
    guild = bot.get_guild(GUILD_ID)
    vc = guild.voice_client if guild else None

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


@bot.command(name="leave", aliases=["اطلع"])
@commands.has_permissions(administrator=True)
async def leave_command(ctx):
    guild = bot.get_guild(GUILD_ID)
    vc = guild.voice_client if guild else None

    if vc:
        song_queue.clear()
        await vc.disconnect(force=True)
        await ctx.send("طلعتني، بس برد للروم الثابت بعد شوي 😏")
    else:
        await ctx.send("أنا أصلًا مو داخل روم.")


@bot.command(name="help", aliases=["مساعدة", "اوامر", "أوامر"])
async def help_command(ctx):
    await ctx.send(
        "**أوامر Osais Club**\n\n"
        "`!play` أو `!شغل` + اسم الأغنية أو الرابط\n"
        "`!join` أو `!ادخل`\n"
        "`!pause` أو `!وقف`\n"
        "`!resume` أو `!كمل`\n"
        "`!skip` أو `!تخطي`\n"
        "`!queue` أو `!قائمة`\n"
        "`!leave` أو `!اطلع`\n"
        "`!help` أو `!مساعدة`"
    )

@bot.command(name="replay", aliases=["احبك"])
@commands.has_permissions(administrator=True)
async def replay_command(ctx):
    await ctx.send("احبك اكثر ❤️")


@bot.command(name="replayy", aliases=["كل زق"])
@commands.has_permissions(administrator=True)
async def replay_command(ctx):
    await ctx.send("كل زقين")
    
@join_command.error
@play_command.error
@pause_command.error
@resume_command.error
@skip_command.error
@queue_command.error
@leave_command.error
@help_command.error
async def command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("هالأمر بس للأدمن.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("ناقصك شي بالأمر.")
    else:
        await ctx.send(f"صار خطأ: `{error}`")



bot.run(TOKEN)



