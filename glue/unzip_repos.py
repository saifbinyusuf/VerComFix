import zipfile, shutil, glob, os

REPOS_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'repos')

def main():
    for zpath in glob.glob(os.path.join(REPOS_DIR, '*.zip')):
        name = zpath[:-4]
        if os.path.isdir(name) and os.listdir(name):
            continue  # already unzipped — safe to rerun
        with zipfile.ZipFile(zpath) as z:
            z.extractall(name)
        entries = os.listdir(name)
        if len(entries) == 1 and os.path.isdir(os.path.join(name, entries[0])):
            inner = os.path.join(name, entries[0])
            for f in os.listdir(inner):
                shutil.move(os.path.join(inner, f), name)
            os.rmdir(inner)
        print(f'unzipped {os.path.basename(zpath)}')

if __name__ == '__main__':
    main()