
import os
import threading
import datetime
import yt_dlp

from pymongo import MongoClient
from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from googleapiclient.discovery import build
from flask import Flask

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@BOT_PROMOTION0")
START_PHOTO = "https://envs.sh/hA0.jpg"

# ===== Ensure downloads folder =====
os.makedirs("downloads", exist_ok=True)

# ===== Telegram Bot =====
bot = TeleBot(BOT_TOKEN, parse_mode="HTML")

# ===== MongoDB =====
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["youtube_bot_db"]
downloads_collection = db["downloads"]

print("✅ Startup: downloads folder ready. MongoDB intact.")

# ===== YouTube API =====
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

# ===== OPTIMIZED DOWNLOAD FUNCTION =====
def download_media(url, media_type="audio"):
    outdir = "downloads"
    os.makedirs(outdir, exist_ok=True)

    # ⚡ Speed optimized options
    ydl_opts = {
        "format": "bestaudio/best" if media_type == "audio" else "best[ext=mp4]/best",
        "outtmpl": f"{outdir}/%(id)s.%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "retries": 3,
        "extract_flat": False,
    }

    if media_type == "audio":
        ydl_opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if media_type == "audio":
            filename = filename.rsplit(".", 1)[0] + ".mp3"

        # ✅ Save in MongoDB if not cached
        if not downloads_collection.find_one({"video_id": info.get("id"), "type": media_type}):
            downloads_collection.insert_one({
                "video_id": info.get("id"),
                "title": info.get("title"),
                "url": url,
                "type": media_type,
                "file_path": filename,
                "timestamp": datetime.datetime.utcnow()
            })

    return filename, info

# ===== YOUTUBE SEARCH =====
def youtube_search(query, max_results=1):
    try:
        request = youtube.search().list(q=query, part="snippet", type="video", maxResults=max_results)
        response = request.execute()
        results = []
        for item in response.get("items", []):
            video_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            results.append((title, f"https://www.youtube.com/watch?v={video_id}", video_id))
        return results
    except Exception as e:
        print("YouTube search error:", e)
        return []

# ===== FORCE JOIN CHECK =====
def is_member(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
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
        bot.send_message(chat_id, f"❌ Error sending file: {e}")

# ===== START COMMAND =====
@bot.message_handler(commands=["start"])
def start_handler(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Join Channel 🔔", url=f"https://t.me/{CHANNEL_ID.strip('@')}"))
    bot.send_photo(
        message.chat.id,
        START_PHOTO,
        caption="👋 Welcome to <b>YouTube Downloader Bot</b>\n\n"
                "🎵 Download songs & 🎬 videos at high speed.\n"
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

    query = message.text.replace("/song", "", 1).strip()
    if not query:
        bot.reply_to(message, "❌ Please provide a song name.")
        return

    results = youtube_search(query)
    if not results:
        bot.reply_to(message, "❌ No results found!")
        return

    title, url, video_id = results[0]
    cached = downloads_collection.find_one({"video_id": video_id, "type": "audio"})

    if cached and os.path.exists(cached.get("file_path", "")):
        bot.reply_to(message, f"🎵 Sending cached song: <b>{title}</b>")
        threading.Thread(target=lambda: send_file(message.chat.id, cached["file_path"], "audio", title), daemon=True).start()
    else:
        bot.reply_to(message, f"🎵 Downloading <b>{title}</b> ...")
        def process():
            filepath, info = download_media(url, "audio")
            send_file(message.chat.id, filepath, "audio", title)
        threading.Thread(target=process, daemon=True).start()

# ===== VIDEO COMMAND =====
@bot.message_handler(commands=["video"])
def video_handler(message):
    if not is_member(message.from_user.id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Join Channel 🔔", url=f"https://t.me/{CHANNEL_ID.strip('@')}"))
        bot.reply_to(message, "🔒 You must join our channel first!", reply_markup=markup)
        return

    query = message.text.replace("/video", "", 1).strip()
    if not query:
        bot.reply_to(message, "❌ Please provide a video name.")
        return

    results = youtube_search(query)
    if not results:
        bot.reply_to(message, "❌ No results found!")
        return

    title, url, video_id = results[0]
    cached = downloads_collection.find_one({"video_id": video_id, "type": "video"})

    if cached and os.path.exists(cached.get("file_path", "")):
        bot.reply_to(message, f"🎬 Sending cached video: <b>{title}</b>")
        threading.Thread(target=lambda: send_file(message.chat.id, cached["file_path"], "video", title), daemon=True).start()
    else:
        bot.reply_to(message, f"🎬 Downloading <b>{title}</b> ...")
        def process():
            filepath, info = download_media(url, "video")
            send_file(message.chat.id, filepath, "video", title)
        threading.Thread(target=process, daemon=True).start()

# ===== FLASK WEB SERVER =====
server = Flask(__name__)

@server.route('/')
def home():
    return "Bot is running on Render!"

# ===== MAIN LOOP =====
if __name__ == "__main__":
    threading.Thread(target=lambda: server.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000))), daemon=True).start()
    bot.polling(non_stop=True)
