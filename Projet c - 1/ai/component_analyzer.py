import json
import os
import re
from groq import Groq


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
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

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

SYSTEM_PROMPT = """Tu es un expert en hardware PC. Ta priorité absolue est la COMPATIBILITÉ entre les composants.

Règles de compatibilité que tu dois respecter impérativement :

SOCKET / PLATEFORME :
- Processeur Intel Core 12e/13e/14e génération (i3/i5/i7/i9-12xxx/13xxx/14xxx) → Socket LGA1700
  → Carte mère : chipset B660, B760, H670, H770, Z690, Z790
  → Refroidisseur : compatible LGA1700 (ex: be quiet Pure Rock 2, Noctua NH-U12S, DeepCool AK400)
- Processeur Intel Core Ultra 200 (Arrow Lake) → Socket LGA1851
  → Carte mère : chipset Z890, B860
  → Refroidisseur : compatible LGA1851/LGA1700
- Processeur AMD Ryzen 5000 (5xxx) → Socket AM4
  → Carte mère : chipset B550, X570, A520
  → Refroidisseur : compatible AM4 (ex: be quiet Pure Rock 2, Noctua NH-U12S, Arctic Freezer 34)
- Processeur AMD Ryzen 7000/8000/9000 (7xxx/8xxx/9xxx) → Socket AM5
  → Carte mère : chipset B650, X670, A620
  → Refroidisseur : compatible AM5

ALIMENTATION :
- GPU RTX 3060 / RX 6600 → minimum 550W
- GPU RTX 3070 / RX 6700 XT → minimum 650W
- GPU RTX 4060 Ti / RX 7700 XT → minimum 650W
- GPU RTX 4070 / RX 7800 XT → minimum 700W
- GPU RTX 5060 / RTX 5060 Ti → minimum 550W
- GPU RTX 5070 → minimum 700W

FORMAT CARTE MÈRE :
- Boîtier Mini-ITX → carte mère Mini-ITX uniquement
- Boîtier Micro-ATX / mATX → carte mère Micro-ATX ou Mini-ITX
- Boîtier Moyen Tour / ATX → carte mère ATX, Micro-ATX ou Mini-ITX

Ne propose JAMAIS un composant incompatible avec le socket ou le format détecté.
Ne propose JAMAIS un refroidisseur TR4/SP3 sauf si le CPU est un Threadripper.
RÈGLE ABSOLUE CPU : si le CPU identifié contient déjà un numéro de modèle précis
  (ex: i5-12400F, Core Ultra 7 270K, Ryzen 5 7500X3D, Ryzen 9 9950X),
  NE LE MODIFIE PAS et NE LE METS PAS dans refined_components.
  Utilise le nom exact tel quel comme search_query (sans le modifier).
Réponds UNIQUEMENT en JSON valide, sans texte ni balises markdown autour."""


def _detect_platform(components: dict, product_name: str = "") -> dict:
    """Détecte le socket et la plateforme à partir du CPU, de la carte mère et du nom produit."""
    cpu  = (components.get("cpu")         or "").lower()
    mobo = (components.get("motherboard") or "").lower()
    name = product_name.lower()

    platform = {"socket": None, "brand": None, "gen": None}

    # ── Étape 1 : détection depuis le CPU et le chipset de la carte mère ─────
    # True si le CPU contient un numéro de modèle spécifique (4-5 chiffres consécutifs)
    # ex: "5500", "7700X", "9800X3D" → True | "4.7 ghz" → False (pas de numéro modèle)
    cpu_has_specific_model = bool(re.search(r'\b\d{4,5}[a-z0-9]{0,3}\b', cpu))

    # Intel
    if "intel" in cpu or any(x in mobo for x in ["b760", "b660", "z790", "z690", "h770", "h670"]):
        platform["brand"] = "Intel"
        if any(f"i{n}-1" in cpu for n in [3, 5, 7, 9]) or any(x in mobo for x in ["b760", "b660", "z790", "z690"]):
            platform["socket"] = "LGA1700"
            platform["gen"] = "12e/13e/14e génération"
        elif "core ultra" in cpu or any(x in mobo for x in ["z890", "b860"]):
            platform["socket"] = "LGA1851"
            platform["gen"] = "Core Ultra 200 (Arrow Lake)"
        else:
            platform["socket"] = "LGA1700"
            platform["gen"] = "12e/13e/14e génération"

    # AMD  — séparé de Intel (elif propre, pas d'imbrication cassante)
    elif "amd" in cpu or any(x in mobo for x in ["b550", "x570", "a520", "b650", "x670", "a620", "x870", "b850", "x970"]):
        platform["brand"] = "AMD"
        am5_mobo = any(x in mobo for x in ["b650", "x670", "a620", "x870", "b850", "x970"])
        # AM5 si CPU contient un numéro 7xxx/8xxx/9xxx (ex: Ryzen 7 7700X, Ryzen 9 9950X)
        am5_cpu  = bool(re.search(r"ryzen [579] [789]\d{3}", cpu))
        # Détection AM5 supplémentaire : modèles X3D AM5 (ex: 9800X3D, 7950X3D)
        am5_x3d  = bool(re.search(r"ryzen [579] [789]\d{3}x3d", cpu))
        if am5_mobo or am5_cpu or am5_x3d:
            platform["socket"] = "AM5"
            platform["gen"] = "Ryzen 7000/8000/9000"
        else:
            # Défaut → AM4, MAIS peut être corrigé par les hints du nom produit si CPU générique
            platform["socket"] = "AM4"
            platform["gen"] = "Ryzen 5000"

    # ── Étape 2 : affiner/corriger depuis le nom du produit ──────────────────
    #
    # Deux cas nécessitent les hints du nom produit :
    #   A) Socket pas encore déterminé (ni Intel ni AMD détecté dans CPU/mobo)
    #   B) AMD AM4 par défaut ET CPU générique (sans numéro de modèle précis)
    #      → le nom produit peut indiquer AM5 (ex: "Zen-M5")
    #
    # Si le CPU a un numéro de modèle précis (ex: Ryzen 5 5500), on fait confiance
    # à la détection matérielle et on n'écrase pas avec les hints du nom.
    _need_name_hint = (
        not platform["socket"] or
        # AMD AM4 par défaut + CPU générique → le nom produit peut indiquer AM5
        (platform["socket"] == "AM4" and platform["brand"] == "AMD" and not cpu_has_specific_model) or
        # Intel LGA1700 par défaut + CPU générique → le nom produit peut indiquer LGA1851
        (platform["socket"] == "LGA1700" and platform["brand"] == "Intel" and not cpu_has_specific_model)
    )

    if _need_name_hint:
        # AM5 : conventions de nommage LDLC ("Zen-M5") ou chipsets AM5 dans le nom/mobo
        if any(x in name for x in ["zen-m5", "zen m5", "am5"]) or \
           any(x in mobo  for x in ["b650", "x670", "a620", "x870", "b850", "x970"]):
            platform["brand"] = "AMD"
            platform["socket"] = "AM5"
            platform["gen"] = "Ryzen 7000/8000/9000"
        # LGA1851 : "Gen15", "Gen 15", chipsets B860/Z890 dans le nom/mobo
        elif any(x in name for x in ["gen15", "gen 15", "b860", "z890"]) or \
             any(x in mobo  for x in ["b860", "z890"]):
            platform["brand"] = "Intel"
            platform["socket"] = "LGA1851"
            platform["gen"] = "Core Ultra 200 (Arrow Lake)"
        # AM4 final : marque AMD sans indices plus précis
        elif not platform["socket"] and ("amd" in cpu or "ryzen" in cpu):
            platform["brand"] = "AMD"
            platform["socket"] = "AM4"
            platform["gen"] = "Ryzen 5000"

    return platform


def _build_prompt(product_name: str, product_price: float, components: dict, platform: dict) -> str:
    found = {k: v for k, v in components.items() if v}
    missing = [k for k, v in components.items() if not v]

    # Séparer les valeurs précises des valeurs génériques
    generics = {k: v for k, v in found.items() if _is_generic(k, v)}
    precise  = {k: v for k, v in found.items() if not _is_generic(k, v)}

    found_lines = "\n".join(
        f"  - {COMPONENT_LABELS_FR[k]} : {v}" for k, v in precise.items()
    )
    generic_lines = "\n".join(
        f"  - {COMPONENT_LABELS_FR[k]} : {v}  ← DOIT être affiné (référence trop générique)"
        for k, v in generics.items()
    )
    missing_lines = "\n".join(f"  - {COMPONENT_LABELS_FR[k]}" for k in missing)

    generic_section = f"\nComposants à AFFINER OBLIGATOIREMENT (référence trop générique) :\n{generic_lines}" if generics else ""
    missing_section = f"\nComposants MANQUANTS à estimer :\n{missing_lines}" if missing else ""

    platform_info = ""
    if platform["socket"]:
        platform_info = f"\nPlateforme détectée : {platform['brand']} {platform['gen']} — Socket {platform['socket']}\n"

    return f"""PC à analyser :
Nom : {product_name}
Prix : {product_price}€
{platform_info}
Composants identifiés avec précision :
{found_lines}
{generic_section}
{missing_section}

Ta mission :
1. Analyse la gamme, le prix et l'usage du PC.
2. Pour chaque composant MANQUANT, propose un équivalent COMPATIBLE avec la plateforme détectée.
3. Pour chaque composant dont la référence est générique, affine avec le modèle exact le plus probable.

RÈGLES ABSOLUES pour les search_query (critiques pour trouver les prix) :
- CPU avec modèle PRÉCIS (ex: "i5-12400F", "Ultra 7 270K", "Ryzen 5 7500X3D") → NE PAS METTRE dans refined_components, utilise le nom exact
- CPU générique "Intel Core i5 X.X GHz"       → cherche le modèle i5 le plus probable du prix du PC
- CPU générique "Intel Core i7 X.X GHz"       → "Intel Core i7-12700KF" (TIER i7, jamais réduire à i5)
- CPU générique "Intel Core i9 X.X GHz"       → "Intel Core i9-14900K" (TIER i9, jamais réduire)
- CPU générique "Intel Core Ultra 5 X.X GHz"  → "Intel Core Ultra 5 245KF" (TIER 5 obligatoire)
- CPU générique "Intel Core Ultra 7 X.X GHz"  → "Intel Core Ultra 7 265F" (TIER 7, JAMAIS Ultra 5)
- CPU générique "Intel Core Ultra 9 X.X GHz"  → "Intel Core Ultra 9 285K" (TIER 9, JAMAIS Ultra 7)
- CPU générique "AMD Ryzen 5 X.X GHz"         → "AMD Ryzen 5 5600X" (modèle exact)
- CPU générique "AMD Ryzen 7 X.X GHz"         → "AMD Ryzen 7 7700X" standard ou "AMD Ryzen 7 7800X3D" si le nom du PC contient "X3D"
- CPU générique "AMD Ryzen 9 X.X GHz"         → "AMD Ryzen 9 9950X" si AM5, "AMD Ryzen 9 5950X" si AM4 ; "AMD Ryzen 9 7950X3D" si PC contient "X3D"
- GPU sans VRAM "NVIDIA GeForce RTX 5060"     → "NVIDIA RTX 5060 8Go" (8Go pour RTX 5060 standard)
- GPU sans VRAM "NVIDIA GeForce RTX 5060 Ti"  → "NVIDIA RTX 5060 Ti 16Go"
- GPU sans VRAM "NVIDIA GeForce RTX 5070"     → "NVIDIA RTX 5070 12Go"
- GPU sans VRAM "NVIDIA GeForce RTX 5070 Ti"  → "NVIDIA RTX 5070 Ti 16Go"
- GPU sans VRAM "NVIDIA GeForce RTX 5080"     → "NVIDIA RTX 5080 16Go"
- GPU sans VRAM "NVIDIA GeForce RTX 5090"     → "NVIDIA RTX 5090 32Go" (32Go, jamais 24Go)
- GPU sans VRAM "NVIDIA GeForce RTX 4070"     → "NVIDIA RTX 4070 12Go"
- GPU sans VRAM "NVIDIA GeForce RTX 3060 Ti"  → "NVIDIA RTX 3060 Ti 8Go"
- SSD générique "SSD 1 To" / "NVMe de 1 To"  → "Crucial P3 Plus 1To NVMe M.2" ou "Kingston NV2 1To M.2" (NE PAS utiliser Samsung 980 ni Samsung 990 EVO — résultats Serper peu fiables)
- SSD générique "SSD 500 Go"                 → "Crucial P3 Plus 500Go NVMe M.2" ou "Kingston NV2 500Go M.2"
- SSD2 (deuxième SSD) si présent              → traite-le séparément comme une clé "ssd2"
- RAM générique "16 Go DDR4"                  → "Corsair Vengeance 16Go DDR4 3200MHz"
- RAM générique "16 Go DDR5"                  → "Kingston Fury Beast 16Go DDR5 5200MHz"
- RAM générique "32 Go DDR5"                  → "G.Skill Trident Z5 32Go DDR5 6000MHz"
- RAM générique "64 Go DDR5"                  → "G.Skill Trident Z5 Neo 64Go DDR5 6000MHz"
- RAM sans type "64 Go de RAM"                → identifie DDR4 ou DDR5 selon la plateforme
- Alimentation générique "650 W" / "650W"     → "be quiet System Power 10 650W" ou "Corsair CV650"
- Boîtier générique "Moyen Tour"              → "be quiet Pure Base 500" ou "Corsair iCUE 4000X"
- Carte mère chipset seul "A520" / "B650"     → modèle exact COMPATIBLE avec le socket détecté
- Refroidisseur                               → toujours inclure le socket (ex: "Noctua NH-U12S LGA1700")

Format de réponse JSON :
{{
  "pc_analysis": {{
    "usage": "gaming / bureau / création / ...",
    "tier": "entrée de gamme / milieu de gamme / haut de gamme",
    "notes": "analyse en 1-2 phrases"
  }},
  "estimated_components": {{
    "<component_key>": {{
      "name": "Référence exacte COMPATIBLE avec socket {platform['socket'] or 'détecté'}",
      "search_query": "Requête Google Shopping pour trouver le prix",
      "reason": "Explication du choix et confirmation de compatibilité",
      "estimated": true
    }}
  }},
  "refined_components": {{
    "<component_key>": {{
      "name": "Référence précise",
      "search_query": "Requête Google Shopping pour trouver le prix",
      "reason": "Pourquoi cette référence est plus précise",
      "estimated": false
    }}
  }}
}}

Clés valides : cpu, gpu, ram, ssd, ssd2, motherboard, case, cooler, psu.
"estimated_components" = composants MANQUANTS uniquement.
"refined_components" = composants TROUVÉS à affiner uniquement.
Si ssd2 existe dans les composants identifiés, traite-le comme un SSD séparé."""


# Valeurs génériques qui doivent toujours être affinées par l'IA
GENERIC_VALUES = {
    "case":        ["moyen tour", "mid tower", "mini tour", "grand tour", "full tower", "tour atx", "mini-itx"],
    "psu":         ["500 w", "500w", "600 w", "600w", "650 w", "650w", "700 w", "700w",
                    "750 w", "750w", "800 w", "800w", "850 w", "850w", "1000 w", "1000w"],
    "cpu":         ["intel core i3", "intel core i5", "intel core i7", "intel core i9",
                    "intel core ultra",
                    "amd ryzen 3", "amd ryzen 5", "amd ryzen 7", "amd ryzen 9"],
    "ram":         ["8 go ddr4", "16 go ddr4", "32 go ddr4", "64 go ddr4",
                    "8 go ddr5", "16 go ddr5", "32 go ddr5", "64 go ddr5"],
    "ssd":         ["ssd 500 go", "ssd 1 to", "ssd 2 to", "ssd 500go", "ssd 1to",
                    "nvme de 1", "nvme de 2", "nvme de 500", "m.2 nvme de",
                    "de 1 to", "de 2 to", "de 500 go"],
    "motherboard": ["intel b760 express", "intel z790 express",
                    "amd a520", "amd b550", "amd b650", "amd x670", "amd x870", "amd b850",
                    "intel b860", "intel z890", "intel b760", "intel z790",
                    # chipset seul (sans marque)
                    "a520", "b550", "b650", "x670", "x870", "b850",
                    "b860", "z890", "b760", "z790", "b660", "z690"],
}


def _has_specific_cpu_model(value_lower: str) -> bool:
    """True si le CPU contient déjà un numéro de modèle précis (pas juste la fréquence)."""
    return bool(
        re.search(r'\bi\d-\d{4,5}[a-z]{0,3}\b', value_lower) or          # i7-12700KF, i5-13400F
        re.search(r'\bultra\s+\d+\s+\d{3,4}[a-z]{0,3}\b', value_lower) or # Ultra 9 285K, Ultra 5 245KF
        re.search(r'\bryzen\s+[3579]\s+\d{4}[a-z0-9]{0,3}\b', value_lower) # Ryzen 5 5600X, Ryzen 9 9950X
    )


def _has_specific_mobo_model(value_lower: str) -> bool:
    """True si la carte mère est un modèle complet (pas juste un chipset)."""
    # Présence d'une marque de carte mère connue indique un modèle précis
    known_brands = ["asus", "msi", "gigabyte", "asrock", "evga", "nzxt", "biostar", "foxconn"]
    return any(b in value_lower for b in known_brands)


def _is_generic(key: str, value: str) -> bool:
    """Retourne True si la valeur est trop générique pour être utilisée telle quelle."""
    if not value:
        return False
    value_lower = value.lower().strip()
    # Normalise les unités collées (500W → 500 w) pour matcher les deux formats
    value_norm = re.sub(r"(\d)(w|go|to)(\b|$)", r"\1 \2", value_lower)
    generics = GENERIC_VALUES.get(key, [])

    # CPU : ne pas re-flaguer si un numéro de modèle précis est déjà présent
    if key == "cpu":
        if _has_specific_cpu_model(value_lower):
            return False
        return any(g in value_lower or g in value_norm for g in generics)

    # Carte mère : ne pas re-flaguer si un modèle complet (avec marque) est présent
    if key == "motherboard":
        if _has_specific_mobo_model(value_lower):
            return False
        return any(g in value_lower or g in value_norm for g in generics)

    # PSU : générique SEULEMENT si la valeur est uniquement une puissance (ex: "650W", "650 W")
    # Ne pas marquer comme générique si c'est un nom de produit contenant la puissance
    # (ex: "be quiet System Power 10 650W" ne doit PAS être marqué générique)
    if key == "psu":
        return bool(re.match(r'^\d+\s*w(?:atts?)?$', value_norm.strip()))

    # RAM : générique si le type DDR n'est pas mentionné
    if key == "ram":
        if "ddr" not in value_lower:
            return True
        # Générique seulement si la valeur COMMENCE par la capacité (pas par une marque)
        # Ex: "16 Go DDR4 3200MHz" → générique
        # Ex: "Corsair Vengeance 16Go DDR4 3200MHz" → précis (commence par marque)
        if not re.match(r'^\d+\s*(go|gb|to|tb)', value_lower.strip()):
            return False  # commence par une marque ou un nom → précis
        return any(g in value_lower or g in value_norm for g in generics)

    if any(g in value_lower or g in value_norm for g in generics):
        return True

    # GPU : générique si pas de mention de VRAM
    # Utilise regex pour détecter "32 Go", "16Go" même en fin de chaîne (pas de trailing space)
    if key == "gpu":
        has_vram = bool(re.search(r'\d+\s*go\b', value_lower)) or \
                   bool(re.search(r'\d+\s*gb\b', value_lower))
        return not has_vram

    return False


# Refroidisseurs de secours garantis compatibles par socket
# Fallbacks ventirad (air cooler) — PCs ≤ 2000 €
COOLER_FALLBACKS_VENTIRAD = {
    "LGA1700": {"name": "be quiet! Pure Rock 2",     "search_query": "be quiet Pure Rock 2 prix"},
    "LGA1851": {"name": "DeepCool AK400",            "search_query": "DeepCool AK400 prix"},
    "AM4":     {"name": "Arctic Freezer 34 eSports", "search_query": "Arctic Freezer 34 eSports prix"},
    "AM5":     {"name": "DeepCool AK400",            "search_query": "DeepCool AK400 prix"},
}

# Fallbacks watercooling AIO — PCs > 2000 €
COOLER_FALLBACKS_AIO = {
    "LGA1700": {"name": "be quiet! Pure Loop 2 FX 240mm", "search_query": "be quiet Pure Loop 2 FX 240mm prix"},
    "LGA1851": {"name": "DeepCool LT240 AIO",             "search_query": "DeepCool LT240 AIO 240mm prix"},
    "AM4":     {"name": "be quiet! Pure Loop 2 240mm",    "search_query": "be quiet Pure Loop 2 240mm AM4 prix"},
    "AM5":     {"name": "DeepCool LT240 AIO",             "search_query": "DeepCool LT240 AIO AM5 prix"},
}

# Alias utilisé par la validation (ventirad par défaut pour la compatibilité socket)
COOLER_FALLBACKS = COOLER_FALLBACKS_VENTIRAD

# Mots-clés détectant le type de refroidissement (miroir de partie2 pour usage local)
_COOLER_WATER_KW = [
    "aio", "watercooling", "water cooling", "liquid", "240mm", "280mm", "360mm",
    "kraken", "capellix", "pure loop", "lt240", "lt360", "lc240", "lc360",
    "lightflow xt", "liquid freezer", "corsair h100", "corsair h115", "corsair h150",
]
_COOLER_AIR_KW = [
    "ventirad", "air cooler", "pure rock", "ak400", "ak620", "ak500",
    "freezer 34", "freezer 36", "freezer a35", "nh-u", "nh-d", "nh-l",
    "hyper 212", "true spirit", "shadow rock", "dark rock",
]

def _cooler_detected_type(name: str, search_query: str = "") -> str:
    """Retourne 'watercooling', 'ventirad', ou 'unknown'."""
    txt = (name + " " + search_query).lower()
    if any(w in txt for w in _COOLER_WATER_KW):
        return "watercooling"
    if any(w in txt for w in _COOLER_AIR_KW):
        return "ventirad"
    return "unknown"


def _validate_results(ai_result: dict, platform: dict) -> dict:
    """
    Vérifie la compatibilité socket de chaque composant estimé/affiné.
    Si un composant est incompatible, le remplace par un fallback fiable
    au lieu de le supprimer.
    """
    socket = platform.get("socket", "")

    incompatible_keywords = {
        "LGA1700": ["tr4", "sp3", "am4", "am5", "lga2066", "lga4189", "threadripper"],
        "LGA1851": ["tr4", "sp3", "am4", "am5", "lga2066", "threadripper"],
        "AM4":     ["tr4", "sp3", "lga1700", "lga1851", "lga2066", "threadripper"],
        "AM5":     ["tr4", "sp3", "lga1700", "lga1851", "lga2066", "threadripper"],
    }

    bad_keywords = incompatible_keywords.get(socket, [])
    if not bad_keywords:
        return ai_result

    for section in ["estimated_components", "refined_components"]:
        for key, data in list(ai_result.get(section, {}).items()):
            name_lower = data.get("name", "").lower()
            if any(kw in name_lower for kw in bad_keywords):
                print(f"  [Validation] '{data['name']}' incompatible avec {socket} → remplacement par fallback")
                # Remplacer par le fallback compatible au lieu de supprimer
                if key == "cooler" and socket in COOLER_FALLBACKS:
                    fallback = COOLER_FALLBACKS[socket]
                    ai_result[section][key] = {
                        "name":         fallback["name"],
                        "search_query": fallback["search_query"],
                        "reason":       f"Fallback automatique compatible {socket} — le modèle proposé par l'IA était incompatible",
                        "estimated":    True,
                    }
                    print(f"  [Fallback] Refroidisseur remplacé par : {fallback['name']}")
                else:
                    del ai_result[section][key]

    return ai_result


def analyze_components(product_name: str, product_price: float, components: dict, platform: dict) -> dict:
    import time, re as _re
    client = Groq(api_key=GROQ_API_KEY)
    prompt = _build_prompt(product_name, product_price, components, platform)

    # Ordre de préférence des modèles : meilleur d'abord, fallback si quota épuisé
    MODELS = [
        "llama-3.3-70b-versatile",   # qualité optimale
        "llama-3.1-8b-instant",       # fallback rapide si quota 70b épuisé
    ]

    last_error = None
    for model in MODELS:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1024,
                temperature=0.1,
            )
            if model != MODELS[0]:
                print(f"   ℹ️  Modèle de secours utilisé : {model}")
            break  # succès → sortir de la boucle
        except Exception as e:
            last_error = e
            err_str = str(e)
            err_low = err_str.lower()
            if "rate_limit" in err_low or "429" in err_low or "rate limit" in err_low:
                # Lire le délai demandé par Groq ("Please try again in Xm Ys")
                retry_in = 0.0
                m = _re.search(r'try again in\s+(?:(\d+)m\s*)?(\d+(?:\.\d+)?)s', err_str, _re.I)
                if m:
                    retry_in = int(m.group(1) or 0) * 60 + float(m.group(2))

                if retry_in > 20:
                    # Quota journalier épuisé pour CE modèle → essayer le suivant
                    print(f"   ↪ Quota {model} épuisé, tentative avec le modèle suivant...")
                    continue  # passe au modèle suivant dans la boucle

                # Rate-limit mineur (< 20s) → courte attente et retry même modèle
                wait = max(retry_in + 2, 5)
                print(f"   ⏳ Rate limit {model} — attente {wait:.0f}s...")
                time.sleep(wait)
                # On ne continue pas vers le modèle suivant, on réessaie le même
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        max_tokens=1024,
                        temperature=0.1,
                    )
                    break
                except Exception:
                    continue  # passe au modèle suivant
            elif "403" in err_str or "permission" in err_low or "access denied" in err_low:
                # Erreur d'accès transitoire (réseau, quota temporaire) → essayer le modèle suivant
                print(f"   ↪ Erreur accès API 403 ({model}) — tentative avec le modèle suivant...")
                continue
            else:
                raise  # erreur non-rate-limit → propager immédiatement
    else:
        # Tous les modèles ont échoué → dégradation gracieuse (pas de crash pipeline)
        print(f"   ⚠️  Tous les modèles IA ont échoué — enrichissement ignoré")
        return {"estimated_components": {}, "refined_components": {}, "pc_analysis": {}}

    raw = response.choices[0].message.content.strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]

    # Tentative de parse JSON avec retry si malformé (8b-instant produit parfois du JSON tronqué)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Essayer de corriger les problèmes courants (virgule finale, guillemets manquants…)
        import re as _re2
        fixed = _re2.sub(r',\s*([\}\]])', r'\1', raw)   # trailing commas
        try:
            result = json.loads(fixed)
        except json.JSONDecodeError:
            # Dernier recours : retourner un résultat vide (pas d'enrichissement)
            print(f"   ⚠️  JSON malformé retourné par l'IA — enrichissement ignoré")
            result = {"estimated_components": {}, "refined_components": {}, "pc_analysis": {}}

    return _validate_results(result, platform)


def enrich_components(scraped: dict) -> dict:
    product_name = scraped.get("product_name", "")
    product_price = scraped.get("product_price", 0)
    components = dict(scraped.get("components", {}))

    # ssd2 n'est pas un composant obligatoire : ne pas le passer à l'IA s'il est absent
    has_ssd2 = bool(components.get("ssd2"))
    if not has_ssd2:
        components.pop("ssd2", None)

    platform = _detect_platform(components, product_name=product_name)
    if platform["socket"]:
        print(f"  Plateforme détectée : {platform['brand']} {platform['gen']} — Socket {platform['socket']}")

    ai_result = analyze_components(product_name, product_price, components, platform)

    # Re-détecter la plateforme si le CPU était générique et que l'IA l'a affiné
    # (ex: scraper → "AMD Ryzen 7 3.6 GHz" → IA → "AMD Ryzen 7 7700X" → socket AM5, pas AM4)
    refined_cpu_name = (
        ai_result.get("refined_components", {}).get("cpu", {}).get("name", "") or
        ai_result.get("estimated_components", {}).get("cpu", {}).get("name", "")
    )
    if refined_cpu_name and not _has_specific_cpu_model(components.get("cpu", "").lower()):
        updated_for_detection = dict(components)
        updated_for_detection["cpu"] = refined_cpu_name
        platform_refined = _detect_platform(updated_for_detection, product_name=product_name)
        if platform_refined.get("socket") and platform_refined["socket"] != platform.get("socket"):
            platform = platform_refined
            print(f"  Plateforme re-détectée (CPU affiné) : {platform['brand']} {platform['gen']} — Socket {platform['socket']}")

    enriched_components = {}

    for key, value in components.items():
        if value:
            # Construire une search_query propre (sans fréquences inutiles pour le CPU)
            sq_base = value
            if key == "cpu":
                # Supprimer "(3.6 GHz / 4.2 GHz)" et fréquences en fin de chaîne
                sq_base = re.sub(r'\s*\(\d+\.?\d*\s*ghz[^)]*\)', '', sq_base, flags=re.I).strip()
                sq_base = re.sub(r'\s+\d+\.?\d*\s*ghz.*$', '', sq_base, flags=re.I).strip()
            elif key == "gpu":
                # "NVIDIA GeForce RTX 5060 avec 8 Go de mémoire" → "NVIDIA GeForce RTX 5060 8Go"
                # Normaliser les mentions VRAM (extraire Go et reformater proprement)
                vram_m = re.search(r'(\d+)\s*go\b', sq_base, re.I)
                clean  = re.sub(r'\s+avec\s+\d+\s+go\s+de\s+m[ée]moire\b.*', '', sq_base, flags=re.I).strip()
                clean  = re.sub(r'\s+avec\s+\d+\s*go\b.*', '', clean, flags=re.I).strip()
                if vram_m:
                    sq_base = f"{clean} {vram_m.group(1)}Go".strip()
                else:
                    sq_base = clean
            enriched_components[key] = {
                "name": value,
                "search_query": f"{sq_base} prix",
                "status": "generic" if _is_generic(key, value) else "found",
                "estimated": False,
            }

    def _ram_type(s: str) -> str | None:
        """Extrait le type DDR (ddr3/ddr4/ddr5) d'une chaîne, ou None si absent."""
        m = re.search(r'ddr([345])', s, re.I)
        return m.group(0).lower() if m else None

    def _capacity_gb(s: str):
        """Extrait la capacité en Go/To et la convertit en Go (None si absent)."""
        m = re.search(r'(\d+)\s*(go|to|gb|tb)', s, re.I)
        if not m:
            return None
        return int(m.group(1)) * (1024 if m.group(2).lower() in ('to', 'tb') else 1)

    def _psu_watts(s: str):
        """Extrait la puissance PSU en watts depuis une chaîne (None si absent)."""
        m = re.search(r'(\d{3,4})\s*w(?:atts?)?', s, re.I)
        return int(m.group(1)) if m else None

    for key, data in ai_result.get("refined_components", {}).items():
        if key in enriched_components:
            original_status = enriched_components[key]["status"]
            if original_status == "generic":
                # Valeur générique → l'IA l'a affinée avec le modèle exact → on prend tout
                # SAUF si l'IA change le type de RAM (DDR4↔DDR5) → refus silencieux
                if key == "ram":
                    orig_type = _ram_type(enriched_components[key]["name"])
                    ai_type   = _ram_type(data.get("name", ""))
                    if orig_type and ai_type and orig_type != ai_type:
                        print(f"  [Protection] RAM type mismatch ignoré : {orig_type.upper()} scrappé ≠ {ai_type.upper()} IA")
                        continue  # On garde la valeur scrappée, pas le raffinement

                # SAUF si l'IA change la capacité RAM/SSD
                if key in ("ram", "ssd", "ssd2"):
                    orig_gb = _capacity_gb(enriched_components[key]["name"])
                    ai_gb   = _capacity_gb(data.get("name", ""))
                    if orig_gb and ai_gb and orig_gb != ai_gb:
                        print(f"  [Protection] Capacité {key.upper()} différente ignorée : {orig_gb}Go scrappé ≠ {ai_gb}Go IA")
                        continue  # On garde la valeur scrappée

                # SAUF si l'IA réduit la puissance du PSU scrappé
                # (ex: "750 W" → "be quiet 650W" : 750W scrappé > 650W IA → refus)
                if key == "psu":
                    orig_w = _psu_watts(enriched_components[key]["name"])
                    ai_w   = _psu_watts(data.get("name", ""))
                    if orig_w and ai_w and ai_w < orig_w - 50:  # tolérance de 50W
                        print(f"  [Protection] PSU wattage réduit ignoré : {orig_w}W scrappé → {ai_w}W IA")
                        continue  # On garde la valeur scrappée (valeur générique mais avec bon wattage)

                enriched_components[key] = {
                    "name": data["name"],
                    "search_query": data.get("search_query", f"{data['name']} prix"),
                    "status": "refined",
                    "estimated": False,
                    "reason": data.get("reason", ""),
                }
            else:
                # Valeur déjà précise (found) → on GARDE le nom du scraping
                # On peut utiliser la search_query de l'IA si disponible — SAUF si elle
                # change la capacité (RAM/SSD) ou le type DDR
                if data.get("search_query"):
                    if key in ("ram", "ssd", "ssd2"):
                        orig_name = enriched_components[key]["name"].lower()
                        ai_sq     = data["search_query"].lower()
                        orig_gb, ai_gb = _capacity_gb(orig_name), _capacity_gb(ai_sq)
                        orig_type      = _ram_type(orig_name)
                        ai_sq_type     = _ram_type(ai_sq) if key == "ram" else None
                        if orig_gb and ai_gb and orig_gb != ai_gb:
                            pass  # Capacités différentes → ignorer la search_query de l'IA
                        elif key == "ram" and orig_type and ai_sq_type and orig_type != ai_sq_type:
                            pass  # Types DDR différents → ignorer
                        else:
                            enriched_components[key]["search_query"] = data["search_query"]
                    else:
                        enriched_components[key]["search_query"] = data["search_query"]

    for key, data in ai_result.get("estimated_components", {}).items():
        if key not in enriched_components:
            # Composant vraiment manquant dans le scraping → on l'ajoute
            enriched_components[key] = {
                "name": data["name"],
                "search_query": data.get("search_query", f"{data['name']} prix"),
                "status": "estimated",
                "estimated": True,
                "reason": data.get("reason", ""),
            }
        elif enriched_components[key]["status"] == "generic":
            # Valeur générique dans le scraping → l'IA peut la raffiner
            # SAUF si elle change la capacité ou le type DDR (RAM/SSD)
            orig_name = enriched_components[key]["name"].lower()
            ai_name   = data["name"].lower()
            ai_sq     = data.get("search_query", f"{data['name']} prix")
            capacity_ok = True
            if key in ("ram", "ssd", "ssd2"):
                orig_gb, ai_gb = _capacity_gb(orig_name), _capacity_gb(ai_name)
                if orig_gb and ai_gb and orig_gb != ai_gb:
                    capacity_ok = False
                    print(f"  [Protection] Capacité {key.upper()} différente ignorée : {orig_gb}Go scrappé ≠ {ai_gb}Go IA")
            if key == "ram" and capacity_ok:
                orig_type = _ram_type(orig_name)
                ai_type   = _ram_type(ai_name)
                if orig_type and ai_type and orig_type != ai_type:
                    capacity_ok = False
                    print(f"  [Protection] RAM type mismatch ignoré : {orig_type.upper()} scrappé ≠ {ai_type.upper()} IA")
            if key == "psu" and capacity_ok:
                orig_w = _psu_watts(orig_name)
                ai_w   = _psu_watts(ai_name)
                if orig_w and ai_w and ai_w < orig_w - 50:
                    capacity_ok = False
                    print(f"  [Protection] PSU wattage réduit ignoré : {orig_w}W scrappé → {ai_w}W IA")
            if capacity_ok:
                enriched_components[key] = {
                    "name": data["name"],
                    "search_query": ai_sq,
                    "status": "refined",   # raffiné (pas vraiment estimé)
                    "estimated": False,
                    "reason": data.get("reason", ""),
                }
        # Si status == "found" : on IGNORE l'estimation de l'IA — la valeur scrappée est précise

    # Si ssd2 existait dans le scraping mais a été ignoré, le rajouter maintenant (tel quel)
    if has_ssd2 and "ssd2" not in enriched_components:
        raw_ssd2 = scraped["components"].get("ssd2", "")
        if raw_ssd2:
            enriched_components["ssd2"] = {
                "name": raw_ssd2,
                "search_query": f"{raw_ssd2} SSD NVMe prix",
                "status": "generic",
                "estimated": False,
            }

    final_socket = platform.get("socket", "")

    # Après re-détection, corriger le cooler estimé si son socket est incompatible
    # (l'IA a tourné avec l'ancien socket → refroidisseur avec mauvais socket)
    # Choisir le bon dictionnaire de fallback cooler selon le prix du PC
    # PC > 2000 € → watercooling AIO 240mm (standard sur les configs premium)
    # PC ≤ 2000 € → ventirad air cooler
    _use_aio = (product_price or 0) > 2000
    _cooler_fb_dict = COOLER_FALLBACKS_AIO if _use_aio else COOLER_FALLBACKS_VENTIRAD
    _cooler_type_label = "watercooling AIO" if _use_aio else "ventirad"

    if final_socket and "cooler" in enriched_components:
        cooler_data = enriched_components["cooler"]
        if cooler_data.get("status") in ("estimated",):
            cooler_name  = cooler_data.get("name", "")
            cooler_sq    = cooler_data.get("search_query", "")

            # 1) Correction socket incompatible
            bad_sockets  = {"AM4": ["lga1700", "lga1851", "am5"],
                            "AM5": ["lga1700", "lga1851", "am4"],
                            "LGA1700": ["am4", "am5", "lga1851"],
                            "LGA1851": ["am4", "am5", "lga1700"]}
            wrong = bad_sockets.get(final_socket, [])
            name_low, sq_low = cooler_name.lower(), cooler_sq.lower()
            if any(w in name_low or w in sq_low for w in wrong):
                if final_socket in _cooler_fb_dict:
                    fb = _cooler_fb_dict[final_socket]
                    enriched_components["cooler"] = {
                        "name": fb["name"], "search_query": fb["search_query"],
                        "status": "estimated", "estimated": True,
                        "reason": f"Fallback compatible {final_socket} ({_cooler_type_label}, socket re-détecté)",
                    }
                    print(f"  [Correction cooler] Socket re-détecté → {fb['name']} ({_cooler_type_label})")
                    cooler_name = fb["name"]
                    cooler_sq   = fb["search_query"]

            # 2) Correction type : ventirad ↔ watercooling selon prix du PC
            current_type = _cooler_detected_type(cooler_name, cooler_sq)
            if _use_aio and current_type != "watercooling":
                # PC > 2000 € mais cooler estimé = ventirad → upgrade AIO
                if final_socket in COOLER_FALLBACKS_AIO:
                    fb = COOLER_FALLBACKS_AIO[final_socket]
                    enriched_components["cooler"] = {
                        "name": fb["name"], "search_query": fb["search_query"],
                        "status": "estimated", "estimated": True,
                        "reason": f"PC > 2000 € → watercooling AIO plus adapté",
                    }
                    print(f"  [Correction cooler] PC {product_price}€ > 2000€ → {fb['name']} (watercooling AIO)")
            elif not _use_aio and current_type == "watercooling":
                # PC ≤ 2000 € mais cooler estimé = AIO → downgrade ventirad
                if final_socket in COOLER_FALLBACKS_VENTIRAD:
                    fb = COOLER_FALLBACKS_VENTIRAD[final_socket]
                    enriched_components["cooler"] = {
                        "name": fb["name"], "search_query": fb["search_query"],
                        "status": "estimated", "estimated": True,
                        "reason": f"PC ≤ 2000 € → ventirad air cooler plus adapté",
                    }
                    print(f"  [Correction cooler] PC {product_price}€ ≤ 2000€ → {fb['name']} (ventirad)")

    # ── Fallbacks de dernier recours pour les composants critiques manquants ──
    # Si l'IA a échoué (JSON malformé) ou oublié d'estimer un composant critique,
    # on injecte un composant générique compatible avec la plateforme détectée.
    # Ces composants sont "estimated" pour que leur prix soit traité comme une estimation.
    if final_socket:
        # Cooler manquant → ventirad ou AIO selon prix du PC
        if "cooler" not in enriched_components and final_socket in _cooler_fb_dict:
            fb = _cooler_fb_dict[final_socket]
            enriched_components["cooler"] = {
                "name":         fb["name"],
                "search_query": fb["search_query"],
                "status":       "estimated",
                "estimated":    True,
                "reason":       f"Fallback par défaut ({_cooler_type_label}, composant absent après échec IA)",
            }
            print(f"  [Fallback défaut] Cooler manquant → {fb['name']} ({_cooler_type_label})")

        # Carte mère manquante → injecter un fallback compatible avec le socket
        _MOBO_DEFAULTS = {
            "AM4":     {"name": "MSI PRO B550M-A PRO",       "search_query": "MSI PRO B550M-A PRO AM4 prix"},
            "AM5":     {"name": "ASUS PRIME B650M-A WiFi",   "search_query": "ASUS PRIME B650M-A WiFi AM5 prix"},
            "LGA1700": {"name": "MSI PRO B760M-A WiFi",      "search_query": "MSI PRO B760M-A WiFi LGA1700 prix"},
            "LGA1851": {"name": "ASUS PRIME B860M-A WiFi",   "search_query": "ASUS PRIME B860M-A WiFi LGA1851 prix"},
        }
        if "motherboard" not in enriched_components and final_socket in _MOBO_DEFAULTS:
            fb = _MOBO_DEFAULTS[final_socket]
            enriched_components["motherboard"] = {
                "name":         fb["name"],
                "search_query": fb["search_query"],
                "status":       "estimated",
                "estimated":    True,
                "reason":       f"Fallback par défaut (carte mère absente après échec IA)",
            }
            print(f"  [Fallback défaut] Carte mère manquante → {fb['name']}")

    return {
        "product_name":    product_name,
        "product_price":   product_price,
        "pc_analysis":     ai_result.get("pc_analysis", {}),
        "components":      enriched_components,
        "platform_socket": final_socket,   # transmis à la recherche de prix (re-détecté si nécessaire)
    }


if __name__ == "__main__":
    test_data = {
        "product_name": "LDLC PC11 Bazooka Fox Gen 12",
        "product_price": 1499.95,
        "components": {
            "cpu": "Intel Core i5 2.5 GHz",
            "gpu": "NVIDIA GeForce RTX 5060",
            "ram": "32 Go DDR4",
            "ssd": "SSD 1 To",
            "motherboard": "Intel B760 Express",
            "case": "Moyen Tour",
            "cooler": None,
            "psu": "650 W",
        },
    }

    result = enrich_components(test_data)
    print(json.dumps(result, indent=2, ensure_ascii=False))
