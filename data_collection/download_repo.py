import os
import pickle
import requests
from tqdm import tqdm
from pathlib import Path
from datetime import datetime

from repo_conf import DOWN_CONF, HEADERS

# ensure dir exists
DUMP_BASE_DIR = DOWN_CONF['download_base_dir']
try:
    Path(DUMP_BASE_DIR).mkdir(parents=True, exist_ok=True)  # parents=True creates parent directories
except OSError as error:
    print(f"[Err] Fail to create directory: '{DUMP_BASE_DIR}', errMsg: {error}")
    exit(0)


# Download all specified repos (specific branch)
def download_all(upstream: list) -> list:
    download_links = [] # for manual download fallback

    # Get the latest commit SHA before cutoff date (2025-06-01)
    def _get_newest_commit_sha(repo_full_name: str, branch: str) -> str:
        try:
            response = requests.get(
                url=f'https://api.github.com/repos/{repo_full_name}/commits',
                params={
                    'sha': branch,
                    'until': '2025-05-31T23:59:59',
                    'per_page': 1, 'page': 1  # auto sorted by newest
                },
                headers=HEADERS
            )
        except Exception as e:
            print(f'[Fail] request {repo_full_name} - {branch}, {e}')
            return "", ""
        
        res = response.json()
        if res:
            try:
                commit_date = commit_date = datetime.strptime(
                                res[0]['commit']['committer']['date'], "%Y-%m-%dT%H:%M:%SZ"
                            ).strftime("%Y-%m-%d")
                commit_sha = res[0]['sha']
                return commit_sha, commit_date
            except Exception as e:
                print(f'[Fail] parse {repo_full_name} - {branch}, {e}')
                return "", ""
        else:   return "", ""
    
    # Download a specific repo, returns tuple on failure
    def _download(commit_sha: str, repo_full_name: str, branch: str) -> None | tuple:
        link = f"https://github.com/{repo_full_name}/archive/{commit_sha}.zip"
        download_links.append(link)

        dump_file = os.path.join(DUMP_BASE_DIR, f"{repo_full_name.split('/')[1]}-{commit_sha}.zip")
        if os.path.exists(dump_file): return None

        response = requests.get(
            f"https://api.github.com/repos/{repo_full_name}/zipball/{commit_sha}", # GitHub API
            headers=HEADERS,
            stream=True,
            timeout=(30, 60)
        )

        if response.status_code == 200:
            try:
                with open(dump_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=1048576): # 1MB / time
                        f.write(chunk)
                return None
            except Exception as e:
                print(f'[Err] Fail to save {repo_full_name}@{branch}, errMsg: {e}')     
        else:
            print(f"[Err] Fail to download {repo_full_name}@{branch}, errMsg: {response.text}")
        return (repo_full_name, branch)

    failed, repo_commit_info = [], []
    for repo_full_name, branch in tqdm(upstream):
        # get latest commit sha
        commit_sha, commit_date = _get_newest_commit_sha(repo_full_name, branch)
        repo_info = repo_full_name.rsplit('/', 1)
        repo_commit_info.append((*repo_info, commit_sha, commit_date))
        if not commit_sha: continue

        # download repo
        is_fail = _download(commit_sha, repo_full_name, branch)
        if is_fail: failed.append(is_fail)

    print(f'[LOG] Download finished! {len(failed)} failed.')

    return failed, download_links, repo_commit_info


if __name__ == '__main__':
    print("[LOG] Start to download selected repos ...")

    # 1 Load (full_repo_name, branch)
    file_url = DOWN_CONF['upstream']
    try:
        with open(file_url, 'rb') as f:
            selected_repos = pickle.load(f)
    except FileNotFoundError:
        print(f"[Err] Can't find '{file_url}'. Maybe you should run 'select_repo.py' first.")
    except pickle.UnpicklingError:
        print(f"[Err] File {file_url} cracked")
    except Exception as e:
        print(f"[Err] {e}")
  
    # 2 Download all repos at specific commit
    _, download_links, repo_commit_info = download_all(selected_repos)
    
    # 3 Serialize repo_commit_info.pkl
    try:
        with open('repo_commit_info.pkl', 'wb') as f:
            pickle.dump(repo_commit_info, f)
    except Exception as e:
        print(f'[Err] Fail to save repo_commit_info.pkl, {e}')