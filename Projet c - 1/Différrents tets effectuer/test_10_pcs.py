"""
Test automatique du pipeline complet sur 10 URLs LDLC.
Affiche les résultats pour chaque PC et signale les anomalies.
"""
import sys, os, asyncio, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.ldlc_scraper import scrape_ldlc_product
from ai.component_analyzer import enrich_components
from search.partie2_recherche_prix import lancer_partie2

URLS = [
    "https://www.ldlc.com/fiche/PB00684984.html",
    "https://www.ldlc.com/fiche/PB00668591.html",
    "https://www.ldlc.com/fiche/PB00684983.html",
    "https://www.ldlc.com/fiche/PB00671200.html",
    "https://www.ldlc.com/fiche/PB00677382.html",
    "https://www.ldlc.com/fiche/PB00713377.html",
    "https://www.ldlc.com/fiche/PB00668558.html",
    "https://www.ldlc.com/fiche/PB00607532.html",
]

async def test_one(url: str, idx: int):
    print(f"\n{'='*65}")
    print(f"  PC {idx+1}/8 — {url.split('/')[-1]}")
    print(f"{'='*65}")
    try:
        scraped = await scrape_ldlc_product(url)
        if "error" in scraped:
            print(f"  ❌ SCRAPING ERREUR : {scraped['error']}")
            return None

        print(f"  Nom     : {scraped.get('product_name','?')}")
        print(f"  Prix    : {scraped.get('product_price','?')} €")
        print(f"  Compos. scrappés :")
        for k, v in scraped.get("components", {}).items():
            print(f"    {k:12} : {v}")

        enriched = enrich_components(scraped)
        print(f"\n  Compos. enrichis (IA) :")
        for k, v in enriched.get("components", {}).items():
            if isinstance(v, dict):
                print(f"    {k:12} : {v.get('name','?')} [{v.get('status','?')}]")

        result = lancer_partie2(enriched)

        print(f"\n  ── RÉSULTAT FINAL ──")
        print(f"  Prix LDLC      : {result.get('product_price','?')} €")
        total = sum(
            v.get("prix_retenu") or 0
            for v in result.get("detail_composants", {}).values()
        )
        print(f"  Total pièces   : {round(total,2)} €")
        diff = result.get("verdict", {}).get("difference_euros", 0)
        print(f"  Différence     : {diff:+.2f} €")
        print(f"  Verdict        : {result.get('verdict',{}).get('verdict_label','?')}")
        print(f"\n  Détail composants :")
        for k, v in result.get("detail_composants", {}).items():
            nom = v.get("nom") or "—"
            prix = v.get("prix_retenu")
            site = v.get("site") or "—"
            statut = v.get("statut") or "—"
            flag = "⚠️ " if not prix else "   "
            print(f"  {flag}{k:12} : {nom[:40]:40} {str(prix)+' €':10} [{statut}] {site}")

        return result

    except Exception as e:
        import traceback
        print(f"  ❌ EXCEPTION : {e}")
        traceback.print_exc()
        return None

async def main():
    results = []
    for i, url in enumerate(URLS):
        r = await test_one(url, i)
        results.append({"url": url, "result": r})

    print(f"\n\n{'='*65}")
    print("  RÉCAPITULATIF")
    print(f"{'='*65}")
    for i, item in enumerate(results):
        r = item["result"]
        if r is None:
            print(f"  PC {i+1}: ❌ ÉCHEC")
        else:
            prix_pc = r.get("product_price", 0)
            total = sum(v.get("prix_retenu") or 0 for v in r.get("detail_composants", {}).values())
            composants_sans_prix = [
                k for k, v in r.get("detail_composants", {}).items()
                if not v.get("prix_retenu")
            ]
            verdict = r.get("verdict", {}).get("verdict_label", "?")
            diff = r.get("verdict", {}).get("difference_euros", 0)
            ok = "✅" if not composants_sans_prix else "⚠️ "
            print(f"  PC {i+1}: {ok} {r.get('product_name','?')[:40]}")
            print(f"         LDLC={prix_pc}€ | Pièces={round(total,2)}€ | Diff={diff:+.0f}€ | {verdict}")
            if composants_sans_prix:
                print(f"         Sans prix : {', '.join(composants_sans_prix)}")

if __name__ == "__main__":
    asyncio.run(main())
