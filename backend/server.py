"""FastAPI layer + live dashboard. Run: python3 -m uvicorn server:api --port 8000"""
import os, sys, time
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from watchdog import Watchdog, q, metrics

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(HERE, "..", "demo", "demo_app.py")
PY = sys.executable
api = FastAPI(title="Self-Healing Application Reliability Platform")
w = Watchdog()

def launch(name, port, extra="", **kw):
    old = w.apps.get(name)
    if old:                                   # replace a previous run of the same app
        old.stop = True
        if old.proc and old.proc.poll() is None: old.proc.kill()
    w.register(name, f"{PY} {DEMO} --port {port} {extra}", health_url=f"http://127.0.0.1:{port}/health", **kw)

launch("demo-api", 8101)
launch("demo-worker", 8102)

@api.get("/api/status")
def status(): return w.status()

@api.get("/api/incidents")
def incidents():
    rows = q("SELECT * FROM incidents ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(id=r["id"], app=r["app"], cause=r["cause"], status=r["status"], attempts=r["attempts"],
                 detected_at=r["detected_at"],
                 detection_latency_max_s=round(r["detected_at"] - r["last_ok_at"], 2),
                 recovery_s=round(r["recovered_at"] - r["detected_at"], 2) if r["recovered_at"] else None) for r in rows]

@api.get("/api/alerts")
def alerts(): return [dict(r) for r in q("SELECT * FROM alerts ORDER BY id DESC LIMIT 30").fetchall()]

@api.get("/api/metrics")
def get_metrics():
    m = metrics(); st = w.status()
    m.update(total=len(st), healthy=sum(s["state"] == "healthy" for s in st),
             failed=sum(s["state"] == "failed" for s in st)); return m

@api.post("/api/kill/{name}")
def kill(name: str):
    if name not in w.apps: raise HTTPException(404, "app not registered")   # only registered apps can be touched
    try: w.kill(name)
    except ProcessLookupError: raise HTTPException(409, "process already dead")
    return {"killed": name}

@api.post("/api/scenario/crashloop")
def crashloop():
    launch("crash-loop", 8103, "--crash-after 1", cooldown=0.5); return {"started": "crash-loop"}

@api.get("/", response_class=HTMLResponse)
def home(): return PAGE

PAGE = """<!doctype html><html><head><meta charset=utf-8><title>Self-Healing Reliability Platform</title>
<style>
:root{--bg:#0b1220;--card:#131c2e;--line:#22304a;--tx:#e6ecf5;--mut:#8fa0ba;--g:#22c55e;--r:#ef4444;--a:#f59e0b;--b:#3b82f6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px system-ui,sans-serif;padding:24px}
h1{margin:0;font-size:22px}.sub{color:var(--mut);margin:4px 0 18px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.card,.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.card b{display:block;font-size:26px;margin-top:4px}.card span{color:var(--mut);font-size:12px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:900px){.grid{grid-template-columns:1fr}}
h2{font-size:15px;margin:0 0 10px}table{width:100%;border-collapse:collapse}
td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}th{color:var(--mut);font-weight:500}
.pill{padding:2px 8px;border-radius:99px;font-size:12px;font-weight:600}
.healthy,.recovered,.info{background:#12341f;color:var(--g)}.failed,.gave_up,.critical{background:#3a1518;color:var(--r)}
.recovering,.warning{background:#3b2a0a;color:var(--a)}
button{background:var(--b);color:#fff;border:0;border-radius:6px;padding:6px 10px;cursor:pointer}
button.d{background:var(--r)}.bar{height:14px;background:var(--b);border-radius:3px;min-width:2px}
.row{display:flex;gap:8px;margin-bottom:10px;align-items:center}.mut{color:var(--mut)}
</style></head><body>
<h1>Self-Healing Application Reliability Platform</h1>
<div class=sub>Real-time process monitoring. Automated recovery. Measurable reliability. <span id=ts></span></div>
<div class=cards id=cards></div>
<div class=grid>
<div class=panel><h2>Monitored applications</h2><table id=apps></table>
<div class=row style="margin-top:12px"><button class=d onclick="post('/api/scenario/crashloop')">Start crash-loop scenario</button>
<span class=mut>app that crashes every start: watch it get blocked</span></div></div>
<div class=panel><h2>Recovery time per incident (s)</h2><div id=chart></div></div>
<div class=panel><h2>Incidents</h2><table id=inc></table></div>
<div class=panel><h2>Alerts</h2><table id=al></table></div>
</div>
<script>
const $=id=>document.getElementById(id);
const pill=s=>`<span class="pill ${s}">${s}</span>`;
async function post(u){await fetch(u,{method:'POST'});load()}
async function load(){
 const [st,inc,al,m]=await Promise.all(['status','incidents','alerts','metrics'].map(x=>fetch('/api/'+x).then(r=>r.json())));
 $('ts').textContent=' | updated '+new Date().toLocaleTimeString();
 const c=(l,v)=>`<div class=card><span>${l}</span><b>${v}</b></div>`;
 $('cards').innerHTML=c('Applications',m.total)+c('Healthy',m.healthy)+c('Failed',m.failed)+c('Incidents',m.incidents)
  +c('MTTR',m.mttr_s+' s')+c('Recovery success',m.success_rate+'%');
 $('apps').innerHTML='<tr><th>App<th>Status<th>PID<th>CPU<th>Mem<th>Uptime<th></tr>'+st.map(a=>
  `<tr><td>${a.name}<td>${pill(a.state)}<td>${a.pid??'-'}<td>${a.cpu??'-'}%<td>${a.mem_mb??'-'} MB<td>${a.uptime}s
   <td><button class=d onclick="post('/api/kill/${a.name}')">Kill</button></tr>`).join('');
 $('inc').innerHTML='<tr><th>#<th>App<th>Cause<th>Attempts<th>Recovery<th>Status</tr>'+inc.slice(0,8).map(i=>
  `<tr><td>${i.id}<td>${i.app}<td>${i.cause}<td>${i.attempts}<td>${i.recovery_s??'-'}s<td>${pill(i.status)}</tr>`).join('');
 $('al').innerHTML=al.slice(0,8).map(a=>`<tr><td>${pill(a.severity)}<td>${a.msg}<td class=mut>${new Date(a.ts*1000).toLocaleTimeString()}</tr>`).join('');
 const rec=inc.filter(i=>i.recovery_s!=null).slice(0,10).reverse(), mx=Math.max(1,...rec.map(i=>i.recovery_s));
 $('chart').innerHTML=rec.length?rec.map(i=>`<div class=row><span class=mut style="width:90px">#${i.id} ${i.app}</span>
  <div class=bar style="width:${i.recovery_s/mx*60}%"></div><span>${i.recovery_s}s</span></div>`).join(''):'<span class=mut>No recoveries yet. Click Kill on an app.</span>';
}
load();setInterval(load,1000);
</script></body></html>"""
