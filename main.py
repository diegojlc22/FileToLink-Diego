import asyncio
import sys
import os

# Adiciona o diretório atual ao sys.path para permitir importações do pacote Thunder
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from Thunder.__main__ import start_services

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        print("\nBot parado pelo usuário.")
    except Exception as e:
        print(f"Ocorreu um erro inesperado: {e}")
    finally:
        if not loop.is_closed():
            loop.close()
