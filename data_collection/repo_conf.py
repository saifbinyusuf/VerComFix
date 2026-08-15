import os, sys
import configparser
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from global_config import GITHUB_CODE_DOWNLOAD_BASE_DIR

CONFIG_FILE = "conf.ini"

# Read token from environment variable
token = os.getenv('GITHUB_TOKEN')
if token:
    print('[LOG] Successfully found <GITHUB_TOKEN>')
    HEADERS = {"Authorization": f"token {token}"}
else:
    print('[Error] Can\'t found <GITHUB_TOKEN>')
    exit(0)

# parse config
config = configparser.ConfigParser()
try:
    # load file
    config.read(CONFIG_FILE, encoding='utf-8')
    # transform to dict
    conf = {}
    for section in config.sections():
        conf[section] = dict(config.items(section))
except configparser.Error as e:
    raise ValueError(f"[Err] Fail to parse config {e}")
except UnicodeDecodeError:
    raise ValueError("[Err] Config file is not encoded with utf-8")
except Exception as e:
    raise ValueError(f"[Err] Fail to handle config {e}")

SPIDER_CONF = conf['spider']
SPIDER_CONF['stars']             = int(SPIDER_CONF['stars'])
SPIDER_CONF['forks']             = int(SPIDER_CONF['forks'])
SPIDER_CONF['isfork']            = bool(SPIDER_CONF['isfork'].lower() == 'true')
SPIDER_CONF['fork_update_range'] = int(SPIDER_CONF['fork_update_range'])
SPIDER_CONF['update_range']      = int(SPIDER_CONF['update_range'])
SPIDER_CONF['create_range']      = f"{SPIDER_CONF['create_bg']}..{SPIDER_CONF['create_ed']}"
SPIDER_CONF['page_size']         = min(int(SPIDER_CONF['page_size']), 100)
SPIDER_CONF['max_res']           = min(int(SPIDER_CONF['max_res']), 1000)

ED_DATE = datetime.strptime(SPIDER_CONF['cutoff_date'], "%Y-%m-%d")

DEP_CONF = conf['dep_filter']
DEP_CONF['min_n_dependency'] = int(DEP_CONF['min_n_dependency'])

DOWN_CONF = {
    'upstream':          DEP_CONF['dump_file'],
    'download_base_dir': GITHUB_CODE_DOWNLOAD_BASE_DIR
}