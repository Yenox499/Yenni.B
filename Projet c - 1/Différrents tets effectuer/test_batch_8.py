"""
Batch test sur les 8 PCs cibles — pipeline complet :
scraping → enrichissement IA → recherche de prix.
"""
import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.ldlc_scraper import scrape_ldlc_product
from ai.component_analyzer import enrich_components
from search.partie2_recherche_prix import lancer_partie2

TEST_URLS = [
    "https://www.ldlc.com/fiche/PB00684984.html",
    "https://www.ldlc.com/fiche/PB00668591.html",
    "https://www.ldlc.com/fiche/PB00684983.html",
    "https://www.ldlc.com/fiche/PB00671200.html",
    "https://www.ldlc.com/fiche/PB00677382.html",
    "https://www.ldlc.com/fiche/PB00713377.html",
    "https://www.ldlc.com/fiche/PB00668558.html",
    "https://www.ldlc.com/fiche/PB00607532.html",
]

STATUS_ICONS = {
    "found":     "✅",
    "refined":   "🔧",
    "estimated": "🤔",
    "generic":   "⚠️ ",
}


async def run_one(url: str) -> dict:
    pid = url.split("/")[-1].replace(".html", "")
    sep = "=" * 65
    print(f"\n{sep}")
    print(f"  PC : {pid}  ({url})")
    print(sep)

    # 1. Scraping
    scraped = await scrape_ldlc_product(url)
    if "error" in scraped:
        print(f"  ❌ ERREUR SCRAPING: {scraped['error']}")
        return {"url": url, "pid": pid, "error": scraped["error"]}

    print(f"  Nom   : {scraped['product_name']}")
    print(f"  Prix  : {scraped['product_price']} €")
    print("  Composants bruts :")
    for k, v in scraped["components"].items():
        if v:
            print(f"    [{k}] {v}")

    # 2. Enrichissement IA
    enriched = enrich_components(scraped)
    socket = enriched.get("platform_socket") or "?"
    print(f"\n  Socket détecté : {socket}")
    print("  Composants enrichis :")
    for k, data in enriched["components"].items():
        icon = STATUS_ICONS.get(data.get("status", ""), "❓")
        name = data.get("name", "?")
        sq   = data.get("search_query", "")
        print(f"    {icon} [{data.get('status','?'):9s}] {k:12s}: {name}")
        if sq != f"{name} prix":
            print(f"              └─ search: {sq}")

    # 3. Recherche de prix
    result = lancer_partie2(enriched)

    print("\n  Prix par composant :")
    for k, v in result.get("detail_composants", {}).items():
        prix = v.get("prix_retenu")
        src  = v.get("source_retenue", "")
        name = v.get("name", k)
        if prix:
            print(f"    ✓ {k:12s}: {prix:.2f}€  ({src})")
        else:
            print(f"    ✗ {k:12s}: NON TROUVÉ  ({name})")

    verdict = result.get("verdict", {})
    label   = verdict.get("verdict_label", "?")
    diff    = verdict.get("difference_euros")
    diff_str = f"{diff:+.2f}€" if diff is not None else "N/A"
    print(f"\n  ▶  Verdict : {label}  ({diff_str})")

    return {
        "url": url,
        "pid": pid,
        "product_name":  enriched["product_name"],
        "product_price": enriched["product_price"],
        "platform_socket": socket,
        "verdict_label": label,
        "difference_euros": diff,
        "detail": result.get("detail_composants", {}),
    }


async def main():
    results = []
    for url in TEST_URLS:
        r = await run_one(url)
        results.append(r)

    # Sauvegarder
    out_path = os.path.join(os.path.dirname(__file__), "batch_8_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n\nRésultats sauvegardés → {out_path}")

    # Tableau de synthèse
    print("\n" + "=" * 75)
    print(f"{'PC':<15} {'Nom':<38} {'Socket':<8} {'Prix LDLC':>10} {'Diff':>10}")
    print("=" * 75)
    for r in results:
        if "error" in r:
            print(f"  {r['pid']:<13} {'ERREUR SCRAPING':<38}")
            continue
        name   = (r.get("product_name") or "?")[:38]
        sock   = (r.get("platform_socket") or "?")
        price  = r.get("product_price")
        diff   = r.get("difference_euros")
        label  = r.get("verdict_label", "?")
        price_s = f"{price:.2f}€" if price is not None else "N/A"
        diff_s  = f"{diff:+.2f}€" if diff is not None else "N/A"
        print(f"  {r['pid']:<13} {name:<38} {sock:<8} {price_s:>10} {diff_s:>10}  {label}")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
