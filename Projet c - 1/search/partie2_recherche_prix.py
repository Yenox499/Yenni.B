"""
=============================================================
  PARTIE 2 — RECHERCHE DU PRIX LE PLUS BAS PAR COMPOSANT
=============================================================
Pour chaque composant extrait + enrichi par l'IA (Partie 1),
ce module recherche via Google Shopping (SerpAPI) :
  - Le prix le plus bas    → composants trouvés / affinés
  - Le prix moyen          → composants estimés par l'IA
Et retourne un résultat de comparaison final.
=============================================================
"""

import os
import re
import json
import statistics
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ---------------------------------------------------------------------------
# Chargement de la clé SerpAPI
# ---------------------------------------------------------------------------

def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())

_load_env()
SERPAPI_KEY      = os.getenv("SERPAPI_KEY", "")
SERPAPI_ENDPOINT = "https://serpapi.com/search"

COMPONENT_LABELS_FR = {
    "cpu":         "Processeur (CPU)",
    "gpu":         "Carte graphique (GPU)",
    "ram":         "Mémoire vive (RAM)",
    "ssd":         "Stockage SSD 1",
    "ssd2":        "Stockage SSD 2",
    "motherboard": "Carte mère",
    "case":        "Boîtier",
    "cooler":      "Refroidisseur",
    "psu":         "Alimentation (PSU)",
}


# ---------------------------------------------------------------------------
# Parsing des prix
# ---------------------------------------------------------------------------

def _parse_price(raw: str) -> float | None:
    """Convertit une chaîne prix en float. Supporte : '149,99 €', '$149.99', '149€99'."""
    if not raw:
        return None
    cleaned = (
        raw.replace("\xa0", "")
           .replace(" ", "")
           .replace("€", ".")
           .replace("$", "")
           .replace("£", "")
    )
    # Format "149.99" ou "149,99"
    match = re.search(r"(\d+)[,.](\d{2})(?!\d)", cleaned)
    if match:
        return float(f"{match.group(1)}.{match.group(2)}")
    # Format entier "149"
    match = re.search(r"\d+", cleaned)
    if match:
        return float(match.group())
    return None


# Requêtes trop génériques à intercepter avant même d'appeler SerpAPI
# Planchers et plafonds de prix par composant pour filtrer les offres aberrantes
# (marketplace occasion, mauvais produit, erreur SerpAPI, etc.)
PRICE_FLOORS = {
    "cpu":         45,
    "gpu":        200,   # GPU dédié récent neuf > 200€ (RTX 5060 ~320€, 5070 Ti ~950€)
    "ram":         12,
    "ssd":         18,
    "ssd2":        18,
    "motherboard": 55,   # Carte mère entrée de gamme ~60€ minimum
    "case":        30,
    "cooler":      35,   # Air cooler basique ~35 €, AIO ≥ 60 € — évite les accessoires
    "psu":         22,
}
PRICE_CEILINGS = {
    "ssd":   150,    # SSD NVMe 1To ~80-100€, raised to 150€ pour inclure modèles actuels
    "ssd2":  200,    # Deuxième SSD peut être plus grand (2-4 To)
    "cooler": 200,   # AIO 360mm haut de gamme (Corsair H150i, NZXT Kraken 360) ~180 €
    "case":   400,   # Plafond raisonnable pour un boîtier
    "psu":    220,   # System Power 10 max ~110 €, RM1000e max ~200 € — évite les séries premium
    "ram":    260,   # DDR5 16Go kit ~200-250€ en 2026, plafond à 260€ pour couvrir tous les cas
}

# Sources non fiables pour la comparaison de prix PC (marketplace occasion, import Chine…)
BLACKLISTED_SOURCES = [
    # Marketplaces chinoises / asiatiques
    "aliexpress", "alicdn", "alibaba.com", "wish.com", "banggood", "gearbest",
    "dhgate", "yoho", "joybuy", "hgspot",
    # Marchés occasion (prix non représentatifs du neuf)
    "leboncoin", "vinted", "ebay", "backmarket", "rakuten",
    # Sites étrangers hors zone euro (prix incomparables avec le marché FR)
    ".co.il", "topmarket", "microless.com", "computer store berlin",
    "computerstore", ".hr", ".il", ".hu", ".pl", ".cz", ".sk", ".ro", ".it", ".pt", ".de",
    "ubuy", "rightdeal", "electromaker", "bestdigit",
    # Distributeurs industriels / professionnels (prix hors marché grand public)
    "rs france", "rs components", "rs-online", "rsonline",
    # Sites presse/média (prix souvent non à jour ou référencés indirectement)
    "kulturegeek", "kulturgeek", "lesnumeriques", "01net", "frandroid", "clubic", "teclab",
    # Sites non spécialisés PC / prix en cache non fiables
    "instinctgaming.gg", "instinctgaming",   # gaming accessories, pas revendeur PC
    "quadrimedia.com",   # retourne toujours le même WD Green 82.9€ peu importe la requête
    "achatmoinscher",    # agrégateur, pas un vrai revendeur
    "pixmania",          # marketplace peu fiable
    "systemtreff",       # revendeur allemand, retourne des PCs entiers
    "pc-boost",          # revendeur étranger peu fiable
    "nozzler",           # revendeur inconnu, retourne Crucial P310 2230 (format laptop)
    "reichelt",          # distributeur allemand, retourne kits montage et accessoires comme produits
]

# Sites de confiance prioritaires pour la comparaison de prix PC en France
# (utilisé pour le scoring — les offres de ces sites sont préférées en cas d'égalité de prix)
TRUSTED_SOURCES = [
    "materiel.net", "ldlc", "amazon.fr", "cdiscount", "fnac.com", "darty",
    "boulanger", "topachat", "top achat", "alternate.fr", "grosbill",
    "pc21", "rueducommerce", "cybertek", "infomax", "oreol",
    "dropReference", "dropreference",
]

# ── Détection du type de refroidissement ────────────────────────────────────
# Mots-clés indiquant un watercooling AIO (refroidissement liquide tout-en-un)
_WATERCOOLING_KEYWORDS = [
    "aio", "watercooling", "water cooling", "water-cooling",
    "liquid cooling", "refroidissement liquide", "liquid freezer",
    "240mm", "280mm", "360mm", "420mm",   # tailles radiateur AIO
    "kraken", "capellix", "elite capellix",
    "lc240", "lc360", "lc280", "lc420",
    "pure loop", "lt240", "lt360", "lt280",
    "rl240", "rl360",
    "lightflow xt240", "lightflow xt360", "lightflow gx",
    "cooler master ml", "enermax liqmax", "gamerstorm castle",
    "corsair h100", "corsair h115", "corsair h150", "corsair h60",
    "nzxt kraken",
]

# Mots-clés indiquant un ventirad (refroidissement air)
_VENTIRAD_KEYWORDS = [
    "ventirad", "air cooler", "aircooler", "air-cooler",
    "nh-u", "nh-d", "nh-l", "noctua nh",
    "ak400", "ak620", "ak500", "ak490",
    "pure rock", "dark rock",
    "freezer 34", "freezer 36", "freezer a35", "freezer i35",
    "hyper 212", "hyper 622",
    "true spirit", "mugen", "shadow rock",
    "be quiet pure rock", "deepcool ak",
]

def _detect_cooler_type(search_query: str) -> str:
    """Retourne 'watercooling', 'ventirad', ou 'unknown' selon la requête."""
    q = search_query.lower()
    if any(w in q for w in _WATERCOOLING_KEYWORDS):
        return "watercooling"
    if any(w in q for w in _VENTIRAD_KEYWORDS):
        return "ventirad"
    return "unknown"


# Mots dans le titre d'un cooler indiquant un accessoire / module (pas le refroidisseur lui-même)
COOLER_ACCESSORY_BLACKLIST = [
    "module lcd", "module écran", "module screen", "écran lcd",
    "display module", "accessoire", "spare part", "pièce détachée",
    "remplacement pompe", "fan replacement", "ventilateur de remplacement",
]

# Mots dans le titre d'une offre indiquant une incompatibilité de socket
# Structure : {composant: {socket_cible: [mots_à_rejeter_dans_le_titre]}}
TITLE_INCOMPATIBILITY_FILTERS = {
    "cooler": {
        "AM4":     ["tr4", "sp3", "sp5", "lga1700", "lga1851", "lga1200", "lga4677", "lga3647", "threadripper", "dx-"],
        "AM5":     ["tr4", "sp3", "lga1700", "lga1851", "lga1200", "lga4677", "lga3647", "threadripper", "dx-"],
        "LGA1700": ["tr4", "sp3", "am4", "am5", "lga2066", "lga4677", "lga3647", "dx-"],
        "LGA1851": ["tr4", "sp3", "am4", "am5", "lga2066", "lga4677", "lga3647", "dx-"],
    }
}

QUERIES_TROP_GENERIQUES = [
    "moyen tour prix", "mid tower prix", "tour atx prix",
    "500 w prix", "500w prix", "600 w prix", "600w prix",
    "650 w prix", "650w prix", "700 w prix", "700w prix",
    "750 w prix", "750w prix", "800 w prix", "800w prix",
    "850 w prix", "850w prix", "1000 w prix", "1000w prix",
    "ssd 1 to prix", "ssd 500 go prix", "ssd 2 to prix",
    "nvme de 1 to prix", "nvme de 2 to prix", "nvme de 500 go prix",
    "ssd m.2 nvme 1 to prix", "ssd m.2 nvme de 1 to prix",
    "ssd m.2 nvme 500 go prix", "ssd m.2 nvme 2 to prix",
    "ssd nvme 1 to prix", "ssd nvme 500 go prix", "ssd nvme 2 to prix",
    "ssd m.2 pcie nvme 1 to prix", "ssd m.2 pcie nvme 500 go prix",
    "16 go ddr4 prix", "32 go ddr4 prix", "8 go ddr4 prix",
    "16 go ddr5 prix", "32 go ddr5 prix", "64 go ddr5 prix",
    # Cooler générique
    "refroidisseur prix", "refroidisseur cpu prix", "refroidissement processeur prix",
    "ventirad prix", "ventirad cpu prix", "watercooling prix", "watercooling aio prix",
    "cooler cpu prix", "cooler prix",
]

# Requêtes de remplacement intelligentes par composant
REQUETES_GENERIQUES_REMPLACEMENT = {
    "case":        "be quiet Pure Base 500 boitier PC ATX",
    "psu":         "Corsair CV650 alimentation 650W 80+ Bronze",
    "ram":         "Corsair Vengeance 16Go DDR4 3200MHz",
    "ssd":         "Samsung 980 1To NVMe M.2",
    "ssd2":        "WD Blue SN580 2To NVMe M.2",
    "motherboard": "MSI PRO B550M-A PRO carte mere AM4",
}

# Requêtes de secours par composant si la requête principale échoue
def _get_ram_fallbacks(search_query: str) -> list:
    """
    Génère des requêtes de secours RAM adaptées au type DDR et à la capacité
    détectés dans la requête principale.
    Évite de fallback en DDR4 quand on cherche de la DDR5 (ou l'inverse).
    """
    q = search_query.lower()
    # Capacité (ex: 8, 16, 32, 64 Go)
    cap_m = re.search(r'(\d+)\s*go', q)
    cap = cap_m.group(1) if cap_m else "16"

    if "ddr5" in q:
        return [
            f"Corsair Vengeance {cap}Go DDR5 5200MHz",
            f"Kingston Fury Beast {cap}Go DDR5",
            f"G.Skill Ripjaws M5 {cap}Go DDR5",
            f"RAM DDR5 {cap}Go",
        ]
    else:  # DDR4 (ou inconnu → on reste DDR4 par défaut)
        return [
            f"Corsair Vengeance {cap}Go DDR4 3200MHz",
            f"Kingston Fury Beast {cap}Go DDR4",
            f"{cap}Go DDR4 3200MHz",
        ]


FALLBACK_QUERIES = {
    "ssd": [
        "Crucial P3 Plus 1To NVMe M.2",  # ~60€, fiable, résultats propres
        "Kingston NV2 1To M.2 NVMe",
        "WD Blue SN580 1To NVMe M.2",
        "Seagate Barracuda Q5 1To NVMe M.2",
        "SSD NVMe M.2 2280 1To",
    ],
    "ram": [
        "Corsair Vengeance 16Go DDR4 3200MHz",
        "Kingston Fury 16Go DDR4",
        "16Go DDR4 3200",
        "barette RAM 16Go DDR4",
    ],
    "cooler": [
        "be quiet Pure Rock 2",
        "DeepCool AK400",
        "Arctic Freezer 34",
        "ventirad CPU 120mm",
    ],
    # Fallbacks spécifiques ventirad (air cooler)
    "cooler_ventirad": [
        "DeepCool AK400 prix",
        "be quiet Pure Rock 2 prix",
        "Arctic Freezer 34 eSports prix",
        "Noctua NH-U12S prix",
        "Arctic Freezer A35 prix",
    ],
    # Fallbacks spécifiques watercooling AIO
    "cooler_watercooling": [
        "be quiet Pure Loop 2 FX 240mm prix",
        "DeepCool LT240 AIO 240mm prix",
        "Arctic Liquid Freezer III 240mm prix",
        "Corsair H100 RGB 240mm prix",
        "NZXT Kraken 240 AIO prix",
    ],
    "psu": [
        "be quiet System Power 10 650W",
        "be quiet System Power 10 750W",
        "Corsair CV650 80+ Bronze",
        "Seasonic Focus GX 650W",
        "alimentation PC 650W 80+ Bronze",
    ],
    "case": [
        "be quiet Pure Base 500 boitier ATX",
        "Corsair iCUE 4000X RGB boitier",
        "Fractal Design North boitier PC",
        "boitier PC Moyen Tour ATX",
    ],
    # Les fallbacks motherboard sont définis dynamiquement selon le socket
    # dans search_avec_fallback — cette entrée sert uniquement de fallback LGA1700 par défaut
    "motherboard": [
        "MSI PRO B760M-A WiFi",
        "ASUS Prime B760M-A",
        "Gigabyte B760M DS3H",
        "carte mere B760 micro ATX",
    ],
    # Fallbacks AM4
    "motherboard_AM4": [
        "MSI PRO B550M-A PRO",
        "ASUS PRIME B550M-A",
        "Gigabyte B550M DS3H",
        "carte mere B550 micro ATX AM4",
    ],
    # Fallbacks AM5
    "motherboard_AM5": [
        "ASUS PRIME B650M-A WiFi",
        "MSI PRO B650M-A WiFi",
        "Gigabyte B650M DS3H",
        "carte mere B650 micro ATX AM5",
    ],
    # Fallbacks LGA1851 (Intel Core Ultra 200)
    "motherboard_LGA1851": [
        "ASUS PRIME B860M-A WiFi",
        "MSI PRO B860M-A WiFi",
        "ASRock B860M Pro-A",
        "carte mere B860 micro ATX LGA1851",
    ],
    "ssd2": [
        "WD Blue SN570 2To NVMe M.2",
        "Samsung 990 Pro 2To NVMe",
        "Crucial P3 Plus 2To M.2",
        "SSD NVMe 2To M.2",
    ],
}


# ---------------------------------------------------------------------------
# Recherche Google Shopping via SerpAPI
# ---------------------------------------------------------------------------

def search_prix_composant(search_query: str, nb_resultats: int = 6, component_key: str = "", platform_socket: str = "") -> dict:
    """
    Recherche les prix d'un composant sur Google Shopping via SerpAPI.
    Retourne prix minimum, prix moyen et la liste des offres trouvées.
    """
    if not SERPAPI_KEY:
        return {
            "query": search_query,
            "prix_min": None,
            "prix_moyen": None,
            "offres": [],
            "erreur": "Clé SerpAPI manquante — ajoutez SERPAPI_KEY dans le fichier .env",
        }

    try:
        response = requests.get(
            SERPAPI_ENDPOINT,
            params={
                "engine":  "google_shopping",
                "q":       search_query,
                "gl":      "fr",
                "hl":      "fr",
                "api_key": SERPAPI_KEY,
                "num":     nb_resultats,
            },
            timeout=15,
        )
        response.raise_for_status()
        resultats = response.json()
        # Détection d'erreur API niveau SerpAPI
        api_error = resultats.get("error", "")
        if api_error:
            raise RuntimeError(f"SerpAPI : {api_error}")
        shopping = resultats.get("shopping_results", [])
    except Exception as e:
        return {
            "query": search_query,
            "prix_min": None,
            "prix_moyen": None,
            "offres": [],
            "erreur": str(e),
        }

    prix_list = []
    offres = []
    floor   = PRICE_FLOORS.get(component_key, 0)
    ceiling = PRICE_CEILINGS.get(component_key, float("inf"))

    # Mots incompatibles à filtrer dans les titres (ex: refroidisseur TR4 sur PC AM4)
    bad_title_words = []
    if component_key in TITLE_INCOMPATIBILITY_FILTERS and platform_socket:
        bad_title_words = TITLE_INCOMPATIBILITY_FILTERS[component_key].get(platform_socket, [])

    for item in shopping[:nb_resultats]:
        # Champs SerpAPI : "source" → marchand, "link" → lien produit, "price" → prix string
        # On normalise product_link pour garder la compatibilité avec le reste du code
        if "link" in item and "product_link" not in item:
            item["product_link"] = item["link"]

        # Filtrer les sources non fiables (AliExpress, Leboncoin, sites hors EU…)
        source_raw = item.get("source", "").lower()
        lien_raw   = item.get("product_link", "").lower()
        if any(b in source_raw or b in lien_raw for b in BLACKLISTED_SOURCES):
            print(f"   ⚠️  Source ignorée (non fiable : {item.get('source','')}) : {item.get('title','')[:60]}")
            continue

        # Filtrer les titres incompatibles (ex: refroidisseur TR4 pour PC AM4)
        titre_lower = item.get("title", "").lower()
        if bad_title_words and any(w in titre_lower for w in bad_title_words):
            print(f"   ⚠️  Offre ignorée (socket incompatible dans le titre) : {item.get('title','')[:60]}")
            continue

        # PSU : éviter les modèles premium et les mauvais wattages
        if component_key == "psu":
            q_low = search_query.lower()
            # Vérifier cohérence wattage : si on cherche 550W/650W, rejeter 850W+
            watt_q = re.search(r'(\d{3,4})\s*w', q_low)
            watt_t = re.search(r'(\d{3,4})\s*w', titre_lower)
            if watt_q and watt_t:
                asked_w = int(watt_q.group(1))
                found_w = int(watt_t.group(1))
                if found_w > asked_w + 100:  # tolérance +100W (650W cherché → max 750W accepté)
                    print(f"   ⚠️  PSU wattage trop élevé ({found_w}W vs {asked_w}W cherché) : {item.get('title','')[:60]}")
                    continue
            # "system power 10" → rejeter "straight power", "dark power", "pure power 12/13"
            if "system power" in q_low and any(x in titre_lower for x in ["straight power", "dark power", "pure power 12", "pure power 13"]):
                print(f"   ⚠️  PSU premium ignoré (cherche System Power) : {item.get('title','')[:60]}")
                continue
            # Rejeter les RAM ECC / serveur dans les résultats RAM
        if component_key == "ram" and any(x in titre_lower for x in ["ecc", "registered", "rdimm", "lrdimm", " server "]):
            print(f"   ⚠️  RAM serveur ignorée : {item.get('title','')[:60]}")
            continue

        # SSD : rejeter les SSD portables USB, les HDDs, le format 2230 (laptop) et les marques maker
        if component_key in ("ssd", "ssd2"):
            ssd_rejects = [
                "xs2000", "xs1000", " t7 ", " t5 ", "portable", "externe",
                "usb", "thunderbolt", "rugged", "disque dur externe",
                "disque dur ", "disque dur,",   # HDD classique (pas NVMe)
                "seagate barracuda", "seagate ironwolf", "wd red ", "wd purple",
                "seeed studio", "seeed",         # Maker/hobbyist, pas un SSD PC grand public
                "industrial", "industriel",
                "2230",                          # Format M.2 2230 = SSD laptop/Steam Deck, pas desktop
                " p310 ",                        # Crucial P310 = format 2230 exclusivement
            ]
            if any(w in titre_lower for w in ssd_rejects):
                print(f"   ⚠️  SSD portable/HDD/maker ignoré : {item.get('title','')[:60]}")
                continue

        # Filtrer les accessoires de refroidisseur (modules LCD, pièces détachées…)
        if component_key == "cooler" and any(w in titre_lower for w in COOLER_ACCESSORY_BLACKLIST):
            print(f"   ⚠️  Offre ignorée (accessoire cooler, pas le produit) : {item.get('title','')[:60]}")
            continue

        # Carte mère : vérifier la cohérence de la gamme (ROG STRIX ≠ TUF GAMING ≠ PRIME)
        if component_key == "motherboard":
            mobo_lines = {
                "rog strix":    ["rog strix"],
                "rog maximus":  ["rog maximus"],
                "tuf gaming":   ["tuf gaming", "tuf-gaming"],
                "prime":        ["prime"],
                "pro art":      ["proart", "pro art"],
                "msi meg":      ["meg "],
                "msi mpg":      ["mpg "],
                "msi mag":      ["mag "],
                "msi pro":      ["msi pro"],
                "aorus":        ["aorus"],
                "asrock taichi":    ["taichi"],
                "asrock phantom":   ["phantom gaming"],
                # ASRock : distinguer Steel Legend (gaming) vs HDV/HVS (budget)
                "steel legend": ["steel legend"],
                "b550m-hdv":    ["b550m-hdv"],
                "b450m-hdv":    ["b450m-hdv"],
                # B550M ≠ B550 : la variante Micro-ATX doit avoir "M" dans le titre
                "b550m ":       ["b550m"],
                "b450m ":       ["b450m"],
                "b650m ":       ["b650m"],
                "b760m ":       ["b760m"],
                "b860m ":       ["b860m"],
            }
            skip_mobo = False
            q_low = search_query.lower()
            for line_key, line_patterns in mobo_lines.items():
                if line_key in q_low:
                    if not any(p in titre_lower for p in line_patterns):
                        print(f"   ⚠️  Carte mère gamme incohérente (cherche '{line_key}') : {item.get('title','')[:60]}")
                        skip_mobo = True
                        break  # échec immédiat — inutile de vérifier les autres clés
            if skip_mobo:
                continue

        # CPU : rejeter les kits de montage, combos, PC entiers et accessoires
        if component_key == "cpu":
            cpu_rejects = [
                "kit de montage", "kit montage", "mounting kit", "bracket kit",
                "kit upgrade", "kit évolution", "kit mise à niveau", "kit amélioration",
                "upgrade bundle",
                "pack processeur", "pack cpu", "bundle cpu", "bundle processeur",
                "combo cpu", "combo processeur",
                "pc gamer", "ordinateur gamer", "unité centrale", "desktop pc",
                "cyberpowerpc", "cyberpower", "sedatech", "gaming pc",
                "tour gamer", "boîtier", "boitier",
                "ram speicher",   # accessoires mémoire vendus comme CPU
            ]
            if any(w in titre_lower for w in cpu_rejects):
                print(f"   ⚠️  CPU ignoré (kit/PC entier/accessoire) : {item.get('title','')[:60]}")
                continue

        # CPU : vérifier que le modèle correspond (ex: i5-13600KF ≠ i5-12400F)
        if component_key == "cpu":
            # Extrait le numéro de modèle CPU de la requête (ex: "13600", "9800X3D", "285K")
            cpu_m = re.search(
                r'(?:i[3579]-?|ryzen\s*[0-9]\s*|core\s*ultra\s*[0-9]+\s*|xeon\s*)(\d{3,5}[a-z0-9]*)',
                search_query.lower()
            )
            if cpu_m:
                expected_cpu = cpu_m.group(1).lower()
                found_cpu_m = re.search(
                    r'(?:i[3579]-?|ryzen\s*[0-9]\s*|core\s*ultra\s*[0-9]+\s*|xeon\s*)(\d{3,5}[a-z0-9]*)',
                    titre_lower
                )
                if found_cpu_m:
                    found_cpu = found_cpu_m.group(1).lower()
                    if found_cpu != expected_cpu:
                        # Tolérance pour variantes K/KF (ex: 245KF ≈ 245K, 13600KF ≈ 13600K)
                        # On retire le suffixe terminal "f" pour comparer le socle
                        norm_exp = re.sub(r'f$', '', expected_cpu)
                        norm_fnd = re.sub(r'f$', '', found_cpu)
                        if norm_exp != norm_fnd:
                            print(f"   ⚠️  CPU incohérent (cherche {expected_cpu}, trouve {found_cpu}) : {item.get('title','')[:60]}")
                            continue

        # GPU : vérifier que le modèle de carte graphique correspond
        # Ex: cherche "RTX 5060" → rejeter "RTX 5050", "RTX 5070", "RTX 4060"
        if component_key == "gpu":
            gpu_model_m = re.search(
                r'(rtx\s*\d{4}(?:\s*ti)?|rx\s*\d{4}(?:\s*xt)?|arc\s*[ab]\d{3})',
                search_query.lower()
            )
            if gpu_model_m:
                expected_gpu = re.sub(r'\s+', '', gpu_model_m.group(1))  # "rtx5060"
                found_gpu_m = re.search(
                    r'(rtx\s*\d{4}(?:\s*ti)?|rx\s*\d{4}(?:\s*xt)?|arc\s*[ab]\d{3})',
                    titre_lower
                )
                if found_gpu_m:
                    found_gpu = re.sub(r'\s+', '', found_gpu_m.group(1))  # "rtx5050"
                    if found_gpu != expected_gpu:
                        print(f"   ⚠️  GPU incohérent (cherche {expected_gpu}, trouve {found_gpu}) : {item.get('title','')[:60]}")
                        continue

        # Cohérence modèle cooler : si la requête cible un modèle précis (ex: NH-U12S),
        # rejeter les résultats avec un modèle clairement différent (ex: NH-D15S)
        if component_key == "cooler":
            model_m = re.search(
                r'(nh-[a-z0-9]+|ak\d+|kraken\s*[a-z0-9]+|pure rock\s*\d*|'
                r'freezer\s*\d+|h\d{2,3}i?|x\d{2}|ts\d+)',
                search_query.lower()
            )
            if model_m:
                expected = model_m.group(1).replace(" ", "")
                found_model = re.search(
                    r'(nh-[a-z0-9]+|ak\d+|kraken\s*[a-z0-9]+|pure rock\s*\d*|'
                    r'freezer\s*\d+|h\d{2,3}i?|x\d{2}|ts\d+)',
                    titre_lower
                )
                if found_model:
                    found = found_model.group(1).replace(" ", "")
                    if found != expected:
                        print(f"   ⚠️  Modèle cooler incohérent ({expected} ≠ {found}) : {item.get('title','')[:60]}")
                        continue

        # Serper retourne "price" en string (ex: "149,99 €") — on le parse
        # extracted_price n'existe pas chez Serper, on utilise uniquement _parse_price
        prix = _parse_price(item.get("price", ""))
        if prix and prix > 0:
            if prix < floor:
                print(f"   ⚠️  Prix ignoré (trop bas : {prix} € < plancher {floor} €) : {item.get('title','')[:60]}")
                continue
            if prix > ceiling:
                print(f"   ⚠️  Prix ignoré (trop haut : {prix} € > plafond {ceiling} €) : {item.get('title','')[:60]}")
                continue
            # PSU budget (System Power 10, CV series…) → max 125€
            # Ces alims coûtent ~50-90€, toute offre > 125€ est un listing marketplace aberrant
            if component_key == "psu":
                _BUDGET_PSU_PATTERNS = [
                    "system power 10", "system power 9", "system power 8",
                    "cv650", "cv750", "cv550", "cv450", "cv850",
                    "alhena", "corsair cv",
                ]
                q_psu_low = search_query.lower()
                if any(bp in q_psu_low for bp in _BUDGET_PSU_PATTERNS) and prix > 125:
                    print(f"   ⚠️  Prix ignoré (budget PSU > 125€) : {item.get('title','')[:60]}")
                    continue
            prix_list.append(prix)
            offres.append({
                "titre":  item.get("title", "")[:80],
                "prix":   prix,
                "site":   item.get("source", ""),
                "lien":   item.get("product_link", ""),
            })

    if not prix_list:
        return {
            "query": search_query,
            "prix_min": None,
            "prix_moyen": None,
            "offres": [],
            "erreur": "Aucun prix trouvé pour cette requête",
        }

    def _sort_key(offre):
        """Tri principal par prix, à égalité les sites de confiance passent en premier."""
        prix = offre["prix"]
        source_lower = offre.get("site", "").lower()
        is_trusted = any(t in source_lower for t in TRUSTED_SOURCES)
        # Léger bonus de -0.01€ pour les sites de confiance (tri stable, non décisif sur le prix)
        return (round(prix, 0), 0 if is_trusted else 1)

    offres_triees = sorted(offres, key=_sort_key)
    prix_moyen = round(statistics.mean(prix_list), 2)

    # Lien de l'offre la moins chère
    lien_moins_cher = offres_triees[0]["lien"] if offres_triees else None
    titre_moins_cher = offres_triees[0]["titre"] if offres_triees else None
    site_moins_cher = offres_triees[0]["site"] if offres_triees else None

    # Lien de l'offre la plus proche du prix moyen (pour les composants estimés)
    offre_proche_moyenne = min(offres_triees, key=lambda x: abs(x["prix"] - prix_moyen))
    lien_prix_moyen = offre_proche_moyenne["lien"]
    titre_prix_moyen = offre_proche_moyenne["titre"]
    site_prix_moyen = offre_proche_moyenne["site"]

    return {
        "query":            search_query,
        "prix_min":         round(min(prix_list), 2),
        "prix_moyen":       prix_moyen,
        "offres":           offres_triees,
        "lien_moins_cher":  lien_moins_cher,
        "titre_moins_cher": titre_moins_cher,
        "site_moins_cher":  site_moins_cher,
        "lien_prix_moyen":  lien_prix_moyen,
        "titre_prix_moyen": titre_prix_moyen,
        "site_prix_moyen":  site_prix_moyen,
        "erreur":           None,
    }


# ---------------------------------------------------------------------------
# Recherche avec requêtes de secours automatiques
# ---------------------------------------------------------------------------

def search_avec_fallback(search_query: str, component_key: str, platform_socket: str = "") -> dict:
    """
    Tente la requête principale. Si la requête est trop générique ou
    ne retourne aucun résultat, essaie les requêtes de secours.
    """
    # Intercepter les requêtes trop génériques avant d'appeler SerpAPI
    if search_query.lower().strip() in QUERIES_TROP_GENERIQUES:
        remplacement = REQUETES_GENERIQUES_REMPLACEMENT.get(component_key)
        if remplacement:
            sq_low = search_query.lower()

            # Pour la RAM : adapter le remplacement au type DDR de la requête originale
            if component_key == "ram":
                cap_m = re.search(r'(\d+)\s*go', sq_low)
                cap   = cap_m.group(1) if cap_m else "16"
                if "ddr5" in sq_low:
                    remplacement = f"Kingston Fury Beast {cap}Go DDR5 5200MHz"
                elif "ddr4" in sq_low:
                    remplacement = f"Corsair Vengeance {cap}Go DDR4 3200MHz"
                # sinon : remplacement par défaut DDR4

            # Pour le cooler : adapter ventirad vs watercooling
            elif component_key == "cooler":
                cooler_type = _detect_cooler_type(search_query)
                if cooler_type == "watercooling":
                    remplacement = "be quiet Pure Loop 2 FX 240mm prix"
                else:
                    remplacement = "DeepCool AK400 prix"

            # Pour le PSU : adapter le wattage de la requête originale
            elif component_key == "psu":
                w_m = re.search(r'(\d{3,4})\s*w', sq_low)
                if w_m:
                    watts = int(w_m.group(1))
                    if watts >= 850:
                        remplacement = "be quiet System Power 10 850W"
                    elif watts >= 750:
                        remplacement = "be quiet System Power 10 750W"
                    elif watts >= 700:
                        remplacement = "Corsair RM700e 700W 80+ Gold"
                    elif watts >= 600:
                        remplacement = "be quiet System Power 10 650W"
                    else:
                        remplacement = "Corsair CV550 alimentation 550W 80+ Bronze"

            print(f"   ↪ Requête générique détectée → remplacement : {remplacement}")
            search_query = remplacement

    result = search_prix_composant(search_query, component_key=component_key, platform_socket=platform_socket)
    if result["prix_min"] is not None:
        return result

    # Pour GPU et CPU : générer un fallback simplifié à partir de la requête principale
    # (Serper renvoie parfois zéro résultat shopping pour une requête trop précise)
    dynamic_fallbacks = []
    if component_key == "gpu":
        # Ex: "NVIDIA RTX 5070 Ti 16Go prix" → "RTX 5070 Ti carte graphique"
        gpu_m = re.search(r'(rtx\s*\d{4}(?:\s*ti)?|rx\s*\d{4}(?:\s*xt)?|arc\s*[ab]\d{3})', search_query.lower())
        if gpu_m:
            model = gpu_m.group(1)  # "rtx 5070 ti"
            dynamic_fallbacks = [
                f"GeForce {model.upper()} carte graphique",
                f"{model.upper()} GPU neuf",
            ]
    elif component_key == "cpu":
        # Ex: "Intel Core Ultra 5 245KF" → "processeur Intel Core Ultra 5 245KF"
        dynamic_fallbacks = [
            f"processeur {search_query}",
            f"{search_query} BOX",
        ]

    # Pour la RAM, utiliser des fallbacks adaptés au type DDR (DDR4 ou DDR5)
    if component_key == "ram":
        fallbacks = _get_ram_fallbacks(search_query)
    elif component_key == "motherboard" and platform_socket:
        # Fallbacks carte mère adaptés au socket de la plateforme
        socket_key = f"motherboard_{platform_socket}"
        fallbacks = FALLBACK_QUERIES.get(socket_key, FALLBACK_QUERIES.get("motherboard", []))
    elif component_key == "cooler":
        # Fallbacks cooler adaptés au type : ventirad ou watercooling
        cooler_type = _detect_cooler_type(search_query)
        if cooler_type == "watercooling":
            fallbacks = dynamic_fallbacks + FALLBACK_QUERIES.get("cooler_watercooling", [])
        elif cooler_type == "ventirad":
            fallbacks = dynamic_fallbacks + FALLBACK_QUERIES.get("cooler_ventirad", [])
        else:
            # Type inconnu → essaye les 2 listes
            fallbacks = dynamic_fallbacks + FALLBACK_QUERIES.get("cooler_ventirad", []) + FALLBACK_QUERIES.get("cooler_watercooling", [])
    else:
        fallbacks = dynamic_fallbacks + FALLBACK_QUERIES.get(component_key, [])

    for fallback_query in fallbacks:
        if fallback_query.lower() == search_query.lower():
            continue
        print(f"   ↪ Requête de secours : {fallback_query}")
        result = search_prix_composant(fallback_query, component_key=component_key, platform_socket=platform_socket)
        if result["prix_min"] is not None:
            return result

    return result  # Retourne le dernier résultat (vide) si tout échoue


# ---------------------------------------------------------------------------
# Recherche pour tous les composants
# ---------------------------------------------------------------------------

def _search_one(key: str, data: dict, platform_socket: str) -> tuple[str, dict, dict | None]:
    """
    Cherche le prix d'un seul composant (appelé en parallèle).
    Retourne (key, data_enrichie, serpapi_error_ou_None).
    """
    query = data.get("search_query", "")
    statut = data.get("status", "found")
    label = COMPONENT_LABELS_FR.get(key, key)

    if not query:
        data["prix_retenu"] = None
        data["prix_details"] = {"erreur": "Pas de requête de recherche"}
        return key, data, None

    print(f"\n  [{label}]  {query}")

    result = search_avec_fallback(query, key, platform_socket=platform_socket)

    # Détecter l'épuisement du quota SerpAPI
    erreur = result.get("erreur", "") or ""
    serper_err = None
    if "credit" in erreur.lower() or "quota" in erreur.lower() or "plan" in erreur.lower() or "upgrade" in erreur.lower() or "run out" in erreur.lower():
        print(f"   ❌ Quota SerpAPI épuisé")
        data["prix_retenu"] = None
        data["prix_details"] = result
        serper_err = erreur
        return key, data, serper_err

    if statut == "estimated":
        prix_retenu  = result["prix_moyen"]
        lien_retenu  = result.get("lien_prix_moyen")
        titre_retenu = result.get("titre_prix_moyen")
        site_retenu  = result.get("site_prix_moyen")
        type_prix    = "moyen (estimé)"
    else:
        prix_retenu  = result["prix_min"]
        lien_retenu  = result.get("lien_moins_cher")
        titre_retenu = result.get("titre_moins_cher")
        site_retenu  = result.get("site_moins_cher")
        type_prix    = "min"

    data["prix_retenu"] = prix_retenu
    data["lien_retenu"] = lien_retenu
    data["titre_retenu"] = titre_retenu
    data["site_retenu"] = site_retenu
    data["prix_details"] = result

    if erreur:
        print(f"   ⚠️  [{label}] Erreur : {erreur}")
    else:
        print(f"   ✓  [{label}] {prix_retenu} € ({type_prix})  — {site_retenu or '?'}")

    return key, data, None


def rechercher_prix_tous_composants(enriched: dict) -> dict:
    """
    Lance la recherche de prix pour chaque composant du dict enrichi (Partie 1).
    Les recherches sont effectuées EN PARALLÈLE (ThreadPoolExecutor) pour
    réduire le temps total de ~30s (séquentiel) à ~5s (parallèle).
    """
    components = enriched.get("components", {})
    total = len(components)
    platform_socket = enriched.get("platform_socket", "")

    print(f"\n{'='*55}")
    print(f"  PARTIE 2 — Recherche des prix ({total} composants) [parallèle]")
    print(f"{'='*55}")

    # Lancer toutes les recherches en parallèle (max 8 workers = 1 par composant)
    with ThreadPoolExecutor(max_workers=min(8, total)) as executor:
        futures = {
            executor.submit(_search_one, key, data, platform_socket): key
            for key, data in components.items()
        }
        for future in as_completed(futures):
            key, updated_data, serper_err = future.result()
            components[key] = updated_data
            if serper_err and "_serpapi_error" not in enriched:
                enriched["_serpapi_error"] = serper_err

    enriched["components"] = components
    return enriched


# ---------------------------------------------------------------------------
# Calcul du résultat final de comparaison
# ---------------------------------------------------------------------------

def calculer_comparaison(enriched: dict) -> dict:
    """
    Compare :
      - Prix du PC complet (fiche LDLC)
      - Somme des composants achetés individuellement
    Retourne le résultat de la comparaison avec économies ou surcoût.
    """
    prix_pc = enriched.get("product_price", 0)
    components = enriched.get("components", {})

    prix_composants = []
    composants_sans_prix = []

    for key, data in components.items():
        prix = data.get("prix_retenu")
        if prix:
            prix_composants.append(prix)
        else:
            composants_sans_prix.append(COMPONENT_LABELS_FR.get(key, key))

    total_composants = round(sum(prix_composants), 2)
    difference = round(prix_pc - total_composants, 2)

    print(f"\n{'='*55}")
    print(f"  RÉSULTAT DE LA COMPARAISON")
    print(f"{'='*55}")
    print(f"  Prix PC complet (LDLC)        : {prix_pc} €")
    print(f"  Somme des composants séparés  : {total_composants} €")
    print(f"  Différence                    : {difference:+.2f} €")

    if composants_sans_prix:
        print(f"\n  ⚠️  Composants sans prix (non inclus dans le total) :")
        for c in composants_sans_prix:
            print(f"     - {c}")

    # Verdict de rentabilité
    # difference = prix_pc - total_composants
    #   > 0 → le PC prémonté est PLUS CHER que les pièces séparées → bon deal pour l'acheteur
    #  <= 0 → le PC prémonté est MOINS CHER (ou identique) → pas d'économie à monter soi-même
    if difference <= 0:
        verdict_label = "PAS DE DEAL"
        verdict_sub = f"Le PC prémonté est moins cher que les pièces séparées (économie de {abs(difference):.2f} € sur le prémonté)."
        verdict_log = "❌ Pas de deal — le PC tout monté est moins cher que les pièces séparées"
    elif difference <= 200:
        verdict_label = "BON DEAL"
        verdict_sub = f"Vous économisez {difference} € en achetant les pièces séparément."
        verdict_log = f"✅ BON DEAL — économie de {difference} €"
    elif difference <= 400:
        verdict_label = "BIG DEAL"
        verdict_sub = f"Belle économie de {difference} € sur ce PC prémonté !"
        verdict_log = f"🔥 BIG DEAL — économie de {difference} €"
    else:
        verdict_label = "DEAL OF THE LIFE"
        verdict_sub = f"Économie exceptionnelle de {difference} € — foncez !"
        verdict_log = f"🚀 DEAL OF THE LIFE — économie de {difference} €"

    print(f"\n  {verdict_log}")

    return {
        "product_name":    enriched.get("product_name"),
        "product_price":   prix_pc,
        "pc_analysis":     enriched.get("pc_analysis", {}),
        "verdict": {
            "verdict_label":    verdict_label,
            "difference_euros": difference,
            "verdict_sub":      verdict_sub,
        },
        "composants_sans_prix": composants_sans_prix,
        "serpapi_error":   enriched.get("_serpapi_error"),
        "detail_composants": {
            k: {
                "nom":         v.get("name"),
                "statut":      v.get("status"),
                "estime":      v.get("estimated", False),
                "prix_retenu": v.get("prix_retenu"),
                "titre_offre": v.get("titre_retenu"),
                "site":        v.get("site_retenu"),
                "lien":        v.get("lien_retenu"),
            }
            for k, v in components.items()
        },
    }


# ---------------------------------------------------------------------------
# Pipeline complet Partie 2
# ---------------------------------------------------------------------------

def lancer_partie2(enriched: dict) -> dict:
    """
    Point d'entrée Partie 2.
    Prend le résultat enrichi de la Partie 1 et retourne la comparaison finale.
    """
    enriched_with_prices = rechercher_prix_tous_composants(enriched)
    return calculer_comparaison(enriched_with_prices)


# ---------------------------------------------------------------------------
# Test standalone
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Données simulées issues de la Partie 1
    test_enriched = {
        "product_name": "LDLC PC11 Bazooka Fox Gen 12",
        "product_price": 1499.95,
        "pc_analysis": {
            "usage": "gaming",
            "tier": "milieu de gamme",
        },
        "components": {
            "cpu": {
                "name": "Intel Core i5-12400",
                "search_query": "Intel Core i5-12400",
                "status": "refined",
                "estimated": False,
            },
            "gpu": {
                "name": "NVIDIA GeForce RTX 5060",
                "search_query": "NVIDIA GeForce RTX 5060",
                "status": "found",
                "estimated": False,
            },
            "ram": {
                "name": "32 Go DDR4",
                "search_query": "32 Go DDR4 3200MHz",
                "status": "found",
                "estimated": False,
            },
            "ssd": {
                "name": "SSD 1 To NVMe",
                "search_query": "SSD 1 To NVMe M.2",
                "status": "found",
                "estimated": False,
            },
            "motherboard": {
                "name": "MSI PRO B760M-A WiFi",
                "search_query": "MSI PRO B760M-A WiFi",
                "status": "refined",
                "estimated": False,
            },
            "case": {
                "name": "Fractal Design Meshify C",
                "search_query": "Fractal Design Meshify C",
                "status": "refined",
                "estimated": False,
            },
            "cooler": {
                "name": "Noctua NH-U12S",
                "search_query": "Noctua NH-U12S LGA1700",
                "status": "estimated",
                "estimated": True,
                "reason": "Compatible LGA1700, adapté i5",
            },
            "psu": {
                "name": "EVGA 650 GS 80+ Gold",
                "search_query": "EVGA 650 GS 80+ Gold",
                "status": "refined",
                "estimated": False,
            },
        },
    }

    resultat = lancer_partie2(test_enriched)
    print("\n=== JSON FINAL ===")
    print(json.dumps(resultat, indent=2, ensure_ascii=False))
