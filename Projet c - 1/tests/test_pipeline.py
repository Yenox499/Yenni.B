"""Test pipeline complet sur 3 PCs représentatifs."""
import sys, os, json, asyncio
sys.path.insert(0, os.path.dirname(__file__))
from scraper.ldlc_scraper import scrape_ldlc_product
from ai.component_analyzer import enrich_components
from search.partie2_recherche_prix import lancer_partie2

TEST_URLS = [
    "https://www.ldlc.com/fiche/PB00677389.html",   # ART SIX-TI — CPU générique, carte mère manquante
    "https://www.ldlc.com/fiche/PB00733836.html",   # Perfect Gen16 — Intel Core Ultra
    "https://www.ldlc.com/fiche/PB00675804.html",   # Zen X3D Top — double SSD, RTX 5080
]

async def run_test(url):
    print(f"\n{'='*60}")
    print(f"TEST: {url.split('/')[-1]}")
    scraped = await scrape_ldlc_product(url)
    if "error" in scraped:
        print(f"ERREUR SCRAPING: {scraped['error']}")
        return {"url": url, "error": scraped["error"]}
    enriched = enrich_components(scraped)
    result = lancer_partie2(enriched)
    return {"url": url, **result}

async def main():
    results = []
    for url in TEST_URLS:
        r = await run_test(url)
        results.append(r)
    with open("test_pipeline_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("\n\n=== SYNTHÈSE FINALE ===")
    for r in results:
        print(f"\n{r.get('product_name','?')}")
        print(f"  Prix LDLC     : {r.get('product_price')} €")
        v = r.get('verdict', {})
        print(f"  Verdict       : {v.get('verdict_label')} ({v.get('difference_euros')} €)")
        comps = r.get('detail_composants', {})
        print(f"  Composants    : {len(comps)} | sans prix: {[k for k,v in comps.items() if not v.get('prix_retenu')]}")

asyncio.run(main())
