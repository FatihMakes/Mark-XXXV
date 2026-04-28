# actions/web_search.py
# MARK XXV — Web Search
# Primary: Groq chat completions for query understanding
# Fallback: DuckDuckGo (ddgs)

import json
import sys
from pathlib import Path
from core.llm_client import groq_chat_response
import ddgs


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


#def _get_api_key() -> str:
  #  with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
   #     return json.load(f)["gemini_api_key"]

def _groq_search(query: str) -> str:
    response = groq_chat_response(
        messages=[{
            "role": "user",
            "content": f"Search the web for the following query and provide a concise, accurate answer: {query}"
        }],
        temperature=0.4,
        max_tokens=80,
    )
    text = response.choices[0].message.content.strip()
    if not text:
        raise ValueError("Empty response")
    return text

def _ddg_then_summarize(query: str) -> str:
    results = _ddg_search(query, max_results=6)
    if not results:
        return f"No encontré información sobre: {query}"
    
    context = "\n".join([
        f"- {r['title']}: {r['snippet']}" 
        for r in results if r.get("snippet")
    ])

    if not context:
        return f"No encontré snippets útiles para: {query}"

    try:
        response = groq_chat_response(
            messages=[{
                "role": "user",
                "content": (
                    f"Search results for '{query}':\n\n"
                    f"{context}\n\n"
                    f"Extract the current temperature number from these results. "
                    f"Reply with ONLY: 'La temperatura actual en [place] es de X°C.' "
                    f"If no specific number found, reply: 'No se encontró temperatura exacta, pero [brief summary].'"
                )
            }],
            temperature=0.1,
            max_tokens=80,
        )
        result = response.choices[0].message.content.strip()
        if not result:
            raise ValueError("Empty response")
        return result
    except Exception as e:
        print(f"[DDG] Summarize failed: {e}")
        first = results[0]
        return f"{first['title']}: {first['snippet'][:200]}"

def _ddg_search(query: str, max_results: int = 6) -> list:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title":   r.get("title", ""),
                "snippet": r.get("body", ""),
                "url":     r.get("href", ""),
            })
    return results

def _format_ddg(query: str, results: list) -> str:
    if not results:
        return f"No results found for: {query}"
    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _compare(items: list, aspect: str) -> str:
    query = f"Compare {', '.join(items)} in terms of {aspect}. Give specific facts and data."
    try:
        return _groq_search(query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Groq compare failed: {e}")
        all_results = {}
        for item in items:
            try:
                all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
            except Exception:
                all_results[item] = []
        lines = [f"Comparison — {aspect.upper()}\n{'─'*40}"]
        for item in items:
            lines.append(f"\n▸ {item}")
            for r in all_results.get(item, [])[:2]:
                if r.get("snippet"):
                    lines.append(f"  • {r['snippet']}")
        return "\n".join(lines)


def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode", "search").lower()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general")

    if not query and not items:
        return "Please provide a search query, sir."

    if items and mode != "compare":
        mode = "compare"

    if player:
        player.write_log(f"[Search] {query or ', '.join(items)}")

    print(f"[WebSearch] 🔍 Query: {query!r}  Mode: {mode}")

    try:
        print("[WebSearch] 🌐 Searching...")
        
        # clima y datos en tiempo real → DDG directo (Groq no tiene datos actuales)
        realtime_keywords = ["clima", "weather", "temperatura", "lluvia", "pronóstico", "forecast"]
        if any(w in query.lower() for w in realtime_keywords):
            print("[WebSearch] 🌦️ Realtime query → DDG + summarize")
            return _ddg_then_summarize(query)

        # resto → Groq primero, DDG como fallback
        try:
            result = _groq_search(query)
            print("[WebSearch] ✅ Groq OK.")
            return result
        except Exception as e:
            print(f"[WebSearch] ⚠️ Groq failed ({e}), trying DDG...")
            results = _ddg_search(query)
            result  = _format_ddg(query, results)
            print(f"[WebSearch] ✅ DDG: {len(results)} results.")
            return result
    except Exception as e:
        print(f"[WebSearch] ❌ Failed: {e}")
        return f"Search failed, sir: {e}"