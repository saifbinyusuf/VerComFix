import os
import re
import glob
import json
import time
import urllib.request

def main():
    repo_dir = 'vendor/VerComFix/data/repos'
    original_rank_file = 'vendor/VerComFix/data_collection/rank.txt'
    out_rank_file = 'vendor/VerComFix/data_collection/src/rank.txt'
    budget_bytes = 150 * 1e6  # 150 MB

    # 1. Derive candidate packages from downloaded repos
    declared = set()
    
    # requirements.txt style
    for req_file in glob.glob(os.path.join(repo_dir, '*', 'requirements.txt')):
        try:
            for line in open(req_file, errors='ignore'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                name = re.split(r'[<>=!\[; ]', line)[0].strip()
                if name:
                    declared.add(name.lower())
        except Exception:
            pass

    # setup.py style (best effort)
    for setup_file in glob.glob(os.path.join(repo_dir, '*', 'setup.py')):
        try:
            src = open(setup_file, errors='ignore').read()
            for m in re.findall(r'[\'\"]([A-Za-z0-9_.\-]+)(?:[<>=!\[].*?)?[\'\"]', src):
                declared.add(m.lower())
        except Exception:
            pass
            
    print(f"{len(declared)} distinct dependency names found across your repos.")

    # 2. Match against rank.txt and add known-breaking safety net
    known_breaking = {'scikit-learn', 'numpy'}
    rank_dict = {}
    
    with open(original_rank_file, 'r', errors='ignore') as f:
        for line in f:
            parts = line.strip().split('@@')
            if len(parts) == 2:
                rank_dict[parts[1].lower()] = line.strip()

    candidates = [d for d in (declared | known_breaking) if d in rank_dict]
    print(f"{len(candidates)} candidates after intersecting with rank.txt")

    # 3. Check real sizes and trim to budget
    sized = []
    print("Checking PyPI sizes...")
    for pkg in candidates:
        try:
            req = urllib.request.Request(f'https://pypi.org/pypi/{pkg}/json', headers={'User-Agent': 'VerComFix-Builder'})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.load(r)
            size = sum(f.get('size', 0) for v in d.get('releases', {}).values() for f in v if f.get('packagetype') == 'sdist')
            sized.append((pkg, size))
            print(f"  {pkg}: {size/1e6:.1f} MB")
        except Exception as e:
            print(f"  {pkg}: FAILED ({e})")
        time.sleep(0.2)

    sized.sort(key=lambda x: x[1])
    kept = []
    running = 0
    
    for pkg, size in sized:
        if running + size <= budget_bytes:
            kept.append(pkg)
            running += size
            
    print(f"\nKeeping {len(kept)} packages, {running/1e6:.1f} MB compressed total.")

    # 4. Write final rank.txt subset
    os.makedirs(os.path.dirname(out_rank_file), exist_ok=True)
    with open(out_rank_file, 'w') as f:
        for pkg in kept:
            f.write(f"{rank_dict[pkg]}\n")
            
    print(f"Wrote final list to {out_rank_file}")

if __name__ == '__main__':
    main()
