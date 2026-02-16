import asyncio
import logging
import json
import re
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from app.config import *
from app import database as db
from app.services import locket, nextdns

logger = logging.getLogger(__name__)

request_queue = asyncio.Queue()
pending_items = []
queue_lock = asyncio.Lock()
bot_enabled = True  # Bot on/off toggle
token_counter = 0   # Round-robin counter for token selection

# Required channels/groups to join before using bot
REQUIRED_CHANNELS = [
    {"id": -1002629963814, "name": "DINO 🛠", "url": "https://t.me/dinotool"},
    {"id": -1002191171631, "name": "DINO Store", "url": "https://t.me/dinostore01"},
]

# Bot only works in this group (admin/VIP can use private)
ALLOWED_CHAT_ID = -1002629963814  # DINO 🛠

class Clr:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def parse_request_text(text):
    """Parse raw HTTP request text (.txt format) to extract token fields."""
    try:
        lines = text.strip().replace('\r\n', '\n').split('\n')
        
        # Find empty line separator between headers and body
        body_text = None
        hash_params = ""
        hash_headers = ""
        is_sandbox = False
        
        for i, line in enumerate(lines):
            lower = line.lower().strip()
            if lower.startswith('x-post-params-hash:'):
                hash_params = line.split(':', 1)[1].strip()
            elif lower.startswith('x-headers-hash:'):
                hash_headers = line.split(':', 1)[1].strip()
            elif lower.startswith('x-is-sandbox:'):
                val = line.split(':', 1)[1].strip().lower()
                is_sandbox = val == 'true'
            elif line.strip() == '' and i < len(lines) - 1:
                # Everything after empty line is body
                body_text = '\n'.join(lines[i+1:]).strip()
        
        if not body_text:
            # Maybe the whole thing is just JSON
            body_text = text.strip()
        
        body = json.loads(body_text)
        fetch_token = body.get('fetch_token')
        app_transaction = body.get('app_transaction')
        
        if not fetch_token or not app_transaction:
            return None
        
        return {
            'fetch_token': fetch_token,
            'app_transaction': app_transaction,
            'hash_params': hash_params,
            'hash_headers': hash_headers,
            'is_sandbox': is_sandbox,
        }
    except Exception:
        return None

def get_next_token():
    """Get next token using round-robin from TOKEN_SETS."""
    global token_counter
    if not TOKEN_SETS:
        return None
    idx = token_counter % len(TOKEN_SETS)
    token_counter += 1
    return TOKEN_SETS[idx]

async def check_membership(bot, user_id):
    """Check if user is a member of all required channels/groups."""
    not_joined = []
    for ch in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
            if member.status in ["left", "kicked"]:
                not_joined.append(ch)
        except Exception:
            not_joined.append(ch)
    return not_joined

def get_join_keyboard(not_joined, lang):
    """Build keyboard with join links for channels user hasn't joined."""
    buttons = []
    for ch in not_joined:
        buttons.append([InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"])])
    buttons.append([InlineKeyboardButton("✅ Đã tham gia / I joined" , callback_data="check_joined")])
    return InlineKeyboardMarkup(buttons)

async def update_pending_positions(app):
    for i, item in enumerate(pending_items):
        position = i + 1
        ahead = i
        try:
            await app.bot.edit_message_text(
                chat_id=item['chat_id'],
                message_id=item['message_id'],
                text=T("queued", item['lang']).format(item['username'], position, ahead),
                parse_mode=ParseMode.HTML
            )
            if ahead == 2:
                try:
                    await app.bot.send_message(
                        chat_id=item['chat_id'],
                        text=T("queue_almost", item['lang']),
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
        except:
            pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    lang = db.get_lang(user_id) or DEFAULT_LANG
    
    # Group-only restriction (admin/VIP bypass)
    if update.effective_chat.type == "private" and not can_bypass_limit(user_id):
        await update.message.reply_text(
            f"{E_ERROR} <b>Bot chỉ hoạt động trong nhóm DINO!</b>\n\n"
            f"👉 <a href='https://t.me/dinotool'>Tham gia DINO 🛠</a> để sử dụng bot.",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        return
    
    if not db.get_user_usage(user_id):
        pass 

    await update.message.reply_text(
        T("welcome", lang),
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_menu_keyboard(lang)
    )

async def setlang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_language_select(update)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = db.get_lang(user_id) or DEFAULT_LANG
    
    help_text = T("help_msg", lang)
    if user_id == ADMIN_ID:
        help_text += (
            f"\n\n<b>👑 Admin Control:</b>\n"
            f"/noti [msg] - Broadcast message\n"
            f"/rs [id] - Reset usage limit\n"
            f"/setdonate - Set success photo\n"
            f"/stats - View detailed statistics\n"
            f"/addtoken [name] - Add new token\n"
            f"/tokens - List all tokens\n"
            f"/deltoken [id] - Delete token\n"
            f"/addvip [user_id] - Add VIP user\n"
            f"/delvip [user_id] - Remove VIP\n"
            f"/vips - List VIP users\n"
            f"/on - Turn bot ON\n"
            f"/off - Turn bot OFF"
        )
        
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return

    stats = db.get_stats()
    vips = db.get_all_vips()
    msg = (
        f"{E_STAT} <b>SYSTEM STATISTICS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{E_USER} <b>Active Users</b>: {stats['unique_users']}\n"
        f"{E_GLOBE} <b>Total Requests</b>: {stats['total']}\n"
        f"{E_SUCCESS} <b>Success</b>: {stats['success']}\n"
        f"{E_ERROR} <b>Failed</b>: {stats['fail']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{E_ANDROID} <b>Active Workers</b>: {NUM_WORKERS}\n"
        f"🔑 <b>Token Sets</b>: {len(TOKEN_SETS)}\n"
        f"⏳ <b>Queue Size</b>: {request_queue.qsize()}\n"
        f"👑 <b>VIP Users</b>: {len(vips)}\n"
        f"🔄 <b>Bot Status</b>: {'🟢 ON' if bot_enabled else '🔴 OFF'}\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

# --- Admin Commands ---
async def broadcast_worker(bot, users, text, chat_id, message_id):
    success = 0
    fail = 0
    total = len(users)
    
    for i, uid in enumerate(users):
        try:
            await bot.send_message(chat_id=uid, text=f"📢 <b>ADMIN NOTIFICATION</b>\n\n{text}", parse_mode=ParseMode.HTML)
            success += 1
        except Exception:
            fail += 1
            
        if (i + 1) % 5 == 0 or (i + 1) == total:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=(
                        f"{E_LOADING} <b>Broadcasting...</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"🔄 <b>Progress</b>: {i+1}/{total}\n"
                        f"{E_SUCCESS} <b>Success</b>: {success}\n"
                        f"{E_ERROR} <b>Failed</b>: {fail}"
                    ),
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
        
        await asyncio.sleep(0.05)

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=(
                f"{E_SUCCESS} <b>Broadcast Complete!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"👥 <b>Total</b>: {total}\n"
                f"{E_SUCCESS} <b>Success</b>: {success}\n"
                f"{E_ERROR} <b>Failed</b>: {fail}"
            ),
            parse_mode=ParseMode.HTML
        )
    except:
        pass

async def noti_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = db.get_lang(user_id) or DEFAULT_LANG
    
    if user_id != ADMIN_ID:
        return
        
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("Usage: /noti {message}")
        return

    users = db.get_all_users()
    if not users:
        await update.message.reply_text("No users found.")
        return

    status_msg = await update.message.reply_text(
        f"{E_LOADING} <b>Starting broadcast to {len(users)} users...</b>",
        parse_mode=ParseMode.HTML
    )
    
    asyncio.create_task(broadcast_worker(context.bot, users, msg, status_msg.chat_id, status_msg.message_id))

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = db.get_lang(user_id) or DEFAULT_LANG
    
    if user_id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("Usage: /rs {user_id}")
        return
        
    try:
        target_id = int(context.args[0])
        db.reset_usage(target_id)
        await update.message.reply_text(T("admin_reset", lang).format(target_id))
    except ValueError:
        await update.message.reply_text("Invalid User ID")

async def set_donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    photo = None
    if update.message.reply_to_message and update.message.reply_to_message.photo:
        photo = update.message.reply_to_message.photo[-1]
    elif update.message.photo:
        photo = update.message.photo[-1]
        
    if photo:
        file_id = photo.file_id
        db.set_config("donate_photo", file_id)
        await update.message.reply_text(f"✅ Updated Donate Photo ID:\n<code>{file_id}</code>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("❌ Please reply to a photo with /setdonate to set it.")

# --- Bot On/Off ---
async def bot_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_enabled
    if update.effective_user.id != ADMIN_ID: return
    bot_enabled = True
    lang = db.get_lang(update.effective_user.id) or DEFAULT_LANG
    await update.message.reply_text(T("bot_on", lang), parse_mode=ParseMode.HTML)

async def bot_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_enabled
    if update.effective_user.id != ADMIN_ID: return
    bot_enabled = False
    lang = db.get_lang(update.effective_user.id) or DEFAULT_LANG
    await update.message.reply_text(T("bot_off", lang), parse_mode=ParseMode.HTML)

# --- Token Management ---
async def addtoken_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    lang = db.get_lang(user_id) or DEFAULT_LANG
    
    name = " ".join(context.args) if context.args else f"Token_{len(TOKEN_SETS)+1}"
    context.user_data['pending_token_name'] = name
    
    await update.message.reply_text(
        T("token_prompt", lang),
        parse_mode=ParseMode.HTML,
        reply_markup=ForceReply(selective=True, input_field_placeholder="Paste request content...")
    )

async def tokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    
    if not TOKEN_SETS:
        await update.message.reply_text(f"{E_ERROR} No tokens configured.")
        return
    
    msg = f"🔑 <b>TOKEN LIST</b> ({len(TOKEN_SETS)} tokens)\n━━━━━━━━━━━━━━━━━━━\n"
    for i, t in enumerate(TOKEN_SETS):
        name = t.get('name', f'Token_{i+1}')
        sandbox = "🟡 Sandbox" if t.get('is_sandbox') else "🟢 Production"
        ft_short = t.get('fetch_token', '')[:30] + '...'
        msg += f"\n<b>#{i+1}</b> {name}\n{sandbox}\n<code>{ft_short}</code>\n"
    
    msg += f"\n━━━━━━━━━━━━━━━━━━━\n⚙️ Workers: {NUM_WORKERS} | Bot: {'🟢' if bot_enabled else '🔴'}"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def deltoken_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    lang = db.get_lang(user_id) or DEFAULT_LANG
    
    if not context.args:
        await update.message.reply_text("Usage: /deltoken {index}")
        return
    
    try:
        idx = int(context.args[0]) - 1
        if 0 <= idx < len(TOKEN_SETS):
            removed = TOKEN_SETS.pop(idx)
            # Also try to delete from DB if it has an id
            if removed.get('db_id'):
                db.delete_token(removed['db_id'])
            await update.message.reply_text(T("token_deleted", lang).format(idx + 1), parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(T("token_not_found", lang).format(context.args[0]), parse_mode=ParseMode.HTML)
    except ValueError:
        await update.message.reply_text("Invalid index")

# --- VIP Management ---
async def addvip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    lang = db.get_lang(user_id) or DEFAULT_LANG
    
    if not context.args:
        await update.message.reply_text("Usage: /addvip {user_id}")
        return
    
    try:
        target_id = int(context.args[0])
        db.add_vip(target_id)
        await update.message.reply_text(T("vip_added", lang).format(target_id), parse_mode=ParseMode.HTML)
    except ValueError:
        await update.message.reply_text("Invalid User ID")

async def delvip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    lang = db.get_lang(user_id) or DEFAULT_LANG
    
    if not context.args:
        await update.message.reply_text("Usage: /delvip {user_id}")
        return
    
    try:
        target_id = int(context.args[0])
        if db.remove_vip(target_id):
            await update.message.reply_text(T("vip_removed", lang).format(target_id), parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(T("vip_not_found", lang).format(target_id), parse_mode=ParseMode.HTML)
    except ValueError:
        await update.message.reply_text("Invalid User ID")

async def vips_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    
    vips = db.get_all_vips()
    if not vips:
        await update.message.reply_text(f"{E_ERROR} No VIP users.")
        return
    
    msg = f"👑 <b>VIP USERS</b> ({len(vips)})\n━━━━━━━━━━━━━━━━━━━\n"
    for uid, added_at in vips:
        msg += f"• <code>{uid}</code> (since {added_at})\n"
    
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

# --- UI Helpers ---
async def show_language_select(update: Update):
    keyboard = [
        [InlineKeyboardButton("Tiếng Việt 🇻🇳", callback_data="setlang_VI")],
        [InlineKeyboardButton("English 🇺🇸", callback_data="setlang_EN")]
    ]
    text = T("lang_select", "EN")
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

def can_bypass_limit(user_id):
    """Check if user can bypass the daily limit (admin or VIP)."""
    return user_id == ADMIN_ID or db.is_vip(user_id)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    lang = db.get_lang(user_id) or DEFAULT_LANG

    # Check if this is a pending addtoken reply (admin only, works anywhere)
    if context.user_data.get('pending_token_name') and user_id == ADMIN_ID:
        token_name = context.user_data.pop('pending_token_name')
        parsed = parse_request_text(text)
        
        if not parsed:
            await update.message.reply_text(T("token_parse_error", lang), parse_mode=ParseMode.HTML)
            return
        
        # Save to DB
        token_id = db.save_token(
            name=token_name,
            fetch_token=parsed['fetch_token'],
            app_transaction=parsed['app_transaction'],
            hash_params=parsed['hash_params'],
            hash_headers=parsed['hash_headers'],
            is_sandbox=parsed['is_sandbox']
        )
        
        # Add to runtime TOKEN_SETS
        new_token = {
            'db_id': token_id,
            'name': token_name,
            'fetch_token': parsed['fetch_token'],
            'app_transaction': parsed['app_transaction'],
            'hash_params': parsed['hash_params'],
            'hash_headers': parsed['hash_headers'],
            'is_sandbox': parsed['is_sandbox'],
        }
        TOKEN_SETS.append(new_token)
        
        await update.message.reply_text(T("token_added", lang).format(token_name), parse_mode=ParseMode.HTML)
        return

    # Must be a reply to bot message for regular text handling
    if not update.message.reply_to_message or not update.message.reply_to_message.from_user.is_bot:
        return

    # Group-only restriction (admin/VIP bypass)
    if update.effective_chat.type == "private" and not can_bypass_limit(user_id):
        await update.message.reply_text(
            f"{E_ERROR} <b>Bot chỉ hoạt động trong nhóm DINO!</b>\n\n"
            f"👉 <a href='https://t.me/dinotool'>Tham gia DINO 🛠</a> để sử dụng bot.",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        return

    # Maintenance check (admin and VIP bypass)
    if not bot_enabled and not can_bypass_limit(user_id):
        await update.message.reply_text(T("maintenance", lang), parse_mode=ParseMode.HTML)
        return

    if "locket.cam/" in text:
        username = text.split("locket.cam/")[-1].split("?")[0]
    elif len(text) < 50 and " " not in text:
        username = text
    else:
        username = text

    msg = await update.message.reply_text(T("resolving", lang), parse_mode=ParseMode.HTML)
    
    uid = await locket.resolve_uid(username)
    if not uid:
        await msg.edit_text(T("not_found", lang), parse_mode=ParseMode.HTML)
        return
        
    # VIP + Admin bypass limit check
    if not can_bypass_limit(user_id) and not db.check_can_request(user_id):
        await msg.edit_text(T("limit_reached", lang), parse_mode=ParseMode.HTML)
        return
        
    await msg.edit_text(T("checking_status", lang), parse_mode=ParseMode.HTML)
    status = await locket.check_status(uid)
    
    status_text = T("free_status", lang)
    if status and status.get("active"):
        status_text = T("gold_active", lang).format(status['expires'])
    
    safe_username = username[:30]
    keyboard = [[InlineKeyboardButton(T("btn_upgrade", lang), callback_data=f"upg|{uid}|{safe_username}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg.edit_text(
        f"{T('user_info_title', lang)}\n"
        f"{E_ID}: <code>{uid}</code>\n"
        f"{E_TAG}: <code>{username}</code>\n"
        f"{E_STAT} <b>Status</b>: {status_text}\n\n"
        f"👇",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    lang = db.get_lang(user_id) or DEFAULT_LANG

    if data.startswith("setlang_"):
        new_lang = data.split("_")[1]
        db.set_lang(user_id, new_lang)
        lang = new_lang
        await query.answer(f"Language: {new_lang}")
        await query.message.edit_text(
            T("menu_msg", lang),
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu_keyboard(lang)
        )
        return

    if data == "menu_lang":
        await show_language_select(update)
        return
        
    if data == "menu_help":
        help_text = T("help_msg", lang)
        if user_id == ADMIN_ID:
            help_text += (
                f"\n\n<b>👑 Admin Control:</b>\n"
                f"/noti [msg] - Broadcast message\n"
                f"/rs [id] - Reset usage limit\n"
                f"/setdonate - Set success photo\n"
                f"/stats - View detailed statistics\n"
                f"/addtoken - Add token\n"
                f"/tokens - List tokens\n"
                f"/deltoken - Delete token\n"
                f"/addvip /delvip /vips - VIP\n"
                f"/on /off - Toggle bot"
            )
            
        await query.edit_message_text(
            help_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_back")]])
        )
        return

    if data == "menu_back":
        await query.message.edit_text(
            T("menu_msg", lang),
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu_keyboard(lang)
        )
        return

    if data == "check_joined":
        # Re-check membership
        not_joined = await check_membership(context.bot, user_id)
        if not_joined:
            try:
                await query.answer("❌ Bạn chưa tham gia hết!", show_alert=True)
            except:
                pass
            return
        await query.answer("✅ OK!")
        await query.message.edit_text(
            T("menu_msg", lang),
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu_keyboard(lang)
        )
        return

    if data == "menu_input":
        # Maintenance check
        if not bot_enabled and not can_bypass_limit(user_id):
            await query.answer(T("maintenance", lang), show_alert=True)
            return
        # Channel membership check
        if not can_bypass_limit(user_id):
            not_joined = await check_membership(context.bot, user_id)
            if not_joined:
                try:
                    await query.answer()
                except:
                    pass
                await query.message.edit_text(
                    f"{E_ERROR} <b>Bạn cần tham gia các kênh sau trước khi dùng bot:</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_join_keyboard(not_joined, lang)
                )
                return
        try:
            await query.answer()
        except:
            pass
        await query.message.reply_text(
            T("prompt_input", lang),
            parse_mode=ParseMode.HTML,
            reply_markup=ForceReply(selective=True, input_field_placeholder="Username...")
        )
        return

    if data.startswith("upg|"):
        # Maintenance check
        if not bot_enabled and not can_bypass_limit(user_id):
            try:
                await query.answer(T("maintenance", lang), show_alert=True)
            except:
                pass
            return

        parts = data.split("|")
        uid = parts[1]
        username = parts[2] if len(parts) > 2 else uid
        
        # VIP + Admin bypass limit check
        if not can_bypass_limit(user_id) and not db.check_can_request(user_id):
            try:
                await query.answer(T("limit_reached", lang), show_alert=True)
            except:
                pass
            return
            
        try:
            await query.answer("🚀 Queue...")
        except:
            pass
        
        item = {
            'user_id': user_id,
            'uid': uid,
            'username': username,
            'chat_id': query.message.chat_id,
            'message_id': query.message.message_id,
            'lang': lang
        }
        
        async with queue_lock:
            pending_items.append(item)
            position = len(pending_items)
            ahead = position - 1
        
        await query.edit_message_text(
            T("queued", lang).format(username, position, ahead),
            parse_mode=ParseMode.HTML
        )
        
        await request_queue.put(item)
        return

async def queue_worker(app, worker_id):
    print(f"Worker #{worker_id} started...")
    
    while True:
        try:
            item = await request_queue.get()
            
            # Get token dynamically (round-robin across all current tokens)
            token_config = get_next_token()
            if not token_config:
                logger.error(f"Worker #{worker_id}: No tokens available!")
                request_queue.task_done()
                continue
            
            token_name = token_config.get('name', 'Unknown')
            
            user_id = item['user_id']
            uid = item['uid']
            username = item['username']
            chat_id = item['chat_id']
            message_id = item['message_id']
            lang = item['lang']
            
            async with queue_lock:
                if item in pending_items:
                    pending_items.remove(item)
                await update_pending_positions(app)
            
            print(f"{Clr.BLUE}[Worker #{worker_id}][{token_name}] Processing:{Clr.ENDC} UID={uid} | UserID={user_id}")
            
            async def edit(text):
                try:
                    await app.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    if "Message is not modified" in str(e):
                        pass
                    elif "Message to edit not found" in str(e):
                        pass
                    else:
                        logger.error(f"Edit msg error: {e}")

            # Double check limit before processing
            if not can_bypass_limit(user_id) and not db.check_can_request(user_id):
                await edit(T("limit_reached", lang))
                request_queue.task_done()
                continue
            
            logs = [f"[Worker #{worker_id}] Processing Request..."]
            loop = asyncio.get_running_loop()
            
            def safe_log_callback(msg):
                clean_msg = msg.replace(Clr.BLUE, "").replace(Clr.GREEN, "").replace(Clr.WARNING, "").replace(Clr.FAIL, "").replace(Clr.ENDC, "").replace(Clr.BOLD, "")
                logs.append(clean_msg)
                asyncio.run_coroutine_threadsafe(update_log_ui(), loop)

            async def update_log_ui():
                display_logs = "\n".join(logs[-10:])
                text = (
                    f"{E_LOADING} <b>⚡ SYSTEM EXPLOIT RUNNING...</b>\n"
                    f"<pre>{display_logs}</pre>"
                )
                try:
                    await app.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )
                except:
                    pass

            await update_log_ui()
            
            success, msg_result = await locket.inject_gold(uid, token_config, safe_log_callback)
            
            db.log_request(user_id, uid, "SUCCESS" if success else "FAIL")
            
            if success:
                if not can_bypass_limit(user_id):
                    db.increment_usage(user_id)
                    
                pid, link = await nextdns.create_profile(NEXTDNS_KEY, safe_log_callback)
                
                dns_text = ""
                if link:
                   dns_text = T('dns_msg', lang).format(link, pid)
                else:
                   dns_text = f"{E_ERROR} NextDNS Error: Check API Key"
                
                final_msg = (
                    f"{T('success_title', lang)}\n\n"
                    f"{E_TAG}: <code>{username}</code>\n"
                    f"{E_ID}: <code>{uid}</code>\n"
                    f"{E_CALENDAR} <b>Plan</b>: Gold\n"
                    f"⏰ <b>Expires</b>: <code>{msg_result}</code>\n"
                    f"{dns_text}"
                )
                
                await asyncio.sleep(2.0)
                
                try:
                    await app.bot.delete_message(chat_id=chat_id, message_id=message_id)
                except:
                    pass
                
                try:
                    current_photo = db.get_config("donate_photo", DONATE_PHOTO)
                    await app.bot.send_photo(
                        chat_id=chat_id,
                        photo=current_photo,
                        caption=final_msg,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Send photo error: {e}")
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=final_msg,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )


            else:
                final_msg = f"{T('fail_title', lang)}\nInfo:\n<code>{msg_result}</code>"
                await edit(final_msg)
                
            request_queue.task_done()
            
        except Exception as e:
            logger.error(f"Worker #{worker_id} Exception: {e}")
            request_queue.task_done()

def get_main_menu_keyboard(lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(T("btn_input", lang), callback_data="menu_input")],
        [InlineKeyboardButton(T("btn_lang", lang), callback_data="menu_lang"),
         InlineKeyboardButton(T("btn_help", lang), callback_data="menu_help")]
    ])

def load_db_tokens():
    """Load tokens from DB and merge into TOKEN_SETS."""
    db_tokens = db.get_all_tokens()
    for t in db_tokens:
        TOKEN_SETS.append({
            'db_id': t['id'],
            'name': t['name'],
            'fetch_token': t['fetch_token'],
            'app_transaction': t['app_transaction'],
            'hash_params': t['hash_params'],
            'hash_headers': t['hash_headers'],
            'is_sandbox': t['is_sandbox'],
        })

def run_bot():
    logging.basicConfig(
        format='%(message)s',
        level=logging.INFO
    )
    logging.getLogger("httpx").setLevel(logging.ERROR)
    logging.getLogger("telegram").setLevel(logging.ERROR)
    logging.getLogger("aiohttp").setLevel(logging.ERROR)

    # Load DB tokens on startup
    load_db_tokens()
    print(f"Loaded {len(TOKEN_SETS)} token sets total")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setlang", setlang_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("noti", noti_command))
    app.add_handler(CommandHandler("rs", reset_command))
    app.add_handler(CommandHandler("setdonate", set_donate_command))
    app.add_handler(CommandHandler("stats", stats_command))
    
    # New commands
    app.add_handler(CommandHandler("addtoken", addtoken_command))
    app.add_handler(CommandHandler("tokens", tokens_command))
    app.add_handler(CommandHandler("deltoken", deltoken_command))
    app.add_handler(CommandHandler("addvip", addvip_command))
    app.add_handler(CommandHandler("delvip", delvip_command))
    app.add_handler(CommandHandler("vips", vips_command))
    app.add_handler(CommandHandler("on", bot_on_command))
    app.add_handler(CommandHandler("off", bot_off_command))
    
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print(f"Bot is running... ({NUM_WORKERS} workers, {len(TOKEN_SETS)} tokens)")
    
    # Python 3.14 compatible: use async approach
    async def main():
        async with app:
            await app.start()
            # Clear old sessions & drop pending updates to avoid Conflict error
            await app.bot.delete_webhook(drop_pending_updates=True)
            await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
            
            # Start queue workers
            for i in range(1, NUM_WORKERS + 1):
                asyncio.create_task(queue_worker(app, i))
            
            # Keep running until stopped
            stop_event = asyncio.Event()
            try:
                await stop_event.wait()
            except (KeyboardInterrupt, SystemExit):
                pass
            finally:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
    
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
