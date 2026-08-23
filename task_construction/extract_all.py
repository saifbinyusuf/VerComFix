import os, sys, pickle
from tqdm import tqdm
from api_extractor import extract_repo_api, extract_repo_func

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from global_config import GITHUB_CODE_DOWNLOAD_BASE_DIR

# Root path for repo source code
REPO_DATA_DIR = GITHUB_CODE_DOWNLOAD_BASE_DIR

def get_folders_in_directory(path: str):
    """Get all folder names under the specified directory"""
    with os.scandir(path) as entries:
        return [entry.name for entry in entries if entry.is_dir()]

def get_target_repo_names():
    """Get repos that have commit date info"""
    file = os.path.join(os.path.dirname(__file__), '..', 'data_collection', 'repo_commit_info.pkl')
    repo_infos = []
    try:
        with open(file, 'rb') as f:
            repo_infos = pickle.load(f)
    except FileNotFoundError:
        print(f"[Err] Can't find '{file}'. Maybe you should run 'select_repo.py' first.")
    except pickle.UnpicklingError:
        print(f"[Err] File {file} cracked")
    except Exception as e:
        print(f"[Err] {e}")
    return set(info[1] for info in repo_infos)
    
if __name__ == '__main__':
    folder_names = get_folders_in_directory(REPO_DATA_DIR)
    target_names = get_target_repo_names()

    for folder_name in tqdm(folder_names):
        try:
            repo_name, commit_sha = folder_name.rsplit("-", 1)
            if not repo_name in target_names: continue
        except ValueError:
            continue
        
        try:
            repo_base_dir = os.path.join(REPO_DATA_DIR, folder_name)
            extract_repo_api(repo_base_dir) # api
            extract_repo_func(repo_base_dir) # func
        except Exception as e:
            print(f'[Err] fail to handle {folder_name}')
            print(f'\t{e}')