# Self-Healing Application Reliability Platform
**Linux Process Watchdog and Auto-Restart System** (OS Hackathon, 17.10.2026)

Monitors registered Linux processes, detects unexpected termination, restarts them automatically
(with cooldown, exponential backoff and a crash-loop limit), verifies recovery with an HTTP health
check, logs every incident, and shows live health and reliability metrics on a web dashboard.

## Features
- Real process monitoring (PID, CPU, memory, uptime) via `psutil`
- Crash detection through the process exit code (`poll()`), including signal kills (e.g. -9 = SIGKILL)
- Automatic restart with configurable max attempts, cooldown and exponential backoff
- Recovery verification: process alive **and** HTTP `/health` returns 200
- Crash-loop prevention: stops restarting and raises a `critical` alert
- Incident log + alerts in SQLite; MTTR, success rate and detection latency computed from records
- Live web dashboard (FastAPI) with a safe "Kill" test button
- Safety: only explicitly registered commands run, never through a shell; the API cannot touch unregistered processes

## Architecture
```
Browser dashboard  --REST-->  FastAPI (server.py)  -->  Watchdog core (watchdog.py)
                                                          |- one guard thread per app
                                                          |- Popen / poll / kill (OS process APIs)
                                                          '- SQLite: incidents, alerts
```

## Setup (Ubuntu / WSL)
```bash
sudo apt update
sudo apt install -y python3 python3-psutil python3-fastapi python3-uvicorn
# or: pip3 install -r requirements.txt --break-system-packages
```
No compilation is needed (pure Python 3).

## Run
```bash
cd backend
python3 -m uvicorn server:api --port 8000
```
Open http://localhost:8000. Click **Kill** on an app to watch detection and auto-recovery.
Click **Start crash-loop scenario** to see restart-loop prevention and the critical alert.

## Test and measure
```bash
python3 -m unittest tests.test_watchdog -v   # 4 automated tests
python3 tests/benchmark.py 10                # detection latency and recovery time over 10 crashes
python3 backend/watchdog.py                  # quick end-to-end console self-test
```

## Sample measured results (8 forced SIGKILL crashes, 1 s poll interval, 1 s cooldown)
| Metric | Result |
|---|---|
| Detection latency | avg 0.42 s (max 0.98 s, bounded by the poll interval) |
| Kill to verified recovery | avg 1.73 s |
| Recovery success | 8 / 8 |

## Project layout
```
backend/watchdog.py   core: monitor, restart policy, verification, incident log
backend/server.py     REST API + dashboard
demo/demo_app.py      disposable test app (/health endpoint, optional crash-after)
tests/                unit tests + benchmark
docs/                 project report
```

## Limitations
Single machine, controlled environment. Detection uses polling, so latency is up to one poll interval.
No authentication yet (future work), no multi-server agents, no email alerts.

## Team
(add names and roles)
