import glob


def remove_duplicates(string_list):
    known = set()
    newlist = []
    for s in string_list:
        if s in known: 
            continue
        newlist.append(s)
        known.add(s)
    return newlist


def expand_file_paths(files):
    if files is None:
        return []
    if not isinstance(files, list):
        files = [files]
    globbed_lists = [glob.glob(fpath) for fpath in files]
    expanded = []
    for g in globbed_lists:
        expanded = expanded + g 
    return remove_duplicates(expanded)
