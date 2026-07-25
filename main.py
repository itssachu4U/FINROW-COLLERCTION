import os
import logging
import sqlite3
import asyncio

from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    ChatJoinRequestHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram.error import Forbidden, BadRequest, TimedOut, NetworkError

# ================= CONFIG =================
BOT_TOKEN = "8913101325:AAEvcfSfI-hJYKVPPvq-ImIHtX96VVzPqxk"
ADMIN_ID = 7849592882
APK_PATH = "BONUS.jpeg"
IMAGE_PATH = "BONUS.jpeg"
VOICE_PATH = "VOICEHACK.ogg"
VIDEO_PATH = "FINROW-BITTU.mp4"
DB_NAME = "users.db"
# ==========================================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# ================= DATABASE =================
conn = sqlite3.connect(DB_NAME, check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
conn.commit()


def add_user(user_id: int):
    try:
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
    except Exception as e:
        logging.error(f"Add user error: {e}")


def get_all_users():
    cursor.execute("SELECT user_id FROM users")
    return [row[0] for row in cursor.fetchall()]


def remove_user(user_id: int):
    cursor.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    conn.commit()


def user_exists(user_id: int):
    cursor.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
    return cursor.fetchone() is not None


# ================= COMMON SEND =================
async def send_welcome_package(user, context: ContextTypes.DEFAULT_TYPE):
    add_user(user.id)

    welcome_message = f"""
👋🏻 𝐖𝐄𝐋𝐂𝐎𝐌𝐄 {user.mention_html()} 𝐁𝐑𝐎𝐓𝐇𝐄𝐑 𝐓𝐎 𝗢𝗨𝗥 - 𝐉𝐀𝐈𝐂𝐋𝐔𝐁 𝐏𝐑𝐈𝐕𝐀𝐓𝐄 𝐇𝐀𝐂𝐊 𝐒𝐄𝐑𝐕𝐄𝐑 🤑
"""

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=welcome_message,
            parse_mode="HTML",
        )
    except Exception:
        return

    # ---------- VIDEO ----------
    if os.path.exists(VIDEO_PATH):
        try:
            with open(VIDEO_PATH, "rb") as video:
                await context.bot.send_video(
                    chat_id=user.id,
                    video=video,
                    caption="""💰ये छोटे बच्चे भी दिन के ₹4000 - ₹5000 कमा रहे हैं 💰
💰आप इस तरह भी कमा सकते हैं 💰💰,""",
                )
        except Exception as e:
            logging.error(f"Video send error: {e}")

    # ---------- APK ----------
    if os.path.exists(APK_PATH):
        try:
            with open(APK_PATH, "rb") as apk:
                await context.bot.send_document(
                    chat_id=user.id,
                    document=apk,
                    caption="""📂 ☆𝟏𝟎𝟎% 𝐍𝐔𝐌𝐁𝐄𝐑 𝐇𝐀𝐂𝐊💸

(केवल प्रीमियम उपयोगकर्ताओं के लिए)💎
(𝟏𝟎𝟎% नुकसान की भरपाई की गारंटी)🧬

♻सहायता के लिए @WADRELL
🔴हैक का उपयोग कैसे करें
https://t.me/+dZWWREbeEkk4NmNl""",
                )
        except Exception as e:
            logging.error(f"APK send error: {e}")

    # ---------- IMAGE ----------


if os.path.exists(IMAGE_PATH):
    try:
        with open(IMAGE_PATH, "rb") as photo:
            await context.bot.send_photo(
                chat_id=user.id,
                photo=photo,
                caption="""📚 Study Material

Here is your study material.

🔗 https://t.me/your_channel_link
""",
            )
    except Exception as e:
        logging.error(f"Image send error: {e}")

    # ---------- VOICE ----------
    if os.path.exists(VOICE_PATH):
        try:
            with open(VOICE_PATH, "rb") as voice:
                await context.bot.send_voice(
                    chat_id=user.id,
                    voice=voice,
                    caption="""🎙 सदस्य 9X गुना लाभ का प्रमाण 👇🏻
https://t.me/+dZWWREbeEkk4NmNl

♻सहायता के लिए @WADRELL
जीवन बदलने वाला ऑडियो ❤️🤑♻👑""",
                )
        except Exception as e:
            logging.error(f"Voice send error: {e}")


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_welcome_package(update.effective_user, context)


async def approve_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request
    if request:
        await send_welcome_package(request.from_user, context)


# ================= BROADCAST =================
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to message to broadcast.")
        return

    users = get_all_users()

    delivered = 0
    failed = 0

    for user_id in users:
        try:
            await update.message.reply_to_message.copy(chat_id=user_id)
            delivered += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.03)

    await update.message.reply_text(f"✅ Done\nDelivered: {delivered}\nFailed: {failed}")


# ================= MESSAGE =================
async def capture_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    if not user or not message:
        return

    if message.from_user.is_bot:
        return

    if user.id == ADMIN_ID:
        return

    if not user_exists(user.id):
        add_user(user.id)

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"New User: {user.id}",
            )
        except:
            pass

    try:
        await message.copy(chat_id=user.id)
    except:
        pass


# ================= MAIN =================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(ChatJoinRequestHandler(approve_and_send))
    app.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, capture_user_message)
    )

    app.run_polling()


if __name__ == "__main__":
    main()
