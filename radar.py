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
    """Nivel 1 (sin demanda): €/venta (60) + intención (40)."""
    total = round(min(euro / 5.0, 1.0) * 60 + intent_pts)
    return total, _verd(total)


INTENT_N2 = {"Alta": 15, "Media": 10, "Baja": 4}


def score2(euro: float, intent_label: str, volume: int) -> tuple[int, str]:
    """Nivel 2 (con demanda real): €/venta (45) + demanda (40) + intención (15).

    NO usa la competencia de Google Ads (venía HIGH/100 en todo → inútil para
    diferenciar; además NO es dificultad SEO). La dificultad real para rankear
    (KD) es un endpoint aparte, la siguiente capa. Topes altos para que un nicho
    excepcional (mucho ticket Y mucha demanda) destaque de verdad:
      · €/venta se satura a 15€ (una venta que paga como 5 freidoras)
      · demanda log, se satura a ~100.000 búsq/mes
    """
    euro_pts = min(euro / 15.0, 1.0) * 45
    demand_pts = min(math.log10(volume + 1) / 5.0, 1.0) * 40
    intent_pts = INTENT_N2.get(intent_label, 10)
    total = round(max(0.0, min(100.0, euro_pts + demand_pts + intent_pts)))
    return total, _verd(total)


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

    # Nivel 2: demanda real en un solo lote (mock o live) si está configurado.
    mode = dataforseo.available()
    demand = {}
    if mode:
        try:
            demand = dataforseo.search_volume([n for n, _, _ in raw])
        except Exception as e:
            print(f"aviso: demanda no disponible ({type(e).__name__}: {str(e)[:80]}) -> Nivel 1")
            mode = ""

    out = []
    for nicho, cat, ticket in raw:
        com, euro = euro_por_venta(cat, ticket)
        ilabel, ipts = intent_label(nicho)
        d = demand.get(nicho)
        if d:
            sc, verd = score2(euro, ilabel, d["volume"])
            vol, cpc, monthly, peak = d["volume"], d["cpc"], d.get("monthly") or [], d.get("peak") or ""
        else:
            sc, verd = score(euro, ipts)
            vol, cpc, monthly, peak = None, None, [], ""
        out.append(dict(nicho=nicho, cat=cat, com=com, ticket=ticket, euro=euro,
                        intent=ilabel, score=sc, verd=verd, vol=vol, cpc=cpc,
                        monthly=monthly, peak=peak))
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
table{width:100%;border-collapse:collapse;min-width:820px}
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
.chip{display:inline-block;font:650 11px/1 ui-monospace,monospace;letter-spacing:.02em;
  padding:5px 9px;border-radius:99px}
.pend{color:var(--dim);opacity:.5}
.foot{color:var(--dim);font-size:12px;margin-top:16px;line-height:1.6}
.foot code{font-family:ui-monospace,monospace;background:var(--accent-soft);padding:1px 5px;border-radius:4px}
"""


def _color(verd):
    return {"Fuerte": ("var(--good)", "var(--good-bg)"),
            "Revisar": ("var(--warn)", "var(--warn-bg)"),
            "Flojo": ("var(--bad)", "var(--bad-bg)")}[verd]


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _inner() -> str:
    rows, mode = _rows()
    n2 = bool(mode)
    n = len(rows)
    top = rows[0]
    best = max(rows, key=lambda x: x["euro"])
    fuertes = sum(1 for r in rows if r["verd"] == "Fuerte")

    trs = []
    for r in rows:
        fg, bg = _color(r["verd"])
        dem = (f"{_miles(r['vol'])}/mes" if r["vol"] is not None
               else "<span class='pend'>—</span>")
        if n2 and r["monthly"]:
            spark = _sparkline(r["monthly"], "var(--accent)")
            peak = (f"<span class='peak'>pico {html.escape(r['peak'])}</span>"
                    if r["peak"] else "")
            trend = f"<div class='trend'>{spark}{peak}</div>"
            cpc = f"{r['cpc']:.2f}€" if r["cpc"] is not None else "—"
        else:
            trend, cpc = "<span class='pend'>—</span>", "<span class='pend'>—</span>"
        trs.append(
            f"<tr>"
            f"<td class='l nicho'>{html.escape(r['nicho'])}</td>"
            f"<td class='l cat'>{html.escape(r['cat'])}</td>"
            f"<td>{r['com']:.1f}%</td>"
            f"<td>{r['ticket']:.0f}€</td>"
            f"<td class='euro'>{r['euro']:.2f}€</td>"
            f"<td>{r['intent']}</td>"
            f"<td>{dem}</td>"
            f"<td class='trendcell'>{trend}</td>"
            f"<td>{cpc}</td>"
            f"<td><div class='scorecell'>"
            f"<span class='bar'><i style='width:{r['score']}%;background:{fg}'></i></span>"
            f"<span class='scoren'>{r['score']}</span></div></td>"
            f"<td><span class='chip' style='color:{fg};background:{bg}'>{r['verd']}</span></td>"
            f"</tr>"
        )

    if n2:
        eyebrow = ("Nivel 2 · demanda real (DEMO)" if mode == "mock"
                   else "Nivel 2 · demanda real")
        total_dem = sum(r["vol"] or 0 for r in rows)
        kpi4 = (f"<div class='kpi'><div class='k'>Demanda total</div>"
                f"<div class='v'>{_miles(total_dem)} <small>búsq/mes</small></div></div>")
        if mode == "mock":
            note = ("<span>⚠</span><div><b>Datos de prueba (mock).</b> El pipeline "
                    "funciona; estas cifras de demanda son ficticias. Con tus credenciales "
                    "de DataForSEO en <code>.env</code> se rellenan con volumen real de España.</div>")
        else:
            note = ("<span>✓</span><div><b>Nivel 2 activo · datos reales de España.</b> "
                    "Demanda, tendencia (12&nbsp;meses), mes pico y CPC de DataForSEO. "
                    "<b>Ojo:</b> el score aún NO mide si podrás <i>rankear</i> — la dificultad "
                    "SEO real (KD) es la siguiente capa. La “tendencia” es la forma del año, "
                    "y el “pico” te dice cuándo atacar.</div>")
        lede = ("Qué nichos compensan de verdad: <b>dinero por venta</b> × <b>demanda real</b>, "
                "con la estación en la que vende cada uno. Ordenado por score.")
        foot = ("Score = €/venta (45, satura a 15€) + demanda (40, log, satura ~100k) + intención (15). "
                "La competencia de Google&nbsp;Ads se omite (venía “alta” en todo y no es dificultad SEO).<br>"
                "Edita <code>nichos.csv</code> y la tabla <code>COMISIONES</code>, y vuelve a ejecutar.")
    else:
        eyebrow = "Nivel 1 · cribado gratis"
        kpi4 = (f"<div class='kpi'><div class='k'>En verde</div>"
                f"<div class='v'>{fuertes} <small>de {n}</small></div></div>")
        note = ("<span>ⓘ</span><div><b>Lo que aún no mide:</b> demanda (búsquedas/mes) y "
                "competencia — esa es la capa de pago barata (Nivel&nbsp;2, DataForSEO "
                "~0,05&nbsp;$/nicho). Este Nivel&nbsp;1 descarta lo que no paga <i>antes</i> "
                "de validar demanda. Comisiones = estimadas y editables.</div>")
        lede = ("Qué nichos compensan por <b>dinero real por venta</b> e intención de compra, "
                "antes de gastar un céntimo en validar demanda. Ordenado por score.")
        foot = ("Score = €/venta (hasta 60, tope 5€) + intención (hasta 40). La columna "
                "<b>Demanda</b> se rellena en el Nivel&nbsp;2.<br>"
                "Edita <code>nichos.csv</code> y la tabla <code>COMISIONES</code>, y vuelve a ejecutar.")

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

  <div class="tablewrap"><table>
    <thead><tr>
      <th class="l">Nicho</th><th class="l">Categoría</th><th>Comisión</th><th>Ticket</th>
      <th>€/venta</th><th>Intención</th><th>Demanda</th><th>Tendencia&nbsp;12m</th><th>CPC</th><th>Score</th><th>Veredicto</th>
    </tr></thead>
    <tbody>{''.join(trs)}</tbody>
  </table></div>

  <p class="foot">{foot}</p>
</div>"""


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
