import os, io, base64
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from google import genai
from google.genai import types
from PIL import Image

# ══════════════════════════════════════
# المفاتيح — تُوضع في Railway كـ Variables
# ══════════════════════════════════════
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8993387119:AAHA1VTLCbJhaaP2NmFPN8s8nlsoUJnVf48")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyCxViE1kVPM656TqPmXT91M3qUMEsTnC8E")

client = genai.Client(api_key=GEMINI_API_KEY)

ORG, TITLE, BULLETS, PHONE, ADDRESS, CONFIRM = range(6)


# ══════════════════════════════════════
# الخطوة 1 — بناء البرومبت
# ══════════════════════════════════════
def build_prompt(data: dict) -> str:
    bullets_text = "\n".join(f"- {b}" for b in data["bullets"])
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"""
You are a professional graphic designer specialized in Arabic event posters.

Create a detailed image generation prompt in English for a professional poster with:

Organization: {data["org"]}
Workshop Title: {data["title"]}
Topics:
{bullets_text}
Phone: {data["phone"]}
Address: {data["address"]}

The poster must have:
- White background
- Dark blue header bar (#1A2E5A) at top with organization name in orange (#F5A623)
- Orange accent line below header
- Arabic text for announcement: يُعلن عن ورشة بعنوان
- Workshop title prominently displayed
- Light gray middle section with CV/document illustration
- List of workshop topics in Arabic on the right side
- Registration note in Arabic
- Link registration box with rounded corners
- Bottom contact section with light gray background
- Phone number and address clearly visible
- Clean professional layout, Somar Sans Arabic font style

Return only the image prompt, no explanation.
"""
    )
    prompt = response.text.strip()
    print(f"📝 البرومبت:\n{prompt[:300]}...")
    return prompt


# ══════════════════════════════════════
# الخطوة 2 — توليد الصورة
# ══════════════════════════════════════
def generate_image(prompt: str) -> bytes:
    response = client.models.generate_images(
        model="imagen-3.0-generate-002",
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="9:16",
            safety_filter_level="block_only_high",
            person_generation="allow_adult",
        ),
    )
    return response.generated_images[0].image.image_bytes


# ══════════════════════════════════════
# الخطوة 3 — مراجعة المحتوى
# ══════════════════════════════════════
def review_content(img_bytes: bytes, data: dict) -> dict:
    img_b64 = base64.b64encode(img_bytes).decode()
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            types.Part(text=f"""
راجع هذا البوستر وتحقق من:
1. وجود اسم المركز: {data["org"]}
2. وجود عنوان الورشة: {data["title"]}
3. وجود رقم التواصل: {data["phone"]}
4. صحة النصوص العربية إملائياً
5. التناسق البصري العام

أعد ردك بهذا التنسيق الحرفي فقط:
APPROVED: true/false
ISSUES: (المشاكل أو "لا يوجد")
CORRECTIONS: (التصحيحات أو "لا يوجد")
"""),
            types.Part(
                inline_data=types.Blob(
                    mime_type="image/png",
                    data=img_b64
                )
            )
        ]
    )
    text = response.text.strip()
    print(f"📋 المراجعة:\n{text}")
    approved    = "APPROVED: true" in text
    issues      = "لا يوجد"
    corrections = "لا يوجد"
    for line in text.split("\n"):
        if line.startswith("ISSUES:"):
            issues = line.replace("ISSUES:", "").strip()
        if line.startswith("CORRECTIONS:"):
            corrections = line.replace("CORRECTIONS:", "").strip()
    return {"approved": approved, "issues": issues, "corrections": corrections}


# ══════════════════════════════════════
# الخطوة 4 — رفع الدقة 300dpi
# ══════════════════════════════════════
def upscale_300dpi(img_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(img_bytes))
    img_resized = img.resize((2481, 3507), Image.LANCZOS)
    buf = io.BytesIO()
    img_resized.save(buf, format="PNG", dpi=(300, 300))
    buf.seek(0)
    return buf.read()


# ══════════════════════════════════════
# الدالة الرئيسية للتوليد
# ══════════════════════════════════════
async def generate_full_poster(update: Update, data: dict):
    await update.message.reply_text(
        "🚀 بدأت العملية!\n\n"
        "الخطوة 1/4: Gemini يبني وصف البوستر..."
    )
    try:
        prompt = build_prompt(data)
        await update.message.reply_text(
            "✅ البرومبت جاهز!\n\n"
            "الخطوة 2/4: Imagen يرسم البوستر (قد يأخذ دقيقة)..."
        )
        img_bytes = generate_image(prompt)
        await update.message.reply_text(
            "✅ البوستر جاهز!\n\n"
            "الخطوة 3/4: Gemini يدقق المحتوى..."
        )
        review = review_content(img_bytes, data)
        if not review["approved"] and review["issues"] != "لا يوجد":
            await update.message.reply_text(
                f"⚠️ لاحظنا:\n{review['issues']}\n\n"
                "🔄 إعادة التوليد مع التصحيحات..."
            )
            img_bytes = generate_image(
                f"{prompt}\n\nIMPORTANT CORRECTIONS: {review['corrections']}"
            )
        await update.message.reply_text(
            "✅ المراجعة اكتملت!\n\n"
            "الخطوة 4/4: رفع الدقة إلى 300dpi..."
        )
        final_img = upscale_300dpi(img_bytes)
        filename  = f"poster_{data['title'][:20].replace(' ', '_')}.png"
        await update.message.reply_document(
            document=io.BytesIO(final_img),
            filename=filename,
            caption=(
                "🎉 بوسترك جاهز بدقة 300dpi!\n"
                f"{'✅ اجتاز مراجعة المحتوى' if review['approved'] else '⚠️ راجع البوستر يدوياً'}"
            )
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ حدث خطأ:\n{e}\n\n"
            "تأكد من:\n"
            "• صحة مفاتيح API في Railway Variables\n"
            "• اشتراكك يدعم Imagen\n"
        )


# ══════════════════════════════════════
# هاندلرز
# ══════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً! سنصمم بوستر احترافي بالذكاء الاصطناعي\n\n"
        "أولاً: ما اسم مركزك أو منظمتك؟"
    )
    return ORG

async def get_org(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["org"] = update.message.text
    await update.message.reply_text("✅ ما عنوان الورشة؟")
    return TITLE

async def get_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["title"] = update.message.text
    await update.message.reply_text(
        "✅ أرسل المحاور — كل محور في سطر:\n\n"
        "مثال:\n"
        "كتابة السيرة الذاتية\n"
        "مهارات المقابلات\n"
        "الأخطاء الشائعة"
    )
    return BULLETS

async def get_bullets(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["bullets"] = update.message.text.strip().split("\n")
    await update.message.reply_text("✅ رقم الهاتف؟")
    return PHONE

async def get_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["phone"] = update.message.text
    await update.message.reply_text("✅ العنوان؟")
    return ADDRESS

async def get_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["address"] = update.message.text
    bullets_preview = "\n".join(f"  • {b}" for b in ctx.user_data.get("bullets", []))
    await update.message.reply_text(
        "📋 ملخص البوستر:\n\n"
        f"🏢 المركز: {ctx.user_data['org']}\n"
        f"📌 الورشة: {ctx.user_data['title']}\n"
        f"📝 المحاور:\n{bullets_preview}\n"
        f"📞 الهاتف: {ctx.user_data['phone']}\n"
        f"📍 العنوان: {ctx.user_data['address']}\n\n"
        "هل تريد المتابعة؟\n"
        "اكتب: نعم أو لا"
    )
    return CONFIRM

async def confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() in ["نعم", "yes", "y", "✅"]:
        await generate_full_poster(update, ctx.user_data)
    else:
        await update.message.reply_text("❌ تم الإلغاء.\nاكتب /start للبدء من جديد")
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ تم الإلغاء.\nاكتب /start للبدء من جديد")
    return ConversationHandler.END


# ══════════════════════════════════════
# تشغيل
# ══════════════════════════════════════

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ORG:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_org)],
            TITLE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_title)],
            BULLETS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bullets)],
            PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)
    print("✅ البوت شغّال!")
    app.run_polling()

if __name__ == "__main__":
    main()