# Thunder/utils/custom_dl.py

import asyncio
from typing import Any, AsyncGenerator, Dict

from pyrogram import Client
from pyrogram.errors import FloodWait
from pyrogram.types import Message

from Thunder.server.exceptions import FileNotFound
from Thunder.utils.file_properties import get_media
from Thunder.utils.logger import logger
from Thunder.vars import Var


class ByteStreamer:
    __slots__ = ('client', 'chat_id')

    def __init__(self, client: Client) -> None:
        self.client = client
        self.chat_id = int(Var.BIN_CHANNEL)

    async def get_message(self, message_id: int) -> Message:
        try:
            # Adicionado timeout de 15s para evitar que o bot fique "travado" infinitamente 
            # e force o fallback do servidor para outro bot.
            msg = await asyncio.wait_for(
                self.client.get_messages(self.chat_id, message_id), 
                timeout=15.0
            )
            if not msg or getattr(msg, 'empty', False):
                # Se a mensagem vier vazia, pode ser delay de propagação do Telegram
                raise FileNotFound(f"Message {message_id} doesn't contain any downloadable media")
            
            return msg
        except asyncio.TimeoutError:
            logger.warning(f"⏰ Timeout ao buscar mensagem {message_id} no bot {self.client.name}")
            raise Exception(f"Timeout no bot {self.client.name}")
        except FloodWait as e:
            # Não dormimos aqui, deixamos a rota tratar e trocar de bot
            raise e
        except Exception as e:
            if "doesn't contain any downloadable media" in str(e):
                raise e
            logger.debug(f"Error fetching message {message_id}: {e}")
            raise FileNotFound(f"Message {message_id} not found")

    async def stream_file(
        self, message_id: int, offset: int = 0, limit: int = 0
    ) -> AsyncGenerator[bytes, None]:
        message = await self.get_message(message_id)
        
        # Verifica se realmente tem mídia para evitar o ValueError do pyrogram
        media = get_media(message)
        if not media:
            raise ValueError("This message doesn't contain any downloadable media")

        chunk_offset = offset // (1024 * 1024)

        chunk_limit = 0
        if limit > 0:
            chunk_limit = ((limit + (1024 * 1024) - 1) // (1024 * 1024)) + 1

        try:
            async for chunk in self.client.stream_media(
                message, offset=chunk_offset, limit=chunk_limit
            ):
                yield chunk
        except FloodWait as e:
            raise e

    def get_file_info_sync(self, message: Message) -> Dict[str, Any]:
        media = get_media(message)
        if not media:
            return {"message_id": message.id, "error": "No media"}

        media_type = type(media).__name__.lower()
        file_name = getattr(media, 'file_name', None)
        mime_type = getattr(media, 'mime_type', None)

        if not file_name:
            ext_map = {
                "photo": "jpg",
                "audio": "mp3",
                "voice": "ogg",
                "video": "mp4",
                "animation": "mp4",
                "videonote": "mp4",
                "sticker": "webp",
            }
            ext = ext_map.get(media_type, "bin")
            file_name = f"Thunder_{message.id}.{ext}"

        if not mime_type:
            mime_map = {
                "photo": "image/jpeg",
                "voice": "audio/ogg",
                "videonote": "video/mp4",
            }
            mime_type = mime_map.get(media_type)

        return {
            "message_id": message.id,
            "file_size": getattr(media, 'file_size', 0) or 0,
            "file_name": file_name,
            "mime_type": mime_type,
            "unique_id": getattr(media, 'file_unique_id', None),
            "media_type": media_type
        }

    async def get_file_info(self, message_id: int) -> Dict[str, Any]:
        try:
            message = await self.get_message(message_id)
            return self.get_file_info_sync(message)
        except Exception as e:
            logger.debug(f"Error getting file info for {message_id}: {e}", exc_info=True)
            return {"message_id": message_id, "error": str(e)}
