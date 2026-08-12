import telebot
from telebot import types
import pymongo
import time
from datetime import datetime, timedelta
import re
import uuid
import logging
import random
import string
import os
import qrcode
import io
from PIL import Image, ImageDraw

# --- CONFIGURATION ---
TOKEN = "8756542169:AAGmQN9cVOvYg5D2Yfjx0ApkbbVrXeHKji0"
CHANNELS = ["@Lalo_Proof", "@About_Me_Lalo", "@Lalo_Tech"]
PUBLIC_PROOF = "@Lalo_Proof"
PRIVATE_LOG = "@Lalo_Statistics"
ADMIN_ID = 6490035509

# MongoDB Connection (Render/GitHub Actions Environment Variable ykn Default Connection String)
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://<username>:<password>@cluster0.xxx.mongodb.net/?retryWrites=true&w=majority")
mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client["stars_bot_db"]

# Collections (Tables)
users_col = db["users"]
settings_col = db["settings"]
transactions_col = db["transactions"]

bot = telebot.TeleBot(TOKEN)
user_temp = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# --- DATABASE INITIALIZATION ---

def init_db():
    if not settings_col.find_one({"key": "maintenance"}):
        settings_col.insert_one({"key": "maintenance", "value": "OFF"})
    
    # Indexes for fast search
    users_col.create_index("user_id", unique=True)
    users_col.create_index("username")
    transactions_col.create_index("txid", unique=True)

init_db()

# --- HELPER FUNCTIONS ---

def get_missing_channels(user_id):
    if user_id == ADMIN_ID:
        return []
    missing = []
    for index, channel in enumerate(CHANNELS, start=1):
        try:
            status = bot.get_chat_member(channel, user_id).status
            if status not in ['member', 'administrator', 'creator']:
                missing.append(f"Join {index}")
        except Exception:
            missing.append(f"Join {index}")
    return missing

def get_join_markup(missing_list=None):
    markup = types.InlineKeyboardMarkup()
    if not missing_list:
        for index, ch in enumerate(CHANNELS, start=1):
            markup.add(types.InlineKeyboardButton(f"🔰 Join {index}", url=f"https://t.me/{ch[1:]}"))
    else:
        for item in missing_list:
            idx = int(item.split()[1]) - 1
            markup.add(types.InlineKeyboardButton(f"🔰 {item}", url=f"https://t.me/{CHANNELS[idx][1:]}"))
    markup.add(types.InlineKeyboardButton("✅ JOINED ✅", callback_data="check_sub"))
    return markup

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add("💰 Balance", "🧑‍🤝‍🧑 Referral", " 😊 Bonus", "💳 Withdraw", "📊 Statistics", "💸 Send Birr")
    return markup

def hide_keyboard():
    return types.ReplyKeyboardRemove()

def is_menu_button(text):
    buttons = ["💰 Balance", "🧑‍🤝‍🧑 Referral", " 😊 Bonus", "💳 Withdraw", "📊 Statistics", "💸 Send Birr"]
    return text in buttons

def check_interrupt(message):
    if not message.text:
        return False

    text = message.text

    if text.startswith('/'):
        bot.clear_step_handler_by_chat_id(message.chat.id)

        if text.startswith('/start'):
            start_and_commands(message)
            return True
        if text.startswith('/help'):
            start_and_commands(message)
            return True
        if text.startswith('/maintenance'):
            maintenance_start(message)
            return True
        if text.startswith('/bonus'):
            handle_bonus(message)
            return True
        if text.startswith('/chat'):
            start_live_chat(message)
            return True
        if text.startswith('/txid'):
            admin_search_txid(message)
            return True
        if text.startswith('/setbal'):
            admin_set_balance(message)
            return True
        if text.startswith('/qr'):
            send_qr_code(message)
            return True
        return False

    if is_menu_button(text):
        bot.clear_step_handler_by_chat_id(message.chat.id)
        handle_text(message)
        return True

    return False

def check_daily_transfer_limit(sender_id):
    twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    count = transactions_col.count_documents({
        "sender_id": str(sender_id),
        "timestamp": {"$gt": twenty_four_hours_ago}
    })
    return count < 5

def generate_txid_qr(txid, sender_id, receiver_id, amount, bot_username, tx_type="TRANSFER"):
    deep_link = f"https://t.me/{bot_username}?start={txid}"
    
    if tx_type == "WITHDRAWAL":
        amt_display = int(amount) if isinstance(amount, (int, float)) else amount
        qr_data = (
            f"😊LALO TELEBIRR BOT WITHDRAWL PAID✅\n\n"
            f"🔰 𝗧𝗫𝗜𝗗: {txid}\n\n"
            f"🔰 𝗦𝘁𝗮𝘁𝘂𝘀: WITHDRAWAL Birr Done✅\n\n"
            f"🔰 𝗔𝗺𝗼𝘂𝗻𝘁/መጠን: {amt_display} Birr\n\n"
            f"🔰 𝗦𝗲𝗻𝗱𝗲𝗿/ላኪ: Admin Of The Bot\n\n"
            f"🔰 𝗥𝗲𝗰𝗲𝗶𝘃𝗲𝗿/ተቀባይ: {receiver_id}\n\n"
            f"🔰 𝗩𝗲𝗿𝗶𝗳𝘆/ማረጋገጥ: {deep_link}"
        )
    else:
        amt_display = int(amount) if isinstance(amount, (int, float)) else amount
        qr_data = (
            f"😊LALO TELEBIRR BOT BIRR RECEIPT LINK\n\n"
            f"🔰 𝗧𝗫𝗜𝗗: {txid}\n\n"
            f"🔰 𝗔𝗺𝗼𝘂𝗻𝘁/መጠን: {amt_display} Birr\n\n"
            f"🔰 𝗦𝗲𝗻𝗱𝗲𝗿/ላኪ: {sender_id}\n\n"
            f"🔰 𝗥𝗲𝗰𝗲𝗶𝘃𝗲𝗿/ተቀባይ: {receiver_id}\n\n"
            f"🔰 𝗩𝗲𝗿𝗶𝗳𝘆/ማረጋገጥ: {deep_link}"
        )
        
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=3
    )
    qr.add_data(qr_data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    logo_path = "bot.lalo.png"
    if os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            qr_w, qr_h = img.size
            logo_size = int(qr_w * 0.22)
            logo = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)

            mask = Image.new('L', (logo_size, logo_size), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, logo_size, logo_size), fill=255)

            circle_bg = Image.new('RGBA', (logo_size, logo_size), (255, 255, 255, 255))
            circle_bg.putalpha(mask)

            pos = ((qr_w - logo_size) // 2, (qr_h - logo_size) // 2)
            img.paste(circle_bg, pos, circle_bg)
            
            logo_cropped = Image.new('RGBA', (logo_size, logo_size), (0, 0, 0, 0))
            logo_cropped.paste(logo, (0, 0), mask)
            img.paste(logo_cropped, pos, logo_cropped)
        except Exception as e:
            print(f"QR Logo Error: {e}")

    bio = io.BytesIO()
    bio.name = f'{txid}.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio

# --- LOGGING SYSTEM ---

def send_log(user_id, status_text, current_balance, referrer_id="None"):
    now = datetime.now().strftime("%B %d, %Y | %H:%M")
    user = users_col.find_one({"user_id": user_id})
    old_msg_id = user.get("last_log_id", 0) if user else 0

    try:
        user_info = bot.get_chat(user_id)
        name = user_info.first_name
    except Exception:
        name = "Unknown"

    ref_display = "None"
    if referrer_id and str(referrer_id) != "None":
        try:
            ref_info = bot.get_chat(referrer_id)
            ref_name = ref_info.first_name
            ref_display = f"[{ref_name}](tg://user?id={referrer_id})"
        except Exception:
            ref_display = f"`{referrer_id}`"

    report = (
        f"🔔 ACTIVITY REPORT 🔔\n"
        f"━━━━━━━━━━━━━━\n"
        f"📅 Date :  {now}\n\n"
        f"👤 Name :  [{name}](tg://user?id={user_id})\n\n"
        f"🆔 ID : `{user_id}`\n\n"
        f"⚡ Status : {status_text}\n\n"
        f"💰 Balance : {int(current_balance)} ETB\n\n"
        f"🧑‍🤝‍🧑 Refer by : {ref_display}\n"
        f"━━━━━━━━━━━━━━"
    )

    try:
        if old_msg_id != 0:
            bot.delete_message(PRIVATE_LOG, old_msg_id)
    except Exception:
        pass

    try:
        new_msg = bot.send_message(PRIVATE_LOG, report, parse_mode="Markdown")
        users_col.update_one({"user_id": user_id}, {"$set": {"last_log_id": new_msg.message_id}})
    except Exception:
        pass

# --- CORE HANDLERS ---

def handle_bonus(message):
    user_id = message.from_user.id
    user = users_col.find_one({"user_id": user_id})
    if not user:
        return
    
    balance = user.get("balance", 0.0)
    last_bonus = user.get("last_bonus", 0)
    ref_by = user.get("referred_by", None)

    curr = int(time.time())
    if curr - int(last_bonus) >= 86400:
        users_col.update_one(
            {"user_id": user_id},
            {"$inc": {"balance": 3}, "$set": {"last_bonus": curr}}
        )
        bot.send_message(message.chat.id, "🤝Congratulations!👏🎉\n\n🔰 You received your 3 birr daily bonus!😊\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 እንኳን ደስ አለህ! 👏🎉 ሁሌ በቀን የሚሰጠው 3 ብር ጉርሻ አግኝተሃል😊", reply_markup=get_main_keyboard())
        send_log(user_id, "Claimed Bonus 🥳", balance + 3, ref_by)
    else:
        remaining = 86400 - (curr - int(last_bonus))
        hr = remaining // 3600
        bot.send_message(message.chat.id, f"🔰 You already took your bonus for today\nSo, come back in {hr} hours again🤭\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 ለዛሬ ጉርሻህን አስቀድመህ ወስደሃል።\nስለዚህ በ {hr} ሰዓታት ውስጥ እንደገና ተመልሰህ መዉሰድ ትችላለህ🤭", reply_markup=get_main_keyboard())

@bot.message_handler(commands=['setbal'])
def admin_set_balance(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "⚠️ Usage: `/setbal <user_id> <new_balance>`\nExample: `/setbal 6741729157 0`", parse_mode="Markdown")
        return
    
    try:
        u_id = int(args[1])
        new_bal = float(args[2])
        
        users_col.update_one({"user_id": u_id}, {"$set": {"balance": new_bal}}, upsert=True)
        bot.reply_to(message, f"✅ Balance for User `{u_id}` updated to `{new_bal}` birr!", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['qr'])
def send_qr_code(message):
    try:
        bot_username = bot.get_me().username
        bot_link = f"https://t.me/{bot_username}"

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(bot_link)
        qr.make(fit=True)

        qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGB')

        logo_path = "bot.lalo.png"
        if os.path.exists(logo_path):
            logo = Image.open(logo_path).convert("RGBA")
            qr_w, qr_h = qr_img.size
            logo_size = qr_w // 5
            logo = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)

            mask = Image.new('L', (logo_size, logo_size), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, logo_size, logo_size), fill=255)

            circle_bg = Image.new('RGBA', (logo_size, logo_size), (255, 255, 255, 255))
            circle_bg.putalpha(mask)

            pos = ((qr_w - logo_size) // 2, (qr_h - logo_size) // 2)
            
            qr_img.paste(circle_bg, pos, circle_bg)
            
            logo_cropped = Image.new('RGBA', (logo_size, logo_size), (0, 0, 0, 0))
            logo_cropped.paste(logo, (0, 0), mask)
            qr_img.paste(logo_cropped, pos, logo_cropped)

        output_file = "bot_qr.png"
        qr_img.save(output_file)

        with open(output_file, 'rb') as photo:
            bot.send_photo(message.chat.id, photo, caption="🎨 QR Code Bot kootii!")

        if os.path.exists(output_file):
            os.remove(output_file)

    except Exception as e:
        bot.reply_to(message, f"Dogoggora: {e}")

@bot.message_handler(commands=['start', 'bonus', 'help', 'chat', 'txid'])
def start_and_commands(message):
    user_id = message.from_user.id
    name = message.from_user.first_name
    uname = message.from_user.username

    args = message.text.split()
    if message.text.startswith('/start') and len(args) > 1:
        param = args[1].strip().upper()
        if not param.isdigit():
            tx = transactions_col.find_one({"txid": param})
            if tx:
                sender_id = tx["sender_id"]
                receiver_id = tx["receiver_id"]
                amount = tx["amount"]
                timestamp = tx["timestamp"]
                tx_type = tx.get("tx_type", "TRANSFER")

                bot_username = bot.get_me().username
                qr_photo = generate_txid_qr(param, sender_id, receiver_id, amount, bot_username, tx_type=tx_type)
                
                if tx_type == "WITHDRAWAL":
                    text = (
                        f"🔍 <b>VERIFIED WITHDRAWAL RECEIPT</b> ✅\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"🔰 <b>TXID:</b> <code>{param}</code>\n\n"
                        f"🔰 <b>Status:</b> WITHDRAWAL Birr Done✅\n\n"
                        f"🔰 <b>Amount/መጠን:</b> <code>{int(amount)}</code> Birr\n\n"
                        f"🔰 <b>Sender/ላኪ:</b> Admin Of The Bot\n\n"
                        f"🔰 <b>Receiver/ተቀባይ:</b> <code>{receiver_id}</code>\n\n"
                        f"🔰 <b>Date/ቀን:</b> <code>{timestamp}</code>"
                    )
                else:
                    text = (
                        f"🔍 <b>VERIFIED TRANSACTION RECEIPT</b> ✅\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"🔰 <b>TXID:</b> <code>{param}</code>\n\n"
                        f"🔰 <b>Amount/መጠን:</b> <code>{int(amount)}</code> Birr\n\n"
                        f"🔰 <b>Sender/ላኪ:</b> <code>{sender_id}</code>\n\n"
                        f"🔰 <b>Receiver/ተቀባይ:</b> <code>{receiver_id}</code>\n\n"
                        f"🔰 <b>Date/ቀን:</b> <code>{timestamp}</code>"
                    )
                bot.send_photo(message.chat.id, qr_photo, caption=text, parse_mode="HTML", reply_markup=get_main_keyboard())
                return

    if message.text.startswith('/help'):
        help_text = (
            "Hey😊Welcome✋\n\n"
            "🔰 Have you had any problems yet?\n"
            "🔰If you have any comments or questions, you can chat with the Bot Creator 24/7 using the Username below 👇\n\n\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 እስካሁን ችግር አጋጥሞሃል? \n\n🔰 ማንኛውም አስተያየት ወይም ጥያቄ ካለህ ከታች ያለውን Username በመጠቀም ከቦት Creator ጋር 24/7 መነጋገር ትችላለህ።👇\n\n"
            "          ➡️ @Lalo_Kajela"
        )
        bot.send_message(message.chat.id, help_text)
        return

    if message.text.startswith('/bonus'):
        handle_bonus(message)
        return

    if message.text.startswith('/chat'):
        start_live_chat(message)
        return

    if message.text.startswith('/txid'):
        admin_search_txid(message)
        return

    bot.clear_step_handler_by_chat_id(chat_id=message.chat.id)

    user = users_col.find_one({"user_id": user_id})

    is_new_user = False
    referrer_id = None
    if not user:
        is_new_user = True
        if len(args) > 1 and args[1].isdigit():
            try:
                referrer_id = int(args[1])
            except Exception:
                referrer_id = None

        new_user_data = {
            "user_id": user_id,
            "balance": 0.0,
            "referred_by": referrer_id,
            "last_bonus": 0,
            "last_log_id": 0,
            "is_rewarded": 0,
            "username": uname,
            "join_date": datetime.now().strftime("%Y-%m-%d")
        }
        users_col.insert_one(new_user_data)
        send_log(user_id, "😊 Started the Bot 🆕", 0.0, referrer_id)
    else:
        users_col.update_one({"user_id": user_id}, {"$set": {"username": uname}})
        send_log(user_id, "🚶Re-started the Bot 🔄", user.get("balance", 0.0), user.get("referred_by", None))

    missing = get_missing_channels(user_id)
    if not missing:
        bot.send_message(message.chat.id, f"👋Hey😊 [{name}](tg://user?id={user_id})\n\n🔰 Well come back again to Lalo Telebirr Bot 🤝 \n🔰 Continue earn birr  by inviting your friends 🧑‍🤝‍🧑\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 እንኳን በደህና ወደ Lalo Telebirr Bot እንደገና መጣህ🤝\n🔰 እንደሚታወቀው አሁንም ጓደኞችህን በመጋበዝ ብር  ስራ🧑‍🤝‍🧑", reply_markup=get_main_keyboard(), parse_mode="Markdown")
    else:
        if is_new_user:
            text = f"👋Hey😊 [{name}](tg://user?id={user_id})\n\nWelcome to Lalo Telebirr Bot🤝\n🔰 Please join this all our channels and once you are done all joining, click on JOINED ✅ button to get all service and then earn birr per day by inviting your friends 🧑‍🤝‍🧑\n━━━━━━━━━━━━━━\n🔰 እንኳን ወደ Lalo Telebirr Bot በደህና መጣህ🤝 እባክህን ሁሉንም ቻናሎቻችንን ተቀላቀልና መቀላቀልህን ካረጋገጥክ በኋላ ደሞ አገልግሎት እንድታገኝ JOINED ✅ የሚለውን Button ተጫንና ጓደኞችህን በመጋበዝ ብቻ በየቀኑ ብር  ስራ🧑‍🤝‍🧑"
        else:
            ch_names = ", ".join(missing)
            text = f"⚠️Hey [{name}](tg://user?id={user_id}) Attention✋\n\n🔰 Sorry🙏 you have left our channel ({ch_names}) and cannot use it this bot😁join again\n━━━━━━━━━━━━━━━\n🔰ይቅርታ🙏ቻናላችንን ({ch_names}) ለቀህ ወጥተሃል።\n🔰 ስለዚህ በፍፁም ይህን ቦት መጠቀም አትችልም😁እናም የበሉበትን ሰሃን አለማጠብ ጋር አንድ ስለሆነ ከይቅርታ ጋር Left ያረከውን ቻነል ተመልሰህ እንደገና ተቀላቀልበት\n\nThankyou😊🙏"

        m1 = bot.send_message(message.chat.id, text, reply_markup=hide_keyboard(), parse_mode="Markdown")
        m2 = bot.send_message(message.chat.id, "🔰 When you join all channel, tap JOINED ✅ button👇\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 ለመቀላቀል መጀመርያ ቻነል Join አርግና ከዛ JOINED✅ ቡቶን ንካው👇", reply_markup=get_join_markup(missing))
        user_temp[f"msg1_{user_id}"] = m1.message_id
        user_temp[f"msg2_{user_id}"] = m2.message_id

# --- CALLBACK HANDLER ---

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    name = call.from_user.first_name

    if call.data in ["m_off", "m_on", "m_broadcast"]:
        maintenance_logic(call)
        return

    if call.data == "user_reply_to_admin":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        start_live_chat(call.message)
        return

    if call.data == "check_sub":
        missing = get_missing_channels(user_id)
        if not missing:
            user = users_col.find_one({"user_id": user_id})

            if user and user.get("is_rewarded", 0) == 0:
                referrer_id = user.get("referred_by")
                if referrer_id and referrer_id != user_id:
                    users_col.update_one({"user_id": referrer_id}, {"$inc": {"balance": 10}})
                    users_col.update_one({"user_id": user_id}, {"$set": {"is_rewarded": 1}})

                    ref_data = users_col.find_one({"user_id": referrer_id})
                    if ref_data:
                        send_log(referrer_id, "🧑 New Referral Joined", ref_data.get("balance", 0.0), ref_data.get("referred_by"))

                    try:
                        msg = f"🎁 Congratulations!🎉\n\n🔰 [{name}](tg://user?id={user_id}) is joined using your link! So, you've got 10 birr now.\nCheck your balance 😊\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 አሁን [{name}](tg://user?id={user_id}) የመጋበዣ ሊንክህን በመጠቀሙ 10 birr አግኝታሃል ቀሪ ሂሳብህን አረጋግጥ😊"
                        bot.send_message(referrer_id, msg, parse_mode="Markdown")
                    except Exception:
                        pass

            bot.answer_callback_query(call.id, "Done! ✅")

            try:
                bot.delete_message(call.message.chat.id, user_temp.get(f"msg1_{user_id}"))
                bot.delete_message(call.message.chat.id, user_temp.get(f"msg2_{user_id}"))
            except Exception:
                pass
            bot.send_message(call.message.chat.id, "🔰 Done! ✅ Now you are joined our channel😊So, you can continue\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 Done! ✅ አሁን ቻናላችንን ተቀላቅላሃል😊ስለዚህ ቀጥልበት", reply_markup=get_main_keyboard())
        else:
            bot.answer_callback_query(call.id, "Warning⚠️ማስጠንቀቅያ")
            bot.send_message(call.message.chat.id, "🔰 Sorry, first join our channels🤭\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 ይቅርታ መጀመሪያ ቻናሎቻችንን ተቀላቀልበት🤭")

    elif call.data == "main_menu":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.clear_step_handler_by_chat_id(call.message.chat.id)
        bot.send_message(call.message.chat.id, "Main Menu  😊", reply_markup=get_main_keyboard())

    elif call.data.startswith("w_"):
        if user_id not in user_temp: user_temp[user_id] = {}
        user_temp[user_id]["method"] = call.data.split("_")[1]
        bot.delete_message(call.message.chat.id, call.message.message_id)
        msg = bot.send_message(call.message.chat.id, f"🔰 Send me the account number you want to spend on {user_temp[user_id]['method']} \n━━━━━━━━━━━━━━━━━━━━━━━\n🔰 ልታወጣበት የምትፈልገውን የ{user_temp[user_id]['method']} Account ቁጥር በትክክል ላክ።")
        bot.register_next_step_handler(msg, validate_acc)

    elif call.data == "confirm_final":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        msg = bot.send_message(call.message.chat.id, "🔰 Enter birr amount you want to withdraw\n━━━━━━━━━━━━━━━━━━━━━━━\n 🔰 ማውጣት የምትፈልገውን የብር መጠን አስገባ")
        bot.register_next_step_handler(msg, final_step)

    elif call.data == "confirm_send":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        msg = bot.send_message(call.message.chat.id, "🔰 Enter birr amount you want to send your friends\n━━━━━━━━━━━━━━━━━━━━━━━\n🔰 ለጓደኛህ መላክ የምትፈልገውን የብር መጠን አስገባ")
        bot.register_next_step_handler(msg, process_send_amount)

    elif call.data == "final_transfer_confirm":
        r_id = user_temp[user_id]["r_id"]
        amt = user_temp[user_id]["send_amt"]

        txid = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_display = datetime.now().strftime("%Y-%m-%d %H:%M")
        bot_username = (bot.get_me()).username

        sender_row = users_col.find_one({"user_id": user_id})
        sender_old_bal = sender_row.get("balance", 0.0) if sender_row else 0
        sender_ref_id = sender_row.get("referred_by") if sender_row else None

        receiver_row = users_col.find_one({"user_id": r_id})
        receiver_old_bal = receiver_row.get("balance", 0.0) if receiver_row else 0
        receiver_ref_id = receiver_row.get("referred_by") if receiver_row else None

        sender_new_bal = sender_old_bal - amt
        receiver_new_bal = receiver_old_bal + amt

        users_col.update_one({"user_id": user_id}, {"$inc": {"balance": -amt}})
        users_col.update_one({"user_id": r_id}, {"$inc": {"balance": amt}})

        transactions_col.insert_one({
            "txid": txid,
            "sender_id": str(user_id),
            "receiver_id": str(r_id),
            "amount": amt,
            "timestamp": now_str,
            "tx_type": "TRANSFER"
        })

        try:
            sender_info = bot.get_chat(user_id)
            sender_name = sender_info.first_name
        except Exception:
            sender_name = "User"

        try:
            receiver_info = bot.get_chat(r_id)
            receiver_name = receiver_info.first_name
        except Exception:
            receiver_name = "User"

        sender_link = f"<a href='tg://user?id={user_id}'>{sender_name}</a>"
        receiver_link = f"<a href='tg://user?id={r_id}'>{receiver_name}</a>"

        sender_ref_link = "None"
        if sender_ref_id and str(sender_ref_id) != "None":
            try:
                s_ref_info = bot.get_chat(sender_ref_id)
                sender_ref_link = f"<a href='tg://user?id={sender_ref_id}'>{s_ref_info.first_name}</a>"
            except Exception:
                sender_ref_link = f"<code>{sender_ref_id}</code>"

        receiver_ref_link = "None"
        if receiver_ref_id and str(receiver_ref_id) != "None":
            try:
                r_ref_info = bot.get_chat(receiver_ref_id)
                receiver_ref_link = f"<a href='tg://user?id={receiver_ref_id}'>{r_ref_info.first_name}</a>"
            except Exception:
                receiver_ref_link = f"<code>{receiver_ref_id}</code>"

        log_text = f"""🔔 <b>SEND BIRR ALERT</b> 🔔
━━━━━━━━━━━━━━
📅 <b>Date :</b> {now_display}

👤 <b>Sender Name :</b> {sender_link}
🆔 <b>Sender ID :</b> <code>{user_id}</code>

👤 <b>Receiver Name :</b> {receiver_link}
🆔 <b>Receiver ID :</b> <code>{r_id}</code>

⚡ <b>Status :</b> Received Birr / Send Birr ✅
🧾 <b>TXID :</b> <code>{txid}</code>

💰 <b>Transferred Amount :</b> {int(amt)} ETB
💰 <b>Sender New Balance :</b> {int(sender_new_bal)} ETB
💰 <b>Receiver New Balance :</b> {int(receiver_new_bal)} ETB

🧑‍🤝‍🧑 <b>Sender Referred By :</b> {sender_ref_link}
🧑‍🤝‍🧑 <b>Receiver Referred By :</b> {receiver_ref_link}
━━━━━━━━━━━━━━"""

        try:
            bot.send_message(PRIVATE_LOG, log_text, parse_mode="HTML")
        except Exception as e:
            print(f"Send Birr Channel Log Error: {e}")

        qr_photo_sender = generate_txid_qr(txid, user_id, r_id, amt, bot_username, tx_type="TRANSFER")
        qr_photo_receiver = generate_txid_qr(txid, user_id, r_id, amt, bot_username, tx_type="TRANSFER")

        bot.delete_message(call.message.chat.id, call.message.message_id)

        sender_msg = (
            f"🔰 Done ✅ You are send for your friends {int(amt)} birr\n"
            f"━━━━━━━━━━━━━━\n"
            f"🔢 TXID : `{txid}`\n"
            f"📅 Date : {now_display}\n"
            f"━━━━━━━━━━━━━━\n"
            f"🔰 Done ✅ ለጓደኛህ {int(amt)} ብር ልከሃል"
        )
        bot.send_photo(call.message.chat.id, qr_photo_sender, caption=sender_msg, parse_mode="Markdown")

        try:
            receiver_msg = (
                f"Congratulations🎉\n\n"
                f"🔰 You are get {int(amt)} birr from [{sender_name}](tg://user?id={user_id}) 😇check your balance now\n"
                f"━━━━━━━━━━━━━━\n"
                f"🔢 TXID : `{txid}`\n"
                f"📅 Date : {now_display}\n"
                f"━━━━━━━━━━━━━━\n"
                f"🔰 ከ [{sender_name}](tg://user?id={user_id}) {int(amt)} birr ተልኮልሃል😇አሁን ቀሪ ሂሳብህን አረጋግጥ"
            )
            bot.send_photo(r_id, qr_photo_receiver, caption=receiver_msg, parse_mode="Markdown")
        except Exception:
            pass

    elif call.data == "user_request_approve":
        if user_id not in user_temp or "amt" not in user_temp[user_id]:
            bot.answer_callback_query(call.id, "Session expired. Try again.", show_alert=True)
            return

        amt = user_temp[user_id]["amt"]
        users_col.update_one({"user_id": user_id}, {"$inc": {"balance": -amt}})

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("Approve ✅", callback_data=f"adm_approve_{user_id}"),
            types.InlineKeyboardButton("Cash Back 🔙", callback_data=f"adm_callback_{user_id}_{int(amt)}"),
            types.InlineKeyboardButton("Mark as paid ✅", callback_data=f"adm_paid_{user_id}_{int(amt)}")
        )
        req = (
            f"👤 User : [{call.from_user.first_name}](tg://user?id={user_id})\n"
            f"━━━━━━━━━━━━━━\n"
            f"🆔 : `{user_id}`\n\n"
            f"💰 Amount : {int(amt)} birr\n\n"
            f"🏦 Method : {user_temp[user_id]['method']}\n\n"
            f"🔢 Acc : `{user_temp[user_id]['acc']}`\n\n"
            f"👤 Name : {user_temp[user_id]['name']}\n"
            f"━━━━━━━━━━━━━━"
        )
        bot.send_message(ADMIN_ID, req, reply_markup=markup, parse_mode="Markdown")
        bot.edit_message_text("🔰 Done your withdraw request is sent to admin✅So,Please wait for the admin to process it🤭\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 Done የማዉጣት ጥያቄህ ወደ Admin ተለኳል✅ስለዚህ እባክህን አድሚኑ እስኪያስተናግድህ ድረስ በመስመር ላይ ጠብቅ🤭", call.message.chat.id, call.message.message_id)

    elif call.data.startswith("adm_callback_"):
        parts = call.data.split("_")
        u_id = int(parts[2])
        amount = float(parts[3])
        
        users_col.update_one({"user_id": u_id}, {"$inc": {"balance": amount}})
        
        bot.send_message(u_id, "ohooo!sorry🙏\n\n🔰 Your withdrawal request is Cash Backed by admin😭\n🔰 Check your balance and try again\n\n🔰 Or ask the owner of this bot or admin click /chat why it failed and he will answer you😥\n━━━━━━━━━━━━━━━━━━━━━━━\n🔰 የማውጣት ጥያቄህ በAdmin ዉድቅ ሆነ👎\n🔰 ገንዘብህ ደሞ ወደ አካዉንትህ ተመልሷል😭ቀሪ ሂሳብህን አረጋግጥ እና እንደገና ለማዉጣት ሞክር \n\n 🔰 ወይም ደሞ ለምን ዉድቅ እንደሆነ የዚህ Bot ባለቤት የሆነ ወይም Admin አግኝተህ ለማዋራት በዚሁ  /chat 'ን ንካውና ጠይቀው😥\n\nThankyou🙏")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, f"🔰 Cash backed🔙\n✅ Done for {u_id} ")

    elif call.data.startswith("adm_approve_"):
        u_id = int(call.data.split("_")[2])
        bot.send_message(u_id, "🔰 Done✅ Your withdrawal request is approved by admin😇So, please wait a few minutes while he is paid for you\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 Done✅የመውጣት ጥያቄህ ተቀባይነት አግኝቶ አድሚን ጸድቋል😇\nእባክህን ክፍያው እስኪፈጸም ድረስ ጥቂት ደቂቃዎችን ብቻ ጠብቅ\n\nThankyou🤭🙏")
        bot.answer_callback_query(call.id, "Approved! ✅")

    elif call.data.startswith("adm_paid_"):
        parts = call.data.split("_")
        u_id = int(parts[2])
        
        req_text = call.message.text
        amt_val = 0
        if len(parts) > 3:
            amt_val = float(parts[3])
        else:
            amt_match = re.search(r"Amount : (\d+)", req_text)
            if amt_match:
                amt_val = float(amt_match.group(1))

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        txid = 'WD' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        bot_username = (bot.get_me()).username

        transactions_col.insert_one({
            "txid": txid,
            "sender_id": "ADMIN",
            "receiver_id": str(u_id),
            "amount": amt_val,
            "timestamp": now_str,
            "tx_type": "WITHDRAWAL"
        })

        qr_photo_channel = generate_txid_qr(txid, "ADMIN", u_id, amt_val, bot_username, tx_type="WITHDRAWAL")
        qr_photo_user = generate_txid_qr(txid, "ADMIN", u_id, amt_val, bot_username, tx_type="WITHDRAWAL")

        proof_caption = (
            f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"<b>🔔 WITHDRAWAL PAID ✅</b>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            f"<code>{req_text}</code>\n\n"
            f"🔢 <b>TXID :</b> <code>{txid}</code>\n\n"
            f"📅  <b>Date :</b> {now}\n\n"
            f"📢  <b>Channel :</b> {PUBLIC_PROOF}\n🔰 𝗕𝗼𝘁: @Lalo_Telebirr_Bot\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━</b>"
        )

        user_msg = (
            f"🤭<b>Congratulations</b>🎉\n\n"
            f"🔰 Your money is paid by admin✅ and again make money by inviting your friends\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔢 <b>TXID :</b> <code>{txid}</code>\n"
            f"📅 <b>Date :</b> {now}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔰 አሁን ገንዘብህ በAdmin ተከፍሏል✅ እናም አሁንም ጓደኞችህን በመጋበዝ እንደገና ገንዘብ መስራት ትችላለህ\n\n"
            f"Thankyou!😊🙏"
        )

        try:
            bot.send_photo(PUBLIC_PROOF, qr_photo_channel, caption=proof_caption, parse_mode="HTML")
            bot.send_photo(u_id, qr_photo_user, caption=user_msg, parse_mode="HTML")
            bot.edit_message_text("Success✅ Marked as paid for user with QR Receipt!😊", call.message.chat.id, call.message.message_id, reply_markup=None)
            bot.answer_callback_query(call.id, "Paid successfully! ✅")
        except Exception as e:
            bot.answer_callback_query(call.id, f"Error: {e}", show_alert=True)

    elif call.data.startswith("reply_"):
        u_id = call.data.split("_")[1]
        msg = bot.send_message(ADMIN_ID, f"📩 <b>Enter your reply for user</b> <code>{u_id}</code>:", parse_mode="HTML")
        bot.register_next_step_handler(msg, lambda m: send_reply_to_user(m, u_id))

# --- TRANSACTION & VALIDATION PROCESS ---

def process_send_amount(message):
    if check_interrupt(message):
        return

    user_id = message.from_user.id

    if not check_daily_transfer_limit(user_id):
        bot.send_message(
            message.chat.id,
            "✋Stop🛑 You have reached your limit! You cannot send money more than 5 times within 24 hours.\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "✋አቁመው🛑በ24 ሰዓታት ውስጥ ገንዘብ ከ 5 ጊዜ በላይ ለሰው መላክ አትችልም"
        )
        return

    try:
        amt = float(message.text)
        if 2 <= amt <= 1000:
            balance_row = users_col.find_one({"user_id": user_id})
            balance = balance_row.get("balance", 0.0) if balance_row else 0

            if balance >= amt:
                if user_id not in user_temp: user_temp[user_id] = {}
                user_temp[user_id]["send_amt"] = amt
                msg = bot.send_message(message.chat.id, "Good👍✅🤭\n\n🔰 Enter your friends Username or 🆔\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 የጓደኛህን Username ወይም 🆔 አስገባ።")
                bot.register_next_step_handler(msg, process_send_recipient)
            else:
                msg = bot.send_message(message.chat.id, f" ❌ Insufficient balance!\n😥 Now you have {int(balance)} birr only\n━━━━━━━━━━━━━━━━━━\n❌ በቂ ያልሆነ ቀሪ ሂሳብ!\n😥 አሁን ያለህ ቀሪ ሂሳብ {int(balance)} ብር ብቻ ነው\n━━━━━━━━━━━━━━━━━━\n🔰 Invite your friends and get other money\n🔰 አሁንም ጓደኛህን በመጋበዝ ሌላ ገንዘብ ስራ")
                bot.register_next_step_handler(msg, process_send_amount)
        else:
            msg = bot.send_message(message.chat.id, "🔰 Minimum = 2 birr\n🔰 Maximum = 1000 birr ")
            bot.register_next_step_handler(msg, process_send_amount)
    except Exception:
        bot.send_message(message.chat.id, "⚠️ Please enter a valid amount😥\n━━━━━━━━━━━━━━━━━━━━━━\n⚠️ እባክህ ትክክለኛ የብር መጠን አስገባ😥")
        bot.register_next_step_handler(message, process_send_amount)

def process_send_recipient(message):
    if check_interrupt(message):
        return

    user_id = message.from_user.id
    target = message.text.strip()

    if target.startswith("@"):
        res = users_col.find_one({"username": target[1:]})
    else:
        try:
            res = users_col.find_one({"user_id": int(target)})
        except Exception:
            msg = bot.send_message(message.chat.id, "❓Invalid ID or Username format\n🔰 Please enter correct ID or Username\n━━━━━━━━━━━━━━━━━━━━━━\n❓ ልክ ያልሆነ ID ወይም Username።\n🔰 እባክህ ትክክለኛ ID ወይም Username አስገባ ")
            bot.register_next_step_handler(msg, process_send_recipient)
            return

    if not res:
        msg = bot.send_message(message.chat.id, "🔰 Sorry🙏this person is not a customer of our bot\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 ይቅርታ🙏ይህ ሰው የቦታችን ተጠቃሚ አይደለም ተሳስተሃል።")
        bot.register_next_step_handler(msg, process_send_recipient)
        return

    r_id = res["user_id"]
    missing_r = get_missing_channels(r_id)
    if missing_r:
        bot.send_message(message.chat.id, "⚠️ Error! this user is not in our channel anymore. You cannot send money to them until they join back\n━━━━━━━━━━━━━━━━━━━━━━━\n⚠️ ስህተት! ይህ ሰው የቦታችን ተጠቃሚ ነበረ ብሆንም ግን አሁን ከቻናላችን ወቷል።ተመልሶ ቻናሉንና ቦቱን እስኪቀላቀል ድረስ ለዚህ ሰው ገንዘብ መላክ አትችልም😥")
        return

    if r_id == user_id:
        bot.send_message(message.chat.id, "You cannot send money it back to yourself😁\n━━━━━━━━━━━━━━━━━━━━━━━\nእረፍ ባክህ😁ወደ ራስህ መልሰህ ብር መላክ አትችልም")
        return

    try:
        r_info = bot.get_chat(r_id)
        r_name = r_info.first_name
        mention = f"[{r_name}](tg://user?id={r_id})"
    except Exception:
        mention = f"`{r_id}`"

    user_temp[user_id]["r_id"] = r_id
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Yes confirm ✅", callback_data="final_transfer_confirm"), types.InlineKeyboardButton("No 🛑", callback_data="main_menu"))

    bot.send_message(message.chat.id, f" Good👍✅🤭\n\n🔰 Do you want to send this {int(user_temp[user_id]['send_amt'])} birr to {mention}?🤔\n━━━━━━━━━━━━━━━━━━━━━━━\n🔰 ይህን {int(user_temp[user_id]['send_amt'])} ብር ለ {mention} መላክ ትፈልጋለህ?🤔", reply_markup=markup, parse_mode="Markdown")

def withdraw_start(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("CBE Bank", callback_data="w_CBE Bank"),
        types.InlineKeyboardButton("Telebirr", callback_data="w_Telebirr"),
        types.InlineKeyboardButton("Awash Bank", callback_data="w_Awash Bank"),
        types.InlineKeyboardButton("CBE Birr", callback_data="w_CBE Birr"),
        types.InlineKeyboardButton("🔙 Back", callback_data="main_menu")
    )
    bot.send_message(message.chat.id, "🔰 Choose Withdrawal Method👇\n━━━━━━━━━━━━━━━━━━━━\n🔰 የማውጣት ዘዴን ምረጥ👇", reply_markup=markup)

def validate_acc(message):
    if check_interrupt(message):
        return

    user_id = message.from_user.id
    text = message.text.strip().replace(" ", "")
    if user_id not in user_temp or "method" not in user_temp[user_id]:
        return

    method = user_temp[user_id]["method"]
    is_valid = False
    error_msg = "⚠️Invalid!"

    if method == "CBE Bank":
        if text.isdigit() and len(text) == 13:
            is_valid = True
        else:
            error_msg = "⚠️Please enter the correct CBE Bank account number only!\n━━━━━━━━━━━━━━━━━━━━━━━\n⚠️እባክህ ትክክለኛውን የንግድ ባንክ ሂሳብ ቁጥርህን ብቻ አስገባ እንጂ ሌላ ነገር እንደ ፍደል እና ስርዓተ ነጥብ አትጻፍ!"

    elif method == "Awash Bank":
        if text.isdigit() and len(text) == 14:
            is_valid = True
        else:
            error_msg = "⚠️ Please enter the correct Awash Bank account number only!\n━━━━━━━━━━━━━━━━━━━━━━━\n⚠️ እባክህ ትክክለኛውን የአዋሽ ባንክ ሂሳብ ቁጥርህን ብቻ አስገባ እንጂ ሌላ ነገር እንደ ፍደል እና ስርዓተ ነጥብ አትጻፍ!"

    elif method in ["Telebirr", "CBE Birr"]:
        if (text.isdigit() and len(text) == 10 and text.startswith("09")) or \
           (text.startswith("+251") and len(text) == 13):
            is_valid = True
        else:
            error_msg = "⚠️️Please enter only the correct your phone number\n━━━━━━━━━━━━━━━━━━━━━━━\nእባክህ ትክክለኛው ስልክ ቁጥርህን ብቻ አስገባ እንጂ ሌላ ነገር እንደ ፍደል እና ስርዓተ ነጥብ አትጻፍ!"

    if is_valid:
        user_temp[user_id]["acc"] = text
        msg = bot.send_message(message.chat.id, f"Good👍✅ 🤭\n\n🔰 Enter your full name, only the same as with this {method}\n\
━━━━━━━━━━━━━━━━━━━━━━━\n🔰 በዚህ {method} ጋር ተመሳሳይ የሆነ ሙሉ ስምህን ብቻ አስገባ")
        bot.register_next_step_handler(msg, validate_name)
    else:
        msg = bot.send_message(message.chat.id, error_msg)
        bot.register_next_step_handler(msg, validate_acc)

def validate_name(message):
    if check_interrupt(message):
        return

    user_id = message.from_user.id
    name_text = message.text.strip()
    if not re.match(r"^[a-zA-Z\s]+$", name_text):
        msg = bot.send_message(message.chat.id, f"❌Stop✋\n\n🔰 Enter correct the {user_temp[user_id]['method']} full name,with spelling only\n🔰 Writing numbers including punctuation is prohibited⚠️\n━━━━━━━━━━━━━━━━━━━━━━━\n🔰 ትክክለኛውን የ{user_temp[user_id]['method']} ሙሉ ስምህን፣ በፊደል አጻጻፍ ብቻ አስገባ\n🔰እንጂ ሥርዓተ ነጥብን ጨምሮ ቁጥሮች መጻፍ የተከለከለ ነው")
        bot.register_next_step_handler(msg, validate_name)
        return

    user_temp[user_id]["name"] = name_text
    method = user_temp[user_id]["method"]
    acc = user_temp[user_id]["acc"]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Confirm ✅", callback_data="confirm_final"), types.InlineKeyboardButton("Edit ⏳", callback_data=f"w_{method}"))
    bot.send_message(message.chat.id, f"🔰 Check your details👇\n🔰 ያስገባኸውን ዝርዝር አረጋግጥ👇\n━━━━━━━━━━━━━━━━━━━━━━━\n🏦 Bank : {method}\n\n🔢 Account : `{acc}`\n\n👤 Name : {name_text}\n━━━━━━━━━━━━━━━━━━━━━━━\n🔰 Is the name and number you entered is correct? do you trust it❓\n\n🔰 ያስገባኸው ስም እና ቁጥር ትክክል ነው ትተማመንበታለህ አይደል❓", parse_mode="Markdown", reply_markup=markup)

def final_step(message):
    if check_interrupt(message):
        return

    user_id = message.from_user.id
    try:
        amt = float(message.text.strip())

        if amt <= 0:
            msg = bot.send_message(message.chat.id, "🙄⚠️ Zero withdrawal is not allowed 🙅‍♂️\n\n⚠️ እንዴ? 🙄ዜሮ ማዉጣት አይፈቀድም ባክህ🙅‍♂️\n\n 😣🤔😁")
            bot.register_next_step_handler(msg, final_step)
            return

        if amt < 5:
            msg = bot.send_message(message.chat.id, "✋ Minimum Withdraw = 100 birr\n\n🔰 Please send over 100🤝\n🔰 እባክህ ከ100 ብር በላይ ላክ🤝")
            bot.register_next_step_handler(msg, final_step)
            return

        if amt > 1500:
            msg = bot.send_message(message.chat.id, "✋ Maximum Withdraw = 1500 birr\n\n🔰 Please send under 1500🤝\n 🔰 እባክህ ከ1500 ብር በታች ላክ🤝")
            bot.register_next_step_handler(msg, final_step)
            return

        balance_row = users_col.find_one({"user_id": user_id})
        balance = balance_row.get("balance", 0.0) if balance_row else 0

        if balance < amt:
            msg = bot.send_message(message.chat.id, f"❌ Insufficient balance!\n😥 Now you have {int(balance)} birr only\n━━━━━━━━━━━━━━━━━━\n❌ በቂ ያልሆነ ቀሪ ሂሳብ!\n😥 አሁን ያለህ ቀሪ ሂሳብ {int(balance)} ብር ብቻ ነው\n━━━━━━━━━━━━━━━━━━\n🔰 Invite your friends and get other money\n🔰 አሁንም ጓደኛህን በመጋበዝ ሌላ ገንዘብ ስራ")
            bot.register_next_step_handler(msg, final_step)
            return

        user_temp[user_id]["amt"] = amt
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Yes ✅", callback_data="user_request_approve"), types.InlineKeyboardButton("No ❌", callback_data="main_menu"))
        bot.send_message(message.chat.id, f"🔰 Have you decided to spend {int(amt)} birr? \n━━━━━━━━━━━━━━━━━━━━━\n 🔰 {int(amt)} ብር ለማውጣት ወስነሃል?\n\n       Click Yes ✅ or No ❌", reply_markup=markup)
    except Exception:
        bot.send_message(message.chat.id, "⚠️ Please enter valid number only\n⚠️ እባክህ ትክክለኛ ቁጥር ብቻ አስገባ!")
        bot.register_next_step_handler(message, final_step)

# --- TEXT MESSAGE HANDLER ---

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    user_id = message.from_user.id

    m_mode_row = settings_col.find_one({"key": "maintenance"})
    m_mode = m_mode_row.get("value", "OFF") if m_mode_row else "OFF"

    if m_mode == "ON" and user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "🛑 Our bot is currently under maintenance, and we will notify you with this bot when it is back up and running. until then, please be patiently.🤝\n━━━━━━━━━━━━━━━━━━━━━━━\n🛑 ቦታችን በአሁኑ ጊዜ በጥገና ላይ ነውና ወደነበረበት ቦታው ስመለስ ደግሞ በዚሁ ቦት የምናሳዉቃችሁ ሲሆን እስከዛ ድረስ በትግዕስት ጠብቁን🤝")
        return

    if message.text.startswith('/'):
        start_and_commands(message)
        return

    if get_missing_channels(user_id):
        start_and_commands(message)
        return

    if message.text == "💰 Balance":
        balance_row = users_col.find_one({"user_id": user_id})
        balance = balance_row.get("balance", 0.0) if balance_row else 0

        total_refs = users_col.count_documents({"referred_by": user_id})

        profile_text = (
            f"<b>👤 USER PROFILE 👤</b>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"🆔 <b>ID :</b> <code>{user_id}</code>\n\n"
            f"👤 <b>Name :</b> {message.from_user.first_name}\n\n"
            f"💰 <b>Balance :</b> {int(balance)} birr\n\n"
            f"🧑‍🤝‍🧑 <b>Total Referrals :</b> {total_refs}\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"😊 Invite your friends and get other money\n"
            f"😊 አሁንም ጓደኛህን በመጋበዝ ሌላ ገንዘብ ስራ"
        )
        bot.send_message(message.chat.id, profile_text, parse_mode="HTML")

    elif "Bonus" in message.text:
        handle_bonus(message)

    elif message.text == "🧑‍🤝‍🧑 Referral":
        ref_link = f"https://t.me/{(bot.get_me()).username}?start={user_id}"
        bot.send_message(message.chat.id, f"🎁 Hey👋 Invite your friends and earn ETB. You get 10 birr for every person who joins via your link🤭\n━━━━━━━━━━━━━━━━━━━━━━━\n🎁 Hey👋 በመጋበዣ ሊንክህ ብቻ ጓደኞችህን ጋብዝና ብር ስራ:: በሊንክህ በኩል ለተቀላቀሉ ለእያንዳንዱ ሰው 10 ብር ታገኛለህ🤭\n━━━━━━━━━━━━━━━━━━━━━━━\n🔰 Your invitation link is here copy & invite👇\n🔰 ይሄው የመጋበዣ ሊንክህ ደሞ ይህ ነው copy & invite👇\n\n`{ref_link}`", parse_mode="Markdown")

    elif message.text == "📊 Statistics":
        total_users = users_col.count_documents({})

        stats_text = (
            f"━━━━━━━━━━━━━\n"
            f" 📊 Bot Statistics \n"
            f"━━━━━━━━━━━━\n"
            f"👥 Total Users : {total_users} \n"
            f"━━━━━━━━━━━━━\n"
            f"✅ Active & Safe🤭\n"
            f"━━━━━━━━━━━━━━"
        )
        bot.send_message(message.chat.id, stats_text)

    elif message.text == "💳 Withdraw":
        withdraw_start(message)

    elif message.text == "💸 Send Birr":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Yes, Confirm ✅", callback_data="confirm_send"), types.InlineKeyboardButton("No 🛑", callback_data="main_menu"))
        bot.send_message(message.chat.id, "Hey😊Welcome to Send Birr section ✋\n━━━━━━━━━━━━━━━━━━━━━━━\n🔰 Do you send birr for your friends?\n🔰 ለጓደኛህ ብር መላክ ትፈለጋለህ? \n\n✅ Minimum = 2 birr💵\n✅ Maximum = 1000 birr 💵", reply_markup=markup)

# --- SUPPORT CHAT SYSTEM ---

def start_live_chat(message):
    msg = bot.send_message(message.chat.id, "<b>Hey✋ Welcome to Admin chat section</b> 🤭\n<b>━━━━━━━━━━━━━━━━━━━━━━━</b>\n📩 If you have a question or idea, you can talk to the Admin through this page\n\n📩 ጥያቄ ወይም ሀሳብ ካለህ በዚህ በኩል Admin ማዋራት ትችላለህ\n<b>━━━━━━━━━━━━━━━━━━━━━━━</b>\n✅Now send msg for admin.... 🤝", parse_mode="HTML")
    bot.register_next_step_handler(msg, forward_to_admin_complex)

def forward_to_admin_complex(message):
    if check_interrupt(message): return
    u_id = message.from_user.id
    user_link = f'<a href="tg://user?id={u_id}">{message.from_user.first_name}</a>'
    admin_report = (
        f" <b>💬 New msg from user </b>🔔\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"👤 <b>From : </b> {user_link}\n\n"
        f"🆔 <b>User ID : </b> <code>{u_id}</code>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Reply 💬", callback_data=f"reply_{u_id}"))
    bot.send_message(ADMIN_ID, admin_report, parse_mode="HTML")
    bot.copy_message(ADMIN_ID, message.chat.id, message.message_id, reply_markup=markup)
    bot.send_message(message.chat.id, "🔰 Your msg is sent to admin✅ so,wait admin's reply for you\n━━━━━━━━━━━━━━━━━━━━━━━\n🔰 መልእክትህ ወደ Admin ተልኳል✅ ስለዚህ አድሚኑ መልስ እስኪሰጥህ ድረስ በመስመር ላይ ጠብቅ", parse_mode="HTML")

def send_reply_to_user(message, u_id):
    if check_interrupt(message):
        return
    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Reply 💬", callback_data="user_reply_to_admin"))

        bot.copy_message(u_id, message.chat.id, message.message_id, reply_markup=markup)
        bot.send_message(ADMIN_ID, "✅Your msg is sent to user 🤭")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ it has error {e}")

# --- ADMIN TXID LOOKUP ---

def admin_search_txid(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "🔰 This command is it works for admin only😌\n━━━━━━━━━━━━━━━━━━━━━━━\n🔰 ተው😫ይህ Command ለAdmin ብቻ ነው የሚሰራው እንጂ ላንተ አይሰራም።😔")
        return

    args = message.text.split()
    if len(args) < 2:
        bot.send_message(message.chat.id, "⚠️ Usage: `/txid <TXID>`\nExample: `/txid WDSA0I7L`", parse_mode="Markdown")
        return

    txid_to_search = args[1].strip().upper()
    result = transactions_col.find_one({"txid": txid_to_search})

    if result:
        sender = result["sender_id"]
        receiver = result["receiver_id"]
        amount = result["amount"]
        timestamp = result["timestamp"]
        tx_type = result.get("tx_type", "TRANSFER")

        if tx_type == "WITHDRAWAL":
            response = (
                f"🔍 <b>WITHDRAWAL TXID DETAILS</b> 🤭\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🔰 <b>TXID:</b> <code>{txid_to_search}</code>\n\n"
                f"🔰 <b>Type:</b> WITHDRAWAL\n\n"
                f"🔰 <b>Sender/ላኪ:</b> Admin Of The Bot\n\n"
                f"🔰 <b>Receiver/ተቀባይ:</b> <code>{receiver}</code>\n\n"
                f"🔰 <b>Amount/መጠን:</b> <code>{amount}</code> Birr\n\n"
                f"🔰 <b>Date/ቀን:</b> <code>{timestamp}</code>"
            )
        else:
            response = (
                f"🔍 <b>TRANSACTION TXID DETAILS</b> 🤭\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🔰 <b>TXID:</b> <code>{txid_to_search}</code>\n\n"
                f"🔰 <b>Sender/ላኪ:</b> <code>{sender}</code>\n\n"
                f"🔰 <b>Receiver/ተቀባይ:</b> <code>{receiver}</code>\n\n"
                f"🔰 <b>Amount/መጠን:</b> <code>{amount}</code> Birr\n\n"
                f"🔰 <b>Date/ቀን:</b> <code>{timestamp}</code>"
            )
    else:
        response = "❌ Wrong Transaction Number barrier😣"

    bot.send_message(message.chat.id, response, parse_mode="HTML")

# --- ADMIN PANEL & MAINTENANCE ---

@bot.message_handler(commands=['maintenance'])
def maintenance_start(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "🔰 This command is it works for admin only😌\n━━━━━━━━━━━━━━━━━━━━━━━\n🔰 ተው😫ይህ Command ለAdmin ብቻ ነው የሚሰራው እንጂ ላንተ አይሰራም።😔")
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Bot Off 🛑", callback_data="m_off"),
        types.InlineKeyboardButton("Bot On ✅", callback_data="m_on"),
        types.InlineKeyboardButton("🗣️ Broadcast", callback_data="m_broadcast")
    )
    bot.send_message(message.chat.id, "⚙️ Lalo Telebirr Bot Admin Panel ⚙️\n⚙️ የለሎ ቴሌብር ቦት Admin ፓነል ⚙️\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 Choose an action to control the bot status 🤭\n🔰 የቦት ሁኔታን ለመቆጣጠር🤭", reply_markup=markup, parse_mode="HTML")

def maintenance_logic(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Access Denied!")
        return

    if call.data == "m_off":
        settings_col.update_one({"key": "maintenance"}, {"$set": {"value": "ON"}}, upsert=True)
        bot.answer_callback_query(call.id, "Maintenance: ON 🛑")
        msg = ("🔰 Our Telegram bot is under maintenance, so we respectfully ask you to be patient😥🤝\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 የቴሌግራም ቦታችን ጥገና ላይ ስለሆነ በትዕግስት እንድትቆዩ በአክብሮት እየጠየቅን፣ ወደነበረበት ቦታ ስመለስ ደግሞ በዚሁ ቦት የምናሳዉቃችሁ ይሆናል።😥🤝")

        for u in users_col.find({}, {"user_id": 1}):
            try:
                bot.send_message(u["user_id"], msg)
            except Exception:
                pass

    elif call.data == "m_on":
        settings_col.update_one({"key": "maintenance"}, {"$set": {"value": "OFF"}}, upsert=True)
        bot.answer_callback_query(call.id, "Bot is online now✅")
        msg = ("🔰 Our Telegram bot, which was under maintenance, is now back you can use it🤝keep making referrals...🤭\n━━━━━━━━━━━━━━━━━━━━━━\n🔰 ጥገና ላይ የነበረው የቴሌግራም ቦታችን አሁን ወደ ስራ ተመልሷል። መጠቀም ትችላላችሁ🤭\n\nThankyou🤭🙏")

        for u in users_col.find({}, {"user_id": 1}):
            try:
                bot.send_message(u["user_id"], msg)
            except Exception:
                pass

    elif call.data == "m_broadcast":
        bot.answer_callback_query(call.id, "🔰Waiting for message...\n\🔰 መልእክት በመጠበቅ ላይ")
        m = bot.send_message(ADMIN_ID, "🔰 Send the message you want to broadcast 📢\n\n🔰 ማሰራጨት የምትፈልገውን መልእክት ላክልኝ📢\n", parse_mode="HTML")
        bot.register_next_step_handler(m, run_broadcast)

def run_broadcast(message):
    if message.text and message.text.lower() == "cancel":
        bot.send_message(ADMIN_ID, "❌ Broadcast cancelled 😥.")
        return

    users = users_col.find({}, {"user_id": 1})

    count, fail = 0, 0
    for u in users:
        try:
            bot.copy_message(u["user_id"], message.chat.id, message.message_id)
            count += 1
            time.sleep(0.04)
        except Exception:
            fail += 1

    bot.send_message(ADMIN_ID, f"<b>Done</b>✅<b>Broadcast Complete 📢 </b>\n━━━━━━━━━━━━━━━━━━━━━\n✅ Success : {count} \n\n❌ Failed : {fail}", parse_mode="HTML")

# --- STARTUP ---
print("🚀 Lalo Bot Online (MongoDB Connected)!")
bot.infinity_polling()
