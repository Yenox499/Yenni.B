"""
Test du module component_analyzer sans clé API.
Simule la réponse de Claude pour valider la logique d'enrichissement.
"""
import json
from ai.component_analyzer import enrich_components

# Réponse simulée de Claude (ce que l'API retournerait réellement)
MOCK_AI_RESPONSE = {
    "pc_analysis": {
        "usage": "gaming",
        "tier": "milieu de gamme",
        "notes": "PC gaming 1080p avec RTX 5060, cohérent avec un budget ~1000€. Config AMD AM4."
    },
    "estimated_components": {
        "motherboard": {
            "name": "MSI B550M PRO-VDH WiFi",
            "search_query": "MSI B550M PRO-VDH WiFi prix",
            "reason": "Carte mère AM4 milieu de gamme compatible Ryzen 5, cohérente avec chipset A520/B550",
            "estimated": True
        },
        "cooler": {
            "name": "be quiet! Pure Rock 2",
            "search_query": "be quiet Pure Rock 2 prix",
            "reason": "Ventirad 120mm adapté à un Ryzen 5 65W, bon rapport qualité/prix pour cette gamme",
            "estimated": True
        }
    },
    "refined_components": {
        "cpu": {
            "name": "AMD Ryzen 5 5600X",
            "search_query": "AMD Ryzen 5 5600X prix",
            "reason": "Le Ryzen 5 AM4 à 4.2 GHz correspond au modèle 5600X (boost 4.6 GHz max)",
            "estimated": False
        },
        "case": {
            "name": "Fractal Design Pop Air",
            "search_query": "Fractal Design Pop Air prix",
            "reason": "Boîtier Moyen Tour gaming typique pour cette gamme de prix",
            "estimated": False
        }
    }
}


def mock_enrich_components(scraped: dict) -> dict:
    """Version mock de enrich_components qui utilise une réponse simulée."""
    product_name = scraped.get("product_name", "")
    product_price = scraped.get("product_price", 0)
    components = scraped.get("components", {})

    ai_result = MOCK_AI_RESPONSE
    enriched_components = {}

    # 1. Composants trouvés par le scraper
    for key, value in components.items():
        if value:
            enriched_components[key] = {
                "name": value,
                "search_query": f"{value} prix",
                "status": "found",
                "estimated": False,
            }

    # 2. Versions affinées
    for key, data in ai_result.get("refined_components", {}).items():
        if key in enriched_components:
            enriched_components[key] = {
                "name": data["name"],
                "search_query": data.get("search_query", f"{data['name']} prix"),
                "status": "refined",
                "estimated": False,
                "reason": data.get("reason", ""),
            }

    # 3. Composants estimés
    for key, data in ai_result.get("estimated_components", {}).items():
        enriched_components[key] = {
            "name": data["name"],
            "search_query": data.get("search_query", f"{data['name']} prix"),
            "status": "estimated",
            "estimated": True,
            "reason": data.get("reason", ""),
        }

    return {
        "product_name": product_name,
        "product_price": product_price,
        "pc_analysis": ai_result.get("pc_analysis", {}),
        "components": enriched_components,
    }


if __name__ == "__main__":
    test_data = {
        "product_name": "LDLC PC AQUA",
        "product_price": 979.99,
        "components": {
            "cpu": "AMD Ryzen 5 4.2 GHz",
            "gpu": "NVIDIA GeForce RTX 5060",
            "ram": "16 Go DDR4",
            "ssd": "SSD 1 To",
            "motherboard": None,
            "case": "Moyen Tour",
            "cooler": None,
            "psu": "500 W",
        },
    }

    result = mock_enrich_components(test_data)
    print(json.dumps(result, indent=2, ensure_ascii=False))
