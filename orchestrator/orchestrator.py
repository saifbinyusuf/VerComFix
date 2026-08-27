# orchestrator/orchestrator.py
import subprocess, json, os, pickle, yaml, argparse, time
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))

STATUS_FILE = os.path.join(BASE, 'data', 'status.json')
LOG_DIR = os.path.join(BASE, 'logs')

def load_profile(name):
    return yaml.safe_load(open(os.path.join(BASE, 'orchestrator', 'profiles', f'{name}.yaml')))

def write_conf_ini(profile):
    conf = f"""[spider]
stars = {profile['repo']['min_stars']}
forks = {profile['repo']['min_forks']}
isfork = false
fork_update_range = 180
create_bg = {profile['repo']['date_start']}
create_ed = {profile['repo']['date_end']}
update_range = 365
cutoff_date = {profile['repo']['date_end']}
page_size = 100
max_res = 1000

[dep_filter]
mirror = raw.gitmirror.com
min_n_dependency = {profile['repo']['min_dependencies']}
dump_file = selectRepo.pkl

[download]
download_base_dir = ../data/repos
"""
    conf_path = os.path.join(BASE, 'data_collection', 'conf.ini')
    os.makedirs(os.path.dirname(conf_path), exist_ok=True)
    open(conf_path, 'w').write(conf)

def cap_selected_repos(profile):
    pkl_path = os.path.join(BASE, 'data_collection', 'selectRepo.pkl')
    d = pickle.load(open(pkl_path, 'rb'))
    # selectRepo.pkl stores tuples like ('owner/repo', 'branch') — not dicts
    # size filtering is not possible at this stage; just cap by count
    d = d[:profile['repo']['max_repo_count']]
    pickle.dump(d, open(pkl_path, 'wb'))
    return len(d)

STAGES = [
    ("select_repos",  "Select GitHub repos",        ["python", "select_repo.py"],                              os.path.join(BASE, 'data_collection')),
    ("cap_repos",     "Cap repo list",               None,                                                     None),
    ("download_repos","Download repos",              ["python", "download_repo.py"],                            os.path.join(BASE, 'data_collection')),
    ("unzip_repos",   "Extract repo archives",       ["python", os.path.join(BASE, 'glue', 'unzip_repos.py')],  BASE),
    ("pick_packages", "Pick packages to crawl",      ["python", os.path.join(BASE, 'glue', 'pick_packages.py')],BASE),
    ("crawl_pypi",    "Crawl PyPI packages",         ["python", "craw_package_from_PyPI.py"],                    os.path.join(BASE, 'data_collection')),
    ("uncompress",    "Uncompress packages",         ["python", "uncompress_package.py"],                        os.path.join(BASE, 'data_collection')),
    ("kb_init",       "Init knowledge DB",           ["python", "db.py"],                                       os.path.join(BASE, 'knowledge_builder')),
    ("kb_top_level",  "Index top-level modules",     ["python", "get_top_level_from_package.py"],               os.path.join(BASE, 'knowledge_builder')),
    ("kb_sniff",      "Sniff API signatures",        ["python", "sniffer_thread.py"],                           os.path.join(BASE, 'knowledge_builder')),
    ("tc_init",       "Init task construction DB",   ["python", "db.py"],                                       os.path.join(BASE, 'task_construction')),
    ("tc_extract",    "Extract tasks from repos",    ["python", "extract_all.py"],                              os.path.join(BASE, 'task_construction')),
    ("select_tasks",  "Select final tasks",          ["python", os.path.join(BASE, 'glue', 'select_tasks.py')], BASE),
]

def write_status(status):
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    json.dump(status, open(STATUS_FILE, 'w'), indent=2)

def run_pipeline(profile_name="light", resume_from=None):
    os.makedirs(LOG_DIR, exist_ok=True)
    profile = load_profile(profile_name)
    
    if resume_from and os.path.exists(STATUS_FILE):
        status = json.load(open(STATUS_FILE))
    else:
        status = {name: {"state": "pending", "description": desc} for name, desc, _, _ in STAGES}
        
    status["overall"] = "running"
    write_status(status)
    write_conf_ini(profile)

    start_idx = 0
    if resume_from:
        for i, (name, _, _, _) in enumerate(STAGES):
            if name == resume_from:
                start_idx = i
                break

    for name, desc, cmd, cwd in STAGES[start_idx:]:
        status[name]["state"] = "running"
        status[name]["started_at"] = time.time()
        write_status(status)

        if name == "cap_repos":
            n = cap_selected_repos(profile)
            status[name] = {"state": "done", "description": desc, "detail": f"kept {n} repos",
                            "started_at": status[name]["started_at"], "duration": 0}
            write_status(status)
            continue

        log_path = os.path.join(LOG_DIR, f"{name}.log")
        print(f"--- Starting stage: {name} ---")
        with open(log_path, "w") as logf:
            process = subprocess.Popen(
                cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=os.environ.copy(), text=True, bufsize=1
            )
            for line in process.stdout:
                import sys
                sys.stdout.write(line)
                sys.stdout.flush()
                logf.write(line)
                logf.flush()
            process.wait()
            result_returncode = process.returncode

        duration = round(time.time() - status[name]["started_at"], 1)

        if result_returncode != 0:
            status[name]["state"] = "failed"
            status[name]["duration"] = duration
            status["overall"] = "failed"
            write_status(status)
            raise RuntimeError(f"stage '{name}' failed — see {log_path}")

        status[name]["state"] = "done"
        status[name]["duration"] = duration
        write_status(status)

    status["overall"] = "complete"
    write_status(status)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--profile", default="light")
    p.add_argument("--resume-from", help="Stage to resume pipeline execution from")
    args = p.parse_args()
    run_pipeline(args.profile, args.resume_from)