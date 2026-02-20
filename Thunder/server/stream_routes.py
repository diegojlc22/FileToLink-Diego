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
# Bots que estão "cegos" para IDs específicos (delay de propagação do Telegram)
# Formato: {message_id: {client_id: expiration_timestamp}}
BLIND_CLIENTS_CACHE = {} 

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

def get_streamer(client_id: int) -> ByteStreamer:
    # Fix: Não cachear o streamer. O `clients.py` pode reiniciar o cliente e mudar o objeto na `multi_clients`.
    # Se usarmos cache, ficamos presos com um cliente "morto" e o bot trava.
    client = multi_clients.get(client_id)
    if not client:
        # Fallback de segurança
        logger.warning(f"Client {client_id} not found in multi_clients during get_streamer. Using primary.")
        client = multi_clients.get(0)
    return ByteStreamer(client)


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


def select_optimal_client(message_id: int = None) -> tuple[int, ByteStreamer]:
    if not work_loads:
        raise web.HTTPInternalServerError(text="No clients.")

    current_time = time.time()
    
    # Dicionário de cegueira para este arquivo
    blind_db = BLIND_CLIENTS_CACHE.get(message_id, {})

    # Lista de todos os bots que não estão banidos e enxergam o arquivo
    available_indices = []
    for cid in sorted(work_loads.keys()):
        # Pula se o bot estiver banido (FloodWait ou Erro Grave)
        if cid in BLACKLISTED_CLIENTS and current_time < BLACKLISTED_CLIENTS[cid]:
            continue
        
        # Pula se este bot estiver marcado como "cego" para este arquivo e ainda não expirou
        if message_id and cid in blind_db and current_time < blind_db[cid]:
            continue
            
        available_indices.append(cid)

    if not available_indices:
        # Se TUDO estiver banido ou cego, tentamos o que tiver menor carga (mesmo cego) 
        # para não travar totalmente e dar chance do propagation ter finalizado.
        candidates = sorted(work_loads.keys(), key=lambda x: work_loads.get(x, 0))
        for cid in candidates:
            if cid in BLACKLISTED_CLIENTS and current_time < BLACKLISTED_CLIENTS[cid]:
                continue
            return cid, get_streamer(cid)
        return 0, get_streamer(0)

    # PRIORIDADE: Conta de Usuário (Session ID 99) é infinitamente mais estável.
    if 99 in available_indices:
        # Se for o Master, ele aguenta muito mais carga.
        # Só passamos para os bots comuns se o Master estiver realmente sobrecarregado (ex: > 400 conexões)
        if work_loads.get(99, 0) < 400:
            return 99, get_streamer(99)

    # RODÍZIO REAL: Escolhe o bot que tiver a MENOR carga no momento entre os disponíveis.
    client_id = min(available_indices, key=lambda x: work_loads.get(x, 0))
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
# Cache global de metadados para evitar FloodWait do Telegram no F5
FILE_INFO_CACHE = {}
# Futuros para evitar que múltiplas requests busquem o mesmo metadado ao mesmo tempo
METADATA_FETCHERS = {}

# ... (parse_media_request e select_optimal_client permanecem iguais)

async def fetch_file_info(message_id: int, streamer: ByteStreamer):
    """Busca informações do arquivo de forma segura e compartilhada."""
    if message_id in FILE_INFO_CACHE:
        return FILE_INFO_CACHE[message_id]
    
    # Se já tem alguém buscando, espera o resultado
    if message_id in METADATA_FETCHERS:
        fetcher = METADATA_FETCHERS[message_id]
        if isinstance(fetcher, asyncio.Future):
            return await fetcher
        return fetcher # Já é o resultado se não for Future
    
    # Cria uma "promessa"
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    METADATA_FETCHERS[message_id] = future
    
    try:
        file_info = None
        # Prioridade 1: Conta MASTER (99) - Vê tudo instantaneamente
        # Prioridade 2: Bot Principal (0)
        source_ids = [99, 0]
        
        for sid in source_ids:
            if sid in multi_clients:
                try:
                    s_name = "MASTER" if sid == 99 else "BOT 0"
                    logger.debug(f"🔍 Buscando metadados via {s_name} (ID {sid})...")
                    st = get_streamer(sid)
                    file_info = await asyncio.wait_for(st.get_file_info(message_id), timeout=10.0)
                    if file_info and file_info.get('unique_id'):
                        break
                except Exception:
                    continue
        
        # Último recurso: tenta no bot que a request veio (se não for nenhum dos acima)
        if not file_info:
            try:
                file_info = await asyncio.wait_for(streamer.get_file_info(message_id), timeout=8.0)
            except Exception as fe:
                logger.error(f"❌ Falha total metadados ID {message_id}: {fe}")
        
        if file_info and file_info.get('unique_id'):
            FILE_INFO_CACHE[message_id] = file_info
            if not future.done():
                future.set_result(file_info)
            return file_info
        else:
            err = FileNotFound("Metadados não encontrados.")
            if not future.done():
                future.set_exception(err)
            raise err
            
    except Exception as e:
        if not future.done():
            future.set_exception(e)
        raise
    finally:
        # Remove do dicionário de fetchers após um tempo para permitir re-tentativas se falhou
        # mas mantém no cache se deu certo.
        async def delayed_cleanup():
            await asyncio.sleep(5)
            METADATA_FETCHERS.pop(message_id, None)
        
        asyncio.create_task(delayed_cleanup())


@routes.get(r"/{path:.+}", allow_head=True)
async def media_delivery(request: web.Request):
    try:
        path = request.match_info["path"]
        message_id, secure_hash = parse_media_request(path, request.query)
        
        # Seleciona o melhor bot levando em conta a carga e se o bot enxerga o arquivo
        client_id, streamer = select_optimal_client(message_id)

        # Busca metadados de forma inteligente (evita o "choque" de 30 users ao mesmo tempo)
        try:
            file_info = await fetch_file_info(message_id, streamer)
        except Exception as e:
            logger.error(f"⚠️ Erro ao obter info do arquivo {message_id}: {e}")
            raise FileNotFound(f"ID {message_id} indisponível no momento.")

        if not file_info or not file_info.get('unique_id'):
            raise FileNotFound("ID único do arquivo não encontrado.")

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
                current_cid = client_id
                current_streamer = streamer
                
                # Armazenamos o bot original para decrementar a carga no final
                # Mas se trocarmos de bot, precisamos gerenciar isso com cuidado.
                active_cids = [current_cid]
                
                try:
                    bytes_sent = 0
                    while bytes_sent < content_length:
                        try:
                            bytes_to_skip = (start + bytes_sent) % CHUNK_SIZE
                            
                            async for chunk in current_streamer.stream_file(
                                    message_id, offset=start + bytes_sent, limit=content_length - bytes_sent):
                                
                                # Ajuste de skip para o primeiro chunk de cada nova conexão/bot
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
                            
                            # Se saiu do loop e terminou, encerramos o while
                            break

                        except Exception as e:
                            err_str = str(e)
                            is_no_media = "doesn't contain any downloadable media" in err_str
                            
                            if is_no_media:
                                logger.warning(f"🔄 Bot {current_cid} não viu ID {message_id}. Aguardando propagação...")
                                await asyncio.sleep(3.5) # Espera um pouco mais
                            
                            # Marca o bot atual como "cego" ou "banido"
                            if is_no_media:
                                if message_id not in BLIND_CLIENTS_CACHE:
                                    BLIND_CLIENTS_CACHE[message_id] = {}
                                BLIND_CLIENTS_CACHE[message_id][current_cid] = time.time() + 45
                            else:
                                wait_time = getattr(e, 'value', 60)
                                logger.error(f"❌ Bot {current_cid} falhou: {e}. 'Esfriando' por {wait_time}s.")
                                BLACKLISTED_CLIENTS[current_cid] = time.time() + wait_time
                            
                            # Tenta buscar um novo bot
                            try:
                                next_id, next_streamer = select_optimal_client(message_id)
                                if next_id == current_cid:
                                    # Se o bot selecionado for o mesmo, significa que não há outros 
                                    # disponíveis ou o Bot 0 é a única opção restante.
                                    if is_no_media and current_cid != 0:
                                        # Forçamos o Bot 0 como última esperança se não for ele quem falhou
                                        next_id = 0
                                        next_streamer = get_streamer(0)
                                    else:
                                        # Se já é o Bot 0 ou não tem mais nada, raise o erro original
                                        raise e
                                
                                logger.warning(f"🔄 Fallback: Trocando do Bot {current_cid} para Bot {next_id}...")
                                
                                # Gerencia carga: decrementa do antigo, incrementa no novo
                                work_loads[next_id] += 1
                                active_cids.append(next_id)
                                
                                current_cid = next_id
                                current_streamer = next_streamer
                                # O loop `while` recomeça a partir do `bytes_sent` atual com o novo bot
                                
                            except Exception as fe:
                                logger.error(f"🚨 Sem bots disponíveis para fallback: {fe}")
                                raise e # Levanta o erro original que causou a falha do bot anterior

                finally:
                    # Decrementa a carga de todos os bots que foram usados nesta request
                    for cid in active_cids:
                        if cid in work_loads:
                            work_loads[cid] -= 1

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
