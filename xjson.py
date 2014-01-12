#!/usr/local/bin/python

__author__ = 'Amir Eshel <amir@eshel.com>'

import json
import sys
import argparse
import string
import urlparse
import urllib
import re
import os.path
from xutils import expand_file_paths

in_lines = 0
out_lines = 0
in_file_name = ''
out_file_name = ''
args = None


def _fix_regexp(f):
    if isinstance(f, str):
        return re.compile(f)
    else:
        return f


def wildpath_compile(fstr):
    fstr = string.replace(fstr, '.', '\.')
    fstr = string.replace(fstr, '?', '[^\.]')
    fstr = string.replace(fstr, '*', '[^\.]*')
    fstr = '^' + fstr + '$'
    return re.compile(fstr)


def wildpath_filter(path_string, f):
    if isinstance(f, str):
        f = wildpath_compile(f)
    return f.match(path_string) is not None

BEAUTIFY_CHOICES = [
    'none',
    'array',
    'dict',
]

FILTER_MODES = {
    "exact": lambda p, f: (p == f),
    "icase": lambda p, f: (p.lower() == f.lower()),
    "regexp": lambda p, f: (_fix_regexp(f).match(p) is not None),
    "wildpath": lambda p, f: wildpath_filter(p, f),
}

OPERATORS = {
    # Longer operator strings must come before short ones
    "~=": lambda a, b: (a.lower() == b.lower()),
    "==": lambda a, b: (a == b),
    "!=": lambda a, b: (a != b),
    ">=": lambda a, b: (a >= b),
    "<=": lambda a, b: (a <= b),
    ">": lambda a, b: (a > b),
    "<": lambda a, b: (a < b),
    "@@": lambda a, b: (string.find(a, b) != -1),
    "~@": lambda a, b: (string.find(a.lower(), b.lower()) != -1),
    ":": lambda a, b: (True),
}

COMMANDS = [
    ('kecho', 'key_echo', 1),
    ('ke', 'key_expand', 1),
    ('kurl', 'key_expand_url', 1),
    ('kunq', 'key_unquote', 1),
#       'line_keep',
    ('ls', 'line_strip', 1),
#       'key_keep',
    ('ks', 'key_strip', 1),
    ('asort', 'array_sort', 1),
]


def eval_operator(val, operand, operator_string):
    if operator_string is None:
        return True
    return OPERATORS[operator_string](val, operand)


def split_key_value_operator(selector_expr):
    k = None
    v = None
    oper = None
    for o in OPERATORS.keys():
        if string.rfind(selector_expr, o) != -1:
            arglist = string.split(selector_expr, o, 1)
            oper = o
            k = arglist[0]
            v = arglist[1]
            break
    if oper is None:
        k = selector_expr
    return (k, v, oper)


def jtree_path_select_one(path, path_selector, filter_mode='wildpath'):
    return FILTER_MODES[filter_mode](path, path_selector)


def jtree_path_select(paths, path_selector, filter_mode='wildpath'):
    if path_selector is None:
        return paths
    return [p for p in paths if jtree_path_select_one(p, path_selector, filter_mode)]


def jtree_child_items(j, path=None):
    if path is not None:
        j = jtree_get(j, path)
    if isinstance(j, dict):
        return j.items()
    elif isinstance(j, list):
        return [(str(idx), v) for (idx, v) in enumerate(j)]
    else:
        return []


def jtree_all_paths(j):
    paths = []
    children = jtree_child_items(j)
    if children is not None:
        for (k, v) in children:
            paths.append(k)
            sub = jtree_all_paths(v)
            for subk in sub:
                paths.append(k + '.' + subk)
    return paths


def jtree_select(j, selector_expr=None):
    all_paths = jtree_all_paths(j)
    if selector_expr is not None:
        (path_selector, val_expr, oper) = split_key_value_operator(selector_expr)
        paths = jtree_path_select(all_paths, path_selector)
        if oper is not None:
            out = []
            for p in paths:
                if jtree_has_path(j, p):
                    if eval_operator(jtree_get(j, p), val_expr, oper):
                        out.append(p)
            paths = out
    return paths


def _jtree_get_list(json_line, keys_list):
    path = keys_list
    t = json_line
    for k in path:
        if not isinstance(t, dict):
            return None
        if not k in t:
            return None
        t = t[k]
    return t


def jtree_get(j, paths):
    if isinstance(paths, list):
        return [jtree_get(j, p) for p in paths]
    else:
        full_path = paths
        if not full_path:
            return j
        path_list = string.split(full_path, '.')
        return _jtree_get_list(j, path_list)


def jtree_get_dict(j, paths):
    return [(p, jtree_get(j, p)) for p in paths]


def _jtree_set_list(json_line, keys_list, val):
    path = keys_list
    if len(path) == 0:
        return val
    else:
        k = path[0]
        if not isinstance(json_line, dict):
            json_line = dict()
        if not k in json_line:
            json_line[k] = dict()
        json_line[k] = _jtree_set_list(json_line[k], path[1:], val)
        return json_line


def jtree_set(j, full_key_name, val):
    if not full_key_name:
        return j
    path = string.split(full_key_name, '.')
    return _jtree_set_list(j, path, val)


def _jtree_del_list(json_line, keys_list):
    path = keys_list
    if len(path) == 0:
        return None

    k = path[0]
    if not json_line:
        return json_line
    if isinstance(json_line, dict):
        if not k in json_line:
            return json_line
    elif isinstance(json_line, list):
        k = int(k)

    if len(path) == 1:
        del json_line[k]
        return json_line
    else:
        json_line[k] = _jtree_del_list(json_line[k], path[1:])
        return json_line


def jtree_del(j, full_key_name):
    if not full_key_name:
        return j
    path = string.split(full_key_name, '.')
    return _jtree_del_list(j, path)


def _jtree_has_path_list(json_line, keys_list):
    path = keys_list
    if len(path) == 0:
        return False

    if not json_line:
        return False
    if not isinstance(json_line, dict):
        return False
    k = path[0]

    if len(path) == 1:
        return k in json_line
    else:
        if not k in json_line:
            return False
        else:
            return _jtree_has_path_list(json_line[k], path[1:])


def jtree_has_path(j, full_key_name):
    if not full_key_name:
        return False
    path = string.split(full_key_name, '.')
    return _jtree_has_path_list(j, path)


def jtree_is_array(j, path):
    val = jtree_get(j, path)
    return isinstance(val, list)


def jtree_is_leaf(j, path):
    val = jtree_get(j, path)
    return not (isinstance(val, list) or isinstance(val, dict))


def jtree_path_father(path):
    paths = string.split(path, '.')
    if len(paths) <= 1:
        return None
    else:
        return '.'.join(paths)


def output_line(json_line, args):
    if args.beautify != 'none':
        return json.dumps(json_line, indent=4, sort_keys=True)
    else:
        return json.dumps(json_line)


def trace_msg(msg):
    global in_lines
    global args
    global in_file_name
    in_line_no = in_lines
    if (args.trace):
        print('%s[%03d]\t%s' % (in_file_name, in_line_no, msg))


def process_path_command(json_line, path, command):
    if not json_line:
        return None
    c = command

    if c == 'key_expand':
        v = jtree_get(json_line, path)
        internal_json = json.loads(v)
        jtree_set(json_line, path, internal_json)
    elif c == 'key_expand_url':
        v = jtree_get(json_line, path)
        us = urlparse.urlsplit(v)
        jl = jtree_del(json_line, path)
        jl = jtree_set(jl, path + ".scheme", us.scheme)
        jl = jtree_set(jl, path + ".netloc", us.netloc)
        jl = jtree_set(jl, path + ".path", us.path)
        jl = jtree_set(jl, path + ".fragment", us.fragment)
        queries = us.query.split('&')
        for q in queries:
            kvp = q.split('=')
            k = kvp[0]
            v = kvp[1]
            jl = jtree_set(jl, path + ".query." + k, v)
        json_line = jl
    elif c == 'key_unquote':
        v = jtree_get(json_line, path)
        unquoted = urllib.unquote(v)
        jtree_set(json_line, path, unquoted)
    elif c == 'line_keep':
        pass
    elif c == 'line_strip':
        json_line = None
    elif c == 'key_keep':
        pass
    elif c == 'key_strip':
        json_line = jtree_del(json_line, path)
    elif c == 'key_echo':
        v = jtree_get(json_line, path)
        print(path + '=' + str(v))
    return json_line


def process_line_command(json_line, command, selector_expr):
    if not json_line:
        return None
    if command == 'array_sort':
        (path_selector, sort_key, oper) = split_key_value_operator(selector_expr)
        array_paths = jtree_select(json_line, path_selector)
        for p in reversed(array_paths):
            status = 'OK'
            try:
                arr = jtree_get(json_line, p)
                if not isinstance(arr, list):
                    status = 'Error: path is not array'
                else:
                    if oper == ':' and sort_key:
                        sort_func = lambda x: x[sort_key]
                    else:
                        sort_func = lambda x: x
                    arr = sorted(arr, key=sort_func)
                    json_line = jtree_set(json_line, p, arr)
            except BaseException as e:
                status = 'Error: %s' % (str(e))
            trace_msg('\tMatch: %s (%s)' % (p, status))
    else:
        paths = jtree_select(json_line, selector_expr)
        for p in reversed(paths):
            status = 'OK'
            try:
                json_line = process_path_command(json_line, p, command)
            except BaseException as e:
                status = 'Error: %s' % (str(e))
            trace_msg('\tMatch: %s (%s)' % (p, status))
    return json_line


def build_commands_list(args):
    cmds = []

    # For ordered commands from script
    for cmd_file_path in args.cmdfiles:
        args_left = 0
        params = []
        for line in open(cmd_file_path, 'r'):
            line = line.strip()
            if (line[0] == '-'):
                cmd = {}
                cl = cs = ''
                if (line[1] == '--'):       # Long
                    cl = string.replace(line, '--', '', 1)
                else:                       # Short
                    cs = string.replace(line, '-', '', 1)
                fnames = [(l, onum) for (s, l, onum) in COMMANDS if ((s == cs) or (l == cl))]
                if len(fnames) == 1:
                    cmd['command'] = fnames[0][0]
                    args_left = fnames[0][1]
                    params = []
            elif args_left > 0:
                params.append(line)
                args_left = args_left - 1
                if (args_left == 0):
                    cmd['selector'] = params[0]
                    cmds.append(cmd)

    # For command line arguments
    for (short, command, onum) in COMMANDS:
        if getattr(args, command):
            for selector_expr in getattr(args, command):
                cmds.append({'command' : command, 'selector' : selector_expr})
    return cmds


def process_line(json_line, cmds):
    for (cmd_num, cmd) in enumerate(cmds):
        command = cmd['command']
        selector_expr = cmd['selector']
        trace_msg('(%02d) %s(%s)' % (cmd_num, command, selector_expr))
        json_line = process_line_command(json_line, command, selector_expr)
    return json_line


def to_json_line(line, args):
    return json.loads(line)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description='Filter a JSON logfile',
        fromfile_prefix_chars='@')
    '''
    parser.add_argument('-kk', '--key_keep',
        metavar='KEY', type=str, action='append', dest='key_keep',
        help='keeps only the specified key in all log lines',)
    parser.add_argument('-lk', '--line_keep',
        metavar='KEY', type=str, action='append', dest='line_keep',
        help='keeps only log lines that contain the specified key',)
    parser.add_argument('-m',
        dest='merge', metavar='KEYS', type=str, nargs=1,
        help='NOT IMPLEMENTED: merges all given (sorted) JSON files into a single log sorted according to KEY',)
    parser.add_argument('-s',
        dest='sort', metavar='KEYS', type=str, nargs=1,
        help='NOT IMPLEMENTED: sorts output file according to KEY',)
    '''
    parser.add_argument('-ks', '--key_strip',
        metavar='KEY', type=str, action='append', dest='key_strip',
        help='strips specified key from all log lines',)
    parser.add_argument('-ke', '--key_expand',
        metavar='KEY', type=str, action='append', dest='key_expand',
        help='expands an embedded JSON string key into its contents (recursively)',)
    parser.add_argument('-kurl', '--key_expand_url',
        metavar='KEY', type=str, action='append', dest='key_expand_url',
        help='expands a url string key into its components',)
    parser.add_argument('-kunq', '--key_unquote',
        metavar='KEY', type=str, action='append', dest='key_unquote',
        help='unquotes a string from percent chars.',)
    parser.add_argument('-kecho', '--key_echo',
        metavar='KEY', type=str, action='append', dest='key_echo',
        help='echoes the key value',)
    parser.add_argument('-ls', '--line_strip',
        metavar='KEY', type=str, action='append', dest='line_strip',
        help='strips log lines that contain the specified key',)
    parser.add_argument('-asort', '--array_sort',
        metavar='KEY', type=str, action='append', dest='array_sort',
        help='sorts the array containing the key under the specified path',)

    parser.add_argument('-v',
        action='count', dest='verbose',
        help='verbose output',)
    parser.add_argument('-t',
        action='count', dest='trace',
        help='trace progress',)
    parser.add_argument('-c', '--cmd', dest='cmdfiles',
        type=str, metavar='CMD', action='append',
        help='loads commands from specified file by order (before all argument commands)',)
    parser.add_argument('infiles',
        nargs='*', metavar='IN',
        help='input files',)
    parser.add_argument('-o', dest='outfiles',
        nargs='*', metavar='OUT',
        help='output file',)
    parser.add_argument('-os', dest='outsuffix',
        default='.x.json', type=str, metavar='SUFFIX',
        help='suffix to be appended to input file name(s)',)
    parser.add_argument('-b',
        dest='beautify', default='array', choices=BEAUTIFY_CHOICES,
        help='beautify JSON output lines',)

    args = parser.parse_args()

    args.cmdfiles = expand_file_paths(args.cmdfiles)
    args.infiles = expand_file_paths(args.infiles)

    if len(args.infiles) == 0:
        raise SyntaxError('error: supply at least one input file')

    args.outfiles = expand_file_paths(args.outfiles)

    if len(args.outfiles) == 0:
        for inpath in args.infiles:
            outpath = inpath + args.outsuffix
            args.outfiles.append(outpath)

    '''
    if args.merge:
        args.merge = string.split(args.merge[0], ',')
    if args.sort:
        args.sort = string.split(args.sort[0], ',')
    if (args.merge):
        if len(args.outfiles) != 1:
            raise SyntaxError('error: merge operation requires only one output file (%d given)' % (len(args.outfiles)))
        if len(args.infiles) < 2:
            raise SyntaxError('error: merge operation requires at least two input files (%d given)' % (len(args.infiles)))
    '''
    if len(args.infiles) != len(args.outfiles):
        raise SyntaxError('error: must supply equal amounts of input files and output files (given %d input, %d output' % (len(args.infiles), len(args.outfiles)))

    if (args.verbose >= 2):
        print('Running with arguments: ' + str(args))
        for f in args.cmdfiles:
            print('Command File: ' + str(f))
        for f in args.infiles:
            print('Input File: ' + str(f))
        for f in args.outfiles:
            print('Output File: ' + str(f))

    return args


def process_one_log(inpath, outpath, cmds):
    global in_lines
    global out_lines
    global in_file_name
    global out_file_name
    global args

    in_file_name = os.path.split(inpath)[1]
    out_file_name = os.path.split(outpath)[1]
    infile = open(inpath, 'r')
    outfile = open(outpath, 'w')

    in_lines = 0
    out_lines = 0
    if args.beautify == 'array':
        outfile.write('[\n')
    elif args.beautify == 'dict':
        outfile.write('{\n')
    for l in infile:
        json_line = to_json_line(l, args)
        json_line = process_line(json_line, cmds)
        if json_line:
            if out_lines > 0:
                if args.beautify != 'none':
                    outfile.write(',')
                outfile.write('\n')
            oline = output_line(json_line, args)
            out_lines = out_lines + 1
            if args.beautify == 'dict':
                outfile.write('"%d": ' % (in_lines))
            outfile.write(oline)
        in_lines = in_lines + 1
    if args.beautify == 'array':
        outfile.write('\n}')
    elif args.beautify == 'dict':
        outfile.write('\n]')
    return (in_lines, out_lines)

def process_merge(infiles, outfile, args):
    pass
#   in_lines = 0
#   out_lines = 0
#   if (args.verbose > 0):
#       print('Processing %s --> %s' % (str(infiles), str(outfile)))    
#   filesnum = len(infiles)
#   # First lines
#   lines = []
#   for f in infiles:
#       l = f.readline()


def main(argv): 
    global args
    args = parse_args(argv)

    if (args.verbose >= 2):
        print argv

    cmds = build_commands_list(args)
    if (args.verbose >= 1):
        print('Commands by order')
        for (idx, cmd) in enumerate(cmds):
            print('(%02d) %s(%s)' % (idx, cmd['command'], cmd['selector']))         

    if (False):     # args.merge
        process_merge(args.infiles, args.outfiles[0], args)
    else:
        for (idx, inf) in enumerate(args.infiles):
            infile = args.infiles[idx]
            outfile = args.outfiles[idx]
            if (args.verbose > 0):
                print('Processing "%s" --> "%s"' % (str(infile), str(outfile)))         
            (in_lines, out_lines) = process_one_log(infile, outfile, cmds)
            if (args.verbose > 0):
                print('Input %d lines --> Output %d lines' % (in_lines, out_lines))

if __name__ == "__main__":
    main(sys.argv)
