import os
from pathlib import Path
import shutil
import tempfile
import logging
from packaging.version import parse as parse_version
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

log_file = 'unpack_log.txt'
logging.basicConfig(
    filename=log_file,
    filemode='w',
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger()

_console = logging.StreamHandler()
_console.setLevel(logging.WARNING)
_console.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger.addHandler(_console)

def get_packages_path_order_by_time(packages_dir):
    # logger.info(f"Scanning directory (by time): {packages_dir}")
    packages_list = os.listdir(packages_dir)
    if packages_list:
        packages_list = sorted(packages_list, key=lambda x: os.path.getmtime(os.path.join(packages_dir, x)))
        return packages_list
    return []

def get_packages_path_order_by_name(packages_dir):
    # logger.info(f"Scanning directory (by version): {packages_dir}")
    packages_list = os.listdir(packages_dir)

    def extract_version(folder_name):
        parts = folder_name.rsplit('-', 1)
        if len(parts) == 2:
            return parse_version(parts[1])
        return parse_version("0.0.0")  # fallback

    if packages_list:
        packages_list = sorted(packages_list, key=extract_version)
        return packages_list

    return []

def unpack_single_package(project_path, packages_dir, ff):
    src_file = project_path / ff
    version_folder_name = ff.replace('.zip', '').replace('.tar.gz', '')
    dest_dir = packages_dir / version_folder_name

    if dest_dir.exists():
        logger.info(f"{ff} already exists, skipping")
        return

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            shutil.unpack_archive(str(src_file), tmpdir)
            top_level_items = list(Path(tmpdir).iterdir())

            if len(top_level_items) == 1 and top_level_items[0].is_dir():
                shutil.move(str(top_level_items[0]), dest_dir)
            else:
                dest_dir.mkdir()
                for item in top_level_items:
                    if item.is_dir():
                        shutil.copytree(item, dest_dir / item.name)
                    else:
                        shutil.copy2(item, dest_dir / item.name)

        logger.info(f"Extracted: {ff}")
    except Exception as e:
        logger.error(f"Extract failed {ff}: {e}")

def main():
    pkg_names = [f for f in os.listdir(projects) if (Path(projects) / f).is_dir()]
    pkg_bar = tqdm(pkg_names, desc="Packages", unit="pkg")

    for f in pkg_bar:
        project_path = Path(projects) / f
        packages_dir = Path(packages) / f
        packages_dir.mkdir(parents=True, exist_ok=True)
        pkg_bar.set_postfix_str(f)

        archives = get_packages_path_order_by_time(project_path)
        if not archives:
            continue

        tasks = []
        ver_bar = tqdm(total=len(archives), desc=f"  {f}", unit="ver", leave=False)

        with ThreadPoolExecutor(max_workers=8) as executor:
            for ff in archives:
                future = executor.submit(unpack_single_package, project_path, packages_dir, ff)
                tasks.append(future)

            for future in as_completed(tasks):
                future.result()
                ver_bar.update(1)

        ver_bar.close()

    print("All packages extracted.")

if __name__ == '__main__':
    current_folder = Path(__file__).resolve().parent
    projects = current_folder.parent / 'projects'
    packages = current_folder.parent / 'packages'
    main()
