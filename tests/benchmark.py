"""Measures real detection latency and recovery time over N forced crashes.  python3 tests/benchmark.py [N]"""
import os, sys, time, tempfile, statistics
os.environ["WATCHDOG_DB"] = os.path.join(tempfile.mkdtemp(), "bench.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import watchdog as wd

N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
DEMO = os.path.join(os.path.dirname(__file__), "..", "demo", "demo_app.py")
w = wd.Watchdog()
w.register("bench", f"{sys.executable} {DEMO} --port 8301", health_url="http://127.0.0.1:8301/health",
           interval=1.0, cooldown=1.0, max_restarts=3)
time.sleep(2); det, rec = [], []
print(f"{'run':>3} {'detect(s)':>10} {'recover(s)':>11}")
for i in range(1, N + 1):
    before = wd.q("SELECT COUNT(*) c FROM incidents WHERE status='recovered'").fetchone()["c"]
    t_kill = time.time(); w.kill("bench")
    while wd.q("SELECT COUNT(*) c FROM incidents WHERE status='recovered'").fetchone()["c"] == before: time.sleep(0.05)
    r = wd.q("SELECT * FROM incidents WHERE status='recovered' ORDER BY id DESC LIMIT 1").fetchone()
    det.append(r["detected_at"] - t_kill); rec.append(r["recovered_at"] - t_kill)
    print(f"{i:>3} {det[-1]:>10.2f} {rec[-1]:>11.2f}"); time.sleep(11)   # let streak counter reset
w.stop_all()
print(f"\nDetection latency : avg {statistics.mean(det):.2f}s  min {min(det):.2f}s  max {max(det):.2f}s")
print(f"Kill-to-recovered : avg {statistics.mean(rec):.2f}s  min {min(rec):.2f}s  max {max(rec):.2f}s")
print(f"Recovery success  : {len(rec)}/{N}")
