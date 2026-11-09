import logging
import sqlite3
import os
from datetime import time as dt_time, datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# ============ تنظیمات ============
# در سرور ابری، این مقادیر از تنظیمات رندر خوانده می‌شوند
BOT_TOKEN = os.environ.get("BOT_TOKEN", "توکن_خود_را_اینجا_بگذارید")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1070951631")) # آیدی عددی شما

DB_PATH = 'reminders.db'
# ==================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

def db():
    return sqlite3.connect(DB_PATH)

def setup_db():
    conn = db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS students (
        chat_id INTEGER PRIMARY KEY, full_name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        class_time TEXT NOT NULL,
        reminder_hours INTEGER NOT NULL,
        student_ids TEXT NOT NULL)''')
    conn.commit()
    conn.close()

def is_admin(uid):
    return uid == ADMIN_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type in ('group', 'supergroup'):
        await update.message.reply_text(f"ربات در گروه فعال است.\nchat_id این گروه: {chat.id}")
        return
    conn = db()
    conn.execute("INSERT OR IGNORE INTO students (chat_id, full_name) VALUES (?,?)",
                 (user.id, user.full_name))
    conn.commit(); conn.close()
    await update.message.reply_text(f"سلام {user.first_name}!\nثبت شدی.\nchat_id شما: {user.id}\n\nاز این به بعد می‌توانید سوالات یا پیام‌های خود را همینجا بنویسید تا استاد ببیند.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        await update.message.reply_text(
            "دستورات ادمین:\n"
            "/sendall متن — ارسال به همه دانشجویان\n"
            "/sendhere متن — ارسال به همین گروه\n"
            "/fee [متن] — یادآوری شهریه\n"
            "/students — لیست دانشجویان\n"
            "/addclass نام | HH:MM | چند ساعت قبل | id1,id2\n"
            "/classes — لیست کلاس‌ها\n"
            "/delclass <id> — حذف کلاس\n\n"
            "💡 برای پاسخ به دانشجو، روی پیامی که ربات برای شما فوروارد می‌کند ریپلای (Reply) بزنید."
        )
    else:
        await update.message.reply_text("شما یک دانشجو هستید. هر پیامی که بفرستید برای استاد ارسال می‌شود.")

async def sendall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("استفاده: /sendall متن پیام")
        return
    conn = db(); rows = conn.execute("SELECT chat_id FROM students").fetchall(); conn.close()
    ok = 0
    for (sid,) in rows:
        try:
            await context.bot.send_message(sid, text); ok += 1
        except Exception as e:
            logger.warning(f"ارسال به {sid} ناموفق: {e}")
    await update.message.reply_text(f"ارسال شد: {ok} از {len(rows)}")

async def sendhere(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("استفاده: /sendhere متن پیام")
        return
    await context.bot.send_message(update.effective_chat.id, text)

async def fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    custom = " ".join(context.args).strip()
    msg = custom if custom else "🔔 یادآوری: لطفاً شهریه خود را پرداخت کنید."
    conn = db(); rows = conn.execute("SELECT chat_id FROM students").fetchall(); conn.close()
    ok = 0
    for (sid,) in rows:
        try:
            await context.bot.send_message(sid, msg); ok += 1
        except Exception: pass
    await update.message.reply_text(f"یادآوری شهریه برای {ok} نفر ارسال شد.")

async def liststudents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    conn = db(); rows = conn.execute("SELECT chat_id, full_name FROM students").fetchall(); conn.close()
    if not rows:
        await update.message.reply_text("هیچ دانشجویی ثبت نشده.")
        return
    await update.message.reply_text("دانشجویان:\n" + "\n".join(f"{n} → {cid}" for cid, n in rows))

async def addclass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    raw = " ".join(context.args)
    try:
        parts = [x.strip() for x in raw.split("|")]
        if len(parts) != 4: raise ValueError
        name, time_str, hours_str, ids_str = parts
        h, m = time_str.split(":")
        dt_time(hour=int(h), minute=int(m))
        hours = int(hours_str)
        ids = [int(x.strip()) for x in ids_str.split(",") if x.strip()]
        if not ids or not name: raise ValueError
    except Exception:
        await update.message.reply_text(
            "فرمت:\n/addclass نام کلاس | HH:MM | چند ساعت قبل | id1,id2\n"
            "مثال:\n/addclass ریاضی | 10:00 | 2 | 111,222"
        )
        return
    conn = db()
    cur = conn.execute(
        "INSERT INTO classes (name, class_time, reminder_hours, student_ids) VALUES (?,?,?,?)",
        (name, time_str, hours, ",".join(str(i) for i in ids))
    )
    cid = cur.lastrowid
    conn.commit(); conn.close()
    schedule_class(context.application, cid, name, time_str, hours, ids)
    await update.message.reply_text(f"✅ کلاس «{name}» ثبت شد (شناسه {cid}).")

async def listclasses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    conn = db()
    rows = conn.execute("SELECT id, name, class_time, reminder_hours, student_ids FROM classes").fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("کلاسی ثبت نشده.")
        return
    await update.message.reply_text("\n".join(
        f"[{i}] {n} — {t} (یادآوری {h}س قبل) → {s}" for i, n, t, h, s in rows
    ))

async def delclass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("استفاده: /delclass <id>")
        return
    try:
        cid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("آیدی نامعتبر")
        return
    conn = db(); conn.execute("DELETE FROM classes WHERE id=?", (cid,)); conn.commit(); conn.close()
    for job in context.application.job_queue.get_jobs_by_name(f"class_{cid}"):
        job.schedule_removal()
    await update.message.reply_text(f"کلاس {cid} حذف شد.")

async def handle_student_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await context.bot.forward_message(
        chat_id=ADMIN_ID,
        from_chat_id=update.effective_chat.id,
        message_id=update.message.message_id
    )
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"⬆️ پیام بالا از طرف: {user.full_name} (آیدی: {user.id})\nبرای پاسخ، روی همان پیام فوروارد شده ریپلای (Reply) بزنید."
    )
    await update.message.reply_text("✅ پیام شما برای استاد ارسال شد. به زودی پاسخ می‌گیرید.")

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.forward_from:
        await update.message.reply_text("⚠️ لطفاً روی پیامی که از طرف دانشجو فوروارد شده، ریپلای (Reply) بزنید.")
        return
    
    student_id = update.message.reply_to_message.forward_from.id
    reply_text = update.message.text
    
    try:
        await context.bot.send_message(
            chat_id=student_id,
            text=f"📩 پاسخ استاد:\n\n{reply_text}"
        )
        await update.message.reply_text("✅ پاسخ شما برای دانشجو ارسال شد.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در ارسال پیام به دانشجو: {e}")

async def class_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    text = f"⏰ یادآوری: کلاس «{d['name']}» امروز ساعت {d['time']} برگزار می‌شود."
    for sid in d['ids']:
        try:
            await context.bot.send_message(sid, text)
        except Exception as e:
            logger.warning(f"یادآوری به {sid} ناموفق: {e}")

def schedule_class(app, cid, name, time_str, hours, ids):
    h, m = time_str.split(":")
    cls_time = datetime.combine(datetime.today(), dt_time(hour=int(h), minute=int(m)))
    rem_time = (cls_time - timedelta(hours=hours)).time()
    app.job_queue.run_daily(
        class_reminder_job,
        time=rem_time,
        days=(0, 1, 2, 3, 4, 5, 6),
        data={'name': name, 'time': time_str, 'ids': ids},
        name=f"class_{cid}"
    )

def load_all_classes(app):
    conn = db()
    rows = conn.execute("SELECT id, name, class_time, reminder_hours, student_ids FROM classes").fetchall()
    conn.close()
    for cid, name, t, h, ids_str in rows:
        ids = [int(x.strip()) for x in ids_str.split(",") if x.strip()]
        schedule_class(app, cid, name, t, h, ids)

async def post_init(app):
    load_all_classes(app)

def main():
    if BOT_TOKEN == "توکن_خود_را_اینجا_بگذارید" or ADMIN_ID == 0:
        print("!!! BOT_TOKEN و ADMIN_ID را پر کنید.")
        return
    setup_db()
    
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .post_init(post_init)
        .build()
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("sendall", sendall))
    app.add_handler(CommandHandler("sendhere", sendhere))
    app.add_handler(CommandHandler("fee", fee))
    app.add_handler(CommandHandler("students", liststudents))
    app.add_handler(CommandHandler("addclass", addclass))
    app.add_handler(CommandHandler("classes", listclasses))
    app.add_handler(CommandHandler("delclass", delclass))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.User(ADMIN_ID), handle_student_message))
    app.add_handler(MessageHandler(filters.TEXT & filters.REPLY & filters.User(ADMIN_ID), handle_admin_reply))
    
    print("ربات در حال اجراست...")
    app.run_polling()

if __name__ == "__main__":
    main()
