import ast, sys, os, re
from os import path

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from global_config import GITHUB_CODE_DOWNLOAD_BASE_DIR

from utils import CodeHandler as CH
from task_construction.get_api_signatures import AssignVisitor, get_api_ref_id

DATA_BASE_DIR = GITHUB_CODE_DOWNLOAD_BASE_DIR # root directory storing repoSrc
MAX_CTX_LINE = 100

def get_indent_regex(line):
    """Use regex to get indentation"""
    match = re.match(r'^(\s*)', line)
    return match.group(1) if match else ''

class Task:
    def __init__(self,
        # version info
        tpl:                str,
        version:            str,
        # Info for building prompt and GT from repoSrc
        repo: str,
        file: str,  
        gt_start_lineno: int, 
        rctx_start_lineno: int
    ):
        self.tpl = tpl
        self.version = version
        self.repo = repo
        
        # Build prompt and GT based on meta
        src_file = path.join(DATA_BASE_DIR, repo, file)
        with open(src_file, 'r') as f:
            content = f.readlines()
            self.content = content

        if gt_start_lineno > MAX_CTX_LINE:
            imports, start_idx = [], 0
            for idx, line in enumerate(content):
                if line.startswith('#') or line.startswith('\n') or line.startswith('"""'):  continue
                if line.startswith('import') or line.startswith('from'): 
                    imports.append(line)
                    continue
                start_idx = idx
                break
            ctx = imports + content[max(start_idx, gt_start_lineno-len(imports)):gt_start_lineno]
        else:
            ctx = content[:gt_start_lineno]

        self.infile_ctx = ctx 

        if ctx: 
            self.indent = get_indent_regex(ctx[-1])
            before = ctx[-1].strip()
            if before.startswith('def') or  before.startswith('if') or before.startswith('for'):
                self.indent = '\t' + self.indent
        else:   self.indent = ''

        # Contents needed for FQN resolution
        tree = ast.parse(''.join(content), mode='exec')
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                child.parent = node
        visitor = AssignVisitor()
        visitor.visit(tree)
        self.class2obj      = visitor.class_obj
        self.instance2class = visitor.instance_to_class
        self.id2fullname = get_api_ref_id(tree)

        return
    
    # Subclass needs to implement this
    def prompt(self, omit: bool = False, is_GPT: bool = False) -> str: pass
    
    # 需要子类实现
    def handle_completion(self, completion: str, debug: bool=False) -> str: pass

class APILevelTask(Task):
    def __init__(self, 
        tpl, version,
        repo, file, 
        gt_start_lineno, rctx_start_lineno
    ):

        super().__init__(tpl, version, repo, file, gt_start_lineno, rctx_start_lineno)
        self.gt = ''.join(self.content[gt_start_lineno:rctx_start_lineno]).strip()

    def handle_completion(self, completion) -> str:
        cleaned = CH.clean_comments(completion)
        return CH.get_first_statement(cleaned)
    
    def prompt(self, omit: bool = False, is_GPT: bool = False)  -> str:
        code = ''.join(self.infile_ctx)
        if omit:
            if is_GPT:
                return f"""
Complete the next line (API Call) for the following code snippet. ONLY return the completion code:
```
{code}
```"""
            else:
                return f"{code}# Complete the next line (API Call) without comment\n"
        else:
            if self.version.startswith('~~'): # Unconstrained
                version_info = self.tpl
            else:
                version_info = f'{self.tpl}{self.version}'

            if is_GPT:
                return f"""
Complete the next line (API Call) for the following code snippet using {version_info}. 
- Make sure the usage is compatible with this version
- ONLY return the completion code:
```
{code}
```"""
            else:
                return f"{code}# Complete the next line (API Call) without comment using {version_info}. Make sure the usage is compatible with this version\n"


class FunctionLevelTask(Task):
    def __init__(self, 
        bg_off: int, end_off: int,
        tpl, version,
        repo, file, 
        gt_start_lineno, rctx_start_lineno
    ):
        super().__init__(tpl, version, repo, file, gt_start_lineno, rctx_start_lineno)

        self.gt = ''.join(
            self.content[gt_start_lineno+bg_off-1:gt_start_lineno+end_off]
        ).strip()

        head = ""
        for line in self.infile_ctx[::-1]:
            head = line.strip() + head
            if line.startswith('def') or line.startswith('async def'): break
        self.head = head


    """这边是放了完整的 Function，只需要 body 的话把注释的地方放出来"""
    def handle_completion(self, completion) -> str:
        if not completion.startswith('\t') or completion.startswith(' '):
            completion = f'    {completion}'
        func = f'{self.head}\n{completion}'
        func = CH.clean_comments(func)
        first_func = CH.get_first_function(func)
        if first_func: return first_func[len(self.head)+1:]
        else:          return ""

    def prompt(self, omit: bool = False, is_GPT: bool = False):
        code = ''.join(self.infile_ctx)
        if omit:
            if is_GPT:
                return f"""
Complete the function body for the following code snippet. ONLY return the completion code:
```
{code}
```"""
            else:
                return f"{code[:-1]} # Complete the function body without comment"
        else:
            if self.version.startswith('~~'): # Unconstrained
                version_info = self.tpl
            else:
                version_info = f'{self.tpl}{self.version}'

            if is_GPT:
                return f"""
Complete the function body for the following code snippet using {version_info}. 
- Make sure the usage is compatible with this version
- ONLY return the completion code:
```
{code}
```"""
            else:
                return f"{code[:-1]} # Complete the function body without comment using {version_info}. Make sure the usage is compatible with this version"

class APILevelRepairTask(Task):
    def __init__(self, 
        stmt: str, pred_fqn: str,
        bcr_desc: str,
        api_signature: tuple,
        tpl, version,
        repo, file, 
        gt_start_lineno, rctx_start_lineno
    ):
        super().__init__(tpl, version, repo, file, gt_start_lineno, rctx_start_lineno)
        self.stmt = stmt
        self.pred_fqn = pred_fqn
        self.orig_pred_api_name = self.get_orig_pred_api_name()
        self.bcr_desc = bcr_desc
        self.api_signature = api_signature
        self.gt = ''.join(self.content[gt_start_lineno:rctx_start_lineno]).strip()

    def get_orig_pred_api_name(self):
        pattern = r'''
            (?:^|[^a-zA-Z0-9_\.])      # 前面不是字母数字下划线或点（或者是行首）
            (                           # 开始捕获组
                (?:                     # 非捕获组：匹配属性访问链
                    [a-zA-Z_][a-zA-Z0-9_]*  # 标识符
                    (?:\s*\.\s*[a-zA-Z_][a-zA-Z0-9_]*)*  # 可选的 .属性 链
                )
                \s*                     # 可选空白
                \(                      # 左括号
            )                           # 结束捕获组
        '''
        
        match = re.search(pattern, self.stmt, re.VERBOSE)
        return match.group(1)[:-1] if match else None
    
    def handle_completion(self, completion) -> str:
        cleaned = CH.clean_comments(completion)
        return CH.get_first_statement(cleaned)
    
    def prompt(self, omit: bool = False, is_GPT: bool = False)  -> str:
        code = ''.join(self.infile_ctx)
        if is_GPT:
            return f"""Complete and output the next line for the following code snippet:
```
{code}
{self.indent}# {self.stmt}
{self.indent}# {self.knowledge(self.bcr_desc)}
```"""
        else:
            return f"""{code[:-1]}
{self.indent}# {self.stmt}
{self.indent}# {self.knowledge(self.bcr_desc)}
"""

    def knowledge(self, bcr_desc: str) -> str:
        gt_api_name = self.api_signature[0]
        gt_api_args = ', '.join(self.api_signature[1])
        return f"Method `{self.orig_pred_api_name}` is unavailable. Use `{gt_api_name}({gt_api_args})` at next line and revise arguments."