# Thunder/bot/clients.py

import asyncio

from pyrogram import Client
from pyrogram.errors import FloodWait

from Thunder.bot import StreamBot, multi_clients, work_loads
from Thunder.utils.config_parser import TokenParser
from Thunder.utils.logger import logger
from Thunder.vars import Var

async def cleanup_clients():
    for client in multi_clients.values():
        try:
            try:
                await client.stop()
            except FloodWait as e:
                await asyncio.sleep(e.value)
                await client.stop()
        except Exception as e:
            logger.error(f"Error stopping client: {e}", exc_info=True)

async def initialize_clients():
    print("╠══════════════════ INITIALIZING CLIENTS ═══════════════════╣")
    multi_clients[0] = StreamBot
    work_loads[0] = 0
    print("   ✓ Primary client initialized")
    try:
        all_tokens = TokenParser().parse_from_env()
        if not all_tokens:
            print("   ◎ No additional clients found.")
            return
    except Exception as e:
        logger.error(f"   ✖ Error parsing additional tokens: {e}", exc_info=True)
        print("   ▶ Primary client will be used.")
        return

    async def start_client(client_id, token):
        try:
            if client_id == len(all_tokens):
                await asyncio.sleep(2)
            client = Client(
                api_hash=Var.API_HASH,
                api_id=Var.API_ID,
                bot_token=token,
                in_memory=True,
                name=str(client_id),
                no_updates=True,
                max_concurrent_transmissions=1000,
                sleep_threshold=Var.SLEEP_THRESHOLD
            )
            try:
                # Tenta iniciar o bot com um tempo limite de 15 segundos
                await asyncio.wait_for(client.start(), timeout=15.0)
            except asyncio.TimeoutError:
                logger.error(f"   ✖ Tempo esgotado ao ligar o Cliente {client_id}. Ignorando.")
                return None
            except FloodWait as e:
                logger.warning(f"   ◎ Cliente {client_id} em FloodWait ({e.value}s).")
                return None
            
            # Pequeno teste para ver se o bot enxerga o canal
            try:
                await client.get_chat(Var.BIN_CHANNEL)
            except Exception:
                logger.warning(f"   ◎ Cliente {client_id} não tem acesso ao canal BIN_CHANNEL.")
            
            work_loads[client_id] = 0
            print(f"   ◎ Client ID {client_id} started")
            return client_id, client
        except Exception as e:
            logger.error(f"   ✖ Failed to start Client ID {client_id}. Error: {e}", exc_info=True)
            return None

    clients_results = await asyncio.gather(*[start_client(i, token) for i, token in all_tokens.items() if token])
    
    for res in clients_results:
        if res:
            cid, client = res
            multi_clients[cid] = client

    if len(multi_clients) > 1:
        Var.MULTI_CLIENT = True
        print("╠══════════════════════ MULTI-CLIENT ═══════════════════════╣")
        print(f"   ◎ Total Clients: {len(multi_clients)} (Including primary client)")
    else:
        print("╠═══════════════════════════════════════════════════════════╣")
        print("   ▶ No additional clients available at the moment.")

    # Task de background para tentar religar bots que falharam (útil para FloodWait)
    failed_tokens = {i: token for i, token in all_tokens.items() if i not in multi_clients}
    if failed_tokens:
        async def retry_failed_clients():
            await asyncio.sleep(60) # Espera 1 minuto antes de tentar a primeira vez
            for cid, token in failed_tokens.copy().items():
                if cid not in multi_clients:
                    res = await start_client(cid, token)
                    if res:
                        multi_clients[res[0]] = res[1]
                        del failed_tokens[cid]
                        logger.info(f"✅ Cliente {cid} recuperado e ativo!")

        asyncio.create_task(retry_failed_clients())
