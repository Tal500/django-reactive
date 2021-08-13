from abc import abstractmethod
from typing import Dict, Iterator, List, Optional, Tuple

from django import template

from ..core.base import ReactContext, ReactValType, ReactHook, ReactVar, value_to_expression

common_delimiters = [('(', ')'), ('[', ']'), ('{', '}')]

def match_and_return_second(char: str, pairs: List[Tuple[str, str]]):
    for first, second in pairs:
        if char == first:
            return second
    # otherwise

    return None

# TODO: Handle correct string parsing, and raise exception on syntax error?
def smart_split(expression: str, seperator: str, delimiters: List[Tuple[str, str]]) -> Iterator[str]:
    i = 0
    loc = 0

    end_delimiters_stack = []

    for loc, char in enumerate(expression):
        if len(end_delimiters_stack) == 0:
            if char == seperator and len(end_delimiters_stack) == 0:
                yield expression[i:loc]
                i = loc + 1
                continue
        else:
            if char == end_delimiters_stack[-1]:
                end_delimiters_stack.pop()
                continue
        # otherwise

        if end_delimiter := match_and_return_second(char, delimiters):
            end_delimiters_stack.append(end_delimiter)\

    yield expression[i:]

class Expression:
    """ An immutable structure for holding expressions. """

    @abstractmethod
    def reduce(self, template_context: template.Context):
        """ Return a reduced expression with template context variables subtituted. """
        pass

    @abstractmethod
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        """ Return the evaluated initial value """
        pass

    @abstractmethod
    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        """ Return a tupple of (js_expression, hooks) """
        pass
class SettableExpression(Expression):
    @abstractmethod
    def js_set(self, react_context: Optional[ReactContext], js_expression: str) -> str:
        """ Return the js expression for setting the self expression to the js_expression"""
        pass

    @abstractmethod
    def js_notify(self, react_context: Optional[ReactContext]) -> str:
        """ Return the js expression for notifying the self expression"""
        pass

class StringExpression(Expression):
    def __init__(self, val: str):
        self.val = val
    
    def reduce(self, template_context: template.Context):
        return self
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return self.val

    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        return f"'{self.val}'", []
    
    @staticmethod
    def try_parse(expression: str) -> Optional['StringExpression']:
        if len(expression) >= 2 and expression[0] == expression[-1] and (expression[0] == "'" or expression[0] == "'"):
            return StringExpression(expression[1:-1])# TODO: escape characters!
        else:
            return None

class IntExpression(Expression):
    def __init__(self, val: int):
        self.val = val
    
    def reduce(self, template_context: template.Context):
        return self
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return self.val

    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        return str(self.val), []
    
    @staticmethod
    def try_parse(expression: str) -> Optional['IntExpression']:
        if expression.isnumeric():
            return IntExpression(int(expression))
        else:
            return None

class BoolExpression(Expression):
    def __init__(self, val: bool):
        self.val = val
    
    def reduce(self, template_context: template.Context):
        return self
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return self.val

    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        return 'true' if self.val else 'false', []
    
    @staticmethod
    def try_parse(expression: str) -> Optional['BoolExpression']:
        if expression == 'True' or expression == 'true':
            return BoolExpression(True)
        elif expression == 'False' or expression == 'false':
            return BoolExpression(False)
        else:
            return None

class NoneExpression(Expression):
    def __init__(self):
        pass
    
    def reduce(self, template_context: template.Context):
        return self
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return None

    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        return 'null', []
    
    @staticmethod
    def try_parse(expression: str) -> Optional['NoneExpression']:
        if expression == 'None' or expression == 'null':
            return NoneExpression()
        else:
            return None

class ArrayExpression(Expression):
    def __init__(self, elements_expression: List[Expression]):
        self.elements_expression = elements_expression
    
    def reduce(self, template_context: template.Context):
        return ArrayExpression([expression.reduce(template_context) for expression in self.elements_expression])
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return [expression.eval_initial(react_context) for expression in self.elements_expression]

    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        js_expressions, all_hooks = [], []

        for expression in self.elements_expression:
            js_expression, hooks = expression.eval_js_and_hooks(react_context)

            js_expressions.append(js_expression)
            all_hooks.extend(hooks)
        
        return f'[{",".join((expression for expression in js_expressions))}]', all_hooks
    
    @staticmethod
    def try_parse(expression: str) -> Optional['ArrayExpression']:
        if not (len(expression) >= 2 and expression[0] == '[' and expression[-1]==']'):
            return None
        # otherwise

        expression = expression[1:-1]

        parts = smart_split(expression, ',', common_delimiters)

        return ArrayExpression([parse_expression(part) for part in parts])

class DictExpression(Expression):
    def __init__(self, dict_expression: Dict[str, Expression]):
        self.dict_expression = dict_expression
    
    def __repr__(self) -> str:
        return f'{super().__repr__()}{{{",".join((f"{key}:{repr(expression)}" for key, expression in self.dict_expression.items()))}}}'
    
    def reduce(self, template_context: template.Context):
        return DictExpression({key: expression.reduce(template_context) for key, expression in self.dict_expression.items()})
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return {key: expression.eval_initial(react_context) for key, expression in self.dict_expression.items()}

    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        key_js_expressions, all_hooks = [], []

        for key, expression in self.dict_expression.items():
            js_expression, hooks = expression.eval_js_and_hooks(react_context)

            key_js_expressions.append((key, js_expression))
            all_hooks.extend(hooks)
        
        return f'{{{",".join((f"{key}:{expression}" for key, expression in key_js_expressions))}}}', all_hooks
    
    @staticmethod
    def try_parse(expression: str) -> Optional['DictExpression']:
        if not (len(expression) >= 2 and expression[0] == '{' and expression[-1]=='}'):
            return None
        # otherwise

        expression = expression[1:-1]

        parts = smart_split(expression, ',', common_delimiters)

        def split_part(part: str) -> Tuple[str, Expression]:
            seperator = part.find(':')
            if seperator == -1:
                raise template.TemplateSyntaxError("Can't find key-value seperator ':'")

            key = part[:seperator]
            val_str = part[seperator+1:]

            if key_expression := StringExpression.try_parse(key):
                key = key_expression.val

            return key, parse_expression(val_str)

        try:
            return DictExpression(dict(split_part(part) for part in parts))
        except:
            return None

class VariableExpression(SettableExpression):
    def __init__(self, var_name):
        assert(" " not in var_name)
        self.var_name = var_name
    
    def __str__(self):
        return self.var_name
    
    def reduce(self, template_context: template.Context):
        if self.var_name in template_context:
            val = template_context[self.var_name]
            return value_to_expression(val)
        else:
            return self
    
    def var(self, react_context: Optional[ReactContext]) -> Optional[ReactVar]:
        if react_context is None:
            raise Exception("Can't evaluate a VariableExpression if react_context=None")
        # otherwise

        # Notice: Might return none which means that the variable isn't registered as reactive variable.
        return react_context.search_var(self.var_name)
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        var = self.var(react_context)

        if var:
            return var.expression.eval_initial(react_context)
        else:
            return ''

    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        var = self.var(react_context)

        if var:
            return var.js_get(), [var]
        else:
            return value_to_expression('').eval_js_and_hooks(react_context)
    
    def js_set(self, react_context: Optional[ReactContext], js_expression: str):
        var = self.var(react_context)

        if var is None:
            raise template.TemplateSyntaxError('No reactive variable named %s was found' % self.var_name)

        return var.js_set(js_expression)
    
    def js_notify(self, react_context: Optional[ReactContext]) -> str:
        var = self.var(react_context)

        if var is None:
            raise template.TemplateSyntaxError('No reactive variable named %s was found' % self.var_name)

        return var.js_notify()
    
    @staticmethod
    def try_parse(expression: str) -> Optional['VariableExpression']:
        if expression.isidentifier():
            return VariableExpression(expression)
        else:
            return None

class PropertyExpression(Expression):
    def __init__(self, root_expression: Expression, key_path: List[str]):
        # TODO: Support also "[]" and not only "."

        assert(key_path)

        self.root_expression: Expression = root_expression
        self.key_path: List[str] = key_path
    
    def __str__(self):
        return '(' + str(self.root_expression) + ').' + '.'.join(self.key_path)
    
    def __repr__(self) -> str:
        return f'{super().__repr__()}({self})'
    
    def reduce(self, template_context: template.Context):
        root_expression_reduced = self.root_expression.reduce(template_context)
        
        return PropertyExpression(root_expression_reduced, self.key_path)
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        root_val = self.root_expression.eval_initial(react_context)

        current: ReactValType = root_val

        for key in self.key_path:
            if key in current:
                current = current[key]
            else:
                raise template.TemplateSyntaxError(f"Error while parsing expression {self}: " +\
                    "There is no key named {key} in {current}")

    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        root_var_js, hooks = self.root_expression.eval_js_and_hooks(react_context)

        return '(' + root_var_js + ').' + '.'.join(self.key_path), hooks
    
    @staticmethod
    def try_parse(expression: str) -> Optional['PropertyExpression']:
        parts = list(smart_split(expression, '.', common_delimiters))

        if len(parts) <= 1:
            return None
        # otherwise

        root_expression = parse_expression(parts[0])
        if root_expression is None:
            return None
        # otherwise

        key_path = parts[1:]
        for key in key_path:
            if key is None or (not key.isidentifier()):
                return None
        # otherwise
        
        if isinstance(root_expression, SettableExpression):
            return SettablePropertyExpression(root_expression, key_path)
        else:
            return PropertyExpression(root_expression, key_path)

class SettablePropertyExpression(PropertyExpression, SettableExpression):
    def __init__(self, root_expression: SettableExpression, key_path: List[str]):
        super().__init__(root_expression, key_path)
    
    def reduce(self, template_context: template.Context):
        root_expression_reduced = self.root_expression.reduce(template_context)
        
        return SettablePropertyExpression(root_expression_reduced, self.key_path)
    
    def js_set(self, react_context: Optional[ReactContext], js_expression: str):
        js_path_expression = self.eval_js_and_hooks(react_context)[0]

        return f'{js_path_expression} = {js_expression}; ' + self.js_notify(react_context)
    
    def js_notify(self, react_context: Optional[ReactContext]) -> str:
        settable_expression: SettableExpression = self.root_expression
        return settable_expression.js_notify(react_context)

def remove_whitespaces_on_boundaries(s: str):
    for i in range(len(s)):
        if s[i] not in [' ', '\t', '\n']:
            break
    
    for j in reversed(range(i, len(s))):
        if s[j] not in [' ', '\t', '\n']:
            break
    
    return s[i:j+1]

def parse_expression(expression: str):
    expression = remove_whitespaces_on_boundaries(expression)
    
    if expression[0] == '(' and expression[-1] == ')':
        return parse_expression(expression[1:-1])
    elif exp := StringExpression.try_parse(expression):
        return exp
    elif exp := BoolExpression.try_parse(expression):
        return exp
    elif exp := IntExpression.try_parse(expression):
        return exp
    elif exp := NoneExpression.try_parse(expression):
        return exp
    elif exp := ArrayExpression.try_parse(expression):
        return exp
    elif exp := DictExpression.try_parse(expression):
        return exp
    elif exp := VariableExpression.try_parse(expression):
        return exp
    elif exp := PropertyExpression.try_parse(expression):
        return exp
    else:
        raise template.TemplateSyntaxError(f"Can't parse expression: ({expression})")