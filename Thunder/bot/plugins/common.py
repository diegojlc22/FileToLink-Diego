# Thunder/bot/plugins/common.py

import asyncio
import time
from datetime import datetime, timedelta

from pyrogram import Client, filters
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                            Message, User)

from Thunder.bot import StreamBot
from Thunder.utils.bot_utils import (gen_dc_txt, get_user, log_newusr,
                                     reply_user_err)
from Thunder.utils.database import db
from Thunder.utils.decorators import check_banned
from Thunder.utils.file_properties import get_fname, get_fsize, parse_fid
from Thunder.utils.force_channel import force_channel_check, get_force_info
from Thunder.utils.human_readable import humanbytes
from Thunder.utils.logger import logger
from Thunder.utils.messages import (
    MSG_ABOUT, MSG_BUTTON_ABOUT, MSG_BUTTON_CLOSE, MSG_BUTTON_GET_HELP,
    MSG_BUTTON_GITHUB, MSG_BUTTON_JOIN_CHANNEL, MSG_BUTTON_VIEW_PROFILE,
    MSG_COMMUNITY_CHANNEL, MSG_DC_ANON_ERROR, MSG_DC_FILE_ERROR,
    MSG_DC_FILE_INFO, MSG_DC_INVALID_USAGE, MSG_DC_UNKNOWN,
    MSG_ERROR_USER_INFO, MSG_FILE_TYPE_ANIMATION, MSG_FILE_TYPE_AUDIO,
    MSG_FILE_TYPE_DOCUMENT, MSG_FILE_TYPE_PHOTO, MSG_FILE_TYPE_STICKER,
    MSG_FILE_TYPE_UNKNOWN, MSG_FILE_TYPE_VIDEO, MSG_FILE_TYPE_VIDEO_NOTE,
    MSG_FILE_TYPE_VOICE, MSG_HELP, MSG_PING_RESPONSE, MSG_PING_START,
    MSG_TOKEN_ACTIVATED, MSG_TOKEN_FAILED, MSG_TOKEN_INVALID, MSG_WELCOME
)
from Thunder.vars import Var

@StreamBot.on_message(filters.command("start") & filters.private)
async def start_command(bot: Client, msg: Message):
    if not await check_banned(bot, msg):
        return
    user = msg.from_user
    if user:
        await log_newusr(bot, user.id, user.first_name)
    
    txt = MSG_WELCOME.format(user_name=user.first_name if user else "Unknown")
    
    btns = [
        [InlineKeyboardButton(MSG_BUTTON_CLOSE, callback_data="close_panel")]
    ]
    
    try:
        await msg.reply_text(text=txt, reply_markup=InlineKeyboardMarkup(btns))
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await msg.reply_text(text=txt, reply_markup=InlineKeyboardMarkup(btns))

# Secondary commands (help, about, ping, dc) removed to make the bot lighter.

