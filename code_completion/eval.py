import pickle, json, os, sys, pymysql, argparse
from tqdm import tqdm
from tabulate import tabulate
from complete import COMPLETION_RESULT_DIR
from tasks import APILevelTask, FunctionLevelTask
from myTypes import CompletionType
from utils import CodeHandler as CH
from utils import get_completion_type, extract_outermost_function_call, extract_first_function_call, has_function_call, get_cleaned_func

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from global_config import DB_CONFIG, GITHUB_CODE_DOWNLOAD_BASE_DIR, RESULT_BASE_DIR
from task_construction.get_api_signatures   import get_API_calls_from_funcnode
from task_construction.api_extractor        import build_package_version_dict
from task_construction.version_resolver     import get_all_dependencies
from task_construction.arg_validity_checker import ArgumentsAnalyser

DATA_BASE_DIR = GITHUB_CODE_DOWNLOAD_BASE_DIR
REPAIR_TASK_DIR = os.path.join(RESULT_BASE_DIR, 'to_repair')

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('-m', '--model', help='model name', type=str, required=True)
arg_parser.add_argument('-f', '--func', help='complete function level tasks', action='store_true')

# DB connection
conn = pymysql.connect(**DB_CONFIG)
cursor = conn.cursor()

def get_task(tid):
    if API:
        cursor.execute(f"SELECT * FROM api_calls WHERE id={tid}" )
        tid, fqn, abs_file, start, end, constrain_type, constrain_str = cursor.fetchone()
    else:
        cursor.execute(f"SELECT * FROM func_task WHERE id={tid}" )
        tid, fqn, abs_file, start, end, constrain_type, constrain_str, bg_off, ed_off = cursor.fetchone()

    if constrain_str.startswith('~~'): constrain_str = '==' + constrain_str[2:]
    tpl = fqn.split('.')[0]
    relative_dir = abs_file[len(DATA_BASE_DIR)+1:]
    repo, file = relative_dir.split('/', 1)

    if API:
        return APILevelTask(
            tpl=tpl, version=constrain_str,
            repo=repo, file=file,
            gt_start_lineno=start-1,
            rctx_start_lineno=end
        ) 
    else:
        return FunctionLevelTask(
            bg_off, ed_off,
            tpl=fqn, version=constrain_str,
            repo=repo, file=file,
            gt_start_lineno=start-1,
            rctx_start_lineno=end
        )

def get_normed_fqn(task, stmt, rtn_str=False):
    try:
        call_str, name, call_node = extract_outermost_function_call(stmt)
    except Exception as e:
        name = extract_first_function_call(stmt)
        if rtn_str: return name if name else '', '', None
        else:       return name if name else ''

    class2obj = task.class2obj
    instance2class = task.instance2class
    id2fullname = task.id2fullname

    name_parts = name.split('.')
    if len(name_parts) == 1 and name in instance2class:
        name = instance2class[name] + '.' + name
    elif name_parts[0] in class2obj and len(name_parts) == 2:
        name = class2obj[name_parts[0]] + '.' + name_parts[1]
    
    name_parts = name.split('.')  
    if name_parts[0] in id2fullname:
        full_name = id2fullname[name_parts[0]] + '.' + '.'.join(name_parts[1:])
    else:
        full_name = name

    if full_name.endswith('.'): full_name = full_name[:-1]
    
    if rtn_str: return full_name, call_str, call_node
    else:       return full_name

def eval_task(pred_stmt, task):
    if not pred_stmt:
        return CompletionType.EMPTY, '', ''
    
    if not has_function_call(pred_stmt):
        return CompletionType.OTHERS, '', ''

    # Exact Match
    pred_stmt.replace(" ", "").replace("\n", "")
    gt_stmt = task.gt.replace(" ", "").replace("\n", "")
    if pred_stmt == gt_stmt: # Exact Match
        return CompletionType.CR, '', ''
    
    pred_fqn, pred_call_str, pred_call_node = get_normed_fqn(task, pred_stmt, True)
    gt_fqn,   gt_call_str,   gt_call_node   = get_normed_fqn(task, gt_stmt,   True)

    # API Name Match
    if pred_fqn == gt_fqn:
        try:
            pred_args = ArgumentsAnalyser(pred_call_str).extract_arguments_info(pred_call_node)
        except Exception as e:
            pred_args = {'keyword_args':[], 'positional_args':[]}
        try: 
            gt_args = ArgumentsAnalyser(gt_call_str).extract_arguments_info(gt_call_node)
        except Exception as e:
            gt_args = {'keyword_args':[], 'positional_args':[]}

        pred_keywords   = [item['keyword_name'] for item in pred_args['keyword_args']]
        gt_keywords     = [item['keyword_name'] for item in gt_args['keyword_args']]

        diff_keywords = set(pred_keywords) - set(gt_keywords)
        diff_arg_num  = ((len(pred_args['keyword_args'])+len(pred_args['positional_args']))!=(len(gt_args['keyword_args'])+len(gt_args['positional_args'])))

        if diff_keywords or diff_arg_num:
            c_type, desc = get_completion_type(api_sig, pred_stmt, pred_fqn, gt_fqn)
            return c_type, desc, pred_fqn
        else:
            return CompletionType.CR, '', ''
    else:
        return CompletionType.BCR, 'Method Name Mismatch', pred_fqn

if __name__ == '__main__':
    args  = arg_parser.parse_args()
    MODEL = args.model
    API   = not args.func
    print(f'[LOG] Evaluating {MODEL} in 「{"API" if API else "Func"}」Level Tasks')

    # init 
    v_types = ['pinned', 'range', 'unconstrained']
    a_types = ['name', 'parameter', 'returntype']

    for OMIT in [False, True]:
        to_repair = []
        cnt = [0 for _ in CompletionType]

        try:
            todos = []
            with open(f'{COMPLETION_RESULT_DIR}/{MODEL}_{OMIT}_{"API" if API else "Func"}_Completion.pkl', 'rb') as f:
                while True:
                    try:
                        todos.append(pickle.load(f))
                    except Exception: break
        except Exception:
            print(f'[Err] Fail to calc: {MODEL} {" (OMIT)" if OMIT else ""} {"API" if API else "Func"} Level')
            continue
        
        # Need to count separately according to version_costrain_type \ api_change_type
        if not OMIT: 
            v_cnt = {}
            for v_t in v_types: v_cnt[v_t] = [0 for _ in CompletionType]
            with open(f'./{"API" if API else "Func"}_Level_Tids_vtype.pkl', 'rb') as f:
                v_ids = pickle.load(f)
                pinned_ids = set(v_ids['pinned'])
                range_ids  = set(v_ids['range'])
                uncon_ids  = set(v_ids['unconstrained'])

            a_cnt = {}
            for a_t in a_types: a_cnt[a_t] = [0 for _ in CompletionType]
            with open(f'./{"API" if API else "Func"}_Level_Tids_atype.pkl', 'rb') as f:
                a_ids = pickle.load(f)
                name_ids  = set(a_ids['name'])
                param_ids = set(a_ids['parameter'])
                retn_ids  = set(a_ids['returntype'])

        for todo in tqdm(todos):
            tid = todo[0]
            task = get_task(tid)

            if API:
                pred_stmt = todo[1]
                c_type, desc, _pred_fqn = eval_task(pred_stmt, task)
            else:
                tid, pred_func, _ = todo
                pred_func = CH.clean_comments(pred_func)
 
                # Iterate through all API_CALLs
                deps = get_all_dependencies(os.path.join(DATA_BASE_DIR, task.repo))
                dep_dict = build_package_version_dict(deps)
                func_src = f'{task.head}\n{get_cleaned_func(pred_func)}'
                func_calls = get_API_calls_from_funcnode(func_src, '', dep_dict, task.class2obj, task.instance2class, task.id2fullname)

                if func_calls:
                    c_type = CompletionType.OTHERS

                    for func_call in func_calls:
                        bg_off, ed_off = func_call['lineno'], func_call['end_lineno']
                        lines = func_src.split('\n')
                        _stmt = ''.join(lines[bg_off-1:ed_off]).strip()

                        _c_type, _desc, _pred_fqn = eval_task(_stmt, task)
                        if _c_type == CompletionType.CR:
                            c_type = CompletionType.CR
                            break
                        elif _c_type == CompletionType.BCR:
                            c_type = CompletionType.BCR
                else:
                    c_type = CompletionType.EMPTY
 
            # count
            cnt[c_type.value-1] += 1

            # Count version / api_change
            if not OMIT: 
                # version_constrain
                if tid in pinned_ids: v_cnt['pinned'][c_type.value-1] += 1
                if tid in range_ids:  v_cnt['range'][c_type.value-1] += 1
                if tid in uncon_ids:  v_cnt['unconstrained'][c_type.value-1] += 1

                # api_change_type
                if tid in name_ids:  a_cnt['name'][c_type.value-1] += 1
                if tid in param_ids: a_cnt['parameter'][c_type.value-1] += 1
                if tid in retn_ids:  a_cnt['returntype'][c_type.value-1] += 1
            
            # Count cases that need repair
            if API and not OMIT \
                and tid in pinned_ids\
                and c_type == CompletionType.BCR:
                
                cursor.execute(f"SELECT api_name, parameters, has_return FROM {'api' if API else 'func'}_gt_info WHERE tid={tid}")
                api_name, parameters, has_return = cursor.fetchone()
                api_sig = (api_name, json.loads(parameters), True if has_return else False)

                to_repair.append((tid, pred_stmt, _pred_fqn, desc, api_sig))
        
        # Store cases that need repair
        if API and not OMIT:
            with open(f'{REPAIR_TASK_DIR}/{MODEL}.pkl', 'wb') as f:
                print(f'Got {len(to_repair)} tasks to repair')
                pickle.dump(to_repair, f)
        
        # Print calculation results
        print(f'% {MODEL} {OMIT} {"API" if API else "Func"} %')
        print(f'## Total ({len(todos)})')
        print(tabulate(
            [cnt], 
            headers= [m.name for m in CompletionType], 
            tablefmt="simple", 
        ))

        if not OMIT:
            print(f'## Version Constrain Type')
            data = []
            for v_t in v_types:
                data.append([v_t] + v_cnt[v_t])
            print(tabulate(
                data, 
                headers= ['Constrain Type'] + [m.name for m in CompletionType], 
                tablefmt="simple", 
            ))

            print(f'## API Change Type')
            data = []
            for a_t in a_types:
                data.append([a_t] + a_cnt[a_t])
            print(tabulate(
                data, 
                headers= ['API Change Type'] + [m.name for m in CompletionType], 
                tablefmt="simple", 
            ))