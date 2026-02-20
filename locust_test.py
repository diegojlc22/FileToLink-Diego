
from locust import HttpUser, task, between
import random

# CONFIGURAÇÃO DO TESTE
# Usando o link fornecido de Interestelar (2014)
SAMPLE_MESSAGE_ID = "188" 
SAMPLE_HASH = "AgADZQ" 

class TelegramStreamUser(HttpUser):
    wait_time = between(1, 3) # Simula usuários clicando com intervalo
    
    @task(1)
    def test_streaming(self):
        # Gera um range aleatório para simular o player "pulando" partes do vídeo
        start_byte = random.randint(0, 1000000)
        end_byte = start_byte + (1024 * 1024) # Pede 1MB
        
        headers = {
            "Range": f"bytes={start_byte}-{end_byte}",
            "User-Agent": "Locust/PerformanceTest"
        }
        
        # Tenta baixar um pedaço do arquivo
        url = f"/{SAMPLE_HASH}{SAMPLE_MESSAGE_ID}"
        
        with self.client.get(url, headers=headers, catch_response=True, stream=True) as response:
            if response.status_code == 206:
                response.success()
            elif response.status_code == 404:
                response.failure("Arquivo não encontrado (Propagação?)")
            else:
                response.failure(f"Erro: {response.status_code}")

    @task(5)
    def test_metadata_only(self):
        # Simula o player apenas carregando as informações do vídeo (HEAD request)
        url = f"/{SAMPLE_HASH}{SAMPLE_MESSAGE_ID}"
        with self.client.head(url, catch_response=True) as response:
            if response.status_code in [200, 206]:
                response.success()
            else:
                response.failure(f"Erro Metadados: {response.status_code}")
