import os
import statistics
from serpapi import GoogleSearch

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")


def search_component_price(search_query: str, num_results: int = 5) -> dict:
    """
    Recherche le prix d'un composant via Google Shopping (SerpAPI).
    Retourne le prix le plus bas trouvé et le prix moyen.
    """
    params = {
        "engine": "google_shopping",
        "q": search_query,
        "hl": "fr",
        "gl": "fr",
        "api_key": SERPAPI_KEY,
        "num": num_results,
    }

    search = GoogleSearch(params)
    results = search.get_dict()

    shopping_results = results.get("shopping_results", [])

    prices = []
    items = []

    for item in shopping_results[:num_results]:
        raw_price = item.get("price", "")
        price = _parse_price(raw_price)
        if price and price > 0:
            prices.append(price)
            items.append({
                "title": item.get("title", ""),
                "price": price,
                "source": item.get("source", ""),
                "link": item.get("link", ""),
            })

    if not prices:
        return {
            "query": search_query,
            "lowest_price": None,
            "average_price": None,
            "items": [],
            "error": "Aucun prix trouvé",
        }

    return {
        "query": search_query,
        "lowest_price": min(prices),
        "average_price": round(statistics.mean(prices), 2),
        "items": items,
        "error": None,
    }


def _parse_price(raw: str) -> float | None:
    """Convertit une chaîne de prix en float (ex: '149,99 €' → 149.99)."""
    if not raw:
        return None
    cleaned = (
        raw.replace("\xa0", "")
           .replace(" ", "")
           .replace("€", "")
           .replace(",", ".")
    )
    # Garder seulement chiffres et point
    import re
    match = re.search(r"\d+\.\d{2}", cleaned)
    if match:
        return float(match.group())
    match = re.search(r"\d+", cleaned)
    if match:
        return float(match.group())
    return None


def search_all_components(enriched: dict) -> dict:
    """
    Lance la recherche de prix pour chaque composant du dict enrichi.
    - Composants "found" / "refined" : prix le plus bas
    - Composants "estimated" : prix moyen
    Retourne le dict enrichi avec les prix ajoutés.
    """
    components = enriched.get("components", {})

    for key, data in components.items():
        query = data.get("search_query", "")
        if not query:
            continue

        print(f"  Recherche prix : {query}")
        price_data = search_component_price(query)

        if data.get("estimated"):
            # Composant estimé : on prend le prix moyen
            data["price"] = price_data.get("average_price")
        else:
            # Composant trouvé : on prend le prix le plus bas
            data["price"] = price_data.get("lowest_price")

        data["price_details"] = price_data

    enriched["components"] = components
    return enriched
