import os
import math
import zipfile
import fitz
from PIL import Image
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
import os

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Client(
    "pdf_zip_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)
def pdf_to_images(pdf_path, scale=2, output_folder="pages"):
    os.makedirs(output_folder, exist_ok=True)

    doc = fitz.open(pdf_path)
    image_paths = []

    total_pages = len(doc)

    for i in range(total_pages):
        page = doc[i]

        pix = page.get_pixmap(
            matrix=fitz.Matrix(scale, scale)
        )

        img_path = os.path.join(
            output_folder,
            f"page_{i+1}.jpg"
        )

        pix.save(img_path)
        image_paths.append(img_path)

    return image_paths, total_pages
def auto_merge_images(images, target_count=15, output_folder="merged"):
    import os
    from PIL import Image

    os.makedirs(output_folder, exist_ok=True)

    total_images = len(images)

    base_pages = total_images // target_count
    extra_pages = total_images % target_count

    merged_files = []
    start = 0

    for i in range(target_count):
        # dastlabki extra_pages ta rasmga +1 sahifa
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

        output_path = os.path.join(
            output_folder,
            f"merged_{i+1}.jpg"
        )

        merged.save(output_path, quality=95)
        merged_files.append(output_path)

    return merged_files
def create_zip(images, zip_name="merged_images.zip"):
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zipf:
        for img in images:
            zipf.write(img, os.path.basename(img))

    return zip_name
user_pdf = {}
@app.on_message(filters.document)
async def receive_pdf(client, message):
    user_id = message.from_user.id

    file_path = await message.download()
    user_pdf[user_id] = file_path

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Past", callback_data="quality_1"),
            InlineKeyboardButton("O‘rta", callback_data="quality_2"),
            InlineKeyboardButton("HD", callback_data="quality_3")
        ]
    ])

    await message.reply(
        "Sifatni tanlang:",
        reply_markup=keyboard)
@app.on_callback_query()
async def callback_handler(client, callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data

    # language selection
    if data.startswith("lang_"):
        lang = data.split("_")[1]
        user_language[user_id] = lang

        if lang == "uz":
            await callback_query.message.reply("📄 PDF fayl yuboring.")
        else:
            await callback_query.message.reply("📄 Please send your PDF file.")
        return

    # quality selection
    if data.startswith("quality_"):
        scale = scale_map.get(scale, 1.5)

    pdf_path = user_pdf.get(user_id)
    lang = user_language.get(user_id, "en")

    if not pdf_path:
        if lang == "uz":
            await callback_query.message.reply("❌ PDF topilmadi.")
        else:
            await callback_query.message.reply("❌ PDF not found.")
        return

    if lang == "uz":
        progress_msg = await callback_query.message.reply(
            "⏳ Fayl qayta ishlanmoqda, biroz kuting... o%"
        )
    else:
        progress_msg = await callback_query.message.reply(
            "⏳ Processing your file, please wait... o%"
        )

    images, total_pages = pdf_to_images(pdf_path, scale=scale)

    await progress_msg.edit_text("⏳ Processing... 40%")

    merged_images = auto_merge_images(images)

    await progress_msg.edit_text("⏳ Processing... 80%")
    zip_file = create_zip(merged_images)

    if lang == "uz":
        caption_text = "✅ ZIP fayl tayyor."
    else:
        caption_text = "✅ ZIP file is ready."

    await callback_query.message.reply_document(
        zip_file,
        caption=caption_text
    )
    import shutil
    shutil.rmtree("pages", ignore_errors=True)
    shutil.rmtree("merged", ignore_errors=True)

    if os.path.exists(zip_file):
        os.remove(zip_file)
user_language = {}

@app.on_message(filters.command("start"))
async def start_command(client, message):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇺🇿 O‘zbek", callback_data="lang_uz"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
        ]
    ])

    await message.reply(
        "🌐 Tilni tanlang / Choose language",
        reply_markup=keyboard
    )
app.run()
