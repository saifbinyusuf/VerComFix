import re, glob, os, time, urllib.request, json

VENDOR = os.path.join(os.path.dirname(__file__), '..', 'vendor', 'VerComFix')
REPO_GLOB = os.path.join(VENDOR, 'data', 'repos', '*')
RANK_TXT = os.path.join(VENDOR, 'data_collection', 'rank.txt')
OUT_FILE = os.path.join(VENDOR, 'data_collection', 'src', 'rank.txt')
KNOWN_BREAKING = {'scikit-learn', 'numpy'}
BUDGET_BYTES = int(os.environ.get('PACKAGE_BUDGET_MB', '150')) * 1_000_000

def find_declared_deps():
    declared = set()
    for req_file in glob.glob(os.path.join(REPO_GLOB, 'requirements.txt')):
        for line in open(req_file, errors='ignore'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            name = re.split(r'[<>=!\[; ]', line)[0].strip()
            if name:
                declared.add(name.lower())
    for setup_file in glob.glob(os.path.join(REPO_GLOB, 'setup.py')):
        src = open(setup_file, errors='ignore').read()
        for m in re.findall(r'[\'"]([A-Za-z0-9_.\-]+)(?:[<>=!\[].*?)?[\'"]', src):
            declared.add(m.lower())
    return declared

def match_against_rank(declared):
    rank = {}
    for line in open(RANK_TXT):
        idx, name = line.strip().split('@@')
        rank[name.lower()] = name
    wanted = declared | KNOWN_BREAKING
    return [rank[d] for d in wanted if d in rank]

def size_and_trim(candidates):
    sized = []
    for pkg in candidates:
        try:
            req = urllib.request.Request(f'https://pypi.org/pypi/{pkg}/json', headers={'User-Agent': 'vercomfix-tool'})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.load(r)
            size = sum(f['size'] for v in d['releases'].values() for f in v if f['packagetype'] == 'sdist')
            sized.append((pkg, size))
            print(f'  {pkg}: {size/1e6:.1f} MB')
        except Exception as e:
            print(f'  {pkg}: FAILED ({e})')
        time.sleep(0.2)
    sized.sort(key=lambda x: x[1])
    kept, running = [], 0
    for pkg, size in sized:
        if running + size <= BUDGET_BYTES:
            kept.append(pkg); running += size
    print(f'kept {len(kept)} packages, {running/1e6:.1f} MB (budget {BUDGET_BYTES/1e6:.0f} MB)')
    return kept

def main():
    declared = find_declared_deps()
    print(f'{len(declared)} distinct dependency names found across downloaded repos')
    candidates = match_against_rank(declared)
    print(f'{len(candidates)} candidates: {candidates}')
    final = size_and_trim(candidates) or [p for p in candidates if p.lower() in KNOWN_BREAKING]
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    kept_set = {p.lower() for p in final}
    with open(RANK_TXT) as src, open(OUT_FILE, 'w') as out:
        for line in src:
            if line.strip().split('@@')[1].lower() in kept_set:
                out.write(line)
    print(f'wrote {OUT_FILE}')

if __name__ == '__main__':
    main()