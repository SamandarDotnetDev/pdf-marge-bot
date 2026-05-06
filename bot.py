import os
import math
import zipfile
import fitz
import sqlite3
import shutil
from datetime import datetime, timedelta
from PIL import Image
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message
)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
CLICK_CARD = os.getenv("CLICK_CARD", "0000 0000 0000 0000")  # Click karta raqami
SUBSCRIPTION_PRICE = os.getenv("SUBSCRIPTION_PRICE", "20000")  # so'm
FREE_LIMIT = 3  # bepul merge soni

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise ValueError("Environment variables are missing")

API_ID = int(API_ID)

app = Client(
    "pdf_zip_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ─── DATABASE ────────────────────────────────────────────────
DB = "subscriptions.db"

def get_conn():
    return sqlite3.connect(DB)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            free_count INTEGER DEFAULT 0,
            subscribed_until TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            status TEXT DEFAULT 'pending',
            photo_file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            days INTEGER DEFAULT 30,
            max_uses INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS promo_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            code TEXT,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_user(user_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row

def ensure_user(user_id, username, first_name, last_name=""):
    full_name = f"{first_name} {last_name}".strip()
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
        (user_id, username, full_name)
    )
    conn.commit()
    conn.close()

def is_subscribed(user_id):
    conn = get_conn()
    row = conn.execute("SELECT subscribed_until FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not row or not row[0]:
        return False
    return datetime.fromisoformat(row[0]) > datetime.now()

def get_free_count(user_id):
    conn = get_conn()
    row = conn.execute("SELECT free_count FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else 0

def increment_free_count(user_id):
    conn = get_conn()
    conn.execute("UPDATE users SET free_count = free_count + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def activate_subscription(user_id, days=30):
    until = datetime.now() + timedelta(days=days)
    conn = get_conn()
    conn.execute("UPDATE users SET subscribed_until=? WHERE user_id=?", (until.isoformat(), user_id))
    conn.commit()
    conn.close()
    return until

def add_payment(user_id, photo_file_id):
    conn = get_conn()
    conn.execute(
        "INSERT INTO payments (user_id, photo_file_id) VALUES (?, ?)",
        (user_id, photo_file_id)
    )
    payment_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return payment_id

def update_payment_status(payment_id, status):
    conn = get_conn()
    conn.execute("UPDATE payments SET status=? WHERE id=?", (status, payment_id))
    conn.commit()
    conn.close()

def create_promo(code, days=30, max_uses=1):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO promo_codes (code, days, max_uses) VALUES (?, ?, ?)",
            (code.upper(), days, max_uses)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False  # kod allaqachon mavjud

def use_promo(user_id, code):
    conn = get_conn()
    code = code.upper().strip()

    # Kod mavjudmi va faolmi
    row = conn.execute(
        "SELECT id, days, max_uses, used_count, is_active FROM promo_codes WHERE code=?",
        (code,)
    ).fetchone()

    if not row:
        conn.close()
        return False, "❌ Bunday promo kod mavjud emas."

    promo_id, days, max_uses, used_count, is_active = row

    if not is_active:
        conn.close()
        return False, "❌ Bu promo kod faol emas."

    if used_count >= max_uses:
        conn.close()
        return False, "❌ Bu promo kodning limiti tugagan."

    # Foydalanuvchi allaqachon ishlatganmi
    already = conn.execute(
        "SELECT id FROM promo_uses WHERE user_id=? AND code=?",
        (user_id, code)
    ).fetchone()

    if already:
        conn.close()
        return False, "❌ Siz bu promo kodni allaqachon ishlatgansiz."

    # Ishlatish
    conn.execute(
        "INSERT INTO promo_uses (user_id, code) VALUES (?, ?)",
        (user_id, code)
    )
    conn.execute(
        "UPDATE promo_codes SET used_count = used_count + 1 WHERE id=?",
        (promo_id,)
    )
    conn.commit()
    conn.close()

    activate_subscription(user_id, days)
    return True, days

def delete_promo(code):
    conn = get_conn()
    conn.execute("UPDATE promo_codes SET is_active=0 WHERE code=?", (code.upper(),))
    conn.commit()
    conn.close()

def list_promos():
    conn = get_conn()
    rows = conn.execute(
        "SELECT code, days, max_uses, used_count, is_active FROM promo_codes ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return rows

def can_use(user_id):
    if is_subscribed(user_id):
        return True, "subscribed"
    free = get_free_count(user_id)
    if free < FREE_LIMIT:
        return True, "free"
    return False, "limit"

# ─── PDF FUNKSIYALAR ─────────────────────────────────────────
def pdf_to_images(pdf_path, scale=2, output_folder="pages"):
    os.makedirs(output_folder, exist_ok=True)
    doc = fitz.open(pdf_path)
    image_paths = []
    for i in range(len(doc)):
        page = doc[i]
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        img_path = os.path.join(output_folder, f"page_{i+1}.jpg")
        pix.save(img_path)
        image_paths.append(img_path)
    return image_paths, len(doc)

def auto_merge_images(images, target_count=20, output_folder="merged"):
    os.makedirs(output_folder, exist_ok=True)
    total_images = len(images)
    base_pages = total_images // target_count
    extra_pages = total_images % target_count
    merged_files = []
    start = 0
    for i in range(target_count):
        pages_in_group = base_pages + (1 if i < extra_pages else 0)
        batch = images[start:start + pages_in_group]
        start += pages_in_group
        pil_images = [Image.open(img) for img in batch]
        width = max(img.width for img in pil_images)
        height = sum(img.height for img in pil_images)
        merged = Image.new("RGB", (width, height))
        y_offset = 0
        for img in pil_images:
            merged.paste(img, (0, y_offset))
            y_offset += img.height
        output_path = os.path.join(output_folder, f"merged_{i+1}.jpg")
        merged.save(output_path, quality=95)
        merged_files.append(output_path)
    return merged_files

def create_zip(images, zip_name="merged_images.zip"):
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zipf:
        for img in images:
            zipf.write(img, os.path.basename(img))
    return zip_name

# ─── STATE ───────────────────────────────────────────────────
user_pdf = {}
user_language = {}
waiting_for_check = {}  # user_id -> True (chek yuborishni kutayapti)

# ─── HELPERS ─────────────────────────────────────────────────
def lang(user_id):
    return user_language.get(user_id, "uz")

def subscription_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 To'lov qildim — chek yuboraman", callback_data="send_check")],
        [InlineKeyboardButton("📊 Holatim", callback_data="my_status")]
    ])

# ─── HANDLERS ────────────────────────────────────────────────
@app.on_message(filters.command("start"))
async def start_command(client, message):
    user_id = message.from_user.id
    ensure_user(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name or "")

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇺🇿 O'zbek", callback_data="lang_uz"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
        ]
    ])
    await message.reply("🌐 Tilni tanlang / Choose language", reply_markup=keyboard)


@app.on_message(filters.command("holat"))
async def status_command(client, message):
    user_id = message.from_user.id
    ensure_user(user_id, message.from_user.username, message.from_user.full_name)
    await send_status(message, user_id)


@app.on_message(filters.command("promo"))
async def promo_command(client, message):
    """Foydalanuvchi promo kod kiritadi: /promo KOD"""
    user_id = message.from_user.id
    ensure_user(user_id, message.from_user.username, message.from_user.full_name)

    parts = message.text.split()
    if len(parts) < 2:
        await message.reply(
            "🎟 Promo kod kiritish uchun:\n"
            "`/promo KODINGIZ`"
        )
        return

    code = parts[1]
    ok, result = use_promo(user_id, code)

    if ok:
        days = result
        conn = get_conn()
        row = conn.execute("SELECT subscribed_until FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        until = datetime.fromisoformat(row[0])
        await message.reply(
            f"🎉 Promo kod qabul qilindi!\n\n"
            f"📅 Obuna muddati: {until.strftime('%d.%m.%Y')}\n"
            f"⏳ {days} kun berildi!"
        )
    else:
        await message.reply(result)
    user_id = message.from_user.id
    await send_subscription_info(message, user_id)


# Admin buyruqlari
@app.on_message(filters.command("foydalanuvchilar") & filters.user(ADMIN_IDS))
async def users_command(client, message):
    conn = get_conn()
    rows = conn.execute("""
        SELECT user_id, full_name, username, free_count, subscribed_until
        FROM users ORDER BY created_at DESC LIMIT 20
    """).fetchall()
    conn.close()

    if not rows:
        await message.reply("Foydalanuvchilar yo'q.")
        return

    text = "👥 **Oxirgi 20 foydalanuvchi:**\n\n"
    for r in rows:
        uid, name, uname, free, until = r
        sub = "✅ Obunachi" if (until and datetime.fromisoformat(until) > datetime.now()) else f"🆓 Bepul: {free}/{FREE_LIMIT}"
        text += f"• {name} (@{uname}) — {sub}\n"

    await message.reply(text)


@app.on_message(filters.command("berobuna") & filters.user(ADMIN_IDS))
async def give_subscription(client, message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("Ishlatish: /berobuna <user_id>")
        return
    try:
        uid = int(parts[1])
        days = int(parts[2]) if len(parts) > 2 else 30
        until = activate_subscription(uid, days)
        await message.reply(f"✅ {uid} ga {days} kunlik obuna berildi.\nMuddati: {until.strftime('%d.%m.%Y')}")
        await app.send_message(uid, f"🎉 Sizga {days} kunlik obuna berildi!\nMuddati: {until.strftime('%d.%m.%Y')}")
    except Exception as e:
        await message.reply(f"Xato: {e}")


async def send_status(message, user_id):
    if is_subscribed(user_id):
        conn = get_conn()
        row = conn.execute("SELECT subscribed_until FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        until = datetime.fromisoformat(row[0])
        days_left = (until - datetime.now()).days
        text = (
            f"✅ **Obuna faol!**\n"
            f"📅 Muddat: {until.strftime('%d.%m.%Y')}\n"
            f"⏳ Qoldi: {days_left} kun"
        )
    else:
        free = get_free_count(user_id)
        remaining = FREE_LIMIT - free
        text = (
            f"🆓 **Bepul limit:** {remaining}/{FREE_LIMIT} ta qoldi\n\n"
            f"Obuna olish uchun /obuna buyrug'ini yuboring."
        )
    await message.reply(text)


async def send_subscription_info(message, user_id):
    text = (
        f"💳 **Oylik obuna — {SUBSCRIPTION_PRICE} so'm**\n\n"
        f"📌 To'lov qilish:\n"
        f"Quyidagi Click kartasiga {SUBSCRIPTION_PRICE} so'm o'tkazing:\n\n"
        f"`{CLICK_CARD}`\n\n"
        f"✅ To'lovdan so'ng chek rasmini shu botga yuboring — admin tasdiqlaydi."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Chek yuboraman", callback_data="send_check")]
    ])
    await message.reply(text, reply_markup=keyboard)


@app.on_message(filters.photo)
async def receive_photo(client, message):
    user_id = message.from_user.id

    if waiting_for_check.get(user_id):
        # Chek rasmi sifatida qabul qilish
        waiting_for_check.pop(user_id, None)
        photo_file_id = message.photo.file_id
        payment_id = add_payment(user_id, photo_file_id)

        await message.reply("⏳ Chekingiz adminga yuborildi. Tez orada tasdiqlanadi!")

        # Adminlarga xabar yuborish
        user = message.from_user
        for admin_id in ADMIN_IDS:
            try:
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve_{payment_id}_{user_id}"),
                        InlineKeyboardButton("❌ Rad etish", callback_data=f"reject_{payment_id}_{user_id}")
                    ]
                ])
                await app.send_photo(
                    admin_id,
                    photo_file_id,
                    caption=(
                        f"💳 **Yangi to'lov cheki**\n\n"
                        f"👤 Ism: {user.full_name}\n"
                        f"🆔 ID: `{user_id}`\n"
                        f"📛 Username: @{user.username}\n"
                        f"🔢 To'lov ID: {payment_id}"
                    ),
                    reply_markup=keyboard
                )
            except Exception:
                pass
    else:
        await message.reply("📄 PDF fayl yuboring yoki /obuna buyrug'ini bosing.")


@app.on_message(filters.document)
async def receive_pdf(client, message):
    user_id = message.from_user.id
    ensure_user(user_id, message.from_user.username, message.from_user.full_name)

    allowed, reason = can_use(user_id)

    if not allowed:
        await message.reply(
            f"❌ Bepul limitingiz tugadi ({FREE_LIMIT} ta).\n\n"
            f"♾️ Cheksiz foydalanish uchun obuna oling:",
            reply_markup=subscription_keyboard(user_id)
        )
        return

    file_path = await message.download()
    user_pdf[user_id] = file_path

    # Bepul foydalanuvchi bo'lsa hisoblagichni oshir
    if reason == "free":
        increment_free_count(user_id)
        free_left = FREE_LIMIT - get_free_count(user_id)
        note = f"\n\n🆓 Bepul: yana {free_left} ta qoldi." if free_left > 0 else f"\n\n⚠️ Bu oxirgi bepul foydalanishingiz edi!"
    else:
        note = "\n\n✅ Obuna faol."

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Past", callback_data="quality_1"),
            InlineKeyboardButton("O'rta", callback_data="quality_2"),
            InlineKeyboardButton("HD", callback_data="quality_3")
        ]
    ])
    await message.reply(f"Sifatni tanlang:{note}", reply_markup=keyboard)


@app.on_callback_query()
async def callback_handler(client, callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data

    # Til tanlash
    if data.startswith("lang_"):
        lang_code = data.split("_")[1]
        user_language[user_id] = lang_code
        ensure_user(user_id, callback_query.from_user.username, callback_query.from_user.first_name, callback_query.from_user.last_name or "")
        if lang_code == "uz":
            await callback_query.message.reply("📄 PDF fayl yuboring.")
        else:
            await callback_query.message.reply("📄 Please send your PDF file.")
        return

    # Holat
    if data == "my_status":
        await send_status(callback_query.message, user_id)
        return

    # Chek yuborish
    if data == "send_check":
        waiting_for_check[user_id] = True
        await callback_query.message.reply(
            "📸 Iltimos, to'lov cheki rasmini yuboring:"
        )
        return

    # Admin: tasdiqlash
    if data.startswith("approve_") and user_id in ADMIN_IDS:
        parts = data.split("_")
        payment_id, target_user_id = int(parts[1]), int(parts[2])
        update_payment_status(payment_id, "approved")
        until = activate_subscription(target_user_id, 30)
        await callback_query.message.edit_caption(
            callback_query.message.caption + "\n\n✅ **TASDIQLANDI**"
        )
        try:
            await app.send_message(
                target_user_id,
                f"🎉 **Obunangiz tasdiqlandi!**\n"
                f"📅 Muddat: {until.strftime('%d.%m.%Y')}\n"
                f"♾️ Endi cheksiz foydalanishingiz mumkin!"
            )
        except Exception:
            pass
        await callback_query.answer("✅ Tasdiqlandi!")
        return

    # Admin: rad etish
    if data.startswith("reject_") and user_id in ADMIN_IDS:
        parts = data.split("_")
        payment_id, target_user_id = int(parts[1]), int(parts[2])
        update_payment_status(payment_id, "rejected")
        await callback_query.message.edit_caption(
            callback_query.message.caption + "\n\n❌ **RAD ETILDI**"
        )
        try:
            await app.send_message(
                target_user_id,
                "❌ Afsuski, to'lovingiz tasdiqlanmadi.\n"
                "Muammo bo'lsa admin bilan bog'laning."
            )
        except Exception:
            pass
        await callback_query.answer("❌ Rad etildi!")
        return

    # Sifat tanlash
    scale_map = {1: 1, 2: 1.5, 3: 2}
    if data.startswith("quality_"):
        scale = scale_map.get(int(data.split("_")[1]), 1.5)
        pdf_path = user_pdf.get(user_id)

        if not pdf_path:
            await callback_query.message.reply("❌ PDF topilmadi. Qayta yuboring.")
            return

        progress_msg = await callback_query.message.reply("⏳ Fayl qayta ishlanmoqda... 0%")

        images, total_pages = pdf_to_images(pdf_path, scale=scale)
        await progress_msg.edit_text("⏳ Processing... 40%")

        merged_images = auto_merge_images(images)
        await progress_msg.edit_text("⏳ Processing... 80%")

        zip_file = create_zip(merged_images)
        await callback_query.message.reply_document(zip_file, caption="✅ ZIP fayl tayyor.")
        await progress_msg.edit_text("✅ Done 100%")

        shutil.rmtree("pages", ignore_errors=True)
        shutil.rmtree("merged", ignore_errors=True)
        if os.path.exists(zip_file):
            os.remove(zip_file)


app.run()