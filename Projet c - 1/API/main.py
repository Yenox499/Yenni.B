import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor

from scraper.ldlc_scraper import scrape_ldlc_product, validate_ldlc_url
from ai.component_analyzer import enrich_components
from search.partie2_recherche_prix import lancer_partie2

app = FastAPI(title="PC Deal Comparator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=4)


class AnalyzeRequest(BaseModel):
    url: str


def _run_pipeline(scraped: dict) -> dict:
    """Exécute les étapes IA + recherche prix (appelé dans un thread)."""
    enriched = enrich_components(scraped)
    return lancer_partie2(enriched)


@app.post("/analyze")
async def analyze(request: AnalyzeRequest):
    url = request.url.strip()

    if not validate_ldlc_url(url):
        raise HTTPException(status_code=400, detail="URL invalide : seuls les liens LDLC sont acceptés.")

    # Étape 1 : Scraping Playwright (async natif) — timeout 45s
    try:
        scraped = await asyncio.wait_for(scrape_ldlc_product(url), timeout=45.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Le chargement de la page LDLC a pris trop de temps. Réessayez.")

    if "error" in scraped:
        raise HTTPException(status_code=400, detail=scraped["error"])

    # Étapes 2 & 3 : IA Groq + recherches Serper (synchrones → thread pool) — timeout 90s
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(executor, _run_pipeline, scraped),
            timeout=90.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=503,
            detail="L'analyse a pris trop de temps. Le service IA est peut-être surchargé — réessayez dans 30 secondes.",
        )
    except Exception as e:
        err = str(e)
        err_low = err.lower()
        # Erreurs Groq API (403, quota, accès) → ne jamais exposer le message brut
        if any(x in err_low for x in ["403", "access denied", "permission", "quota", "épuisé", "réessayez", "rate limit", "429"]):
            raise HTTPException(
                status_code=503,
                detail="Le moteur d'analyse est temporairement indisponible. Réessayez dans quelques secondes.",
            )
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'analyse : {err}")

    return result


# Servir le frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index_v2.html"))
