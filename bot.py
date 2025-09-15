import os
from flask import Flask, request
import telebot
from mega import Mega

# ==============================
# CONFIG
# ==============================
TOKEN = os.getenv("BOT_TOKEN")  # Render environment se
bot = telebot.TeleBot(TOKEN)
mega = Mega()
m = mega.login()  # guest login

app = Flask(__name__)

# ==============================
# BOT HANDLERS
# ==============================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "👋 Namaste! Mujhe Mega.nz video link bhejo, main Telegram pe bhej dunga (max 2GB).")

@bot.message_handler(func=lambda msg: msg.text and "mega.nz" in msg.text)
def handle_mega_link(message):
    link = message.text.strip()
    chat_id = message.chat.id
    bot.send_message(chat_id, "⏳ Video download ho raha hai... wait karo...")

    try:
        file_path = m.download_url(link)  # Mega se download
        file_name = os.path.basename(file_path)

        size_mb = os.path.getsize(file_path) / (1024 * 1024)

        # 2GB limit check
        if size_mb > 1990:
            bot.send_message(chat_id, f"⚠️ Video bahut badi hai ({round(size_mb,2)} MB). Telegram limit 2GB hai.")
        elif file_name.lower().endswith((".mp4", ".mkv", ".avi", ".mov")):
            bot.send_video(chat_id, open(file_path, "rb"), caption=f"🎬 {file_name}")
        else:
            bot.send_message(chat_id, "❌ Ye video format supported nahi hai.")

        os.remove(file_path)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {str(e)}")

# ==============================
# WEBHOOK FOR RENDER
# ==============================
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def home():
    return "Bot is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
