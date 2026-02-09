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

            # Pequeno teste/aquecimento: força o bot a conhecer o canal após ligar
            try:
                chat = await client.get_chat(Var.BIN_CHANNEL)
                logger.info(f"   ✓ Cliente {client_id} conectado ao canal: {chat.title}")
            except Exception as e:
                logger.error(f"   ✖ Cliente {client_id} NÃO TEM ACESSO ao canal {Var.BIN_CHANNEL}! Erro: {e}")
                # Se for o bot principal, isso é fatal. Se for secundário, apenas ignoramos ele.
                if client_id == 0:
                    raise e
                return None
            
            work_loads[client_id] = 0
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

    # Task de background permanente para manutenção dos clientes
    all_tokens_dict = all_tokens
    
    async def maintenance_loop():
        while True:
            try:
                await asyncio.sleep(60) # Verifica a cada 1 minuto
                
                # 1. Tenta reconectar bots que falharam na inicialização ou caíram
                for cid, token in all_tokens_dict.items():
                    if cid not in multi_clients or not multi_clients[cid].is_connected:
                        logger.info(f"🔄 Tentando (re)conectar Cliente {cid}...")
                        res = await start_client(cid, token)
                        if res:
                            multi_clients[res[0]] = res[1]
                            logger.info(f"✅ Cliente {cid} está online agora!")
                
                # 2. Health Check: Verifica se os bots ativos respondem (evita o "hang")
                for cid, client in list(multi_clients.items()):
                    if client.is_connected:
                        try:
                            # Tenta um comando simples com timeout curto
                            await asyncio.wait_for(client.get_me(), timeout=5.0)
                        except (asyncio.TimeoutError, Exception) as e:
                            logger.warning(f"⚠️ Cliente {cid} não respondeu ao health check: {e}. Reiniciando...")
                            try:
                                await client.stop()
                            except:
                                pass
                            # O loop de reconexão acima cuidará de ligá-lo na próxima volta
                            if cid in multi_clients:
                                del multi_clients[cid]
            except Exception as e:
                logger.error(f"❌ Erro no loop de manutenção de clientes: {e}", exc_info=True)

    asyncio.create_task(maintenance_loop(), name="client_maintenance_task")
