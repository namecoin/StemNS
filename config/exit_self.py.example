import os


def exit_callback():
    # Can't use sys.exit() here because it's called from a child thread.
    os._exit(0)
