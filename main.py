#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Coded by aqil.almara - t.me/prudentscitus

# Imports
import os
import re
import sys
import json
import math
import time
import hashlib
import asyncio
import logging
import functools
import PyPDF2
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Union, Dict, Any, List, Tuple
from dataclasses import dataclass

import requests
from requests.exceptions import HTTPError, ConnectionError, ReadTimeout, RequestException
try: from json.decoder import JSONDecodeError
except ImportError: JSONDecodeError = ValueError

from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup
from telegram import KeyboardButton, ReplyKeyboardMarkup, CopyTextButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    InlineQueryHandler, MessageHandler, ContextTypes, filters, JobQueue
)
from telegram.error import TelegramError, BadRequest
from telegram.constants import ParseMode

# Configuration
@dataclass
class Config:
    """Bot configuration"""
    bot_token: str = os.getenv("BOT_TOKEN")
    db_file: Path = Path('assets', 'NIMESCANSBOT.db.json')
    fp_projects: Path = Path('assets', 'Projects.json')
    admin_user_ids: List[int] = None
    delete_delay: int = 30
    base_password: str = "N1M3SC4NS"

    def __post_init__(self):
        if self.admin_user_ids is None: self.admin_user_ids = [1308147558, 5074802729]
        if not self.bot_token: raise ValueError("BOT_TOKEN environment variable is required")

config = Config()

# Messages
MESSAGES = {
    "welcome": (
        "👋 <b>Welcome {user_mention}!</b>\n"
        "🆔 <code>{user_id}</code>\n\n"
        "🔥 <b>NIMESCANS Bot</b>\n"
        "Read and discover your favorite manhwa instantly! 🍒\n\n"
        "👇 Tap <b>'🔍 List Project'</b> to begin your adventure."
    ),
    "main_menu": """🏠 <b>Main Menu</b>\n\nPlease select an option below:""",
    "error_occurred": """⚠️ <b>Something went wrong</b>\n\nPlease try again in a few moments.""",
    "privacy_not_available": """📄 <b>Privacy Policy</b>\n\nPrivacy policy documentation is currently unavailable.\n\nWe respect your privacy and do not store personal data unnecessarily.""",
}

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Determine if running on Windows
isWin = os.name == 'nt'
if isWin: __import__('colorama').init(autoreset=True)

# Terminal width function
def term_c(): return os.get_terminal_size().columns - isWin

# Simplified UI Colors
class UIColor:
    COLORS = {
        'black': '\x1b[0;30m',
        'orange': '\x1b[38;5;130m',
        'turquoise': '\x1b[38;5;50m',
        'smoothgreen': '\x1b[38;5;42m'
    }

    @classmethod
    def print_colored(cls, *values, sep=' ', end='\n', file=sys.stdout, flush=False, clr=False):
        cls.clear_line()
        prefix, suffix = '\x1b[0;1;39;49m', '\x1b[0;1;39;49m'
        if not isinstance(file, type(sys.stdout)): clr = True
        colored_values = [f"{prefix}{cls.placeholders(v, clr)}{suffix}" for v in values]
        print(*colored_values, sep=sep, end=end, flush=flush)

    @classmethod
    def placeholders(cls, raw_value: str, clr=False):
        raw_value = str(raw_value)
        for kc, vc in reversed(re.findall(r'(\?([\dbo]{1,3})`?)', raw_value)):
            if vc in 'bo':
                raw_value = raw_value.replace(kc, {'b': '\x1b[0;30m', 'o': '\x1b[38;5;130m'}.get(vc, ''))
            raw_value = raw_value.replace(kc, '' if clr else f'\x1b[{vc}m')
        return raw_value.replace('`', '')

    @classmethod
    def set_title(cls, title: str): sys.stdout.write(f'\x1b]2;{title}\a'); sys.stdout.flush()

    @classmethod
    def clear_screen(cls): os.system('cls' if isWin else 'clear')

    @classmethod
    def clear_line(cls, mode=2): print(f'\x1b[{mode}K', end='\r', flush=True)

    @classmethod
    def exit_with_msg(cls, msg: str): cls.print_colored(msg); sys.exit(1)

# Aliases for backward compatibility
printn = UIColor.print_colored

def format_bytes(size, precision=2):
    """
    Format a size in bytes to a human-readable string (e.g., 1024 -> '1.00KB').

    Args:
        size (int or float): The size in bytes.
        precision (int): Number of decimal places (default 2).

    Returns:
        str: Formatted string.

    Raises:
        ValueError: If size is negative.
    """
    if size < 0: raise ValueError("Size cannot be negative")
    if size == 0: return f"0.{'0' * precision}B"

    units = ['B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y']

    # Calculate the unit index using log2
    unit_index = min(int(math.log2(size) // 10), len(units) - 1)
    scaled_size = size / (1024 ** unit_index)

    return f"{scaled_size:.{precision}f} {units[unit_index]}B"


class Database:
    """Thread-safe database manager"""
    def __init__(self, db_file: Path):
        self.db_file = db_file
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load database from file"""
        try:
            if self.db_file.exists():
                self._data = json.loads(self.db_file.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Failed to load database: {e}")
            self._data = {}

    def _save(self) -> None:
        """Save database to file"""
        try:
            self.db_file.parent.mkdir(exist_ok=True)
            self.db_file.write_text(
                json.dumps(self._data, ensure_ascii=False, separators=(',', ':'), indent=4),
                encoding='utf-8'
            )
        except Exception as e: logger.error(f"Failed to save database: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._save()

    def user_exists(self, user_id: str) -> bool:
        return user_id in self._data
    
    def _users(self) -> list:
        return list(self._data.keys())

    def ensure_user(self, user_id: str, user_info: Dict[str, Any]) -> None:
        """Ensure user exists in database"""
        if not self.user_exists(user_id):
            self._data[user_id] = {
                'User': user_info,
                'Library': {}
            }
            self._save()


    def _projects(self):
        self._load()
        return self._data

    def get_project(self, title: str) -> Dict[str, Any]:
        self._load()
        return self._data.get(title, {})
    
    def set_rate(self, title, rate):
        self._data[title]['rates'].update(rate)
        self._save()

    def items(self):
        self._load()
        return self._data.items()

    def __len__(self):
        return len(self._data)

db_bot = Database(config.db_file)
db_projects = Database(config.fp_projects)

def LockPDF(input_url: str, user_pwd: str, owner_pwd: str) -> BytesIO:
    # Menggunakan pathlib untuk membaca bytes secara langsung
    resp_pdf = requests.get(input_url)
    filename = resp_pdf.headers.get('Content-Disposition').split('"')[1]

    input_buffer = io.BytesIO(resp_pdf.content)
    reader = PyPDF2.PdfReader(input_buffer)
    writer = PyPDF2.PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    writer.encrypt(
        user_pwd,
        owner_pwd,
        permissions_flag=0  # -3904
    )

    output_buffer = BytesIO()
    output_buffer.name = filename
    writer.write(output_buffer)

    file_size = output_buffer.tell()

    output_buffer.seek(0)
    file_hash = hashlib.md5(output_buffer.read()).hexdigest()

    output_buffer.seek(0)
    return output_buffer, file_size, file_hash

class MessageManager:
    """Message management utilities"""

    @staticmethod
    async def send_temp(context: ContextTypes.DEFAULT_TYPE, 
                       chat_id: int, 
                       text: str, 
                       reply_markup: Optional[InlineKeyboardMarkup] = None,
                       delay: int = None,
                       protect_content=False) -> Optional[int]:
        """Send temporary message with auto-delete"""
        if delay is None: delay = config.delete_delay

        try:
            message = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                protect_content=protect_content,
                # protect_content=int(chat_id) not in config.admin_user_ids,
                disable_web_page_preview=True
            )

            # Schedule deletion
            context.job_queue.run_once(
                MessageManager._delete_message,
                when=delay,
                data={'chat_id': chat_id, 'message_id': message.message_id},
                name=f"del_{message.message_id}"
            )
            return message.message_id
        except Exception as e:
            logger.error(f"Failed to send temp message: {e}")
            return None

    @staticmethod
    async def _delete_message(context: ContextTypes.DEFAULT_TYPE) -> None:
        """Delete message callback"""
        try:
            data = context.job.data
            await context.bot.delete_message(**data)
        except Exception as e: logger.debug(f"Delete failed: {e}")

def generate_main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Generate main menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("📚 List Project", callback_data="list_project"),
            InlineKeyboardButton("📢 Channel Kami", url="https://t.me/+KwyYbkBSpCpmOTY1")
        ],
        [
            InlineKeyboardButton("☕ Donate", callback_data="donate"),
            InlineKeyboardButton("❓ Help", callback_data="help")
        ],
        [InlineKeyboardButton("📄 Privacy Policy", callback_data='privacy')]
    ]
    
    # if is_admin:
    #     keyboard.insert(1, [
    #         InlineKeyboardButton("📢 Broadcast", callback_data='broadcast_mode'),
    #         InlineKeyboardButton("👥 Notify Users", callback_data='notify_user')
    #     ])
    #     keyboard.insert(2, [InlineKeyboardButton("💻 Source Code", callback_data='source_code')])

    return InlineKeyboardMarkup(keyboard)

# --- DECORATOR UNTUK MENGHAPUS COMMAND USER ---
def auto_delete_command(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.message:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=update.message.message_id
                )
            except Exception as e: print(f"Gagal menghapus: {e}")
        return await func(update, context, *args, **kwargs)
    return wrapper


# Handlers
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler"""
    logger.error(f"Update {update} caused error: {context.error}")

    if (update and hasattr(update, 'callback_query') and 
        update.callback_query and update.callback_query.message):
        try:
            await update.callback_query.answer(
                MESSAGES["error_occurred"], show_alert=True
            )
        except Exception: pass

async def privacy_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Privacy policy handler"""
    query = update.callback_query
    await query.answer()

    privacy_file = Path('assets', 'privacy-policy.html')
    try: response = privacy_file.read_text(encoding='utf-8')
    except FileNotFoundError: response = MESSAGES["privacy_not_available"]

    keyboard = [[
        InlineKeyboardButton("🏠 Main Menu", callback_data='main_menu'),
        InlineKeyboardButton("💬 Contact", url='https://t.me/ShenZhiiyi')
    ]]

    await query.edit_message_text(
        text=response,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main menu handler"""
    query = update.callback_query
    await query.answer()

    context.user_data.clear()
    user = update.effective_user

    response = MESSAGES["welcome"].format(
        user_mention=user.mention_html(),
        user_id=user.id
    )
    reply_markup = generate_main_menu_keyboard(query.from_user.id in config.admin_user_ids)
    if query.message.photo:
        await query.message.delete()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=response,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            protect_content=True,
            disable_web_page_preview=True
        )

    else: await query.edit_message_text(response, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    user = update.effective_user
    user_id = str(user.id)
    is_admin = user.id in config.admin_user_ids

    # Ensure user in database
    user_info = {
        'first_name': user.first_name or '',
        'username': user.username or '',
        'is_bot': user.is_bot,
        'language_code': user.language_code or ''
    }
    db_bot.ensure_user(user_id, user_info)

    # Clear user data
    context.user_data.clear()

    await update.message.reply_html(
        MESSAGES["welcome"].format(
            user_mention=user.mention_html(),
            user_id=user_id
        ),
        reply_markup=generate_main_menu_keyboard(is_admin),
        protect_content=True,
        # protect_content=not is_admin,
        disable_web_page_preview=True
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main button handler"""
    query = update.callback_query
    await query.answer("⏳ Processing data, please wait..")

    user_id = str(query.from_user.id)
    data = query.data

    if data == 'privacy': await privacy_handler(update, context)
    elif data == 'back_project_details': await project_details_handler(update, context)
    elif data == 'project_rate': await project_rate_handler(update, context)

    elif data.startswith('rating:'):
        user_rate = int(data.split(':')[1])
        title = context.user_data.get('project_title')
        db_projects.set_rate(title, {user_id: user_rate})
        await project_details_handler(update, context)

    elif data.startswith('chapters_index:'):
        chapters_index = int(data.split(':')[1])
        if chapters_index < 0: return
        context.user_data['chapters_index'] = chapters_index
        await project_details_handler(update, context)

    # Projects pagination
    elif data.startswith('project:'):
        context.user_data['project_title'] = data.split(':')[1]
        await project_details_handler(update, context)

    elif data.startswith('get_chapter:'):
        _project_details = context.user_data.get('project_details')
        ch_idx = data.split(':')[1]
        ch_data = _project_details['chapters'][ch_idx]
        file_path = Path(ch_data['chapter_path'])

        if not context.user_data.get('geted_chapters'): context.user_data['geted_chapters'] = []
        if context.user_data['geted_chapters'].count(file_path.name): return
        context.user_data['geted_chapters'].append(file_path.name)
        printn(f"?95>>> ?94`{file_path}")

        dynamic_pw = f"{config.base_password}{int(datetime.now().timestamp())}"
        pdf_BytesIO, file_size, file_hash = LockPDF(
            input_url=ch_data['chapter_url'],
            user_pwd=dynamic_pw,
            owner_pwd="n1M3sC4N_S3cr3t_K3y_!@#$%^&*()"
        )

        caption = (
            f"📖 <b>{context.user_data['project_title']}</b>\n"
            f"📑 {ch_data['chapter_name']}\n\n"
            f"<blockquote>📝 <b>File Name:</b> <code>{ch_data['chapter_path']}</code>\n"
            f"📦 <b>Size:</b> {format_bytes(file_size)}\n"
            f"📌 <b>Type:</b> Document\n"
            f"🔤 <b>Extension:</b> PDF\n"
            f"⚓ <b>MD5:</b> <code>{file_hash}</code></blockquote>\n\n"
            f"⚠️ <i>This document is confidential. Internal use only.</i>\n"
            "<b>- NIMESCANS</b>\n"
        )
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Password PDF", copy_text=CopyTextButton(dynamic_pw))]
        ])
        sent_msg = await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=pdf_BytesIO,
            caption=caption,
            filename=file_path.name,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            protect_content=True
        )
        # pdf_terkunci.close()

        document_life = 300
        context.job_queue.run_once(
            MessageManager._delete_message,
            when=document_life,
            data={'chat_id': query.message.chat_id, 'message_id': sent_msg.message_id}
        )
        await MessageManager.send_temp(
            context, query.message.chat_id, delay=document_life,
            text=(
                f"✅ <b>Chapter {ch_idx}</b> berhasil dikirim!\n\n"
                # f"🔑 <tg-spoiler>{dynamic_pw}</tg-spoiler>\n\n"
                "Selamat membaca~ 🍒\n\n"
                "<i>Kalau suka manhwa ini, jangan lupa kasih rating ya!</> ⭐"
            ),
            protect_content=True
        )


    else: await main_menu_handler(update, context)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages"""

    user = update.effective_user
    message = update.message
    text = message.text.strip()
    text_html = message.text_html
    # Path('message_handler.txt').write_bytes(text.encode())
    printn(f"?95>>> ?93`{text_html}")

    # Delete user message
    try: await message.delete()
    except TelegramError: pass

    # await MessageManager.send_temp(
    #     context, message.chat_id,
    #     text_html, delay=60
    # )



async def job_send_reports(context: ContextTypes.DEFAULT_TYPE) -> None:
    RECEIVER_ID = config.admin_user_ids[0]

    now = datetime.now()
    response = (
        f"<b>📊 PERIODIC ONLINE REPORT</b>\n"
        f"<i>Automated Security Monitoring System</i>\n\n"
        f"📅 <b>Date:</b> {now.strftime('%d %B %Y')}\n"
        f"⏰ <b>Time:</b> {now.strftime('%H:%M:%S')} UTC+0\n"
    )
    sent_msg = await context.bot.send_message(
        chat_id=RECEIVER_ID,
        text=response,
        parse_mode=ParseMode.HTML
    )

    # Schedule deletion
    context.job_queue.run_once(
        MessageManager._delete_message,
        when=300,
        data={'chat_id': RECEIVER_ID, 'message_id': sent_msg.message_id},
        name=f"del_{sent_msg.message_id}"
    )

@auto_delete_command
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Kirim peringatan
    return
    sent_message = await update.message.reply_text(
        f"Maaf, command {update.message.text} tidak terdaftar!"
    )

    # Optional: Hapus pesan peringatan bot setelah 5 detik agar grup tetap bersih
    await asyncio.sleep(5)
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=sent_message.message_id
        )
    except Exception as e: print(f"Gagal menghapus pesan bot: {e}")


async def donate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    await query.message.delete() # Hapus pesan teks
    with open(Path('assets', 'nime_qris.jpg'), 'rb') as photo:
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=photo,
            caption=(
                "╔═════════════════════════\n"
                "║    <b>☕ DUKUNG NIMESCANS!</b>\n"
                "╚═════════════════════════\n\n"
                "🍒 Setiap dukungan kalian, besar atau kecil, sangat berarti dan membuat Nime makin semangat! 💖\n\n"
                "🔗 <a href='https://telegra.ph/Support-Nime-02-22-5'>Link Donasi</a>\n\n"
                "Terima kasih atas dukungannya! 💖\n"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💝 Donate Sekarang!", url="https://telegra.ph/Support-Nime-02-22-5")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ]),
            parse_mode=ParseMode.HTML,
            protect_content=True
        )

async def help_handler(update: Update, context:ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    response = (
        "╔═════════════════════════\n"
        "║    <b>❓ CARA MENGGUNAKAN</b>\n"
        "╚═════════════════════════\n\n"
        "📌 <b>Cara membaca manhwa</b>:\n"
        "1️⃣ Klik 📚 <b>List Project</b>\n"
        "2️⃣ Pilih judul manhwa\n"
        "3️⃣ Pilih nomor chapter\n"
        "4️⃣ File PDF otomatis dikirim!\n\n"
        "⚠️ <b>Penting</b>:\n"
        "• File <b>tidak bisa</b> disimpan/diteruskan\n"
        "• Baca langsung di Telegram\n"
        "• Wajib join channel untuk akses\n\n"
        "❓ Pertanyaan? Hubungi admin di channel!\n"
    )
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
    await query.edit_message_text(response, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def list_project_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await update.callback_query.answer("⏳ Processing data, please wait..")

    keyboard_list = []
    project_items = dict(sorted(db_projects.items(), key=lambda x:len(x[1]['rates']), reverse=True))
    for title in project_items:
        if len(title) > 32: title = f'{title[:29]}...'
        keyboard_list.append([
            InlineKeyboardButton(f"• {title} •", callback_data=f"project:{title}")
        ])

    response = (
        "╔═════════════════════════\n"
        "║    <b>📖 KATALOG NIMESCANS!</b>\n"
        "╚═════════════════════════\n\n"
        f"🍒 {len(db_projects)} manhwa tersedia\n\n"
        "Pilih Manhwa yang ingin dibaca:"
    )

    keyboard_list.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard_list)

    with open(Path('assets', 'deskripsi_bot.jpg'), 'rb') as photo:
        await query.message.delete() # Hapus pesan teks
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=photo,
            caption=response,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            protect_content=True
        )

async def project_details_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User library handler"""
    query = update.callback_query
    await update.callback_query.answer("⏳ Processing data, please wait..")

    user_id = str(query.from_user.id)
    project_title = context.user_data.get('project_title', '')
    chapters_index = context.user_data.get('chapters_index', 0)
    project = db_projects.get(project_title, {})
    total_chapter = len(project['chapters'])
    context.user_data['project_details'] = project

    rates, rate = project['rates'], 5
    if rates: rate = sum(rates.values()) /len(rates)

    response = (
        "📢 <b>NEW MANHWA ALERT</b>\n\n"
        f"🔮 <b>Judul</b>: {project_title}\n"
        f"⭐ <b>Rating</b>: {rate:.1F} ({len(rates)} Votes)\n"
        f"📁 <b>Alternatif</b>: {', '.join(project.get('alternatif'))}\n"
        f"🎭 <b>Genre</b>: {', '.join(project['genre'])}\n\n"
        "🍒 <b>Sinopsis</b>:\n"
        f"<i>{project['sinopsis']}</i>\n\n"
        f"Total: <b>{total_chapter}</b> chapter tersedia\n"
        "Pilih chapter yang ingin dibaca:"
    )

    buttons_size = 30
    buttons = []
    project_items = list(project['chapters'].items())
    for ch_idx, ch_data in project_items[chapters_index:chapters_index + buttons_size]:
        buttons.append(InlineKeyboardButton(f"Ch. {ch_idx}", callback_data=f"get_chapter:{ch_idx}"))

    keyboard = []
    if total_chapter > buttons_size:
        max_chapters_index = buttons_size * (math.ceil(total_chapter / buttons_size)-1)
        nex_chapters_index = buttons_size + chapters_index
        if nex_chapters_index > max_chapters_index:
            nex_chapters_index = -buttons_size
        keyboard.append([
            InlineKeyboardButton("◀️", callback_data=f'chapters_index:{chapters_index - buttons_size}'),
            InlineKeyboardButton("▶️", callback_data=f'chapters_index:{nex_chapters_index}')
        ])

    for i in range(0, len(buttons), 3):
        keyboard.append(buttons[i:i + 3])

    keyboard.append([InlineKeyboardButton("⭐ Beri Rating", callback_data="project_rate")])
    keyboard.append([
        InlineKeyboardButton("📚 List Project", callback_data="back_project_list"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    with open(Path('cover', project['cover_path']), 'rb') as photo:
        await query.message.delete() # Hapus pesan katalog
        await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=photo,
                caption=response,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                protect_content=True
            )

async def project_rate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    project_title = context.user_data.get('project_title', '')
    project_details = context.user_data.get('project_details')
    rates, rate = project_details['rates'], 5
    if rates: rate = sum(rates.values()) /len(rates)

    response = (
        "╔═════════════════════════\n"
        "║    <b>⭐ BERI RATING MANHWA</b>\n"
        "╚═════════════════════════\n\n"
        f"📗 <b>{project_title}</b>\n"
        f"⭐ Rating: <b>{rate:.1F}</b> ({len(rates)} Votes)\n\n"
        "Gimana menurutmu manhwa ini?\nSilakan pilih bintang:\n\n"
        "<i>*Jika sudah pernah beri rating, rating kamu akan diperbarui</i>\n"
    )
    keyboard = [
        [
            InlineKeyboardButton("⭐ 1", callback_data="rating:1"),
            InlineKeyboardButton("⭐ 2", callback_data="rating:2"),
            InlineKeyboardButton("⭐ 3", callback_data="rating:3"),
            InlineKeyboardButton("⭐ 4", callback_data="rating:4"),
            InlineKeyboardButton("⭐ 5", callback_data="rating:5"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="back_project_details")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    if query.message.photo:
        await query.message.delete()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=response,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            protect_content=True,
            disable_web_page_preview=True
        )

    else: await query.edit_message_text(response, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)




def main() -> None:
    """Main application entry point"""
    if not config.bot_token:
        logger.error("BOT_TOKEN not set")
        sys.exit(1)

    UIColor.clear_screen()
    UIColor.set_title('ProWebtoonsBot')

    # Create application
    app = (
        ApplicationBuilder()
        .token(config.bot_token)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        # .job_queue(JobQueue())
        .build()
    )

    # Handlers registration
    app.add_handler(CommandHandler('start', start))

    # Callback query handlers
    app.add_handler(CallbackQueryHandler(main_menu_handler, pattern='^main_menu$'))
    app.add_handler(CallbackQueryHandler(privacy_handler, pattern='^privacy$'))

    app.add_handler(CallbackQueryHandler(list_project_handler, pattern='^list_project$'))
    app.add_handler(CallbackQueryHandler(list_project_handler, pattern='^back_project_list$'))

    app.add_handler(CallbackQueryHandler(donate_handler, pattern='^donate$'))
    app.add_handler(CallbackQueryHandler(help_handler, pattern='^help$'))

    app.add_handler(CallbackQueryHandler(button_handler))

    # Message handler
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Error handler
    app.add_error_handler(error_handler)

    now = datetime.now()
    minute_to_add = 5 - (now.minute % 5)
    first_run = (now + timedelta(minutes=minute_to_add)).replace(second=0, microsecond=0)
    app.job_queue.run_repeating(
        job_send_reports,
        interval=300,
        first=(first_run - now).seconds,
        name="hourly_reports"
    )

    logger.info("🚀 NIMESCANS Bot started successfully!")
    logger.info("Bot is now running...")

    # Run bot
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False
    )


KATALOG = {
    # "": {
    #     "rates": {},
    #     "cover_path": "_cover.jpg",
    #     "alternatif": [""],
    #     "genre": [""],
    #     "sinopsis": "",
    #     "chapters": {}
    # }
}
if __name__ == '__main__':
    main()
