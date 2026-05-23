"""
Script de test : scrape 10 fiches LDLC en parallèle et sauvegarde les résultats.
"""
import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from scraper.ldlc_scraper import scrape_ldlc_product

URLS = [
    "https://www.ldlc.com/fiche/PB00691188.html",   # PC11i ART — Ryzen 5 5500 + RTX 5060
    "https://www.ldlc.com/fiche/PB00684984.html",   # PC11 ART — Ryzen 5 + RTX 5060
    "https://www.ldlc.com/fiche/PB00677389.html",   # PC11 ART SIX-TI — RTX 5060 Ti 16Go
    "https://www.ldlc.com/fiche/PB00671360.html",   # PC11 ART Seventy — RTX 5070
    "https://www.ldlc.com/fiche/PB00668591.html",   # Zen-M5 X3D Plus Perfect Seven-Ti
    "https://www.ldlc.com/fiche/PB00677437.html",   # Zen-M5 X3D Plus Perfect SIX-TI
    "https://www.ldlc.com/fiche/PB00733836.html",   # PC11 Perfect Gen16
    "https://www.ldlc.com/fiche/PB00729248.html",   # PC11i AQUA
    "https://www.ldlc.com/fiche/PB00675804.html",   # Zen-M5 X3D Top Perfect
    "https://www.ldlc.com/fiche/PB00677382.html",   # PC ART SIX-TI
]

async def scrape_all():
    results = []
    # Scraper 3 par 3 pour ne pas surcharger
    for i in range(0, len(URLS), 3):
        batch = URLS[i:i+3]
        tasks = [scrape_ldlc_product(url) for url in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        for url, result in zip(batch, batch_results):
            if isinstance(result, Exception):
                results.append({"url": url, "error": str(result)})
            else:
                results.append({"url": url, **result})
        print(f"Batch {i//3 + 1} terminé ({min(i+3, len(URLS))}/{len(URLS)})")
    return results

if __name__ == "__main__":
    results = asyncio.run(scrape_all())
    with open("test_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("\n=== RÉSUMÉ ===")
    for r in results:
        name = r.get("product_name", "ERREUR")[:50]
        price = r.get("product_price")
        comps = r.get("components", {})
        missing = [k for k, v in comps.items() if not v]
        found = [k for k, v in comps.items() if v]
        print(f"\n{name}")
        print(f"  Prix   : {price} €")
        print(f"  Trouvés: {found}")
        print(f"  Absents: {missing}")
