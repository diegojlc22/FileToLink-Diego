# Thunder/server/stream_routes.py

import asyncio
import re
import secrets
import time
from urllib.parse import quote, unquote

from aiohttp import web

from Thunder import __version__, StartTime
from pyrogram.errors import FloodWait
from Thunder.bot import StreamBot, multi_clients, work_loads
from Thunder.server.exceptions import FileNotFound, InvalidHash
from Thunder.utils.custom_dl import ByteStreamer
from Thunder.utils.logger import logger
from Thunder.utils.render_template import render_page
from Thunder.utils.time_format import get_readable_time

routes = web.RouteTableDef()

SECURE_HASH_LENGTH = 6
CHUNK_SIZE = 1024 * 1024
MAX_CONCURRENT_PER_CLIENT = 100
RANGE_REGEX = re.compile(r"bytes=(?P<start>\d*)-(?P<end>\d*)")

# Cache global de metadados para evitar FloodWait do Telegram no F5
FILE_INFO_CACHE = {}

# Controle de bots que estão dando erro (ex: Message Not Found)
BLACKLISTED_CLIENTS = {} # {client_id: expiration_timestamp}

PATTERN_HASH_FIRST = re.compile(
    rf"^([a-zA-Z0-9_-]{{{SECURE_HASH_LENGTH}}})(\d+)(?:/.*)?$")
PATTERN_ID_FIRST = re.compile(r"^(\d+)(?:/.*)?$")
VALID_HASH_REGEX = re.compile(r'^[a-zA-Z0-9_-]+$')

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Range, Content-Type, *",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Content-Disposition",
}

streamers = {}


def get_streamer(client_id: int) -> ByteStreamer:
    if client_id not in streamers:
        streamers[client_id] = ByteStreamer(multi_clients[client_id])
    return streamers[client_id]


def parse_media_request(path: str, query: dict) -> tuple[int, str]:
    clean_path = unquote(path).strip('/')

    match = PATTERN_HASH_FIRST.match(clean_path)
    if match:
        try:
            message_id = int(match.group(2))
            secure_hash = match.group(1)
            if (len(secure_hash) == SECURE_HASH_LENGTH and
                    VALID_HASH_REGEX.match(secure_hash)):
                return message_id, secure_hash
        except ValueError as e:
            raise InvalidHash(f"Invalid message ID format in path: {e}") from e

    match = PATTERN_ID_FIRST.match(clean_path)
    if match:
        try:
            message_id = int(match.group(1))
            secure_hash = query.get("hash", "").strip()
            if (len(secure_hash) == SECURE_HASH_LENGTH and
                    VALID_HASH_REGEX.match(secure_hash)):
                return message_id, secure_hash
            else:
                raise InvalidHash("Invalid or missing hash in query parameter")
        except ValueError as e:
            raise InvalidHash(f"Invalid message ID format in path: {e}") from e

    raise InvalidHash("Invalid URL structure or missing hash")


def select_optimal_client() -> tuple[int, ByteStreamer]:
    if not work_loads:
        raise web.HTTPInternalServerError(text="No clients.")

    current_time = time.time()
    
    # Lista de todos os bots que não estão banidos
    available_indices = []
    for cid in sorted(work_loads.keys()):
        if cid in BLACKLISTED_CLIENTS:
            if current_time < BLACKLISTED_CLIENTS[cid]:
                continue
            else:
                del BLACKLISTED_CLIENTS[cid]
        available_indices.append(cid)

    if not available_indices:
        # Se TUDO estiver banido, tenta o Bot 0 como última esperança
        logger.warning("ALERTA: Todos os bots estão banidos! Tentando Bot 0.")
        return 0, get_streamer(0)

    # Sempre prefere o Bot 0 se ele estiver disponível
    if 0 in available_indices:
        return 0, get_streamer(0)

    # Se Bot 0 está banido, usa o secundário com menos carga
    client_id = min(available_indices, key=lambda x: work_loads[x])
    return client_id, get_streamer(client_id)


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    if not range_header:
        return 0, file_size - 1

    match = RANGE_REGEX.match(range_header)
    if not match:
        raise web.HTTPBadRequest(text=f"Invalid range header: {range_header}")

    start_str = match.group("start")
    end_str = match.group("end")
    if start_str:
        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1
    else:
        if not end_str:
            raise web.HTTPBadRequest(text=f"Invalid range header: {range_header}")
        suffix_len = int(end_str)
        if suffix_len <= 0:
            raise web.HTTPRequestRangeNotSatisfiable(
                headers={"Content-Range": f"bytes */{file_size}"})
        start = max(file_size - suffix_len, 0)
        end = file_size - 1

    if start < 0 or end >= file_size or start > end:
        raise web.HTTPRequestRangeNotSatisfiable(
            headers={"Content-Range": f"bytes */{file_size}"}
        )

    return start, end


@routes.get("/", allow_head=True)
async def root_redirect(request):
    raise web.HTTPFound("https://github.com/fyaz05/FileToLink")


@routes.get("/status", allow_head=True)
async def status_endpoint(request):
    uptime = time.time() - StartTime
    total_load = sum(work_loads.values())

    workload_distribution = {str(k): v for k, v in sorted(work_loads.items())}

    return web.json_response(
        {
            "server": {
                "status": "operational",
                "version": __version__,
                "uptime": get_readable_time(uptime)
            },
            "telegram_bot": {
                "username": f"@{StreamBot.username}",
                "active_clients": len(multi_clients)
            },
            "resources": {
                "total_workload": total_load,
                "workload_distribution": workload_distribution
            }
        },
        headers={"Access-Control-Allow-Origin": "*"}
    )


@routes.options("/status")
async def status_options(request: web.Request):
    return web.Response(headers={
        **CORS_HEADERS,
        "Access-Control-Max-Age": "86400"
    })


@routes.options(r"/{path:.+}")
async def media_options(request: web.Request):
    return web.Response(headers={
        **CORS_HEADERS,
        "Access-Control-Max-Age": "86400"
    })


@routes.get(r"/watch/{path:.+}", allow_head=True)
async def media_preview(request: web.Request):
    try:
        path = request.match_info["path"]
        message_id, secure_hash = parse_media_request(path, request.query)

        rendered_page = await render_page(
            message_id, secure_hash, requested_action='stream')

        response = web.Response(
            text=rendered_page,
            content_type='text/html',
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Range, Content-Type, *",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
        response.enable_compression()
        return response

    except (InvalidHash, FileNotFound) as e:
        logger.debug(
            f"Client error in preview: {type(e).__name__} - {e}",
            exc_info=True)
        raise web.HTTPNotFound(text="Resource not found") from e
    except Exception as e:
        error_id = secrets.token_hex(6)
        logger.error(f"Preview error {error_id}: {e}", exc_info=True)
        raise web.HTTPInternalServerError(
            text=f"Server error occurred: {error_id}") from e


@routes.get(r"/{path:.+}", allow_head=True)
async def media_delivery(request: web.Request):
    try:
        path = request.match_info["path"]
        message_id, secure_hash = parse_media_request(path, request.query)
        
        # Define o streamer principal no início para evitar erros de UnboundLocalError
        main_streamer = get_streamer(0)

        # Tenta buscar do cache primeiro (evita FloodWait do Telegram no F5)
        if message_id in FILE_INFO_CACHE:
            file_info = FILE_INFO_CACHE[message_id]
            logger.debug(f"ℹ Usando cache para o arquivo {message_id}")
        else:
            try:
                file_info = await main_streamer.get_file_info(message_id)
                if file_info and file_info.get('unique_id'):
                    FILE_INFO_CACHE[message_id] = file_info
                    logger.info(f"✅ Metadados salvos no cache para o arquivo {message_id}")
            except Exception as e:
                logger.error(f"Erro crítico: Bot principal não conseguiu acessar arquivo {message_id}: {e}")
                raise FileNotFound("Arquivo não encontrado no bot principal.")

        if not file_info or not file_info.get('unique_id'):
            raise FileNotFound("ID único do arquivo não encontrado.")

        # PRIORIDADE TOTAL AO BOT 0 (O único 100% estável para IDs)
        # Os outros bots só entram se o 0 estiver em FloodWait real.
        client_id, streamer = select_optimal_client()

        work_loads[client_id] += 1
        logger.info(f"▶ [Bot {client_id}] Conexão iniciada. Carga: {work_loads[client_id]}")

        try:
            file_size = file_info.get('file_size', 0)
            if file_size == 0:
                raise FileNotFound(
                    "File size is reported as zero or unavailable.")

            range_header = request.headers.get("Range", "")
            start, end = parse_range_header(range_header, file_size)
            content_length = end - start + 1

            if start == 0 and end == file_size - 1:
                range_header = ""

            mime_type = (
                file_info.get('mime_type') or 'application/octet-stream')

            filename = file_info.get('file_name')
            if not filename:
                ext = mime_type.split('/')[-1] if '/' in mime_type else 'bin'
                ext_map = {'jpeg': 'jpg', 'mpeg': 'mp3', 'octet-stream': 'bin'}
                ext = ext_map.get(ext, ext)
                filename = f"file_{secrets.token_hex(4)}.{ext}"

            headers = {
                "Content-Type": mime_type,
                "Content-Length": str(content_length),
                "Accept-Ranges": "bytes",
                "Content-Disposition": f'inline; filename="{quote(filename)}"',
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "X-Content-Type-Options": "nosniff",
                **CORS_HEADERS
            }

            if range_header:
                headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

            if request.method == 'HEAD':
                work_loads[client_id] -= 1
                return web.Response(
                    status=206 if range_header else 200,
                    headers=headers
                )

            async def stream_generator():
                nonlocal client_id, streamer
                initial_client_id = client_id
                try:
                    bytes_sent = 0
                    bytes_to_skip = start % CHUNK_SIZE

                    try:
                        # Tenta iniciar o stream direto
                        async for chunk in streamer.stream_file(
                                message_id, offset=start, limit=content_length):
                            if bytes_to_skip > 0:
                                if len(chunk) <= bytes_to_skip:
                                    bytes_to_skip -= len(chunk)
                                    continue
                                chunk = chunk[bytes_to_skip:]
                                bytes_to_skip = 0

                            remaining = content_length - bytes_sent
                            if len(chunk) > remaining:
                                chunk = chunk[:remaining]

                            if chunk:
                                yield chunk
                                bytes_sent += len(chunk)

                            if bytes_sent >= content_length:
                                break
                    except (FloodWait, Exception) as e:
                        # Se qualquer bot falhar (ID errado ou FloodWait), banimos e tentamos outro
                        wait_time = getattr(e, 'value', 300) # 5 min se for erro comum
                        logger.error(f"❌ Bot {client_id} falhou: {e}. Banindo por {wait_time}s.")
                        BLACKLISTED_CLIENTS[client_id] = time.time() + wait_time
                        
                        # Tenta encontrar o próximo bot disponível (Fallback)
                        try:
                            next_id, next_streamer = select_optimal_client()
                            if next_id == client_id:
                                raise e # Se o seletor devolveu o mesmo, não há o que fazer
                                
                            logger.warning(f"🔄 Fallback: Trocando do Bot {client_id} para Bot {next_id}...")
                            async for chunk in next_streamer.stream_file(
                                    message_id, offset=start + bytes_sent, limit=content_length - bytes_sent):
                                yield chunk
                                bytes_sent += len(chunk)
                        except Exception as fe:
                            logger.error(f"🚨 Fallback final falhou: {fe}")
                            raise fe
                finally:
                    # Sempre desconta do bot que começou a tarefa original para manter a contagem certa
                    work_loads[initial_client_id] -= 1

            return web.Response(
                status=206 if range_header else 200,
                body=stream_generator(),
                headers=headers
            )

        except (FileNotFound, InvalidHash):
            work_loads[client_id] -= 1
            raise
        except Exception as e:
            work_loads[client_id] -= 1
            error_id = secrets.token_hex(6)
            logger.error(
                f"Stream error {error_id}: {e}",
                exc_info=True)
            raise web.HTTPInternalServerError(
                text=f"Server error during streaming: {error_id}") from e

    except (InvalidHash, FileNotFound) as e:
        logger.debug(f"Client error: {type(e).__name__} - {e}", exc_info=True)
        raise web.HTTPNotFound(text="Resource not found") from e
    except Exception as e:
        error_id = secrets.token_hex(6)
        logger.error(f"Server error {error_id}: {e}", exc_info=True)
        raise web.HTTPInternalServerError(
            text=f"An unexpected server error occurred: {error_id}") from e
