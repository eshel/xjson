import sys
import argparse
import json
import os.path
from xutils import expand_file_paths

DEFAULT_KEY = 'Name'
DEFAULT_DELIM = ','
APPEND_DELIM = ';'
CONFLICT_CHOICES = {
    'keep': lambda old, new: old,
    'override': lambda old, new: new,
    'append': lambda old, new: old + APPEND_DELIM + new,
    'longer': lambda old, new: old if (len(old) > len(new)) else new,
}

DEFAULT_CONFLICT = 'keep'

args = None

def parse_lines(csv_lines, key_column=DEFAULT_KEY, delim=DEFAULT_DELIM):
    columns = csv_lines[0].strip().split(delim)
    dat = [dict(zip(columns, l.strip().split(delim))) for l in csv_lines[1:]]
    rows = {}
    for d in dat:
        rows[d[key_column]] = d
    return (rows, columns)


def parse_file(file_path, key_column=DEFAULT_KEY, delim=DEFAULT_DELIM):
    return parse_lines(open(file_path, 'r').readlines(), key_column, delim)


def parse_files(infiles, key_column=DEFAULT_KEY, delim=DEFAULT_DELIM):
    return [parse_file(inf, key_column, delim) for inf in infiles]


def merge_columns(headers_list):
    all_columns_list = []
    known = set()
    for hdr in headers_list:
        for h in hdr:
            if h not in known:
                known.add(h)
                all_columns_list.append(h)
    return all_columns_list


def merge_row(old, new, columns, on_conflict=DEFAULT_CONFLICT):
    global args
    merged = {}
    mergekey = args.merge[0]

    def valid(dct, key):
        return (key in dct) and (not dct[key] is None) and (len(dct[key]) > 0)

    for c in columns:
        if valid(old, c) and valid(new, c) and old[c] != new[c]:
            conflict_func = CONFLICT_CHOICES[on_conflict]
            val = conflict_func(old[c], new[c])
            if args.verbose and c != mergekey:
                print('[CONFLICT] For %s="%s" in column %s: ["%s","%s"] --> %s' % 
                    (mergekey, old[mergekey], c, old[c], new[c], val))
        elif valid(old, c):
            val = old[c]
        elif valid(new, c):
            val = new[c]
        else:
            val = None
        merged[c] = val
    return merged


def merge_rows_from_tables(all_tables, all_columns, key_column=DEFAULT_KEY, on_conflict=DEFAULT_CONFLICT):
    merged = {}
    for table in all_tables:
        for (k, row) in table.items():
            if not k in merged:
                merged[k] = dict()
            merged[k] = merge_row(merged[k], row, all_columns, on_conflict)
    return merged


def merge_files(file_paths, key_column=DEFAULT_KEY, delim=DEFAULT_DELIM, on_conflict=DEFAULT_CONFLICT):
    parsed = parse_files(file_paths, key_column, delim)
    columns = merge_columns([p[1] for p in parsed])
    rows = merge_rows_from_tables([p[0] for p in parsed], columns, key_column, on_conflict)
    return (rows, columns)


def output_json(rows, columns, beautify=True):
    if beautify:
        return json.dumps(rows, indent=4, sort_keys=True)
    else:
        return json.dumps(rows)


def output_csv(rows, columns, delim=DEFAULT_DELIM, sort=True):
    s = ''
    for c in columns:
        s += c + delim
    s += '\n'
    if sort:
        rowitems = sorted(rows.items())
    else:
        rowitems = rows.items()
    for (key, r) in rowitems:
        for c in columns:
            if r[c] is None:
                val = ''
            else:
                val = str(r[c])
            s += val + delim
        s += '\n'
    return s


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description='Filter CSV file(s)',
        fromfile_prefix_chars='@')

    parser.add_argument('-v', action='count', dest='verbose',
        help='verbose output',)
    parser.add_argument('-t', action='count', dest='trace',
        help='trace progress',)
    parser.add_argument('infiles', nargs='*', metavar='IN',
        help='input files',)
    parser.add_argument('-m', type=str, nargs=1, metavar='COL', dest='merge',
        help='merge files using COL')
    parser.add_argument('-o', dest='outfiles', nargs='*', metavar='OUT',
        help='output file',)
    parser.add_argument('-os', dest='outsuffix',
        default='.x.csv', type=str, metavar='SUFFIX',
        help='suffix to be appended to input file name(s)',)
    parser.add_argument('-d', type=str, default=DEFAULT_DELIM, metavar='DELIM', dest='delim',
        help='set delimiter to DELIM',)
    parser.add_argument('--conflict', type=str, 
        choices=CONFLICT_CHOICES.keys(), default=DEFAULT_CONFLICT, dest='conflict',
        help='set delimiter to DELIM',)

    args = parser.parse_args()

    args.beautify = True
    args.infiles = expand_file_paths(args.infiles)

    if len(args.infiles) == 0:
        raise SyntaxError('error: supply at least one input file')

    if args.outfiles is None:
        args.outfiles = []
    if len(args.outfiles) == 0:
        if args.merge:
            args.outfiles = [args.infiles[0] + args.outsuffix]
        else:
            args.outfiles = [inpath + args.outsuffix for inpath in args.infiles]

    get_ext = lambda p: None if p is None else os.path.splitext(opath)[1].strip('.')
    args.outext = [get_ext(opath) for opath in args.outfiles]

    if args.merge:
        if len(args.outfiles) > 1:
            raise SyntaxError('error: may supply up to 1 output file for merges')

    if (args.verbose >= 2):
        print('Ordered Arguments: ' + str(argv))
        print('Parsed Arguments: ' + str(args))
        for f in args.infiles:
            print('Input File: ' + str(f))
        for f in args.outfiles:
            print('Output File: ' + str(f))
        if args.merge:
            print('Merge Column: ' + args.merge[0])
        print('Using delimiter: %s' % (args.delim))

    return args


def main(argv): 
    global args
    args = parse_args(argv)

    if args.merge:
        (rows, cols) = merge_files(args.infiles, args.merge[0], args.delim, args.conflict)
        with open(args.outfiles[0], 'w') as of:
            ext = args.outext[0]
            if ext == 'txt':
                s = output_csv(rows, cols, '\t', args.beautify)
            elif ext == 'json':
                s = output_json(rows, cols, args.beautify)
            else:
                s = output_csv(rows, cols, args.delim, args.beautify)
            of.write(s)

if __name__ == "__main__":
    main(sys.argv)
