"""Test pipeline complet sur 5 URLs LDLC ciblées."""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.ldlc_scraper import scrape_ldlc_product
from ai.component_analyzer import enrich_components
from search.partie2_recherche_prix import lancer_partie2

URLS = [
    "https://www.ldlc.com/fiche/PB00671200.html",
    "https://www.ldlc.com/fiche/PB00677382.html",
    "https://www.ldlc.com/fiche/PB00713377.html",
    "https://www.ldlc.com/fiche/PB00668558.html",
    "https://www.ldlc.com/fiche/PB00607532.html",
]

async def test_one(url, idx):
    print(f"\n{'='*65}")
    print(f"  PC {idx+1}/5 — {url.split('/')[-1]}")
    print(f"{'='*65}")
    try:
        scraped = await scrape_ldlc_product(url)
        if "error" in scraped:
            print(f"  ❌ SCRAPING ERREUR : {scraped['error']}")
            return None
        enriched = enrich_components(scraped)
        result   = lancer_partie2(enriched)

        print(f"\n  ── RÉSULTAT ──")
        print(f"  {result.get('product_name','?')}")
        print(f"  Prix LDLC  : {result.get('product_price','?')} €")
        total = sum(v.get('prix_retenu') or 0 for v in result.get('detail_composants',{}).values())
        print(f"  Total pièces: {round(total,2)} €")
        diff = result.get('verdict',{}).get('difference_euros', 0)
        print(f"  Différence  : {diff:+.2f} €  →  {result.get('verdict',{}).get('verdict_label','?')}")
        print(f"\n  Composants :")
        for k, v in result.get('detail_composants',{}).items():
            prix  = v.get('prix_retenu')
            site  = v.get('site') or '—'
            nom   = (v.get('nom') or '—')[:42]
            flag  = "❌ " if not prix else "   "
            print(f"  {flag}{k:12} {nom:44} {str(prix)+'€':9} {site}")
        return result
    except Exception as e:
        import traceback; traceback.print_exc()
        return None

async def main():
    results = []
    for i, url in enumerate(URLS):
        r = await test_one(url, i)
        results.append(r)

    print(f"\n\n{'='*65}")
    print("  RÉCAPITULATIF FINAL")
    print(f"{'='*65}")
    for i, r in enumerate(results):
        if r is None:
            print(f"  PC {i+1}: ❌ ÉCHEC")
            continue
        sans_prix = [k for k,v in r.get('detail_composants',{}).items() if not v.get('prix_retenu')]
        diff = r.get('verdict',{}).get('difference_euros',0)
        verdict = r.get('verdict',{}).get('verdict_label','?')
        ok = "✅" if not sans_prix else f"⚠️  (sans prix: {', '.join(sans_prix)})"
        print(f"  PC {i+1}: {ok}")
        print(f"         {r.get('product_name','?')[:50]}")
        print(f"         LDLC={r.get('product_price','?')}€ | Pièces={round(sum(v.get('prix_retenu') or 0 for v in r.get('detail_composants',{}).values()),0):.0f}€ | Diff={diff:+.0f}€ | {verdict}")

if __name__ == "__main__":
    asyncio.run(main())
