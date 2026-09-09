import ast
import operator
import numpy as np

class SafeMathEvaluator:
    """
    A strictly restricted expression evaluator that only permits
    basic mathematical operations and predefined variables.
    """
    
    ALLOWED_OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos
    }

    @classmethod
    def evaluate(cls, expression: str, context: dict):
        try:
            tree = ast.parse(expression.strip(), mode='eval')
        except SyntaxError as e:
            raise ValueError(f"Invalid mathematical expression: {expression}") from e
            
        return cls._eval_node(tree.body, context)

    @classmethod
    def _eval_node(cls, node, context):
        if isinstance(node, getattr(ast, 'Constant', type(None))):
            return node.value
        elif type(node).__name__ == 'Num': # Fallback for Python < 3.8
            return node.n
        elif isinstance(node, ast.Name):
            if node.id in context:
                return context[node.id]
            else:
                raise ValueError(f"Variable '{node.id}' not provided in context.")
        elif isinstance(node, ast.BinOp):
            left = cls._eval_node(node.left, context)
            right = cls._eval_node(node.right, context)
            op_type = type(node.op)
            if op_type in cls.ALLOWED_OPERATORS:
                return cls.ALLOWED_OPERATORS[op_type](left, right)
            else:
                raise ValueError(f"Unsupported binary operator: {op_type}")
        elif isinstance(node, ast.UnaryOp):
            operand = cls._eval_node(node.operand, context)
            op_type = type(node.op)
            if op_type in cls.ALLOWED_OPERATORS:
                return cls.ALLOWED_OPERATORS[op_type](operand)
            else:
                raise ValueError(f"Unsupported unary operator: {op_type}")
        else:
            raise ValueError(f"Unsupported expression node type: {type(node)}")
