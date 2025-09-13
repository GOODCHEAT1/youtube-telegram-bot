import os, threading, datetime, yt_dlp, asyncio
from pymongo import MongoClient
from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from googleapiclient.discovery import build
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import InputAudioStream
from pytgcalls.types.input_stream.quality import HighQualityAudio
from pyrogram import Client
from flask import Flask

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@BOT_PROMOTION0")
OWNER_ID = int(os.getenv("OWNER_ID", "7700872337"))
START_PHOTO = "https://envs.sh/hA0.jpg"

# ===== Telegram Bot =====
bot = TeleBot(BOT_TOKEN, parse_mode="HTML")

# ===== Pyrogram + PyTgCalls (VC client) =====
app_client = Client("vc_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
pytgcalls = PyTgCalls(app_client)

# ===== MongoDB =====
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["youtube_bot_db"]
downloads_collection = db["downloads"]

# ===== CLEAR OLD DATA ON STARTUP =====
downloads_collection.delete_many({})
print("🗑 Old MongoDB data cleared. Starting fresh...")

# ===== YouTube API =====
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

# ===== Playlist Queue =====
playlist = {}

# ===== DOWNLOAD FUNCTION =====
def download_media(url, media_type="audio"):
    ydl_opts = {
        "format": "bestaudio/best" if media_type == "audio" else "best[ext=mp4]/best",
        "outtmpl": f"downloads/%(id)s.%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "retries": 5,
    }
    if media_type == "audio":
        ydl_opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)
        if media_type == "audio":
            file_path = file_path.rsplit(".", 1)[0] + ".mp3"

        # Save in MongoDB (no duplicates)
        if not downloads_collection.find_one({"video_id": info["id"], "type": media_type}):
            downloads_collection.insert_one({
                "video_id": info["id"],
                "title": info["title"],
                "description": info.get("description", ""),
                "url": url,
                "type": media_type,
                "file_path": file_path,
                "timestamp": datetime.datetime.now()
            })
    return file_path, info

# ===== YOUTUBE SEARCH =====
def youtube_search(query, max_results=1):
    request = youtube.search().list(q=query, part="snippet", type="video", maxResults=max_results)
    response = request.execute()
    results = []
    for item in response["items"]:
        video_id = item["id"]["videoId"]
        title = item["snippet"]["title"]
        description = item["snippet"]["description"]
        results.append((title, f"https://www.youtube.com/watch?v={video_id}", video_id, description))
    return results

# ===== FORCE JOIN CHECK =====
def is_member(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# ===== SEND FILE =====
def send_file(chat_id, filename, media_type, title):
    try:
        with open(filename, "rb") as f:
            if media_type == "audio":
                bot.send_audio(chat_id, f, title=title)
            else:
                bot.send_video(chat_id, f, caption=title)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}")

# ===== START COMMAND =====
@bot.message_handler(commands=["start"])
def start_handler(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Join Channel 🔔", url=f"https://t.me/{CHANNEL_ID.strip('@')}"))
    bot.send_photo(
        message.chat.id,
        START_PHOTO,
        caption="👋 Welcome to <b>YouTube Downloader + VC Player Bot</b>\n\n"
                "🎵 Download songs, 🎬 videos & play in VC.\n"
                "🎶 Now supports Playlist Queue!\n"
                "🔒 Join our channel to use the bot.",
        reply_markup=markup
    )

# ===== SONG COMMAND =====
@bot.message_handler(commands=["song"])
def song_handler(message):
    if not is_member(message.from_user.id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Join Channel 🔔", url=f"https://t.me/{CHANNEL_ID.strip('@')}"))
        bot.reply_to(message, "🔒 You must join our channel first!", reply_markup=markup)
        return

    query = message.text.replace("/song", "").strip()
    if not query:
        bot.reply_to(message, "❌ Please provide a song name.")
        return

    title, url, video_id, desc = youtube_search(query)[0]
    cached = downloads_collection.find_one({"video_id": video_id, "type": "audio"})

    if cached and os.path.exists(cached["file_path"]):
        bot.reply_to(message, f"🎵 Sending cached song: <b>{title}</b>")
        threading.Thread(target=lambda: send_file(message.chat.id, cached["file_path"], "audio", title)).start()
    else:
        bot.reply_to(message, f"🎵 Downloading <b>{title}</b> ...")
        threading.Thread(target=lambda: send_file(
            message.chat.id, download_media(url, "audio")[0], "audio", title
        )).start()

# ===== VIDEO COMMAND =====
@bot.message_handler(commands=["video"])
def video_handler(message):
    if not is_member(message.from_user.id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Join Channel 🔔", url=f"https://t.me/{CHANNEL_ID.strip('@')}"))
        bot.reply_to(message, "🔒 You must join our channel first!", reply_markup=markup)
        return

    query = message.text.replace("/video", "").strip()
    if not query:
        bot.reply_to(message, "❌ Please provide a video name.")
        return

    title, url, video_id, desc = youtube_search(query)[0]
    cached = downloads_collection.find_one({"video_id": video_id, "type": "video"})

    if cached and os.path.exists(cached["file_path"]):
        bot.reply_to(message, f"🎬 Sending cached video: <b>{title}</b>")
        threading.Thread(target=lambda: send_file(message.chat.id, cached["file_path"], "video", title)).start()
    else:
        bot.reply_to(message, f"🎬 Downloading <b>{title}</b> ...")
        threading.Thread(target=lambda: send_file(
            message.chat.id, download_media(url, "video")[0], "video", title
        )).start()

# ===== PLAYLIST COMMAND =====
@bot.message_handler(commands=["play"])
def play_handler(message):
    query = message.text.replace("/play", "").strip()
    if not query:
        bot.reply_to(message, "❌ Please provide a song name to play in VC.")
        return

    title, url, video_id, desc = youtube_search(query)[0]
    file_path, info = download_media(url, "audio")

    chat_id = message.chat.id
    if chat_id not in playlist:
        playlist[chat_id] = []

    playlist[chat_id].append((file_path, title))
    bot.reply_to(message, f"🎶 Added <b>{title}</b> to playlist.")

    if len(playlist[chat_id]) == 1:
        asyncio.run(play_next(chat_id))

async def play_next(chat_id):
    if chat_id in playlist and playlist[chat_id]:
        file_path, title = playlist[chat_id][0]
        await pytgcalls.join_group_call(
            chat_id,
            InputAudioStream(file_path, HighQualityAudio())
        )
        print(f"▶️ Playing: {title}")

# ===== SKIP COMMAND =====
@bot.message_handler(commands=["skip"])
def skip_handler(message):
    chat_id = message.chat.id
    if chat_id in playlist and len(playlist[chat_id]) > 1:
        playlist[chat_id].pop(0)
        bot.reply_to(message, "⏭ Skipping to next song...")
        asyncio.run(play_next(chat_id))
    else:
        bot.reply_to(message, "❌ No more songs in playlist.")

# ===== STOP COMMAND =====
@bot.message_handler(commands=["stop"])
def stop_handler(message):
    chat_id = message.chat.id
    if chat_id in playlist:
        playlist[chat_id] = []
    asyncio.run(pytgcalls.leave_group_call(chat_id))
    bot.reply_to(message, "⏹ Stopped playing and cleared playlist.")

# ===== FLASK WEB SERVER =====
server = Flask(__name__)

@server.route('/')
def home():
    return "Bot is running on Render!"

# ===== START BOT =====
async def main():
    await app_client.start()
    await pytgcalls.start()
    print("🤖 Bot + VC + Playlist system running with MongoDB caching...")
    threading.Thread(target=lambda: bot.polling(non_stop=True)).start()
    server.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

if __name__ == "__main__":
    asyncio.run(main())
