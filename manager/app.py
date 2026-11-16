import os, time, json, asyncio, logging, subprocess
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import httpx
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ai-sre-manager")
app = FastAPI(title="AI SRE Manager")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "600"))
INCIDENTS_LOG = "/data/incidents.jsonl"

ALERTS_RECEIVED = Counter("sre_alerts_received_total", "Total alerts received", ["alertname", "status"])
LLM_CALLS = Counter("sre_llm_calls_total", "DeepSeek API calls", ["status"])
LLM_LATENCY = Histogram("sre_llm_latency_seconds", "DeepSeek response latency")
cooldown_cache = {}

def collect_local_diagnostics():
    cmds = {"uptime": "uptime", "memory": "free -h", "disk": "df -h /", "top_cpu": "ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -n 6"}
    results = {}
    for k, c in cmds.items():
        try:
            results[k] = subprocess.check_output(c, shell=True, text=True, timeout=5).strip()
        except Exception as e:
            results[k] = f"error: {e}"
    return results

async def analyze_with_deepseek(alert, diagnostics):
    if not DEEPSEEK_API_KEY:
        return "DEEPSEEK_API_KEY не задан."
    sys_p = "Ты — опытный SRE-инженер. Тебе приходит алерт от Prometheus/Alertmanager и базовая диагностика Linux-хоста. Дай краткий разбор на русском: 1) Причина, 2) Что проверить, 3) Безопасная команда для диагностики."
    payload = json.dumps({"alert": alert, "diagnostics": diagnostics}, ensure_ascii=False, indent=2)
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(f"{DEEPSEEK_BASE_URL}/chat/completions", headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}, json={"model": DEEPSEEK_MODEL, "messages": [{"role": "system", "content": sys_p}, {"role": "user", "content": payload}], "temperature": 0.2})
            r.raise_for_status()
            LLM_CALLS.labels(status="ok").inc()
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        LLM_CALLS.labels(status="error").inc()
        return f"Ошибка анализа DeepSeek: {e}"
    finally:
        LLM_LATENCY.observe(time.perf_counter() - start)

@app.get("/health")
async def health():
    return {"status": "ok", "model": DEEPSEEK_MODEL}

@app.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/webhook")
async def alertmanager_webhook(request: Request):
    payload = await request.json()
    alerts = payload.get("alerts", [])
    processed = []
    for alert in alerts:
        labels = alert.get("labels", {})
        name = labels.get("alertname", "UnknownAlert")
        inst = labels.get("instance", "local")
        status = alert.get("status", "firing")
        ALERTS_RECEIVED.labels(alertname=name, status=status).inc()
        key = f"{name}:{inst}:{status}"
        now = time.time()
        if now - cooldown_cache.get(key, 0) < COOLDOWN_SECONDS:
            processed.append({"alert": key, "skipped": "cooldown"})
            continue
        cooldown_cache[key] = now
        diag = await asyncio.to_thread(collect_local_diagnostics)
        analysis = await analyze_with_deepseek(alert, diag)
        os.makedirs(os.path.dirname(INCIDENTS_LOG), exist_ok=True)
        with open(INCIDENTS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "alertname": name, "status": status, "analysis": analysis}, ensure_ascii=False) + "\n")
        logger.info("Incident %s analyzed", name)
        processed.append({"alert": name, "status": status, "analysis": analysis})
    return {"received": len(alerts), "processed": processed}
