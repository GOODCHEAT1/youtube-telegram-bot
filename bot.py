import os
import datetime
import yt_dlp
import threading
import json

from flask import Flask, request
from pymongo import MongoClient
from telebot import TeleBot, types
from googleapiclient.discovery import build

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@BOT_PROMOTION0")
START_PHOTO = "https://envs.sh/hA0.jpg"

bot = TeleBot(BOT_TOKEN, parse_mode="HTML")

# ===== MongoDB =====
client = MongoClient(MONGO_URI)
db = client["youtube_bot_db"]
downloads_collection = db["downloads"]

# ===== YouTube API =====
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

# ===== Ensure downloads folder =====
os.makedirs("downloads", exist_ok=True)

# ===== DOWNLOAD FUNCTION =====
def download_media(url, media_type="audio"):
    outdir = "downloads"
    ydl_opts = {
        "format": "bestaudio/best" if media_type == "audio" else "best[ext=mp4]/best",
        "outtmpl": f"{outdir}/%(id)s.%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "retries": 2,
        "concurrent_fragment_downloads": 5,  # 🚀 Fast download
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

        # ✅ Save in MongoDB
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
    request = youtube.search().list(q=query, part="snippet", type="video", maxResults=max_results)
    response = request.execute()
    results = []
    for item in response.get("items", []):
        video_id = item["id"]["videoId"]
        title = item["snippet"]["title"]
        results.append((title, f"https://www.youtube.com/watch?v={video_id}", video_id))
    return results

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

# ===== COMMANDS =====
@bot.message_handler(commands=["start"])
def start_handler(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Join Channel 🔔", url=f"https://t.me/{CHANNEL_ID.strip('@')}"))
    bot.send_photo(
        message.chat.id,
        START_PHOTO,
        caption="👋 Welcome to <b>YouTube Downloader Bot</b>\n\n"
                "🎵 Download songs & 🎬 videos instantly.\n"
                "🔒 Join our channel to use the bot.",
        reply_markup=markup
    )

@bot.message_handler(commands=["song"])
def song_handler(message):
    if not is_member(message.from_user.id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Join Channel 🔔", url=f"https://t.me/{CHANNEL_ID.strip('@')}"))
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
            try:
                filepath, info = download_media(url, "audio")
                send_file(message.chat.id, filepath, "audio", title)
            except Exception as e:
                bot.send_message(message.chat.id, f"❌ Download error: {e}")
        threading.Thread(target=process, daemon=True).start()

@bot.message_handler(commands=["video"])
def video_handler(message):
    if not is_member(message.from_user.id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Join Channel 🔔", url=f"https://t.me/{CHANNEL_ID.strip('@')}"))
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
            try:
                filepath, info = download_media(url, "video")
                send_file(message.chat.id, filepath, "video", title)
            except Exception as e:
                bot.send_message(message.chat.id, f"❌ Download error: {e}")
        threading.Thread(target=process, daemon=True).start()

# ===== FLASK SERVER (Webhook Mode) =====
server = Flask(__name__)

@server.route(f"/{BOT_TOKEN}", methods=["POST"])
def process_webhook():
    update = request.get_json(force=True)   # ✅ FIXED
    if update:
        bot.process_new_updates([types.Update.de_json(update)])
    return "OK", 200

@server.route("/")
def set_webhook():
    bot.remove_webhook()
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{BOT_TOKEN}"
    bot.set_webhook(url=webhook_url)
    return f"Webhook set to {webhook_url}", 200

if __name__ == "__main__":
    server.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
