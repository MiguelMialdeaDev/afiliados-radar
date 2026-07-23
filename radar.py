# -*- coding: utf-8 -*-
"""Radar de nichos de afiliación — Nivel 1 (gratis, fiable).

Puntúa nichos por lo que SÍ se puede saber sin APIs frágiles ni de pago:
  - ECONOMÍA: comisión Amazon (por categoría) × ticket medio = € por venta.
  - INTENCIÓN de compra: heurística sobre la keyword.

NO incluye demanda/tendencia/competencia: eso es la capa de pago barata
(Nivel 2, DataForSEO ~0,05$/consulta) sobre los finalistas. Este Nivel 1 hace el
primer cribado: descarta nichos donde el € por venta o la intención no compensan.

Uso:  python radar.py     -> escribe radar.html (local) y radar_artifact.html
"""
import csv
import html
import math
import os
import re
import urllib.parse
from pathlib import Path

import dataforseo

BASE = Path(__file__).parent

# Carga .env (DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD / DATAFORSEO_MOCK) sin deps.
_env = BASE / ".env"
if _env.exists():
    for _ln in _env.read_text(encoding="utf-8").splitlines():
        _ln = _ln.strip()
        if _ln and not _ln.startswith("#") and "=" in _ln:
            _k, _v = _ln.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# Comisiones Amazon Afiliados España, % ESTIMADO por categoría (2025-26).
# EDITABLE: verifica las tarifas oficiales, cambian. Bajaron mucho.
COMISIONES = {
    "moda": 10.0, "belleza": 10.0, "lujo_belleza": 10.0,
    "hogar": 3.0, "cocina": 4.0, "jardin": 3.0,
    "electronica": 3.0, "informatica": 2.5, "videojuegos": 2.5,
    "deportes": 3.0, "juguetes": 3.0, "salud": 4.0, "bebe": 3.0,
    "herramientas": 3.0, "muebles": 3.0, "libros": 5.0,
    "alimentacion": 3.0, "mascotas": 4.0, "equipaje": 4.0,
}

INTENT_HIGH = {"mejor", "mejores", "comprar", "opiniones", "review", "precio",
               "barato", "barata", "comparativa", "oferta", "ofertas"}
INTENT_LOW = {"como", "cómo", "que", "qué", "para", "gratis", "casero",
              "casera", "diy", "significa", "sirve"}


def intent_label(nicho: str) -> tuple[str, int]:
    words = set(re.findall(r"[a-záéíóúñ]+", nicho.lower()))
    if words & INTENT_HIGH:
        return "Alta", 40
    if words & INTENT_LOW:
        return "Baja", 12
    return "Media", 26  # nombre de producto a secas = intención de compra media


def euro_por_venta(categoria: str, ticket: float) -> tuple[float, float]:
    com = COMISIONES.get(categoria.strip().lower(), 3.0)
    return com, round(com / 100.0 * ticket, 2)


def _verd(total: int) -> str:
    return "Fuerte" if total >= 65 else "Revisar" if total >= 45 else "Flojo"


def score(euro: float, intent_pts: int) -> tuple[int, str]:
    """Nivel 1 (gratis, sin demanda): €/venta (60, satura a 15€) + intención (40).
    Satura a 15€ para repartir bien en un catálogo con tickets muy dispares."""
    total = round(min(euro / 15.0, 1.0) * 60 + intent_pts)
    return total, _verd(total)


INTENT_N2 = {"Alta": 15, "Media": 10, "Baja": 4}


def score2(euro: float, intent_label: str, volume: int, rank_pts=None) -> tuple[int, str]:
    """Nivel 2: €/venta + demanda + intención (+ rankeabilidad si hay SERP).

    La rankeabilidad viene de la PÁGINA 1 REAL de Google (classify_serp), que SÍ
    es fiable en español — a diferencia del KD de DataForSEO Labs, que se descartó.
    Sin SERP, se reparte su peso entre €/venta y demanda.
    """
    intent_pts = INTENT_N2.get(intent_label, 10)
    if rank_pts is not None:
        euro_pts = min(euro / 15.0, 1.0) * 35
        demand_pts = min(math.log10(volume + 1) / 5.0, 1.0) * 30
        total = round(max(0.0, min(100.0, euro_pts + demand_pts + rank_pts + intent_pts)))
    else:
        euro_pts = min(euro / 15.0, 1.0) * 45
        demand_pts = min(math.log10(volume + 1) / 5.0, 1.0) * 40
        total = round(max(0.0, min(100.0, euro_pts + demand_pts + intent_pts)))
    return total, _verd(total)


# € potenciales/mes = techo optimista si rankeas bien. Supuestos conservadores,
# editables: capturas ~4% de las búsquedas del término y ~3% compra en Amazon.
CAPTURE = 0.04
CONVERSION = 0.03


def potencial_mes(volume: int, euro: float) -> float:
    return volume * CAPTURE * CONVERSION * euro


# Grandes dominios que una web nueva de afiliación NO puede desbancar (retailers,
# marketplaces y medios con autoridad). EDITABLE: añade los que veas repetirse.
# Si la página 1 está llena de estos, el nicho es difícil; si asoman webs nicho
# pequeñas, hay hueco. Se comprueba por "contiene" (amazon. cubre amazon.es/.com).
BIG_DOMAINS = [
    "amazon.", "elcorteingles.", "pccomponentes.", "mediamarkt.", "carrefour.",
    "worten.", "fnac.", "leroymerlin.", "decathlon.", "aliexpress.", "ebay.",
    "ikea.", "conforama.", "miravia.", "idealo.", "kelkoo.", "milanuncios.",
    "xataka.", "elpais.", "elmundo.", "20minutos.", "lavanguardia.", "abc.",
    "elindependiente.", "elespanol.", "larazon.", "businessinsider.", "ocu.org",
    "computerhoy.", "hola.", "marca.", "as.com", "elconfidencial.", "wikipedia.",
    "youtube.", "reddit.", "google.",
]


def _is_big(domain: str) -> bool:
    d = (domain or "").lower()
    return any(b in d for b in BIG_DOMAINS)


def classify_serp(domains: list[str], ai_overview: bool) -> tuple[str, int, int]:
    """De la página 1 real -> (etiqueta, nº grandes, puntos de rankeabilidad 0-25).

    Cuantas menos webs pequeñas (nichables) haya en el top 10, más difícil entrar.
    Un AI Overview resta (Google responde sin clic → menos tráfico aunque rankees).
    """
    if not domains:
        return "s/d", 0, 12  # sin dato -> neutro, no penaliza ni premia
    big = sum(1 for d in domains if _is_big(d))
    small = len(domains) - big
    frac_small = small / len(domains)
    pts = round(frac_small * 25)
    if ai_overview:
        pts = max(0, pts - 6)
    if small >= 4 and not ai_overview:
        lab = "Accesible"
    elif small >= 2:
        lab = "Media"
    else:
        lab = "Difícil"
    if ai_overview:
        lab += " · AIO"
    return lab, big, pts


def _sparkline(monthly: list[int], color: str) -> str:
    """SVG mínimo de 12 puntos (tendencia visual honesta, sin inventar un número)."""
    if not monthly:
        return ""
    w, h = 68, 20
    lo, hi = min(monthly), max(monthly)
    rng = (hi - lo) or 1
    pts = []
    for i, v in enumerate(monthly):
        x = round(i / (len(monthly) - 1) * (w - 2) + 1, 1)
        y = round(h - 2 - (v - lo) / rng * (h - 4), 1)
        pts.append(f"{x},{y}")
    return (f"<svg viewBox='0 0 {w} {h}' width='{w}' height='{h}' preserveAspectRatio='none' "
            f"aria-hidden='true'><polyline points='{' '.join(pts)}' fill='none' "
            f"stroke='{color}' stroke-width='1.5' stroke-linejoin='round' stroke-linecap='round'/></svg>")


def _rows():
    raw = []
    with (BASE / "nichos.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            raw.append((r["nicho"].strip(), r["categoria"].strip(), float(r["ticket_estimado"])))

    # Nivel 2 (demanda + SERP de DataForSEO) SOLO si se pide explícitamente con
    # DATAFORSEO_ENABLE=1 y hay credenciales/saldo. Por defecto = Nivel 1 GRATIS,
    # sin llamadas a la API (así la web no depende de saldo ni falla con 402).
    mode = dataforseo.available() if os.environ.get("DATAFORSEO_ENABLE") == "1" else ""
    demand, serps = {}, {}
    if mode:
        try:
            demand = dataforseo.search_volume([n for n, _, _ in raw])
            for nicho, _, _ in raw:
                # Consultamos la SERP del término con intención comercial ("mejor X").
                serps[nicho] = dataforseo.serp_top(f"mejor {nicho}")
        except Exception as e:
            print(f"aviso: Nivel 2 no disponible ({type(e).__name__}: {str(e)[:80]}) -> Nivel 1")
            mode = ""

    out = []
    for nicho, cat, ticket in raw:
        com, euro = euro_por_venta(cat, ticket)
        ilabel, ipts = intent_label(nicho)
        d = demand.get(nicho)
        if d:
            s = serps.get(nicho) or {"domains": [], "ai_overview": False}
            rank_lab, big, rank_pts = classify_serp(s["domains"], s["ai_overview"])
            sc, verd = score2(euro, ilabel, d["volume"], rank_pts)
            vol, cpc = d["volume"], d["cpc"]
            monthly, peak = d.get("monthly") or [], d.get("peak") or ""
            pot = potencial_mes(vol, euro)
            aio = s["ai_overview"]
        else:
            sc, verd = score(euro, ipts)
            vol, cpc, monthly, peak, pot = None, None, [], "", None
            rank_lab, big, aio = "", 0, False
        out.append(dict(nicho=nicho, cat=cat, com=com, ticket=ticket, euro=euro,
                        intent=ilabel, score=sc, verd=verd, vol=vol, cpc=cpc,
                        monthly=monthly, peak=peak, pot=pot,
                        rank=rank_lab, big=big, aio=aio))
    out.sort(key=lambda x: x["score"], reverse=True)
    return out, mode


CSS = """
:root{
  --bg:#eef1f5; --panel:#ffffff; --line:#dfe4ec; --ink:#1b2230; --dim:#69727f;
  --accent:#4f63e0; --accent-soft:#eef0fd;
  --good:#1f9d57; --good-bg:#e6f5ec; --warn:#c1841a; --warn-bg:#faf1dd; --bad:#d34a4a; --bad-bg:#fbe9e9;
  --bar-track:#e7ebf1;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0e1218; --panel:#161c25; --line:#26303c; --ink:#e6ebf2; --dim:#8a95a4;
  --accent:#7d8ff2; --accent-soft:#1c2440;
  --good:#4cc585; --good-bg:#12321f; --warn:#e0a63e; --warn-bg:#33280f; --bad:#ef6b6b; --bad-bg:#3a1a1a;
  --bar-track:#232c38;
}}
:root[data-theme="light"]{
  --bg:#eef1f5; --panel:#fff; --line:#dfe4ec; --ink:#1b2230; --dim:#69727f;
  --accent:#4f63e0; --accent-soft:#eef0fd; --good:#1f9d57; --good-bg:#e6f5ec;
  --warn:#c1841a; --warn-bg:#faf1dd; --bad:#d34a4a; --bad-bg:#fbe9e9; --bar-track:#e7ebf1;
}
:root[data-theme="dark"]{
  --bg:#0e1218; --panel:#161c25; --line:#26303c; --ink:#e6ebf2; --dim:#8a95a4;
  --accent:#7d8ff2; --accent-soft:#1c2440; --good:#4cc585; --good-bg:#12321f;
  --warn:#e0a63e; --warn-bg:#33280f; --bad:#ef6b6b; --bad-bg:#3a1a1a; --bar-track:#232c38;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
.wrap{max-width:940px;margin:0 auto;padding:32px 20px 60px}
.eyebrow{font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.14em;
  text-transform:uppercase;color:var(--accent)}
h1{font-size:26px;margin:8px 0 4px;letter-spacing:-.01em;text-wrap:balance}
.lede{color:var(--dim);font-size:14px;margin:0 0 22px;max-width:60ch}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
@media(max-width:640px){.kpis{grid-template-columns:repeat(2,1fr)}}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 15px}
.kpi .k{font:600 10px/1 ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--dim)}
.kpi .v{font-size:22px;font-weight:750;margin-top:6px;letter-spacing:-.01em;
  font-variant-numeric:tabular-nums}
.kpi .v small{font-size:12px;font-weight:600;color:var(--dim)}
.note{display:flex;gap:10px;background:var(--accent-soft);border:1px solid var(--line);
  border-radius:12px;padding:12px 14px;font-size:13px;color:var(--ink);margin-bottom:22px;line-height:1.5}
.note b{color:var(--accent)}
.tablewrap{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:14px}
table{width:100%;border-collapse:collapse;min-width:900px}
th,td{padding:12px 14px;text-align:right;border-bottom:1px solid var(--line);
  font-variant-numeric:tabular-nums;white-space:nowrap}
tr:last-child td{border-bottom:0}
th{font:600 10px/1.2 ui-monospace,monospace;letter-spacing:.09em;text-transform:uppercase;
  color:var(--dim);background:transparent;position:sticky;top:0}
td.l,th.l{text-align:left}
td.nicho{font-weight:650}
td.cat{color:var(--dim);font-size:13px;text-transform:capitalize}
td.euro{font-weight:750;font-size:15px}
.scorecell{display:flex;align-items:center;gap:10px;justify-content:flex-end}
.bar{width:74px;height:7px;border-radius:5px;background:var(--bar-track);overflow:hidden;flex:0 0 auto}
.bar i{display:block;height:100%;border-radius:5px}
.scoren{font-weight:750;width:26px;text-align:right;font-variant-numeric:tabular-nums}
.trendcell{text-align:left}
.trend{display:flex;align-items:center;gap:8px}
.trend svg{flex:0 0 auto;opacity:.85}
.peak{font:600 10px/1 ui-monospace,monospace;color:var(--dim);text-transform:uppercase;letter-spacing:.03em;white-space:nowrap}
.kd{font-weight:650;font-size:13px}
.rankcell{text-align:left}
.big{display:block;font:600 10px/1.2 ui-monospace,monospace;color:var(--dim);margin-top:2px}
.aio{font:700 9px/1 ui-monospace,monospace;color:var(--bad);border:1px solid var(--bad);
  border-radius:4px;padding:1px 4px;margin-left:4px;vertical-align:middle}
.filters{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.flabel{font:600 11px/1 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.08em;color:var(--dim)}
.fbtn{font:600 12px/1 -apple-system,system-ui,sans-serif;padding:7px 13px;border-radius:99px;
  border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer}
.fbtn:hover{border-color:var(--accent)}
.fbtn.on{background:var(--accent);border-color:var(--accent);color:#fff}
.fsearch{margin-left:auto;font-size:13px;padding:7px 12px;border-radius:9px;
  border:1px solid var(--line);background:var(--panel);color:var(--ink);min-width:150px}
.fsearch:focus{outline:2px solid var(--accent);outline-offset:1px}
th{cursor:pointer;user-select:none}
th:hover{color:var(--accent)}
.chip{display:inline-block;font:650 11px/1 ui-monospace,monospace;letter-spacing:.02em;
  padding:5px 9px;border-radius:99px}
.pend{color:var(--dim);opacity:.5}
tr.nrow{cursor:pointer}
tr.nrow:hover td{background:var(--accent-soft)}
tr.nrow td.nicho::after{content:"›";color:var(--dim);margin-left:6px;font-weight:700}
.ovl{position:fixed;inset:0;background:rgba(10,14,20,.55);display:flex;align-items:flex-end;
  justify-content:center;z-index:50;padding:0}
@media(min-width:640px){.ovl{align-items:center;padding:20px}}
.ovl[hidden]{display:none}
.sheet{background:var(--panel);border:1px solid var(--line);width:100%;max-width:460px;
  border-radius:18px 18px 0 0;padding:22px 20px 26px;position:relative;
  box-shadow:0 -8px 40px rgba(0,0,0,.25)}
@media(min-width:640px){.sheet{border-radius:18px}}
.dclose{position:absolute;top:14px;right:14px;background:var(--accent-soft);border:0;color:var(--ink);
  width:32px;height:32px;border-radius:50%;font-size:15px;cursor:pointer}
.dcat{font:600 11px/1 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.08em;color:var(--accent)}
.dtitle{font-size:21px;margin:4px 0 16px;text-transform:capitalize;text-wrap:balance}
.dgrid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:18px}
.dgrid>div{background:var(--accent-soft);border-radius:10px;padding:9px 11px}
.dgrid span{display:block;font:600 9px/1.3 ui-monospace,monospace;text-transform:uppercase;
  letter-spacing:.05em;color:var(--dim)}
.dgrid b{font-size:15px;font-variant-numeric:tabular-nums;text-transform:capitalize}
.dcopy label{display:block;font-size:12px;color:var(--dim);margin-bottom:6px}
.copyrow{display:flex;gap:8px;margin-bottom:8px}
.copyrow input{flex:1;background:var(--bg);border:1px solid var(--line);border-radius:9px;
  padding:11px 12px;color:var(--ink);font-size:15px;font-weight:600}
.cbtn{background:var(--accent);border:0;color:#fff;border-radius:9px;padding:0 16px;
  font-weight:700;font-size:13px;cursor:pointer;white-space:nowrap}
.cbtn:hover{filter:brightness(1.08)}
.dlinks{display:flex;gap:10px;margin-top:14px}
.dlink{flex:1;text-align:center;text-decoration:none;color:var(--accent);border:1px solid var(--line);
  border-radius:10px;padding:11px;font-weight:600;font-size:13px}
.dlink:hover{border-color:var(--accent);background:var(--accent-soft)}
.foot{color:var(--dim);font-size:12px;margin-top:16px;line-height:1.6}
.foot code{font-family:ui-monospace,monospace;background:var(--accent-soft);padding:1px 5px;border-radius:4px}
"""


def _color(verd):
    return {"Fuerte": ("var(--good)", "var(--good-bg)"),
            "Revisar": ("var(--warn)", "var(--warn-bg)"),
            "Flojo": ("var(--bad)", "var(--bad-bg)")}[verd]


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _check_links(nicho: str) -> str:
    """Botones para comprobar A MANO (gratis) la página 1 de Google y la
    tendencia — la vía sin coste para validar rankeabilidad y demanda."""
    q = urllib.parse.quote_plus(f"mejor {nicho}")
    serp = f"https://www.google.es/search?q={q}"
    tq = urllib.parse.quote_plus(nicho)
    trends = f"https://trends.google.es/trends/explore?geo=ES&q={tq}"
    return (f"<a class='chk' href='{serp}' target='_blank' rel='noopener'>Página&nbsp;1</a>"
            f"<a class='chk' href='{trends}' target='_blank' rel='noopener'>Tendencia</a>")


def _inner() -> str:
    rows, mode = _rows()
    n2 = bool(mode)
    n = len(rows)
    top = rows[0]
    best = max(rows, key=lambda x: x["euro"])
    fuertes = sum(1 for r in rows if r["verd"] == "Fuerte")

    def _rank_cell(r):
        lab = r.get("rank") or ""
        if not lab or lab == "s/d":
            return "<span class='pend'>s/d</span>", -1
        base = lab.split(" · ")[0]
        col = ("var(--good)" if base == "Accesible" else
               "var(--warn)" if base == "Media" else "var(--bad)")
        sort = {"Accesible": 2, "Media": 1, "Difícil": 0}.get(base, -1)
        aio = " <span class='aio'>AIO</span>" if r.get("aio") else ""
        big = r.get("big", 0)
        title = f"{big}/10 grandes en la página 1 de Google"
        return (f"<span class='kd' style='color:{col}' title='{title}'>{base}</span>{aio}"
                f"<span class='big'>{big}/10 grandes</span>", sort)

    trs = []
    for r in rows:
        fg, bg = _color(r["verd"])
        cells = [
            f"<td class='l nicho'>{html.escape(r['nicho'])}</td>",
            f"<td class='l cat'>{html.escape(r['cat'])}</td>",
            f"<td data-s='{r['com']}'>{r['com']:.1f}%</td>",
            f"<td data-s='{r['ticket']}'>{r['ticket']:.0f}€</td>",
            f"<td class='euro' data-s='{r['euro']}'>{r['euro']:.2f}€</td>",
            f"<td>{r['intent']}</td>",
        ]
        if n2:  # columnas de pago (demanda + tendencia + rankeabilidad + €/mes)
            dem = (f"{_miles(r['vol'])}/mes" if r["vol"] is not None
                   else "<span class='pend'>—</span>")
            if r["monthly"]:
                peak = (f"<span class='peak'>pico {html.escape(r['peak'])}</span>"
                        if r["peak"] else "")
                trend = f"<div class='trend'>{_sparkline(r['monthly'], 'var(--accent)')}{peak}</div>"
            else:
                trend = "<span class='pend'>—</span>"
            rank_html, rank_sort = _rank_cell(r)
            pot_html = (f"<b>{_miles(round(r['pot']))}€</b>" if r.get("pot") is not None
                        else "<span class='pend'>—</span>")
            pot_sort = r["pot"] if r.get("pot") is not None else -1
            cells += [
                f"<td data-s='{r['vol'] or 0}'>{dem}</td>",
                f"<td class='trendcell'>{trend}</td>",
                f"<td class='rankcell' data-s='{rank_sort}'>{rank_html}</td>",
                f"<td class='euro' data-s='{pot_sort}'>{pot_html}</td>",
            ]
        cells += [
            f"<td data-s='{r['score']}'><div class='scorecell'>"
            f"<span class='bar'><i style='width:{r['score']}%;background:{fg}'></i></span>"
            f"<span class='scoren'>{r['score']}</span></div></td>",
            f"<td><span class='chip' style='color:{fg};background:{bg}'>{r['verd']}</span></td>",
        ]
        # data-* con todo lo del nicho: la ficha se rellena desde aquí al hacer clic.
        attrs = (f"data-verd='{r['verd']}' data-nicho=\"{html.escape(r['nicho'], quote=True)}\" "
                 f"data-cat=\"{html.escape(r['cat'], quote=True)}\" data-com='{r['com']:.1f}' "
                 f"data-ticket='{r['ticket']:.0f}' data-euro='{r['euro']:.2f}' "
                 f"data-intent=\"{html.escape(r['intent'], quote=True)}\" "
                 f"data-score='{r['score']}'")
        trs.append(f"<tr class='nrow' {attrs}>" + "".join(cells) + "</tr>")

    if n2:
        eyebrow = ("Nivel 2 · demanda real (DEMO)" if mode == "mock"
                   else "Nivel 2 · demanda real")
        pots = [r for r in rows if r.get("pot") is not None]
        bestpot = max(pots, key=lambda x: x["pot"]) if pots else None
        kpi4 = (f"<div class='kpi'><div class='k'>Potencial top</div>"
                f"<div class='v'>{_miles(round(bestpot['pot']))}€ <small>{html.escape(bestpot['nicho'])}/mes</small></div></div>"
                if bestpot else
                f"<div class='kpi'><div class='k'>En verde</div><div class='v'>{fuertes} <small>de {n}</small></div></div>")
        if mode == "mock":
            note = ("<span>⚠</span><div><b>Datos de prueba (mock).</b> El pipeline "
                    "funciona; estas cifras de demanda son ficticias. Con tus credenciales "
                    "de DataForSEO en <code>.env</code> se rellenan con volumen real de España.</div>")
        else:
            note = ("<span>✓</span><div><b>Nivel 2 · datos reales de España.</b> Demanda, "
                    "tendencia&nbsp;12m, mes pico, <b>€ potenciales/mes</b> y <b>Rankeable</b>. "
                    "Esta última mira la <b>página 1 real de Google</b> (“mejor {nicho}”) y cuenta "
                    "cuántos son grandes (Amazon, El&nbsp;Corte&nbsp;Inglés, medios…): pocas webs "
                    "pequeñas = difícil entrar; varias = hay hueco. <b>AIO</b> = Google pone AI "
                    "Overview (roba clics). Esta sí es fiable en español (mira quién rankea de "
                    "verdad, no un número). Toca una cabecera para reordenar; filtra arriba.</div>")
        lede = ("Qué nichos compensan de verdad: <b>paga</b> × <b>se busca</b> × <b>puedes entrar</b>. "
                "Ordena y filtra a tu gusto.")
        foot = ("Score = €/venta (35, satura 15€) + demanda (30, log) + rankeabilidad de la SERP (25) "
                "+ intención (10). €/mes = demanda × 4% captura × 3% conversión × €/venta. Grandes "
                "dominios en <code>BIG_DOMAINS</code> (editable).<br>"
                "Edita <code>nichos.csv</code> y <code>COMISIONES</code>, y vuelve a ejecutar.")
    else:
        eyebrow = "Cribado gratis · 100% sin coste"
        kpi4 = (f"<div class='kpi'><div class='k'>En verde</div>"
                f"<div class='v'>{fuertes} <small>de {n}</small></div></div>")
        note = ("<span>✓</span><div><b>Toca cualquier nicho</b> para abrir su ficha: verás sus "
                "datos (comisión, ticket, € por venta, score) y un <b>texto listo para copiar y "
                "pegar en Google</b> (“mejor …”), además de botones para abrir la búsqueda y la "
                "tendencia. Todo gratis: el score se basa en lo fiable (€ por venta × intención); "
                "la rankeabilidad la compruebas tú en Google con un clic. Filtra por veredicto y "
                "ordena tocando una cabecera.</div>")
        lede = ("Qué nichos <b>pagan de verdad</b> (comisión × ticket × intención). Toca uno para "
                "ver su ficha y copiar la búsqueda de Google. Ordena y filtra a tu gusto.")
        foot = ("Score = €/venta (60, satura a 15€) + intención de compra (40). Comisiones "
                "Amazon estimadas y editables en <code>COMISIONES</code>.<br>"
                "Flujo: el radar filtra por dinero → tú comprueba los finalistas con los botones "
                "<b>Página&nbsp;1</b> / <b>Tendencia</b> (gratis). Edita <code>nichos.csv</code> y vuelve a ejecutar.")

    return f"""<title>Radar de nichos de afiliación</title>
<style>{CSS}</style>
<div class="wrap">
  <div class="eyebrow">{eyebrow}</div>
  <h1>Radar de nichos de afiliación</h1>
  <p class="lede">{lede}</p>

  <div class="kpis">
    <div class="kpi"><div class="k">Nichos</div><div class="v">{n}</div></div>
    <div class="kpi"><div class="k">Top</div><div class="v" style="font-size:15px;line-height:1.25">{html.escape(top['nicho'])}<br><small>score {top['score']}</small></div></div>
    <div class="kpi"><div class="k">Mejor €/venta</div><div class="v">{best['euro']:.2f}€ <small>{html.escape(best['nicho'])}</small></div></div>
    {kpi4}
  </div>

  <div class="note">{note}</div>

  <div class="filters">
    <span class="flabel">Filtrar:</span>
    <button class="fbtn on" data-f="all">Todos</button>
    <button class="fbtn" data-f="Fuerte">Fuerte</button>
    <button class="fbtn" data-f="Revisar">Revisar</button>
    <button class="fbtn" data-f="Flojo">Flojo</button>
    <input class="fsearch" type="search" placeholder="Buscar nicho…" aria-label="Buscar nicho">
  </div>

  <div class="tablewrap"><table id="radar">
    <thead><tr>
      <th class="l">Nicho</th><th class="l">Categoría</th><th>Comisión</th><th>Ticket</th>
      <th>€/venta</th><th>Intención</th>{'<th>Demanda</th><th>Tendencia&nbsp;12m</th><th>Rankeable?</th><th>€/mes</th>' if n2 else ''}
      <th>Score</th><th>Veredicto</th>
    </tr></thead>
    <tbody>{''.join(trs)}</tbody>
  </table></div>

  <p class="foot">{foot}</p>
</div>

<div class="ovl" id="ovl" hidden>
  <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="dTitle">
    <button class="dclose" id="dclose" aria-label="Cerrar">✕</button>
    <div class="dcat" id="dCat"></div>
    <h2 class="dtitle" id="dTitle"></h2>

    <div class="dgrid">
      <div><span>Comisión</span><b id="dCom"></b></div>
      <div><span>Ticket</span><b id="dTicket"></b></div>
      <div><span>€ por venta</span><b id="dEuro"></b></div>
      <div><span>Intención</span><b id="dIntent"></b></div>
      <div><span>Score</span><b id="dScore"></b></div>
      <div><span>Veredicto</span><b id="dVerd"></b></div>
    </div>

    <div class="dcopy">
      <label>Texto para buscar en Google (cópialo y pégalo):</label>
      <div class="copyrow">
        <input id="dQuery" readonly>
        <button class="cbtn" id="dCopy">Copiar</button>
      </div>
      <div class="copyrow">
        <input id="dQueryT" readonly>
        <button class="cbtn" id="dCopyT">Copiar</button>
      </div>
    </div>

    <div class="dlinks">
      <a class="dlink" id="dGoogle" target="_blank" rel="noopener">Abrir en Google ↗</a>
      <a class="dlink" id="dTrends" target="_blank" rel="noopener">Ver tendencia ↗</a>
    </div>
  </div>
</div>
<script>
(function(){{
  var table=document.getElementById('radar'); if(!table) return;
  var tb=table.tBodies[0];
  var rows=function(){{return Array.prototype.slice.call(tb.rows);}};
  // Ordenar al tocar cabecera (numérico por data-s, texto si no).
  var ths=table.tHead.rows[0].cells, dir={{}};
  Array.prototype.forEach.call(ths,function(th,i){{
    th.style.cursor='pointer'; th.title='Ordenar';
    th.addEventListener('click',function(){{
      var d=dir[i]=-(dir[i]||1);
      rows().sort(function(a,b){{
        var ca=a.cells[i], cb=b.cells[i];
        var sa=ca.getAttribute('data-s'), sb=cb.getAttribute('data-s');
        var va = sa!==null? parseFloat(sa) : ca.textContent.trim().toLowerCase();
        var vb = sb!==null? parseFloat(sb) : cb.textContent.trim().toLowerCase();
        if(va<vb) return -1*d; if(va>vb) return 1*d; return 0;
      }}).forEach(function(r){{tb.appendChild(r);}});
    }});
  }});
  // Filtrar por veredicto + búsqueda de texto.
  var cur='all', q='';
  function apply(){{
    rows().forEach(function(r){{
      var okV = cur==='all' || r.getAttribute('data-verd')===cur;
      var okQ = !q || r.getAttribute('data-nicho').toLowerCase().indexOf(q)>=0;
      r.style.display = (okV&&okQ)?'':'none';
    }});
  }}
  document.querySelectorAll('.fbtn').forEach(function(b){{
    b.addEventListener('click',function(){{
      document.querySelectorAll('.fbtn').forEach(function(x){{x.classList.remove('on');}});
      b.classList.add('on'); cur=b.getAttribute('data-f'); apply();
    }});
  }});
  var s=document.querySelector('.fsearch');
  if(s) s.addEventListener('input',function(){{q=s.value.trim().toLowerCase(); apply();}});

  // ── Ficha del nicho: clic en una fila -> abre modal con datos + texto a copiar ──
  var ovl=document.getElementById('ovl');
  var $=function(id){{return document.getElementById(id);}};
  function openSheet(tr){{
    var n=tr.getAttribute('data-nicho');
    $('dTitle').textContent=n;
    $('dCat').textContent=tr.getAttribute('data-cat');
    $('dCom').textContent=tr.getAttribute('data-com')+'%';
    $('dTicket').textContent=tr.getAttribute('data-ticket')+'€';
    $('dEuro').textContent=tr.getAttribute('data-euro')+'€';
    $('dIntent').textContent=tr.getAttribute('data-intent');
    $('dScore').textContent=tr.getAttribute('data-score');
    $('dVerd').textContent=tr.getAttribute('data-verd');
    var q='mejor '+n;
    $('dQuery').value=q;
    $('dQueryT').value=n;
    $('dGoogle').href='https://www.google.es/search?q='+encodeURIComponent(q);
    $('dTrends').href='https://trends.google.es/trends/explore?geo=ES&q='+encodeURIComponent(n);
    ovl.hidden=false; document.body.style.overflow='hidden';
  }}
  function closeSheet(){{ ovl.hidden=true; document.body.style.overflow=''; }}
  tb.addEventListener('click',function(e){{
    var tr=e.target.closest('tr.nrow'); if(tr) openSheet(tr);
  }});
  $('dclose').addEventListener('click',closeSheet);
  ovl.addEventListener('click',function(e){{ if(e.target===ovl) closeSheet(); }});
  document.addEventListener('keydown',function(e){{ if(e.key==='Escape') closeSheet(); }});
  function copyFrom(inputId, btn){{
    var inp=$(inputId); inp.select(); inp.setSelectionRange(0,999);
    var done=function(){{ var t=btn.textContent; btn.textContent='¡Copiado!';
      setTimeout(function(){{btn.textContent=t;}},1200); }};
    if(navigator.clipboard) navigator.clipboard.writeText(inp.value).then(done,function(){{
      try{{document.execCommand('copy');done();}}catch(_){{}}
    }});
    else {{ try{{document.execCommand('copy');done();}}catch(_){{}} }}
  }}
  $('dCopy').addEventListener('click',function(){{copyFrom('dQuery',this);}});
  $('dCopyT').addEventListener('click',function(){{copyFrom('dQueryT',this);}});
}})();
</script>"""


def run() -> tuple[Path, Path]:
    inner = _inner()
    full = ("<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"</head><body>{inner}</body></html>")
    p_full = BASE / "radar.html"
    p_art = BASE / "radar_artifact.html"
    p_full.write_text(full, encoding="utf-8")
    p_art.write_text(inner, encoding="utf-8")
    return p_full, p_art


if __name__ == "__main__":
    a, b = run()
    print(f"OK -> {a.name} + {b.name}")
