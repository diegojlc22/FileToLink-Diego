# Thunder/bot/plugins/admin.py

import asyncio
import html
import os
import shutil
import sys
import time
from io import BytesIO

import psutil
from pyrogram import filters
from pyrogram.client import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from Thunder import StartTime, __version__
from Thunder.bot import StreamBot, multi_clients, work_loads
from Thunder.utils.bot_utils import reply
from Thunder.utils.database import db
from Thunder.utils.human_readable import humanbytes
from Thunder.utils.logger import LOG_FILE, logger
from Thunder.utils.messages import (
    MSG_BUTTON_CLOSE, MSG_DB_ERROR, MSG_DB_STATS,
    MSG_ERROR_GENERIC, MSG_LOG_FILE_CAPTION, MSG_LOG_FILE_EMPTY,
    MSG_LOG_FILE_MISSING, MSG_RESTARTING, 
    MSG_SPEEDTEST_ERROR, MSG_SPEEDTEST_INIT, MSG_SPEEDTEST_RESULT,
    MSG_STATUS_ERROR, MSG_SYSTEM_STATS, MSG_SYSTEM_STATUS,
    MSG_WORKLOAD_ITEM
)
from Thunder.utils.time_format import get_readable_time
from Thunder.utils.speedtest import run_speedtest
from Thunder.vars import Var

owner_filter = filters.private & filters.user(Var.OWNER_ID)


@StreamBot.on_message(filters.command("users") & owner_filter)
async def get_total_users(client: Client, message: Message):
    try:
        total = await db.total_users_count()
        await reply(message,
                    text=MSG_DB_STATS.format(total_users=total),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton(MSG_BUTTON_CLOSE, callback_data="close_panel")]]))
    except Exception as e:
        logger.error(f"Error in get_total_users: {e}", exc_info=True)
        await reply(message, text=MSG_DB_ERROR)





@StreamBot.on_message(filters.command("status") & owner_filter)
async def show_status(client: Client, message: Message):
    try:
        uptime_str = get_readable_time(int(time.time() - StartTime))
        workload_items = ""
        sorted_workloads = sorted(work_loads.items(), key=lambda item: item[0])
        for client_id, load_val in sorted_workloads:
            workload_items += MSG_WORKLOAD_ITEM.format(
                bot_name=f"🔹 Client {client_id}", load=load_val)

        total_workload = sum(work_loads.values())
        status_text_str = MSG_SYSTEM_STATUS.format(
            uptime=uptime_str, active_bots=len(multi_clients),
            total_workload=total_workload, workload_items=workload_items,
            version=__version__)
        await reply(message,
                    text=status_text_str,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton(MSG_BUTTON_CLOSE, callback_data="close_panel")]]))
    except Exception as e:
        logger.error(f"Error in show_status: {e}", exc_info=True)
        await reply(message, text=MSG_STATUS_ERROR)


@StreamBot.on_message(filters.command("stats") & owner_filter)
async def show_stats(client: Client, message: Message):
    try:
        sys_uptime = await asyncio.to_thread(psutil.boot_time)
        sys_uptime_str = get_readable_time(int(time.time() - sys_uptime))
        bot_uptime_str = get_readable_time(int(time.time() - StartTime))
        net_io_counters = await asyncio.to_thread(psutil.net_io_counters)
        cpu_percent = await asyncio.to_thread(psutil.cpu_percent, interval=0.5)
        cpu_cores = await asyncio.to_thread(psutil.cpu_count, logical=False)
        cpu_freq = await asyncio.to_thread(psutil.cpu_freq)
        cpu_freq_ghz = f"{cpu_freq.current / 1000:.2f}" if cpu_freq else "N/A"
        ram_info = await asyncio.to_thread(psutil.virtual_memory)
        ram_total = humanbytes(ram_info.total)
        ram_used = humanbytes(ram_info.used)
        ram_free = humanbytes(ram_info.free)

        total_disk, used_disk, free_disk = await asyncio.to_thread(
            shutil.disk_usage, '.')

        stats_text_val = MSG_SYSTEM_STATS.format(
            sys_uptime=sys_uptime_str,
            bot_uptime=bot_uptime_str,
            cpu_percent=cpu_percent,
            cpu_cores=cpu_cores,
            cpu_freq=cpu_freq_ghz,
            ram_total=ram_total,
            ram_used=ram_used,
            ram_free=ram_free,
            disk_percent=psutil.disk_usage('.').percent,
            total=humanbytes(total_disk),
            used=humanbytes(used_disk),
            free=humanbytes(free_disk),
            upload=humanbytes(net_io_counters.bytes_sent),
            download=humanbytes(net_io_counters.bytes_recv)
        )

        await reply(message,
                    text=stats_text_val,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton(MSG_BUTTON_CLOSE, callback_data="close_panel")]]))
    except Exception as e:
        logger.error(f"Error in show_stats: {e}", exc_info=True)
        await reply(message, text=MSG_STATUS_ERROR)


@StreamBot.on_message(filters.command("restart") & owner_filter)
async def restart_bot(client: Client, message: Message):
    msg = await reply(message, text=MSG_RESTARTING)
    await db.add_restart_message(msg.id, message.chat.id)
    os.execv("/bin/bash", ["bash", "thunder.sh"])


@StreamBot.on_message(filters.command("log") & owner_filter)
async def send_logs(client: Client, message: Message):
    if not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0:
        await reply(
            message,
            text=(MSG_LOG_FILE_MISSING if not os.path.exists(LOG_FILE) else MSG_LOG_FILE_EMPTY)
        )
        return
    
    try:
        try:
            await message.reply_document(LOG_FILE, caption=MSG_LOG_FILE_CAPTION)
        except FloodWait as e:
            logger.debug(f"FloodWait in log file sending, sleeping for {e.value}s")
            await asyncio.sleep(e.value)
            await message.reply_document(LOG_FILE, caption=MSG_LOG_FILE_CAPTION)
    except Exception as e:
        logger.error(f"Error sending log file: {e}", exc_info=True)
        await reply(message, text=MSG_ERROR_GENERIC)


# Commands for Authorization, Banning, and Shell have been removed to make the bot lighter.





@StreamBot.on_message(filters.command("speedtest") & owner_filter)
async def speedtest_command(client: Client, message: Message):
    status_msg = await reply(message, text=MSG_SPEEDTEST_INIT)
    try:
        result_dict, image_url = await run_speedtest()
        if result_dict is None:
            try:
                await status_msg.edit_text(MSG_SPEEDTEST_ERROR)
            except FloodWait as e:
                logger.debug(f"FloodWait in speedtest error edit, sleeping for {e.value}s")
                await asyncio.sleep(e.value)
                await status_msg.edit_text(MSG_SPEEDTEST_ERROR)
            except MessageNotModified:
                pass
            return
        
        result_text = _format_speedtest_result(result_dict)
        await _send_result(message, status_msg, result_text, image_url)
    except Exception as e:
        logger.error(f"Error in speedtest_command: {e}", exc_info=True)
        try:
            try:
                await status_msg.edit_text(MSG_SPEEDTEST_ERROR)
            except FloodWait as e:
                logger.debug(f"FloodWait in speedtest exception error edit, sleeping for {e.value}s")
                await asyncio.sleep(e.value)
                await status_msg.edit_text(MSG_SPEEDTEST_ERROR)
            except MessageNotModified:
                pass
        except Exception:
            await reply(message, text=MSG_SPEEDTEST_ERROR)


def _format_speedtest_result(result_dict: dict) -> str:
    s, c = result_dict['server'], result_dict['client']
    return MSG_SPEEDTEST_RESULT.format(
        download_mbps=_fmt(result_dict['download_mbps']),
        upload_mbps=_fmt(result_dict['upload_mbps']),
        download_bps=humanbytes(result_dict['download_bps']),
        upload_bps=humanbytes(result_dict['upload_bps']),
        ping=_fmt(result_dict['ping']),
        timestamp=result_dict['timestamp'],
        bytes_sent=humanbytes(result_dict['bytes_sent']),
        bytes_received=humanbytes(result_dict['bytes_received']),
        server_name=s['name'],
        server_country=f"{s['country']} ({s['cc']})",
        server_sponsor=s['sponsor'],
        server_latency=_fmt(s['latency']),
        server_lat=_fmt(s['lat'], 4),
        server_lon=_fmt(s['lon'], 4),
        client_ip=c['ip'],
        client_lat=_fmt(c['lat'], 4),
        client_lon=_fmt(c['lon'], 4),
        client_isp=c['isp'],
        client_isprating=c['isprating'],
        client_country=c['country']
    )


async def _send_result(message: Message, status_msg: Message, result_text: str, image_url: str):
    if image_url:
        try:
            await message.reply_photo(image_url, caption=result_text, parse_mode=ParseMode.MARKDOWN)
        except FloodWait as e:
            logger.debug(f"FloodWait in speedtest photo reply, sleeping for {e.value}s")
            await asyncio.sleep(e.value)
            await message.reply_photo(image_url, caption=result_text, parse_mode=ParseMode.MARKDOWN)
        try:
            await status_msg.delete()
        except FloodWait as e:
            logger.debug(f"FloodWait in speedtest status delete, sleeping for {e.value}s")
            await asyncio.sleep(e.value)
            await status_msg.delete()
    else:
        try:
            await status_msg.edit_text(result_text, parse_mode=ParseMode.MARKDOWN)
        except FloodWait as e:
            logger.debug(f"FloodWait in speedtest result edit, sleeping for {e.value}s")
            await asyncio.sleep(e.value)
            await status_msg.edit_text(result_text, parse_mode=ParseMode.MARKDOWN)
        except MessageNotModified:
            pass


def _fmt(value, decimals: int = 2) -> str:
    return f"{float(value):.{decimals}f}"
