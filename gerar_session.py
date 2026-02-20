
import asyncio
from pyrogram import Client
import sys

# Credenciais do seu config.env
API_ID = 25946794
API_HASH = "c13ab5fe029cb271522873732cfac4e6"

async def main():
    print("Iniciando gerador de sessão...")
    # Usamos o cliente de forma interativa
    app = Client("temp_session", api_id=API_ID, api_hash=API_HASH, in_memory=True)
    try:
        async with app:
            session_string = await app.export_session_string()
            print("\n" + "="*50)
            print("SUA STRING SESSION:")
            print(session_string)
            print("="*50)
    except Exception as e:
        print(f"\nErro durante a geração: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
