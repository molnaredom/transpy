import ast
from analyzer.utils import get_branches, load_patterns, flatten
from analyzer import config
from .utils import OutputHandler

class Analyzer(ast.NodeVisitor):
    Patterns = None

    def recognise_Branch(self, branch):
        """Passes the branch to all known Patterns. Returns the pattern that recognises it. Returns None, if no pattern recognises the branch."""
        for pattern in Analyzer.Patterns:
            curr_pattern = pattern()
            if curr_pattern.visit(branch.test):
                return curr_pattern
        return None

    def log(self, text):
        if self.logger is not None:
            self.logger.log(text)

    def __init__(self):
        self.branches = {} # Mapping If-nodes to a list of its branches. !!Only contains transformable if-nodes!!
        self.patterns = {} # Mapping branches to a pattern
        self.subjects = {} # Mapping the If-node to its selected subject !!Only contains transformable if-nodes!!
        self.logger = OutputHandler("analyzer.log") if config["OUTPUT"].getboolean("AllowAnalyzerLogs") else None
        self.file = "DEFAULT_FILENAME"
        if Analyzer.Patterns is None:
            Analyzer.Patterns = tuple(load_patterns())
            for pattern in Analyzer.Patterns:
                pattern.Patterns = Analyzer.Patterns

    def visit_If(self, node):
        self.branches[node] = get_branches(node)

        # Looping through the If-nodes branches
        for branch in self.branches[node]:
            # Skipping trivial 'else:' branches.
            if branch.test is None:
                continue

            # Determine the main pattern of the branch
            branch_pattern = self.recognise_Branch(branch)
            if branch_pattern is None: # If no pattern recognises the branch, then delete the whole if node from the dict and return.
                self.log(f"If-node in '{self.file}' at line ({node.test.lineno}) is not transformable: Branch ({ast.unparse(branch.test)}) is not recognisable!")
                del self.branches[node]
                return

            self.patterns[branch] = branch_pattern



        # An if-node can be transformed, if all of its branches are recognised patterns, and these patterns can all recognise the same subject.
        # Intersecting the possible subjects for each branch
        potential_subjects = self.patterns[self.branches[node][0]].potential_subjects().copy()

        # Skipping "else:" branch
        for branch in [b for b in self.branches[node] if b.test is not None]:
            potential_subjects = potential_subjects.intersection(self.patterns[branch].potential_subjects())


        if len(potential_subjects) == 0: # No common subject across branches -> reject
            self.log(f"If-node in '{self.file}' at line ({node.test.lineno}) is not transformable: No common subject is found!")
            del self.branches[node]
            return
        elif len(potential_subjects) > 1: # More than one common subjects across branches -> choose randomly
            subjects = set()
            for subj in potential_subjects:
                subjects.add(ast.unparse(subj))
            self.log(f"If-node in '{self.file}' at line ({node.test.lineno}) has more than one common subjects: {subjects}")

        self.subjects[node] = potential_subjects.pop()

        number_of_subBranches = 0
        for branch in self.branches[node]:
            # Checking nested If-nodes
            subBranches = flatten(branch)
            if subBranches is not None: # Have to determine which version to transform: flattened, or base
                isUgly = False
                can_be_flattened = True
                for subBranch in subBranches:
                    pattern = self.recognise_Branch(subBranch) # NOT Guaranteed to be GuardPattern
                    if pattern is None:
                        can_be_flattened = False
                        self.log(f"Branch in '{self.file}' at line ({branch.body[0].lineno-1}) cannot be flattened! No pattern recognises: ({ast.unparse(subBranch.test)})")
                        break

                    self.patterns[subBranch] = pattern
                    # Flattened branches tests always look like: BoolOp(And(), [mainTest, (nestedTest)*])
                    # Have to check if the patterns guard == nestedTest (if nestedTest is not None)
                    # Guard looks like: BoolOp(And(), [values])
                    guard = pattern.guard(self.subjects[node])
                    if guard is not None:
                        guardList = guard.values
                        temp = subBranch.test.values.copy()
                        match subBranch.mainTest:
                            case ast.BoolOp(op = ast.And()):
                                for term in subBranch.mainTest.values:
                                    if term in temp:
                                        temp.remove(term)
                            case _:
                                temp.remove(subBranch.mainTest)

                        if temp == guardList: # Found ugly branch
                            if not config["FLATTENING"].getboolean("AllowUglyFlattening"):
                                self.log(f"Branch in '{self.file}' at line ({branch.body[0].lineno-1}) cannot be flattened! Would result in ugly subBranch: ({ast.unparse(subBranch.test)})")
                            isUgly = True

                if (not isUgly or config["FLATTENING"].getboolean("AllowUglyFlattening")) and can_be_flattened:
                    branch.flat = subBranches
                    number_of_subBranches += len(subBranches)

            else:
                self.log(f"Branch in '{self.file}' at line ({branch.body[0].lineno-1}) cannot be flattened!")
        # print("-----\nnumber_of_subBranches", number_of_subBranches)
        # print("LEN self.branches[node]", len(self.branches[node]))
        # TODO config: minimum number of branches for an If-node to be transformed
        if len(self.branches[node]) + number_of_subBranches < config["MAIN"].getint("MinimumBranches"):
            self.log(f"If-node in '{self.file}' at line ({node.test.lineno}) does not have enough branches: ({len(self.branches[node]) + number_of_subBranches})")
            del self.branches[node]
            del self.subjects[node]





def main():
    pass



if __name__ == "__main__":
    main()



