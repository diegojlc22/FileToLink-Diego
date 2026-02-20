# Thunder/bot/clients.py

import asyncio
import os

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
    multi_clients[0] = StreamBot
    work_loads[0] = 0
    try:
        all_tokens = TokenParser().parse_from_env()
        if not all_tokens:
            print("   ◎ No additional clients found.")
            return
    except Exception as e:
        logger.error(f"   ✖ Error parsing additional tokens: {e}", exc_info=True)
        print("   ▶ Primary client will be used.")
        return

    async def start_client(client_id, token_or_session):
        try:
            is_bot = ":" in token_or_session
            client = Client(
                api_hash=Var.API_HASH,
                api_id=Var.API_ID,
                bot_token=token_or_session if is_bot else None,
                session_string=None if is_bot else token_or_session,
                in_memory=True,
                name=f"Client_{client_id}",
                no_updates=True,
                max_concurrent_transmissions=1000,
                sleep_threshold=Var.SLEEP_THRESHOLD
            )
            await asyncio.wait_for(client.start(), timeout=20.0)
            
            try:
                chat = await client.get_chat(Var.BIN_CHANNEL)
                logger.info(f"   ✓ Cliente {client_id} online: {chat.title}")
            except Exception as e:
                logger.error(f"   ✖ Cliente {client_id} sem acesso ao canal: {e}")
                if client_id == 0: raise e
                return None
            
            work_loads[client_id] = 0
            return client_id, client
        except Exception as e:
            logger.error(f"   ✖ Falha ao iniciar Cliente {client_id}: {e}")
            return None

    # Carrega tokens extras do ambiente
    config_tokens = TokenParser().parse_from_env()
    
    # Adiciona STRING_SESSION da classe Var (ID 99 reservado)
    if Var.STRING_SESSION:
        config_tokens[99] = Var.STRING_SESSION
        logger.info("   🔍 STRING_SESSION detectada! Preparando Cliente 99...")
    else:
        logger.warning("   ⚠️ STRING_SESSION não encontrada no arquivo config.env.")

    if not config_tokens:
        print("   ◎ Nenhum cliente adicional encontrado.")
        return

    tasks = [start_client(cid, tok) for cid, tok in config_tokens.items()]
    results = await asyncio.gather(*tasks)
    
    for res in results:
        if res:
            cid, client = res
            multi_clients[cid] = client
            if cid == 99:
                logger.info("   💎 [MASTER] Conta de Usuário (Session) vinculada como Cliente 99!")

    if len(multi_clients) > 1:
        Var.MULTI_CLIENT = True
        print("╠══════════════════════ MULTI-CLIENT ═══════════════════════╣")
        print(f"   ◎ Total Clients: {len(multi_clients)} (Including primary client)")
    else:
        print("╠═══════════════════════════════════════════════════════════╣")
        print("   ▶ No additional clients available at the moment.")

    # Task de background permanente para manutenção dos clientes
    async def maintenance_loop():
        while True:
            try:
                await asyncio.sleep(60) # Verifica a cada 1 minuto
                
                # 1. Tenta reconectar bots que falharam na inicialização ou caíram
                for cid, token in config_tokens.items():
                    if cid not in multi_clients or not multi_clients[cid].is_connected:
                        logger.info(f"🔄 Tentando (re)conectar Cliente {cid}...")
                        res = await start_client(cid, token)
                        if res:
                            multi_clients[res[0]] = res[1]
                            logger.info(f"✅ Cliente {cid} está online agora!")
                
                # 2. Health Check: Verifica se os bots ativos respondem
                for cid, client in list(multi_clients.items()):
                    if client.is_connected:
                        try:
                            await asyncio.wait_for(client.get_me(), timeout=5.0)
                        except Exception as e:
                            logger.warning(f"⚠️ Cliente {cid} não respondeu: {e}. Reiniciando...")
                            try:
                                await client.stop()
                            except:
                                pass
                            if cid in multi_clients:
                                del multi_clients[cid]
            except Exception as e:
                logger.error(f"❌ Erro no loop de manutenção de clientes: {e}", exc_info=True)

    asyncio.create_task(maintenance_loop(), name="client_maintenance_task")
