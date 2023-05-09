import ast
import io
import subprocess
import tokenize

from analyzer import Analyzer, config
from .utils import OutputHandler
from functools import lru_cache
import difflib
from tokenize import generate_tokens
import astor


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
    res = 1 - offset
    pos += 1
    while pos < len(lines) and is_inside_if(lines, pos, base_indent):
        res += 1
        pos += 1
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


from textwrap import dedent


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
        self.src_lines = None

    def log(self, text):
        if self.logger is not None:
            self.logger.log(text)

    def visit_If(self, node):
        global comments, src_rownum, multiline_rownum

        def comment_nl_inserter(row: str, last_row: bool, add_nl: bool = True) -> str:
            """
                row: a string representing a single row of unparsed ast code without comments or newlines.
                add_nl: a boolean value indicating whether a newline character should be added to row or not.

                comments: a dictionary containing comments and newlines to be inserted into the code rows.
                    The keys of the dictionary are strings of the form in{rownum}, out{rownum},
                    or nl{rownum} where rownum is an integer representing the row number of the original code.
                    The values of the dictionary are the comments themselves, as strings.

                src_rownum: an integer representing the current row number being processed.
                multiline_rownum: an integer representing the current row number of a multiline block being processed.
            """
            global src_rownum, multiline_rownum
            if f"in{src_rownum}" in comments:
                row += "  " + comments[f"in{src_rownum}"]
            if f"out{src_rownum + 1}" in comments and not last_row:
                if add_nl:
                    row += "\n" + " " * 4 + comments[f"out{src_rownum + 1}"]
                else:
                    row += "  " + comments[f"out{src_rownum + 1}"]
                    multiline_rownum -= 1
                src_rownum += 1
                return comment_nl_inserter(row, last_row=last_row, add_nl=add_nl)
            if f"nl{src_rownum + 1}" in comments and not last_row:
                if add_nl:
                    row += "\n"
                else:
                    multiline_rownum -= 1
                src_rownum += 1
                return comment_nl_inserter(row, last_row=last_row, add_nl=add_nl)
            return row

        def get_multiline_rownum(i_from: int, i_to: int) -> int:
            """
            It takes two indices i_from and i_to that define a range of rows in the source code of the object.
            The function then determines the number of lines that this range of code should occupy when it is
            split into multiple lines.

            i_from: An integer representing the index of the first row of the code range.
            i_to: An integer representing the index of the last row of the code range.
            """
            original_code = "".join(self.src_lines[i_from:i_to])
            if "else" in original_code:
                return 1
            original_code = original_code.replace("elif", "if")
            try:
                ast.unparse(ast.parse(dedent(original_code)))
                return i_to - i_from
            except (IndentationError, SyntaxError):
                try:
                    # can we parse and unparse with an added line 'pass'
                    ast.unparse(ast.parse(dedent(original_code + (count_spaces(original_code) + 4) * " " + "pass")))
                    return i_to - i_from
                except (IndentationError, SyntaxError):
                    if i_to - i_from > 40:
                        raise Exception("The length of the multiline statement is longer than 40. Maybe somewhere "
                                        "it can't recognise the code ending and it gets syntax error recursively")
                    return get_multiline_rownum(i_from, i_to + 1)

        def is_last_row(uast_rownum: int) -> bool:
            """
            Returns: A boolean value representing whether the current row and node are the last in their
            respective structures. If they are, returns True. Otherwise, returns None.
            """
            if len(self.analyzer.branches[node]) - 1 == branch_num:  # last if node
                if len(unparsed_ast.splitlines()) - 1 == uast_rownum:
                    return True

        def unparsed_ast_with_comments_and_newlines(unparsed_ast: str) -> list:
            """
            Input:
            unparsed_ast - a string of unparsed code containing Python AST (Abstract Syntax Tree) nodes as lines.

            Returns:
            uast_store - a list of strings containing the parsed code with comments and newlines added

            Description: This function takes in an unparsed code containing Python AST nodes and adds comments and
            newlines to it. The output is a list of strings containing the parsed code.
            """
            global src_rownum, multiline_rownum

            uast_store = []
            src_rownum = node.test.lineno - 1
            for uast_rownum, uast_row in enumerate(unparsed_ast.splitlines()):
                last_row = is_last_row(uast_rownum)
                multiline_rownum = get_multiline_rownum(i_from=src_rownum - 1, i_to=src_rownum)

                if multiline_rownum > 1:
                    comment_store = ""
                    while multiline_rownum != 1:
                        komment = comment_nl_inserter("", last_row=last_row, add_nl=False)
                        multiline_rownum -= 1
                        src_rownum += 1
                        comment_store += komment
                    # add the comments and newlines to the end of the multiline statement
                    src_rownum += 1
                    uast_with_comments_nls = uast_row + \
                                             comment_store + comment_nl_inserter("", last_row=last_row, add_nl=True)
                elif multiline_rownum == 1:
                    uast_with_comments_nls = comment_nl_inserter(uast_row, last_row=last_row)
                    src_rownum += 1
                else:
                    raise Exception(
                        "Multiline rownum is slower than 1. Probably it is decreased somewhere by 2 times "
                        "instead of one.")
                uast_store.append(uast_with_comments_nls + "\n")

            return uast_store

        self.visited_nodes += 1
        self.analyzer.visit(node)
        if node in self.analyzer.subjects.keys():
            subjectNode = self.analyzer.subjects[node]
            _cases = []
            for branch_num, branch in enumerate(self.analyzer.branches[node]):
                if branch.flat:
                    for subBranch in branch.flat:
                        pattern = self.analyzer.patterns[subBranch]
                        transformed_branch = ast.match_case(pattern=pattern.transform(subjectNode),
                                                            guard=pattern.guard(subjectNode),
                                                            body=subBranch.body)
                        try:
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

            unparsed_ast = ast.unparse(ast.Match(subject=subjectNode, cases=_cases))

            self.results[node.test.lineno - 1] = unparsed_ast_with_comments_and_newlines(unparsed_ast)
            return ast.Match(subject=subjectNode, cases=_cases)
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
            src.seek(0)
            self.src_lines = tuple(src.readlines())
            src.seek(0)
            self.preserved_comments(src)
            src.seek(0)

            parsed_code = self.visit(tree)

            # Use the `ast.fix_missing_locations()` function to add line information to the parsed AST
            ast.fix_missing_locations(parsed_code)

            # Convert the parsed AST back to code while preserving indentation
            transformed_code_str = ast.unparse(parsed_code)

            # Extract comments from the original code
            tokens = tokenize.generate_tokens(io.StringIO(src.read()).readline)
            comments = [t for t in tokens if t.type == tokenize.COMMENT]

            # Insert comments into the transformed code
            transformed_lines = transformed_code_str.splitlines()
            for comment in comments:
                line_num = comment.start[0] - 1  # Convert 1-based line numbers to 0-based
                comment_str = comment.string.strip()
                transformed_lines.insert(line_num, comment_str)

            # Join the transformed lines into a single string
            transformed_code_str = "\n".join(transformed_lines)

            if len(self.results.keys()) == 0:
                return

        i = 0
        while i < len(self.src_lines):
            if i in self.results.keys():
                # print(f"LINE {i} IS IN RESULTS")
                if_length, offset = count_actual_lines(self.src_lines, i)
                self.results[i] = (self.results[i], if_length)
                if offset != 0:
                    # print(f" AT LINE ({i}) OFFSET IS: {offset}")
                    self.results[i + offset] = self.results[i]
            i += 1

        with open(file, "w", encoding='utf-8') as out:
            # print("FFÁÁJL", file)
            i = 0
            while i < len(self.src_lines):
                if i in self.results.keys():
                    indent = indentation(self.src_lines[i])
                    res = self.results[i][0]
                    for newLine in res:
                        # print(indent)
                        out.write(indent * " " + newLine)
                    i += self.results[i][1] - 1
                else:
                    out.write(self.src_lines[i])
                i += 1
        subprocess.run(["python3.11", "-m", "black", "--line-length", "79", file])
        subprocess.run(["python3.11", "-m", "autopep8", file])

        # Checking for SyntaxErrors in the transformed file
        with open(file, "r", encoding='utf-8') as f:
            new_lines = f.read()
            f.seek(0)
            newlines = f.readlines()

        try:
            ast.parse(new_lines)
        except SyntaxError as err:
            self.log(f"REVERTING {file}: SyntaxError: {err.msg} - line({err.lineno})")
            print("SYNTAX ERR", f"REVERTING {file}: SyntaxError: {err.msg} - line({err.lineno})")
            with open(file, "w", encoding='utf-8') as f:
                f.writelines(self.src_lines)
            return

        if self.generate_diffs and OutputHandler.OUTPUT_FOLDER:
            import os
            from pathlib import Path

            diff = difflib.context_diff(self.src_lines, newlines, fromfile=str(file), tofile=str(file))
            diffile = (OutputHandler.OUTPUT_FOLDER / 'diffs' / f'{os.path.basename(file)}-diffs.diff').resolve()

            with open(diffile, 'w', encoding='utf-8') as f:
                f.writelines(diff)

    def preserved_comments(self, src):
        """
        Description: The preserved_comments function takes the original file object as input and reads it line by line,
        identifying any comments or empty newlines in the code. The function returns a dictionary containing the line
        number and the comment string iteslf and empty newlines found.
        """
        global comments
        if self.preserve_comments:
            comments = {}
            src.seek(0)
            tokens = generate_tokens(src.readline)
            cyclestart = True
            for token in tokens:
                if token.type == 61:
                    if cyclestart:
                        comments[f"out{token.start[0]}"] = token.string  # full row comment
                    else:
                        comments[f"in{token.start[0]}"] = token.string  # inline comment
                    cyclestart = False
                elif token.string == "\n":
                    cyclestart = True
                else:
                    cyclestart = False
            for i, row in enumerate(self.src_lines):
                if row.replace(" ", "").replace("\t", "") == "\n":
                    comments[f"nl{i + 1}"] = True  # empty newline
