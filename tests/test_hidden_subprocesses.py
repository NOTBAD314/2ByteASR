import os

from twobyteasr.processes import hidden_subprocess_kwargs


def test_hidden_subprocess_options_are_platform_safe():
    options = hidden_subprocess_kwargs()
    if os.name == "nt":
        assert options["creationflags"]
        assert options["startupinfo"].dwFlags
    else:
        assert options == {}
