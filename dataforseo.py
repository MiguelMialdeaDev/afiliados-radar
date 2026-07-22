# -*- coding: utf-8 -*-
"""Cliente mínimo de DataForSEO — demanda real por nicho (Nivel 2).

Usa el endpoint de volumen de búsqueda de Google Ads (barato, ~0,05$/lote de
hasta 1.000 keywords). Devuelve por keyword: volumen mensual, CPC y competencia.

Credenciales por variables de entorno (o .env): DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD.
Sin dependencias externas (urllib de la stdlib).

Modo prueba SIN cuenta: DATAFORSEO_MOCK=1 -> genera cifras deterministas ficticias
para verificar que el pipeline (scoring + tabla) funciona antes de pagar nada.
"""
import base64
import json
import os
import urllib.request

BASE = "https://api.dataforseo.com/v3"
LOCATION_ES = 2724   # España
LANGUAGE_ES = "es"
MES_ABBR = ["", "ene", "feb", "mar", "abr", "may", "jun",
            "jul", "ago", "sep", "oct", "nov", "dic"]


def _auth() -> str | None:
    # Atajo: si tienes el token Base64 ya hecho (campo "Base64 Format" del panel),
    # basta con eso — no hace falta login/password por separado.
    b64 = os.environ.get("DATAFORSEO_B64")
    if b64:
        return "Basic " + b64.strip()
    login = os.environ.get("DATAFORSEO_LOGIN")
    pw = os.environ.get("DATAFORSEO_PASSWORD")
    if not login or not pw:
        return None
    return "Basic " + base64.b64encode(f"{login}:{pw}".encode()).decode()


def available() -> str:
    """'mock' | 'live' | '' según lo que haya configurado."""
    if os.environ.get("DATAFORSEO_MOCK") == "1":
        return "mock"
    return "live" if _auth() else ""


def _mock(keywords: list[str]) -> dict:
    out = {}
    for kw in keywords:
        h = sum(ord(c) for c in kw)
        base = (h % 60) * 350 + 150
        # 12 meses ficticios con un pico estacional determinista.
        peak = h % 12
        months = [int(base * (1.6 if abs(i - peak) <= 1 else 0.7 if abs(i - peak) > 4 else 1.0))
                  for i in range(12)]
        out[kw] = {"volume": base, "cpc": round((h % 18) / 10 + 0.2, 2),
                   "competition": ["LOW", "MEDIUM", "HIGH"][h % 3],
                   "monthly": months, "peak": MES_ABBR[peak + 1]}
    return out


def search_volume(keywords: list[str]) -> dict:
    """keyword -> {'volume': int/mes, 'cpc': float, 'competition': 0-100}."""
    if os.environ.get("DATAFORSEO_MOCK") == "1":
        return _mock(keywords)
    auth = _auth()
    if not auth:
        raise RuntimeError("Faltan DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD")
    body = json.dumps([{
        "keywords": keywords,
        "location_code": LOCATION_ES,
        "language_code": LANGUAGE_ES,
    }]).encode()
    req = urllib.request.Request(
        f"{BASE}/keywords_data/google_ads/search_volume/live",
        data=body,
        headers={"Authorization": auth, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    out = {}
    for task in data.get("tasks", []):
        for item in (task.get("result") or []):
            kw = item.get("keyword")
            if not kw:
                continue
            ms = item.get("monthly_searches") or []
            chrono = sorted(ms, key=lambda m: (m.get("year", 0), m.get("month", 0)))
            months = [m.get("search_volume") or 0 for m in chrono]
            peak = ""
            if chrono:
                pm = max(chrono, key=lambda m: m.get("search_volume") or 0)
                peak = MES_ABBR[pm.get("month", 0)]
            out[kw] = {"volume": item.get("search_volume") or 0,
                       "cpc": item.get("cpc") or 0.0,
                       "competition": item.get("competition") or "",
                       "monthly": months, "peak": peak}
    return out
