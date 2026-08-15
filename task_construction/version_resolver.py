"""
BUG: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte
"""
import os, re, ast, toml, pickle, configparser, argparse, requests
from datetime import datetime

COMMIT_DATE = None

NAME_TO_INFO = None
def get_commit_date(repo_name, commit_sha):
    """Get commit date of a specific commit in a GitHub repo"""

    global NAME_TO_INFO
    if not NAME_TO_INFO:
        NAME_TO_INFO = {}
        try:
            file_url = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data_collection', 'repo_commit_info.pkl')
            with open(file_url, 'rb') as f:
                for repo_info in pickle.load(f):
                    NAME_TO_INFO[repo_info[1]] = repo_info
        except FileNotFoundError:
            print(f"[Err] Can't find '{file_url}'. Maybe you should run 'select_repo.py' first.")

    try:
        repo_info = NAME_TO_INFO[repo_name] # owner, repo_name, commit_sha, commit_date
    except KeyError:
        print(f"[Err] Repository({repo_name}) don't have commit date info")
        return None
    if commit_sha != repo_info[2]: print(f'{commit_sha} => {repo_info[2]}')
    return repo_info[3]

USE_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/pypi/{package_name}/json"
NOT_MIRROR = "https://pypi.org/pypi/{package_name}/json"
def get_newest_tpl_version_before_date(package_name, cutoff_date):
    url = USE_MIRROR.format(package_name=package_name) if USE_MIRROR else\
          NOT_MIRROR.format(package_name=package_name)
    response = requests.get(url)

    try:
        data = response.json()
    except Exception:
        return None # TPL not found
    
    cutoff = datetime.strptime(cutoff_date, "%Y-%m-%d")
    versions = []
    
    for version, files in data["releases"].items():
        if files:  # skip versions with no files
            upload_time = datetime.strptime(files[0]["upload_time"], "%Y-%m-%dT%H:%M:%S")
            if upload_time <= cutoff:
                versions.append((version, upload_time))
    
    versions.sort(key=lambda x: x[1], reverse=True)
    return versions[0][0] if versions else None

def parse_requirement_line(line: str):
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    # General regex matching, supports numpy==1.21.0, numpy>=1.20,<=1.22, numpy
    pattern = r'^\s*([a-zA-Z0-9_\-\.]+)\s*(.*)$'
    match = re.match(pattern, line)
    if not match:
        return None
    package, version_spec = match.groups()
    version_spec = version_spec.strip()
    if version_spec.startswith(('==', '>=', '<=', '>', '<', '~=', '!=')):
        return (package, version_spec)
    else: # no version specified
        pkg_version = get_newest_tpl_version_before_date(package, COMMIT_DATE)
        return (package, f'~~{pkg_version}') if pkg_version else (package, '')

def parse_pyproject_toml(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()
        config = toml.loads(text) # parse TOML format string
    except Exception as e:
        print(f"[Err] Fail to parse toml config: {e}")
        return []

    deps = set()
    try: # core dependencies
        deps |= set(config["project"]["dependencies"])
    except KeyError: pass
    try: # optional dependency groups
        optional_deps = config["project"]["optional-dependencies"] # dict
        for optional_dep_group in optional_deps.values(): 
            deps |= set(optional_dep_group)
    except KeyError: pass
    
    deps = [parse_requirement_line(line) for line in list(deps) if line]
    return deps

def parse_requirements_txt(filepath):
    _SKIP_LINE = "#-_`"
    def _clean_req_line(line: str) -> str:
        pattern =  r"^([^#;@\\]+)"
        match = re.search(pattern, line)
        if match: line = match.group(0)
        match = re.search(r'^(.*?)--(.*?)$', line)
        if match: line = match.group(1)
        return line.strip().replace('\ufeff', '')

    deps = []
    try: 
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = _clean_req_line(line)
                # Skip empty lines, comments, index substitutions
                if not line or line[0] in _SKIP_LINE: continue
                if line.startswith("pip install"):
                    for dep in line[12:].split(' '):
                        deps.append(parse_requirement_line(dep))
                    continue
                if line.startswith('git+'): 
                    deps.append(parse_requirement_line(line[4:]))
                    continue
                match = re.search(r"(.+?)=(.+?)=(.+)", line)
                if match: # conda-format requirement
                    deps.append(parse_requirement_line(match.group(1)))
                    continue
                line = re.sub(r"\+.*$", "", line)  
                try:
                    deps.append(parse_requirement_line(line))
                except Exception as e:
                    print(f"[Err] fail to parse line: '{line}', {e}")
                    exit(0)
    except Exception as e:
        print(f"Fail to parse [{filepath}], {e}")
    return deps

def parse_setup_py(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        tree = ast.parse(f.read(), filename=filepath)
    class FindInstallRequires(ast.NodeVisitor):
        def __init__(self):
            self.requires = []

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == 'setup':
                for kw in node.keywords:
                    if kw.arg == 'install_requires':
                        if isinstance(kw.value, (ast.List, ast.Tuple)):
                            for elt in kw.value.elts:
                                if isinstance(elt, ast.Str):
                                    parsed = parse_requirement_line(elt.s)
                                    if parsed:
                                        self.requires.append(parsed)
                    elif kw.arg == 'extras_require':
                        if isinstance(kw.value, ast.Dict): 
                            for elt in kw.value.keys:
                                parsed = parse_requirement_line(elt.value)
                                if parsed:
                                        self.requires.append(parsed)
    finder = FindInstallRequires()
    finder.visit(tree)
    return finder.requires

def parse_setup_cfg(filepath):
    config = configparser.ConfigParser()
    config.read(filepath)
    deps = []
    if config.has_section('options') and config.has_option('options', 'install_requires'):
        requires = config.get('options', 'install_requires').splitlines()
        for line in requires:
            parsed = parse_requirement_line(line)
            if parsed:
                deps.append(parsed)
    return deps

def find_dependency_files(project_dir):
    setup_files = []
    requirements_files = []
    
    # Only look in top-level directory
    for name in os.listdir(project_dir):
        if name in ['setup.py', 'setup.cfg']:
            setup_files.append(os.path.join(project_dir, name))
        elif name in ['requirements.txt', 'pyproject.toml']:
            requirements_files.append(os.path.join(project_dir, name))

    return setup_files, requirements_files

def get_all_dependencies(project_dir) -> list:
    pkl_path = os.path.join(project_dir, 'dep_version.pkl')
    
    try:
        with open(pkl_path, 'rb') as f:
            all_deps = pickle.load(f)
        return all_deps
    except Exception as e: pass

    global COMMIT_DATE
    repo_name, commit_sha = os.path.basename(os.path.normpath(project_dir)).rsplit("-", 1)
    COMMIT_DATE = get_commit_date(repo_name, commit_sha)
    if COMMIT_DATE is None: return []

    setup_files, requirements_files = find_dependency_files(project_dir)
    all_deps = []
    for file in setup_files:
        if file.endswith('setup.py'):
            deps = parse_setup_py(file)
            print(f"[setup.py] {file} -> {deps}")
            all_deps.extend(deps)
        elif file.endswith('setup.cfg'):
            deps = parse_setup_cfg(file)
            print(f"[setup.cfg] {file} -> {deps}")
            all_deps.extend(deps)

    for file in requirements_files:
        if file.endswith('txt'):
            deps = parse_requirements_txt(file)
            print(f"[requirements.txt] {file} -> {deps}")
        elif file.endswith('toml'):
            deps = parse_pyproject_toml(file)
            print(f"[pyproject.toml] {file} -> {deps}")
        all_deps.extend(deps)

    # Serialize
    with open(pkl_path, 'wb') as f:
        pickle.dump(all_deps, f)

    return all_deps

