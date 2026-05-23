import asyncio
import json
import re
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup


LDLC_DOMAIN = "ldlc.com"

# Mapping composant → labels exacts du tableau LDLC (priorité : premier de la liste)
COMPONENT_LABELS = {
    "cpu":         ["processor", "processeur"],
    "gpu":         ["graphics chipset", "chipset graphique", "carte graphique"],
    "ram":         ["memory size", "taille de la mémoire", "taille mémoire"],
    "ssd":         ["hard drive(s) configuration", "configuration disque(s)", "configuration disque dur(s)"],
    "motherboard": ["chipset"],
    "case":        ["case format", "format du boitier", "format boîtier", "format du boîtier"],
    "cooler":      ["cooler", "refroidisseur", "ventirad"],
    "psu":         ["power supply", "puissance", "power", "alimentation"],
}

# Labels secondaires à combiner avec la valeur principale
SECONDARY_LABELS = {
    "cpu": ["cpu frequency", "fréquence cpu"],
    "ram": ["memory type", "type de mémoire", "type mémoire"],
}

# Labels à ignorer absolument (trop génériques ou hors-sujet)
BLACKLIST_LABELS = {
    "cpu": ["platform (processor)", "plateforme (proc.)", "plateforme (processeur)"],
    "psu": ["maximum ram capacity", "maximum ram capacity per slot",
            "capacité maximale de ram", "capacité maximale de ram par slot"],
}

# Mots-clés pour identifier les composants dans la liste de description LDLC
DESCRIPTION_KEYWORDS = {
    "cpu":         ["processeur", "processor"],
    "gpu":         ["carte graphique", "graphics card", "chipset graphique"],
    "ram":         ["mémoire", "memory", "ram"],
    "ssd":         ["ssd", "nvme", "stockage", "disque"],
    "motherboard": ["carte mère", "motherboard", "chipset"],
    "case":        ["boîtier", "boitier", "case"],
    "cooler":      ["refroidisseur", "ventirad", "cooler", "watercooling",
                    "water cooling", "water-cooling", "aio", "liquid", "liquide",
                    "nzxt kraken", "corsair h1", "be quiet silent loop",
                    "deepcool castle", "arctic liquid", "enermax liqmax"],
    "psu":         ["alimentation", "watts", "watt", "power supply"],
}

# Préfixes-labels à supprimer de la référence extraite (présents dans les <li> LDLC)
_LABEL_PREFIXES = [
    "watercooling ", "water cooling ", "water-cooling ",
    "refroidisseur ", "ventirad ", "cooler ",
    "processeur ", "processor ",
    "carte graphique ", "chipset graphique ", "graphics card ",
    "graphique ",       # ex: <li>Carte <strong>graphique NVIDIA...</strong></li>
    "carte mère ", "motherboard ",
    "alimentation ", "power supply ",
    "boîtier moyen tour ", "boîtier mini-itx ", "boîtier ",
    "mémoire vive ", "mémoire ", "memory ",   # "mémoire vive " doit être AVANT "mémoire "
    "stockage ", "disque dur ", "disque ",
]


# Mots-clés indiquant du texte marketing LDLC (pas un vrai nom de composant)
_MARKETING_WORDS = [
    "grande capacité", "large capacité", "capacité de stockage",
    "pour vos jeux", "pour votre", "idéal pour", "parfait pour",
    "conception élégante", "design élégant", "haute performance",
    "boostez", "profitez", "découvrez",
]

def _is_marketing_text(text: str) -> bool:
    """Retourne True si le texte ressemble à du marketing plutôt qu'à une référence produit."""
    t = text.lower()
    return any(w in t for w in _MARKETING_WORDS)


# Séparateurs indiquant que la suite du texte est du marketing (pas du nom de produit)
_MARKETING_SEPARATORS = [
    " pour le jeu", " pour le stream", " pour vos ", " pour votre ",
    " watercooling tout-en-un", " water cooling tout", " tout-en-un",
    " idéal pour", " conçu pour",
]

def _truncate_at_marketing(text: str) -> str:
    """
    Tronque le texte à partir du premier séparateur marketing détecté.
    Ex: 'Intel Core Ultra 9 285K pour le jeu et le stream watercooling…'
        → 'Intel Core Ultra 9 285K'
    """
    low = text.lower()
    for sep in _MARKETING_SEPARATORS:
        idx = low.find(sep)
        if idx > 5:  # On ne tronque que si un nom de produit précède
            return text[:idx].strip()
    return text


# Patterns indiquant que le texte COMMENCE par du marketing
# (le vrai nom de composant suit la phrase marketing)
_MARKETING_START_PATTERNS = [
    r'^jouer\s+en\b',          # "Jouer en WQHD (1440p)…"
    r'^jouez\s+',               # "Jouez à vos jeux…"
    r'^profitez\s+',            # "Profitez d'une…"
    r'^vivez\s+',               # "Vivez l'expérience…"
    r'^découvrez\s+',           # "Découvrez la puissance…"
    r'^performez\s+',           # "Performez dans vos jeux…"
    r'^grâce\s+à\b',            # "Grâce à la RTX…"
    r'^avec\s+ce\s+pc',         # "Avec ce PC, jouez…"
    r'^exploitez\s+',           # "Exploitez la puissance…"
    r'^tirez\s+le\s+meilleur',  # "Tirez le meilleur de…"
    r'^entrez\s+dans',          # "Entrez dans le monde…"
    r'^plongez\s+',             # "Plongez dans l'action…"
]

# Patterns pour extraire un nom de composant connu depuis un texte marketing
_COMPONENT_NAME_PATTERNS = [
    r'NVIDIA\s+GeForce\s+(?:RTX|GTX)\s*\d{3,4}(?:\s*(?:Ti|SUPER|XT))?\b',
    r'AMD\s+Radeon\s+RX\s*\d{3,4}(?:\s*(?:XT|XTX|GRE|M))?\b',
    r'Intel\s+Arc\s+[A-Z]\d{3,}\b',
    r'Intel\s+Core(?:\s+Ultra)?\s+(?:i\d|Ultra\s+\d)\s*[-]?\s*\d+[A-Za-z0-9]*\b',
    r'AMD\s+Ryzen\s+(?:Threadripper\s+)?\s*[3579]\s+\d+[A-Za-z]*\b',
    r'Ryzen\s+[AI]\s+(?:PRO\s+)?\d+[A-Za-z]*\b',  # Ryzen AI / Ryzen AI PRO
]


def _starts_with_marketing(text: str) -> bool:
    """Retourne True si le texte commence par une phrase marketing."""
    low = text.lower().strip()
    return any(re.match(p, low) for p in _MARKETING_START_PATTERNS)


def _extract_component_name(text: str) -> str | None:
    """
    Tente d'extraire un nom de composant connu depuis un texte marketing.
    Ex: 'Jouer en WQHD (1440p) à 60 fps et plus NVIDIA GeForce RTX 5070 Ti'
        → 'NVIDIA GeForce RTX 5070 Ti'
    Retourne None si aucun composant reconnu n'est trouvé.
    """
    for pattern in _COMPONENT_NAME_PATTERNS:
        m = re.search(pattern, text, re.I)
        if m:
            return m.group(0).strip()
    return None


def validate_ldlc_url(url: str) -> bool:
    return LDLC_DOMAIN in url


async def fetch_page_html(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        # Bloquer les ressources inutiles pour accélérer le chargement
        # NB: on ne bloque PAS "other" (inclut XHR/fetch utilisés par LDLC pour charger les specs)
        _BLOCKED_TYPES = {"image", "media", "font"}
        _BLOCKED_DOMAINS = {"google-analytics", "googletagmanager", "facebook.com",
                            "doubleclick.net", "hotjar.com", "clarity.ms"}

        async def _block_resource(route, request):
            if request.resource_type in _BLOCKED_TYPES:
                await route.abort()
            elif any(d in request.url for d in _BLOCKED_DOMAINS):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", _block_resource)

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector("#product-parameters", timeout=8000)
        except Exception:
            pass
        html = await page.content()
        await browser.close()
        return html


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _get_cell_text(td) -> str:
    links = td.find_all("a")
    if links:
        text = " ".join(a.get_text(strip=True) for a in links if a.get_text(strip=True))
        if text:
            return _clean(text)
    return _clean(td.get_text(strip=True))


def _parse_specs_table(soup: BeautifulSoup) -> dict[str, str]:
    """Retourne un dict {label_lower: valeur} depuis #product-parameters."""
    pairs = {}
    table = soup.select_one("#product-parameters")
    if not table:
        return pairs
    for row in table.select("tr"):
        label_tag = row.select_one("td.label h3")
        value_tag = row.select_one("td.checkbox")
        if label_tag and value_tag:
            label = _clean(label_tag.get_text(strip=True)).lower()
            value = _get_cell_text(value_tag)
            if value:
                pairs[label] = value
    return pairs


def _strip_label_prefix(text: str) -> str:
    """Supprime les préfixes-labels LDLC du début d'une référence (ex: 'Watercooling ')."""
    low = text.lower()
    for prefix in _LABEL_PREFIXES:
        if low.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def _find_config_ul(soup: BeautifulSoup):
    """
    Retourne le <ul> de la liste de configuration du PC.
    Stratégie 1 : cherche un <strong> avec 'configuration' puis le <ul> suivant.
    Stratégie 2 (fallback) : cherche le premier <ul> du #description dont les items
                             contiennent des liens vers des fiches LDLC (/fiche/PB…),
                             signe d'une vraie liste de composants (pas du marketing).
    """
    # Stratégie 1 : header "Configuration détaillée" explicite
    for strong in soup.find_all("strong"):
        if "configuration" in strong.get_text(strip=True).lower():
            ul = strong.find_next("ul")
            if ul:
                return ul

    # Stratégie 2 : <ul> avec au moins 2 liens vers des fiches LDLC
    desc = soup.select_one("#description") or soup
    for ul in desc.find_all("ul"):
        fiche_links = sum(
            1 for a in ul.find_all("a", href=True)
            if "/fiche/" in a["href"] or "/product/" in a["href"]
        )
        if fiche_links >= 2:
            return ul

    # Stratégie 3 (fallback pour les pages LDLC récentes sans liens /fiche/) :
    # cherche le <ul> du #description dont les <li> contiennent des mots-clés
    # caractéristiques d'une liste de composants PC (ex : processeur, graphique…)
    _COMP_KEYWORDS_S3 = [
        "processeur", "processor", "carte graphique", "graphics",
        "mémoire", "memory", "ssd", "nvme", "carte mère", "motherboard",
        "boîtier", "boitier", "alimentation", "watercooling",
        "refroidisseur", "ventirad",
    ]
    for ul in desc.find_all("ul"):
        comp_items = sum(
            1 for li in ul.find_all("li")
            if any(kw in li.get_text(separator=" ", strip=True).lower()
                   for kw in _COMP_KEYWORDS_S3)
        )
        if comp_items >= 3:
            return ul

    return None


def _parse_description_refs(soup: BeautifulSoup) -> dict[str, str]:
    """
    Parse la liste de configuration dans div#description.
    Gère deux formats LDLC :
      - Avec en-tête <strong>Configuration détaillée</strong> + <ul>
      - Sans en-tête : premier <ul> du #description contenant les composants
    Retourne un dict {composant: référence_exacte}.
    """
    refs = {}
    config_ul = _find_config_ul(soup)
    if not config_ul:
        return refs

    for li in config_ul.select("li"):
        full_text = _clean(li.get_text(separator=" ", strip=True))
        full_lower = full_text.lower()

        # Référence exacte : priorité au texte des <strong>, sinon texte brut
        # separator="" évite "S SD" (mot scindé par une balise inline)
        # strip=False préserve les espaces internes ("Watercooling " + lien → pas de fusion)
        strong_texts = [
            _clean(s.get_text(separator="", strip=False))
            for s in li.find_all("strong")
            if s.get_text(strip=True)
        ]
        if strong_texts:
            exact_ref = " ".join(strong_texts)
            exact_ref = re.sub(r"^\d+-Core\s*", "", exact_ref).strip()
        else:
            # separator="", strip=False : préserve les espaces internes ("Alimentation " + lien)
            # et évite les splits de mots ("S" + <span>"SD..."</span> → "SSD")
            exact_ref = _clean(li.get_text(separator="", strip=False))

        if not exact_ref:
            continue

        # Supprimer les préfixes-labels (ex: "Watercooling ", "Alimentation ", …)
        exact_ref = _strip_label_prefix(exact_ref)
        if not exact_ref:
            continue

        for component, keywords in DESCRIPTION_KEYWORDS.items():
            if component in refs:
                continue
            if any(kw in full_lower for kw in keywords):
                if component == "psu":
                    # Extraire la puissance seulement si c'est une description générique
                    # (ex: "500 watts", "650W seul")
                    # Garder le nom de produit si une marque PSU connue est présente
                    _PSU_BRANDS = [
                        "be quiet", "corsair", "seasonic", "antec", "silverstone", "evga",
                        "cooler master", "thermaltake", "fractal", "nzxt", "enermax",
                        "deepcool", "gigabyte", "msi", "asus", "super flower", "superflower",
                        "bitfenix", "lian li", "xfx", "aerocool", "chieftec", "fsp", "fortron",
                        "ldlc", "kolink", "sharkoon", "phanteks", "silverpower",
                    ]
                    ref_low = exact_ref.lower()
                    has_brand = any(brand in ref_low for brand in _PSU_BRANDS)
                    if not has_brand:
                        m = re.search(r"(\d+)\s*watts?", exact_ref, re.I)
                        if m:
                            exact_ref = f"{m.group(1)}W"
                elif component == "motherboard":
                    # Nettoie les préfixes résiduels après strip_label_prefix :
                    # "avec Chipset Intel B860" → "Intel B860"
                    # "ATX avec chipset AMD B650" → "AMD B650"
                    exact_ref = re.sub(
                        r"^(?:(?:atx|micro.?atx|mini.?itx)\s+)?avec\s+chipset\s+",
                        "", exact_ref, flags=re.I
                    ).strip()
                    # "Chipset B450" → "B450"
                    exact_ref = re.sub(r"^chipset\s+", "", exact_ref, flags=re.I).strip()
                elif component == "cooler":
                    # "RGB 240 mm Fox Spirit LightFlow GX240 ARGB" → "Fox Spirit LightFlow GX240 ARGB"
                    exact_ref = re.sub(
                        r"^(?:rgb\s+)?\d+\s*mm\s+", "", exact_ref, flags=re.I
                    ).strip()
                # ── Filtrage marketing ─────────────────────────────────────────
                # Cas 1 : le texte COMMENCE par du marketing
                # ex: "Jouer en WQHD (1440p) à 60 fps et plus NVIDIA GeForce RTX 5070 Ti"
                # → on tente d'extraire le nom du composant depuis le texte
                if _starts_with_marketing(exact_ref):
                    extracted = _extract_component_name(exact_ref)
                    if extracted:
                        exact_ref = extracted
                    else:
                        break  # Texte 100% marketing, ignorer ce <li>

                # Cas 2 : le texte CONTIENT des mots marketing non liés à un composant
                # ex: "Large capacité de stockage pour vos jeux"
                elif _is_marketing_text(exact_ref):
                    break  # Ignorer ce <li>, laisser l'IA estimer

                # Cas 3 : tronquer les suffixes marketing
                # ex: "Intel Core Ultra 9 285K pour le jeu et le stream watercooling…"
                # → "Intel Core Ultra 9 285K"
                else:
                    exact_ref = _truncate_at_marketing(exact_ref)
                    if not exact_ref:
                        break
                # ───────────────────────────────────────────────────────────────
                refs[component] = exact_ref
                break

    return refs


def _extract_components(pairs: dict[str, str]) -> dict:
    components = {key: None for key in COMPONENT_LABELS}

    for component, keywords in COMPONENT_LABELS.items():
        blacklist = BLACKLIST_LABELS.get(component, [])

        for kw in keywords:
            if kw in pairs and kw not in blacklist:
                components[component] = pairs[kw]
                break

        # Combiner avec un label secondaire si disponible
        if components[component]:
            for sec_kw in SECONDARY_LABELS.get(component, []):
                if sec_kw in pairs:
                    components[component] = f"{components[component]} {pairs[sec_kw]}"
                    break

    return components


def extract_product_info(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # Nom du produit
    name_tag = soup.select_one("h1.title-1") or soup.select_one("h1")
    product_name = name_tag.get_text(strip=True) if name_tag else "Nom introuvable"

    # Prix — LDLC format : "739€95"
    product_price = None
    price_tag = soup.select_one(".price")
    if price_tag:
        raw = price_tag.get_text(strip=True).replace("\xa0", "").replace(" ", "")
        match = re.search(r"(\d+)[€,.](\d{2})", raw)
        if match:
            product_price = float(f"{match.group(1)}.{match.group(2)}")

    # Image
    img_tag = soup.select_one(".picture-product img") or soup.select_one("img.product")
    product_image = img_tag.get("src") if img_tag else None

    # Specs structurées (tableau) + références exactes (description)
    pairs = _parse_specs_table(soup)
    components = _extract_components(pairs)

    # Valider la carte mère extraite du tableau : le label "chipset" peut désigner
    # un chipset réseau (ex: "Wi-Fi 6E LAN à 2.5 Gigabits") et non le chipset mobo.
    # On ne garde la valeur que si elle ressemble à un vrai chipset ou à une marque mobo.
    if components.get("motherboard"):
        mobo_raw = components["motherboard"]
        mobo_low = mobo_raw.lower()
        _VALID_CHIPSET_RE  = re.compile(r'\b[abxhz][45678][0-9][0-9][a-z]?\b', re.I)
        _MOBO_BRANDS       = ["asus", "msi", "gigabyte", "asrock", "evga", "nzxt", "biostar"]
        _NETWORK_KEYWORDS  = ["wi-fi", "wifi", "lan", "gigabit", "ethernet", "bluetooth",
                               "réseau", "network", "wireless"]
        has_chipset  = bool(_VALID_CHIPSET_RE.search(mobo_low))
        has_brand    = any(b in mobo_low for b in _MOBO_BRANDS)
        has_network  = any(kw in mobo_low for kw in _NETWORK_KEYWORDS)
        if has_network and not has_chipset and not has_brand:
            # Spec réseau parasitée — ignorer pour laisser la description prendre la main
            components["motherboard"] = None

    desc_refs = _parse_description_refs(soup)

    # Les références de la description sont prioritaires sur les valeurs
    # génériques du tableau (ex : "Moyen Tour" → "Zalman i3 Neo V2 Black")
    for component, ref in desc_refs.items():
        if ref:
            components[component] = ref

    # Validation finale de la carte mère : rejeter les valeurs qui ressemblent
    # à des specs réseau (Wi-Fi, LAN…) et non à un vrai chipset/modèle de carte mère.
    # S'applique APRÈS fusion desc_refs pour couvrir les deux sources.
    if components.get("motherboard"):
        mobo_raw = components["motherboard"]
        mobo_low = mobo_raw.lower()
        _VALID_CHIPSET_RE  = re.compile(r'\b[abxhz][45678][0-9][0-9][a-z]?\b', re.I)
        _MOBO_BRANDS_FINAL = ["asus", "msi", "gigabyte", "asrock", "evga", "nzxt", "biostar"]
        _NETWORK_KW_FINAL  = ["wi-fi", "wifi", "lan", "gigabit", "ethernet", "bluetooth",
                               "réseau", "network", "wireless", "2.5 giga"]
        _has_chipset  = bool(_VALID_CHIPSET_RE.search(mobo_low))
        _has_brand    = any(b in mobo_low for b in _MOBO_BRANDS_FINAL)
        _has_network  = any(kw in mobo_low for kw in _NETWORK_KW_FINAL)
        if _has_network and not _has_chipset and not _has_brand:
            components["motherboard"] = None  # Spec réseau parasite, pas un modèle mobo

    # ── Post-traitement RAM ──────────────────────────────────────────────────
    # Si la RAM n'a pas de type DDR (ex: "16 Go de RAM", "16 Go"),
    # on l'enrichit avec le type + fréquence du tableau de specs.
    if components.get("ram"):
        ram_val = components["ram"]
        if not re.search(r"ddr[345]", ram_val, re.I):
            ddr_type  = pairs.get("type de mémoire", "")             # "DDR5"
            freq_raw  = pairs.get("fréquence(s) mémoire", "")        # "DDR5 5600 MHz"
            freq_m    = re.search(r"(\d{3,5})\s*mhz", freq_raw, re.I)
            cap_m     = re.search(r"(\d+)\s*go", ram_val, re.I)
            if ddr_type and cap_m:
                freq_str = f" {freq_m.group(1)}MHz" if freq_m else ""
                components["ram"] = f"{cap_m.group(1)} Go {ddr_type}{freq_str}"

    # ── Post-traitement SSD ──────────────────────────────────────────────────
    # Si le SSD ne contient pas l'info PCIe, on l'ajoute depuis le tableau.
    for ssd_key in ("ssd", "ssd2"):
        if components.get(ssd_key):
            ssd_val = components[ssd_key]
            if "nvme" in ssd_val.lower() and "pcie" not in ssd_val.lower() and "pci" not in ssd_val.lower():
                iface = pairs.get("interface avec l'ordinateur disque dur système", "")
                pcie_m = re.search(r"pci[- ]?e\s*(\d+\.\d+)", iface, re.I)
                if pcie_m:
                    components[ssd_key] = re.sub(
                        r"(nvme)", rf"\1 PCIe {pcie_m.group(1)}", ssd_val, flags=re.I, count=1
                    )

    # ── Post-traitement CPU ──────────────────────────────────────────────────
    # Si le CPU vient du tableau (ex: "Intel Core Ultra 5 4.2 GHz") et manque
    # le modèle complet, on essaie de récupérer le numéro depuis le tableau.
    if components.get("cpu"):
        cpu_val = components["cpu"]
        # Si le modèle CPU ne contient pas de numéro (ex: "Intel Core Ultra 5")
        if not re.search(r"\d{3,5}[a-z]*", cpu_val, re.I):
            # Chercher dans les specs le champ "modèle" ou le nom complet
            for k in ("processeur", "processor", "cpu"):
                if k in pairs and re.search(r"\d{3,5}", pairs[k]):
                    components["cpu"] = pairs[k]
                    break

    # Double SSD (ex: "SSD 1 To + SDD 2 To NVMe M.2") → sépare en ssd + ssd2
    if components.get("ssd") and re.search(r"\+|( et )", components["ssd"], re.I):
        parts = re.split(r"\s*\+\s*|\s+et\s+", components["ssd"], maxsplit=1)
        components["ssd"]  = parts[0].strip()
        components["ssd2"] = parts[1].strip() if len(parts) > 1 else None
    else:
        components["ssd2"] = None

    return {
        "product_name": product_name,
        "product_price": product_price,
        "product_image": product_image,
        "components": components,
    }


async def scrape_ldlc_product(url: str) -> dict:
    if not validate_ldlc_url(url):
        return {"error": "URL invalide : seuls les liens LDLC sont acceptés."}

    print(f"Scraping : {url}")
    html = await fetch_page_html(url)
    return extract_product_info(html)


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://www.ldlc.com/fiche/PB00684984.html"
    )

    data = asyncio.run(scrape_ldlc_product(url))
    print(json.dumps(data, indent=2, ensure_ascii=False))
