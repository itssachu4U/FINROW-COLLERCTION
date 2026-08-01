import asyncio
import logging
import os
import sqlite3
import time

from telegram import Update
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut
from telegram.ext import (
    Application,
    ChatJoinRequestHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession
from telethon.tl.types import (
    DocumentAttributeAudio,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
)

# =============================================================================
#  BOT CONFIG
#  ──────────────────────────────────────────────────────────────────────────
#  BOT_SELF_ID → Numeric ID of THIS bot. Prevents self-message relay loops.
#                NEVER add a trailing comma — must be a plain int.
# =============================================================================
BOT_TOKEN   = "8913101325:AAEvcfSfI-hJYKVPPvq-ImIHtX96VVzPqxk"
BOT_SELF_ID = 8913101325

# =============================================================================
#  TELEGRAM API CREDENTIALS  (for Telethon userbot — premium emoji support)
# =============================================================================
TELEGRAM_ACCOUNTS = [
    {
        "api_id":   36250534,
        "api_hash": "342c1a0671b188527b16a1644556dea0",
        "label":    "Main Account",
    },
    # Add more accounts here if needed:
    # {
    #     "api_id":   12345678,
    #     "api_hash": "abcdef1234567890abcdef1234567890",
    #     "label":    "Account 2",
    # },
]

_ACTIVE  = TELEGRAM_ACCOUNTS[0]
API_ID   = _ACTIVE["api_id"]
API_HASH = _ACTIVE["api_hash"]

# =============================================================================
#  ADMIN IDs  — can use all commands (/login /logout /status /users /broadcast)
# =============================================================================
ADMIN_IDS = [
    8749071857,
    7920174721,
]

# =============================================================================
#  SUPERVISOR SOURCE
#  ──────────────────────────────────────────────────────────────────────────
#  SUPERVISOR_CHANNEL_ID → Your source channel OR group ID.
#                          Works with BOTH channels and groups automatically.
#                          NEVER add a trailing comma — must be a plain int.
#
#  Examples:
#    Channel ID : SUPERVISOR_CHANNEL_ID = -1004226507747
#    Group ID   : SUPERVISOR_CHANNEL_ID = -1001234567890
# =============================================================================
SUPERVISOR_CHANNEL_ID = -1004226507747

# =============================================================================
#  TARGET CHANNELS
#  ──────────────────────────────────────────────────────────────────────────
#  Posts from SUPERVISOR are relayed here AND to user DMs.
#  Adding more targets does NOT increase user DM count — users always get 1.
#  Leave empty [] if you only want user DM broadcast and no channel relay.
# =============================================================================
TARGET_CHANNEL_IDS = [
   # -1003192266753,
   # -1003926870297,
   # -1003640308371,
   # -1003959429271,
   # -1002483412243,
   # -1002317625845,
]

# =============================================================================
#  FILE PATHS  — place these files in the same folder as main.py
# =============================================================================
APK_PATH      = ""                   # Leave "" if no APK file
IMAGE_PATH    = "BONUS.jpeg"
WITHDW_PATH   = "WITHDR-PROOF.jpeg"
VOICE_PATH    = "VOICEHACK.ogg"
TUTORIAL_PATH = "VATSAL_TOP-01.mp4"
VIDEO_PATH    = "FINROW-BITTU.mp4"

# =============================================================================
#  DATABASE
# =============================================================================
DB_NAME = "users.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

LOGIN_PHONE    = 1
LOGIN_OTP      = 2
LOGIN_PASSWORD = 3

# =============================================================================
#  DATABASE HELPERS
# =============================================================================
conn   = sqlite3.connect(DB_NAME, check_same_thread=False)
cursor = conn.cursor()

cursor.execute(
    "CREATE TABLE IF NOT EXISTS users "
    "(user_id INTEGER PRIMARY KEY, joined_at TEXT)"
)
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS message_map (
        supervisor_msg_id INTEGER,
        target_chat_id    INTEGER,
        target_msg_id     INTEGER,
        PRIMARY KEY (supervisor_msg_id, target_chat_id)
    )
    """
)
cursor.execute(
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
)
conn.commit()


def add_user(user_id: int):
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, joined_at) VALUES (?, datetime('now'))",
            (user_id,),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"add_user error: {e}")


def get_all_users():
    cursor.execute("SELECT user_id FROM users")
    return [row[0] for row in cursor.fetchall()]


def get_user_count() -> int:
    cursor.execute("SELECT COUNT(*) FROM users")
    return cursor.fetchone()[0]


def user_exists(user_id: int) -> bool:
    cursor.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
    return cursor.fetchone() is not None


def remove_user(user_id: int):
    cursor.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    conn.commit()


def save_msg_mapping(sup_msg_id: int, target_chat_id: int, target_msg_id: int):
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO message_map "
            "(supervisor_msg_id, target_chat_id, target_msg_id) VALUES (?, ?, ?)",
            (sup_msg_id, target_chat_id, target_msg_id),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"save_msg_mapping error: {e}")


def get_msg_mappings(sup_msg_id: int):
    cursor.execute(
        "SELECT target_chat_id, target_msg_id FROM message_map WHERE supervisor_msg_id=?",
        (sup_msg_id,),
    )
    return cursor.fetchall()


def get_setting(key: str):
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cursor.fetchone()
    return row[0] if row else None


def set_setting(key: str, value: str):
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()


# =============================================================================
#  USERBOT  (Telethon — needed for premium emoji + no "Forwarded from")
# =============================================================================
_userbot_client = None


async def get_userbot():
    global _userbot_client

    if _userbot_client and _userbot_client.is_connected():
        return _userbot_client

    session_str = get_setting("telethon_session")
    if not session_str:
        return None

    try:
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            _userbot_client = client
            logger.info("✅ Userbot reconnected from saved session.")
            return _userbot_client
        else:
            logger.warning("Saved session is no longer authorised.")
            return None
    except Exception as e:
        logger.error(f"get_userbot error: {e}")
        return None


# =============================================================================
#  RELAY HELPER
#  ──────────────────────────────────────────────────────────────────────────
#  Downloads media fresh and re-uploads so Telegram never shows
#  "Forwarded from". formatting_entities preserves premium emojis.
#  This posts to TARGET CHANNELS only — user DMs are handled separately.
# =============================================================================
async def relay_as_new_post(userbot, original_msg, target_channel: int):
    text     = original_msg.message or ""
    entities = original_msg.entities or []

    if not original_msg.media:
        return await userbot.send_message(
            entity=target_channel,
            message=text,
            formatting_entities=entities,
            link_preview=False,
        )

    try:
        file_bytes = await userbot.download_media(original_msg, file=bytes)
    except Exception as e:
        logger.error(f"download_media failed: {e}")
        file_bytes = None

    if not file_bytes:
        return await userbot.send_message(
            entity=target_channel,
            message=text,
            formatting_entities=entities,
            link_preview=False,
        )

    voice_note = False
    video_note = False

    if isinstance(original_msg.media, MessageMediaDocument):
        for attr in getattr(original_msg.media.document, "attributes", []):
            if isinstance(attr, DocumentAttributeAudio) and getattr(attr, "voice", False):
                voice_note = True
            if isinstance(attr, DocumentAttributeVideo) and getattr(attr, "round_message", False):
                video_note = True

    return await userbot.send_file(
        entity=target_channel,
        file=file_bytes,
        caption=text,
        formatting_entities=entities,
        voice_note=voice_note,
        video_note=video_note,
    )


# =============================================================================
#  WELCOME PACKAGE  (text + video + APK + image + image + video + voice)
# =============================================================================
async def send_welcome_package(user, context: ContextTypes.DEFAULT_TYPE):
    add_user(user.id)

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=(
                f"👋🏻 𝐖𝐄𝐋𝐂𝐎𝐌𝐄 {user.mention_html()} 𝐁𝐑𝐎𝐓𝐇𝐄𝐑 "
                "𝐓𝐎 𝗢𝗨𝗥 - 𝐓𝐄𝐀𝐌 𝐃𝐎𝐌𝐈𝐍𝐀𝐓𝐎𝐑𝐒 𝐅𝐀𝐌𝐈𝐋𝐘 🤑"
            ),
            parse_mode="HTML",
        )
    except Exception:
        return

    # ---------- VIDEO 1 (FINROW-BITTU.mp4) ----------
    if os.path.exists(VIDEO_PATH):
        try:
            with open(VIDEO_PATH, "rb") as f:
                await context.bot.send_video(
                    chat_id=user.id,
                    video=f,
                    caption=(
                        "💰ये छोटे बच्चे भी दिन के ₹4000 - ₹5000 कमा रहे हैं 💰\n"
                        "💰आप इस तरह भी कमा सकते हैं 💰💰,"
                    ),
                )
        except Exception as e:
            logger.error(f"Video 1 send error: {e}")

    # ---------- APK ----------
    if APK_PATH and os.path.exists(APK_PATH):
        try:
            with open(APK_PATH, "rb") as f:
                await context.bot.send_document(
                    chat_id=user.id,
                    document=f,
                    caption=(
                        "📂 ☆𝟏𝟎𝟎% 𝐍𝐔𝐌𝐁𝐄𝐑 𝐇𝐀𝐂𝐊💸\n\n"
                        "(केवल प्रीमियम उपयोगकर्ताओं के लिए)💎\n"
                        "(𝟏𝟎𝟎% नुकसान की भरपाई की गारंटी)🧬\n\n"
                        "♻सहायता के लिए @WADRELL\n"
                        "🔴हैक का उपयोग कैसे करें\n"
                        "https://t.me/+dZWWREbeEkk4NmNl"
                    ),
                )
        except Exception as e:
            logger.error(f"APK send error: {e}")

    # ---------- IMAGE 1 (BONUS.jpeg) ----------
    if os.path.exists(IMAGE_PATH):
        try:
            with open(IMAGE_PATH, "rb") as f:
                await context.bot.send_photo(
                    chat_id=user.id,
                    photo=f,
                    caption=(
                        "💰रजिस्टर किजिए लाइफ बदल देनी वाली प्लेटफॉर्म लिंक से, "
                        "आईएसआई प्लेटफॉर्म से आप भी दिन का 4000-5000 कमा सकते हैं💰\n\n"
                        "https://finoraw.com/register/referral?code=TR94507\n\n"
                        "💰 रजिस्ट्रेशन करने के बाद तुरंत मुफ़्त ₹10,000/-  💰\n"
                        "ग्राहक सहायता ✅💰 @WADRELL"
                    ),
                )
        except Exception as e:
            logger.error(f"Image 1 send error: {e}")

    # ---------- IMAGE 2 (WITHDR-PROOF.jpeg) ----------
    if os.path.exists(WITHDW_PATH):
        try:
            with open(WITHDW_PATH, "rb") as f:
                await context.bot.send_photo(
                    chat_id=user.id,
                    photo=f,
                    caption=(
                        "💰रजिस्टर किजिए लाइफ बदल देनी वाली प्लेटफॉर्म लिंक से, "
                        "💰PROFIT WITHDRAWAL PROOF💰\n"
                        "💰लोगो ने अपनी जिंदगी बदली है आप भी बदल सकते हैं इतने सारे "
                        "विदड्रॉल वो वी आईएसआई चैनल के प्रेडिक्शन से 💵\n\n"
                        "💰 रजिस्ट्रेशन करने के बाद तुरंत मुफ़्त ₹10,000/-  💰\n"
                        "ग्राहक सहायता ✅💰 @WADRELL"
                    ),
                )
        except Exception as e:
            logger.error(f"Image 2 send error: {e}")

    # ---------- VIDEO 2 (VATSAL_TOP-01.mp4 — tutorial) ----------
    if os.path.exists(TUTORIAL_PATH):
        try:
            with open(TUTORIAL_PATH, "rb") as f:
                await context.bot.send_video(
                    chat_id=user.id,
                    video=f,
                    caption=(
                        "𝗥𝗘𝗚𝗜𝗦𝗧𝗥𝗔𝗧𝗜𝗢𝗡 𝗟𝗜𝗡𝗞🎗️\n"
                        "https://finoraw.com/register/referral?code=TR94507\n\n"
                        "💰 रजिस्ट्रेशन करने के बाद तुरंत मुफ़्त ₹10,000/-  💰\n"
                        "ग्राहक सहायता ✅💰 @WADRELL,"
                    ),
                )
        except Exception as e:
            logger.error(f"Video 2 send error: {e}")

    # ---------- VOICE (VOICEHACK.ogg) ----------
    if os.path.exists(VOICE_PATH):
        try:
            with open(VOICE_PATH, "rb") as f:
                await context.bot.send_voice(
                    chat_id=user.id,
                    voice=f,
                    caption=(
                        "🎙 सदस्य 9X गुना लाभ का प्रमाण 👇🏻\n"
                        "https://t.me/+dZWWREbeEkk4NmNl\n\n"
                        "♻सहायता के लिए @WADRELL\n"
                        "जीवन बदलने वाला ऑडियो ❤️🤑♻👑"
                    ),
                )
        except Exception as e:
            logger.error(f"Voice send error: {e}")


# =============================================================================
#  /start
# =============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_welcome_package(update.effective_user, context)


# =============================================================================
#  JOIN REQUEST  — auto welcome when user requests to join a linked channel
# =============================================================================
async def approve_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request
    if request:
        await send_welcome_package(request.from_user, context)


# =============================================================================
#  /users
# =============================================================================
async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Only admins can use this command.")
        return

    total = get_user_count()

    try:
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE joined_at >= datetime('now', '-7 days')"
        )
        recent = cursor.fetchone()[0]
    except Exception:
        recent = "N/A"

    try:
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE joined_at >= datetime('now', '-1 day')"
        )
        today = cursor.fetchone()[0]
    except Exception:
        today = "N/A"

    userbot = await get_userbot()
    userbot_status = "🟢 Active" if userbot else "🔴 Not logged in"

    await update.message.reply_text(
        "👥 <b>USER DATABASE REPORT</b>\n\n"
        f"📊 <b>Total Users:</b> <code>{total}</code>\n"
        f"📅 <b>Joined Today:</b> <code>{today}</code>\n"
        f"📆 <b>Last 7 Days:</b> <code>{recent}</code>\n\n"
        f"🤖 <b>Userbot Status:</b> {userbot_status}\n"
        f"📡 <b>Target Channels:</b> <code>{len(TARGET_CHANNEL_IDS)}</code>\n"
        f"🤖 <b>Bot ID:</b> <code>{BOT_SELF_ID}</code>\n"
        f"🔑 <b>Active API Account:</b> {_ACTIVE['label']}\n"
        f"📋 <b>Total API Accounts:</b> <code>{len(TELEGRAM_ACCOUNTS)}</code>",
        parse_mode="HTML",
    )


# =============================================================================
#  /login CONVERSATION  (admin only)
# =============================================================================
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Only admins can use this command.")
        return ConversationHandler.END

    userbot = await get_userbot()
    if userbot:
        me = await userbot.get_me()
        await update.message.reply_text(
            f"✅ <b>Userbot already active!</b>\n\n"
            f"👤 Logged in as: <b>{me.first_name}</b> (@{me.username})\n"
            f"📱 ID: <code>{me.id}</code>\n\n"
            f"✨ Premium emoji posting is ON 🎉\n\n"
            f"Use /logout to log out.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "📱 <b>Userbot Login — Step 1</b>\n\n"
        "अपना मोबाइल नंबर भेजो (country code के साथ):\n\n"
        "<code>+919876543210</code>\n\n"
        "⚡ OTP आपके Telegram app पर आएगा.\n\n"
        "/cancel — रोकने के लिए",
        parse_mode="HTML",
    )
    return LOGIN_PHONE


async def login_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    context.user_data["login_phone"] = phone
    await update.message.reply_text("⏳ OTP भेज रहे हैं...")

    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        result = await client.send_code_request(phone)
        context.user_data["login_client"]    = client
        context.user_data["login_code_hash"] = result.phone_code_hash

        await update.message.reply_text(
            "📲 <b>OTP भेज दिया!</b>\n\n"
            "✅ अपना Telegram app open करो\n"
            "✅ वहाँ आया हुआ OTP यहाँ भेजो\n\n"
            "Format: <code>12345</code> या <code>1 2 3 4 5</code>\n\n"
            "/cancel — रोकने के लिए",
            parse_mode="HTML",
        )
        return LOGIN_OTP

    except FloodWaitError as e:
        await update.message.reply_text(
            f"⏳ Telegram ने wait करने को कहा.\n"
            f"{e.seconds} seconds बाद /login से try करो."
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"send_code_request error: {e}")
        await update.message.reply_text(
            f"❌ OTP नहीं भेजा जा सका.\nError: {e}\n\n"
            f"Phone number check करो और /login से दोबारा try करो."
        )
        return ConversationHandler.END


async def login_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    otp       = update.message.text.strip().replace(" ", "")
    phone     = context.user_data.get("login_phone")
    client    = context.user_data.get("login_client")
    code_hash = context.user_data.get("login_code_hash")

    if not client or not phone or not code_hash:
        await update.message.reply_text("❌ Session expire हो गया. /login से try करो.")
        return ConversationHandler.END

    try:
        await client.sign_in(phone, otp, phone_code_hash=code_hash)
        session_str = client.session.save()
        set_setting("telethon_session", session_str)

        global _userbot_client
        _userbot_client = client

        me = await client.get_me()
        await update.message.reply_text(
            f"✅ <b>Login हो गया!</b>\n\n"
            f"👤 Name: <b>{me.first_name}</b>\n"
            f"📱 Phone: <code>{phone}</code>\n"
            f"🆔 ID: <code>{me.id}</code>\n\n"
            f"🎉 <b>Premium emoji posting ACTIVE है!</b>\n"
            f"Supervisor → Target channels: NEW post (no 'Forwarded from') ✅\n"
            f"Users DM: 1 copy only (no duplicates) ✅",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    except PhoneCodeInvalidError:
        await update.message.reply_text(
            "❌ OTP गलत है!\n\nSahi OTP भेजो (Telegram app check करो):"
        )
        return LOGIN_OTP

    except PhoneCodeExpiredError:
        await update.message.reply_text(
            "❌ OTP expire हो गया.\n\n/login से दोबारा try करो."
        )
        return ConversationHandler.END

    except SessionPasswordNeededError:
        await update.message.reply_text(
            "🔒 <b>2-Step Verification चालू है.</b>\n\n"
            "अपना Telegram password भेजो:",
            parse_mode="HTML",
        )
        return LOGIN_PASSWORD

    except Exception as e:
        logger.error(f"sign_in error: {e}")
        await update.message.reply_text(
            f"❌ Login failed.\nError: {e}\n\n/login से दोबारा try करो."
        )
        return ConversationHandler.END


async def login_2fa_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    client   = context.user_data.get("login_client")

    if not client:
        await update.message.reply_text("❌ Session expire हो गया. /login से try करो.")
        return ConversationHandler.END

    try:
        await client.sign_in(password=password)
        session_str = client.session.save()
        set_setting("telethon_session", session_str)

        global _userbot_client
        _userbot_client = client

        me = await client.get_me()
        await update.message.reply_text(
            f"✅ <b>Login हो गया! (2FA)</b>\n\n"
            f"👤 Name: <b>{me.first_name}</b>\n"
            f"🆔 ID: <code>{me.id}</code>\n\n"
            f"🎉 Premium emoji posting ACTIVE है!",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"2FA error: {e}")
        await update.message.reply_text(
            f"❌ Password गलत है.\nError: {e}\n\n/login से दोबारा try करो."
        )
        return ConversationHandler.END


async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = context.user_data.get("login_client")
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
    await update.message.reply_text("🚫 Login cancel किया गया.")
    return ConversationHandler.END


# =============================================================================
#  /logout
# =============================================================================
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Only admins can use this command.")
        return

    global _userbot_client
    if _userbot_client:
        try:
            await _userbot_client.log_out()
        except Exception:
            pass
        _userbot_client = None

    cursor.execute("DELETE FROM settings WHERE key='telethon_session'")
    conn.commit()

    await update.message.reply_text(
        "🔓 <b>Userbot Logout हो गया.</b>\n\n"
        "Session delete कर दिया गया.\n\n"
        "⚠️ अब posts Bot API copy mode में जाएंगी (premium emojis नहीं होंगे).\n"
        "Premium emoji posting के लिए /login करो.",
        parse_mode="HTML",
    )


# =============================================================================
#  /status
# =============================================================================
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Only admins can use this command.")
        return

    userbot     = await get_userbot()
    total_users = get_user_count()

    if userbot:
        try:
            me = await userbot.get_me()
            ubot_text = (
                f"🟢 <b>ACTIVE</b>\n"
                f"   👤 {me.first_name} (@{me.username})\n"
                f"   🆔 <code>{me.id}</code>"
            )
        except Exception:
            ubot_text = "🟡 Session exists (could not fetch user info)"
    else:
        ubot_text = "🔴 <b>NOT ACTIVE</b> — run /login"

    accounts_text = "\n".join(
        f"   {'✅' if i == 0 else '  '} {acc['label']} (ID: {acc['api_id']})"
        for i, acc in enumerate(TELEGRAM_ACCOUNTS)
    )

    await update.message.reply_text(
        "📊 <b>BOT STATUS</b>\n\n"
        f"🤖 <b>Bot ID:</b> <code>{BOT_SELF_ID}</code>\n\n"
        f"👤 <b>Userbot:</b>\n{ubot_text}\n\n"
        f"👥 <b>Total Users in DB:</b> <code>{total_users}</code>\n"
        f"📡 <b>Supervisor ID:</b> <code>{SUPERVISOR_CHANNEL_ID}</code>\n"
        f"📡 <b>Target Channels:</b> <code>{len(TARGET_CHANNEL_IDS)}</code>\n\n"
        f"🔑 <b>API Accounts ({len(TELEGRAM_ACCOUNTS)}):</b>\n{accounts_text}",
        parse_mode="HTML",
    )


# =============================================================================
#  SUPERVISOR RELAY
#  ──────────────────────────────────────────────────────────────────────────
#  Supports BOTH channels and groups as supervisor source.
#
#  HOW IT WORKS:
#    • Channel post  → arrives as update.channel_post
#    • Group message → arrives as update.message
#    Both handled by the SAME function — just set SUPERVISOR_CHANNEL_ID.
#
#  FLOW:
#    1. Message arrives from SUPERVISOR only (all others are ignored).
#    2. Userbot relays it to each TARGET channel (no "Forwarded from").
#    3. All users in DB receive exactly ONE copy — never more.
#
#  GUARANTEES:
#    ✅ Users always get 1 message regardless of how many target channels.
#    ✅ Bot never reacts to its own messages (BOT_SELF_ID check).
#    ✅ Admin commands in supervisor group are not relayed.
# =============================================================================
async def handle_supervisor_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    # Works for both channel posts and group messages
    post = update.channel_post or update.message
    if not post:
        return

    chat_id = post.chat.id

    # Only act on the supervisor source — ignore everything else
    if chat_id != SUPERVISOR_CHANNEL_ID:
        return

    # Skip self-messages (prevents relay loop)
    if post.from_user and post.from_user.id == BOT_SELF_ID:
        return

    # Skip bot messages
    if post.from_user and post.from_user.is_bot:
        return

    # Skip admin commands typed in the supervisor group (e.g. /status, /users)
    if post.text and post.text.startswith("/"):
        return

    userbot = await get_userbot()

    # Fetch original Telethon message (carries premium emoji entity metadata)
    original_msg = None
    if userbot:
        try:
            original_msg = await userbot.get_messages(
                SUPERVISOR_CHANNEL_ID, ids=post.message_id
            )
        except Exception as e:
            logger.error(f"get_messages failed: {e}")

    # ── Step 1: Relay to each target channel ─────────────────────────────────
    for target_channel in TARGET_CHANNEL_IDS:
        try:
            if userbot and original_msg:
                # Fresh download + re-upload = NO "Forwarded from" ✅
                # formatting_entities = premium emojis preserved ✅
                sent = await relay_as_new_post(userbot, original_msg, target_channel)
                if sent:
                    save_msg_mapping(post.message_id, target_channel, sent.id)
            else:
                # Fallback when no userbot session: Bot API copy
                # copyMessage does NOT add "Forwarded from" header ✅
                copied = await post.copy(chat_id=target_channel)
                save_msg_mapping(post.message_id, target_channel, copied.message_id)

            await asyncio.sleep(0.05)

        except Exception as e:
            logger.error(f"Relay error → {target_channel}: {e}")

    # ── Step 2: Broadcast to user DMs — EXACTLY ONCE ─────────────────────────
    # This runs only for the supervisor post.
    # Target channel posts are completely ignored (no cascading).
    # Users always receive 1 copy no matter how many target channels exist.
    users = get_all_users()
    for user_id in users:
        try:
            await post.copy(chat_id=user_id)
        except Exception:
            pass
        await asyncio.sleep(0.04)


# =============================================================================
#  EDITED MESSAGE SYNC
#  ──────────────────────────────────────────────────────────────────────────
#  When you edit a message in the supervisor channel or group, the edit is
#  synced to all target channels automatically.
#  Works for both channel edits and group edits.
# =============================================================================
async def handle_edited_supervisor_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    # Works for both edited channel posts and edited group messages
    edited = update.edited_channel_post or update.edited_message
    if not edited or edited.chat.id != SUPERVISOR_CHANNEL_ID:
        return

    mappings = get_msg_mappings(edited.message_id)
    for target_chat_id, target_msg_id in mappings:
        try:
            if edited.text:
                await context.bot.edit_message_text(
                    chat_id=target_chat_id,
                    message_id=target_msg_id,
                    text=edited.text,
                    parse_mode=edited.parse_mode,
                )
            elif edited.caption:
                await context.bot.edit_message_caption(
                    chat_id=target_chat_id,
                    message_id=target_msg_id,
                    caption=edited.caption,
                    parse_mode=edited.parse_mode,
                )
        except Exception as e:
            logger.error(f"Edit sync failed for {target_chat_id}: {e}")


# =============================================================================
#  /resend — re-send full welcome package to ALL existing users in DB
# =============================================================================
async def resend_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Only admins can use this command.")
        return

    users = get_all_users()
    total = len(users)

    if total == 0:
        await update.message.reply_text("⚠️ Database में कोई user नहीं है.")
        return

    status_msg = await update.message.reply_text(
        f"📤 <b>Resend शुरू हो रहा है...</b>\n\n"
        f"👥 Total users: <code>{total}</code>\n"
        f"⏳ थोड़ा time लेगा...",
        parse_mode="HTML",
    )

    delivered = 0
    failed    = 0
    start_t   = time.time()

    for i, user_id in enumerate(users, 1):
        try:
            if os.path.exists(VIDEO_PATH):
                with open(VIDEO_PATH, "rb") as f:
                    await context.bot.send_video(
                        chat_id=user_id, video=f,
                        caption=(
                            "💰ये छोटे बच्चे भी दिन के ₹4000 - ₹5000 कमा रहे हैं 💰\n"
                            "💰आप इस तरह भी कमा सकते हैं 💰💰,"
                        ),
                    )
                await asyncio.sleep(0.3)

            if APK_PATH and os.path.exists(APK_PATH):
                with open(APK_PATH, "rb") as f:
                    await context.bot.send_document(
                        chat_id=user_id, document=f,
                        caption=(
                            "📂 ☆𝟏𝟎𝟎% 𝐍𝐔𝐌𝐁𝐄𝐑 𝐇𝐀𝐂𝐊💸\n\n"
                            "(केवल प्रीमियम उपयोगकर्ताओं के लिए)💎\n"
                            "(𝟏𝟎𝟎% नुकसान की भरपाई की गारंटी)🧬\n\n"
                            "♻सहायता के लिए @WADRELL\n"
                            "🔴हैक का उपयोग कैसे करें\n"
                            "https://t.me/+dZWWREbeEkk4NmNl"
                        ),
                    )
                await asyncio.sleep(0.3)

            if os.path.exists(IMAGE_PATH):
                with open(IMAGE_PATH, "rb") as f:
                    await context.bot.send_photo(
                        chat_id=user_id, photo=f,
                        caption=(
                            "💰रजिस्टर किजिए लाइफ बदल देनी वाली प्लेटफॉर्म लिंक से💰\n\n"
                            "https://finoraw.com/register/referral?code=TR94507\n\n"
                            "💰 रजिस्ट्रेशन करने के बाद तुरंत मुफ़्त ₹10,000/-  💰\n"
                            "ग्राहक सहायता ✅💰 @WADRELL"
                        ),
                    )
                await asyncio.sleep(0.3)

            if os.path.exists(WITHDW_PATH):
                with open(WITHDW_PATH, "rb") as f:
                    await context.bot.send_photo(
                        chat_id=user_id, photo=f,
                        caption=(
                            "💰PROFIT WITHDRAWAL PROOF💰\n\n"
                            "💰 रजिस्ट्रेशन करने के बाद तुरंत मुफ़्त ₹10,000/-  💰\n"
                            "ग्राहक सहायता ✅💰 @WADRELL"
                        ),
                    )
                await asyncio.sleep(0.3)

            if os.path.exists(TUTORIAL_PATH):
                with open(TUTORIAL_PATH, "rb") as f:
                    await context.bot.send_video(
                        chat_id=user_id, video=f,
                        caption=(
                            "𝗥𝗘𝗚𝗜𝗦𝗧𝗥𝗔𝗧𝗜𝗢𝗡 𝗟𝗜𝗡𝗞🎗️\n"
                            "https://finoraw.com/register/referral?code=TR94507\n\n"
                            "💰 रजिस्ट्रेशन करने के बाद तुरंत मुफ़्त ₹10,000/-  💰\n"
                            "ग्राहक सहायता ✅💰 @WADRELL,"
                        ),
                    )
                await asyncio.sleep(0.3)

            if os.path.exists(VOICE_PATH):
                with open(VOICE_PATH, "rb") as f:
                    await context.bot.send_voice(
                        chat_id=user_id, voice=f,
                        caption=(
                            "🎙 सदस्य 9X गुना लाभ का प्रमाण 👇🏻\n"
                            "https://t.me/+dZWWREbeEkk4NmNl\n\n"
                            "♻सहायता के लिए @WADRELL\n"
                            "जीवन बदलने वाला ऑडियो ❤️🤑♻👑"
                        ),
                    )

            delivered += 1

        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            failed += 1
        except (Forbidden, BadRequest):
            failed += 1
        except Exception as e:
            failed += 1
            logger.error(f"Resend failed for {user_id}: {e}")

        if i % 50 == 0:
            try:
                await status_msg.edit_text(
                    f"📤 <b>Resend चल रहा है...</b>\n\n"
                    f"🔄 Progress: <code>{i}/{total}</code>\n"
                    f"✅ Delivered: <code>{delivered}</code>\n"
                    f"❌ Failed: <code>{failed}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        await asyncio.sleep(0.05)

    elapsed = round(time.time() - start_t, 2)
    report = (
        "✅ <b><u>RESEND COMPLETE</u></b>\n\n"
        f"👥 <b>Total Users:</b> <code>{total}</code>\n"
        f"📬 <b>Delivered:</b> <code>{delivered}</code>\n"
        f"❌ <b>Failed / Blocked:</b> <code>{failed}</code>\n"
        f"🛡 <b>Database:</b> सभी users safe हैं\n"
        f"⏱ <b>Time:</b> {elapsed} seconds\n\n"
        "🎉 <i>सभी old users को files मिल गई!</i>"
    )
    try:
        await status_msg.edit_text(report, parse_mode="HTML")
    except Exception:
        await update.message.reply_text(report, parse_mode="HTML")


# =============================================================================
#  /broadcast — admin replies to any message and sends it to all users
# =============================================================================
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "⚠️ किसी message / media को reply करके /broadcast भेजो."
        )
        return

    status_msg = await update.message.reply_text("⏳ Broadcast चल रहा है...")

    users       = get_all_users()
    total_users = len(users)
    delivered   = 0
    failed      = 0
    start_time  = time.time()

    for user_id in users:
        success = False
        while not success:
            try:
                await update.message.reply_to_message.copy(chat_id=user_id)
                delivered += 1
                success = True
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except (Forbidden, BadRequest) as e:
                failed += 1
                logger.warning(f"Delivery failed for {user_id}: {e}")
                success = True
            except (TimedOut, NetworkError):
                await asyncio.sleep(2)
                try:
                    await update.message.reply_to_message.copy(chat_id=user_id)
                    delivered += 1
                except Exception:
                    failed += 1
                success = True
            except Exception as e:
                failed += 1
                logger.error(f"Broadcast failure for {user_id}: {e}")
                success = True
        await asyncio.sleep(0.04)

    elapsed = round(time.time() - start_time, 2)
    report = (
        "📊 <b><u>BROADCAST ANNOUNCEMENT REPORT</u></b>\n\n"
        f"👥 <b>Total Target Users:</b> {total_users}\n"
        f"✅ <b>Successfully Delivered:</b> {delivered}\n"
        f"❌ <b>Failed / Blocked:</b> {failed}\n"
        f"🛡 <b>Database Deletions:</b> 0 (All users preserved permanently)\n"
        f"⏱ <b>Execution Time:</b> {elapsed} seconds\n\n"
        "🎉 <i>Broadcast completed!</i>"
    )
    try:
        await status_msg.edit_text(report, parse_mode="HTML")
    except Exception:
        await update.message.reply_text(report, parse_mode="HTML")


# =============================================================================
#  USER MESSAGE CAPTURE
#  ──────────────────────────────────────────────────────────────────────────
#  When a user DMs the bot, admin gets a notification + copy of the message.
#  BOT_SELF_ID check prevents the bot from reacting to its own messages.
# =============================================================================
async def capture_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    message = update.message

    if not user or not message:
        return

    # Skip bots and self
    if message.from_user and message.from_user.is_bot:
        return
    if user.id == BOT_SELF_ID:
        return

    # Skip admins
    if user.id in ADMIN_IDS:
        return

    is_new = not user_exists(user.id)
    if is_new:
        add_user(user.id)

    username_str        = f"@{user.username}" if user.username else "N/A"
    direct_contact_link = f"tg://openmessage?user_id={user.id}"
    status_label = (
        "🚨 <b>NEW USER DETECTED</b> 🚨" if is_new
        else "📩 <b>USER MEDIA/MESSAGE RECEIVED</b>"
    )

    notification = (
        f"{status_label}\n\n"
        f"👤 <b>TELEGRAM ID:</b> <code>{user.id}</code>\n"
        f"🏷 <b>TELEGRAM USER NAME:</b> {username_str}\n"
        f"🔗 <b>DIRECT LINK:</b> "
        f"<a href='{direct_contact_link}'>Click to Chat directly with User</a>"
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=notification,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            await message.copy(chat_id=admin_id)
        except Exception as e:
            logger.error(f"Admin notification failed for {admin_id}: {e}")


# =============================================================================
#  STARTUP
# =============================================================================
async def on_startup(app: Application):
    userbot = await get_userbot()
    if userbot:
        try:
            me = await userbot.get_me()
            logger.info(f"✅ Userbot auto-connected: {me.first_name} (@{me.username})")
        except Exception as e:
            logger.warning(f"Userbot startup reconnect failed: {e}")
    else:
        logger.info("ℹ️ No userbot session found. Admin can run /login to activate.")


# =============================================================================
#  MAIN
# =============================================================================
def main():
    app = Application.builder().token(BOT_TOKEN).post_init(on_startup).build()

    # ── /login conversation ───────────────────────────────────────────────────
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            LOGIN_PHONE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, login_phone)],
            LOGIN_OTP:      [MessageHandler(filters.TEXT & ~filters.COMMAND, login_otp)],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_2fa_password)],
        },
        fallbacks=[CommandHandler("cancel", login_cancel)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(login_conv)
    app.add_handler(CommandHandler("logout",    logout))
    app.add_handler(CommandHandler("status",    status_cmd))
    app.add_handler(CommandHandler("users",     users_cmd))
    app.add_handler(CommandHandler("resend",    resend_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(ChatJoinRequestHandler(approve_and_send))

    # ── Supervisor: CHANNEL new posts ─────────────────────────────────────────
    app.add_handler(
        MessageHandler(
            filters.ChatType.CHANNEL & ~filters.UpdateType.EDITED_CHANNEL_POST,
            handle_supervisor_message,
        )
    )

    # ── Supervisor: GROUP / SUPERGROUP new messages ───────────────────────────
    # This handles the case where SUPERVISOR_CHANNEL_ID is a group, not a channel.
    # Bot must be added as a member (or admin) of the supervisor group.
    app.add_handler(
        MessageHandler(
            (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP)
            & ~filters.UpdateType.EDITED_MESSAGE
            & ~filters.COMMAND,
            handle_supervisor_message,
        )
    )

    # ── Supervisor: CHANNEL edited posts (sync edits to targets) ─────────────
    app.add_handler(
        MessageHandler(
            filters.ChatType.CHANNEL & filters.UpdateType.EDITED_CHANNEL_POST,
            handle_edited_supervisor_message,
        )
    )

    # ── Supervisor: GROUP / SUPERGROUP edited messages (sync edits) ───────────
    app.add_handler(
        MessageHandler(
            (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP)
            & filters.UpdateType.EDITED_MESSAGE,
            handle_edited_supervisor_message,
        )
    )

    # ── Private DM messages from users → notify admin ─────────────────────────
    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND & filters.ChatType.PRIVATE,
            capture_user_message,
        )
    )

    logger.info("🚀 Bot started. Supervisor supports CHANNEL and GROUP.")
    app.run_polling()


if __name__ == "__main__":
    main()
