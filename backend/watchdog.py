"""Watchdog core: launches registered processes, detects crashes, restarts with
cooldown/backoff, verifies recovery, logs incidents + alerts to SQLite."""
import os, sys, time, shlex, signal, sqlite3, threading, subprocess, urllib.request
try:
    import psutil
except ImportError:
    psutil = None

DB = os.environ.get("WATCHDOG_DB", "watchdog.db")
_lock = threading.Lock()

def db():
    c = sqlite3.connect(DB, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _lock, db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY AUTOINCREMENT, app TEXT,
            last_ok_at REAL, detected_at REAL, recovered_at REAL, attempts INT DEFAULT 0,
            cause TEXT, status TEXT);
        CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL,
            app TEXT, severity TEXT, msg TEXT);""")

def q(sql, args=()):
    with _lock, db() as c:
        cur = c.execute(sql, args); c.commit(); return cur

class App:
    def __init__(s, name, cmd, health_url=None, max_restarts=3, cooldown=2.0, interval=1.0):
        s.name, s.cmd, s.health_url = name, cmd, health_url
        s.max_restarts, s.cooldown, s.interval = max_restarts, cooldown, interval
        s.proc = None; s.state = "stopped"; s.started_at = 0.0; s.streak = 0; s.stop = False

class Watchdog:
    def __init__(s): s.apps = {}; init_db()

    # ---- registration: only explicitly registered commands are ever run (no shell) ----
    def register(s, name, cmd, **kw):
        app = App(name, shlex.split(cmd), **kw); s.apps[name] = app
        s._start(app); threading.Thread(target=s._guard, args=(app,), daemon=True).start()

    def _start(s, app):
        app.proc = subprocess.Popen(app.cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        app.started_at = time.time()

    def _healthy(s, app):
        if app.proc.poll() is not None: return False
        if not app.health_url: return True
        try: return urllib.request.urlopen(app.health_url, timeout=1).status == 200
        except Exception: return False

    def _verify(s, app, timeout=6):
        end = time.time() + timeout
        while time.time() < end:
            if s._healthy(app): return True
            if app.proc.poll() is not None: return False
            time.sleep(0.3)
        return False

    def _alert(s, app, sev, msg):
        q("INSERT INTO alerts(ts,app,severity,msg) VALUES(?,?,?,?)", (time.time(), app.name, sev, msg))

    def _guard(s, app):
        last_ok = time.time(); app.state = "healthy" if s._verify(app) else "failed"
        while not app.stop:
            time.sleep(app.interval)
            if app.state == "failed": return
            if s._healthy(app):
                last_ok = time.time(); app.state = "healthy"
                if last_ok - app.started_at > 10: app.streak = 0   # stable -> reset crash-loop counter
                continue
            code = app.proc.poll()
            cause = f"exit code {code}" if code is not None else "health check failed"
            if code is None: app.proc.kill(); app.proc.wait()
            detected = time.time(); app.state = "recovering"
            alive_for = detected - app.started_at
            app.streak = app.streak + 1 if alive_for < 10 else 1
            iid = q("INSERT INTO incidents(app,last_ok_at,detected_at,cause,status) VALUES(?,?,?,?,'recovering')",
                    (app.name, last_ok, detected, cause)).lastrowid
            s._alert(app, "warning", f"{app.name} failed ({cause})")
            if app.streak > app.max_restarts:
                q("UPDATE incidents SET status='gave_up' WHERE id=?", (iid,))
                s._alert(app, "critical", f"{app.name}: crash loop, auto-restart disabled"); app.state = "failed"; return
            ok = False
            for n in range(1, app.max_restarts + 1):
                time.sleep(app.cooldown * 2 ** (n - 1))          # exponential backoff
                q("UPDATE incidents SET attempts=? WHERE id=?", (n, iid))
                s._start(app)
                if s._verify(app): ok = True; break
            if ok:
                q("UPDATE incidents SET recovered_at=?, status='recovered' WHERE id=?", (time.time(), iid))
                s._alert(app, "info", f"{app.name} recovered after {n} attempt(s)"); app.state = "healthy"
            else:
                q("UPDATE incidents SET status='failed' WHERE id=?", (iid,))
                s._alert(app, "critical", f"{app.name}: recovery failed after {n} attempts"); app.state = "failed"; return

    # ---- demo / dashboard helpers ----
    def kill(s, name): os.kill(s.apps[name].proc.pid, signal.SIGKILL)

    def status(s):
        out = []
        for a in s.apps.values():
            pid = a.proc.pid if a.proc and a.proc.poll() is None else None
            cpu = mem = None
            if pid and psutil:
                try: p = psutil.Process(pid); cpu = p.cpu_percent(); mem = round(p.memory_info().rss / 1e6, 1)
                except psutil.Error: pass
            out.append(dict(name=a.name, state=a.state, pid=pid, cpu=cpu, mem_mb=mem,
                            uptime=round(time.time() - a.started_at) if pid else 0))
        return out

    def stop_all(s):
        for a in s.apps.values():
            a.stop = True
            if a.proc and a.proc.poll() is None: a.proc.kill()

def metrics():
    r = q("SELECT * FROM incidents").fetchall()
    rec = [x for x in r if x["status"] == "recovered"]
    mttr = sum(x["recovered_at"] - x["detected_at"] for x in rec) / len(rec) if rec else 0
    return dict(incidents=len(r), recovered=len(rec), mttr_s=round(mttr, 2),
                success_rate=round(100 * len(rec) / len(r), 1) if r else 100.0)

if __name__ == "__main__":      # quick end-to-end self-test
    if os.path.exists(DB): os.remove(DB)
    w = Watchdog(); py = sys.executable; app = os.path.join(os.path.dirname(__file__), "../demo/demo_app.py")
    w.register("demo-api", f"{py} {app} --port 8101", health_url="http://127.0.0.1:8101/health")
    time.sleep(2); print("before:", w.status())
    w.kill("demo-api"); time.sleep(6); print("after :", w.status())
    w.register("crash-loop", f"{py} {app} --port 8102 --crash-after 1", health_url="http://127.0.0.1:8102/health", cooldown=0.5)
    time.sleep(25)
    for i in q("SELECT app,attempts,status,cause FROM incidents").fetchall(): print(dict(i))
    for a in q("SELECT severity,msg FROM alerts").fetchall(): print(dict(a))
    print(metrics()); w.stop_all()
