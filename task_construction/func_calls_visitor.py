import ast
from collections import deque
from arg_validity_checker import ArgumentsAnalyser, GlobalVariableDefFinder

'''
visit keyword arguments
'''


class KWVisitor(ast.NodeVisitor):
    def __init__(self):
        self._name = []

    @property
    def name(self):
        return ",".join(self._name)

    def visit_keyword(self, node):
        if node.arg is not None:
            self._name.append(node.arg)


'''
visit function call nodes
'''


class FuncCallVisitor(ast.NodeVisitor):
    def __init__(self):
        self._name = deque()

    @property
    def name(self):
        return ".".join(self._name)

    @name.deleter
    def name(self):
        self._name.clear()

    def visit_Name(self, node):
        self._name.appendleft(node.id)

    def visit_Attribute(self, node):
        try:
            self._name.appendleft(node.attr)
            self._name.appendleft(node.value.id)
        except AttributeError:
            self.generic_visit(node)

'''
rewrite function call nodes
'''


# Rewirte ast node about reflection
class ReWriteRefNode(ast.NodeTransformer):
    def __init__(self):
        self.assign_obj = {}
        self.ref_call = {}

    def visit_Assign(self, node):
        if node.value.__dict__.__contains__("value") and isinstance(node.value.value, str):
            self.assign_obj[node.targets[0].id] = node.value.value
        if isinstance(node.value, ast.Call) and node.value.func.__dict__.__contains__("id") and node.value.func.id == 'getattr':
            target = node.targets[0].id
            if isinstance(node.value.args[0], ast.Str):
                module = ""
            elif isinstance(node.value.args[0], ast.expr):
                module = node.value.args[0].id

            if isinstance(node.value.args[1], ast.Str):
                func = ""
            elif isinstance(node.value.args[1], ast.expr):
                func = node.value.args[1].id


            if module and func and module in self.assign_obj.keys() and func in self.assign_obj.keys():
                self.ref_call[target] = self.assign_obj[module] + '.' + self.assign_obj[func]
            elif module and module in self.assign_obj.keys() and isinstance(node.value.args[1], ast.Str):
                self.ref_call[target] = self.assign_obj[module] + '.' + node.value.args[1].value
            elif func and func in self.assign_obj.keys() and isinstance(node.value.args[0], ast.Str):
                self.ref_call[target] = node.value.args[0].value + '.' + self.assign_obj[func]
            elif isinstance(node.value.args[0], ast.Str) and isinstance(node.value.args[1], ast.Str):
                self.ref_call[target] = node.value.args[0].value + '.' + node.value.args[1].value

        self.generic_visit(node)
        return node

    def visit_Call(self, node):
        if node.func.__dict__.__contains__("id") and node.func.id in self.ref_call.keys():
            node.func.id = self.ref_call[node.func.id]
        self.generic_visit(node)
        return node

def get_func_calls(code, tree):
    # get intra file dependencies
    arg_analyser, intra_file_deps = None, set()
    if code:
        arg_analyser = ArgumentsAnalyser(code)
        finder = GlobalVariableDefFinder()
        finder.visit(tree)
        intra_file_deps = finder.defined_vars

    func_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_visitor = FuncCallVisitor()
            call_visitor.visit(node.func)

            kw_visitor = KWVisitor()
            try:
                kw_visitor.visit(node)
                lineno = getattr(node, "lineno", -1)
                end_lineno = getattr(node, "end_lineno", lineno)
                if code:
                    # Find variable content in positional & keyword arguments
                    var_names = arg_analyser.get_varnames_in_args(node)
        
                    # Check if variable is an intra-File dependency
                    if var_names.issubset(intra_file_deps):
                        func_calls.append((call_visitor.name, kw_visitor.name, lineno, end_lineno))
                    else:
                        continue
                else:
                    func_calls.append((call_visitor.name, kw_visitor.name, lineno, end_lineno))
            except:
                func_calls.append((call_visitor.name, "", getattr(node, "lineno", -1), getattr(node, "end_lineno", -1)))
    return func_calls
