import threading
import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
import requests
import re
import logging
import json
import hashlib
import socket
import psutil
import time
import zlib 
from telebot import types
from datetime import datetime, timedelta
import signal
import sqlite3
import platform
import uuid
import base64

# تهيئة التسجيل (Logging)
# تم تحديثه ليشمل ملفات منفصلة لسجلات الأمان وسجلات الأخطاء العامة
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_activity.log"), # سجل عام لأنشطة البوت
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MainBot") # لوجر للأنشطة العامة

security_logger = logging.getLogger("SecurityLog") # لوجر خاص للأمان
security_logger.setLevel(logging.WARNING) # تم تغيير المستوى لتسجيل التحذيرات الأمنية
security_logger.addHandler(logging.FileHandler("security_events.log"))
security_logger.addHandler(logging.StreamHandler())


# --- إعدادات البوت ---
TOKEN = '7574562116:AAGdVrowUpYwlRjEgnVb0rUt0qJg1rEzS7c'  # توكن البوت الخاص بك من BotFather
ADMIN_ID = 7700185632  # ايدي المطور الخاص بك (الـ User ID الخاص بك)
YOUR_USERNAME = '@VR_SX'  # يوزر المطور الخاص بك مع علامة @

bot = telebot.TeleBot(TOKEN)

# أدلة تخزين الملفات والبوتات
uploaded_files_dir = 'uploaded_bots'
quarantined_files_dir = 'quarantined_files' 

# تأكد من وجود المجلدات
os.makedirs(uploaded_files_dir, exist_ok=True)
os.makedirs(quarantined_files_dir, exist_ok=True)


# القوائم والمتغيرات العالمية
# لتخزين العمليات الجارية للبوتات: {process_key: {'process': Popen_object, 'folder_path': 'path/to/bot_folder', 'bot_username': '@botusername', 'file_name': 'script.py', 'owner_id': user_id, 'log_file_stdout': 'path/to/stdout.log', 'log_file_stderr': 'path/to/stderr.log', 'start_time': datetime_object}}
bot_processes = {} 
# لتخزين الملفات التي رفعها كل مستخدم: {user_id: [{'file_name': 'script.py', 'folder_path': 'path/to/bot_folder', 'bot_username': '@botusername'}]}
user_files = {}      
active_users = set() # لتخزين معرفات المستخدمين النشطين
banned_users = set() # لتخزين معرفات المستخدمين المحظورين
user_warnings = {} # لتتبع التحذيرات لكل مستخدم: {user_id: [{'reason': '...', 'timestamp': '...', 'file_name': '...'}]}

bot_locked = False  # حالة قفل البوت
free_mode = True    # وضع مجاني افتراضي (لا يتطلب اشتراك)
block_new_users = False # لمنع المستخدمين الجدد من الانضمام

# --- دوال فحص الحماية (تم تعديلها لتنفيذ الفحص المطلوب) ---
def is_safe_python_code(file_content_bytes, user_id, file_name):
    """
    يفحص محتوى ملف بايثون بحثاً عن أكواد مشبوهة.
    يعيد True إذا كان آمناً، ويعيد False مع السبب إذا كان مشبوهاً.
    """
    file_content = file_content_bytes.decode('utf-8', errors='ignore')

    # قائمة الكلمات المفتاحية/الوحدات المشبوهة
    suspicious_patterns = {
        r'\bos\.system\b': 'استخدام os.system',
        r'\bsubprocess\.(?!run|Popen|check_output|call)': 'استخدام subprocess بطريقة غير مصرح بها', # استثناءات للتشغيل الرسمي
        r'\beval\(': 'استخدام eval()',
        r'\bexec\(': 'استخدام exec()',
        r'\bcompile\(': 'استخدام compile()',
        r'\bsocket\b': 'استخدام socket',
        r'\brequests\.post\b': 'استخدام requests.post',
        r'\bbase64\b': 'استخدام base64',
        r'\bmarshal\b': 'استخدام marshal',
        r'\bzlib\b': 'استخدام zlib',
        r'\btelebot\.TeleBot\(': 'إنشاء كائن TeleBot داخل ملف المستخدم',
        r'while\s+True\s*:': 'حلقة لا نهائية (while True)',
        r'\binput\(': 'استخدام input()',
    }

    found_reasons = []
    for pattern, reason in suspicious_patterns.items():
        if re.search(pattern, file_content):
            found_reasons.append(reason)

    if found_reasons:
        reason_str = ", ".join(found_reasons)
        log_user_warning(user_id, f"تم اكتشاف كود مشبوه: {reason_str}", file_name)
        notify_admins_of_potential_risk(user_id, f"كود مشبوه في الملف {file_name}", file_name, file_content_bytes)
        return False, reason_str
    
    return True, None

def scan_file_with_api(file_content, file_name, user_id):
    """
    هذه الدالة Dummy - لا تقوم بأي فحص API وتعود بـ True دائمًا.
    (تم الإبقاء عليها كما هي، لا يوجد طلب لتعديلها)
    """
    return True 

def scan_zip_for_malicious_code(zip_file_path, user_id):
    """
    يفحص ملف ZIP بحثاً عن ملفات بايثون مشبوهة.
    يعيد True, None إذا كان آمناً، ويعيد False, السبب إذا تم اكتشاف كود مشبوه.
    """
    try:
        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                if file_info.filename.endswith('.py'):
                    with zip_ref.open(file_info.filename) as py_file:
                        file_content_bytes = py_file.read()
                        is_safe, reason = is_safe_python_code(file_content_bytes, user_id, file_info.filename)
                        if not is_safe:
                            return False, f"كود مشبوه في الملف {file_info.filename}: {reason}"
        return True, None
    except Exception as e:
        logger.error(f"خطأ أثناء فحص ملف ZIP ({zip_file_path}) لـ user_id {user_id}: {e}")
        log_user_warning(user_id, f"خطأ في فحص ملف ZIP: {e}", zip_file_path.split('/')[-1])
        return False, "فشل في فحص ملف ZIP"

def log_user_warning(user_id, reason, file_name=None):
    """
    يسجل تحذيراً للمستخدم في قاعدة البيانات والمتغيرات العالمية.
    """
    timestamp = datetime.now().isoformat()
    warning_entry = {'reason': reason, 'file_name': file_name, 'timestamp': timestamp}
    
    if user_id not in user_warnings:
        user_warnings[user_id] = []
    user_warnings[user_id].append(warning_entry)

    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('INSERT INTO user_warnings (user_id, reason, file_name, timestamp) VALUES (?, ?, ?, ?)', 
              (user_id, reason, file_name, timestamp))
    conn.commit()
    conn.close()
    security_logger.warning(f"تحذير للمستخدم {user_id}: {reason} (الملف: {file_name})")

def notify_admins_of_potential_risk(user_id, activity, file_name, file_content_bytes):
    """
    يرسل تنبيهًا للمطور بشأن نشاط مشبوه، مع تفاصيل الملف والسبب.
    """
    warning_message = f"⚠️ **محاولة مشبوهة!**\n\n"
    warning_message += f"🧪 **السبب**: {activity}\n"
    warning_message += f"👤 **معرف المستخدم**: `{user_id}`\n"
    warning_message += f"📄 **اسم الملف**: `{file_name}`\n"
    warning_message += f"🔗 **رابط الملف**: [انقر هنا لتحميل الملف]({get_file_download_link(file_content_bytes, file_name)})" # يمكن إضافة رابط لتحميل الملف إذا أردت إتاحة مراجعة يدوية

    try:
        bot.send_message(ADMIN_ID, warning_message, parse_mode='Markdown')
        security_logger.critical(f"تم إرسال تحذير للمطور: {activity} من المستخدم {user_id} للملف {file_name}")
    except Exception as e:
        security_logger.error(f"فشل في إرسال تنبيه للمطور بشأن نشاط مشبوه: {e}")

def get_file_download_link(file_content_bytes, file_name):
    """
    دالة Dummy لإنشاء رابط تحميل ملف. في بيئة حقيقية ستحتاج لرفع الملف إلى خدمة تخزين.
    هنا، سنستخدم حلاً بديلاً بسيطًا، أو نوضح أنه يجب أن يكون هناك خدمة تخزين.
    """
    # في بيئة إنتاجية، ستحتاج إلى رفع هذا الملف مؤقتًا إلى خدمة تخزين (مثل Telegram's own file storage if possible
    # or a cloud storage like S3, or simply storing it temporarily on the server and providing a direct link).
    # For now, we'll just indicate it's not directly downloadable via this link.
    # يمكن إرجاع رابط placeholder أو عدم تضمين الرابط إذا لم يكن هناك طريقة لتحميل الملف تلقائيًا.
    return "لا يتوفر رابط تحميل مباشر (يجب مراجعة الملف في مجلد quarantined_files)"

# --- وظائف قاعدة البيانات (تم تحديثها لتشمل حفظ حالة البوتات) ---

def init_db():
    """يهيئ قاعدة البيانات والجداول المطلوبة، ويضيف أعمدة جديدة إذا لم تكن موجودة."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    # جدول لملفات المستخدمين
    c.execute('''CREATE TABLE IF NOT EXISTS user_files
                 (user_id INTEGER, file_name TEXT, folder_path TEXT, bot_username TEXT, UNIQUE(user_id, file_name, folder_path))''')
    
    # جدول للمستخدمين النشطين
    c.execute('''CREATE TABLE IF NOT EXISTS active_users
                 (user_id INTEGER PRIMARY KEY)''')
    # جدول للمستخدمين المحظورين
    c.execute('''CREATE TABLE IF NOT EXISTS banned_users
                 (user_id INTEGER PRIMARY KEY, reason TEXT, ban_date TEXT)''')
    # جدول للتحذيرات
    c.execute('''CREATE TABLE IF NOT EXISTS user_warnings
                 (user_id INTEGER, reason TEXT, file_name TEXT, timestamp TEXT)''')
    
    # جدول لحفظ حالة البوتات قيد التشغيل (جديد)
    c.execute('''CREATE TABLE IF NOT EXISTS bot_processes_state
                 (process_key TEXT PRIMARY KEY, folder_path TEXT, bot_username TEXT, file_name TEXT, owner_id INTEGER, 
                 log_file_stdout TEXT, log_file_stderr TEXT, start_time TEXT)''')

    conn.commit()
    conn.close()

def load_data():
    """يحمل البيانات من قاعدة البيانات عند بدء تشغيل البوت."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()

    c.execute('SELECT user_id, file_name, folder_path, bot_username FROM user_files')
    user_files_data = c.fetchall()
    for user_id, file_name, folder_path, bot_username in user_files_data:
        if user_id not in user_files:
            user_files[user_id] = []
        user_files[user_id].append({'file_name': file_name, 'folder_path': folder_path, 'bot_username': bot_username})
    
    c.execute('SELECT user_id FROM active_users')
    active_users_data = c.fetchall()
    for user_id, in active_users_data:
        active_users.add(user_id)
    
    c.execute('SELECT user_id, reason FROM banned_users') # تم إضافة reason في الاستعلام
    banned_users_data = c.fetchall()
    for user_id, reason in banned_users_data:
        banned_users.add(user_id) # فقط إضافة الـ ID للمجموعة، السبب يخزن في DB فقط
    
    c.execute('SELECT user_id, reason, file_name, timestamp FROM user_warnings')
    warnings_data = c.fetchall()
    for user_id, reason, file_name, timestamp in warnings_data:
        if user_id not in user_warnings:
            user_warnings[user_id] = []
        user_warnings[user_id].append({'reason': reason, 'file_name': file_name, 'timestamp': timestamp})

    conn.close()

def save_user_file_db(user_id, file_name, folder_path, bot_username=None):
    """يحفظ معلومات الملف في قاعدة البيانات."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, folder_path, bot_username) VALUES (?, ?, ?, ?)', 
              (user_id, file_name, folder_path, bot_username))
    conn.commit()
    conn.close()

def remove_user_file_db(user_id, file_name, folder_path):
    """
    يحذف معلومات الملف من قاعدة البيانات بناءً على user_id و file_name و folder_path
    لضمان التفرد في حال رفع نفس اسم الملف لعدة بوتات.
    """
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ? AND folder_path = ?', 
              (user_id, file_name, folder_path))
    conn.commit()
    conn.close()

def add_active_user(user_id):
    """يضيف مستخدمًا إلى قائمة المستخدمين النشطين في قاعدة البيانات."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()

def ban_user(user_id, reason):
    """يحظر المستخدم ويسجل السبب في قاعدة البيانات."""
    banned_users.add(user_id)
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO banned_users (user_id, reason, ban_date) VALUES (?, ?, ?)', 
              (user_id, reason, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    logger.warning(f"تم حظر المستخدم {user_id} بسبب: {reason}")

def unban_user(user_id):
    """يلغي حظر المستخدم من قاعدة البيانات."""
    if user_id in banned_users:
        banned_users.remove(user_id)
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute('DELETE FROM banned_users WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        logger.info(f"تم إلغاء حظر المستخدم {user_id}")
        return True
    return False

def save_bot_process_state(process_key, folder_path, bot_username, file_name, owner_id, log_file_stdout, log_file_stderr, start_time):
    """يحفظ حالة البوت الجاري تشغيله في قاعدة البيانات."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO bot_processes_state 
                 (process_key, folder_path, bot_username, file_name, owner_id, log_file_stdout, log_file_stderr, start_time) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (process_key, folder_path, bot_username, file_name, owner_id, log_file_stdout, log_file_stderr, start_time.isoformat()))
    conn.commit()
    conn.close()

def remove_bot_process_state(process_key):
    """يحذف حالة البوت من قاعدة البيانات."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('DELETE FROM bot_processes_state WHERE process_key = ?', (process_key,))
    conn.commit()
    conn.close()

def load_bot_processes_state():
    """يحمل حالات البوتات من قاعدة البيانات عند بدء التشغيل."""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('SELECT process_key, folder_path, bot_username, file_name, owner_id, log_file_stdout, log_file_stderr, start_time FROM bot_processes_state')
    saved_processes = c.fetchall()
    conn.close()
    return saved_processes

# تهيئة وتحميل البيانات عند بدء التشغيل
init_db()
load_data()

# --- استرداد تلقائي للبوتات (وظيفة جديدة) ---
def recover_running_bots():
    """
    يسترد البوتات التي كانت تعمل سابقاً من قاعدة البيانات ويقوم بتشغيلها.
    """
    logger.info("جارٍ استرداد البوتات التي كانت تعمل سابقاً...")
    saved_processes = load_bot_processes_state()
    for process_key, folder_path, bot_username, file_name, owner_id, log_file_stdout, log_file_stderr, start_time_str in saved_processes:
        main_script_path = os.path.join(folder_path, file_name)
        if os.path.exists(main_script_path):
            logger.info(f"إعادة تشغيل البوت: {bot_username} ({file_name}) للمستخدم {owner_id}")
            start_time_dt = datetime.fromisoformat(start_time_str)
            try:
                # التأكد من أن المجلد هو دليل العمل الصحيح
                process = subprocess.Popen(
                    ['python3', main_script_path],
                    cwd=folder_path,  # تعيين مجلد العمل
                    stdout=open(log_file_stdout, 'a'),
                    stderr=open(log_file_stderr, 'a'),
                    preexec_fn=os.setsid # لجعل العملية مستقلة عن البوت الرئيسي
                )
                bot_processes[process_key] = {
                    'process': process,
                    'folder_path': folder_path,
                    'bot_username': bot_username,
                    'file_name': file_name,
                    'owner_id': owner_id,
                    'log_file_stdout': log_file_stdout,
                    'log_file_stderr': log_file_stderr,
                    'start_time': start_time_dt # استخدام الوقت الأصلي للتشغيل
                }
                logger.info(f"تمت إعادة تشغيل البوت {bot_username} بنجاح.")
                # إرسال إشعار للمستخدم إذا كان موجودًا في active_users
                if owner_id in active_users:
                    try:
                        bot.send_message(owner_id, f"✅ **تم استرداد وإعادة تشغيل البوت الخاص بك** `{bot_username if bot_username else file_name}` **تلقائياً.**")
                    except Exception as e:
                        logger.error(f"فشل في إرسال إشعار استرداد للمستخدم {owner_id}: {e}")
            except Exception as e:
                logger.error(f"فشل في إعادة تشغيل البوت {file_name} للمستخدم {owner_id}: {e}")
                # إزالة البوت من قائمة الاسترداد إذا فشل تشغيله
                remove_bot_process_state(process_key)
        else:
            logger.warning(f"ملف البوت {file_name} في المسار {folder_path} غير موجود. إزالة من قائمة الاسترداد.")
            remove_bot_process_state(process_key)
    logger.info("اكتمل استرداد البوتات.")

# --- لوحة التحكم والقوائم ---

def create_main_menu(user_id):
    """ينشئ لوحة المفاتيح الرئيسية للبوت."""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📤 رفع ملف بوت', callback_data='upload'))
    markup.add(types.InlineKeyboardButton('🤖 بوتاتي', callback_data='my_bots')) 
    markup.add(types.InlineKeyboardButton('⚡ سرعة البوت', callback_data='speed'))
    markup.add(types.InlineKeyboardButton('📞 تواصل مع المطور', url=f'https://t.me/{YOUR_USERNAME[1:]}'))
    
    # إضافة زر الإحصائيات هنا للمستخدمين العاديين أيضًا
    markup.add(types.InlineKeyboardButton('📊 إحصائيات عامة', callback_data='stats'))
    
    if user_id == ADMIN_ID:
        # الأزرار الخاصة بالمطور فقط
        markup.add(types.InlineKeyboardButton('🔐 تقرير الأمان', callback_data='security_report'))
        markup.add(types.InlineKeyboardButton('📢 إذاعة رسالة', callback_data='broadcast'))
        markup.add(types.InlineKeyboardButton('🔒 قفل البوت', callback_data='lock_bot'))
        markup.add(types.InlineKeyboardButton('🔓 فتح البوت', callback_data='unlock_bot'))
        markup.add(types.InlineKeyboardButton('🔨 إدارة المستخدمين', callback_data='manage_users'))
        markup.add(types.InlineKeyboardButton('⚙️ إدارة البوتات المستضافة', callback_data='manage_hosted_bots'))
        markup.add(types.InlineKeyboardButton('🖥️ إحصائيات الخادم', callback_data='server_stats'))
        markup.add(types.InlineKeyboardButton('🛠️ أدوات المطور', callback_data='dev_tools'))
    return markup

# --- معالجات الأوامر والرسائل ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    """يعالج أمر /start ويرسل رسالة الترحيب."""
    user_id = message.from_user.id
    
    if user_id in banned_users:
        bot.send_message(message.chat.id, "⛔ **أنت محظور من استخدام هذا البوت.** يرجى التواصل مع المطور إذا كنت تعتقد أن هذا خطأ.")
        return
    
    if bot_locked:
        bot.send_message(message.chat.id, "⚠️ **البوت مقفل حالياً.** الرجاء المحاولة لاحقًا.")
        return

    if block_new_users and user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "🚫 **نأسف، البوت لا يقبل مستخدمين جدد حاليًا.** يرجى التواصل مع المطور @VR_SX.")
        return

    user_name = message.from_user.first_name
    user_username = message.from_user.username

    user_bio = "لا يوجد بايو"
    photo_file_id = None

    if user_id not in active_users:
        active_users.add(user_id)  
        add_active_user(user_id)  # أضف المستخدم إلى قاعدة البيانات كنشط

        try:
            # استخدام bot.get_chat بدلاً من bot.get_user_profile_photos لبعض التفاصيل
            # للحصول على البايو، نحتاج إلى معرفة ما إذا كان المستخدم يملك بايو عام
            # هذا الجزء قد لا يعمل مباشرة بدون صلاحيات خاصة أو إذا لم يكن البايو متاحًا عبر API
            # bot.get_chat() لا يعيد البايو العام للمستخدمين العاديين، فقط للقنوات والمجموعات
            # لذلك، سأتركها كما هي مع ملاحظة أنها قد لا تجلب البايو
            # user_profile = bot.get_chat(user_id)
            # user_bio = user_profile.bio if user_profile.bio else "لا يوجد بايو"
            
            user_profile_photos = bot.get_user_profile_photos(user_id, limit=1)
            if user_profile_photos.photos:
                photo_file_id = user_profile_photos.photos[0][-1].file_id  
        except Exception as e:
            logger.error(f"فشل في جلب تفاصيل المستخدم الجديد {user_id}: {e}")

        try:
            welcome_message_to_admin = f"🎉 **انضم مستخدم جديد إلى البوت!**\n\n"
            welcome_message_to_admin += f"👤 **الاسم**: {user_name}\n"
            welcome_message_to_admin += f"📌 **اليوزر**: @{user_username if user_username else 'غير متوفر'}\n"
            welcome_message_to_admin += f"🆔 **الـ ID**: `{user_id}`\n"
            welcome_message_to_admin += f"📝 **البايو**: {user_bio}\n" # هذا سيبقى "لا يوجد بايو" في معظم الحالات

            if photo_file_id:
                bot.send_photo(ADMIN_ID, photo_file_id, caption=welcome_message_to_admin, parse_mode='Markdown')
            else:
                bot.send_message(ADMIN_ID, welcome_message_to_admin, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"فشل في إرسال تفاصيل المستخدم الجديد إلى الأدمن: {e}")

    welcome_message = f"👋 **أهلاً بك يا {user_name}!**\n\n"
    welcome_message += f"〽️ أنا بوت متخصص في استضافة وتشغيل بوتات بايثون 🎗.\n"
    welcome_message += "يمكنك رفع ملفات بوتاتك بصيغة `.py` أو `.zip` وسأقوم بتشغيلها لك تلقائيًا.\n\n"
    welcome_message += "👇 **استخدم الأزرار أدناه للتحكم في البوت:**"

    # واجهة المستخدم الاحترافية - الرد بصورة واسم المستخدم
    if photo_file_id:
        bot.send_photo(message.chat.id, photo_file_id, caption=welcome_message, reply_markup=create_main_menu(user_id), parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, welcome_message, reply_markup=create_main_menu(user_id), parse_mode='Markdown')

# --- أوامر إذاعة الرسائل ---
@bot.callback_query_handler(func=lambda call: call.data == 'broadcast')
def broadcast_callback(call):
    """يعالج طلب المطور لإذاعة رسالة."""
    if call.from_user.id == ADMIN_ID:
        bot.send_message(call.message.chat.id, "📢 **أرسل الرسالة التي تريد إذاعتها لجميع المستخدمين:**")
        bot.register_next_step_handler(call.message, process_broadcast_message)
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

def process_broadcast_message(message):
    """يرسل الرسالة الإذاعية إلى جميع المستخدمين النشطين."""
    if message.from_user.id == ADMIN_ID:
        broadcast_message = message.text
        success_count = 0
        fail_count = 0

        # جلب المستخدمين النشطين من قاعدة البيانات لضمان الشمولية
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute('SELECT user_id FROM active_users')
        users_to_broadcast = [row[0] for row in c.fetchall()]
        conn.close()

        for user_id in users_to_broadcast:
            try:
                bot.send_message(user_id, broadcast_message)
                success_count += 1
            except Exception as e:
                logger.error(f"فشل في إرسال الرسالة إلى المستخدم {user_id}: {e}")
                fail_count += 1

        bot.send_message(message.chat.id, f"✅ **تم إرسال الرسالة إلى {success_count} مستخدم.**\n❌ **فشل إرسال الرسالة إلى {fail_count} مستخدم.**")
    else:
        bot.send_message(message.chat.id, "⚠️ **أنت لست المطور.**")

# --- تقارير وإحصائيات ---
@bot.callback_query_handler(func=lambda call: call.data == 'security_report')
def security_report_callback(call):
    """يعرض تقرير الأمان للمطور (على الرغم من أن الحماية معطلة، لكن الميزة موجودة)."""
    if call.from_user.id == ADMIN_ID:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM banned_users')
        banned_count = c.fetchone()[0]
        
        c.execute('SELECT user_id, reason, file_name, timestamp FROM user_warnings ORDER BY timestamp DESC LIMIT 20') 
        recent_warnings = c.fetchall()
        
        conn.close()
        
        report = f"📊 **تقرير الأمان** 🔐\n\n"
        report += f"👥 **عدد المستخدمين المحظورين**: `{banned_count}`\n\n"
        
        if recent_warnings:
            report += "⚠️ **آخر التحذيرات والأنشطة المشبوهة:**\n"
            for user_id, reason, file_name, timestamp in recent_warnings:
                dt = datetime.fromisoformat(timestamp)
                formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                report += f"- **المستخدم**: `{user_id}`\n"
                report += f"  **السبب**: `{reason}`\n"
                if file_name:
                    report += f"  **الملف**: `{file_name}`\n"
                report += f"  **الوقت**: `{formatted_time}`\n\n"
        else:
            report += "✅ **لا توجد تحذيرات أو أنشطة مشبوهة مسجلة حالياً.**"
        
        bot.send_message(call.message.chat.id, report, parse_mode='Markdown')
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

@bot.callback_query_handler(func=lambda call: call.data == 'speed')
def bot_speed_info(call):
    """يقوم بفحص سرعة استجابة البوت."""
    try:
        start_time = time.time()
        # استخدام get_me() بدلاً من requests.get() للحصول على سرعة استجابة API Telegram مباشرة
        bot.get_me() 
        latency = time.time() - start_time
        bot.send_message(call.message.chat.id, f"⚡ **سرعة البوت**: `{latency:.2f}` ثانية.")
    except Exception as e:
        logger.error(f"حدث خطأ أثناء فحص سرعة البوت: {e}")
        bot.send_message(call.message.chat.id, f"❌ **حدث خطأ أثناء فحص سرعة البوت**: {e}")

@bot.callback_query_handler(func=lambda call: call.data == 'upload')
def ask_to_upload_file(call):
    """يطلب من المستخدم إرسال ملف البوت."""
    user_id = call.from_user.id
    
    if user_id in banned_users:
        bot.send_message(call.message.chat.id, "⛔ **أنت محظور من استخدام هذا البوت.**")
        return
    
    if bot_locked:
        bot.send_message(call.message.chat.id, "⚠️ **البوت مقفل حالياً.** الرجاء التواصل مع المطور @VR_SX.")
        return
        
    bot.send_message(call.message.chat.id, "📄 **من فضلك، أرسل ملف البوت الخاص بك** (بصيغة `.py` أو `.zip`).")

@bot.callback_query_handler(func=lambda call: call.data == 'stats')
def stats_menu(call):
    """يعرض إحصائيات عامة عن البوت."""
    user_id = call.from_user.id
    # هذه الإحصائيات متاحة الآن لجميع المستخدمين
    
    total_uploaded_files = sum(len(files) for files in user_files.values())
    total_active_users = len(active_users)
    banned_users_count = len(banned_users)
    
    running_bots_count = 0
    for process_key, p_info in bot_processes.items():
        if p_info.get('process') and p_info['process'].poll() is None:
            running_bots_count += 1

    stats_message = f"📊 **إحصائيات البوت:**\n\n"
    stats_message += f"📂 **عدد الملفات/البوتات المرفوعة الكلي**: `{total_uploaded_files}`\n"
    stats_message += f"🟢 **عدد البوتات قيد التشغيل حالياً**: `{running_bots_count}`\n"
    stats_message += f"👥 **المستخدمين النشطين**: `{total_active_users}`\n"
    stats_message += f"🚫 **المستخدمين المحظورين**: `{banned_users_count}`"
    
    bot.send_message(call.message.chat.id, stats_message, parse_mode='Markdown')

# --- إدارة قفل البوت ---
@bot.callback_query_handler(func=lambda call: call.data == 'lock_bot')
def lock_bot_callback(call):
    """يقفل البوت ليمنع المستخدمين من استخدامه."""
    if call.from_user.id == ADMIN_ID:
        global bot_locked
        bot_locked = True
        bot.send_message(call.message.chat.id, "🔒 **تم قفل البوت بنجاح.** لن يتمكن المستخدمون من رفع ملفات جديدة أو استخدام بعض الميزات.")
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

@bot.callback_query_handler(func=lambda call: call.data == 'unlock_bot')
def unlock_bot_callback(call):
    """يفتح البوت ليسمح للمستخدمين باستخدامه."""
    if call.from_user.id == ADMIN_ID:
        global bot_locked
        bot_locked = False
        bot.send_message(call.message.chat.id, "🔓 **تم فتح البوت بنجاح.** يمكن للمستخدمين الآن رفع الملفات واستخدام جميع الميزات.")
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

# --- إدارة المستخدمين (قائمة فرعية) ---
@bot.callback_query_handler(func=lambda call: call.data == 'manage_users')
def manage_users_menu(call):
    """يعرض قائمة إدارة المستخدمين."""
    if call.from_user.id == ADMIN_ID:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton('🔨 حظر مستخدم', callback_data='ban_user_menu'))
        markup.add(types.InlineKeyboardButton('🔓 إلغاء حظر', callback_data='unban_user_menu'))
        markup.add(types.InlineKeyboardButton('ℹ️ معلومات مستخدم', callback_data='get_user_info_menu'))
        markup.add(types.InlineKeyboardButton('🚫 حظر المستخدمين الجدد', callback_data='block_new_users'))
        markup.add(types.InlineKeyboardButton('✅ السماح للمستخدمين الجدد', callback_data='unblock_new_users'))
        markup.add(types.InlineKeyboardButton('📋 قائمة المستخدمين المحظورين', callback_data='list_banned_users_cmd'))
        markup.add(types.InlineKeyboardButton('👥 قائمة المستخدمين النشطين', callback_data='list_active_users_cmd'))
        markup.add(types.InlineKeyboardButton('⚠️ تحذير مستخدم', callback_data='warn_user_menu'))
        markup.add(types.InlineKeyboardButton('🧹 مسح تحذيرات مستخدم', callback_data='clear_user_warnings_menu')) # زر جديد لمسح التحذيرات
        markup.add(types.InlineKeyboardButton('⬅️ العودة للقائمة الرئيسية', callback_data='main_menu'))
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                              text="⚙️ **لوحة تحكم إدارة المستخدمين:**", reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

@bot.callback_query_handler(func=lambda call: call.data == 'main_menu')
def back_to_main_menu(call):
    """يعيد المستخدم إلى القائمة الرئيسية."""
    user_id = call.from_user.id
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                          text="👋 **أهلاً بك مرة أخرى!**\n\n👇 **استخدم الأزرار أدناه للتحكم في البوت:**",
                          reply_markup=create_main_menu(user_id), parse_mode='Markdown')

# --- وظائف حظر/إلغاء حظر المستخدمين ---
@bot.callback_query_handler(func=lambda call: call.data == 'ban_user_menu')
def ban_user_menu(call):
    """يطلب معرف المستخدم لحظره."""
    if call.from_user.id == ADMIN_ID:
        bot.send_message(call.message.chat.id, "🔨 **أدخل معرف المستخدم (User ID) الذي تريد حظره:**")
        bot.register_next_step_handler(call.message, process_ban_user_id)
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

def process_ban_user_id(message):
    """يعالج معرف المستخدم للحظر ويطلب السبب."""
    if message.from_user.id == ADMIN_ID:
        try:
            user_to_ban_id = int(message.text.strip())
            if user_to_ban_id == ADMIN_ID:
                bot.send_message(message.chat.id, "❌ **لا يمكنك حظر نفسك!**")
                return
            bot.send_message(message.chat.id, f"📝 **أدخل سبب حظر المستخدم** `{user_to_ban_id}`:")
            bot.register_next_step_handler(message, process_ban_user_reason, user_to_ban_id)
        except ValueError:
            bot.send_message(message.chat.id, "❌ **معرف مستخدم غير صالح.** يرجى إدخال رقم صحيح.")
    else:
        bot.send_message(message.chat.id, "⚠️ **أنت لست المطور.**")

def process_ban_user_reason(message, user_to_ban_id):
    """يقوم بحظر المستخدم بالسبب المحدد."""
    if message.from_user.id == ADMIN_ID:
        reason = message.text.strip()
        if not reason:
            reason = "لم يتم تحديد سبب."
        
        ban_user(user_to_ban_id, reason)
        bot.send_message(message.chat.id, f"✅ **تم حظر المستخدم** `{user_to_ban_id}` **بنجاح.**\n**السبب**: {reason}")
        try:
            bot.send_message(user_to_ban_id, f"⛔ **لقد تم حظرك من استخدام هذا البوت.**\n**السبب**: {reason}")
        except Exception as e:
            logger.error(f"فشل في إرسال إشعار الحظر للمستخدم {user_to_ban_id}: {e}")
    else:
        bot.send_message(message.chat.id, "⚠️ **أنت لست المطور.**")

@bot.callback_query_handler(func=lambda call: call.data == 'unban_user_menu')
def unban_user_menu(call):
    """يطلب معرف المستخدم لإلغاء حظره."""
    if call.from_user.id == ADMIN_ID:
        bot.send_message(call.message.chat.id, "🔓 **أدخل معرف المستخدم (User ID) الذي تريد إلغاء حظره:**")
        bot.register_next_step_handler(call.message, process_unban_user_id)
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

def process_unban_user_id(message):
    """يقوم بإلغاء حظر المستخدم المحدد."""
    if message.from_user.id == ADMIN_ID:
        try:
            user_to_unban_id = int(message.text.strip())
            if unban_user(user_to_unban_id):
                bot.send_message(message.chat.id, f"✅ **تم إلغاء حظر المستخدم** `{user_to_unban_id}` **بنجاح.**")
                try:
                    bot.send_message(user_to_unban_id, "🎉 **لقد تم إلغاء حظرك من استخدام هذا البوت!** يمكنك الآن استخدام جميع الميزات.")
                except Exception as e:
                    logger.error(f"فشل في إرسال إشعار إلغاء الحظر للمستخدم {user_to_unban_id}: {e}")
            else:
                bot.send_message(message.chat.id, f"❌ **المستخدم** `{user_to_unban_id}` **ليس محظوراً.**")
        except ValueError:
            bot.send_message(message.chat.id, "❌ **معرف مستخدم غير صالح.** يرجى إدخال رقم صحيح.")
    else:
        bot.send_message(message.chat.id, "⚠️ **أنت لست المطور.**")

@bot.callback_query_handler(func=lambda call: call.data == 'list_banned_users_cmd')
def list_banned_users_cmd(call):
    """يعرض قائمة بالمستخدمين المحظورين."""
    if call.from_user.id == ADMIN_ID:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute('SELECT user_id, reason, ban_date FROM banned_users')
        banned_users_data = c.fetchall()
        conn.close()

        if banned_users_data:
            response = "🚫 **قائمة المستخدمين المحظورين:**\n\n"
            for user_id, reason, ban_date in banned_users_data:
                response += f"🆔 **ID**: `{user_id}`\n"
                response += f"📝 **السبب**: `{reason}`\n"
                response += f"🗓️ **تاريخ الحظر**: `{datetime.fromisoformat(ban_date).strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
        else:
            response = "✅ **لا توجد مستخدمون محظورون حالياً.**"
        bot.send_message(call.message.chat.id, response, parse_mode='Markdown')
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

@bot.callback_query_handler(func=lambda call: call.data == 'list_active_users_cmd')
def list_active_users_cmd(call):
    """يعرض قائمة بالمستخدمين النشطين."""
    if call.from_user.id == ADMIN_ID:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute('SELECT user_id FROM active_users')
        active_users_data = c.fetchall()
        conn.close()

        if active_users_data:
            response = "👥 **قائمة المستخدمين النشطين:**\n\n"
            for user_id, in active_users_data:
                response += f"- `{user_id}`\n"
            response += f"\n**الإجمالي**: `{len(active_users_data)}` مستخدم."
        else:
            response = "❌ **لا توجد مستخدمون نشطون حالياً.**"
        bot.send_message(call.message.chat.id, response, parse_mode='Markdown')
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

@bot.callback_query_handler(func=lambda call: call.data == 'warn_user_menu')
def warn_user_menu(call):
    """يطلب معرف المستخدم لتحذيره."""
    if call.from_user.id == ADMIN_ID:
        bot.send_message(call.message.chat.id, "⚠️ **أدخل معرف المستخدم (User ID) الذي تريد تحذيره:**")
        bot.register_next_step_handler(call.message, process_warn_user_id)
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

def process_warn_user_id(message):
    """يعالج معرف المستخدم للتحذير ويطلب السبب."""
    if message.from_user.id == ADMIN_ID:
        try:
            user_to_warn_id = int(message.text.strip())
            bot.send_message(message.chat.id, f"📝 **أدخل سبب تحذير المستخدم** `{user_to_warn_id}`:")
            bot.register_next_step_handler(message, process_warn_user_reason, user_to_warn_id)
        except ValueError:
            bot.send_message(message.chat.id, "❌ **معرف مستخدم غير صالح.** يرجى إدخال رقم صحيح.")
    else:
        bot.send_message(message.chat.id, "⚠️ **أنت لست المطور.**")

def process_warn_user_reason(message, user_to_warn_id):
    """يقوم بتحذير المستخدم بالسبب المحدد."""
    if message.from_user.id == ADMIN_ID:
        reason = message.text.strip()
        if not reason:
            reason = "لم يتم تحديد سبب."
        
        log_user_warning(user_to_warn_id, reason, file_name="تحذير يدوي من الأدمن")
        bot.send_message(message.chat.id, f"✅ **تم تحذير المستخدم** `{user_to_warn_id}` **بنجاح.**\n**السبب**: {reason}")
        try:
            bot.send_message(user_to_warn_id, f"⚠️ **لقد تلقيت تحذيراً من المطور!**\n**السبب**: {reason}\n**تنبيه**: تكرار المخالفات قد يؤدي إلى الحظر.")
        except Exception as e:
            logger.error(f"فشل في إرسال إشعار التحذير للمستخدم {user_to_warn_id}: {e}")
    else:
        bot.send_message(message.chat.id, "⚠️ **أنت لست المطور.**")

@bot.callback_query_handler(func=lambda call: call.data == 'clear_user_warnings_menu')
def clear_user_warnings_menu(call):
    """يطلب معرف المستخدم لمسح تحذيراته."""
    if call.from_user.id == ADMIN_ID:
        bot.send_message(call.message.chat.id, "🧹 **أدخل معرف المستخدم (User ID) لمسح تحذيراته:**")
        bot.register_next_step_handler(call.message, process_clear_user_warnings_id)
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

def process_clear_user_warnings_id(message):
    """يقوم بمسح تحذيرات المستخدم المحدد من قاعدة البيانات."""
    if message.from_user.id == ADMIN_ID:
        try:
            user_id = int(message.text.strip())
            conn = sqlite3.connect('bot_data.db')
            c = conn.cursor()
            c.execute('DELETE FROM user_warnings WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
            
            if user_id in user_warnings:
                del user_warnings[user_id]
            
            bot.send_message(message.chat.id, f"✅ **تم مسح جميع التحذيرات للمستخدم** `{user_id}` **بنجاح.**")
            try:
                bot.send_message(user_id, "🧹 **تم مسح جميع التحذيرات المسجلة بحقك من قبل المطور.** يرجى الالتزام بالقواعد.")
            except Exception as e:
                logger.error(f"فشل في إرسال إشعار مسح التحذيرات للمستخدم {user_id}: {e}")
        except ValueError:
            bot.send_message(message.chat.id, "❌ **معرف مستخدم غير صالح.** يرجى إدخال رقم صحيح.")
    else:
        bot.send_message(message.chat.id, "⚠️ **أنت لست المطور.**")


@bot.callback_query_handler(func=lambda call: call.data == 'block_new_users')
def block_new_users_callback(call):
    """يمنع المستخدمين الجدد من الانضمام."""
    if call.from_user.id == ADMIN_ID:
        global block_new_users
        block_new_users = True
        bot.send_message(call.message.chat.id, "🚫 **تم تفعيل منع المستخدمين الجدد من الانضمام.**")
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

@bot.callback_query_handler(func=lambda call: call.data == 'unblock_new_users')
def unblock_new_users_callback(call):
    """يسمح للمستخدمين الجدد بالانضمام."""
    if call.from_user.id == ADMIN_ID:
        global block_new_users
        block_new_users = False
        bot.send_message(call.message.chat.id, "✅ **تم تعطيل منع المستخدمين الجدد.** يمكنهم الانضمام الآن.")
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

@bot.callback_query_handler(func=lambda call: call.data == 'get_user_info_menu')
def get_user_info_menu(call):
    """يطلب معرف المستخدم لعرض معلوماته."""
    if call.from_user.id == ADMIN_ID:
        bot.send_message(call.message.chat.id, "ℹ️ **أدخل معرف المستخدم (User ID) الذي تريد عرض معلوماته:**")
        bot.register_next_step_handler(call.message, process_get_user_info_id)
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

def process_get_user_info_id(message):
    """يعرض معلومات المستخدم."""
    if message.from_user.id == ADMIN_ID:
        try:
            target_user_id = int(message.text.strip())
            
            user_info = f"ℹ️ **معلومات المستخدم** `{target_user_id}`:\n\n"
            
            # حالة الحظر
            conn = sqlite3.connect('bot_data.db')
            c = conn.cursor()
            c.execute('SELECT reason, ban_date FROM banned_users WHERE user_id = ?', (target_user_id,))
            ban_data = c.fetchone()
            if ban_data:
                user_info += f"🚫 **الحالة**: محظور\n"
                user_info += f"  **السبب**: `{ban_data[0]}`\n"
                user_info += f"  **تاريخ الحظر**: `{datetime.fromisoformat(ban_data[1]).strftime('%Y-%m-%d %H:%M:%S')}`\n"
            else:
                user_info += f"✅ **الحالة**: غير محظور\n"
            
            # حالة النشاط
            if target_user_id in active_users:
                user_info += "🟢 **حالة النشاط**: نشط\n"
            else:
                user_info += "⚪ **حالة النشاط**: غير نشط (ربما لم يبدأ البوت مؤخرًا)\n"

            # الملفات المرفوعة
            if target_user_id in user_files and user_files[target_user_id]:
                user_info += f"📂 **الملفات المرفوعة**: `{len(user_files[target_user_id])}` ملفات\n"
                for i, file_data in enumerate(user_files[target_user_id]):
                    user_info += f"  - `{file_data['file_name']}` (المسار: `{file_data['folder_path']}`)\n"
            else:
                user_info += "📂 **الملفات المرفوعة**: لا يوجد\n"

            # البوتات قيد التشغيل
            running_user_bots = [p_info for p_key, p_info in bot_processes.items() if p_info['owner_id'] == target_user_id and p_info['process'].poll() is None]
            if running_user_bots:
                user_info += f"🟢 **البوتات قيد التشغيل**: `{len(running_user_bots)}` بوت\n"
                for i, bot_data in enumerate(running_user_bots):
                    user_info += f"  - `{bot_data['file_name']}` (يوزر البوت: `{bot_data.get('bot_username', 'غير محدد')}`)\n"
            else:
                user_info += "🟢 **البوتات قيد التشغيل**: لا يوجد\n"
            
            # التحذيرات
            if target_user_id in user_warnings and user_warnings[target_user_id]:
                user_info += f"⚠️ **التحذيرات**: `{len(user_warnings[target_user_id])}` تحذير\n"
                for i, warning_data in enumerate(user_warnings[target_user_id]):
                    dt = datetime.fromisoformat(warning_data['timestamp'])
                    formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                    user_info += f"  - **السبب**: `{warning_data['reason']}`\n"
                    if warning_data['file_name']:
                        user_info += f"    **الملف**: `{warning_data['file_name']}`\n"
                    user_info += f"    **الوقت**: `{formatted_time}`\n"
            else:
                user_info += "⚠️ **التحذيرات**: لا يوجد\n"

            conn.close()
            bot.send_message(message.chat.id, user_info, parse_mode='Markdown')
        except ValueError:
            bot.send_message(message.chat.id, "❌ **معرف مستخدم غير صالح.** يرجى إدخال رقم صحيح.")
        except Exception as e:
            logger.error(f"خطأ في جلب معلومات المستخدم {target_user_id}: {e}")
            bot.send_message(message.chat.id, f"❌ **حدث خطأ أثناء جلب معلومات المستخدم**: {e}")
    else:
        bot.send_message(message.chat.id, "⚠️ **أنت لست المطور.**")

# --- إدارة البوتات المستضافة (قائمة فرعية جديدة) ---
@bot.callback_query_handler(func=lambda call: call.data == 'manage_hosted_bots')
def manage_hosted_bots_menu(call):
    """يعرض قائمة إدارة البوتات المستضافة."""
    if call.from_user.id == ADMIN_ID:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton('📋 عرض جميع البوتات', callback_data='list_all_bots'))
        markup.add(types.InlineKeyboardButton('🛑 إيقاف بوت', callback_data='stop_specific_bot'))
        markup.add(types.InlineKeyboardButton('▶️ تشغيل بوت', callback_data='start_specific_bot'))
        markup.add(types.InlineKeyboardButton('🗑️ حذف بوت', callback_data='delete_specific_bot'))
        markup.add(types.InlineKeyboardButton('⬅️ العودة للقائمة الرئيسية', callback_data='main_menu'))
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                              text="⚙️ **لوحة تحكم إدارة البوتات المستضافة:**", reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

@bot.callback_query_handler(func=lambda call: call.data == 'list_all_bots')
def list_all_bots_cmd(call):
    """يعرض قائمة بجميع البوتات المرفوعة وحالتها."""
    if call.from_user.id == ADMIN_ID:
        response = "🤖 **قائمة بجميع البوتات المرفوعة:**\n\n"
        has_bots = False
        
        for owner_id, files_data in user_files.items():
            for file_data in files_data:
                has_bots = True
                file_name = file_data['file_name']
                folder_path = file_data['folder_path']
                bot_username = file_data.get('bot_username', 'غير محدد')
                
                # التحقق مما إذا كان البوت قيد التشغيل حاليًا
                is_running = False
                process_key = f"{owner_id}_{os.path.basename(folder_path)}_{file_name}"
                if process_key in bot_processes and bot_processes[process_key]['process'].poll() is None:
                    is_running = True
                
                status = "🟢 قيد التشغيل" if is_running else "🔴 متوقف"
                
                response += f"👤 **المستخدم**: `{owner_id}`\n"
                response += f"📄 **الملف**: `{file_name}`\n"
                response += f"🔗 **المسار**: `{folder_path}`\n"
                response += f"📌 **يوزر البوت**: `{bot_username}`\n"
                response += f"📊 **الحالة**: {status}\n\n"
        
        if not has_bots:
            response = "❌ **لا توجد بوتات مرفوعة حالياً.**"
        
        bot.send_message(call.message.chat.id, response, parse_mode='Markdown')
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

def prompt_for_bot_to_manage(call, action):
    """يطلب من المطور إدخال معرف البوت أو اسمه لإدارة بوت معين."""
    if call.from_user.id == ADMIN_ID:
        bot.send_message(call.message.chat.id, f"📝 **أدخل معرف المستخدم (User ID) الذي يملك البوت واسم الملف الذي تريد {action}ه.**\nمثال: `123456789 bot_script.py`")
        bot.register_next_step_handler(call.message, process_bot_management_input, action)
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

@bot.callback_query_handler(func=lambda call: call.data == 'stop_specific_bot')
def stop_specific_bot_cmd(call):
    prompt_for_bot_to_manage(call, 'إيقاف')

@bot.callback_query_handler(func=lambda call: call.data == 'start_specific_bot')
def start_specific_bot_cmd(call):
    prompt_for_bot_to_manage(call, 'تشغيل')

@bot.callback_query_handler(func=lambda call: call.data == 'delete_specific_bot')
def delete_specific_bot_cmd(call):
    prompt_for_bot_to_manage(call, 'حذف')

def process_bot_management_input(message, action):
    """يعالج إدخال المطور لإدارة بوت معين (إيقاف، تشغيل، حذف)."""
    if message.from_user.id == ADMIN_ID:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.send_message(message.chat.id, "❌ **صيغة الأمر غير صحيحة.** يرجى استخدام: `User ID اسم_الملف`")
            return

        try:
            owner_id = int(parts[0])
            file_name = parts[1].strip()
        except ValueError:
            bot.send_message(message.chat.id, "❌ **معرف المستخدم غير صالح.** يرجى إدخال رقم صحيح.")
            return
        
        # البحث عن المسار الصحيح للملف
        target_folder_path = None
        if owner_id in user_files:
            for file_info in user_files[owner_id]:
                if file_info['file_name'] == file_name:
                    target_folder_path = file_info['folder_path']
                    break

        if not target_folder_path:
            bot.send_message(message.chat.id, f"❌ **لم يتم العثور على البوت** `{file_name}` **الخاص بالمستخدم** `{owner_id}`.")
            return

        process_key = f"{owner_id}_{os.path.basename(target_folder_path)}_{file_name}"

        if action == 'إيقاف':
            if process_key in bot_processes and bot_processes[process_key]['process'].poll() is None:
                try:
                    # قتل العملية ومجموعتها
                    os.killpg(os.getpgid(bot_processes[process_key]['process'].pid), signal.SIGTERM)
                    # الانتظار قليلاً للتأكد من انتهاء العملية
                    time.sleep(1)
                    if bot_processes[process_key]['process'].poll() is None: # إذا لم تتوقف، أرسل SIGKILL
                         os.killpg(os.getpgid(bot_processes[process_key]['process'].pid), signal.SIGKILL)
                    
                    bot_processes[process_key]['process'].wait() # انتظر حتى تنتهي العملية تمامًا
                    del bot_processes[process_key]
                    remove_bot_process_state(process_key) # إزالة من قاعدة البيانات
                    bot.send_message(message.chat.id, f"✅ **تم إيقاف البوت** `{file_name}` **الخاص بالمستخدم** `{owner_id}` **بنجاح.**")
                    try:
                        bot.send_message(owner_id, f"🛑 **قام المطور بإيقاف البوت الخاص بك**: `{file_name}`")
                    except Exception as e:
                        logger.error(f"فشل إرسال إشعار إيقاف البوت للمستخدم {owner_id}: {e}")
                except Exception as e:
                    logger.error(f"خطأ أثناء إيقاف البوت {process_key}: {e}")
                    bot.send_message(message.chat.id, f"❌ **فشل إيقاف البوت** `{file_name}`: `{e}`")
            else:
                bot.send_message(message.chat.id, f"ℹ️ **البوت** `{file_name}` **الخاص بالمستخدم** `{owner_id}` **ليس قيد التشغيل حالياً.**")
        
        elif action == 'تشغيل':
            if process_key in bot_processes and bot_processes[process_key]['process'].poll() is None:
                bot.send_message(message.chat.id, f"ℹ️ **البوت** `{file_name}` **الخاص بالمستخدم** `{owner_id}` **قيد التشغيل بالفعل.**")
            else:
                main_script_path = os.path.join(target_folder_path, file_name)
                if os.path.exists(main_script_path):
                    try:
                        # إنشاء ملفات سجل جديدة لكل تشغيل
                        log_file_stdout_path = os.path.join(target_folder_path, f'{file_name}.stdout.log')
                        log_file_stderr_path = os.path.join(target_folder_path, f'{file_name}.stderr.log')

                        process = subprocess.Popen(
                            ['python3', main_script_path],
                            cwd=target_folder_path,
                            stdout=open(log_file_stdout_path, 'a'),
                            stderr=open(log_file_stderr_path, 'a'),
                            preexec_fn=os.setsid
                        )
                        bot_processes[process_key] = {
                            'process': process,
                            'folder_path': target_folder_path,
                            'bot_username': user_files[owner_id][0].get('bot_username'), # يفترض أن كل الملفات في نفس مجلد البوت تستخدم نفس اليوزر
                            'file_name': file_name,
                            'owner_id': owner_id,
                            'log_file_stdout': log_file_stdout_path,
                            'log_file_stderr': log_file_stderr_path,
                            'start_time': datetime.now()
                        }
                        save_bot_process_state(process_key, target_folder_path, user_files[owner_id][0].get('bot_username'), file_name, owner_id, log_file_stdout_path, log_file_stderr_path, datetime.now())
                        bot.send_message(message.chat.id, f"✅ **تم تشغيل البوت** `{file_name}` **الخاص بالمستخدم** `{owner_id}` **بنجاح.**")
                        try:
                            bot.send_message(owner_id, f"▶️ **قام المطور بإعادة تشغيل البوت الخاص بك**: `{file_name}`")
                        except Exception as e:
                            logger.error(f"فشل إرسال إشعار تشغيل البوت للمستخدم {owner_id}: {e}")
                    except Exception as e:
                        logger.error(f"خطأ أثناء تشغيل البوت {file_name} للمستخدم {owner_id}: {e}")
                        bot.send_message(message.chat.id, f"❌ **فشل تشغيل البوت** `{file_name}`: `{e}`")
                else:
                    bot.send_message(message.chat.id, f"❌ **ملف البوت** `{file_name}` **غير موجود في المسار:** `{target_folder_path}`.")

        elif action == 'حذف':
            # إيقاف البوت أولاً إذا كان قيد التشغيل
            if process_key in bot_processes and bot_processes[process_key]['process'].poll() is None:
                try:
                    os.killpg(os.getpgid(bot_processes[process_key]['process'].pid), signal.SIGTERM)
                    time.sleep(1)
                    if bot_processes[process_key]['process'].poll() is None:
                         os.killpg(os.getpgid(bot_processes[process_key]['process'].pid), signal.SIGKILL)
                    bot_processes[process_key]['process'].wait()
                    del bot_processes[process_key]
                    remove_bot_process_state(process_key)
                except Exception as e:
                    logger.error(f"خطأ أثناء إيقاف البوت {process_key} قبل الحذف: {e}")
                    bot.send_message(message.chat.id, f"⚠️ **حدث خطأ أثناء إيقاف البوت قبل الحذف**: `{e}`. سيتم محاولة الحذف.")
            
            # حذف الملفات والمجلد
            if os.path.exists(target_folder_path):
                try:
                    shutil.rmtree(target_folder_path)
                    
                    # إزالة من user_files ومن قاعدة البيانات
                    user_files[owner_id] = [f for f in user_files[owner_id] if not (f['file_name'] == file_name and f['folder_path'] == target_folder_path)]
                    if not user_files[owner_id]: # إذا لم يتبق للمستخدم أي ملفات
                        del user_files[owner_id]
                    
                    remove_user_file_db(owner_id, file_name, target_folder_path)

                    bot.send_message(message.chat.id, f"✅ **تم حذف البوت** `{file_name}` **الخاص بالمستخدم** `{owner_id}` **بنجاح.**")
                    try:
                        bot.send_message(owner_id, f"🗑️ **قام المطور بحذف البوت الخاص بك**: `{file_name}`")
                    except Exception as e:
                        logger.error(f"فشل إرسال إشعار حذف البوت للمستخدم {owner_id}: {e}")
                except Exception as e:
                    logger.error(f"خطأ أثناء حذف مجلد البوت {target_folder_path}: {e}")
                    bot.send_message(message.chat.id, f"❌ **فشل حذف مجلد البوت** `{file_name}`: `{e}`")
            else:
                bot.send_message(message.chat.id, f"❌ **مجلد البوت** `{target_folder_path}` **غير موجود أو سبق حذفه.**")
    else:
        bot.send_message(message.chat.id, "⚠️ **أنت لست المطور.**")

# --- إحصائيات الخادم (ميزة جديدة) ---
@bot.callback_query_handler(func=lambda call: call.data == 'server_stats')
def server_stats_cmd(call):
    """يعرض إحصائيات استخدام الخادم."""
    if call.from_user.id == ADMIN_ID:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory_info = psutil.virtual_memory()
        disk_info = psutil.disk_usage('/')
        
        # معلومات العمليات الجارية
        running_bots_count = 0
        total_bot_uptime = timedelta(0)
        for process_key, p_info in bot_processes.items():
            if p_info.get('process') and p_info['process'].poll() is None:
                running_bots_count += 1
                if 'start_time' in p_info and isinstance(p_info['start_time'], datetime):
                    total_bot_uptime += (datetime.now() - p_info['start_time'])

        stats_message = f"🖥️ **إحصائيات الخادم:**\n\n"
        stats_message += f"📊 **استخدام المعالج (CPU)**: `{cpu_percent}%`\n"
        stats_message += f"🧠 **استخدام الذاكرة (RAM)**: `{memory_info.percent}%` (`{memory_info.used / (1024**3):.2f}` GB / `{memory_info.total / (1024**3):.2f}` GB)\n"
        stats_message += f"💽 **استخدام القرص (Disk)**: `{disk_info.percent}%` (`{disk_info.used / (1024**3):.2f}` GB / `{disk_info.total / (1024**3):.2f}` GB)\n"
        stats_message += f"🟢 **البوتات قيد التشغيل**: `{running_bots_count}`\n"
        stats_message += f"⏱️ **إجمالي وقت تشغيل البوتات**: `{str(total_bot_uptime).split('.')[0]}`\n\n" # إزالة أجزاء الثانية
        
        bot.send_message(call.message.chat.id, stats_message, parse_mode='Markdown')
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

# --- أدوات المطور (ميزة جديدة) ---
@bot.callback_query_handler(func=lambda call: call.data == 'dev_tools')
def dev_tools_menu(call):
    """يعرض قائمة أدوات المطور."""
    if call.from_user.id == ADMIN_ID:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton('📥 تثبيت مكتبة بايثون', callback_data='install_library_menu'))
        markup.add(types.InlineKeyboardButton('⬅️ العودة للقائمة الرئيسية', callback_data='main_menu'))
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                              text="🛠️ **أدوات المطور:**", reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

# --- دعم تثبيت مكتبات بايثون (ميزة جديدة) ---
@bot.message_handler(commands=['install'])
def install_library_command(message):
    """يعالج أمر /install لتثبيت مكتبات بايثون."""
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "⚠️ **أنت لست المطور. لا يمكنك استخدام هذا الأمر.**")
        return

    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        bot.send_message(message.chat.id, "❌ **الاستخدام الصحيح**: `/install <اسم_المكتبة>`")
        return

    library_name = command_parts[1].strip()
    bot.send_message(message.chat.id, f"🔄 **جارٍ تثبيت المكتبة** `{library_name}`... قد يستغرق هذا بعض الوقت.")

    try:
        # استخدام pip في بيئة التشغيل الحالية
        process = subprocess.run(['pip3', 'install', library_name], capture_output=True, text=True, check=True)
        bot.send_message(message.chat.id, f"✅ **تم تثبيت المكتبة** `{library_name}` **بنجاح!**\n\n`{process.stdout}`")
    except subprocess.CalledProcessError as e:
        bot.send_message(message.chat.id, f"❌ **فشل تثبيت المكتبة** `{library_name}`.\n\n**الخطأ**: `{e.stderr}`")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ **حدث خطأ غير متوقع أثناء التثبيت**: `{e}`")

@bot.callback_query_handler(func=lambda call: call.data == 'install_library_menu')
def install_library_menu_callback(call):
    """يطلب اسم المكتبة لتثبيتها من قائمة أدوات المطور."""
    if call.from_user.id == ADMIN_ID:
        bot.send_message(call.message.chat.id, "📥 **أدخل اسم المكتبة التي تريد تثبيتها:**\nمثال: `requests` أو `numpy`\n(سيتم تنفيذ الأمر `pip3 install <اسم المكتبة>`)")
        bot.register_next_step_handler(call.message, process_install_library_input)
    else:
        bot.send_message(call.message.chat.id, "⚠️ **أنت لست المطور.**")

def process_install_library_input(message):
    """يعالج اسم المكتبة المدخل من واجهة المستخدم لتثبيتها."""
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "⚠️ **أنت لست المطور. لا يمكنك استخدام هذا الأمر.**")
        return

    library_name = message.text.strip()
    if not library_name:
        bot.send_message(message.chat.id, "❌ **لم يتم إدخال اسم المكتبة.** يرجى المحاولة مرة أخرى.")
        return

    bot.send_message(message.chat.id, f"🔄 **جارٍ تثبيت المكتبة** `{library_name}`... قد يستغرق هذا بعض الوقت.")

    try:
        # استخدام pip في بيئة التشغيل الحالية
        process = subprocess.run(['pip3', 'install', library_name], capture_output=True, text=True, check=True)
        bot.send_message(message.chat.id, f"✅ **تم تثبيت المكتبة** `{library_name}` **بنجاح!**\n\n`{process.stdout}`")
    except subprocess.CalledProcessError as e:
        bot.send_message(message.chat.id, f"❌ **فشل تثبيت المكتبة** `{library_name}`.\n\n**الخطأ**: `{e.stderr}`")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ **حدث خطأ غير متوقع أثناء التثبيت**: `{e}`")

# --- معالجة الملفات المرفوعة ---
@bot.message_handler(content_types=['document'])
def handle_docs(message):
    """يعالج الملفات المرفوعة (py. و .zip)."""
    user_id = message.from_user.id

    if user_id in banned_users:
        bot.send_message(message.chat.id, "⛔ **أنت محظور من استخدام هذا البوت.**")
        return

    if bot_locked:
        bot.send_message(message.chat.id, "⚠️ **البوت مقفل حالياً.** الرجاء التواصل مع المطور @VR_SX.")
        return

    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    file_name = message.document.file_name

    logger.info(f"المستخدم {user_id} رفع ملف: {file_name}")

    if file_name.endswith('.py'):
        # فحص ملف بايثون
        is_safe, reason = is_safe_python_code(downloaded_file, user_id, file_name)
        if not is_safe:
            quarantine_file(downloaded_file, file_name, user_id, reason)
            bot.send_message(message.chat.id, f"⚠️ **تم رفض الملف!** تم اكتشاف كود مشبوه: `{reason}`. تم عزل الملف.")
            return

        # إنشاء مجلد جديد للبوت في uploaded_bots
        unique_folder_name = f"bot_{user_id}_{int(time.time())}"
        bot_folder_path = os.path.join(uploaded_files_dir, unique_folder_name)
        os.makedirs(bot_folder_path, exist_ok=True)
        
        main_script_path = os.path.join(bot_folder_path, file_name)
        with open(main_script_path, 'wb') as f:
            f.write(downloaded_file)
        
        # إضافة البوت إلى قائمة المستخدمين وملفاتهم
        if user_id not in user_files:
            user_files[user_id] = []
        user_files[user_id].append({'file_name': file_name, 'folder_path': bot_folder_path})
        save_user_file_db(user_id, file_name, bot_folder_path) # حفظ في قاعدة البيانات

        bot.send_message(message.chat.id, f"✅ **تم استقبال ملف البوت** `{file_name}` **بنجاح.** جاري محاولة تشغيله...")
        start_bot_process(user_id, file_name, bot_folder_path)

    elif file_name.endswith('.zip'):
        # حفظ الملف المؤقت لفك الضغط
        temp_zip_path = os.path.join(tempfile.gettempdir(), file_name)
        with open(temp_zip_path, 'wb') as f:
            f.write(downloaded_file)

        is_safe, reason = scan_zip_for_malicious_code(temp_zip_path, user_id)
        if not is_safe:
            quarantine_file(downloaded_file, file_name, user_id, reason)
            bot.send_message(message.chat.id, f"⚠️ **تم رفض الملف المضغوط!** تم اكتشاف كود مشبوه داخله: `{reason}`. تم عزل الملف.")
            os.remove(temp_zip_path) # حذف الملف المؤقت
            return

        # فك ضغط الملف في مجلد جديد
        unique_folder_name = f"bot_{user_id}_{int(time.time())}"
        bot_folder_path = os.path.join(uploaded_files_dir, unique_folder_name)
        os.makedirs(bot_folder_path, exist_ok=True)

        try:
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                zip_ref.extractall(bot_folder_path)
            bot.send_message(message.chat.id, f"✅ **تم استقبال وفك ضغط ملف البوت** `{file_name}` **بنجاح.** جاري البحث عن ملف بايثون رئيسي...")

            # البحث عن ملف .py رئيسي لتشغيله
            python_files = [f for f in os.listdir(bot_folder_path) if f.endswith('.py')]
            
            if not python_files:
                bot.send_message(message.chat.id, "❌ **لم يتم العثور على أي ملفات بايثون (.py) داخل الملف المضغوط.** يرجى التأكد من وجود ملف بايثون واحد على الأقل.")
                shutil.rmtree(bot_folder_path) # حذف المجلد الفارغ
                return
            elif len(python_files) == 1:
                main_script_name = python_files[0]
                # إضافة البوت إلى قائمة المستخدمين وملفاتهم
                if user_id not in user_files:
                    user_files[user_id] = []
                user_files[user_id].append({'file_name': main_script_name, 'folder_path': bot_folder_path})
                save_user_file_db(user_id, main_script_name, bot_folder_path) # حفظ في قاعدة البيانات

                bot.send_message(message.chat.id, f"🟢 **تم العثور على الملف الرئيسي:** `{main_script_name}`. جاري تشغيل البوت...")
                start_bot_process(user_id, main_script_name, bot_folder_path)
            else:
                # إذا كان هناك عدة ملفات .py، اطلب من المستخدم اختيار الرئيسي
                markup = types.InlineKeyboardMarkup()
                for py_file in python_files:
                    markup.add(types.InlineKeyboardButton(py_file, callback_data=f"select_main_script_{unique_folder_name}_{py_file}"))
                bot.send_message(message.chat.id, "❓ **تم العثور على عدة ملفات بايثون.** يرجى اختيار الملف الرئيسي للتشغيل:", reply_markup=markup)
                # تخزين مؤقت لربط المجلد بالملفات
                user_files[user_id].append({'file_name': None, 'folder_path': bot_folder_path, 'temp_files': python_files}) # إضافة temp_files هنا
                
        except zipfile.BadZipFile:
            bot.send_message(message.chat.id, "❌ **الملف المضغوط تالف أو غير صالح.**")
            if os.path.exists(bot_folder_path):
                shutil.rmtree(bot_folder_path)
        except Exception as e:
            logger.error(f"خطأ أثناء فك ضغط الملف {file_name} لـ user_id {user_id}: {e}")
            bot.send_message(message.chat.id, f"❌ **حدث خطأ أثناء فك ضغط الملف**: {e}")
        finally:
            os.remove(temp_zip_path) # حذف الملف المؤقت بعد الانتهاء

    else:
        bot.send_message(message.chat.id, "❌ **نوع الملف غير مدعوم.** يرجى رفع ملفات `.py` أو `.zip` فقط.")

def quarantine_file(file_content_bytes, file_name, user_id, reason):
    """
    يقوم بنقل الملف المشبوه إلى مجلد العزل ويرسل تنبيهًا للمطور.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    quarantined_file_path = os.path.join(quarantined_files_dir, f"{file_name}_user_{user_id}_{timestamp}.quarantined")
    with open(quarantined_file_path, 'wb') as f:
        f.write(file_content_bytes)
    
    logger.warning(f"تم عزل الملف المشبوه: {file_name} للمستخدم {user_id}. السبب: {reason}")
    notify_admins_of_potential_risk(user_id, reason, file_name, file_content_bytes)


@bot.callback_query_handler(func=lambda call: call.data.startswith('select_main_script_'))
def handle_main_script_selection(call):
    """يعالج اختيار المستخدم للملف الرئيسي في حالة ملفات ZIP المتعددة."""
    user_id = call.from_user.id
    
    # استخراج المعلومات من callback_data
    parts = call.data.split('_')
    # select_main_script_ {unique_folder_name} _ {file_name}
    folder_name_part_index = 4 # index of unique_folder_name part
    script_name_part_index = 5 # index of file_name part
    
    # إعادة بناء folder_name و script_name
    unique_folder_name_parts = []
    script_name_parts = []
    
    # Loop to reconstruct the unique_folder_name in case it contains underscores
    # Find the beginning of the actual script name, which is always .py
    script_start_index = -1
    for i, part in enumerate(parts):
        if part.endswith('.py'):
            script_start_index = i
            break
            
    if script_start_index == -1: # Fallback in case .py is not found (shouldn't happen)
        bot.send_message(user_id, "❌ **حدث خطأ غير متوقع في معالجة اختيار الملف.** يرجى المحاولة مرة أخرى.")
        return

    unique_folder_name = "_".join(parts[folder_name_part_index : script_start_index])
    main_script_name = "_".join(parts[script_start_index:])

    bot_folder_path = os.path.join(uploaded_files_dir, unique_folder_name)

    # تحديث معلومات الملف في user_files وقاعدة البيانات
    found = False
    if user_id in user_files:
        for i, file_data in enumerate(user_files[user_id]):
            # نبحث عن الإدخال المؤقت الذي قمنا بإنشائه عند رفع ZIP
            if file_data.get('folder_path') == bot_folder_path and file_data.get('file_name') is None:
                user_files[user_id][i]['file_name'] = main_script_name
                # إزالة temp_files لأنه لم يعد ضرورياً
                if 'temp_files' in user_files[user_id][i]:
                    del user_files[user_id][i]['temp_files']
                
                save_user_file_db(user_id, main_script_name, bot_folder_path)
                found = True
                break

    if found:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                              text=f"✅ **تم اختيار الملف الرئيسي:** `{main_script_name}`. جاري تشغيل البوت...")
        start_bot_process(user_id, main_script_name, bot_folder_path)
    else:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                              text="❌ **حدث خطأ: لم يتم العثور على معلومات مجلد البوت.** يرجى المحاولة مرة أخرى أو إعادة رفع الملف المضغوط.")

def start_bot_process(user_id, file_name, folder_path, bot_username=None):
    """
    يبدأ عملية تشغيل البوت كعملية فرعية.
    """
    main_script_path = os.path.join(folder_path, file_name)
    
    # توليد مفتاح فريد لعملية البوت
    process_key = f"{user_id}_{os.path.basename(folder_path)}_{file_name}"

    # إيقاف أي عملية سابقة لنفس البوت إذا كانت قيد التشغيل
    if process_key in bot_processes and bot_processes[process_key]['process'].poll() is None:
        try:
            os.killpg(os.getpgid(bot_processes[process_key]['process'].pid), signal.SIGTERM)
            time.sleep(1)
            if bot_processes[process_key]['process'].poll() is None:
                os.killpg(os.getpgid(bot_processes[process_key]['process'].pid), signal.SIGKILL)
            bot_processes[process_key]['process'].wait()
            del bot_processes[process_key]
            remove_bot_process_state(process_key)
            logger.info(f"تم إيقاف نسخة سابقة من البوت {file_name} للمستخدم {user_id}.")
            bot.send_message(user_id, f"⚠️ **تم إيقاف النسخة القديمة من البوت** `{file_name}` **لتشغيل النسخة الجديدة.**")
        except Exception as e:
            logger.warning(f"فشل إيقاف النسخة السابقة من البوت {file_name} للمستخدم {user_id}: {e}")
            bot.send_message(user_id, f"❌ **حدث خطأ أثناء محاولة إيقاف النسخة القديمة من البوت** `{file_name}`: {e}")
            # قد تستمر العملية القديمة في العمل في هذه الحالة

    try:
        # إنشاء ملفات سجل (Log files) لكل بوت
        log_file_stdout_path = os.path.join(folder_path, f'{file_name}.stdout.log')
        log_file_stderr_path = os.path.join(folder_path, f'{file_name}.stderr.log')

        # حذف ملفات السجل القديمة إذا وجدت
        if os.path.exists(log_file_stdout_path):
            os.remove(log_file_stdout_path)
        if os.path.exists(log_file_stderr_path):
            os.remove(log_file_stderr_path)

        process = subprocess.Popen(
            ['python3', main_script_path],
            cwd=folder_path,  # تعيين مجلد العمل ليكون مجلد البوت
            stdout=open(log_file_stdout_path, 'w'),
            stderr=open(log_file_stderr_path, 'w'),
            preexec_fn=os.setsid # لجعل العملية مستقلة عن البوت الرئيسي
        )
        
        bot_processes[process_key] = {
            'process': process,
            'folder_path': folder_path,
            'bot_username': bot_username, # يمكن تحديث هذا لاحقًا إذا تم استخراج اليوزر من ملف البوت
            'file_name': file_name,
            'owner_id': user_id,
            'log_file_stdout': log_file_stdout_path,
            'log_file_stderr': log_file_stderr_path,
            'start_time': datetime.now() # وقت بدء التشغيل
        }
        save_bot_process_state(process_key, folder_path, bot_username, file_name, user_id, log_file_stdout_path, log_file_stderr_path, datetime.now())
        
        bot.send_message(user_id, f"🟢 **تم تشغيل البوت الخاص بك** `{file_name}` **بنجاح!**\nيمكنك التحقق من حالته عبر زر 'بوتاتي'.")
        logger.info(f"تم تشغيل البوت {file_name} للمستخدم {user_id} في المسار {folder_path}.")

        # محاولة استخلاص اسم مستخدم البوت من ملف البوت نفسه
        threading.Thread(target=extract_bot_username_and_update, args=(user_id, file_name, folder_path, process_key)).start()

    except Exception as e:
        logger.error(f"فشل تشغيل البوت {file_name} للمستخدم {user_id}: {e}")
        bot.send_message(user_id, f"❌ **فشل تشغيل البوت الخاص بك** `{file_name}`.\n**الخطأ**: `{e}`\nيرجى التحقق من الكود الخاص بك أو التواصل مع المطور.")
        # إزالة الملفات إذا فشل التشغيل
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path)
        # إزالة من user_files وقاعدة البيانات
        if user_id in user_files:
            user_files[user_id] = [f for f in user_files[user_id] if not (f['file_name'] == file_name and f['folder_path'] == folder_path)]
            if not user_files[user_id]:
                del user_files[user_id]
        remove_user_file_db(user_id, file_name, folder_path)
        remove_bot_process_state(process_key)


def extract_bot_username_and_update(user_id, file_name, folder_path, process_key):
    """
    يحاول استخلاص اسم مستخدم البوت من ملف السجل ويقوم بتحديث معلومات البوت.
    """
    log_file_stdout_path = os.path.join(folder_path, f'{file_name}.stdout.log')
    timeout_seconds = 60 # محاولة لمدة دقيقة
    start_time = time.time()
    
    while time.time() - start_time < timeout_seconds:
        if os.path.exists(log_file_stdout_path):
            try:
                with open(log_file_stdout_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    # البحث عن "https://t.me/" متبوعًا باسم المستخدم
                    match = re.search(r'https://t.me/([a-zA-Z0-9_]+)', content)
                    if match:
                        bot_username = '@' + match.group(1)
                        if process_key in bot_processes:
                            bot_processes[process_key]['bot_username'] = bot_username
                            # تحديث اسم المستخدم في user_files أيضًا
                            if user_id in user_files:
                                for i, f_data in enumerate(user_files[user_id]):
                                    if f_data['file_name'] == file_name and f_data['folder_path'] == folder_path:
                                        user_files[user_id][i]['bot_username'] = bot_username
                                        # تحديث في قاعدة البيانات
                                        conn = sqlite3.connect('bot_data.db')
                                        c = conn.cursor()
                                        c.execute('UPDATE user_files SET bot_username = ? WHERE user_id = ? AND file_name = ? AND folder_path = ?',
                                                  (bot_username, user_id, file_name, folder_path))
                                        # تحديث في جدول حالة العمليات أيضًا
                                        c.execute('UPDATE bot_processes_state SET bot_username = ? WHERE process_key = ?',
                                                  (bot_username, process_key))
                                        conn.commit()
                                        conn.close()
                                        logger.info(f"تم تحديث يوزر البوت لـ {file_name} إلى {bot_username}")
                                        break
                        return # تم العثور على اليوزر، يمكن الخروج
            except Exception as e:
                logger.error(f"خطأ أثناء قراءة ملف سجل البوت {file_name}: {e}")
        time.sleep(2) # انتظر قليلاً قبل المحاولة مرة أخرى

    logger.warning(f"لم يتم العثور على يوزر بوت لـ {file_name} خلال المهلة المحددة.")


# --- معالجة أمر 'بوتاتي' ---
@bot.callback_query_handler(func=lambda call: call.data == 'my_bots')
def my_bots_menu(call):
    """يعرض قائمة بوتات المستخدم مع خيارات التحكم."""
    user_id = call.from_user.id
    
    if user_id not in user_files or not user_files[user_id]:
        bot.send_message(call.message.chat.id, "❌ **ليس لديك أي بوتات مرفوعة حالياً.** استخدم زر 'رفع ملف بوت' للبدء.")
        return

    markup = types.InlineKeyboardMarkup()
    message_text = "🤖 **بوتاتك المرفوعة:**\n\n"
    
    for i, file_data in enumerate(user_files[user_id]):
        file_name = file_data['file_name']
        folder_path = file_data['folder_path']
        bot_username = file_data.get('bot_username', 'غير محدد')
        
        # التأكد من عدم عرض المدخلات المؤقتة لملفات ZIP التي لم يتم اختيار ملف رئيسي لها بعد
        if file_name is None and 'temp_files' in file_data:
            message_text += f"📄 **ملف ZIP قيد الانتظار**: `{os.path.basename(folder_path)}` (اختر ملفًا رئيسيًا)\n\n"
            continue

        process_key = f"{user_id}_{os.path.basename(folder_path)}_{file_name}"
        
        is_running = False
        if process_key in bot_processes and bot_processes[process_key]['process'].poll() is None:
            is_running = True
        
        status = "🟢 قيد التشغيل" if is_running else "🔴 متوقف"
        
        # إضافة وقت التشغيل
        uptime_str = "غير متاح"
        if is_running and 'start_time' in bot_processes[process_key]:
            start_time = bot_processes[process_key]['start_time']
            uptime = datetime.now() - start_time
            uptime_str = str(uptime).split('.')[0] # إزالة أجزاء الثانية

        message_text += f"📊 **البوت**: `{file_name}`\n"
        message_text += f"  **الحالة**: {status}\n"
        message_text += f"  **يوزر البوت**: `{bot_username}`\n"
        message_text += f"  **وقت التشغيل**: `{uptime_str}`\n\n"
        
        # أزرار التحكم لكل بوت
        markup.add(
            types.InlineKeyboardButton(f"🛑 إيقاف {file_name}", callback_data=f"stop_{process_key}"),
            types.InlineKeyboardButton(f"▶️ تشغيل {file_name}", callback_data=f"start_{process_key}")
        )
        markup.add(
            types.InlineKeyboardButton(f"🗑️ حذف {file_name}", callback_data=f"delete_{process_key}"),
            types.InlineKeyboardButton(f"📄 سجل {file_name}", callback_data=f"log_{process_key}")
        )
        markup.add(types.InlineKeyboardButton(f"🔄 إعادة تشغيل {file_name}", callback_data=f"restart_{process_key}"))
        
    markup.add(types.InlineKeyboardButton('⬅️ العودة للقائمة الرئيسية', callback_data='main_menu'))
    
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                          text=message_text, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith(('stop_', 'start_', 'delete_', 'log_', 'restart_')))
def handle_bot_action(call):
    """يعالج إجراءات المستخدم على البوتات (إيقاف، تشغيل، حذف، سجل، إعادة تشغيل)."""
    action, process_key = call.data.split('_', 1)
    user_id = call.from_user.id

    parts = process_key.split('_', 2) # owner_id_folderbase_filename
    owner_id_str = parts[0]
    folder_base_name = parts[1]
    file_name = parts[2]

    if str(user_id) != owner_id_str:
        bot.send_message(call.message.chat.id, "⚠️ **لا تملك الصلاحية للتحكم بهذا البوت.**")
        return

    # استعادة المسار الكامل للمجلد
    # يمكن البحث عنه في user_files للحصول على المسار الأصلي الدقيق
    target_folder_path = None
    if user_id in user_files:
        for file_info in user_files[user_id]:
            if file_info['file_name'] == file_name and os.path.basename(file_info['folder_path']) == folder_base_name:
                target_folder_path = file_info['folder_path']
                break
    
    if not target_folder_path:
        bot.send_message(call.message.chat.id, "❌ **عذراً، لم يتم العثور على معلومات البوت.** ربما تم نقله أو حذفه يدوياً.")
        return

    main_script_path = os.path.join(target_folder_path, file_name)

    if action == 'stop':
        if process_key in bot_processes and bot_processes[process_key]['process'].poll() is None:
            try:
                # قتل العملية ومجموعتها (لضمان إنهاء جميع العمليات الفرعية للبوت)
                os.killpg(os.getpgid(bot_processes[process_key]['process'].pid), signal.SIGTERM)
                # الانتظار قليلاً للتأكد من انتهاء العملية
                time.sleep(1)
                if bot_processes[process_key]['process'].poll() is None: # إذا لم تتوقف، أرسل SIGKILL
                     os.killpg(os.getpgid(bot_processes[process_key]['process'].pid), signal.SIGKILL)
                
                bot_processes[process_key]['process'].wait() # انتظر حتى تنتهي العملية تمامًا
                del bot_processes[process_key]
                remove_bot_process_state(process_key) # إزالة من قاعدة البيانات
                bot.send_message(call.message.chat.id, f"✅ **تم إيقاف البوت** `{file_name}` **بنجاح.**")
            except Exception as e:
                logger.error(f"خطأ أثناء إيقاف البوت {process_key}: {e}")
                bot.send_message(call.message.chat.id, f"❌ **فشل إيقاف البوت** `{file_name}`: `{e}`")
        else:
            bot.send_message(call.message.chat.id, f"ℹ️ **البوت** `{file_name}` **ليس قيد التشغيل حالياً.**")

    elif action == 'start':
        if process_key in bot_processes and bot_processes[process_key]['process'].poll() is None:
            bot.send_message(call.message.chat.id, f"ℹ️ **البوت** `{file_name}` **قيد التشغيل بالفعل.**")
        else:
            if os.path.exists(main_script_path):
                start_bot_process(user_id, file_name, target_folder_path)
            else:
                bot.send_message(call.message.chat.id, f"❌ **ملف البوت** `{file_name}` **غير موجود في المسار:** `{target_folder_path}`.")

    elif action == 'delete':
        # إيقاف البوت أولاً إذا كان قيد التشغيل
        if process_key in bot_processes and bot_processes[process_key]['process'].poll() is None:
            try:
                os.killpg(os.getpgid(bot_processes[process_key]['process'].pid), signal.SIGTERM)
                time.sleep(1)
                if bot_processes[process_key]['process'].poll() is None:
                     os.killpg(os.getpgid(bot_processes[process_key]['process'].pid), signal.SIGKILL)
                bot_processes[process_key]['process'].wait()
                del bot_processes[process_key]
                remove_bot_process_state(process_key)
            except Exception as e:
                logger.error(f"خطأ أثناء إيقاف البوت {process_key} قبل الحذف: {e}")
                bot.send_message(call.message.chat.id, f"⚠️ **حدث خطأ أثناء إيقاف البوت قبل الحذف**: `{e}`. سيتم محاولة الحذف.")
        
        # حذف الملفات والمجلد
        if os.path.exists(target_folder_path):
            try:
                shutil.rmtree(target_folder_path)
                
                # إزالة من user_files ومن قاعدة البيانات
                user_files[user_id] = [f for f in user_files[user_id] if not (f['file_name'] == file_name and f['folder_path'] == target_folder_path)]
                if not user_files[user_id]: # إذا لم يتبق للمستخدم أي ملفات
                    del user_files[user_id]
                
                remove_user_file_db(user_id, file_name, target_folder_path)

                bot.send_message(call.message.chat.id, f"✅ **تم حذف البوت** `{file_name}` **بنجاح.**")
            except Exception as e:
                logger.error(f"خطأ أثناء حذف مجلد البوت {target_folder_path}: {e}")
                bot.send_message(call.message.chat.id, f"❌ **فشل حذف مجلد البوت** `{file_name}`: `{e}`")
        else:
            bot.send_message(call.message.chat.id, f"❌ **مجلد البوت** `{target_folder_path}` **غير موجود أو سبق حذفه.**")
        
        # بعد أي إجراء قد يغير القائمة، قم بتحديث قائمة البوتات للمستخدم
        my_bots_menu(call) # إعادة عرض القائمة المحدثة

    elif action == 'log':
        log_file_stdout_path = os.path.join(target_folder_path, f'{file_name}.stdout.log')
        log_file_stderr_path = os.path.join(target_folder_path, f'{file_name}.stderr.log')

        log_content = ""
        if os.path.exists(log_file_stdout_path):
            with open(log_file_stdout_path, 'r', encoding='utf-8', errors='ignore') as f:
                log_content += "📄 **سجل المخرجات (STDOUT):**\n```\n"
                log_content += f.read()[-2000:] # آخر 2000 حرف
                log_content += "\n```\n"
        else:
            log_content += "❌ **لا يوجد سجل مخرجات (STDOUT) لهذا البوت.**\n"
        
        if os.path.exists(log_file_stderr_path):
            with open(log_file_stderr_path, 'r', encoding='utf-8', errors='ignore') as f:
                log_content += "‼️ **سجل الأخطاء (STDERR):**\n```\n"
                log_content += f.read()[-2000:] # آخر 2000 حرف
                log_content += "\n```"
        else:
            log_content += "❌ **لا يوجد سجل أخطاء (STDERR) لهذا البوت.**\n"

        if len(log_content) > 4096: # Telegram message limit
            # تقسيم الرسالة إلى أجزاء أو إرسال كملف
            try:
                with tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8') as temp_log_file:
                    temp_log_file.write(log_content)
                bot.send_document(call.message.chat.id, open(temp_log_file.name, 'rb'), 
                                  caption=f"📄 **سجل البوت** `{file_name}` (كبير جدًا للعرض المباشر):", parse_mode='Markdown')
                os.remove(temp_log_file.name)
            except Exception as e:
                bot.send_message(call.message.chat.id, f"❌ **فشل في إرسال سجل البوت كملف**: {e}")
        else:
            bot.send_message(call.message.chat.id, log_content, parse_mode='Markdown')

    elif action == 'restart':
        # إجراء الإيقاف
        if process_key in bot_processes and bot_processes[process_key]['process'].poll() is None:
            try:
                os.killpg(os.getpgid(bot_processes[process_key]['process'].pid), signal.SIGTERM)
                time.sleep(1)
                if bot_processes[process_key]['process'].poll() is None:
                     os.killpg(os.getpgid(bot_processes[process_key]['process'].pid), signal.SIGKILL)
                bot_processes[process_key]['process'].wait()
                del bot_processes[process_key]
                remove_bot_process_state(process_key)
                bot.send_message(call.message.chat.id, f"🔄 **تم إيقاف البوت** `{file_name}`. جاري إعادة التشغيل...")
            except Exception as e:
                logger.error(f"خطأ أثناء إيقاف البوت {process_key} لإعادة التشغيل: {e}")
                bot.send_message(call.message.chat.id, f"❌ **فشل إيقاف البوت لإعادة التشغيل** `{file_name}`: `{e}`")
                return # لا تحاول التشغيل إذا فشل الإيقاف

        # إجراء التشغيل
        if os.path.exists(main_script_path):
            start_bot_process(user_id, file_name, target_folder_path)
        else:
            bot.send_message(call.message.chat.id, f"❌ **ملف البوت** `{file_name}` **غير موجود لإعادة التشغيل.**")


# --- نقطة دخول البوت ---
if __name__ == '__main__':
    # عند بدء تشغيل البوت الرئيسي، حاول استرداد البوتات التي كانت تعمل سابقاً
    recover_running_bots()
    logger.info("البوت بدأ العمل...")
    bot.polling(none_stop=True)

