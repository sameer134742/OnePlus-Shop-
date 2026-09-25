import sqlite3, secrets, string, logging, asyncio, os, random, re, html
from datetime import datetime, timedelta

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      MessageEntity, BotCommand)
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, filters, ContextTypes)
from telegram.constants import ParseMode
from telegram.error import BadRequest

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ==================== CONFIG ====================
BOT_TOKEN  = "8995307156:AAG3swHLA-Naa8kmkjewCgyLoO4WtFe-AI8"
ADMIN_IDS  = [6900492704]
UPI_ID     = "7505804616@ybl"
QR_PATH    = "qr.png"
SUPPORT    = "@Mrsameer46"

PLANS = {
    "1day":   {"name": "1 Day",   "price": 50,  "days": 1,  "emoji": "⚡"},
    "7day":   {"name": "7 Days",  "price": 499, "days": 7,  "emoji": "🔥"},
    "1month": {"name": "1 Month", "price": 799, "days": 30, "emoji": "💎"},
}

# ==================== ANIMATED EMOJI TOGGLE ====================
USE_ANIMATED_EMOJIS = False   # Safe mode — normal emojis, no crash

# ==================== ANIMATED EMOJI IDs ====================
ANIMATED_EMOJI_IDS = {}

pending = {}
reseller_setup = {}


# ==================== EMOJI HELPERS ====================
def a(text):
    if not text or not USE_ANIMATED_EMOJIS or not ANIMATED_EMOJI_IDS:
        return text
    result = text
    for emoji, eid in ANIMATED_EMOJI_IDS.items():
        result = result.replace(emoji, f'<tg-emoji emoji-id="{eid}">{emoji}</tg-emoji>')
    return result


def strip_animated(text):
    if not text:
        return text
    return re.sub(r'<tg-emoji[^>]*>|</tg-emoji>', '', text)


def e(text):
    return html.escape(str(text)) if text else ""


async def safe_reply(msg, text, **kwargs):
    try:
        return await msg.reply_text(a(text), parse_mode=ParseMode.HTML, **kwargs)
    except BadRequest as ex:
        if "Document_invalid" in str(ex) or "DOCUMENT_INVALID" in str(ex):
            logging.warning("Animated emoji fail — plain fallback")
            return await msg.reply_text(strip_animated(text),
                                        parse_mode=ParseMode.HTML, **kwargs)
        raise


async def safe_send(bot, chat_id, text, **kwargs):
    try:
        return await bot.send_message(chat_id, a(text),
                                      parse_mode=ParseMode.HTML, **kwargs)
    except BadRequest as ex:
        if "Document_invalid" in str(ex) or "DOCUMENT_INVALID" in str(ex):
            logging.warning("Animated emoji fail (send) — plain fallback")
            return await bot.send_message(chat_id, strip_animated(text),
                                          parse_mode=ParseMode.HTML, **kwargs)
        raise


async def safe_photo_msg(msg, photo_bytes, caption="", **kwargs):
    """Photo bytes bhejo — file object nahi"""
    try:
        return await msg.reply_photo(photo_bytes, caption=a(caption),
                                     parse_mode=ParseMode.HTML, **kwargs)
    except BadRequest as ex:
        if "Document_invalid" in str(ex) or "DOCUMENT_INVALID" in str(ex):
            logging.warning("Photo animated fail — plain fallback")
            return await msg.reply_photo(photo_bytes, caption=strip_animated(caption),
                                         parse_mode=ParseMode.HTML, **kwargs)
        raise


async def safe_photo_bot(bot, chat_id, photo_bytes, caption="", **kwargs):
    """Photo bytes bhejo via bot"""
    try:
        return await bot.send_photo(chat_id, photo_bytes, caption=a(caption),
                                    parse_mode=ParseMode.HTML, **kwargs)
    except BadRequest as ex:
        if "Document_invalid" in str(ex) or "DOCUMENT_INVALID" in str(ex):
            logging.warning("Bot photo animated fail — plain fallback")
            return await bot.send_photo(chat_id, photo_bytes, caption=strip_animated(caption),
                                        parse_mode=ParseMode.HTML, **kwargs)
        raise


# ==================== FUN REPLIES ====================
FUN_REPLIES = [
    "😄 Arre bhai, ye koi command nahi hai!\n\n🔑 Key kharidne ke liye /start dabao",
    "🤣 Haha! Ye command maine suna nahi.\n\n💎 /start dabao aur premium key lo",
    "🎯 Bhai, ye to galat command hai!\n\n🚀 /start dabao, keys milengi",
    "😎 Interesting... lekin ye command mujhe nahi aati!\n\n🔥 /start dabao",
    "🙃 Ye kya likh diya bhai?\n\n💎 Sahi rasta: /start",
    "🤖 Beep boop... command samajh nahi aayi!\n\n⚡ /start dabao",
    "😅 Ye command nahi hai, shayad tumne galti se likh diya!\n\n🎉 /start dabao",
    "🎪 Circus chal raha hai yahan!\n\n🔑 Asli kaam: /start",
]

BORED_REPLIES = [
    "😴 Bore ho rahe ho? Chalo keys kharido!",
    "😜 Kuch kaam karo bhai, keys becho!",
    "🤪 Time waste mat karo, /start dabao!",
]


# ==================== DB ====================
def db():
    return sqlite3.connect("bot.db", check_same_thread=False)


def init_db():
    con = db(); c = con.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS keys(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE, plan TEXT, days INTEGER,
        used INTEGER DEFAULT 0, used_by INTEGER,
        activated_at TEXT, expires_at TEXT,
        seller_id INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, plan TEXT, price INTEGER,
        status TEXT DEFAULT 'pending', utr TEXT, created_at TEXT,
        seller_id INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS resellers(
        user_id INTEGER PRIMARY KEY,
        name TEXT, upi_id TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT,
        expires_at TEXT,
        duration_days INTEGER DEFAULT 30)""")
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        referred_by INTEGER DEFAULT 0,
        first_seen TEXT)""")
    con.commit(); con.close()


def gen_key(plan):
    a_ = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    b_ = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"KEY-{plan.upper()}-{a_}-{b_}"


# ==================== HELPERS ====================
def is_reseller(uid):
    con = db(); c = con.cursor()
    c.execute("SELECT user_id, active, expires_at FROM resellers WHERE user_id=?", (uid,))
    r = c.fetchone(); con.close()
    if not r:
        return False
    if not r[1]:
        return False
    if r[2]:
        try:
            if datetime.fromisoformat(r[2]) < datetime.now():
                return False
        except Exception:
            pass
    return True


def get_reseller(uid):
    con = db(); c = con.cursor()
    c.execute("""SELECT user_id, name, upi_id, active, created_at, expires_at, duration_days
                 FROM resellers WHERE user_id=?""", (uid,))
    r = c.fetchone(); con.close()
    return r


def reseller_days_left(uid):
    r = get_reseller(uid)
    if not r or not r[5]:
        return None
    try:
        delta = datetime.fromisoformat(r[5]) - datetime.now()
        return max(0, delta.days), max(0, delta.seconds // 3600)
    except Exception:
        return None


def get_seller_info(seller_id):
    if seller_id == 0 or not seller_id:
        return {"id": 0, "name": "Admin", "upi": UPI_ID, "qr": QR_PATH}
    con = db(); c = con.cursor()
    c.execute("SELECT user_id, name, upi_id FROM resellers WHERE user_id=?", (seller_id,))
    r = c.fetchone(); con.close()
    if not r:
        return {"id": 0, "name": "Admin", "upi": UPI_ID, "qr": QR_PATH}
    qr = f"qr_{r[0]}.png"
    if not os.path.exists(qr):
        qr = None
    return {"id": r[0], "name": r[1], "upi": r[2], "qr": qr}


def get_user_seller(uid):
    con = db(); c = con.cursor()
    c.execute("SELECT referred_by FROM users WHERE user_id=?", (uid,))
    r = c.fetchone(); con.close()
    return r[0] if r else 0


def set_user_seller(uid, seller_id):
    con = db(); c = con.cursor()
    now = datetime.now().isoformat()
    c.execute("""INSERT INTO users(user_id, referred_by, first_seen) VALUES(?,?,?)
                 ON CONFLICT(user_id) DO UPDATE SET referred_by=excluded.referred_by""",
              (uid, seller_id, now))
    con.commit(); con.close()


# ==================== /start ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    r = get_reseller(uid)
    if r:
        if not r[3]:
            await safe_reply(update.message,
                "🚫 <b>Tumhara reseller account band hai.</b>\n\n"
                f"💬 Support: {SUPPORT}")
            return
        days_left = reseller_days_left(uid)
        if days_left is not None and days_left[0] == 0 and days_left[1] == 0:
            await safe_reply(update.message,
                "⏰ <b>Tumhara reseller plan expire ho gaya!</b>\n\n"
                "🔄 Renew karane ke liye admin se baat karo\n"
                f"💬 Support: {SUPPORT}")
            return
        await reseller_dashboard(update, context)
        return

    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                rid = int(arg[4:])
                if rid == 0 or is_reseller(rid) or rid in ADMIN_IDS:
                    set_user_seller(uid, rid)
                    try:
                        target = rid if rid != 0 else ADMIN_IDS[0]
                        await safe_send(context.bot, target,
                            f"🎉 <b>Naya Customer Aaya!</b>\n\n"
                            f"👤 {e(user.full_name)}\n"
                            f"🆔 <code>{uid}</code>\n"
                            f"🔖 @{e(user.username or '—')}")
                    except Exception:
                        pass
            except Exception as ex:
                logging.error(f"Ref err: {ex}")
        elif arg in PLANS:
            await send_payment(update, context, arg)
            return

    seller_id = get_user_seller(uid)
    seller = get_seller_info(seller_id)

    text = (
        f"👋 <b>Namaste {e(user.first_name)}!</b>\n\n"
        "╔══════════════════════════╗\n"
        "  🚀 <b>PREMIUM KEY STORE</b> 🚀\n"
        "╚══════════════════════════╝\n\n"
        "✨ <i>Instant Key Delivery Guaranteed</i>\n"
        "🎯 Neeche se apna plan choose karo\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  💎 <b>AVAILABLE PLANS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "  ⚡ <b>1 Day</b>       ➜  ₹50\n"
        "  🔥 <b>7 Days</b>      ➜  ₹499\n"
        "  💎 <b>1 Month</b>     ➜  ₹799\n"
    )
    if seller["id"] != 0:
        text += f"\n  🏪 Seller: <b>{e(seller['name'])}</b>"

    text += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>"

    kb = [
        [InlineKeyboardButton("⚡ 1 Day — ₹50",    callback_data="plan_1day")],
        [InlineKeyboardButton("🔥 7 Days — ₹499",  callback_data="plan_7day")],
        [InlineKeyboardButton("💎 1 Month — ₹799", callback_data="plan_1month")],
        [InlineKeyboardButton("📞 Support", url=f"https://t.me/{SUPPORT.strip('@')}"),
         InlineKeyboardButton("📖 Help",    callback_data="show_help")],
    ]
    await safe_reply(update.message, text, reply_markup=InlineKeyboardMarkup(kb))


# ==================== RESELLER DASHBOARD ====================
async def reseller_dashboard(update, context):
    uid = update.effective_user.id
    r = get_reseller(uid)
    if not r:
        await update.message.reply_text("Reseller nahi mila.")
        return

    bot_username = context.bot.username
    ref_link = f"https://t.me/{bot_username}?start=ref_{uid}"

    con = db(); c = con.cursor()
    c.execute("SELECT COUNT(*) FROM keys WHERE seller_id=? AND used=0", (uid,))
    stock = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM orders WHERE seller_id=? AND status='pending'", (uid,))
    pend = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM orders WHERE seller_id=? AND status='approved'", (uid,))
    appr = c.fetchone()[0]
    c.execute("SELECT SUM(price) FROM orders WHERE seller_id=? AND status='approved'", (uid,))
    rev = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,))
    customers = c.fetchone()[0]
    con.close()

    qr_status = "✅ Set" if os.path.exists(f"qr_{uid}.png") else "❌ Not set"

    days_left = reseller_days_left(uid)
    if days_left:
        d, h = days_left
        time_str = f"<b>{d} din {h} ghante</b> bache"
        warn = "⚠️ " if d <= 3 else "⏰ "
    else:
        time_str = "<b>Unlimited</b>"
        warn = "♾️ "

    exp_str = r[5][:10] if r[5] else "—"

    text = (
        "╔══════════════════════════╗\n"
        "   🏪 <b>RESELLER DASHBOARD</b>\n"
        "╚══════════════════════════╝\n\n"
        f"👤 Name: <b>{e(r[1])}</b>\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"💳 UPI: <code>{e(r[2])}</code>\n"
        f"🖼️ QR: {qr_status}\n\n"
        f"{warn}Plan Valid Till: <b>{exp_str}</b>\n"
        f"{warn}Time Left: {time_str}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  📊 <b>YOUR STATISTICS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"  👥 Customers   ➜  <b>{customers}</b>\n"
        f"  📦 Stock       ➜  <b>{stock} keys</b>\n"
        f"  ⏳ Pending     ➜  <b>{pend}</b>\n"
        f"  ✅ Approved    ➜  <b>{appr}</b>\n"
        f"  💰 Revenue     ➜  <b>₹{rev}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  🔗 <b>YOUR REFERRAL LINK</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<code>{ref_link}</code>\n\n"
        "☝️ Ye link share karo customers ko!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>"
    )
    kb = [
        [InlineKeyboardButton("🔗 Get Link",  callback_data="res_link"),
         InlineKeyboardButton("📊 Stats",     callback_data="res_stats")],
        [InlineKeyboardButton("🖼️ Set QR",    callback_data="res_setqr"),
         InlineKeyboardButton("💳 Set UPI",   callback_data="res_setupi")],
        [InlineKeyboardButton("📦 Stock",     callback_data="res_stock"),
         InlineKeyboardButton("⏳ Orders",    callback_data="res_orders")],
        [InlineKeyboardButton("📖 Help",      callback_data="res_help")],
    ]
    await safe_reply(update.message, text, reply_markup=InlineKeyboardMarkup(kb))


# ==================== PAYMENT ====================
async def send_payment(update, context, plan_key):
    plan = PLANS[plan_key]
    uid = update.effective_user.id
    seller_id = get_user_seller(uid)
    seller = get_seller_info(seller_id)

    pending[uid] = {"plan": plan_key, "photo": None, "utr": None,
                    "seller_id": seller_id}

    caption = (
        "╔══════════════════════════╗\n"
        f"  {plan['emoji']} <b>{plan['name'].upper()} PLAN</b> {plan['emoji']}\n"
        "╚══════════════════════════╝\n\n"
        f"💰 <b>Amount:</b> ₹{plan['price']}\n"
        f"⏳ <b>Validity:</b> {plan['days']} din\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  📱 <b>PAYMENT STEPS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "  1️⃣ Upar wala QR scan karo\n"
        "  2️⃣ Ya UPI ID pe bhejo:\n"
        f"     <code>{e(seller['upi'])}</code>\n"
        f"  3️⃣ ₹{plan['price']} pay karo\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  📤 <b>AB YE BHEJO</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "  📸 Payment ka <b>screenshot</b>\n"
        "  🧾 <b>UTR / Transaction ID</b>\n\n"
        "⏳ Dono milne par admin verify karke\n"
        "tumhari <b>KEY</b> bhej dega 🔑\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>"
    )
    msg = update.effective_message

    # ✅ QR file ko bytes me read karo (ek baar)
    if seller["qr"] and os.path.exists(seller["qr"]):
        try:
            with open(seller["qr"], "rb") as f:
                photo_bytes = f.read()
            if photo_bytes:
                await safe_photo_msg(msg, photo_bytes, caption=caption)
                return
        except Exception as ex:
            logging.error(f"QR read fail: {ex}")

    # Fallback — text only
    await safe_reply(msg, caption + "\n\n⚠️ <i>QR available nahi, UPI ID use karo</i>")


# ==================== SCREENSHOT ====================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid in reseller_setup and reseller_setup[uid] == "awaiting_qr":
        try:
            file = await update.message.photo[-1].get_file()
            await file.download_to_drive(f"qr_{uid}.png")
            del reseller_setup[uid]
            await safe_reply(update.message,
                "✅ <b>QR set ho gaya!</b>\n\n🖼️ Ab customers ko ye QR dikhega.")
        except Exception as ex:
            logging.error(f"QR save: {ex}")
            await update.message.reply_text("❌ QR save nahi hua. Dobara try karo.")
        return

    if uid not in pending:
        await safe_reply(update.message,
            "⚠️ Pehle /start dabao aur plan choose karo.")
        return

    pending[uid]["photo"] = update.message.photo[-1].file_id
    if pending[uid]["utr"]:
        await create_order(update, context, uid)
    else:
        await safe_reply(update.message,
            "✅ <b>Screenshot mil gaya!</b>\n\n🧾 Ab <b>UTR / Transaction ID</b> bhejo.")


# ==================== TEXT ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if uid in reseller_setup and reseller_setup[uid] == "awaiting_upi":
        if "@" not in text or len(text) < 5:
            await update.message.reply_text(
                "⚠️ Valid UPI bhejo (jaise <code>name@ybl</code>)",
                parse_mode=ParseMode.HTML)
            return
        con = db(); c = con.cursor()
        c.execute("UPDATE resellers SET upi_id=? WHERE user_id=?", (text, uid))
        con.commit(); con.close()
        del reseller_setup[uid]
        await safe_reply(update.message, f"✅ <b>UPI set!</b>\n\n💳 <code>{e(text)}</code>")
        return

    if uid not in pending:
        return
    if len(text) < 6:
        await update.message.reply_text("⚠️ Ye valid UTR nahi lag raha.")
        return

    pending[uid]["utr"] = text
    if pending[uid]["photo"]:
        await create_order(update, context, uid)
    else:
        await safe_reply(update.message,
            "✅ <b>UTR note ho gaya!</b>\n\n📸 Ab screenshot bhejo.")


# ==================== ORDER CREATE ====================
async def create_order(update, context, uid):
    st = pending[uid]
    plan_key = st["plan"]
    plan = PLANS[plan_key]
    seller_id = st["seller_id"]
    user = update.effective_user

    con = db(); c = con.cursor()
    c.execute("""INSERT INTO orders(user_id, username, plan, price, status, utr, created_at, seller_id)
                 VALUES(?,?,?,?,?,?,?,?)""",
              (uid, user.username or "", plan_key, plan["price"],
               "pending", st["utr"], datetime.now().isoformat(), seller_id))
    oid = c.lastrowid
    con.commit(); con.close()
    del pending[uid]

    await safe_reply(update.message,
        f"⏳ <b>Order #{oid} Submit Ho Gaya!</b>\n\n"
        f"📦 Plan: <b>{plan['name']}</b>\n"
        f"💰 Amount: <b>₹{plan['price']}</b>\n"
        f"🧾 UTR: <code>{e(st['utr'])}</code>\n\n"
        "🔔 Admin verify karke key bhejega...\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>")

    caption = (
        f"🔔 <b>NAYA ORDER #{oid}</b>\n\n"
        f"👤 {e(user.full_name)}\n"
        f"🔖 @{e(user.username or '—')}\n"
        f"🆔 <code>{uid}</code>\n\n"
        f"📦 Plan: <b>{plan['name']}</b>\n"
        f"💰 Price: <b>₹{plan['price']}</b>\n"
        f"🧾 UTR: <code>{e(st['utr'])}</code>\n\n"
        "👇 Verify karke decide karo:"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"ok_{oid}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"no_{oid}")
    ]])

    recipients = ADMIN_IDS if seller_id == 0 else [seller_id]
    for rec in recipients:
        try:
            # Screenshot file_id — direct bhej sakte hain
            await safe_photo_bot(context.bot, rec, st["photo"],
                                 caption=caption, reply_markup=kb)
        except Exception as ex:
            logging.error(f"Notify {rec}: {ex}")


# ==================== CALLBACKS ====================
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    uid = q.from_user.id

    if data in ("show_help", "res_help"):
        await q.answer()
        await safe_reply(q.message, help_text(uid, reseller=is_reseller(uid)))
        return

    if data == "res_link":
        await q.answer()
        link = f"https://t.me/{context.bot.username}?start=ref_{uid}"
        await safe_reply(q.message,
            f"🔗 <b>YOUR REFERRAL LINK</b>\n\n<code>{link}</code>\n\n☝️ Share karo!")
        return

    if data == "res_setqr":
        await q.answer()
        reseller_setup[uid] = "awaiting_qr"
        await safe_reply(q.message, "🖼️ <b>QR Setup</b>\n\nAb QR image bhejo 👇")
        return

    if data == "res_setupi":
        await q.answer()
        reseller_setup[uid] = "awaiting_upi"
        await safe_reply(q.message,
            "💳 <b>UPI Setup</b>\n\nUPI ID bhejo (jaise <code>name@ybl</code>) 👇")
        return

    if data == "res_stock":
        await q.answer()
        con = db(); c = con.cursor()
        txt = "📦 <b>YOUR STOCK</b>\n\n"
        total = 0
        for p in PLANS:
            c.execute("SELECT COUNT(*) FROM keys WHERE plan=? AND used=0 AND seller_id=?",
                      (p, uid))
            n = c.fetchone()[0]; total += n
            txt += f"{PLANS[p]['emoji']} {PLANS[p]['name']}: <b>{n}</b> keys\n"
        con.close()
        txt += f"\n📊 Total: <b>{total}</b> keys\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>"
        await safe_reply(q.message, txt)
        return

    if data == "res_orders":
        await q.answer()
        con = db(); c = con.cursor()
        c.execute("""SELECT id, user_id, plan, utr FROM orders
                     WHERE status='pending' AND seller_id=? ORDER BY id""", (uid,))
        rows = c.fetchall(); con.close()
        if not rows:
            await safe_reply(q.message, "✅ Koi pending order nahi!")
            return
        txt = "⏳ <b>YOUR PENDING ORDERS</b>\n\n"
        for r in rows:
            txt += f"🔔 #{r[0]} | {PLANS.get(r[2],{}).get('name',r[2])} | <code>{r[1]}</code> | UTR <code>{e(r[3])}</code>\n"
        txt += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>"
        await safe_reply(q.message, txt)
        return

    if data == "res_stats":
        await q.answer()
        con = db(); c = con.cursor()
        c.execute("SELECT COUNT(*) FROM orders WHERE seller_id=? AND status='approved'", (uid,))
        a_ = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM orders WHERE seller_id=? AND status='pending'", (uid,))
        p_ = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM orders WHERE seller_id=? AND status='rejected'", (uid,))
        r_ = c.fetchone()[0]
        c.execute("SELECT SUM(price) FROM orders WHERE seller_id=? AND status='approved'", (uid,))
        rev = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,))
        cust = c.fetchone()[0]
        con.close()
        days_left = reseller_days_left(uid)
        time_line = ""
        if days_left:
            d, h = days_left
            time_line = f"⏰ Plan Time: <b>{d}d {h}h</b>\n"
        await safe_reply(q.message,
            f"📊 <b>YOUR STATISTICS</b>\n\n"
            f"👥 Customers: <b>{cust}</b>\n"
            f"✅ Approved: <b>{a_}</b>\n"
            f"⏳ Pending: <b>{p_}</b>\n"
            f"❌ Rejected: <b>{r_}</b>\n"
            f"💰 Revenue: <b>₹{rev}</b>\n\n"
            f"{time_line}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>")
        return

    if data.startswith("plan_"):
        pk = data.split("_", 1)[1]
        if pk in PLANS:
            await q.answer()
            await send_payment(update, context, pk)
        return

    if data.startswith(("ok_", "no_")):
        action, oid = data.split("_")
        oid = int(oid)

        con = db(); c = con.cursor()
        c.execute("SELECT user_id, plan, status, seller_id FROM orders WHERE id=?", (oid,))
        row = c.fetchone()
        if not row:
            await q.answer("Order nahi mila", show_alert=True); con.close(); return
        user_id, plan_key, status, seller_id = row

        if uid not in ADMIN_IDS and uid != seller_id:
            await q.answer("Tum is order ke owner nahi ho!", show_alert=True)
            con.close(); return
        if status != "pending":
            await q.answer("Already handled", show_alert=True); con.close(); return

        if action == "ok":
            c.execute("""SELECT id, key, days FROM keys
                         WHERE plan=? AND used=0 AND seller_id=? LIMIT 1""",
                      (plan_key, seller_id))
            k = c.fetchone()
            if not k:
                await q.answer(
                    f"❌ Tumhare stock me {plan_key} ki key nahi hai!\n"
                    f"/addkeys ya /genkeys chalao.",
                    show_alert=True)
                con.close(); return

            key_id, key, days = k
            now = datetime.now()
            exp = now + timedelta(days=days)
            c.execute("""UPDATE keys SET used=1, used_by=?, activated_at=?, expires_at=?
                         WHERE id=?""",
                      (user_id, now.isoformat(), exp.isoformat(), key_id))
            c.execute("UPDATE orders SET status='approved' WHERE id=?", (oid,))
            con.commit(); con.close()

            plan = PLANS[plan_key]
            try:
                await safe_send(context.bot, user_id,
                    f"🎉 <b>PAYMENT VERIFIED!</b> 🎉\n\n"
                    "╔══════════════════════════╗\n"
                    f"  {plan['emoji']} <b>YOUR KEY</b> {plan['emoji']}\n"
                    "╚══════════════════════════╝\n\n"
                    f"🔑 <code>{key}</code>\n\n"
                    f"📦 Plan: <b>{plan['name']}</b>\n"
                    f"⏳ Validity: <b>{days} din</b>\n"
                    f"📅 Expiry: <b>{exp.strftime('%d-%m-%Y')}</b>\n\n"
                    f"🚀 Enjoy karo!\n💬 Support: {SUPPORT}\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>")
            except Exception as ex:
                logging.error(f"Key send: {ex}")

            try:
                await q.edit_message_caption(
                    caption=(q.message.caption or "") + "\n\n✅ <b>APPROVED</b>",
                    parse_mode=ParseMode.HTML, reply_markup=None)
            except Exception:
                pass
            await q.answer("Key bhej di ✅")

        else:
            c.execute("UPDATE orders SET status='rejected' WHERE id=?", (oid,))
            con.commit(); con.close()
            try:
                await safe_send(context.bot, user_id,
                    "❌ <b>Payment Verify Nahi Hua</b>\n\n"
                    "Sahi screenshot + UTR ke saath dobara try karo\n"
                    f"💬 Support: {SUPPORT}")
            except Exception:
                pass
            try:
                await q.edit_message_caption(
                    caption=(q.message.caption or "") + "\n\n❌ <b>REJECTED</b>",
                    parse_mode=ParseMode.HTML, reply_markup=None)
            except Exception:
                pass
            await q.answer("Reject kar diya")


# ==================== HELP ====================
def help_text(uid, reseller=False):
    text = (
        "📖 <b>COMMAND LIST</b>\n"
        "═══════════════════════════\n\n"
        "👤 <b>USER COMMANDS</b>\n"
        "├ /start — Welcome\n"
        "├ /help — Ye list\n"
        "├ /id — Apni ID\n"
        "└ /myorders — Orders\n"
    )
    if uid in ADMIN_IDS:
        text += (
            "\n👑 <b>ADMIN COMMANDS</b>\n"
            "├ /addreseller <code>&lt;uid&gt; &lt;name&gt; &lt;upi&gt; &lt;days&gt;</code>\n"
            "├ /extendreseller <code>&lt;uid&gt; &lt;days&gt;</code>\n"
            "├ /resellerinfo <code>&lt;uid&gt;</code>\n"
            "├ /removereseller <code>&lt;uid&gt;</code>\n"
            "├ /resellers — Sabki list\n"
            "├ /addkeys <code>&lt;plan&gt; &lt;k1,k2&gt;</code>\n"
            "├ /genkeys <code>&lt;plan&gt; &lt;count&gt;</code>\n"
            "├ /stock — Stock\n"
            "├ /orders — Pending\n"
            "├ /stats — Overall stats\n"
            "└ /broadcast <code>&lt;msg&gt;</code>\n"
        )
    if reseller:
        text += (
            "\n🏪 <b>RESELLER COMMANDS</b>\n"
            "├ /myinfo — Apni info + time\n"
            "├ /ref — Referral link\n"
            "├ /setqr — QR change\n"
            "├ /setupi <code>&lt;upi&gt;</code> — UPI change\n"
            "├ /addkeys <code>&lt;plan&gt; &lt;k1,k2&gt;</code>\n"
            "├ /genkeys <code>&lt;plan&gt; &lt;count&gt;</code>\n"
            "├ /stock — Apna stock\n"
            "├ /orders — Apne orders\n"
            "└ /stats — Apni sales\n"
        )
    text += f"\n═══════════════════════════\n💬 Support: {SUPPORT}\n\n✨ <i>Powered by OnePlus Store</i>"
    return text


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await safe_reply(update.message, help_text(uid, reseller=is_reseller(uid)))


async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    extra = ""
    if is_reseller(u.id):
        extra = "\n🏪 Status: <b>RESELLER</b>"
    elif get_user_seller(u.id) > 0:
        r = get_reseller(get_user_seller(u.id))
        extra = f"\n🏪 Seller: <b>{e(r[1]) if r else '—'}</b>"
    await safe_reply(update.message,
        f"🆔 <b>Tumhari Details</b>\n\n"
        f"👤 {e(u.full_name)}\n"
        f"🔖 @{e(u.username or '—')}\n"
        f"🆔 <code>{u.id}</code>{extra}")


async def myorders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    con = db(); c = con.cursor()
    c.execute("""SELECT id, plan, status FROM orders
                 WHERE user_id=? ORDER BY id DESC LIMIT 10""", (uid,))
    rows = c.fetchall(); con.close()
    if not rows:
        await safe_reply(update.message, "📭 Koi order nahi."); return
    emoji_map = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
    txt = "📋 <b>Tumhare Orders</b>\n\n"
    for r in rows:
        txt += f"{emoji_map.get(r[2],'❔')} #{r[0]} — {PLANS.get(r[1],{}).get('name',r[1])} — <b>{r[2].upper()}</b>\n"
    txt += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>"
    await safe_reply(update.message, txt)


async def ref_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_reseller(uid):
        await update.message.reply_text("Sirf resellers ke liye."); return
    link = f"https://t.me/{context.bot.username}?start=ref_{uid}"
    await safe_reply(update.message,
        f"🔗 <b>YOUR REFERRAL LINK</b>\n\n<code>{link}</code>\n\n☝️ Share karo!")


async def setqr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_reseller(uid): return
    reseller_setup[uid] = "awaiting_qr"
    await safe_reply(update.message, "🖼️ Ab apna naya QR bhejo 👇")


async def setupi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_reseller(uid): return
    if not context.args:
        reseller_setup[uid] = "awaiting_upi"
        await safe_reply(update.message, "💳 UPI ID bhejo (jaise <code>name@ybl</code>)")
        return
    upi = context.args[0]
    if "@" not in upi:
        await update.message.reply_text("❌ Invalid UPI"); return
    con = db(); c = con.cursor()
    c.execute("UPDATE resellers SET upi_id=? WHERE user_id=?", (upi, uid))
    con.commit(); con.close()
    await safe_reply(update.message, f"✅ UPI set: <code>{e(upi)}</code>")


async def myinfo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_reseller(uid) and uid not in ADMIN_IDS:
        await update.message.reply_text("Sirf resellers ke liye."); return
    if uid in ADMIN_IDS and not get_reseller(uid):
        await safe_reply(update.message, "👑 Tum Admin ho."); return

    r = get_reseller(uid)
    if not r:
        await update.message.reply_text("Reseller nahi mila."); return

    link = f"https://t.me/{context.bot.username}?start=ref_{uid}"
    qr_status = "✅ Set" if os.path.exists(f"qr_{uid}.png") else "❌ Not set"
    days_left = reseller_days_left(uid)
    if days_left:
        d, h = days_left
        time_line = f"⏰ Time Left: <b>{d} din {h} ghante</b>"
        exp_line = f"📅 Expires: <b>{r[5][:10]}</b>"
    else:
        time_line = "♾️ Unlimited"
        exp_line = ""

    await safe_reply(update.message,
        f"🏪 <b>My Info</b>\n\n"
        f"👤 Name: <b>{e(r[1])}</b>\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"💳 UPI: <code>{e(r[2])}</code>\n"
        f"🖼️ QR: {qr_status}\n\n"
        f"{exp_line}\n{time_line}\n\n"
        f"🔗 Link: <code>{link}</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>")


# ==================== ADMIN COMMANDS ====================
async def addreseller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if len(context.args) < 4:
        await safe_reply(update.message,
            "📝 <b>Use:</b> <code>/addreseller &lt;user_id&gt; &lt;name&gt; &lt;upi&gt; &lt;days&gt;</code>\n\n"
            "Example:\n<code>/addreseller 123456789 Rahul rahul@ybl 30</code>\n\n"
            "Days = kitne din ke liye reseller banega\n"
            "(30 = 1 month, 60 = 2 months, 365 = 1 year)")
        return
    try:
        rid = int(context.args[0])
        name = context.args[1]
        upi = context.args[2]
        days = int(context.args[3])
        assert "@" in upi and days > 0
    except Exception:
        await update.message.reply_text("❌ Invalid input. Format check karo.")
        return

    expires = (datetime.now() + timedelta(days=days)).isoformat()

    con = db(); c = con.cursor()
    try:
        c.execute("""INSERT INTO resellers(user_id, name, upi_id, active, created_at, expires_at, duration_days)
                     VALUES(?,?,?,1,?,?,?)""",
                  (rid, name, upi, datetime.now().isoformat(), expires, days))
        con.commit()
    except sqlite3.IntegrityError:
        con.close()
        await update.message.reply_text("⚠️ Ye user already reseller hai. /extendreseller use karo.")
        return
    con.close()

    await safe_reply(update.message,
        f"✅ <b>Reseller Added!</b>\n\n"
        f"👤 Name: <b>{e(name)}</b>\n"
        f"🆔 ID: <code>{rid}</code>\n"
        f"💳 UPI: <code>{e(upi)}</code>\n"
        f"⏰ Duration: <b>{days} din</b>\n"
        f"📅 Expires: <b>{expires[:10]}</b>\n\n"
        "Ab unhe bolo /start dabaye.")

    try:
        await safe_send(context.bot, rid,
            f"🎉 <b>Congratulations!</b>\n\n"
            f"Tum ab <b>RESELLER</b> ho is bot par!\n\n"
            f"⏰ Duration: <b>{days} din</b>\n"
            f"📅 Expires: <b>{expires[:10]}</b>\n\n"
            "Setup karo:\n"
            "1️⃣ /setqr — apna QR\n"
            "2️⃣ /setupi — apni UPI\n"
            "3️⃣ /ref — referral link\n"
            "4️⃣ /genkeys — keys banao\n\n"
            "📖 /help — full commands")
    except Exception:
        pass


async def extendreseller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if len(context.args) < 2:
        await safe_reply(update.message,
            "📝 <b>Use:</b> <code>/extendreseller &lt;uid&gt; &lt;days&gt;</code>\n\n"
            "Example: <code>/extendreseller 123456789 30</code>")
        return
    try:
        rid = int(context.args[0])
        days = int(context.args[1])
        assert days > 0
    except Exception:
        await update.message.reply_text("❌ Invalid"); return

    r = get_reseller(rid)
    if not r:
        await update.message.reply_text("Reseller nahi mila."); return

    try:
        current = datetime.fromisoformat(r[5]) if r[5] else datetime.now()
        if current < datetime.now():
            current = datetime.now()
    except Exception:
        current = datetime.now()

    new_exp = current + timedelta(days=days)
    total = (r[6] or 0) + days

    con = db(); c = con.cursor()
    c.execute("""UPDATE resellers SET expires_at=?, duration_days=?, active=1
                 WHERE user_id=?""", (new_exp.isoformat(), total, rid))
    con.commit(); con.close()

    await safe_reply(update.message,
        f"✅ <b>Extended!</b>\n\n"
        f"👤 <code>{rid}</code>\n"
        f"➕ Added: <b>{days} din</b>\n"
        f"📅 New Expiry: <b>{new_exp.strftime('%Y-%m-%d')}</b>")

    try:
        await safe_send(context.bot, rid,
            f"🎉 <b>Plan Extended!</b>\n\n"
            f"➕ <b>{days} din</b> add ho gaye\n"
            f"📅 New Expiry: <b>{new_exp.strftime('%Y-%m-%d')}</b>")
    except Exception:
        pass


async def resellerinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await safe_reply(update.message, "Use: <code>/resellerinfo &lt;uid&gt;</code>")
        return
    try:
        rid = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ Invalid ID"); return

    r = get_reseller(rid)
    if not r:
        await update.message.reply_text("Reseller nahi mila."); return

    con = db(); c = con.cursor()
    c.execute("SELECT COUNT(*) FROM keys WHERE seller_id=? AND used=0", (rid,))
    stock = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM orders WHERE seller_id=? AND status='approved'", (rid,))
    appr = c.fetchone()[0]
    c.execute("SELECT SUM(price) FROM orders WHERE seller_id=? AND status='approved'", (rid,))
    rev = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (rid,))
    cust = c.fetchone()[0]
    con.close()

    days_left = reseller_days_left(rid)
    if days_left:
        d, h = days_left
        time_line = f"⏰ Left: <b>{d}d {h}h</b>"
        status = "🟢 Active" if d > 0 or h > 0 else "🔴 Expired"
    else:
        time_line = "♾️ Unlimited"
        status = "🟢 Active"

    await safe_reply(update.message,
        f"🏪 <b>RESELLER INFO</b>\n\n"
        f"👤 Name: <b>{e(r[1])}</b>\n"
        f"🆔 ID: <code>{rid}</code>\n"
        f"💳 UPI: <code>{e(r[2])}</code>\n"
        f"📊 Status: {status}\n"
        f"📅 Expires: <b>{r[5][:10] if r[5] else '—'}</b>\n"
        f"{time_line}\n\n"
        f"👥 Customers: <b>{cust}</b>\n"
        f"📦 Stock: <b>{stock}</b>\n"
        f"✅ Approved: <b>{appr}</b>\n"
        f"💰 Revenue: <b>₹{rev}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>")


async def removereseller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await safe_reply(update.message, "Use: <code>/removereseller &lt;uid&gt;</code>")
        return
    try:
        rid = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ Invalid"); return
    con = db(); c = con.cursor()
    c.execute("DELETE FROM resellers WHERE user_id=?", (rid,))
    con.commit(); con.close()
    await safe_reply(update.message, f"✅ Reseller <code>{rid}</code> hata diya.")
    try:
        await context.bot.send_message(rid, "🚫 Tumhara reseller account band kar diya gaya.")
    except Exception:
        pass


async def resellers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    con = db(); c = con.cursor()
    c.execute("""SELECT user_id, name, upi_id, active, expires_at
                 FROM resellers ORDER BY created_at""")
    rows = c.fetchall(); con.close()
    if not rows:
        await update.message.reply_text("Koi reseller nahi."); return

    txt = "🏪 <b>ALL RESELLERS</b>\n\n"
    for r in rows:
        rid = r[0]
        d = reseller_days_left(rid)
        if d and (d[0] > 0 or d[1] > 0):
            st = f"🟢 {d[0]}d left"
        elif d:
            st = "🔴 Expired"
        else:
            st = "♾️"
        act = "" if r[3] else " (inactive)"
        txt += f"• <code>{rid}</code> — <b>{e(r[1])}</b>{act}\n  💳 <code>{e(r[2])}</code>\n  {st}\n\n"
    txt += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>"
    await safe_reply(update.message, txt)


# ==================== KEYS / STOCK / ORDERS / STATS ====================
async def addkeys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    is_admin = uid in ADMIN_IDS
    is_res = is_reseller(uid)
    if not is_admin and not is_res: return

    if len(context.args) < 2:
        await safe_reply(update.message, "📝 <code>/addkeys 1day KEY1,KEY2,KEY3</code>")
        return
    pk = context.args[0].lower()
    if pk not in PLANS:
        await update.message.reply_text("Plans: " + ", ".join(PLANS)); return

    keys = [k.strip() for k in " ".join(context.args[1:]).split(",") if k.strip()]
    seller_id = 0 if is_admin else uid
    con = db(); c = con.cursor(); added = 0
    for k in keys:
        try:
            c.execute("""INSERT INTO keys(key, plan, days, seller_id)
                         VALUES(?,?,?,?)""",
                      (k, pk, PLANS[pk]["days"], seller_id))
            added += 1
        except sqlite3.IntegrityError:
            pass
    con.commit(); con.close()
    await safe_reply(update.message,
        f"✅ <b>{added}</b> key(s) add!\n📦 {PLANS[pk]['name']}")


async def genkeys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    is_admin = uid in ADMIN_IDS
    is_res = is_reseller(uid)
    if not is_admin and not is_res: return

    try:
        pk = context.args[0].lower()
        count = int(context.args[1])
        assert pk in PLANS and 1 <= count <= 100
    except Exception:
        await safe_reply(update.message, "Use: <code>/genkeys 1day 10</code>")
        return

    seller_id = 0 if is_admin else uid
    con = db(); c = con.cursor(); made = []
    for _ in range(count):
        for _try in range(5):
            k = gen_key(pk)
            try:
                c.execute("""INSERT INTO keys(key, plan, days, seller_id)
                             VALUES(?,?,?,?)""",
                          (k, pk, PLANS[pk]["days"], seller_id))
                made.append(k); break
            except sqlite3.IntegrityError:
                continue
    con.commit(); con.close()
    await safe_reply(update.message,
        f"✅ <b>{len(made)}</b> keys generated!\n\n<code>" + "</code>\n<code>".join(made) + "</code>")


async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    is_admin = uid in ADMIN_IDS
    is_res = is_reseller(uid)
    if not is_admin and not is_res: return

    seller_id = 0 if is_admin else uid
    con = db(); c = con.cursor()
    txt = "📦 <b>STOCK</b>\n\n"
    total = 0
    for p in PLANS:
        c.execute("SELECT COUNT(*) FROM keys WHERE plan=? AND used=0 AND seller_id=?",
                  (p, seller_id))
        n = c.fetchone()[0]; total += n
        txt += f"{PLANS[p]['emoji']} {PLANS[p]['name']}: <b>{n}</b> keys\n"
    con.close()
    txt += f"\n📊 Total: <b>{total}</b> keys\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>"
    await safe_reply(update.message, txt)


async def orders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    is_admin = uid in ADMIN_IDS
    is_res = is_reseller(uid)
    if not is_admin and not is_res: return

    con = db(); c = con.cursor()
    if is_admin:
        c.execute("""SELECT id, user_id, plan, utr, seller_id FROM orders
                     WHERE status='pending' ORDER BY id""")
    else:
        c.execute("""SELECT id, user_id, plan, utr, seller_id FROM orders
                     WHERE status='pending' AND seller_id=? ORDER BY id""", (uid,))
    rows = c.fetchall(); con.close()
    if not rows:
        await safe_reply(update.message, "✅ Koi pending order nahi!")
        return
    txt = "⏳ <b>PENDING ORDERS</b>\n\n"
    for r in rows:
        seller_tag = f" (seller: <code>{r[4]}</code>)" if r[4] != 0 else ""
        txt += f"🔔 #{r[0]} | {PLANS.get(r[2],{}).get('name',r[2])} | <code>{r[1]}</code>{seller_tag}\n"
    txt += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>"
    await safe_reply(update.message, txt)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    is_admin = uid in ADMIN_IDS
    is_res = is_reseller(uid)
    if not is_admin and not is_res: return

    con = db(); c = con.cursor()
    if is_admin:
        base = ""
        params = ()
    else:
        base = "WHERE seller_id=?"
        params = (uid,)

    sep = "AND" if base else "WHERE"
    c.execute(f"SELECT COUNT(*) FROM orders {base} {sep} status='approved'", params)
    a_ = c.fetchone()[0]
    c.execute(f"SELECT COUNT(*) FROM orders {base} {sep} status='pending'", params)
    p_ = c.fetchone()[0]
    c.execute(f"SELECT COUNT(*) FROM orders {base} {sep} status='rejected'", params)
    r_ = c.fetchone()[0]
    c.execute(f"SELECT SUM(price) FROM orders {base} {sep} status='approved'", params)
    rev = c.fetchone()[0] or 0
    con.close()

    title = "BOT STATISTICS" if is_admin else "YOUR STATISTICS"
    await safe_reply(update.message,
        f"📊 <b>{title}</b>\n\n"
        f"✅ Approved: <b>{a_}</b>\n"
        f"⏳ Pending:  <b>{p_}</b>\n"
        f"❌ Rejected: <b>{r_}</b>\n\n"
        f"💰 Revenue: <b>₹{rev}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Powered by OnePlus Store</i>")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await safe_reply(update.message, "Use: <code>/broadcast Your message</code>")
        return
    msg = " ".join(context.args)
    con = db(); c = con.cursor()
    c.execute("SELECT DISTINCT user_id FROM orders")
    users = [r[0] for r in c.fetchall()]
    con.close()
    sent = 0
    for u in users:
        try:
            await safe_send(context.bot, u, f"📢 <b>ANNOUNCEMENT</b>\n\n{e(msg)}")
            sent += 1
        except Exception:
            pass
    await safe_reply(update.message, f"✅ Bhej diya <b>{sent}</b> users ko.")


# ==================== UNKNOWN HANDLERS ====================
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fun = random.choice(FUN_REPLIES)
    await safe_reply(update.message, fun)


async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in pending or uid in reseller_setup:
        return
    fun = random.choice(FUN_REPLIES + BORED_REPLIES)
    await safe_reply(update.message, fun)


# ==================== POST INIT ====================
async def post_init(app):
    me = await app.bot.get_me()
    print(f"✅ Bot: @{me.username}")
    print(f"👑 Admin: {ADMIN_IDS}")
    print(f"🎬 Animated Emojis: {'ON' if USE_ANIMATED_EMOJIS else 'OFF (safe mode)'}")
    try:
        await app.bot.set_my_commands([
            BotCommand("start",    "🚀 Bot shuru karo"),
            BotCommand("help",     "📖 Command list"),
            BotCommand("id",       "🆔 Apni Telegram ID"),
            BotCommand("myorders", "📋 Apne orders"),
            BotCommand("ref",      "🔗 Referral link (reseller)"),
            BotCommand("stock",    "📦 Stock check"),
            BotCommand("orders",   "⏳ Pending orders"),
            BotCommand("stats",    "📊 Statistics"),
            BotCommand("myinfo",   "🏪 Reseller info"),
        ])
    except Exception as ex:
        logging.error(f"Set commands: {ex}")


# ==================== MAIN ====================
def main():
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    init_db()
    app = (Application.builder().token(BOT_TOKEN).post_init(post_init).build())

    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("help",      help_cmd))
    app.add_handler(CommandHandler("id",        id_cmd))
    app.add_handler(CommandHandler("myorders",  myorders_cmd))
    app.add_handler(CommandHandler("myinfo",    myinfo_cmd))
    app.add_handler(CommandHandler("ref",       ref_cmd))
    app.add_handler(CommandHandler("setqr",     setqr_cmd))
    app.add_handler(CommandHandler("setupi",    setupi_cmd))
    app.add_handler(CommandHandler("addreseller",     addreseller))
    app.add_handler(CommandHandler("extendreseller",  extendreseller))
    app.add_handler(CommandHandler("resellerinfo",    resellerinfo))
    app.add_handler(CommandHandler("removereseller",  removereseller))
    app.add_handler(CommandHandler("resellers",       resellers_cmd))
    app.add_handler(CommandHandler("addkeys",   addkeys))
    app.add_handler(CommandHandler("genkeys",   genkeys))
    app.add_handler(CommandHandler("stock",     stock))
    app.add_handler(CommandHandler("orders",    orders_cmd))
    app.add_handler(CommandHandler("stats",     stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    print("🤖 Bot chal raha hai... (Ctrl+C to stop)")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
