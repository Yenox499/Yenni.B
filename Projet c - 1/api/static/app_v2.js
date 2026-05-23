/* ═══════════════════════════════════════════════════════
   B.pc — app.js
═══════════════════════════════════════════════════════ */

const COMPONENT_NAMES = {
  cpu:         "CPU",
  gpu:         "GPU",
  ram:         "RAM",
  ssd:         "SSD 1",
  ssd2:        "SSD 2",
  motherboard: "Carte mère",
  case:        "Boîtier",
  cooler:      "Refroidisseur",
  psu:         "Alimentation",
};

const STATUS_CFG = {
  found:    { label: "trouvé",  cls: "tag-found"     },
  refined:  { label: "affiné",  cls: "tag-refined"   },
  estimated:{ label: "estimé",  cls: "tag-estimated" },
  generic:  { label: "affiné",  cls: "tag-refined"   },
};

/* ── DOM ── */
const form        = document.getElementById("form");
const urlInput    = document.getElementById("url-input");
const urlRow      = document.querySelector(".input-field-wrap");
const urlIcon     = document.getElementById("url-icon");
const helperText  = document.getElementById("helper-text");
const submitBtn   = document.getElementById("submit-btn");
const errorMsg    = document.getElementById("error-msg");
const heroSection = document.getElementById("hero-section");
const loadingSect = document.getElementById("loading");
const resultsSect = document.getElementById("results");

/* ════════════════════════════════════════
   1. VALIDATION URL LIVE
════════════════════════════════════════ */

function validateLDLC(raw) {
  const url = raw.trim();
  if (!url) return { status: "idle", hint: "Collez l'URL d'un PC en ligne pour démarrer l'analyse", hintCls: "hint-idle" };

  let parsed;
  try {
    const candidate = /^https?:\/\//i.test(url) ? url : "https://" + url;
    parsed = new URL(candidate);
  } catch {
    return { status: "invalid", hint: "URL invalide · format attendu : https://www.ldlc.com/fiche/PB00XXXXXX.html", hintCls: "hint-invalid" };
  }

  const host = parsed.hostname.toLowerCase();
  if (host !== "ldlc.com" && host !== "www.ldlc.com")
    return { status: "invalid", hint: `Ce marchand n'est pas encore pris en charge : « ${host} »`, hintCls: "hint-invalid" };

  if (!/\/fiche\//i.test(parsed.pathname))
    return { status: "invalid", hint: "Lien invalide · doit pointer vers une fiche produit", hintCls: "hint-invalid" };

  return { status: "valid", hint: "Produit reconnu · prêt à lancer l'analyse", hintCls: "hint-valid" };
}

function applyValidation(v) {
  urlRow.classList.remove("is-valid", "is-invalid");
  helperText.className   = v.hintCls;
  helperText.textContent = v.hint;

  if (v.status === "valid") {
    urlRow.classList.add("is-valid");
    urlIcon.innerHTML = iconSVG("check");
    submitBtn.disabled = false;
  } else if (v.status === "invalid") {
    urlRow.classList.add("is-invalid");
    urlIcon.innerHTML = iconSVG("cross");
    submitBtn.disabled = true;
  } else {
    urlIcon.innerHTML = "";
    submitBtn.disabled = true;
  }
}

function iconSVG(kind) {
  const path = kind === "check"
    ? `<path d="M3 8.5l3.5 3.5L13 5"/>`
    : `<path d="M4 4l8 8M12 4l-8 8"/>`;
  return `<span class="status-icon status-${kind === "check" ? "valid" : "invalid"}">
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="#fff"
         stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${path}</svg>
  </span>`;
}

urlInput.addEventListener("input", () => applyValidation(validateLDLC(urlInput.value)));
applyValidation(validateLDLC(""));

/* ════════════════════════════════════════
   2. PROGRESS BAR SIMULÉE
════════════════════════════════════════ */

let progressRaf   = null;
let progressStart = 0;
const ESTIMATED_MS = 80_000;

function startProgress() {
  progressStart = performance.now();
  const fill  = document.getElementById("progress-fill");
  const pct   = document.getElementById("prog-pct");
  const label = document.getElementById("prog-label");
  const timer = document.getElementById("loading-timer");

  function tick(now) {
    const elapsed = now - progressStart;
    const raw     = Math.min(0.88, elapsed / ESTIMATED_MS);
    const display = Math.round(raw * 100);
    fill.style.width = display + "%";
    pct.textContent  = display + "%";

    const remaining = Math.max(0, Math.ceil((ESTIMATED_MS - elapsed) / 1000));
    timer.textContent = remaining > 5
      ? `Estimation : ${remaining} seconde${remaining > 1 ? "s" : ""} restante${remaining > 1 ? "s" : ""}`
      : "Finalisation de l'analyse…";

    const found = Math.min(9, Math.floor(raw * 10.5));
    label.textContent = `${found} composant${found > 1 ? "s" : ""} analysé${found > 1 ? "s" : ""}`;

    if (raw < 0.88) progressRaf = requestAnimationFrame(tick);
  }
  progressRaf = requestAnimationFrame(tick);
}

function finishProgress() {
  cancelAnimationFrame(progressRaf);
  document.getElementById("progress-fill").style.width = "100%";
  document.getElementById("prog-pct").textContent      = "100%";
  document.getElementById("prog-label").textContent    = "9 composants analysés";
}

/* ════════════════════════════════════════
   3. LOADING STEPS
════════════════════════════════════════ */

let stepTimers = [];

function activateStep(n) {
  for (let i = 1; i <= 3; i++) {
    const el = document.getElementById(`step-${i}`);
    if (el) el.classList.toggle("active", i === n);
  }
}

function startSteps() {
  activateStep(1);
  stepTimers.push(setTimeout(() => activateStep(2), 6_000));
  stepTimers.push(setTimeout(() => activateStep(3), 18_000));
}

function clearSteps() {
  stepTimers.forEach(clearTimeout);
  stepTimers = [];
}

/* ════════════════════════════════════════
   4. NAVIGATION
════════════════════════════════════════ */

function showLoading() {
  heroSection.classList.add("hidden");
  loadingSect.classList.remove("hidden");
  resultsSect.classList.add("hidden");
  startProgress();
  startSteps();
}

function showResults(data) {
  finishProgress();
  clearSteps();
  loadingSect.classList.add("hidden");
  resultsSect.classList.remove("hidden");
  renderResults(data);
  resultsSect.scrollIntoView({ behavior: "smooth", block: "start" });
}

function clearError() {
  errorMsg.textContent = "";
  errorMsg.classList.add("hidden");
}
function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.remove("hidden");
}

/* ════════════════════════════════════════
   5. SUBMIT
════════════════════════════════════════ */

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearError();
  const url = urlInput.value.trim();
  if (!url) return;

  submitBtn.disabled = true;
  showLoading();

  try {
    const res = await fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Erreur serveur ${res.status}`);
    }
    const data = await res.json();
    showResults(data);
  } catch (err) {
    finishProgress();
    clearSteps();
    loadingSect.classList.add("hidden");
    heroSection.classList.remove("hidden");
    showError(err.message || "Une erreur est survenue. Vérifiez l'URL et réessayez.");
  } finally {
    submitBtn.disabled = false;
  }
});

/* ════════════════════════════════════════
   6. COUNT-UP ANIMATION
════════════════════════════════════════ */

function countUp(el, target, duration = 1100) {
  const start = performance.now();
  const sign  = target < 0 ? -1 : 1;
  const abs   = Math.abs(target);
  function tick(now) {
    const p     = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - p, 3);
    const val   = sign * Math.round(abs * eased);
    el.textContent = fmtInt(val) + " €";
    if (p < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

/* ════════════════════════════════════════
   7. FORMATTERS
════════════════════════════════════════ */

function fmtInt(n) {
  return new Intl.NumberFormat("fr-FR").format(Math.round(n));
}

function fmt(price) {
  if (price == null || price === 0) return "—";
  return new Intl.NumberFormat("fr-FR", {
    style: "currency", currency: "EUR", maximumFractionDigits: 0,
  }).format(price);
}

function fmtFull(price) {
  if (price == null) return "—";
  return new Intl.NumberFormat("fr-FR", {
    style: "currency", currency: "EUR",
  }).format(price);
}

/* ════════════════════════════════════════
   8. RENDER RESULTS
════════════════════════════════════════ */

function renderResults(data) {
  const verdict    = data.verdict           || {};
  const analysis   = data.pc_analysis      || {};
  const components = data.detail_composants || {};
  const ldlcPrice  = data.product_price     || 0;
  const diff       = verdict.difference_euros ?? 0;
  const isSavings  = diff > 0;

  // Bandeau erreur SerpAPI (quota épuisé)
  let warningBanner = document.getElementById("serpapi-warning");
  if (data.serpapi_error) {
    if (!warningBanner) {
      warningBanner = document.createElement("div");
      warningBanner.id = "serpapi-warning";
      warningBanner.style.cssText = "background:#fff3cd;border:1px solid #ffc107;color:#856404;padding:12px 18px;border-radius:8px;margin-bottom:20px;font-size:0.9rem;";
      resultsSect.prepend(warningBanner);
    }
    warningBanner.innerHTML = `⚠️ <strong>Quota SerpAPI épuisé</strong> — les prix des composants ne sont pas disponibles pour l'instant. L'analyse des composants reste valide. Rechargez votre quota sur <a href="https://serpapi.com" target="_blank">serpapi.com</a>.`;
    warningBanner.style.display = "block";
  } else if (warningBanner) {
    warningBanner.style.display = "none";
  }

  document.getElementById("pc-name").textContent = data.product_name || "PC";

  const usageEl = document.getElementById("pc-usage");
  const tierEl  = document.getElementById("pc-tier");
  usageEl.textContent = analysis.usage || "";
  tierEl.textContent  = analysis.tier  || "";
  usageEl.classList.toggle("hidden", !analysis.usage);
  tierEl.classList.toggle("hidden",  !analysis.tier);

  document.getElementById("pc-price").textContent = ldlcPrice ? fmtFull(ldlcPrice) : "—";

  const total = renderComponents(components);

  const tf = fmt(total);
  document.getElementById("total-prix").textContent      = tf;
  document.getElementById("total-prix-foot").textContent = tf;

  renderEconomyHero(diff, isSavings, ldlcPrice, total);

  document.getElementById("cmp-pc").textContent     = ldlcPrice ? fmtFull(ldlcPrice) : "—";
  document.getElementById("cmp-pieces").textContent = fmt(total);
  const econEl = document.getElementById("cmp-economie");
  if (diff > 0)      { econEl.textContent = fmt(diff) + " de moins";          econEl.style.color = "var(--green-2)"; }
  else if (diff < 0) { econEl.textContent = fmt(Math.abs(diff)) + " de plus"; econEl.style.color = "var(--red-2)"; }
  else               { econEl.textContent = "Équivalent";                     econEl.style.color = "var(--muted)"; }

  renderVerdictPanel(verdict, diff, isSavings);
}

function renderEconomyHero(diff, isSavings, ldlcPrice, piecesTotal) {
  const panel   = document.getElementById("economy-hero");
  const numEl   = document.getElementById("economy-number");
  const eyebrow = document.getElementById("economy-eyebrow");
  const vtag    = document.getElementById("verdict-label");
  const veco    = document.getElementById("verdict-economy");
  const vsub    = document.getElementById("verdict-sub");

  panel.classList.remove("is-savings", "no-savings");
  panel.classList.add(isSavings ? "is-savings" : "no-savings");

  eyebrow.textContent = isSavings ? "Économie possible" : "Le PC prémonté est moins cher";

  countUp(numEl, isSavings ? diff : -Math.abs(diff), 1100);

  vtag.className = "verdict-tag";
  const vLabel = diff > 400 ? "DEAL OF THE LIFE" : diff > 200 ? "BIG DEAL" : diff > 0 ? "BON DEAL" : "PAS UN DEAL";
  const vtMap = {
    "BON DEAL":         { cls: "vt-bon",  lbl: "Bon Deal"         },
    "BIG DEAL":         { cls: "vt-big",  lbl: "Big Deal"         },
    "DEAL OF THE LIFE": { cls: "vt-life", lbl: "Deal of the Life" },
    "PAS UN DEAL":      { cls: "vt-none", lbl: "Pas un Deal"      },
  };
  const vt = vtMap[vLabel] || vtMap["PAS UN DEAL"];
  vtag.classList.add(vt.cls);
  vtag.textContent = vt.lbl;

  veco.textContent = isSavings
    ? `Économie de ${fmt(diff)}`
    : `Surcoût de ${fmt(Math.abs(diff))}`;
  vsub.textContent = isSavings
    ? `Monter ce PC pièce par pièce te ferait gagner ${fmt(diff)} par rapport au prix LDLC.`
    : `Sur ce modèle, LDLC propose un meilleur tarif que l'achat des composants séparément.`;

  document.getElementById("econ-ldlc").textContent   = ldlcPrice ? fmtFull(ldlcPrice) : "—";
  document.getElementById("econ-pieces").textContent = fmt(piecesTotal);
}

function renderComponents(components) {
  const tbody = document.getElementById("components-body");
  tbody.innerHTML = "";
  let total = 0;

  for (const [key, data] of Object.entries(components)) {
    const name   = COMPONENT_NAMES[key] || key;
    const nom    = data.nom    || "—";
    const statut = data.statut || "estimated";
    const prix   = data.prix_retenu || 0;
    const site   = data.site   || "";
    const lien   = data.lien   || "";

    if (prix) total += prix;

    const cfg      = STATUS_CFG[statut] || { label: statut, cls: "" };
    const priceCls = prix === 0 ? "p-none"
      : (statut === "estimated" || statut === "generic") ? "p-estimated"
      : "p-found";

    const priceHTML    = `<span class="dt-price ${priceCls} dt-right serif">${prix ? fmt(prix) : "—"}</span>`;
    const merchantHTML = site ? `<span class="dt-merchant">${site}</span>` : `<span class="dt-unavail">—</span>`;
    const linkHTML     = lien ? `<a class="dt-link-btn" href="${lien}" target="_blank" rel="noopener">voir →</a>` : `<span class="dt-unavail">—</span>`;

    tbody.innerHTML += `
      <div class="dt-row">
        <span class="dt-comp">${name}</span>
        <span class="dt-ref">${nom}</span>
        <span><span class="tag ${cfg.cls}">${cfg.label}</span></span>
        ${priceHTML}
        ${merchantHTML}
        <span class="dt-right">${linkHTML}</span>
      </div>`;
  }
  return total;
}

function renderVerdictPanel(verdict, diff, isSavings) {
  const panel = document.getElementById("verdict-card");
  const label = document.getElementById("verdict-card-label");
  const eco   = document.getElementById("verdict-card-eco");
  const sub   = document.getElementById("verdict-card-sub");
  const v     = verdict.verdict_label;

  panel.className = "verdict-panel serif";

  const cfg = {
    "BON DEAL":         { cls: "bon-deal",  lbl: "bon deal",         color: "var(--green-2)"  },
    "BIG DEAL":         { cls: "big-deal",  lbl: "big deal",         color: "var(--orange-2)" },
    "DEAL OF THE LIFE": { cls: "deal-life", lbl: "deal of the life", color: "var(--blue-2)"   },
  };
  const c = cfg[v] || { cls: "pas-deal", lbl: "pas un deal", color: "var(--red-2)" };

  panel.classList.add(c.cls);
  label.textContent = c.lbl;
  eco.textContent   = isSavings ? `Économie de ${fmt(diff)}` : `Surcoût de ${fmt(Math.abs(diff))}`;
  eco.style.color   = c.color;
  sub.textContent   = verdict.verdict_sub || "";
}

/* ════════════════════════════════════════
   9. DEMO DATA
════════════════════════════════════════ */

const DEMO_DATA = {
  product_name: "PC Gamer LDLC PC10 Ryzen 5 — RTX 4070 Super",
  product_price: 1899,
  pc_analysis: { usage: "gaming", tier: "milieu de gamme +" },
  verdict: {
    verdict_label: "BIG DEAL",
    verdict_sub: "Monter ce PC pièce par pièce te ferait gagner près de 13 % par rapport au tarif LDLC.",
    difference_euros: 247,
  },
  detail_composants: {
    cpu:         { nom: "Intel Core i5-13600KF",          statut: "found",     prix_retenu: 289, site: "topachat.com", lien: "https://www.topachat.com/" },
    gpu:         { nom: "NVIDIA RTX 4070 Super 12 Go",    statut: "found",     prix_retenu: 619, site: "ldlc.com",     lien: "https://www.ldlc.com/" },
    ram:         { nom: "Corsair Vengeance 32 Go DDR5",   statut: "refined",   prix_retenu: 124, site: "materiel.net", lien: "https://www.materiel.net/" },
    ssd:         { nom: "Samsung 990 Pro 1 To NVMe",      statut: "found",     prix_retenu:  79, site: "amazon.fr",    lien: "https://www.amazon.fr/" },
    motherboard: { nom: "ASUS TUF Gaming B760-Plus WiFi", statut: "refined",   prix_retenu: 189, site: "topachat.com", lien: "https://www.topachat.com/" },
    psu:         { nom: "Corsair RM750e 750W 80+ Gold",   statut: "refined",   prix_retenu: 109, site: "topachat.com", lien: "https://www.topachat.com/" },
    case:        { nom: "NZXT H5 Flow ATX",               statut: "estimated", prix_retenu:  89, site: "ldlc.com",     lien: "https://www.ldlc.com/" },
    cooler:      { nom: "be quiet! Pure Rock 2",          statut: "found",     prix_retenu:  39, site: "materiel.net", lien: "https://www.materiel.net/" },
    ssd2:        { nom: "Crucial P3 Plus 2 To NVMe",      statut: "estimated", prix_retenu: 115, site: "amazon.fr",    lien: "https://www.amazon.fr/" },
  },
};

/* ════════════════════════════════════════
   10. DEMO + RESET
════════════════════════════════════════ */

function showDemo() {
  clearError();
  heroSection.classList.add("hidden");
  loadingSect.classList.add("hidden");
  resultsSect.classList.remove("hidden");
  renderResults(DEMO_DATA);
  document.getElementById("progress-fill").style.width = "100%";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function resetForm() {
  cancelAnimationFrame(progressRaf);
  clearSteps();
  resultsSect.classList.add("hidden");
  loadingSect.classList.add("hidden");
  heroSection.classList.remove("hidden");
  clearError();
  urlInput.value = "";
  applyValidation(validateLDLC(""));
  window.scrollTo({ top: 0, behavior: "smooth" });
}
