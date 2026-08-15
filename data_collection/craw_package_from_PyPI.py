import os
import random
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from tqdm import tqdm


# Configure logging
log_file = 'log.txt'
logging.basicConfig(
    filename=log_file,
    filemode='w',
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger()

# Also log to console so progress is visible
_console = logging.StreamHandler()
_console.setLevel(logging.WARNING)
_console.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger.addHandler(_console)

def read_file(path):
    try:
        file = open(path, "r")
        data = file.read().splitlines()
        return data
    except Exception as e:
        logger.error(f"Failed to read file: {e}")


def write_to_file(file, context, write_type):
    try:
        file = open(file, write_type)
        file.write(context)
        file.write('\n')
    finally:
        file.close()


def get_page_by_bs4(url):
    r = requests.get(url)
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, 'lxml')
        return soup


def get_now():
    return time.strftime("%x %X")


def download(package_name, package_version_name, download_url):
    project_dir = root_folder / 'projects' / package_name

    full_file_name = str(project_dir / package_version_name)

    if Path(full_file_name).exists():
        logger.info(full_file_name + ' already exists, skipping')
        return True

    download_dir = Path(project_dir)
    if download_dir.exists() is False:
        download_dir.mkdir(parents=True, exist_ok=True)
    try:
        logger.info("Downloading: " + full_file_name)
        req = requests.get(download_url, timeout=600)
        with open(full_file_name, 'wb') as code:
            code.write(req.content)
        logger.info("Downloaded: " + full_file_name)
        return True
    except Exception as e:
        logger.error(f"Download failed [{package_name} {package_version_name}]: {e}")
        return False

def process_package(package_name, url_template, pkg_bar=None):
    package_url = url_template % package_name
    logger.info(f"Fetching package page: {package_url}")
    try:
        r = requests.get(package_url, timeout=(5, 10))
        if r.status_code != 200:
            logger.warning(f"{package_name} request failed, sleeping 1 min")
            time.sleep(60)
            return

        soup = BeautifulSoup(r.text, 'lxml')
        all_packages = soup.find_all('a')

        # Filter to sdist archives only
        sdist_packages = [
            p for p in all_packages
            if p.text.endswith('.tar.gz') or p.text.endswith('.zip')
        ]

        ver_bar = tqdm(total=len(sdist_packages), desc=f"  {package_name}", unit="ver", leave=False)

        download_tasks = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            for package in sdist_packages:
                package_version_name = package.text
                download_url = package.get('href')
                future = executor.submit(download_with_retry, package_name, package_version_name, download_url)
                download_tasks.append(future)

            for future in as_completed(download_tasks):
                future.result()
                ver_bar.update(1)

        ver_bar.close()
        logger.info(f"{package_name} all versions downloaded, sleeping 10s")
        time.sleep(10)

    except Exception as e:
        logger.error(f"{package_name} request error: {e}")
        time.sleep(60)

def download_with_retry(package_name, package_version_name, download_url, max_retries=3):
    for attempt in range(1, max_retries + 1):
        success = download(package_name, package_version_name, download_url)
        if success:
            return True
        else:
            logger.warning(f"{package_name} {package_version_name} download failed, attempt {attempt}")
            if attempt < max_retries:
                time.sleep(60)
    logger.error(f"{package_name} {package_version_name} download failed, max retries reached")
    return False

def craw_package():
    url_template = "https://pypi.org/simple/%s/"
    rank_list = read_file('./src/rank.txt')

    pkg_bar = tqdm(rank_list, desc="Packages", unit="pkg")
    for rank in pkg_bar:
        package_name = rank.split('@@')[1]
        pkg_bar.set_postfix_str(package_name)
        process_package(package_name, url_template, pkg_bar)

if __name__ == '__main__':
    current_folder = Path(__file__).resolve().parent
    root_folder = current_folder.parent
    craw_package()
