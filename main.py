import os
import json
import urllib.request
import urllib.parse
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/"

TOTAL_EPISODES = 39
DB_FILE = "episodes_db.json"
USERS_FILE = "users_db.json"
CONFIG_FILE = "config_db.json"

# Load database helper functions
def load_json(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json(filename, data):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving {filename}: {e}")

# Global DB state
db = load_json(DB_FILE)
users_db = load_json(USERS_FILE)
config_db = load_json(CONFIG_FILE)

# Ensure admin_id is set. If not, the first person to use /admin becomes admin (auto-setup)
ADMIN_ID = os.getenv("ADMIN_ID")
if not ADMIN_ID and "admin_id" in config_db:
    ADMIN_ID = config_db["admin_id"]

def register_user(chat_id, username, first_name):
    """Add a new user to the database if they don't exist."""
    chat_id_str = str(chat_id)
    if chat_id_str not in users_db:
        users_db[chat_id_str] = {
            "username": username or "",
            "first_name": first_name or "",
            "joined_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_json(USERS_FILE, users_db)

def send_api(method, payload=None):
    """Send request to Telegram Bot API."""
    url = API_URL + method
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, headers=headers, method="POST")
    if payload is not None:
        req.data = json.dumps(payload).encode("utf-8")
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        print(f"API Error ({method}): {e}")
        return None

def chunk_list(lst, chunk_size):
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

def make_episodes_keyboard():
    rows = []
    episode_numbers = list(range(1, TOTAL_EPISODES + 1))
    for chunk in chunk_list(episode_numbers, 5):
        button_row = [
            {"text": str(num), "callback_data": f"episode_{num}"}
            for num in chunk
        ]
        rows.append(button_row)
    return {"inline_keyboard": rows}

def make_admin_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Statistika", "callback_data": "admin_stats"},
                {"text": "📋 Yuklanmagan qismlar", "callback_data": "admin_missing"}
            ],
            [
                {"text": "📢 Reklama tarqatish", "callback_data": "admin_broadcast"}
            ],
            [
                {"text": "❌ Panelni yopish", "callback_data": "admin_close"}
            ]
        ]
    }

def handle_update(update):
    global ADMIN_ID
    
    if "message" in update:
        message = update["message"]
        chat_id = message["chat"]["id"]
        user_info = message.get("from", {})
        
        # Register user
        register_user(chat_id, user_info.get("username"), user_info.get("first_name"))

        # Setup auto-admin if none exists
        if not ADMIN_ID:
            ADMIN_ID = str(chat_id)
            config_db["admin_id"] = ADMIN_ID
            save_json(CONFIG_FILE, config_db)
            send_api("sendMessage", {
                "chat_id": chat_id,
                "text": "👑 Siz ushbu botning asosiy *Admini* etib tayinlandingiz!",
                "parse_mode": "Markdown"
            })

        is_admin = (str(chat_id) == str(ADMIN_ID))

        # Check for broadcast state
        if is_admin and config_db.get("state") == "waiting_for_broadcast":
            config_db["state"] = ""
            save_json(CONFIG_FILE, config_db)
            
            # Send broadcasting start notice
            send_api("sendMessage", {"chat_id": chat_id, "text": "📢 Reklama tarqatilmoqda, kuting..."})
            
            success_count = 0
            for u_id in users_db:
                # We can copy the message to all users
                res = send_api("copyMessage", {
                    "chat_id": int(u_id),
                    "from_chat_id": chat_id,
                    "message_id": message["message_id"]
                })
                if res and res.get("ok"):
                    success_count += 1
                time.sleep(0.05) # anti-flood delay
                
            send_api("sendMessage", {
                "chat_id": chat_id,
                "text": f"✅ Reklama yuborildi!\n👥 Jami foydalanuvchilar: {len(users_db)}\n📥 Muvaffaqiyatli yetkazildi: {success_count}"
            })
            return

        # 1. Admin uploads a video with caption "/set <num>"
        if is_admin and "video" in message and "caption" in message:
            caption = message["caption"].strip().lower()
            if caption.startswith("/set"):
                try:
                    cleaned = caption.replace("/set", "").strip()
                    episode_num = int(cleaned)
                    file_id = message["video"]["file_id"]
                    db[str(episode_num)] = file_id
                    save_json(DB_FILE, db)
                    send_api("sendMessage", {
                        "chat_id": chat_id,
                        "text": f"✅ {episode_num}-qism videosi muvaffaqiyatli saqlandi!"
                    })
                    return
                except Exception as e:
                    send_api("sendMessage", {"chat_id": chat_id, "text": f"❌ Xatolik: {e}"})
                    return

        # 2. Admin replies to a video message with "/set <num>"
        if "text" in message:
            text = message["text"].strip().lower()
            
            if is_admin and text.startswith("/set"):
                try:
                    cleaned = text.replace("/set", "").strip()
                    episode_num = int(cleaned)
                    
                    if "reply_to_message" in message and "video" in message["reply_to_message"]:
                        video_msg = message["reply_to_message"]
                        file_id = video_msg["video"]["file_id"]
                        db[str(episode_num)] = file_id
                        save_json(DB_FILE, db)
                        send_api("sendMessage", {
                            "chat_id": chat_id,
                            "text": f"✅ {episode_num}-qism videosi muvaffaqiyatli saqlandi! (Reply orqali)"
                        })
                        return
                    else:
                        send_api("sendMessage", {
                            "chat_id": chat_id,
                            "text": "💡 Videoga javob (reply) tarzida yuboring!"
                        })
                        return
                except Exception as e:
                    send_api("sendMessage", {
                        "chat_id": chat_id,
                        "text": f"❌ Xatolik: {e}. Format: /set 1 yoki /set1"
                    })
                    return

            # Commands
            if text == "/start":
                welcome_text = (
                    "Assalomu alaykum! 🎬 *Ichkarida* (İçerde) serialini Telegram'ning o'zida tomosha qilish botiga xush kelibsiz!\n\n"
                    "Qismlarni ko'rish uchun buyruqni bosing:\n"
                    "👉 /episodes"
                )
                send_api("sendMessage", {
                    "chat_id": chat_id, 
                    "text": welcome_text,
                    "parse_mode": "Markdown"
                })
            elif text == "/episodes":
                keyboard = make_episodes_keyboard()
                send_api("sendMessage", {
                    "chat_id": chat_id,
                    "text": "🎬 Kerakli epizodni tanlang:",
                    "reply_markup": keyboard
                })
            elif text == "/admin" and is_admin:
                keyboard = make_admin_keyboard()
                send_api("sendMessage", {
                    "chat_id": chat_id,
                    "text": "🛠️ *Admin Panelga xush kelibsiz!*",
                    "reply_markup": keyboard,
                    "parse_mode": "Markdown"
                })

    # Handle Callback Queries
    elif "callback_query" in update:
        callback = update["callback_query"]
        callback_id = callback["id"]
        chat_id = callback["message"]["chat"]["id"]
        message_id = callback["message"]["message_id"]
        data = callback["data"]
        is_admin = (str(chat_id) == str(ADMIN_ID))

        send_api("answerCallbackQuery", {"callback_query_id": callback_id})

        if data.startswith("episode_"):
            episode_num = data.split("_")[1]
            if episode_num in db:
                file_id = db[episode_num]
                send_api("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
                send_api("sendVideo", {
                    "chat_id": chat_id,
                    "video": file_id,
                    "caption": f"📽️ Ichkarida - {episode_num}-qism (O'zbek tilida)\n\n✨ Yoqimli tomosha!"
                })
            else:
                youtube_url = f"https://www.youtube.com/results?search_query=ichkarida+uzbek+tilida+{episode_num}+qism"
                uzmovi_url = "https://uzmovi.su/index.php?do=search&subaction=search&story=ichkarida"
                
                response_text = (
                    f"📽️ *Ichkarida - {episode_num}-qism (O'zbek tilida)*\n\n"
                    f"⚠️ Bu qism videosi hali Telegramga to'liq yuklanmagan.\n"
                    f"Quyidagi havolalar orqali onlayn ko'rishingiz mumkin:\n\n"
                    f"🔴 [YouTube orqali ko'rish]({youtube_url})\n"
                    f"🎬 [UzMovi saytidan ko'rish]({uzmovi_url})\n\n"
                    f"💡 _Tavsiya: Ushbu videoni botga forward qilib yuboring va unga reply qilib `/set {episode_num}` deb yozing._"
                )
                
                back_keyboard = {
                    "inline_keyboard": [[
                        {"text": "🔙 Epizodlar ro'yxatiga qaytish", "callback_data": "back_to_list"}
                    ]]
                }

                send_api("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": response_text,
                    "parse_mode": "Markdown",
                    "reply_markup": back_keyboard
                })
            
        elif data == "back_to_list":
            keyboard = make_episodes_keyboard()
            send_api("editMessageText", {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": "🎬 Kerakli epizodni tanlang:",
                "reply_markup": keyboard
            })

        # Admin panel buttons
        elif is_admin:
            if data == "admin_stats":
                stats_text = (
                    "📊 *Bot statistikasi:*\n\n"
                    f"👥 Foydalanuvchilar: {len(users_db)} ta\n"
                    f"🎬 Yuklangan qismlar: {len(db)} / {TOTAL_EPISODES} ta"
                )
                back_admin = {"inline_keyboard": [[{"text": "🔙 Ortga", "callback_data": "admin_back"}]]}
                send_api("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": stats_text,
                    "reply_markup": back_admin,
                    "parse_mode": "Markdown"
                })
            elif data == "admin_missing":
                missing = [str(i) for i in range(1, TOTAL_EPISODES + 1) if str(i) not in db]
                missing_text = (
                    "📋 *Hali yuklanmagan qismlar ro'yxati:*\n\n"
                    f"{', '.join(missing) if missing else 'Hamma qismlar yuklangan! 🎉'}"
                )
                back_admin = {"inline_keyboard": [[{"text": "🔙 Ortga", "callback_data": "admin_back"}]]}
                send_api("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": missing_text,
                    "reply_markup": back_admin,
                    "parse_mode": "Markdown"
                })
            elif data == "admin_broadcast":
                config_db["state"] = "waiting_for_broadcast"
                save_json(CONFIG_FILE, config_db)
                send_api("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": "📢 *Reklama matnini (yoki rasmli/videoli reklama) yuboring:*\n\nMen uni barcha foydalanuvchilarga jo'nataman.",
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": [[{"text": "🚫 Bekor qilish", "callback_data": "admin_back"}]]}
                })
            elif data == "admin_back":
                config_db["state"] = ""
                save_json(CONFIG_FILE, config_db)
                send_api("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": "🛠️ *Admin Panelga xush kelibsiz!*",
                    "reply_markup": make_admin_keyboard(),
                    "parse_mode": "Markdown"
                })
            elif data == "admin_close":
                send_api("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

def main():
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN not set in .env")
        return

    print("Bot is starting via long polling with Admin Panel...")
    offset = 0
    while True:
        try:
            updates = send_api("getUpdates", {"offset": offset, "timeout": 10})
            if updates and updates.get("ok"):
                for update in updates["result"]:
                    offset = update["update_id"] + 1
                    handle_update(update)
        except KeyboardInterrupt:
            print("Stopping bot...")
            break
        except Exception as e:
            print(f"Polling loop error: {e}")
        time.sleep(0.5)

if __name__ == "__main__":
    main()
