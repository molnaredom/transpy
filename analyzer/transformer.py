import ast
import subprocess

from analyzer import Analyzer, config
from .utils import OutputHandler
from functools import lru_cache
import difflib
from tokenize import generate_tokens


@lru_cache(maxsize=128)
def is_inside_if(lines, pos, base_indent):
    # Supposing that base_indent is the indentation of the If-node returns True if the lines[pos] is inside that If-node
    indent = indentation(lines[pos])
    # print(f"Indent at line: ({lines[pos].strip()}): {indent}")
    stripped = lines[pos].strip()

    if (stripped.startswith("#") or not bool(stripped)):  # Empty / comment lines, have to check ahead if possible.
        if pos + 1 < len(lines):
            return is_inside_if(lines, pos + 1, base_indent)
        return False

    if indent > base_indent:
        # Line is indented inside base_indent
        return True
    elif indent == base_indent:  # Line is at the same indentation
        if (stripped.startswith("else:") or stripped.startswith("elif") or stripped.startswith(")")):
            return True  # its just another branch or multiline test

    return False


def count_actual_lines(lines, pos):
    # At pos is the beginning of the If-node in the source code's string of lines
    offset = 0
    if not lines[pos].startswith('if'):
        while not lines[pos + offset].strip().startswith('if'):
            offset -= 1

    base_indent = indentation(lines[pos + offset])
    # print(f"Base-Indent at line: ({lines[pos+offset].strip()}): {base_indent}")
    res = 1 - offset
    pos += 1
    while pos < len(lines) and is_inside_if(lines, pos, base_indent):
        res += 1
        pos += 1
    # print(f" ACTUAL LINES: {res}, OFFSET: {offset}")
    return (res, offset)


def indentation(s, tabsize=4):
    sx = s.expandtabs(tabsize)
    return 0 if sx.isspace() else len(sx) - len(sx.lstrip())


def count_spaces(code):
    """
    Counts the number of spaces before the first non-space character in the first line of code.

    Parameters:
    code (str): The code to count spaces in.

    Returns:
    int: The number of spaces before the first non-space character in the first line of code.
    """
    count = 0
    for char in code:
        if char == ' ':
            count += 1
        elif char == '\n':
            return count
        else:
            return count
    return count


def does_not_have_return_continue_break_yield(code):
    """
    Returns True if the given code contains any of the following statements:
    - return
    - continue
    - break
    - yield
    """
    tree = ast.parse(code)
    print(code)
    print(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Return, ast.Continue, ast.Break, ast.Yield)):
            print("@@TARTALMAZ")
            return False
    print("@@NEM TARTALMAZ")
    return True


class Transformer(ast.NodeTransformer):

    def __init__(self):
        self.analyzer = Analyzer()
        self.results = {}  # Mapping the linenos of the og If-nodes to their transformed counterpart
        self.visit_recursively = config["MAIN"].getboolean("VisitBodiesRecursively")
        self.preserve_comments = config["MAIN"].getboolean("PreserveComments")
        self.logger = OutputHandler("transformer.log") if config["OUTPUT"].getboolean("AllowTransformerLogs") else None
        self.generate_diffs = config["OUTPUT"].getboolean("GenerateDiffs")
        self.visited_nodes = 0
        self.code = None

    def log(self, text):
        if self.logger is not None:
            self.logger.log(text)

    def visit_If(self, node):
        global comments, ast_sorok
        self.visited_nodes += 1
        self.analyzer.visit(node)  # szetszedi a regi kodot ast darabokra , A node ast objektum
        if node in self.analyzer.subjects.keys():  # ha IF objektum benne van az analizalhato objektumok közt ??
            subjectNode = self.analyzer.subjects[node]  # ifben a változó neve,--> astra alakitva a változó érték
            _cases = []  # if ágak gyűjtőhelye --> if elif else
            res = []
            for hanyadik_barnch, branch in enumerate(self.analyzer.branches[node]):
                if branch.flat:
                    for subBranch in branch.flat:
                        pattern = self.analyzer.patterns[subBranch]
                        transformed_branch = ast.match_case(pattern=pattern.transform(subjectNode),
                                                            guard=pattern.guard(subjectNode),
                                                            body=subBranch.body)
                        try:
                            # print(ast.parse(ast.unparse(transformed_branch)))
                            _cases.append(transformed_branch)
                        except SyntaxError:
                            return None
                else:
                    _pattern = ast.MatchAs() if branch.test is None else self.analyzer.patterns[branch].transform(
                        subjectNode)
                    _guard = None if branch.test is None else self.analyzer.patterns[branch].guard(subjectNode)
                    temp = ast.Module(body=branch.body, type_ignores=[])
                    if self.visit_recursively:
                        self.generic_visit(temp)
                    transformed_branch = ast.match_case(pattern=_pattern, guard=_guard, body=temp.body)
                    _cases.append(transformed_branch)

            def utolsosor():
                if len(self.analyzer.branches[node]) - 1 == hanyadik_barnch:  # utolso if node
                    if len(unparsed_ast.splitlines()) - 1 == sorszam:
                        return True
                return None

            def sorellenor(sor):
                global ast_sorok
                if f"in{ast_sorok}" in comments:
                    sor += "  " + comments[f"in{ast_sorok}"]
                if f"out{ast_sorok + 1}" in comments and not utolsosor():
                    elozo_sor_indentalasa = count_spaces(sor.splitlines()[0])
                    sor += "\n" + " " * 4 + " " * elozo_sor_indentalasa + comments[f"out{ast_sorok + 1}"]
                    ast_sorok += 1
                    return sorellenor(sor)
                return sor  # minden sorba 4 space a match miatt
                # *4 indentalas szama , +4 mert mindig bentebb kerul 1 sorral ami ciklusobn belul van

            ast_atalakitott = ast.Match(subject=subjectNode, cases=_cases)  # mar atalakitott cucc
            unparsed_ast = ast.unparse(ast_atalakitott)
            print("ÉÉÉÉÉ\n", unparsed_ast)
            ast_sorok = node.test.lineno
            for sorszam, sor in enumerate(unparsed_ast.splitlines()):
                ujsor = sorellenor(sor)
                # print("Ú", ujsor)
                res.append(ujsor + "\n")
                if "match" not in sor:
                    ast_sorok += 1

            # res.insert(0, ast.unparse(ast_atalakitott).splitlines()[0] + "\n")
            # print("res")
            # [print(i) for i in res]

            self.results[node.test.lineno - 1] = res
            result = ast.Match(subject=subjectNode, cases=_cases)
            print("result", ast.unparse(result))
            return result
        elif self.visit_recursively:
            curr_node = node
            while isinstance(curr_node, ast.If):
                temp = ast.Module(body=curr_node.body)
                self.generic_visit(temp)
                curr_node.body = temp.body
                if len(curr_node.orelse):
                    if isinstance(curr_node.orelse[0], ast.If):
                        curr_node = curr_node.orelse[0]
                        continue
                    else:
                        temp = ast.Module(body=curr_node.orelse)
                        self.generic_visit(temp)
                        curr_node.orelse = temp.body
                break
        return node

    def transform(self, file):
        # Reading the source file
        with open(file, "r", encoding='utf-8') as src:
            try:
                k = src.read()
                self.code = k.splitlines()
                tree = ast.parse(k)
            except SyntaxError as error:
                self.log(f"SyntaxError in '{file}': {error.msg} - line({error.lineno})")
                return
            except UnicodeDecodeError as error:
                self.log(f"UnicodeDecodeError in {file}")
                return

            self.analyzer.file = file
            global comments
            comments = None
            self.preserved_comments(src)
            self.visit(tree)

            if len(self.results.keys()) == 0:
                return
            src.seek(0)
            src_lines = tuple(src.readlines())

        print(self.results.keys())

        self.nemtommi(src_lines)

        with open(file, "w", encoding='utf-8') as out:
            print("FFÁÁJL", file)
            i = 0
            while i < len(src_lines):
                if i in self.results.keys():
                    indent = indentation(src_lines[i])
                    res = self.results[i][0]
                    for newLine in res:
                        print(indent)
                        out.write(indent * " " + newLine)
                    i += self.results[i][1] - 1
                else:
                    out.write(src_lines[i])
                i += 1
        subprocess.run(["python3.11", "-m", "black", file])

        # print(k.stdout)
        # print(k.stderr)
        # # Checking for SyntaxErrors in the transformed file
        # with open(file, "r", encoding='utf-8') as f:
        #     new_lines = f.read()
        #     f.seek(0)
        #     newlines = f.readlines()
        #
        # # try:
        # #     ast.parse(new_lines)
        # # except SyntaxError as err:
        # #     self.log(f"REVERTING {file}: SyntaxError: {err.msg} - line({err.lineno})")
        # #     print("SYNTAX ERR", f"REVERTING {file}: SyntaxError: {err.msg} - line({err.lineno})")
        # #     with open(file, "w", encoding='utf-8') as f:
        # #         f.writelines(src_lines)
        # #     return
        #
        # if self.generate_diffs and OutputHandler.OUTPUT_FOLDER:
        #     import os
        #     from pathlib import Path
        #
        #     diff = difflib.context_diff(src_lines, newlines, fromfile=str(file), tofile=str(file))
        #     diffile = (OutputHandler.OUTPUT_FOLDER / 'diffs' / f'{os.path.basename(file)}-diffs.diff').resolve()
        #
        #     with open(diffile, 'w', encoding='utf-8') as f:
        #         f.writelines(diff)

    def preserved_comments(self, src):
        global comments
        if self.preserve_comments:
            comments = {}
            src.seek(0)
            tokens = generate_tokens(src.readline)
            cikluskezdet = True
            for token in tokens:
                if token.type == 61:
                    if cikluskezdet:
                        comments[f"out{token.start[0]}"] = token.string  # egeszsoros komment
                        cikluskezdet = False
                    else:
                        comments[f"in{token.start[0]}"] = token.string  # kodot tartalmazo sorban komment
                        cikluskezdet = False
                else:
                    if token.string == "\n":
                        cikluskezdet = True
                    else:
                        cikluskezdet = False

    def nemtommi(self, src_lines):
        i = 0
        while i < len(src_lines):
            if i in self.results.keys():
                # print(f"LINE {i} IS IN RESULTS")
                if_length, offset = count_actual_lines(src_lines, i)
                self.results[i] = (self.results[i], if_length)
                if offset != 0:
                    # print(f" AT LINE ({i}) OFFSET IS: {offset}")
                    self.results[i + offset] = self.results[i]
            i += 1
