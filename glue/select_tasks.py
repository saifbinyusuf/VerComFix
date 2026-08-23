import pymysql, json, pickle, sys, os
from packaging.specifiers import SpecifierSet

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from global_config import DB_CONFIG

conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
cur = conn.cursor()


def resolve_pypi_name(import_prefix):
    """'sklearn' -> 'scikit-learn'. Needed because api_name's first segment is
    the IMPORT name, but top_level/differences are keyed by the PyPI project name."""
    cur.execute("SELECT DISTINCT package_name FROM top_level WHERE top_level = %s", (import_prefix,))
    row = cur.fetchone()
    return row['package_name'] if row else import_prefix


def get_known_versions(pypi_name):
    cur.execute("SELECT DISTINCT package_version FROM top_level WHERE package_name = %s", (pypi_name,))
    return {r['package_version'] for r in cur.fetchall()}


def resolve_version_range(version_spec, all_known_versions):
    """version_spec is whatever was stored on the api_calls row by api_extractor.py:
       ''            -> unresolvable (no declared version, no PyPI fallback found)
       '~~1.24.0'    -> nothing was declared; this is what pip would've installed
                        at the repo's commit date (version_resolver.py's own fallback)
       '>=1.20,<=1.22' etc -> a real declared constraint (PEP 440 specifier)"""
    if not version_spec:
        return set()
    if version_spec.startswith('~~'):
        resolved = version_spec[2:]
        return {resolved} if resolved in all_known_versions else set()
    try:
        spec = SpecifierSet(version_spec)
    except Exception:
        return set()
    return {v for v in all_known_versions if spec.contains(v, prereleases=True)}


def find_transition_pair(rows_outside_range):
    """A matched +/- pair at the SAME version = the name still exists, signature changed.
    A lone +/- with no partner = the name itself appeared or disappeared."""
    by_version = {}
    for r in rows_outside_range:
        by_version.setdefault(r['version_str'], {'+': None, '-': None})
        by_version[r['version_str']][r['diff']] = r
    for sides in by_version.values():
        if sides['+'] and sides['-']:
            return (sides['-'], sides['+'])
    for sides in by_version.values():
        return (sides['-'], sides['+'])
    return (None, None)


def infer_evolution_type(pair):
    removed, added = pair
    if removed is None or added is None:
        return 'name'
    if removed['param_list'] != added['param_list']:
        return 'parameter'
    if removed['has_return'] != added['has_return']:
        return 'return_type'
    return 'unknown'


def classify(api_call):
    import_prefix = api_call['api_name'].split('.')[0]
    pypi_name = resolve_pypi_name(import_prefix)
    known_versions = get_known_versions(pypi_name)

    versions_in_range = resolve_version_range(api_call['version'], known_versions)
    if not versions_in_range:
        return None   # can't resolve a real version range -> not usable

    cur.execute("""
        SELECT t.package_version AS version_str, d.param_list, d.has_return, d.diff
        FROM differences d
        JOIN top_level t ON d.package_version = t.id
        WHERE d.api_name = %s
    """, (api_call['api_name'],))
    sigs = cur.fetchall()
    if not sigs:
        return None   # no signature history recorded for this API at all

    inside  = [s for s in sigs if s['version_str'] in versions_in_range]
    outside = [s for s in sigs if s['version_str'] not in versions_in_range]

    changed_inside  = any(s['diff'] in ('+', '-') for s in inside)
    changed_outside = any(s['diff'] in ('+', '-') for s in outside)

    if changed_inside or not changed_outside:
        return None   # unstable inside the range, or nothing changed outside it -> discard

    pair = find_transition_pair(outside)
    return {**api_call, "evolution_type": infer_evolution_type(pair)}


def run(table_name, level):
    cur.execute(f"SELECT * FROM {table_name}")
    kept = []
    for row in cur.fetchall():
        result = classify(row)
        if result:
            result['level'] = level
            kept.append(result)
    return kept


api_tasks = run('api_calls', 'api')
# func_task's columns may not exactly mirror api_calls (check with DESCRIBE func_task;
# before relying on this) — safe to leave disabled while func_task is empty anyway.
# func_tasks = run('func_task', 'func')
func_tasks = []

with open('tasks.jsonl', 'w') as f:
    for t in api_tasks + func_tasks:
        f.write(json.dumps(t, default=str) + '\n')

pickle.dump([t['id'] for t in api_tasks],  open('API_Level_Tids.pkl', 'wb'))
pickle.dump([t['id'] for t in func_tasks], open('Func_Level_Tids.pkl', 'wb'))

print(f"{len(api_tasks)} API-level tasks, {len(func_tasks)} function-level tasks kept")