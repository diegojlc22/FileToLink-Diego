# Thunder/utils/keepalive.py

import asyncio
import aiohttp
from Thunder.vars import Var
from Thunder.utils.logger import logger

async def ping_server():
    # Timeout maior para o ping não falhar enquanto o vídeo está rodando
    timeout = aiohttp.ClientTimeout(total=45)
    while True:
        try:
            await asyncio.sleep(Var.PING_INTERVAL)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(Var.URL) as resp:
                    if resp.status != 200:
                        logger.warning(f"Ping status {resp.status} em {Var.URL}.")
        except asyncio.CancelledError:
            break
        except Exception as e:
            # Log discreto para não poluir
            logger.debug(f"Keep-alive ping falhou (Normal sob carga): {e}")
