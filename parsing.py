"""
Maintainer: David Halter <davidhalter88@gmail.com>
Version: 0.1

py_fuzzyparser parses python code, with the goal of a good representation of
the code within a tree structure. Variables, Classes and Functions are defined
within this tree structure, containing their exact locations in the code.
It is also a primary goal to work with code which contains syntax errors.

This behaviour may be used to refactor, modify, search and complete code.

To understand this code it is extremely important to understand the behaviour
of the python module 'tokenize'.

This original codebase of this parser, which has been refactored and heavily
changed, was programmed by Aaron Griffin <aaronmgriffin@gmail.com>.

**The structure of the following script:**
A Scope has
 - imports (Import)
 - subscopes (Scope, Class, Function, Flow)
 - statements (Statement)

All those classes are being generated by PyFuzzyParser, which takes python text
as input.

Ignored statements:
 - print (no use for it, just slows down)
 - exec (dangerous - not controllable)

TODO take special care for future imports
TODO check meta classes
TODO evaluate options to either replace tokenize or change its behavior for
multiline parentheses (if they don't close, there must be a break somewhere)
"""

import tokenize
import cStringIO
import re


def indent_block(text, indention="    "):
    """ This function indents a text block with a default of four spaces """
    temp = ''
    while text and text[-1] == '\n':
        temp += text[-1]
        text = text[:-1]
    lines = text.split('\n')
    return '\n'.join(map(lambda s: indention + s, lines)) + temp


class Simple(object):
    """
    The super class for Scope, Import, Name and Statement. Every object in
    the parser tree inherits from this class.
    """
    def __init__(self, indent, line_nr, line_end=None):
        self.indent = indent
        self.line_nr = line_nr
        self.line_end = line_end
        self.parent = None


class Scope(Simple):
    """
    Super class for the parser tree, which represents the state of a python
    text file.
    A Scope manages and owns its subscopes, which are classes and functions, as
    well as variables and imports. It is used to access the structure of python
    files.

    :param indent: The indent level of the flow statement.
    :type indent: int
    :param line_nr: Line number of the flow statement.
    :type line_nr: int
    :param docstr: The docstring for the current Scope.
    :type docstr: str
    """
    def __init__(self, indent, line_nr, docstr=''):
        super(Scope, self).__init__(indent, line_nr)
        self.subscopes = []
        self.imports = []
        self.statements = []
        self.global_vars = []
        self.docstr = docstr

    def add_scope(self, sub, decorators):
        # print 'push scope: [%s@%s]' % (sub.line_nr, sub.indent)
        sub.parent = self
        sub.decorators = decorators
        self.subscopes.append(sub)
        return sub

    def add_statement(self, stmt):
        """
        Used to add a Statement or a Scope.
        A statement would be a normal command (Statement) or a Scope (Flow).
        """
        stmt.parent = self
        self.statements.append(stmt)
        return stmt

    def add_docstr(self, string):
        """ Clean up a docstring """

        # TODO use prefixes, to format the doc strings
        # scan for string prefixes like r, u, etc.
        index1 = string.find("'")
        index2 = string.find('"')
        index = index1 if index1 < index2 and index1 > -1 else index2
        prefix = string[:index]
        d = string[index:]
        print 'docstr', d, prefix

        # now clean docstr
        d = d.replace('\n', ' ')
        d = d.replace('\t', ' ')
        while d.find('  ') > -1:
            d = d.replace('  ', ' ')
        while d[0] in '"\'\t ':
            d = d[1:]
        while d[-1] in '"\'\t ':
            d = d[:-1]
        dbg("Scope(%s)::docstr = %s" % (self, d))
        self.docstr = d

    def add_import(self, imp):
        self.imports.append(imp)

    def add_global(self, name):
        """
        Global means in these context a function (subscope) which has a global
        statement.
        This is only relevant for the top scope.

        :param name: The name of the global.
        :type name: Name
        """
        self.global_vars.append(name)

    def _checkexisting(self, test):
        "Convienance function... keep out duplicates"
        if test.find('=') > -1:
            var = test.split('=')[0].strip()
            for l in self.locals:
                if l.find('=') > -1 and var == l.split('=')[0].strip():
                    self.locals.remove(l)

    def get_code(self, first_indent=False, indention="    "):
        """
        :return: Returns the code of the current scope.
        :rtype: str
        """
        string = ""
        if len(self.docstr) > 0:
            string += '"""' + self.docstr + '"""\n'
        for i in self.imports:
            string += i.get_code()
        for sub in self.subscopes:
            #string += str(sub.line_nr)
            string += sub.get_code(first_indent=True, indention=indention)
        for stmt in self.statements:
            string += stmt.get_code()

        if first_indent:
            string = indent_block(string, indention=indention)
        return string

    def get_set_vars(self):
        """
        Get all the names, that are active and accessible in the current
        scope.

        :return: list of Name
        :rtype: list
        """
        n = []
        for stmt in self.statements:
            n += stmt.get_set_vars()

        # function and class names
        n += [s.name for s in self.subscopes]
        n += self.global_vars

        for i in self.imports:
            n += i.get_names()

        return n

    def is_empty(self):
        """
        :return: True if there are no subscopes, imports and statements.
        :rtype: bool
        """
        return not (self.imports or self.subscopes or self.statements)

    def get_simple_for_line(self, line):
        """ Get the Simple objects, which are on the line. """
        simple = []
        for s in self.statements + self.imports:
            if s.line_nr <= line <= s.line_end:
                simple.append(s)
        return simple

    def __repr__(self):
        try:
            name = self.name
        except:
            try:
                name = self.command
            except:
                name = 'global'

        return "<%s: %s@%s-%s>" % \
                (self.__class__.__name__, name, self.line_nr, self.line_end)


class Class(Scope):
    """
    Used to store the parsed contents of a python class.

    :param name: The Class name.
    :type name: string
    :param name: The super classes of a Class.
    :type name: list
    :param indent: The indent level of the flow statement.
    :type indent: int
    :param line_nr: Line number of the flow statement.
    :type line_nr: int
    :param docstr: The docstring for the current Scope.
    :type docstr: str
    """
    def __init__(self, name, supers, indent, line_nr, docstr=''):
        super(Class, self).__init__(indent, line_nr, docstr)
        self.name = name
        self.supers = supers
        self.decorators = []

    def get_code(self, first_indent=False, indention="    "):
        str = "\n".join('@' + stmt.get_code() for stmt in self.decorators)
        str += 'class %s' % (self.name)
        if len(self.supers) > 0:
            sup = ','.join(stmt.code for stmt in self.supers)
            str += '(%s)' % sup
        str += ':\n'
        str += super(Class, self).get_code(True, indention)
        if self.is_empty():
            str += "pass\n"
        return str

    def get_set_vars(self):
        n = []
        for s in self.subscopes:
            try:
                # get the self name, if there's one
                self_name = s.params[0].used_vars[0].names[0]
            except:
                pass
            else:
                for n2 in s.get_set_vars():
                    # Only names with the selfname are being added.
                    # It is also important, that they have a len() of 2,
                    # because otherwise, they are just something else
                    if n2.names[0] == self_name and len(n2.names) == 2:
                        n.append(n2)
        n += super(Class, self).get_set_vars()
        return n


class Function(Scope):
    """
    Used to store the parsed contents of a python function.

    :param name: The Function name.
    :type name: string
    :param params: The parameters (Statement) of a Function.
    :type name: list
    :param indent: The indent level of the flow statement.
    :type indent: int
    :param line_nr: Line number of the flow statement.
    :type line_nr: int
    :param docstr: The docstring for the current Scope.
    :type docstr: str
    """
    def __init__(self, name, params, indent, line_nr, docstr=''):
        Scope.__init__(self, indent, line_nr, docstr)
        self.name = name
        self.params = params
        self.decorators = []

    def get_code(self, first_indent=False, indention="    "):
        str = "\n".join('@' + stmt.get_code() for stmt in self.decorators)
        params = ','.join([stmt.code for stmt in self.params])
        str += "def %s(%s):\n" % (self.name, params)
        str += super(Function, self).get_code(True, indention)
        if self.is_empty():
            str += "pass\n"
        return str

    def get_set_vars(self):
        n = []
        for i, p in enumerate(self.params):
            n += p.set_vars or p.used_vars
        n += super(Function, self).get_set_vars()
        return n


class Flow(Scope):
    """
    Used to describe programming structure - flow statements,
    which indent code, but are not classes or functions:

    - for
    - while
    - if
    - try
    - with

    Therefore statements like else, except and finally are also here,
    they are now saved in the root flow elements, but in the next variable.

    :param command: The flow command, if, while, else, etc.
    :type command: str
    :param statement: The statement after the flow comand -> while 'statement'.
    :type statement: Statement
    :param indent: The indent level of the flow statement.
    :type indent: int
    :param line_nr: Line number of the flow statement.
    :type line_nr: int
    :param set_vars: Local variables used in the for loop (only there).
    :type set_vars: list
    """
    def __init__(self, command, statement, indent, line_nr, set_vars=None):
        super(Flow, self).__init__(indent, line_nr, '')
        self.command = command
        self.statement = statement
        if set_vars == None:
            self.set_vars = []
        else:
            self.set_vars = set_vars
        self.next = None

    def get_code(self, first_indent=False, indention="    "):
        if self.set_vars:
            vars = ",".join(map(lambda x: x.get_code(), self.set_vars))
            vars += ' in '
        else:
            vars = ''

        if self.statement:
            stmt = self.statement.get_code(new_line=False)
        else:
            stmt = ''
        str = "%s %s%s:\n" % (self.command, vars, stmt)
        str += super(Flow, self).get_code(True, indention)
        if self.next:
            str += self.next.get_code()
        return str

    def get_set_vars(self):
        """
        Get the names for the flow. This includes also a call to the super
        class.
        """
        n = self.set_vars
        if self.statement:
            n += self.statement.set_vars
        if self.next:
            n += self.next.get_set_vars()
        n += super(Flow, self).get_set_vars()
        return n

    def set_next(self, next):
        """ Set the next element in the flow, those are else, except, etc. """
        if self.next:
            return self.next.set_next(next)
        else:
            self.next = next
            next.parent = self.parent
            return next


class Import(Simple):
    """
    Stores the imports of any Scopes.

    >>> 1+1
    2

    :param line_nr: Line number.
    :type line_nr: int
    :param namespace: The import, as an array list of Name, \
    e.g. ['datetime', 'time'].
    :type namespace: list
    :param alias: The alias of a namespace(valid in the current namespace).
    :type alias: str
    :param from_ns: Like the namespace, can be equally used.
    :type from_ns: list
    :param star: If a star is used -> from time import *.
    :type star: bool
    """
    def __init__(self, indent, line_nr, line_end, namespace, alias='', \
                    from_ns='', star=False):
        super(Import, self).__init__(indent, line_nr, line_end)
        self.namespace = namespace
        self.alias = alias
        self.from_ns = from_ns
        self.star = star

    def get_code(self):
        if self.alias:
            ns_str = "%s as %s" % (self.namespace, self.alias)
        else:
            ns_str = str(self.namespace)
        if self.from_ns:
            if self.star:
                ns_str = '*'
            return "from %s import %s" % (self.from_ns, ns_str) + '\n'
        else:
            return "import " + ns_str + '\n'

    def get_names(self):
        if self.star:
            return [self]
        return [self.alias] if self.alias else [self.namespace]


class Statement(Simple):
    """
    This is the class for all the possible statements. Which means, this class
    stores pretty much all the Python code, except functions, classes, imports,
    and flow functions like if, for, etc.

    :param code: The full code of a statement. This is import, if one wants \
    to execute the code at some level.
    :param code: str
    :param set_vars: The variables which are defined by the statement.
    :param set_vars: str
    :param used_funcs: The functions which are used by the statement.
    :param used_funcs: str
    :param used_vars: The variables which are used by the statement.
    :param used_vars: str
    :param indent: The indent level of the flow statement.
    :type indent: int
    :param line_nr: Line number of the flow statement.
    :type line_nr: int
    """
    def __init__(self, code, set_vars, used_funcs, used_vars, indent, line_nr,
            line_end):
        super(Statement, self).__init__(indent, line_nr, line_end)
        self.code = code
        self.set_vars = set_vars
        self.used_funcs = used_funcs
        self.used_vars = used_vars

    def get_code(self, new_line=True):
        if new_line:
            return self.code + '\n'
        else:
            return self.code

    def get_set_vars(self):
        """ Get the names for the statement. """
        return self.set_vars


class Name(Simple):
    """
    Used to define names in python.
    Which means the whole namespace/class/function stuff.
    So a name like "module.class.function"
    would result in an array of [module, class, function]
    """
    def __init__(self, names, indent, line_nr, line_end):
        super(Name, self).__init__(indent, line_nr, line_end)
        self.names = tuple(names)

    def get_code(self):
        """ Returns the names in a full string format """
        return ".".join(self.names)

    def __str__(self):
        return self.get_code()

    def __eq__(self, other):
        return self.names == other.names \
                and self.indent == other.indent \
                and self.line_nr == self.line_nr

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.names) + hash(self.indent) + hash(self.line_nr)

    def __repr__(self):
        return "<%s: %s@%s>" % \
                (self.__class__.__name__, self.get_code(), self.line_nr)


class PyFuzzyParser(object):
    """
    This class is used to parse a Python file, it then divides them into a
    class structure of different scopes.

    :param code: The codebase for the parser.
    :type code: str
    :param user_line: The line, the user is currently on.
    :type user_line: int
    """
    def __init__(self, code, user_line=None):
        self.user_line = user_line
        self.code = code

        # initialize global Scope
        self.top = Scope(0, 0)
        self.scope = self.top
        self.current = (None, None, None)

        self.parse()

    def _parsedotname(self, pre_used_token=None):
        """
        The dot name parser parses a name, variable or function and returns
        their names.

        :return: list of the names, token_type, nexttoken, start_indent, \
        start_line.
        :rtype: (Name, int, str, int, int)
        """
        names = []
        if pre_used_token is None:
            token_type, tok, indent = self.next()
            start_line = self.line_nr
            if token_type != tokenize.NAME and tok != '*':
                return ([], tok)
        else:
            token_type, tok, indent = pre_used_token
            start_line = self.line_nr
        names.append(tok)
        start_indent = indent
        while True:
            token_type, tok, indent = self.next()
            if tok != '.':
                break
            token_type, tok, indent = self.next()
            if token_type != tokenize.NAME:
                break
            names.append(tok)
        return (names, token_type, tok, start_indent, start_line)

    def _parse_value_list(self, pre_used_token=None):
        """
        A value list is a comma separated list. This is used for:
        >>> for a,b,self.c in enumerate(test)

        TODO there may be multiple "sub" value lists e.g. (a,(b,c)).
        """
        value_list = []
        if pre_used_token:
            token_type, tok, indent = pre_used_token
            n, token_type, tok, start_indent, start_line = \
                self._parsedotname(tok)
            if n:
                temp = Name(n, start_indent, start_line, self.line_nr)
                value_list.append()

        token_type, tok, indent = self.next()
        while tok != 'in' and token_type != tokenize.NEWLINE:
            n, token_type, tok, start_indent, start_line = \
                self._parsedotname(self.current)
            if n:
                temp = Name(n, start_indent, start_line, self.line_nr)
                value_list.append(temp)
            if tok == 'in':
                break

            token_type, tok, indent = self.next()
        return (value_list, tok)

    def _parseimportlist(self):
        """
        The parser for the imports. Unlike the class and function parse
        function, this returns no Import class, but rather an import list,
        which is then added later on.
        The reason, why this is not done in the same class lies in the nature
        of imports. There are two ways to write them:

        - from ... import ...
        - import ...

        To distinguish, this has to be processed after the parser.

        :return: List of imports.
        :rtype: list
        """
        imports = []
        while True:
            name, token_type, tok, start_indent, start_line = \
                self._parsedotname()
            if not name:
                break
            name2 = None
            if tok == 'as':
                name2, token_type, tok, start_indent2, start_line = \
                    self._parsedotname()
                name2 = Name(name2, start_indent2, start_line, self.line_nr)
            i = Name(name, start_indent, start_line, self.line_nr)
            imports.append((i, name2))
            while tok != "," and "\n" not in tok:
                token_type, tok, indent = self.next()
            if tok != ",":
                break
        return imports

    def _parseparen(self):
        """
        Functions and Classes have params (which means for classes
        super-classes). They are parsed here and returned as Statements.

        :return: List of Statements
        :rtype: list
        """
        names = []
        tok = None
        while tok not in [')', '\n', ':']:
            stmt, tok = self._parse_statement(added_breaks=',')
            if stmt:
                names.append(stmt)

        return names

    def _parsefunction(self, indent):
        """
        The parser for a text functions. Process the tokens, which follow a
        function definition.

        :return: Return a Scope representation of the tokens.
        :rtype: Function
        """
        start_line = self.line_nr
        token_type, fname, ind = self.next()
        if token_type != tokenize.NAME:
            return None

        fname = Name([fname], ind, self.line_nr, self.line_nr)

        token_type, open, ind = self.next()
        if open != '(':
            return None
        params = self._parseparen()

        token_type, colon, ind = self.next()
        if colon != ':':
            return None

        return Function(fname, params, indent, start_line)

    def _parseclass(self, indent):
        """
        The parser for a text class. Process the tokens, which follow a
        class definition.

        :return: Return a Scope representation of the tokens.
        :rtype: Class
        """
        start_line = self.line_nr
        token_type, cname, ind = self.next()
        if token_type != tokenize.NAME:
            print "class: syntax error - token is not a name@%s (%s: %s)" \
                    % (self.line_nr, tokenize.tok_name[token_type], cname)
            return None

        cname = Name([cname], ind, self.line_nr, self.line_nr)

        super = []
        token_type, next, ind = self.next()
        if next == '(':
            super = self._parseparen()
        elif next != ':':
            print "class: syntax error - %s@%s" % (cname, self.line_nr)
            return None

        return Class(cname, super, indent, start_line)

    def _parseassignment(self):
        """ TODO remove or replace, at the moment not used """
        assign = ''
        token_type, tok, indent = self.next()
        if token_type == tokenize.STRING or tok == 'str':
            return '""'
        elif tok == '(' or tok == 'tuple':
            return '()'
        elif tok == '[' or tok == 'list':
            return '[]'
        elif tok == '{' or tok == 'dict':
            return '{}'
        elif token_type == tokenize.NUMBER:
            return '0'
        elif tok == 'open' or tok == 'file':
            return 'file'
        elif tok == 'None':
            return '_PyCmplNoType()'
        elif tok == 'type':
            return 'type(_PyCmplNoType)'  # only for method resolution
        else:
            assign += tok
            level = 0
            while True:
                token_type, tok, indent = self.next()
                if tok in ('(', '{', '['):
                    level += 1
                elif tok in (']', '}', ')'):
                    level -= 1
                    if level == 0:
                        break
                elif level == 0:
                    if tok in (';', '\n'):
                        break
                    assign += tok
        return "%s" % assign

    def _parse_statement(self, pre_used_token=None, added_breaks=None):
        """
        Parses statements like:

        >>> a = test(b)
        >>> a += 3 - 2 or b

        and so on. One row at a time.

        :param pre_used_token: The pre parsed token.
        :type pre_used_token: set
        :return: Statement + last parsed token.
        :rtype: (Statement, str)
        """
        string = ''
        set_vars = []
        used_funcs = []
        used_vars = []
        level = 0  # The level of parentheses

        if pre_used_token:
            token_type, tok, indent = pre_used_token
        else:
            token_type, tok, indent = self.next()

        line_start = self.line_nr

        # the difference between "break" and "always break" is that the latter
        # will even break in parentheses. This is true for typical flow
        # commands like def and class and the imports, which will never be used
        # in a statement.
        breaks = ['\n', ':', ')']
        always_break = [';', 'import', 'from', 'class', 'def', 'try', 'except',
                        'finally']
        if added_breaks:
            breaks += added_breaks

        while not (tok in always_break or tok in breaks and level <= 0):
            set_string = None
            #print 'parse_stmt', tok, tokenize.tok_name[token_type]
            if tok == 'as':
                string += " %s " % tok
                token_type, tok, indent_dummy = self.next()
                if token_type == tokenize.NAME:
                    path, token_type, tok, start_indent, start_line = \
                            self._parsedotname(self.current)
                    n = Name(path, start_indent, start_line, self.line_nr)
                    set_vars.append(n)
                    string += ".".join(path)
                continue
            elif token_type == tokenize.NAME:
                #print 'is_name', tok
                if tok in ['return', 'yield', 'del', 'raise', 'assert']:
                    set_string = tok + ' '
                elif tok in ['print', 'exec']:
                    # delete those statements, just let the rest stand there
                    set_string = ''
                else:
                    path, token_type, tok, start_indent, start_line = \
                            self._parsedotname(self.current)
                    n = Name(path, start_indent, start_line, self.line_nr)
                    if tok == '(':
                        # it must be a function
                        used_funcs.append(n)
                    else:
                        if not n.names[0] in ['global']:
                            used_vars.append(n)
                    if string and re.match(r'[\w\d\'"]', string[-1]):
                        string += ' '
                    string += ".".join(path)
                    #print 'parse_stmt', tok, tokenize.tok_name[token_type]
                    continue
            elif '=' in tok and not tok in ['>=', '<=', '==', '!=']:
                # there has been an assignement -> change vars
                set_vars = used_vars
                used_vars = []
            elif tok in ['{', '(', '[']:
                level += 1
            elif tok in ['}', ')', ']']:
                level -= 1

            if set_string is not None:
                string = set_string
            else:
                string += tok
            # caution: don't use indent anywhere,
            # it's not working with the name parsing
            token_type, tok, indent_dummy = self.next()
        if not string:
            return None, tok
        #print 'new_stat', string, set_vars, used_funcs, used_vars
        stmt = Statement(string, set_vars, used_funcs, used_vars,\
                            indent, line_start, self.line_nr)
        return stmt, tok

    def next(self):
        """ Generate the next tokenize pattern. """
        type, tok, position, dummy, self.parserline = self.gen.next()
        (self.line_nr, indent) = position
        if self.line_nr == self.user_line:
            print 'user scope found [%s] =%s' % \
                    (self.parserline.replace('\n', ''), repr(self.scope))
            self.user_scope = self.scope
        self.last_token = self.current
        self.current = (type, tok, indent)
        return self.current

    def parse(self):
        """
        The main part of the program. It analyzes the given code-text and
        returns a tree-like scope. For a more detailed description, see the
        class description.

        :param text: The code which should be parsed.
        :param type: str

        :raises: IndentationError
        """
        buf = cStringIO.StringIO(self.code)
        self.gen = tokenize.generate_tokens(buf.readline)
        self.currentscope = self.scope

        extended_flow = ['else', 'except', 'finally']
        statement_toks = ['{', '[', '(', '`']

        decorators = []
        freshscope = True
        while True:
            try:
                token_type, tok, indent = self.next()
                dbg('main: tok=[%s] type=[%s] indent=[%s]'\
                    % (tok, token_type, indent))

                while token_type == tokenize.DEDENT and self.scope != self.top:
                    print 'dedent', self.scope
                    token_type, tok, indent = self.next()
                    if indent <= self.scope.indent:
                        self.scope.line_end = self.line_nr
                        self.scope = self.scope.parent

                # check again for unindented stuff. this is true for syntax
                # errors. only check for names, because thats relevant here. If
                # some docstrings are not indented, I don't care.
                while indent <= self.scope.indent \
                        and token_type in [tokenize.NAME] \
                        and self.scope != self.top:
                    print 'syntax_err, dedent @%s - %s<=%s', \
                            (self.line_nr, indent, self.scope.indent)
                    self.scope.line_end = self.line_nr
                    self.scope = self.scope.parent

                start_line = self.line_nr
                if tok == 'def':
                    func = self._parsefunction(indent)
                    if func is None:
                        print "function: syntax error@%s" % self.line_nr
                        continue
                    dbg("new scope: function %s" % (func.name))
                    freshscope = True
                    self.scope = self.scope.add_scope(func, decorators)
                    decorators = []
                elif tok == 'class':
                    cls = self._parseclass(indent)
                    if cls is None:
                        continue
                    freshscope = True
                    dbg("new scope: class %s" % (cls.name))
                    self.scope = self.scope.add_scope(cls, decorators)
                    decorators = []
                # import stuff
                elif tok == 'import':
                    imports = self._parseimportlist()
                    for m, alias in imports:
                        i = Import(indent, start_line, self.line_nr, m, alias)
                        self.scope.add_import(i)
                    freshscope = False
                elif tok == 'from':
                    mod, token_type, tok, start_indent, start_line2 = \
                        self._parsedotname()
                    if not mod or tok != "import":
                        print "from: syntax error..."
                        continue
                    mod = Name(mod, start_indent, start_line2, self.line_nr)
                    names = self._parseimportlist()
                    for name, alias in names:
                        star = name.names[0] == '*'
                        if star:
                            name = None
                        i = Import(indent, start_line, self.line_nr, name,
                                    alias, mod, star)
                        self.scope.add_import(i)
                    freshscope = False
                #loops
                elif tok == 'for':
                    value_list, tok = self._parse_value_list()
                    if tok == 'in':
                        statement, tok = self._parse_statement()
                        if tok == ':':
                            f = Flow('for', statement, indent, self.line_nr, \
                                        value_list)
                            dbg("new scope: flow for@%s" % (f.line_nr))
                            self.scope = self.scope.add_statement(f)

                elif tok in ['if', 'while', 'try', 'with'] + extended_flow:
                    added_breaks = []
                    command = tok
                    if command == 'except':
                        added_breaks += (',')
                    statement, tok = \
                        self._parse_statement(added_breaks=added_breaks)
                    if tok in added_breaks:
                        # the except statement defines a var
                        # this is only true for python 2
                        path, token_type, tok, start_indent, start_line2 = \
                                self._parsedotname()
                        n = Name(path, start_indent, start_line2, self.line_nr)
                        statement.set_vars.append(n)
                        statement.code += ',' + n.get_code()
                    if tok == ':':
                        f = Flow(command, statement, indent, self.line_nr)
                        dbg("new scope: flow %s@%s" % (command, self.line_nr))
                        if command in extended_flow:
                            # the last statement has to be another part of
                            # the flow statement
                            self.scope = self.scope.statements[-1].set_next(f)
                        else:
                            self.scope = self.scope.add_statement(f)
                # globals
                elif tok == 'global':
                    stmt, tok = self._parse_statement(self.current)
                    if stmt:
                        self.scope.add_statement(stmt)
                        print 'global_vars', stmt.used_vars
                        for name in stmt.used_vars:
                            # add the global to the top, because there it is
                            # important.
                            self.top.add_global(name)
                # decorator
                elif tok == '@':
                    stmt, tok = self._parse_statement()
                    decorators.append(stmt)
                elif tok == 'pass':
                    continue
                # check for docstrings
                elif token_type == tokenize.STRING:
                    if freshscope:
                        self.scope.add_docstr(tok)
                # this is the main part - a name can be a function or a normal
                # var, which can follow anything. but this is done by the
                # statement parser.
                elif token_type == tokenize.NAME or tok in statement_toks:
                    stmt, tok = self._parse_statement(self.current)
                    if stmt:
                        self.scope.add_statement(stmt)
                    freshscope = False
                #else:
                    #print "_not_implemented_", tok, self.parserline
            except StopIteration:  # thrown on EOF
                break
        #except StopIteration:
        #    dbg("parse error: %s, %s @ %s" %
        #        (sys.exc_info()[0], sys.exc_info()[1], self.parserline))
        return self.top


def dbg(*args):
    global debug_function
    if debug_function:
        debug_function(*args)


debug_function = None
