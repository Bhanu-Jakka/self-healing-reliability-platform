"""Automated tests. Run from project root:  python3 -m unittest tests.test_watchdog -v"""
import os, sys, time, tempfile, unittest
os.environ["WATCHDOG_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import watchdog as wd

DEMO = os.path.join(os.path.dirname(__file__), "..", "demo", "demo_app.py")
CMD = f"{sys.executable} {DEMO}"

def wait_for(cond, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if cond(): return True
        time.sleep(0.2)
    return False

class WatchdogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.w = wd.Watchdog()
    @classmethod
    def tearDownClass(cls): cls.w.stop_all()

    def test_1_crash_is_detected_and_restarted(self):
        self.w.register("t-api", f"{CMD} --port 8201", health_url="http://127.0.0.1:8201/health", cooldown=0.5)
        self.assertTrue(wait_for(lambda: self.w.apps["t-api"].state == "healthy"))
        old = self.w.apps["t-api"].proc.pid
        self.w.kill("t-api")
        self.assertTrue(wait_for(lambda: wd.q("SELECT 1 FROM incidents WHERE app='t-api' AND status='recovered'").fetchone()))
        self.assertNotEqual(old, self.w.apps["t-api"].proc.pid, "a NEW process must be running")
        self.assertEqual(self.w.apps["t-api"].state, "healthy")

    def test_2_crash_loop_is_stopped_with_alert(self):
        self.w.register("t-loop", f"{CMD} --port 8202 --crash-after 1", health_url="http://127.0.0.1:8202/health", cooldown=0.3)
        self.assertTrue(wait_for(lambda: self.w.apps["t-loop"].state == "failed", 40))
        self.assertTrue(wd.q("SELECT 1 FROM alerts WHERE app='t-loop' AND severity='critical'").fetchone())
        self.assertTrue(wd.q("SELECT 1 FROM incidents WHERE app='t-loop' AND status='gave_up'").fetchone())

    def test_3_unregistered_app_cannot_be_touched(self):
        with self.assertRaises(KeyError): self.w.kill("some-other-process")

    def test_4_metrics_are_computed_from_records(self):
        m = wd.metrics()
        self.assertGreaterEqual(m["incidents"], 2); self.assertGreater(m["mttr_s"], 0)
        self.assertTrue(0 <= m["success_rate"] <= 100)

if __name__ == "__main__": unittest.main(verbosity=2)
