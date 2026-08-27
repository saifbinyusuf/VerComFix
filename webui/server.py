import subprocess, json, os, signal, time, pickle, re, glob
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS_FILE = os.path.join(BASE, 'data', 'status.json')
LOG_DIR = os.path.join(BASE, 'logs')
PID_FILE = os.path.join(BASE, 'data', 'pipeline.pid')

app = FastAPI()

def is_running(pid):
    try:
        os.kill(pid, 0); return True
    except OSError:
        return False


# ── Progress computation ──────────────────────────────────────────
def _count_dirs(path):
    """Count subdirectories in a path."""
    if not os.path.isdir(path):
        return 0
    return sum(1 for e in os.scandir(path) if e.is_dir())

def _count_files(path, pattern="*"):
    """Count files matching a glob pattern."""
    if not os.path.isdir(path):
        return 0
    return len(glob.glob(os.path.join(path, pattern)))

def _count_log_lines(stage, pattern=None):
    """Count lines (optionally matching a regex) in a stage's log."""
    path = os.path.join(LOG_DIR, f"{stage}.log")
    if not os.path.exists(path):
        return 0
    try:
        with open(path, errors='ignore') as f:
            if pattern:
                return sum(1 for line in f if re.search(pattern, line))
            return sum(1 for _ in f)
    except Exception:
        return 0

def _load_total_repos():
    """Total repos selected (from selectRepo.pkl)."""
    pkl = os.path.join(BASE, 'data_collection', 'selectRepo.pkl')
    if not os.path.exists(pkl):
        return 0
    try:
        return len(pickle.load(open(pkl, 'rb')))
    except Exception:
        return 0

def _load_total_packages():
    """Total packages from rank.txt."""
    rank_files = [
        os.path.join(BASE, 'data_collection', 'src', 'rank.txt'),
        os.path.join(BASE, 'data_collection', 'rank.txt'),
    ]
    for p in rank_files:
        if os.path.exists(p):
            try:
                return sum(1 for line in open(p) if line.strip() and not line.startswith('#'))
            except Exception:
                pass
    return 0

def compute_progress(stage_name, stage_state):
    """Compute real progress (current, total, label) for a stage."""
    if stage_state not in ('running', 'done'):
        return None

    repos_dir = os.path.join(BASE, 'data', 'repos')
    src_dir = os.path.join(BASE, 'data_collection', 'src')
    packages_dir = os.path.join(BASE, 'packages')

    if stage_name == 'select_repos':
        n = _load_total_repos()
        return {"current": n, "total": None, "label": f"{n} repos found"} if n else None

    elif stage_name == 'download_repos':
        total = _load_total_repos()
        current = _count_dirs(repos_dir)
        if total:
            return {"current": current, "total": total, "label": f"{current}/{total} repos downloaded"}
        return None

    elif stage_name == 'unzip_repos':
        # Count .zip files vs extracted dirs
        current = _count_log_lines('unzip_repos', r'(extracted|unzipped|inflating|done)')
        total = _count_dirs(repos_dir)
        if total:
            return {"current": min(current, total), "total": total, "label": f"{min(current, total)}/{total} repos extracted"}
        return None

    elif stage_name == 'pick_packages':
        n = _load_total_packages()
        return {"current": n, "total": None, "label": f"{n} packages selected"} if n else None

    elif stage_name == 'crawl_pypi':
        total = _load_total_packages()
        current = _count_dirs(src_dir)
        if total:
            return {"current": current, "total": total, "label": f"{current}/{total} packages crawled"}
        return None

    elif stage_name == 'uncompress':
        total = _count_dirs(src_dir)
        current = _count_dirs(packages_dir)
        if total:
            return {"current": current, "total": total, "label": f"{current}/{total} packages uncompressed"}
        return None

    elif stage_name == 'kb_top_level':
        current = _count_log_lines('kb_top_level', r'handle version')
        return {"current": current, "total": None, "label": f"{current} versions indexed"} if current else None

    elif stage_name == 'kb_sniff':
        current = _count_log_lines('kb_sniff', r'(Saved|Processing|APIs for)')
        return {"current": current, "total": None, "label": f"{current} packages sniffed"} if current else None

    elif stage_name == 'tc_extract':
        current = _count_log_lines('tc_extract', r'(Processing|Extracted|repo)')
        return {"current": current, "total": None, "label": f"{current} items extracted"} if current else None

    elif stage_name == 'select_tasks':
        tasks_path = os.path.join(BASE, 'tasks.jsonl')
        if os.path.exists(tasks_path):
            n = sum(1 for _ in open(tasks_path))
            return {"current": n, "total": None, "label": f"{n} tasks selected"}
        return None

    return None


# ── API endpoints ─────────────────────────────────────────────────

@app.post("/start")
def start(profile: str = "light"):
    if os.path.exists(PID_FILE) and is_running(int(open(PID_FILE).read())):
        return {"error": "already running"}
    proc = subprocess.Popen(
        ["python", os.path.join(BASE, "orchestrator", "orchestrator.py"), "--profile", profile], 
        cwd=BASE, start_new_session=True)
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    open(PID_FILE, 'w').write(str(proc.pid))
    return {"status": "started", "pid": proc.pid}

@app.post("/stop")
def stop():
    if not os.path.exists(PID_FILE):
        return {"error": "not running"}
    pid = int(open(PID_FILE).read())
    try: 
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError: 
        pass
    os.remove(PID_FILE)
    
    # Update status to stopped
    if os.path.exists(STATUS_FILE):
        status_data = json.load(open(STATUS_FILE))
        status_data["overall"] = "stopped"
        # Mark running stages as stopped
        for key, val in status_data.items():
            if isinstance(val, dict) and val.get("state") == "running":
                val["state"] = "stopped"
        json.dump(status_data, open(STATUS_FILE, 'w'), indent=2)
        
    return {"status": "stopped"}

@app.get("/stages")
def stages():
    """Return the ordered stage list with descriptions for the frontend."""
    from orchestrator.orchestrator import STAGES
    return [{"id": name, "description": desc} for name, desc, _, _ in STAGES]

@app.get("/status")
def status():
    if not os.path.exists(STATUS_FILE):
        return {"overall": "not_started"}
    data = json.load(open(STATUS_FILE))
    # Inject live progress for each stage
    for key, val in data.items():
        if key == 'overall' or not isinstance(val, dict):
            continue
        progress = compute_progress(key, val.get('state', 'pending'))
        if progress:
            val['progress'] = progress
    return data

@app.get("/log/{stage}")
def log(stage: str, tail: int = 500):
    path = os.path.join(LOG_DIR, f"{stage}.log")
    if not os.path.exists(path):
        return {"lines": []}
    return {"lines": open(path, errors='ignore').readlines()[-tail:]}

@app.get("/results")
def results():
    tasks_path = os.path.join(BASE, "tasks.jsonl")
    n = sum(1 for _ in open(tasks_path)) if os.path.exists(tasks_path) else 0
    return {"tasks_count": n, "tasks_file_exists": os.path.exists(tasks_path)}

@app.get("/results/preview")
def preview(n: int = 10):
    tasks_path = os.path.join(BASE, "tasks.jsonl")
    if not os.path.exists(tasks_path):
        return {"tasks": []}
    return {"tasks": [json.loads(l) for l in open(tasks_path).readlines()[:n]]}

@app.get("/results/download")
def download():
    return FileResponse(os.path.join(BASE, "tasks.jsonl"), filename="tasks.jsonl")

app.mount("/", StaticFiles(directory=os.path.join(BASE, "webui", "static"), html=True), name="static")