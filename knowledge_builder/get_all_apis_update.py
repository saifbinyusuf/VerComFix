import ast
import fnmatch

import os
import re
from pathlib import Path
from packaging.version import parse as parse_version
from db import *


def read_file(path):
    try:
        file = open(path, "r")
        data = file.read().splitlines()
        return data
    except Exception as e:
        print(e)

def clean_api_name(api_name, version):
    """
    Try to remove version number or version-related directory from path (e.g. numpy-1.3.0.numpy -> numpy)
    """
    # return api_name.replace(f"-{version}.", ".")
    pattern = rf'^.*-{re.escape(version)}\.'
    return re.sub(pattern, '.', api_name)


def get_packages_version_order_by_time(package_name, packages_dir):
    try:
        packages_list = os.listdir(packages_dir)
        if packages_list:
            packages_list = sorted(packages_list, key=lambda x: os.path.getmtime(os.path.join(packages_dir, x)))
            version_list = []
            for package in packages_list:
                if package.endswith('.tar.gz'):
                    package = package.replace('.tar.gz', '')
                if package.endswith('.zip'):
                    package = package.replace('.zip', '')

                version_list.append(package.replace(package_name + '-', ''))

            return version_list
    except Exception as e:
        print(e)
        return []


def get_packages_version_order_by_name(package_name, packages_dir):
    try:
        packages_list = os.listdir(packages_dir)
        version_list = []

        for package in packages_list:
            if package.endswith('.tar.gz'):
                package = package.replace('.tar.gz', '')
            elif package.endswith('.zip'):
                package = package.replace('.zip', '')
            
            if package.startswith(package_name + '-'):
                version = package.replace(package_name + '-', '')
                version_list.append(version)

        version_list.sort(key=lambda v: parse_version(v))
        return version_list
    except Exception as e:
        print(e)
        return []

def search_egg_dir(package_dir):
    for parent_dir, dir_names, file_names in os.walk(package_dir):
        for dir_name in dir_names:
            if str(dir_name).endswith('.egg-info'):
                return os.path.join(parent_dir, dir_name, 'top_level.txt'), os.path.join(parent_dir, dir_name,
                                                                                         'SOURCES.txt')
    return '', ''


# sources = package : file_path
def get_all_sources_module_from_package_dir(package_dir):
    top_level_file, sources_file = search_egg_dir(package_dir)
    sources = dict()
    if os.path.exists(top_level_file) and os.path.exists(sources_file):
        # print('SOURCES file available')
        top_levels = read_file(top_level_file)

        for source_file in read_file(sources_file):
            if top_levels and len(top_levels[0]) > 0:
                for top_level in top_levels:
                    if top_level \
                            and source_file.endswith('.py') and source_file.__contains__(top_level) \
                            and not source_file.__contains__('test') \
                            and not source_file == 'setup.py':
                        # sources.append(top_level + source_file.split(top_level)[1])
                        sources[top_level + source_file.split(top_level)[1]] = package_dir + '/' + source_file
                        # print(f"Found source file: {top_level + source_file.split(top_level)[1]} in {package_dir + source_file}")
            else:
                if source_file.endswith('.py') \
                        and not source_file.__contains__('test') \
                        and not source_file == 'setup.py':
                    # sources.append(top_level + source_file.split(top_level)[1])
                    sources[source_file] = package_dir + '/' + source_file
    else:
        # print('egg file not found')
        for parent_dir, dir_names, file_names in os.walk(package_dir):
            for file_name in file_names:
                if file_name.endswith('.py') and not file_name.__contains__('test') and not file_name == 'setup.py':
                    # sources.append(parent_dir.replace(package_dir, '') + '/' + file_name)
                    sources[parent_dir.replace(package_dir, '') + '/' + file_name] = parent_dir + '/' + file_name
                    # print(f"Found source file: {parent_dir}/{file_name}")

    return sources


def extract_parameters(node):
    """Extract parameter names from function arguments, ignoring types"""
    params = []
    # Handle positional arguments
    for arg in node.args.args:
        params.append(arg.arg)
    
    # Handle keyword-only arguments
    for arg in node.args.kwonlyargs:
        params.append(arg.arg)
    
    # Handle vararg (*args)
    if node.args.vararg:
        params.append(node.args.vararg.arg)
    
    # Handle kwarg (**kwargs)
    if node.args.kwarg:
        params.append(node.args.kwarg.arg)
    
    return params


def has_return_value(node):
    """Check if the function has any return statements with values"""
    for item in ast.walk(node):
        if isinstance(item, ast.Return) and item.value is not None:
            return True
    return False


def get_all_apis_from_source(module_py, source_path, export_map=None):
    all_apis = []
    module_call_path = module_py.replace('.py', '').replace('/', '.').replace('\\', '.')

    try:
        text = open(source_path, 'r').read()
        module_ast = ast.parse(text)
    except Exception as e:
        print(f"Error parsing {source_path}: {e}")
        return []

    def get_all_exposed_paths(fullname):
        """
        Return original path + all possible exposed paths mapped.
        For example:
        fullname = sklearn.linear_model._logistic.LogisticRegression.__init__
        If export_map contains:
            'sklearn.linear_model._logistic.LogisticRegression' → 'sklearn.linear_model.LogisticRegression'
        Then it should return:
            - sklearn.linear_model._logistic.LogisticRegression.__init__
            - sklearn.linear_model.LogisticRegression.__init__
        """
        fullname = fullname.lstrip('.')
        results = {fullname}

        if not export_map:
            return results

        for k, v in export_map.items():
            if '*' in k:
                if fnmatch.fnmatch(fullname, k):
                    prefix = k.split('*')[0]
                    suffix = fullname[len(prefix):]
                    if '*' in v:
                        mapped = v.replace('*', suffix)
                        results.add(mapped)
            else:
                if fullname == k:
                    results.add(v)
                elif fullname.startswith(k + '.'):
                    suffix = fullname[len(k):]
                    mapped = v + suffix
                    results.add(mapped)

        return results

    # Process module-level functions
    functions = [n for n in module_ast.body if isinstance(n, ast.FunctionDef)]
    for func in functions:
        base_full_name = f"{module_call_path}.{func.name}"
        for full_name in get_all_exposed_paths(base_full_name):
            params = extract_parameters(func)
            has_return = has_return_value(func)
            api_signature = (full_name, params, has_return)
            all_apis.append(api_signature)

    # Process classes and their methods
    classes = [n for n in module_ast.body if isinstance(n, ast.ClassDef)]
    for cls in classes:
        for m in cls.body:
            if isinstance(m, ast.FunctionDef):
                base_full_name = f"{module_call_path}.{cls.name}.{m.name}"
                for full_name in get_all_exposed_paths(base_full_name):
                    params = extract_parameters(m)
                    has_return = has_return_value(m)
                    api_signature = (full_name, params, has_return)
                    all_apis.append(api_signature)

    return all_apis


# def get_diff_from_all_version_apis(all_version_apis):
#     if not all_version_apis:
#         return {}

#     diff = {}
#     version_keys = list(all_version_apis.keys())
#     first_version = version_keys[0]

#     def normalize_apis(version, api_triples):
#         """
#         Construct:
#         - norm_set: set of cleaned api triple (used for diff)
#         - mapping: dict of cleaned_name -> original_name
#         """
#         norm_set = set()
#         mapping = {}
#         for api in api_triples:
#             orig_name = api[0]
#             norm_name = clean_api_name(orig_name, version)
#             # print(f"Normalizing API: {orig_name} -> {norm_name} (version: {version})")
#             triple = (norm_name, tuple(api[1]), api[2])
#             norm_set.add(triple)
#             mapping[triple] = orig_name  # Key: record original name
#         return norm_set, mapping

#     # Initialize first version
#     base_apis, base_map = normalize_apis(first_version, all_version_apis[first_version])
#     diff[first_version] = {base_map[api]: '=' for api in base_apis}

#     for version in version_keys[1:]:
#         current_apis, current_map = normalize_apis(version, all_version_apis[version])
#         result = {}

#         for api in base_apis - current_apis:
#             result[base_map[api]] = '-'  # Delete (using original name of base version)
#         for api in current_apis - base_apis:
#             result[current_map[api]] = '+'  # Add (using original name of current version)
#         for api in base_apis & current_apis:
#             result[current_map.get(api, base_map.get(api, api[0]))] = '='

#         diff[version] = result
#         base_apis, base_map = current_apis, current_map  # Update base version

#     return diff

def get_diff_from_all_version_apis(all_version_apis):
    if not all_version_apis:
        return {}

    diff = {}
    version_keys = list(all_version_apis.keys())
    first_version = version_keys[0]

    def to_hashable(api):
        return (api[0], tuple(api[1]), api[2])  # qualified name, params, return flag

    base_apis = {to_hashable(api) for api in all_version_apis[first_version]}
    diff[first_version] = {api: '=' for api in base_apis}

    for version in version_keys[1:]:
        current_apis = {to_hashable(api) for api in all_version_apis[version]}
        result = {}

        for api in base_apis - current_apis:
            result[api] = '-'  # Removed
        for api in current_apis - base_apis:
            result[api] = '+'  # Added

        diff[version] = result
        base_apis = current_apis

    return diff


def save_package_version_apis_diff(package_name, all_diff):
    version_id = 0
    for version, apis in all_diff.items():
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Get top_level record
                cursor.execute("""
                    SELECT id FROM top_level 
                    WHERE package_name=%s AND package_version=%s 
                    LIMIT 1
                """, (package_name, version))
                result = cursor.fetchone()
                if not result:
                    print(f"Warning: No top_level entry found for {package_name} {version}")
                    continue
                top_level_id = result[0]

                # Update version_id
                cursor.execute("""
                    UPDATE top_level SET version_id=%s 
                    WHERE id=%s
                """, (version_id, top_level_id))

                # Insert into differences table
                sql_list = []
                for api_signature, diff_flag in apis.items():
                    api_name, params, has_return = api_signature
                    param_str = ', '.join(params)
                    sql_list.append((top_level_id, api_name, param_str, has_return, diff_flag))

                # If no changes, still insert a placeholder record
                if not sql_list:
                    sql_list.append((top_level_id, '', '', False, '='))

                cursor.executemany("""
                    INSERT INTO differences(package_version, api_name, param_list, has_return, diff)
                    VALUES (%s, %s, %s, %s, %s)
                """, sql_list)

                conn.commit()

        version_id += 1

def build_export_map(source_map):
    """
    Build {real path -> exposed path} mapping. For example:
    requests.models.PreparedRequest -> requests.PreparedRequest
    Or support wildcards:
    numpy.core.fromnumeric.* -> numpy.core.*
    """
    export_map = {}

    for module_path, abs_path in source_map.items():
        if os.path.basename(abs_path) == "__init__.py":
            try:
                text = open(abs_path, 'r', encoding='utf-8').read()
                module_ast = ast.parse(text)
            except Exception as e:
                print(f"Error parsing {abs_path}: {e}")
                continue

            # E.g. module_path = numpy/core/__init__.py -> numpy.core
            parent_module = module_path.replace('.py', '').replace('/', '.').replace('\\', '.')
            parent_module = parent_module.replace('.__init__', '').lstrip('.')

            for node in ast.walk(module_ast):
                if isinstance(node, ast.ImportFrom) and node.level in (0, 1):
                    mod = node.module or ''
                    for alias in node.names:
                        orig = alias.name
                        asname = alias.asname or orig

                        # Handle relative imports
                        if node.level == 1:
                            # Relative import, complete the path
                            if mod:
                                imported_module = f"{parent_module}.{mod}"
                            else:
                                imported_module = parent_module
                        else:
                            imported_module = mod

                        # Clean leading dots (possibly produced by incorrect concatenation)
                        imported_module = imported_module.lstrip('.')

                        if orig == "*":
                            real_path = f"{imported_module}.*".lstrip('.')
                            public_path = f"{parent_module}.*".lstrip('.')
                        else:
                            real_path = f"{imported_module}.{orig}".lstrip('.')
                            public_path = f"{parent_module}.{asname}".lstrip('.')

                        export_map[real_path] = public_path

    return export_map


def main():
    for package_name in os.listdir(packages_path):
        # all_version_list = get_packages_version_order_by_time(package_name, 
                                                        #    os.path.join(projects_path, package_name))
        all_version_list = get_packages_version_order_by_name(package_name, 
                                                           os.path.join(projects_path, package_name))                                                
        
        for version in all_version_list:
            print(f"Processing {package_name} version {version}")
            
            if is_exist("SELECT 1 FROM api_signatures WHERE package_name=%s AND package_version=%s", 
                       (package_name, version)):
                print(f"{package_name} - {version} already exists in database")
                continue

            package_dir = os.path.join(packages_path, package_name, f"{package_name}-{version}")
            if os.path.exists(package_dir):
                all_sources = get_all_sources_module_from_package_dir(package_dir)
                export_map = build_export_map(all_sources)
                print("export_map:", export_map)
                version_apis = []

                for source in all_sources:
                    version_apis.extend(get_all_apis_from_source(source, all_sources[source], export_map))
                
                # Save API signatures to database
                save_api_signatures(package_name, version, version_apis)
                print(f"Saved {len(version_apis)} APIs for {package_name}-{version} to database")
                
        # Compare API differences between versions
        if all_version_list:
            all_version_apis = {}
            for version in all_version_list:
                version_apis = get_api_signatures(package_name, version)
                all_version_apis[version] = version_apis

            api_diff = get_diff_from_all_version_apis(all_version_apis)
            save_package_version_apis_diff(package_name, api_diff)
            print(f"Saved API diff for {package_name}")


if __name__ == '__main__':
    current_folder = Path(__file__).resolve().parent
    projects_path = current_folder.parent / 'projects'
    packages_path = current_folder.parent / 'packages'
    main()
