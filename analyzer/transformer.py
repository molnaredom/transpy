import ast
from analyzer import Analyzer, config
from .utils import OutputHandler
from functools import lru_cache
import difflib
from tokenize import generate_tokens

@lru_cache(maxsize=128)
def is_inside_if(lines, pos, base_indent):
    #Supposing that base_indent is the indentation of the If-node returns True if the lines[pos] is inside that If-node
    indent = indentation(lines[pos])
    #print(f"Indent at line: ({lines[pos].strip()}): {indent}")
    stripped = lines[pos].strip()

    if (stripped.startswith("#") or not bool(stripped)): # Empty / comment lines, have to check ahead if possible.
        if pos+1 < len(lines):
            return is_inside_if(lines, pos+1, base_indent)
        return False

    if indent > base_indent:
        # Line is indented inside base_indent
        return True
    elif indent == base_indent: # Line is at the same indentation
        if (stripped.startswith("else:") or stripped.startswith("elif") or stripped.startswith(")")):
            return True # its just another branch or multiline test

    return False

def count_actual_lines( lines, pos):
    # At pos is the beginning of the If-node in the source code's string of lines
    offset = 0
    if not lines[pos].startswith('if'):
        while not lines[pos+offset].strip().startswith('if'):
            offset -= 1

    base_indent = indentation(lines[pos+offset])
    #print(f"Base-Indent at line: ({lines[pos+offset].strip()}): {base_indent}")
    res = 1 - offset
    pos += 1
    while pos < len(lines) and is_inside_if(lines, pos, base_indent):
        res += 1
        pos += 1
    #print(f" ACTUAL LINES: {res}, OFFSET: {offset}")
    return (res, offset)

def indentation(s, tabsize=4):
    sx = s.expandtabs(tabsize)
    return 0 if sx.isspace() else len(sx) - len(sx.lstrip())

class Transformer(ast.NodeTransformer):

    def __init__(self):
        self.analyzer = Analyzer()
        self.results = {} # Mapping the linenos of the og If-nodes to their transformed counterpart
        self.visit_recursively = config["MAIN"].getboolean("VisitBodiesRecursively")
        self.preserve_comments = config["MAIN"].getboolean("PreserveComments")
        self.logger = OutputHandler("transformer.log") if config["OUTPUT"].getboolean("AllowTransformerLogs") else None
        #self.differ = OutputHandler("diffs.diff") if  else None
        self.generate_diffs = config["OUTPUT"].getboolean("GenerateDiffs")
        self.visited_nodes = 0
        self.code = None

    def log(self, text):
        if self.logger is not None:
            self.logger.log(text)

    def visit_If(self, node):
        global comments, ast_sorok
        ast_sorok = 0
        old_sorok = 0
        #self.log(f"Transforming If-node at ({node.test.lineno})")
        self.visited_nodes += 1
        # print("node", ast.unparse(node))  # A NODE MAGA A REGI KOD csak unparseolni kell már nincs benne komment
        self.analyzer.visit(node)  # szetszedi a regi kodot darabokra
        if node in self.analyzer.subjects.keys():  # ha IF objektum benne van az analizalhato objektumok közt ??
            print("--------------")
            kezdet = node.test.lineno
            print("kezdet", kezdet) # ITT KEZDŐDIK AZ ATALAKITAS sor
            ast_sorok += kezdet
            old_sorok += kezdet
            # self.analyzer.
            subjectNode = self.analyzer.subjects[node] # a változóneve,--> astra alakitva maga az érték
            _cases = [] # if elif else , ilyesmik gyujtese
            with open("kjo.py", "w") as sf:
                for branch in self.analyzer.branches[node]:
                    # print("\nEgy node atlakaitas alatt")
                    # print("N", ast.unparse(node) if node is not None else "---")
                    if branch.flat:
                        # print(f"TRANSFORMER: BRANCH IS FLATTENED")
                        for subBranch in branch.flat:
                            pattern = self.analyzer.patterns[subBranch]
                            transformed_branch = ast.match_case(pattern = pattern.transform(subjectNode), guard = pattern.guard(subjectNode), body = subBranch.body)
                            _cases.append(transformed_branch)
                    else:
                        # print(f"TRANSFORMER: BRANCH IS NOT FLATTENED")
                        # print("S", ast.unparse(subjectNode) if subjectNode is not None else "---")
                        _pattern = ast.MatchAs() if branch.test is None else self.analyzer.patterns[branch].transform(subjectNode)
                        _guard = None if branch.test is None else self.analyzer.patterns[branch].guard(subjectNode)
                        temp = ast.Module(body = branch.body, type_ignores=[])
                        if self.visit_recursively:
                            self.generic_visit(temp)
                        # print("TRANSFORMER TEMP:")
                        # print( if _pattern is not None else "---")
                        # print(ast.unparse(_guard)if _guard is not None else "---")
                        # print(ast.unparse(temp)if temp is not None else "---")
                        transformed_branch = ast.match_case(pattern = _pattern, guard = _guard, body = temp.body)
                        _cases.append(transformed_branch)
                        # print("_", ast.unparse(branch)if transformed_branch is not None else "---")
                        # tra = ast.unparse(transformed_branch)
                        body_sorok = ast.unparse(temp)
                        uj = ast.unparse(transformed_branch)
                        old = ast.unparse(branch.body)
                        def sorellenor(sor, rekurziv_akcio):
                            global ast_sorok
                            if f"in{ast_sorok}" in comments:
                                sor += comments[f"in{ast_sorok}"]
                                if rekurziv_akcio:
                                    sor += "\n"+"\n".join(rekurziv_akcio)
                                return sor
                            elif f"out{ast_sorok}" in comments:
                                # sor = ""
                                print("R", rekurziv_akcio)
                                rekurziv_akcio.append(comments[f"out{ast_sorok}"])
                                ast_sorok += 1
                                return sorellenor(sor, rekurziv_akcio=rekurziv_akcio)
                            else:

                                return sor # semilyen komment nem volt


                        for sor in uj.splitlines():
                            ujsor = sorellenor(sor, [])
                            # print(f"[{ast_sorok}]({old_sorok})",ujsor)
                            sf.write(ujsor+"\n")
                            ast_sorok += 1

                        old_sorok+= old.count("\n") +2

                print("_cases", len(_cases))
                result = ast.Match(subject = subjectNode, cases = _cases) # mar atalakitott cucc
                self.results[node.test.lineno-1] = result
                return result
        elif self.visit_recursively:
            curr_node = node
            while isinstance(curr_node, ast.If):
                temp = ast.Module(body = curr_node.body)
                self.generic_visit(temp)
                curr_node.body = temp.body
                if len(curr_node.orelse):
                    if isinstance(curr_node.orelse[0], ast.If):
                        curr_node = curr_node.orelse[0]
                        continue
                    else:
                        temp = ast.Module(body = curr_node.orelse)
                        self.generic_visit(temp)
                        curr_node.orelse = temp.body
                break
        return node

    def transform(self, file):
        # Reading the source file
        with open(file, "r", encoding='utf-8-sig') as src:
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
            if self.preserve_comments:
                comments = {}
                src.seek(0)
                tokens = generate_tokens(src.readline)
                print("tokens", tokens)
                cikluskezdet = True
                for token in tokens:
                    if token.type == 61:
                        if cikluskezdet:
                            comments[f"out{token.start[0]}"] = token.string
                            print("K-out", token.string)
                            cikluskezdet = False
                        else:
                            comments[f"in{token.start[0]}"] = token.string
                            print("K-in", token.string)
                            cikluskezdet = False
                    else:
                        print("*", token.string)
                        if token.string == "\n":
                            print("ujsor")
                            cikluskezdet = True
                        else:
                            cikluskezdet = False

            print("Comments", comments)

            # itt kezdődik az if cuccok nezese
            self.visit(tree)
            if len(self.results.keys()) == 0:
                return

            src.seek(0)
            src_lines = tuple(src.readlines())

        print(self.results.keys())
        # Writing the (transformed) file

        self.nemtommi(src_lines)

        # kerdes felteves
        i = 0
#         while i < len(src_lines):
#             if i in self.results.keys():
#
#                 indent = indentation(src_lines[i])
#                 res = ast.unparse(self.results[i][0]).splitlines()
#                 print(f"""
# ------------------------------------------------------------------------------------------------------------------
#                                 #       | original | transpy
#                                 sorszám |{self.results[i][1]}       |  {len(res)}
# ------------------------------------------------------------------------------------------------------------------
#                        """)
#                 if self.preserve_comments:
#                     flag = False
#                     for key in comments.keys():
#                         if key in range(i, i + self.results[i][1] - 1):
#                             if not flag:
#                                 print(f"{i}[#]: ", (indent + 1) * " " + comments[key])
#                             flag = True
#                 for l,newLine in enumerate(res): # KICSERELENDO SOROK
#                     print(f"{i+l}[+]: ", indent * " " + newLine)
#                 print("- "*50)
#                 for _ in range(self.results[i][1]): # TORLENDO AOROK
#                     print(f"{i}[-]: ", src_lines[i], end="")
#                     i+=1
#                 print("|______________________________________________________________|")
#             else:
#                 print("OLD: ", src_lines[i], end="")
#             # a = input("Megtartanád?")
#
#             i += 1



        with open(file, "w", encoding='utf-8-sig') as out:
            i = 0
            # fileba iratas
            while i < len(src_lines):
                if i in self.results.keys():
                    indent = indentation(src_lines[i])
                    # print("indent: ", indent)
                    res = ast.unparse(self.results[i][0]).splitlines()
                    if self.preserve_comments:
                        flag = False
                        for key in comments.keys():
                            if key in range(i, i+self.results[i][1] -1):
                                if not flag:
                                    out.write(indent * " " + "# PRESERVED COMMENTS: \n")
                                flag = True
                                out.write((indent+1) * " " + comments[key] + "\n")
                    for newLine in res:
                        # print("NL: ",indent * " " + newLine)
                        out.write(indent * " " + newLine + "\n")
                    i += self.results[i][1] -1
                else:
                    # print("el: ", src_lines[i], end="")
                    out.write(src_lines[i])
                i += 1

        # Checking for SyntaxErrors in the transformed file
        with open(file, "r", encoding='utf-8-sig') as f:
            new_lines = f.read()
            f.seek(0)
            newlines = f.readlines()

        try:
            ast.parse(new_lines)
        except SyntaxError as err:
            self.log(f"REVERTING {file}: SyntaxError: {err.msg} - line({err.lineno})")
            with open(file, "w", encoding='utf-8-sig') as f:
                f.writelines(src_lines)
            return


        if self.generate_diffs and OutputHandler.OUTPUT_FOLDER:
            import os
            from pathlib import Path

            diff = difflib.context_diff(src_lines, newlines, fromfile= str(file), tofile= str(file))
            diffile = (OutputHandler.OUTPUT_FOLDER / 'diffs' / f'{os.path.basename(file)}-diffs.diff').resolve()

            with open(diffile, 'w', encoding='utf-8-sig') as f:
                f.writelines(diff)

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
