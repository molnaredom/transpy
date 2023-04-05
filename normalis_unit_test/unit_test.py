import subprocess
def proba(code):
    with open("tmp.py", "w")as f:
        f.write(code)

    proc = subprocess.Popen(f"python3.11 ../__main__.py tmp.py -o",
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)

    # print(proc.stdout.read().decode('utf-8'))
    print(proc.stderr.read().decode('utf-8'))
    with open("transformed-tmp.py", "w", encoding="utf-8") as t_f:
        return t_f.read()

def test_egytagu_dupla_reurn():
    code = """def eredeti(obj, Class, a, b):
    if isinstance(obj, Class) and a:
        if b:
            return obj.copy()
        return obj
"""
    elvart = """def eredeti(obj, Class, a, b):
    if isinstance(obj, Class) and a:
        if b:
            return obj.copy()
        return obj
"""
    kapott= proba(code)
    assert kapott == elvart, f"\nKAPOTT:\n{kapott}\n\nELVÁRT:\n {elvart}"

def test_egytagu_nagy_if():
    code = """if (number == 1 or number == 2) and (asd == 3 or asd == 4) and anything(): 
    pass
elif number == 5 and asd == 6 and anything():                               
    pass"""
    elvart = """if (number == 1 or number == 2) and (asd == 3 or asd == 4) and anything(): 
    pass
elif number == 5 and asd == 6 and anything():                               
    pass"""
    kapott= proba(code)
    assert kapott == elvart, f"\nKAPOTT:\n{kapott}\n\nELVÁRT:\n {elvart}"
