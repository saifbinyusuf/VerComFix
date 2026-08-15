import pickle, argparse, pymysql
import torch.cuda
from tqdm import tqdm

from complete import query_api_task_info
from tasks import APILevelRepairTask
from global_config import DB_CONFIG, GITHUB_CODE_DOWNLOAD_BASE_DIR
from models import MODEL_FACTORY, CodeLLMCompletionEngine, GLMCompletionEngine, CopilotCompletionEngine

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('-m', '--model', help='model name', type=str, required=True)
arg_parser.add_argument('-g', '--gpu',  help='GPU index', type=int, default=6)

DATA_BASE_DIR = GITHUB_CODE_DOWNLOAD_BASE_DIR
MAX_CTX_LINE = 100

conn = pymysql.connect(**DB_CONFIG)
cursor = conn.cursor()

if __name__ == '__main__':
    # parse args
    args = arg_parser.parse_args()
    GPU   = args.gpu
    if torch.cuda.is_available():
        print(f'[Info] Using GPU ({GPU})')
        torch.cuda.set_device(GPU)

    # select model
    MODEL = args.model
    valid_models = list(MODEL_FACTORY.keys())
    if not MODEL in valid_models:
        print(f'[Err] Invalide model: "{MODEL}". Please select from: {valid_models}')
        exit(0)
    print(f'[LOG] Sample: using model "{MODEL}"')

    # init engine
    if MODEL == 'copilot':
        project_root, app_name = MODEL_FACTORY[MODEL]()
        app_name = app_name if app_name else 'Visual Studio Code'
        engine = CopilotCompletionEngine(project_root, app_name=app_name)
    elif MODEL in ['deepseek-v3', 'gpt-4o']:
        client, model, price = MODEL_FACTORY[MODEL]()
        engine = GLMCompletionEngine(client, model, price)
    elif MODEL in ['gemini-2.5-flash']:
        client, model, price = MODEL_FACTORY[MODEL]()
        engine = GLMCompletionEngine(client, model, price, useGemini=True)
    else:
        model, tokenizer = MODEL_FACTORY[MODEL]()
        engine = CodeLLMCompletionEngine(model, tokenizer)
    print('[LOG] Model initialized')

    # load tasks (api_level) => from the corresponding file
    with open(f'./to_repair/{MODEL}.pkl', 'rb') as f:
        tasks = pickle.load(f)
        
    repaired, results = 0, []
    # recover
    try:
        with open(f'./repaired/{MODEL}_max_task.txt', 'r', encoding='utf-8') as f:
            min_idx = int(f.read())+1
        print(f'[LOG] Recover from task_id {min_idx}')
    except Exception:
        min_idx = 0
        print(f'[LOG] Start from scratch')

    for idx in tqdm(range(min_idx, len(tasks))):
        task_info = tasks[idx]
        tid, stmt, pred_fqn, desc, api_sig = task_info

        # construct task
        tpl, repo, file, start, end, constrain_str = query_api_task_info(cursor, tid)
        task = APILevelRepairTask(
            stmt, pred_fqn,
            desc, api_sig,
            tpl=tpl, version=constrain_str,
            repo=repo, file=file,
            gt_start_lineno=start-1,
            rctx_start_lineno=end
        )

        # pred
        if MODEL=='codegen-6b': res = engine.complete(task, max_len=2048)
        else:                   res = engine.complete(task)
        
        results.append((tid, res))
        res = (tid, res)
        with open(f'./repaired/{MODEL}.pkl', 'wb') as f:
            pickle.dump(results, f)
        with open(f'./repaired/{MODEL}_max_task.txt', 'w', encoding='utf-8') as f:
            f.write(str(idx))
