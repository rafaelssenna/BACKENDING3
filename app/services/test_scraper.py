#!/usr/bin/env python3
"""
Script de diagnóstico para testar o scraper localmente.

Uso:
    python test_scraper.py
"""
import asyncio
from app.services.scraper import search_numbers
from app.utils.logs import setup_logger

log = setup_logger("test_scraper")


async def main():
    """Testa o scraper com um nicho e local específicos."""
    print("=" * 60)
    print("🔍 TESTE DE DIAGNÓSTICO DO SCRAPER")
    print("=" * 60)
    
    # Configurações de teste
    nicho = "padarias"
    locais = ["Belo Horizonte, MG"]
    target = 5  # Buscar apenas 5 leads para teste rápido
    
    print(f"\n📋 Configurações:")
    print(f"  - Nicho: {nicho}")
    print(f"  - Locais: {locais}")
    print(f"  - Meta: {target} leads")
    print("\n⏳ Iniciando busca...\n")
    
    count = 0
    try:
        async for lead in search_numbers(nicho, locais, target, max_pages=3):
            count += 1
            phone = lead.get("phone", "N/A")
            name = lead.get("name", "(sem nome)")
            print(f"✅ Lead {count}: {name} — {phone}")
            
        print(f"\n✅ Teste concluído! Total de leads encontrados: {count}")
        
        if count == 0:
            print("\n⚠️  PROBLEMA: Nenhum lead foi encontrado!")
            print("   Possíveis causas:")
            print("   1. Google bloqueou com CAPTCHA")
            print("   2. Seletores CSS desatualizados")
            print("   3. Problema de rede/timeout")
            print("   4. Chromium não instalado corretamente")
            print("\n   💡 Verifique os logs acima para mais detalhes.")
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Teste interrompido pelo usuário")
    except Exception as e:
        print(f"\n❌ ERRO: {e}")
        import traceback
        traceback.print_exc()
        

if __name__ == "__main__":
    asyncio.run(main())
