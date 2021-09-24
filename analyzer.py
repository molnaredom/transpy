import ast


class Analyzer(ast.NodeVisitor):
    def __init__(self):
        self.save_file = open("to_transform.py", "w")
        self.valid_nodes = []

    def __del__(self):
        self.save_file.close()

    def save_code(self, node, start, end):
        self.save_file.write(f"# {start} - {end}\n" + ast.unparse(node) + "\n")

    def get_var_from_if(self, node):
        #Returns false if the If-node's test is not either in the form 'id == constant' or 'constant == id'
        #Returns the variable's id (name) otherwise
        match node.test:
            case ast.Compare(left=ast.Name(id=var_id, ctx = _), ops =[ast.Eq()], comparators=[ast.Constant(_)]) | ast.Compare(left=ast.Constant(_), ops =[ast.Eq()], comparators=[ast.Name(id=var_id, ctx = _)]):
                return var_id
            case _:
                return False

    def visit_If(self, node):
        #print(f"## Found and If, at line number: {node.lineno} ##")
        variable_id = ""
        last_line = -1

        variable_id = self.get_var_from_if(node)
        if not variable_id:
            return

        depth = 0
        current = node 
        # Going through and counting all the elif nodes and checking their form
        while len(current.orelse) and isinstance(current.orelse[0], ast.If):
            depth += 1
            current = current.orelse[0]
            if not self.get_var_from_if(current) == variable_id:
                return

            
        if not len(current.orelse): # If there is no last else: block
            last_line = current.body[-1].lineno
        else:
            last_line = current.orelse[-1].lineno

        #print(f"# This If that spans from line number ({node.lineno} - {last_line}) has ({depth}) elif-s #")
        self.save_code(node, node.lineno, last_line)


   






def main():
    with open("test.py", "r") as src:
        tree = ast.parse(src.read())
    Analyzer().visit(tree)

if __name__ == "__main__":
    main()

    