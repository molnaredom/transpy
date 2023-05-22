import ast
from copy import deepcopy
from analyzer import Transformer, make_output_folder, transform_helper, init_output
from analyzer.utils import OutputHandler
import os, glob
import argparse
import shutil
from pathlib import Path
import concurrent.futures
import threading
from tqdm import tqdm
import time


parser = argparse.ArgumentParser(description="Analyzes and transforms python projects.")
parser.add_argument("path", metavar='PATH', type=str, nargs=1, help="path to the directory / python file")
parser.add_argument('-i', '--inline',          dest='mode',    action='store_const', const="inline", default="copy", help='transform inline (default makes a copy)')
parser.add_argument('-o', '--overwrite',       dest='ow',      action='store_const', const="Y",      default=None,   help="automatically overwrite files, when not transforming inline")
# parser.add_argument('-t', '--test',            dest='test',   action='store_const', const=True,      default=False,   help="run in test mode, provides additional info on runtime and memory usage, etc.")
# parser.add_argument('-mt','--max-threads',dest='max_threads', const=None, default=None, type=int, help='maximum number of threads to use', nargs=1)
# parser.add_argument('-p','--p-name',dest='proj_name', const=None, default=None, type=str, help='name of the project, used to label test data', nargs=1)


TEST_DATA = {
    "project_size_MiB" : 0,
    "no_files" : 0,
    "cloc_py": {},
    "no_nodes_visited" : 0,
    "no_nodes_transformed" : 0,
    "runtime_s" : 0,
    "max_memory_MiB" : 0,
    "max_workers": 0,
    "project": ''
}



def _test_helper(path, _max_workers):
    global TEST_DATA
    files_to_transform = [f for f in path.rglob('*.py')] if path.is_dir() else [path]

    with concurrent.futures.ProcessPoolExecutor(max_workers=_max_workers, initializer=init_output, initargs=(OutputHandler.OUTPUT_FOLDER,)) as executor:
        results = list(tqdm(executor.map(transform_helper, files_to_transform), total=len(files_to_transform)))

    TEST_DATA["no_files"] = len(files_to_transform)
    TEST_DATA["max_workers"] = _max_workers if _max_workers is not None else 12
    for res in results:
        TEST_DATA["no_nodes_visited"] += res[0]
        TEST_DATA["no_nodes_transformed"] += res[1]


def _test_main(path, max_workers):
    from datetime import timedelta
    from memory_profiler import memory_usage
    global TEST_DATA

    start_time = time.monotonic()
    #mem = max(memory_usage((_test_helper, (path, max_workers), {})))
    _test_helper(path, max_workers)
    end_time = time.monotonic()

    TEST_DATA["runtime_s"] = timedelta(seconds=end_time - start_time).total_seconds()
    TEST_DATA["max_memory_MiB"] = None

def _write_test_data(project):
    import json
    n = 1
    TEST_DATA_BASE = Path(__file__).parent.resolve() / 'test-data'

    if not TEST_DATA_BASE.exists():
        print(f"Creating {TEST_DATA_BASE} for test data.")
        os.mkdir(TEST_DATA_BASE)

    testdatapath = (TEST_DATA_BASE / f'TEST_DATA_{project}({n}).json').resolve()
    while testdatapath.exists():
        n += 1
        testdatapath = (TEST_DATA_BASE / f'TEST_DATA_{project}({n}).json').resolve()

    print(f"Writing test data in: {testdatapath}")
    with open(testdatapath, "w") as f:
        json.dump(TEST_DATA, f, indent=4)

def onerror(func, path, exc_info):
    """
    Error handler for ``shutil.rmtree``.

    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.

    If the error is for another reason it re-raises the error.

    Usage : ``shutil.rmtree(path, onerror=onerror)``
    """
    import stat
    # Is the error an access error?
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        raise



def make_copy(schizo, newPath):
    prompt = "Overwriting" if newPath.exists() else "Creating"
    print(f"{prompt} '{newPath}'")
    path = schizo[0]
    if path.is_dir():
        if newPath.exists():
            shutil.rmtree(newPath, onerror=onerror)
        schizo[0] = shutil.copytree(path, newPath)
    else:
        schizo[0] = shutil.copy(path,newPath)

def main():
    args = parser.parse_args()
    path = Path(args.path[0]).resolve()
    files_to_transform = []
    ow = args.ow
    test_mode = False
    max_threads = None
    # DEFAULT max_workers = 12
    # MAX max_workers = 61


    if not path.exists():
        parser.error("Given path does not exist!")

    if args.mode == "copy":
        newPath = (path.parent / f"transformed-{path.parts[-1]}")
        if newPath.exists():
            while not (ow == "Y" or ow == "N"):
                prompt = "Directory" if path.is_dir() else "File"
                ow = input(f">> {prompt} '{newPath}' already exists! Want to overwrite? (Y/N)\n")

            if ow == "N":
                print("Quitting")
                return

        path = [path]
        #make_copy(path, newPath)
        thread = threading.Thread(target = make_copy, args = (path, newPath), name="Copying thread")
        thread.start()
        eli_count = 0
        while thread.is_alive():
            print('Copying files', '.'*(eli_count+1), ' '*(2-eli_count), end='\r')
            eli_count = (eli_count + 1) % 3
            time.sleep(0.1)
        thread.join()
        path = path[0]
        print('Done                 ')

    make_output_folder(path)

    if test_mode:
        p_name = args.proj_name[0]
        if not p_name:
            p_name = "unknown"
        TEST_DATA["project"] = p_name
        _test_main(path, max_threads)
        _write_test_data(p_name)
        return

    files_to_transform = [f for f in path.rglob('*.py')] if path.is_dir() else [path]
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_threads, initializer=init_output, initargs=(OutputHandler.OUTPUT_FOLDER,)) as executor:
        results = list(tqdm(executor.map(transform_helper, files_to_transform), total=len(files_to_transform)))


if __name__ == "__main__":
    main()
