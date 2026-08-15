import re, ast, time, math, toml, pickle, requests
from tqdm import tqdm
from datetime import datetime, timedelta
from packaging.requirements import Requirement, InvalidRequirement

from repo_conf import SPIDER_CONF, DEP_CONF, HEADERS, ED_DATE

MIN_STARS         = SPIDER_CONF['stars']
IS_FORK           = SPIDER_CONF['isfork']
FORK_UPDATE_RANGE = SPIDER_CONF['fork_update_range']
MIN_FORKS         = SPIDER_CONF['forks']
CREATE_RANGE      = SPIDER_CONF['create_range']
UPDATE_RANGE      = SPIDER_CONF['update_range']
PAGE_SIZE         = SPIDER_CONF['page_size']
MAX_RES           = SPIDER_CONF['max_res']
DAY_GAP           = 90 # initial interval
DEP_FILES = {          # dependency files to search for
    'requirements.txt',
    'pyproject.toml',
    'setup.py'
}

DUMP_FILE     = DEP_CONF['dump_file']
MIN_N_DEP     = DEP_CONF['min_n_dependency']
CONDA_PATTERN = r"(.+?)=(.+?)=(.+)"
MIRROR = DEP_CONF['mirror']
if MIRROR: print(f'[LOG] Using mirror: {MIRROR}')


# Get repos created within CREATE_RANGE, with commits within UPDATE_RANGE, star>=50, fork>=10
def basic_filter(update_range: int) -> list:
    def _get_repo_list(bg_dt: datetime, time_gap: int, page: int=1, tot_page: int=0) -> list:
        """
        func: filter repos in Python & Star>=50, Fork>=10 & Update within required time range
        return: list<str> (repo Full Name)
        """
        def _get_full_name(repos: list) -> list:
            """fork status matches config (default: not fork), return full_name"""
            return list(map(
                lambda item: item['full_name'],
                filter(lambda item: item['fork'] == IS_FORK, repos)
            ))
        def _format_time(dt: datetime) -> str:
            return min(dt, ED_DATE).strftime('%Y-%m-%d')
        
        # time_range = xxxx-xx-xx..xxxx-xx-xx closed interval
        time_range = f"{_format_time(bg_dt)}..{_format_time(bg_dt+timedelta(time_gap))}"
        # send request
        response = requests.get(
            url="https://api.github.com/search/repositories",
            params={
                'q': f'language:python stars:>={MIN_STARS} forks:>={MIN_FORKS} pushed:{time_range} created:{CREATE_RANGE}',
                'per_page': PAGE_SIZE,
                'page': page
            },
            headers=HEADERS
        )

        status = response.status_code
        if status==200:
            tot_items = response.json()['total_count']

            if tot_items > MAX_RES:
                if time_gap == 0:
                    print(f"[Warn] {time_range} still > 1k")
                    return []
                else:  
                    sub_gap = time_gap//2
                    print(f'「{time_range}」=> DEVIEDE {_format_time(bg_dt)}, {_format_time(bg_dt+timedelta(days=sub_gap))}')
                    return \
                        _get_repo_list(bg_dt, sub_gap) + \
                        _get_repo_list(bg_dt+timedelta(days=sub_gap+1), time_gap-1-sub_gap) # DEBUG: there is indeed an issue here
            else:
                if page==1:
                    tot_page = max(1, math.ceil(tot_items / PAGE_SIZE))
                    print(f'[LOG] {time_range}, got <{tot_items}> to filter, ')
                    
                    res = _get_full_name(response.json()['items'])

                    for p in range(2, tot_page+1):
                        try:
                            page_res = _get_repo_list(bg_dt, time_gap, p, tot_page)
                            res += page_res
                        except Exception:
                            print(f'[Error] fetch Page<{p}/{tot_page}>, {type(page_res) = }')
                else:
                    res = _get_full_name(response.json()['items'])
        
                print(f'\tPage: {page}/{tot_page}, Got {len(res)}')
                return res
            
        elif status==403 and ('rate limit' in response.text.lower()):
            reset_time = int(response.headers['X-RateLimit-Reset'])
            sleep_time = reset_time - int(time.time()) + 5
            time.sleep(sleep_time)
            return _get_repo_list(bg_dt, time_gap, page, tot_page)
        
        else:
            print(f'[Err] Fail to fetch: {time_range}')
            return []

    repos = []
    date = ED_DATE-timedelta(days=update_range)
    while date < ED_DATE:
        repos += _get_repo_list(date, DAY_GAP)
        date += timedelta(days=DAY_GAP)
    print(f'[LOG] Got {len(repos)} repo that has Stars>=50 && Forks>=10')
    return repos


# Filter repos with active forks
def active_fork_filter(upstream: list, fork_active_range: int) -> list:
    # Check if repo has an active fork within FORK_UPDATE_RANGE
    def _has_active_fork(repo_full_name: str) -> bool:
        cutoff_date = ED_DATE - timedelta(days=fork_active_range)
        try: 
            response = requests.get(
                headers=HEADERS,
                url = f"https://api.github.com/repos/{repo_full_name}/forks",
                params={ "sort": "newest", "per_page": 100 }
            )
            response.raise_for_status()
            forks = response.json()
            if not forks: return False
            for fork in forks:
                updated_at = datetime.fromisoformat(fork["updated_at"].replace("Z", ""))
                if updated_at >= cutoff_date:
                    return True
            return False
        except requests.exceptions.RequestException as e:
            print(f'[ERR] Fail to fetch {repo_full_name}')
            return False
        except ValueError as e:
            print(f'[ERR] Fail to parse {repo_full_name}')
            return False


    filtered = []
    for full_name in tqdm(upstream):
        if _has_active_fork(full_name):
            filtered.append(full_name)
    print(f'[LOG] Got {len(filtered)} repo that has active fork within {fork_active_range} days')
    return filtered


# Filter repos that have dependency files (DEP_FILES)
def dependency_file_filter(upstream: list) -> list:
    def _has_dependency_file(repo_full_name: str) -> bool | list:
        """
        param: <str> repo_full_name = '{author}/{repo}'
        return: <bool> False (not found), <str> file_download_url (dependency file name in root path)
        """
        response = requests.get(
            url=f'https://api.github.com/repos/{repo_full_name}/contents', # default branch
            headers=HEADERS
        )
        status = response.status_code
        if status==200:
            down_urls = list(map(
                lambda item: item['download_url'],
                filter(
                    lambda item: item['name'].lower() in DEP_FILES,
                    response.json()
                )
            ))
            return down_urls if len(down_urls)==1 else False
        elif status==403 and ('rate limit' in response.text.lower()):
            reset_time = int(response.headers['X-RateLimit-Reset'])
            sleep_time = reset_time - int(time.time()) + 5
            time.sleep(sleep_time)
            return _has_dependency_file(repo_full_name)
        else:
            print(f'[Error] Fail to handle <{repo_full_name}>')
            return False

    filtered = []
    for full_name in tqdm(upstream):
        dependency_file = _has_dependency_file(full_name)
        if dependency_file:
            filtered.append((full_name, dependency_file))
    print(f'[LOG] Got {len(filtered)} repo that has dependency file')
    return filtered

# Filter repos with dependency count >= MIN_NDEP(5)
def dependency_coverage_filter(upstream: list) -> list:
    # Get branch
    def _get_branch(url: str) -> str:
        parts = url.split('/')
        if len(parts) >= 6:
            return parts[5]
        else:
            print(f'[Err] Invalid GitHub raw URL format: {url}')
            return ""
    # Return dependency count: -1 means failed
    def _cnt_dep(down_url: str) -> int:
        # Get file extension
        def _get_ext(url: str) -> str:
            match = re.search(r'\.([a-zA-Z0-9]+)(?:[\?#]|$)', url)
            return match.group(1).lower() if match else ""
        
        # Download dependency file
        def _get_dep_file(down_url: str) -> str:
            """
            params:
                down_url(str): "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
            return:
                str: rtn "" when failed
            """
            # Use mirror
            if MIRROR: down_url = down_url.replace("raw.githubusercontent.com", MIRROR) 
            try:
                res = requests.get(url=down_url, headers=HEADERS)
                if 'Not Found' in res.text: 
                    print(f"[Err] File don't exist {down_url}, errMsg: {res.text}")
                    return ""
                else: 
                    return res.text
            except Exception as e:
                print(f"[Err] Fail to fetch {down_url}, errMsg: {e}")
                return ""
        
        def _toml_handler(text: str) -> int:
            try:
                config = toml.loads(text) # parse TOML format string
            except Exception as e:
                print(f"[Err] Fail to parse toml config: {e}")
                return -1

            deps = set()
            try: # core dependencies
                deps |= set(config["project"]["dependencies"])
            except KeyError: pass
            try: # optional dependency groups
                optional_deps = config["project"]["optional-dependencies"] # dict
                for optional_dep_group in optional_deps.values(): 
                    deps |= set(optional_dep_group)
            except KeyError: pass

            return len(deps)

        def _txt_handler(text: str) -> int:
            """
            """
            _SKIP_LINE = "#-_`"
            def _clean_req_line(line: str) -> str:
                pattern =  r"^([^#;@\\]+)"
                match = re.search(pattern, line)
                if match: line = match.group(0)
                match = re.search(r'^(.*?)--(.*?)$', line)
                if match: line = match.group(1)
                return line.strip().replace('\ufeff', '')
            
            try:
                deps = set()
                for line in text.splitlines():
                    line = _clean_req_line(line)
                    # Skip empty lines, comments, index substitutions
                    if not line or line[0] in _SKIP_LINE: continue
                        
                    req_text = line
                    if req_text:
                        if req_text.startswith("pip install"): 
                            deps |= set(req_text[12:].split(' '))
                            continue
                        if req_text.startswith('git+'): 
                            deps.add(req_text[4:])
                            continue
                        match = re.search(CONDA_PATTERN, req_text)
                        if match:
                            deps.add(match.group(1))
                            continue
                        req_text = re.sub(r"\+.*$", "", req_text)  
                        try: 
                            deps.add(Requirement(req_text).name)
                        except InvalidRequirement as e:
                            print(f"[Warn] Fail to parse txt line: '{line}', {e}")
                            return -1

                return len(deps)
            except Exception as e:
                print(f"[Err] Fail to parse txt config: {e}")
                return -1

        def _py_handler(text: str) -> int:
            try:
                deps = set()
                ast_tree = ast.parse(text)

                for node in ast.walk(ast_tree):
                    if not isinstance(node, ast.Call): continue
                    if not (isinstance(node.func, ast.Name) and node.func.id == 'setup'): continue 
                    for kw in node.keywords:
                        if kw.arg == 'install_requires' and isinstance(kw.value, (ast.List, ast.Tuple)):  
                            deps |= set(map(
                                lambda el: el.value,
                                kw.value.elts
                            ))
                        elif kw.arg == 'extras_require' and isinstance(kw.value, ast.Dict): 
                            deps |= set(map(
                                lambda el: el.value,
                                kw.value.keys
                            ))
                return len(deps)
            except Exception as e:
                print(f"[Err] Fail to parse py config: {e}")
                return -1

        _DEP_HANDLER = {
            'txt':  _txt_handler,
            'toml': _toml_handler,
            'py':   _py_handler
        }

        try:
            dep_type = _get_ext(down_url)
            dep_file = _get_dep_file(down_url)
            if dep_file: return _DEP_HANDLER[dep_type](dep_file)
            else:        return -1 
        except ValueError:
            print(f'[Err] Illegal dependency file: {dep_file}')
            return -1
    
    selected = [] 
    for repo_full_name, down_urls in tqdm(upstream):
        if len(down_urls) == 0: continue 
        n_dep = max(list(map(
            lambda down_url: _cnt_dep(down_url),
            down_urls
        )))
        if n_dep >= MIN_N_DEP:
            selected.append((repo_full_name, _get_branch(down_urls[0])))
    
    print(f'[LOG] Finally select {len(selected)} repos.')

    return selected


if __name__ == '__main__':
    print("[LOG] Start to select repos ...")

    selected_repos = \
    dependency_coverage_filter( # 4 have at Least 5 Dependencies
        dependency_file_filter( # 3 have Depenfency File
            active_fork_filter( # 2 have Active Fork
                basic_filter(   # 1 Basic Filter
                    update_range=UPDATE_RANGE
                ), 
                fork_active_range=FORK_UPDATE_RANGE
            )))
    
    # 5 Serialize Result
    selected_repos = list(set(selected_repos))
    try:
        with open(DUMP_FILE, 'wb') as f:
            pickle.dump(selected_repos, f)
        print(f'[LOG] Successfully dump to {DUMP_FILE}')
    except Exception:
        print('[Error] Fail to dump result')