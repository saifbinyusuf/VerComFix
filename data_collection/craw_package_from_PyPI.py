import os
import random
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging


# 配置日志
log_file = 'log.txt'
logging.basicConfig(
    filename=log_file,
    filemode='w',
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger()

def read_file(path):
    try:
        file = open(path, "r")
        data = file.read().splitlines()
        return data
    except Exception as e:
        logger.error(f"读取文件出错: {e}")


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
        logger.info(full_file_name + ' 已存在，跳过下载')
        return True

    download_dir = Path(project_dir)
    if download_dir.exists() is False:
        download_dir.mkdir(parents=True, exist_ok=True)
    try:
        logger.info("开始下载: " + full_file_name)
        req = requests.get(download_url, timeout=600)
        with open(full_file_name, 'wb') as code:
            code.write(req.content)
        logger.info("下载成功: " + full_file_name)
        return True
    except Exception as e:
        logger.error(f"下载出错 [{package_name} {package_version_name}]: {e}")
        return False

def process_package(package_name, url_template):
    package_url = url_template % package_name
    logger.info(f"请求包页面: {package_url}")
    try:
        r = requests.get(package_url, timeout=(5, 10))
        if r.status_code != 200:
            logger.warning(f"{package_name} 请求失败，休息1分钟")
            time.sleep(60)
            return

        soup = BeautifulSoup(r.text, 'lxml')
        all_packages = soup.find_all('a')

        download_tasks = []
        with ThreadPoolExecutor(max_workers=8) as executor:  # 可以根据机器性能调节 max_workers
            for package in all_packages:
                package_version_name = package.text
                if package_version_name.endswith('.tar.gz') or package_version_name.endswith('.zip'):
                    download_url = package.get('href')
                    future = executor.submit(download_with_retry, package_name, package_version_name, download_url)
                    download_tasks.append(future)

            for future in as_completed(download_tasks):
                future.result()

        logger.info(f"{package_name} 所有版本下载完成，休息10秒")
        time.sleep(10)

    except Exception as e:
        logger.error(f"{package_name} 请求异常: {e}")
        time.sleep(60)

def download_with_retry(package_name, package_version_name, download_url, max_retries=3):
    for attempt in range(1, max_retries + 1):
        success = download(package_name, package_version_name, download_url)
        if success:
            return True
        else:
            logger.warning(f"{package_name} {package_version_name} 下载失败，第 {attempt} 次尝试")
            if attempt < max_retries:
                time.sleep(60)
    logger.error(f"{package_name} {package_version_name} 下载失败，已达最大重试次数")
    return False

def craw_package():
    url_template = "https://pypi.org/simple/%s/"
    rank_list = read_file('./src/rank.txt')

    for rank in rank_list:
        package_name = rank.split('@@')[1]
        process_package(package_name, url_template)

if __name__ == '__main__':
    current_folder = Path(__file__).resolve().parent
    root_folder = current_folder.parent
    craw_package()
