"""Persisted JSON flags without treating the string 'false' as true."""
def flag(value, default=False):
    if value is None: return bool(default)
    if isinstance(value, str):
        text=value.strip().casefold()
        if text in {'false','0','off','no',''}: return False
        if text in {'true','1','on','yes'}: return True
        return True  # preserve a nonempty unrecognized lock conservatively
    return bool(value)
