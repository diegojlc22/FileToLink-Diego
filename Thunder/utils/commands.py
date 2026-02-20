from pyrogram.types import BotCommand

from Thunder.bot import StreamBot
from Thunder.utils.logger import logger
from Thunder.vars import Var

def get_commands():
    command_descriptions = {
        "start": "Inicia o bot",
        "link": "Gera link de arquivo (Grupos)",
        "serie": "Ativa o Modo Série (Organização)",
        "done": "Finaliza o Modo Série e gera a lista",
        "status": "(Admin) Ver carga dos bots",
        "stats": "(Admin) Ver estatísticas de uso",
        "log": "(Admin) Enviar logs do bot",
        "restart": "(Admin) Reiniciar o bot",
        "speedtest": "(Admin) Teste de velocidade",
        "users": "(Admin) Total de usuários"
    }
    return [BotCommand(name, desc) for name, desc in command_descriptions.items()]

async def set_commands():
    if Var.SET_COMMANDS:
        try:
            commands = get_commands()
            if commands:
                await StreamBot.set_bot_commands(commands)
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}", exc_info=True)
