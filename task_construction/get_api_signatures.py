import os, ast
from func_calls_visitor import get_func_calls
from db import save_api_calls

# Load filter targets
target_tpl_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data_collection', 'rank.txt')
target_tpls = set()
with open(target_tpl_file, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line: target_tpls.add(line.split("@@")[1]) # case sensitive

class AssignVisitor(ast.NodeVisitor):
    def __init__(self):
        self.class_obj = {}
        self.instance_to_class = {}
    
    def visit_Assign(self, node):
        call_name = get_func_calls('', node.value)
        if len(call_name) > 0 and isinstance(node.targets[0], ast.Name):
            self.class_obj[node.targets[0].id] = call_name[0][0]
        
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
            # Case: x = some.module.ClassName()
            full_name = self.get_full_attr_name(node.value.func)
            if full_name and isinstance(node.targets[0], ast.Name):
                self.instance_to_class[node.targets[0].id] = full_name
        elif isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            # Case: x = ClassName() (when class was imported directly)
            if node.value.func.id in self.class_obj:
                self.instance_to_class[node.targets[0].id] = self.class_obj[node.value.func.id]
        
        return node
    
    def get_full_attr_name(self, node):
        """Helper to get full dotted name from an Attribute node"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self.get_full_attr_name(node.value)}.{node.attr}"
        return None

def get_api_ref_id(tree):
    id2fullname = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            items = [nn.__dict__ for nn in node.names]
            for d in items:
                if d['asname'] is None:
                    id2fullname[d['name']] = d['name']
                else:
                    id2fullname[d['asname']] = d['name']
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            items = [nn.__dict__ for nn in node.names]
            for d in items:
                if d['asname'] is None:
                    id2fullname[d['name']] = node.module + '.' + d['name']
                else:
                    id2fullname[d['asname']] = node.module + '.' + d['name']
    return id2fullname

def get_API_calls(code, file_path, package_version_dict):
    try:
        tree = ast.parse(code, mode='exec')
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                child.parent = node

        visitor = AssignVisitor()
        visitor.visit(tree)
        class2obj = visitor.class_obj
        instance2class = visitor.instance_to_class

        func_calls_raw = get_func_calls(code, tree)
        new_func_calls = []  
        for name, param, lineno, end_lineno in func_calls_raw:
            name_parts = name.split('.')
            
            # Case 1: Method call on known instance (e.g., y = linear(x))
            if len(name_parts) == 1 and name in instance2class:
                resolved_name = instance2class[name] + '.' + name
                new_func_calls.append((resolved_name, param, lineno, end_lineno))
            # Case 2: Direct API call through variable (original functionality)
            elif name_parts[0] in class2obj and len(name_parts) == 2:
                resolved_name = class2obj[name_parts[0]] + '.' + name_parts[1]
                new_func_calls.append((resolved_name, param, lineno, end_lineno))
            else:
                new_func_calls.append((name, param, lineno, end_lineno))

        id2fullname = get_api_ref_id(tree)
        result = []
        for name, kw, lineno, end_lineno in new_func_calls:
            name_parts = name.split('.')
            
            if name_parts[0] in id2fullname:
                full_name = id2fullname[name_parts[0]] + '.' + '.'.join(name_parts[1:])
                prefix = id2fullname[name_parts[0]].split('.')[0].lower()
            else:
                full_name = name
                prefix = name_parts[0].lower()

            # Check if it is a method of the specified TPL
            lib_name = full_name.split('.')[0]
            if not lib_name in target_tpls: continue

            if len(name_parts) > 1 and name_parts[0] in instance2class:
                class_parts = instance2class[name_parts[0]].split('.')
                prefix = class_parts[0].lower()

            version = package_version_dict.get(prefix, None)
            result.append({
                "api": full_name.rstrip('.'),
                "file": file_path,
                "lineno": lineno,
                "end_lineno": end_lineno,
                "version": version
            })
        return result
    except (SyntaxError, ValueError):
        return []

"""Used to construct function-level task: extract API from specific function node"""
def get_API_calls_from_funcnode(func_code, full_code, file_path, package_version_dict, class2obj=[], instance2class=[], id2fullname=[]):
    try:
        if full_code:
            tree = ast.parse(full_code, mode='exec')
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    child.parent = node

            # Based on the entire file
            visitor = AssignVisitor()
            visitor.visit(tree)
            class2obj = visitor.class_obj
            instance2class = visitor.instance_to_class
            id2fullname = get_api_ref_id(tree)
        else: # eval func-level
            pass

        # Based on a single function
        func_tree = tree = ast.parse(func_code, mode='exec')
        func_calls_raw = get_func_calls(func_code, func_tree)
        new_func_calls = []  
        for name, param, lineno, end_lineno in func_calls_raw:
            name_parts = name.split('.')
            
            # Case 1: Method call on known instance (e.g., y = linear(x))
            if len(name_parts) == 1 and name in instance2class:
                resolved_name = instance2class[name] + '.' + name
                new_func_calls.append((resolved_name, param, lineno, end_lineno))
            # Case 2: Direct API call through variable (original functionality)
            elif name_parts[0] in class2obj and len(name_parts) == 2:
                resolved_name = class2obj[name_parts[0]] + '.' + name_parts[1]
                new_func_calls.append((resolved_name, param, lineno, end_lineno))
            else:
                new_func_calls.append((name, param, lineno, end_lineno))

        result = []
        for name, kw, lineno, end_lineno in new_func_calls:
            name_parts = name.split('.')
            
            if name_parts[0] in id2fullname:
                full_name = id2fullname[name_parts[0]] + '.' + '.'.join(name_parts[1:])
                prefix = id2fullname[name_parts[0]].split('.')[0].lower()
            else:
                full_name = name
                prefix = name_parts[0].lower()

            if len(name_parts) > 1 and name_parts[0] in instance2class:
                class_parts = instance2class[name_parts[0]].split('.')
                prefix = class_parts[0].lower()

            version = package_version_dict.get(prefix, None)
            result.append({
                "api": full_name.rstrip('.'),
                "file": file_path,
                "lineno": lineno,
                "end_lineno": end_lineno,
                "version": version
            })
        return result
    except (SyntaxError, ValueError):
        lines = func_code.splitlines()

        if len(lines)>3: 
            neo_func_lines = [lines[0]] + lines[2:]
            return get_API_calls_from_funcnode(
                '\n'.join(neo_func_lines), 
                full_code, file_path, package_version_dict, class2obj, instance2class, id2fullname
            )
            
        else:            return []

"""
This is a get_all_call_apis docs.
 
Parameters:
  param1 - List of code source file paths

Returns:
    Returns a list containing the called APIs, already formatted

"""
def get_all_call_apis_from_sources(sources, package_version_dict):
    all_call_apis = []
    for source in sources:
        try:
            with open(source, errors='ignore') as f:
                code_text = f.read()
            func_calls = get_API_calls(code_text, source, package_version_dict)
            all_call_apis.extend(func_calls)
        except Exception as e:
            print(f"[ERROR] {source}: {e}")
            continue
    return all_call_apis