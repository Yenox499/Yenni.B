"""
Test complet : 10 fiches LDLC variées — scraping + IA + prix.
Produit un rapport détaillé de chaque composant pour détecter les bugs.
"""
import asyncio, sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from scraper.ldlc_scraper import scrape_ldlc_product
from ai.component_analyzer import enrich_components
from search.partie2_recherche_prix import lancer_partie2

URLS = [
    ("https://www.ldlc.com/fiche/PB00706786.html", "ASUS ROG STRIX G700TF (Core Ultra 7 / RTX 5080)"),
    ("https://www.ldlc.com/fiche/PB00664315.html", "PC11P Zi Artist 9 Studio (Core Ultra 9 / RTX 5090 / AIO 360)"),
    ("https://www.ldlc.com/fiche/PB00475427.html", "PC11 Plus Perfect (i7-12700KF / RTX 3060 Ti / AIO 240)"),
    ("https://www.ldlc.com/fiche/PB00671360.html", "PC11 ART Seventy (Ryzen 5 / RTX 5070)"),
    ("https://www.ldlc.com/fiche/PB00668591.html", "Zen-M5 X3D Seven-Ti (Ryzen 7 / RTX 5070 Ti / DDR5)"),
    ("https://www.ldlc.com/fiche/PB00733836.html", "PC11 Perfect Gen16 (Core Ultra 5 / RTX 5060 / B860)"),
    ("https://www.ldlc.com/fiche/PB00729248.html", "PC11i AQUA (Ryzen 5 / RTX 5060)"),
    ("https://www.ldlc.com/fiche/PB00677437.html", "Zen-M5 X3D SIX-TI (Ryzen 7 / RTX 5060 Ti / DDR5)"),
    ("https://www.ldlc.com/fiche/PB00675804.html", "Zen X3D Top (Ryzen 9 / RTX 5080 / double SSD)"),
    ("https://www.ldlc.com/fiche/PB00677382.html", "PC ART SIX-TI (Ryzen 5 / RTX 5060 Ti)"),
]

COMP_KEYS = ["cpu","gpu","ram","ssd","ssd2","motherboard","case","cooler","psu"]

async def scrape_batch(urls, batch_size=3):
    results = []
    for i in range(0, len(urls), batch_size):
        batch = urls[i:i+batch_size]
        tasks = [scrape_ldlc_product(url) for url, _ in batch]
        batch_res = await asyncio.gather(*tasks, return_exceptions=True)
        for (url, label), res in zip(batch, batch_res):
            if isinstance(res, Exception):
                results.append({"url": url, "label": label, "error": str(res)})
            else:
                results.append({"url": url, "label": label, **res})
        print(f"  Batch scraping {i+batch_size}/{len(urls)} done")
    return results

def enrich_and_price(scraped_list):
    results = []
    for s in scraped_list:
        if "error" in s:
            results.append(s); continue
        try:
            enriched = enrich_components(s)
            final    = lancer_partie2(enriched)
            results.append({**final, "url": s["url"], "label": s["label"]})
        except Exception as e:
            results.append({"url": s["url"], "label": s["label"], "pipeline_error": str(e)})
    return results

async def main():
    print("=" * 65)
    print("ÉTAPE 1 — Scraping des 10 fiches")
    print("=" * 65)
    scraped = await scrape_batch(URLS)

    print("\n" + "=" * 65)
    print("SCRAPING REPORT")
    print("=" * 65)
    issues = []
    for s in scraped:
        label = s.get("label", s["url"])
        print(f"\n[{label}]")
        print(f"  Prix    : {s.get('product_price')} €")
        comps = s.get("components", {})
        for k in COMP_KEYS:
            v = comps.get(k)
            tag = ""
            if v is None:
                tag = " [MANQUANT]"
            elif any(bad in str(v) for bad in ["S SD", "AlimentationFox", "WatercoolingFox"]):
                tag = f" [BUG CONCAT]"
                issues.append(f"Concat bug sur {k} pour {label}: {v}")
            print(f"  {k:12}: {v or 'null'}{tag}")

    if issues:
        print("\n⚠️  BUGS SCRAPING DÉTECTÉS:")
        for i in issues: print(f"  {i}")

    print("\n" + "=" * 65)
    print("ÉTAPE 2 — Enrichissement IA + recherche prix (10 PCs)")
    print("=" * 65)
    final_results = enrich_and_price(scraped)

    print("\n" + "=" * 65)
    print("PIPELINE REPORT FINAL")
    print("=" * 65)
    pipeline_issues = []
    for r in final_results:
        label = r.get("label", r.get("url", "?"))
        print(f"\n[{label}]")
        if "pipeline_error" in r:
            print(f"  ❌ ERREUR PIPELINE: {r['pipeline_error']}")
            pipeline_issues.append(f"Pipeline crash: {label}: {r['pipeline_error']}")
            continue
        print(f"  Prix LDLC      : {r.get('product_price')} €")
        v = r.get("verdict", {})
        diff = v.get("difference_euros", 0) or 0
        print(f"  Verdict        : {v.get('verdict_label','?')} ({diff:+.2f} €)")
        comps = r.get("detail_composants", {})
        no_price = [k for k, d in comps.items() if not d.get("prix_retenu")]
        suspicious = []
        for k, d in comps.items():
            p = d.get("prix_retenu") or 0
            name = d.get("nom","")
            # Prix suspects
            if k == "psu" and 0 < p < 20:
                suspicious.append(f"PSU trop bas ({p}€): {name}")
            if k == "ram" and 0 < p < 15:
                suspicious.append(f"RAM trop bas ({p}€): {name}")
            if k == "cpu" and 0 < p < 30:
                suspicious.append(f"CPU trop bas ({p}€): {name}")
            if k == "cooler" and 0 < p < 10:
                suspicious.append(f"Cooler trop bas ({p}€): {name}")
            if k == "gpu" and 0 < p < 50:
                suspicious.append(f"GPU trop bas ({p}€): {name}")
        print(f"  Sans prix      : {no_price or 'aucun'}")
        if suspicious:
            print(f"  ⚠️  Prix suspects : {suspicious}")
            pipeline_issues.extend(suspicious)
        for k, d in comps.items():
            p = d.get("prix_retenu")
            nom = d.get("nom", "?")[:50]
            statut = d.get("statut","?")
            print(f"  {k:12} [{statut:8}] {p or '—':>8} € — {nom}")

    with open("test_10_random_results.json", "w", encoding="utf-8") as f:
        json.dump(final_results, f, indent=2, ensure_ascii=False)

    print("\n\n" + "=" * 65)
    print("RÉSUMÉ DES PROBLÈMES")
    print("=" * 65)
    all_issues = issues + pipeline_issues
    if all_issues:
        for i, iss in enumerate(all_issues, 1):
            print(f"  {i}. {iss}")
    else:
        print("  Aucun problème détecté ✅")

asyncio.run(main())
