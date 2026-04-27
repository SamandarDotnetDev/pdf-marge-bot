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
API_ID = 32599427
API_HASH = "4c94a696dc744d619b19789b93ed4709"
BOT_TOKEN = "8510708874:AAF0sVI1Lj3aOoQZjmdOUw3kYB-0sLgKOwo"

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

    for i in range(len(doc)):
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

    return image_paths
def auto_merge_images(
    images,
    target_min=15,
    target_max=18,
    output_folder="merged"
):
    os.makedirs(output_folder, exist_ok=True)

    total_images = len(images)

    target_count = min(
        target_max,
        max(target_min, total_images // 10)
    )

    pages_per_image = math.ceil(
        total_images / target_count
    )

    merged_files = []

    for i in range(0, total_images, pages_per_image):
        batch = images[i:i + pages_per_image]

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
            f"merged_{len(merged_files)+1}.jpg"
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
async def process_quality(client, callback_query):
    user_id = callback_query.from_user.id
    scale = int(callback_query.data.split("_")[1])

    pdf_path = user_pdf.get(user_id)

    if not pdf_path:
        await callback_query.message.reply("PDF topilmadi")
        return

    await callback_query.message.reply(
        "Ishlanmoqda..."
    )

    images = pdf_to_images(pdf_path, scale=scale)

    merged_images = auto_merge_images(images)

    zip_file = create_zip(merged_images)

    await callback_query.message.reply_document(
        zip_file,
        caption="ZIP tayyor ✅"
    )
app.run()