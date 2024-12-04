def _tokenator(xml):
    collected = []
    for ch in xml:
        if ch == '<':
            if collected:
                yield ''.join(collected)
                collected.clear()
        elif ch in {'\r', '\n'}:
            continue
        elif ch == '>':
            collected.append(ch)
            yield ''.join(collected)
            collected.clear()
            continue

        collected.append(ch)


def safe_dict_insert(d, keypath, value):
    cur = d
    end = keypath[-1]
    for i, key in enumerate(keypath):
        if key in cur:
            cur = cur[key]
        else:
            if key == end:
                if key in cur:
                    print('WARN: {keypath} exists')
                cur[key] = value
            else:
                cur[key] = {}
                cur = cur[key]


def deep_key_exists(d, keypath):
    cur = d
    for key in keypath:
        if isinstance(cur, dict) and key not in cur:
            return False
        elif isinstance(cur, list) and len(cur) <= key:
            return False
        cur = cur[key]

    return True


def get_deep_key(d, keypath, default=None):
    cur = d
    for key in keypath:
        if key in cur:
            cur = cur[key]
        else:
            if default is not None:
                return default
            else:
                raise KeyError(keypath)
    return cur


def parse_attrs(attrs_raw):
    attrs = {}
    while attrs_raw:
        name, rest = attrs_raw.split('=', 1)
        qc = rest[0]
        value_end = rest.index(qc, 1)
        value, attrs_raw = rest[1:value_end], rest[value_end + 2:]
        attrs[name] = value
    return attrs


# NOTE: this is working well overall, but there are a few things left to potentially address
# TODO: the way this function currently builds the dict is inefficient
def _nest(tokens):
    doc = {}
    path = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if token.startswith('<?xml'):
            continue
        if token.startswith('<') and not token.startswith('</'):
            tag_body = token[1:-1].split(' ', 1)
            name = tag_body[0]
            idx = sum(1 for k in get_deep_key(doc, path, {}) if k[0] == name)

            if len(tag_body) == 2:
                attrs = parse_attrs(tag_body[1])
                attrs_path = path.copy()
                attrs_path.append((f'{name}_attrs', idx))
                safe_dict_insert(doc, attrs_path, attrs)

            if token.endswith('/>'):
                safe_dict_insert(doc, path + [(name, idx)], {})
            else:
                path.append((name, idx))

        elif token.startswith('</'):
            path.pop()
            if path and isinstance(path[-1], int):
                path.pop()
        else:
            safe_dict_insert(doc, path, token)

    return doc


def xmltodict(xmlraw):
    return _nest(_tokenator(xmlraw))


def dicttoxml(d):
    return ''.join(
        f'<{k}>{dicttoxml(v) if isinstance(v, dict) else v}</{k}>'
        for k, v in d.items()
    )
