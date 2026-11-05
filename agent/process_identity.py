"""PID plus creation identity. Unknown inspection never proves stopped work."""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import sys


def identity(pid=None):
    pid = os.getpid() if pid is None else pid
    if type(pid) is not int or pid <= 0:
        raise OSError('Invalid process identifier.')
    if os.name == 'nt':
        api = c.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.argtypes = [w.DWORD,w.BOOL,w.DWORD]
        api.OpenProcess.restype = w.HANDLE
        api.GetProcessTimes.argtypes = [w.HANDLE,*([c.POINTER(w.FILETIME)]*4)]
        api.WaitForSingleObject.argtypes = [w.HANDLE,w.DWORD]
        api.CloseHandle.argtypes = [w.HANDLE]
        handle = api.OpenProcess(0x1000 | 0x100000, False, pid)
        if not handle:
            if c.get_last_error() == 87:
                raise ProcessLookupError
            raise PermissionError('Cannot inspect process identity.')
        try:
            created, exited, kernel, user = (w.FILETIME() for _ in range(4))
            if not api.GetProcessTimes(handle, c.byref(created), c.byref(exited), c.byref(kernel), c.byref(user)):
                raise OSError('Cannot read process identity.')
            if api.WaitForSingleObject(handle,0) == 0:
                raise ProcessLookupError
            birth = str((created.dwHighDateTime << 32) | created.dwLowDateTime)
        finally:
            api.CloseHandle(handle)
    elif sys.platform.startswith('linux'):
        try:
            fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
            if fields[0] in {'Z','X'}:
                raise ProcessLookupError
            birth = Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' + fields[19]
        except FileNotFoundError as exc:
            raise ProcessLookupError from exc
    else:
        raise OSError('Process identity is unavailable on this platform.')
    return {'pid':pid, 'platform':sys.platform, 'birth':birth}


def inspect(record):
    try:
        return 'ALIVE' if identity(record['pid']) == record else 'DIFFERENT'
    except ProcessLookupError:
        return 'GONE'
    except (OSError,KeyError,TypeError,ValueError):
        return 'UNKNOWN'
