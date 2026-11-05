"""Windows Job Object containment. Unsupported platforms fail closed."""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import signal
import time


class TreeError(OSError):
    pass


class BasicLimits(c.Structure):
    _fields_ = [("process_time", c.c_longlong), ("job_time", c.c_longlong), ("flags", w.DWORD),
                ("min_working", c.c_size_t), ("max_working", c.c_size_t), ("processes", w.DWORD),
                ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]


class IO(c.Structure):
    _fields_ = [(name, c.c_ulonglong) for name in ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")]


class Extended(c.Structure):
    _fields_ = [("basic", BasicLimits), ("io", IO), ("process_memory", c.c_size_t), ("job_memory", c.c_size_t),
                ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]


class Accounting(c.Structure):
    _fields_ = [(name, c.c_longlong) for name in ("user", "kernel", "period_user", "period_kernel")] + [
        (name, w.DWORD) for name in ("faults", "total_processes", "active", "terminated")]


class Cpu(c.Structure):
    _fields_ = [("flags", w.DWORD), ("rate", w.DWORD)]


class ThreadEntry(c.Structure):
    _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("thread_id", w.DWORD), ("owner_pid", w.DWORD),
                ("base_priority", w.LONG), ("delta_priority", w.LONG), ("flags", w.DWORD)]


class WindowsTree:
    kind = "WINDOWS_JOB_OBJECT"

    def spawn_options(self):
        import subprocess
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | 0x4}

    def __init__(self, limits):
        if os.name != "nt":
            raise TreeError("This runner requires verified Windows Job Object containment; other platforms are unavailable.")
        self.api = c.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.api.QueryInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p]
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise TreeError("Cannot create runner process containment.")
        try:
            info = Extended()
            # Kill-on-close, job-wide committed memory, aggregate user CPU time,
            # active-process count. No breakaway flag is granted.
            info.basic.flags = 0x2000 | 0x200 | 0x4 | 0x8
            info.basic.job_time = int(limits.cpu_seconds * 10_000_000)
            info.basic.processes = limits.processes
            info.job_memory = limits.memory_mb * 1024 * 1024
            if not self.api.SetInformationJobObject(self.handle, 9, c.byref(info), c.sizeof(info)):
                raise TreeError("Cannot apply runner memory/process/CPU-time limits.")
            cpu = Cpu(0x1 | 0x4, limits.cpu_percent * 100)
            if not self.api.SetInformationJobObject(self.handle, 15, c.byref(cpu), c.sizeof(cpu)):
                raise TreeError("Cannot apply runner CPU-rate limit.")
        except BaseException:
            self.close()
            raise

    def attach(self, process):
        # CPython's Windows Popen retains the exact process HANDLE. Using that
        # handle avoids a PID-reuse race; absence of it is a setup error.
        handle = getattr(process, "_handle", None)
        if handle is None or not self.api.AssignProcessToJobObject(self.handle, int(handle)):
            raise TreeError("Cannot contain worker; launch gate remains closed.")

    def accounting(self):
        info = Accounting()
        if not self.api.QueryInformationJobObject(self.handle, 1, c.byref(info), c.sizeof(info), None):
            raise TreeError("Cannot confirm runner process-tree state.")
        return {"active_processes": info.active, "total_processes": info.total_processes,
                "user_cpu_seconds": info.user / 10_000_000, "kernel_cpu_seconds": info.kernel / 10_000_000}

    def resume(self, process):
        # Popen closes the primary thread handle. Enumerate only this still-
        # suspended process's threads using documented Toolhelp/OpenThread APIs.
        self.api.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        self.api.CreateToolhelp32Snapshot.restype = w.HANDLE
        self.api.Thread32First.argtypes = [w.HANDLE, c.POINTER(ThreadEntry)]
        self.api.Thread32Next.argtypes = [w.HANDLE, c.POINTER(ThreadEntry)]
        self.api.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.api.OpenThread.restype = w.HANDLE
        self.api.ResumeThread.argtypes = [w.HANDLE]
        self.api.ResumeThread.restype = w.DWORD
        snapshot = self.api.CreateToolhelp32Snapshot(0x4, 0)
        if snapshot == c.c_void_p(-1).value:
            raise TreeError("Cannot inspect suspended worker threads.")
        resumed = False
        try:
            entry = ThreadEntry()
            entry.size = c.sizeof(entry)
            available = self.api.Thread32First(snapshot, c.byref(entry))
            while available:
                if entry.owner_pid == process.pid:
                    handle = self.api.OpenThread(0x2, False, entry.thread_id)
                    if not handle:
                        raise TreeError("Cannot resume contained worker.")
                    try:
                        previous = self.api.ResumeThread(handle)
                        if previous == 0xFFFFFFFF:
                            raise TreeError("Cannot resume contained worker.")
                        resumed |= previous == 1
                    finally:
                        self.api.CloseHandle(handle)
                available = self.api.Thread32Next(snapshot, c.byref(entry))
        finally:
            self.api.CloseHandle(snapshot)
        if not resumed:
            raise TreeError("Contained worker did not resume.")

    def stop(self):
        if not self.api.TerminateJobObject(self.handle, 2):
            raise TreeError("Cannot terminate runner process tree.")

    def wait_empty(self, seconds=3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.accounting()["active_processes"] == 0:
                return True
            time.sleep(.02)
        return self.accounting()["active_processes"] == 0

    def close(self):
        if getattr(self, "handle", None):
            self.api.CloseHandle(self.handle)
            self.handle = None


class LinuxTree:
    """Trusted-plugin group supervision, not a hostile-code/cgroup sandbox."""
    kind = "LINUX_PROCESS_GROUP"

    def __init__(self, limits):
        if not sys_platform_linux() or not Path('/proc').is_dir() or limits.cpu_percent != 100:
            raise TreeError("Linux requires /proc and cpu_percent=100; CPU-rate throttling is unsupported.")
        self.pid = None
        self.observed = {}
        self.confirmed_empty = False

    def spawn_options(self):
        return {"start_new_session": True}

    def attach(self, process):
        if os.getpgid(process.pid) != process.pid:
            raise TreeError("Worker process group was not isolated.")
        self.pid = process.pid

    def resume(self, process):
        pass  # Bootstrap already waits for GO; no plugin was imported.

    def accounting(self):
        active = 0
        ticks = os.sysconf('SC_CLK_TCK')
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
                if int(fields[2]) == self.pid:
                    self.observed[int(entry.name)] = (int(fields[11]) / ticks, int(fields[12]) / ticks)
                    active += fields[0] not in {'Z', 'X'}
            except (OSError, ValueError, IndexError):
                if int(entry.name) == self.pid or int(entry.name) in self.observed:
                    try:
                        os.kill(int(entry.name), 0)
                    except ProcessLookupError:
                        continue
                    raise TreeError("Cannot inspect a known runner process.")
                continue  # Unrelated/short-lived process disappeared.
        return {"active_processes": active, "total_processes": len(self.observed),
                "user_cpu_seconds": sum(v[0] for v in self.observed.values()),
                "kernel_cpu_seconds": sum(v[1] for v in self.observed.values()),
                "accounting_scope": "OBSERVED_PROC_GROUP"}

    def stop(self):
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def wait_empty(self, seconds=3):
        deadline = time.monotonic() + seconds
        empty_samples = 0
        while time.monotonic() < deadline:
            empty_samples = empty_samples + 1 if self.accounting()['active_processes'] == 0 else 0
            if empty_samples >= 2:
                self.confirmed_empty = True
                return True
            time.sleep(.02)
        return False

    def close(self):
        if self.pid is not None and not self.confirmed_empty:
            self.stop()


def sys_platform_linux():
    import sys
    return sys.platform.startswith('linux')


def create_tree(limits):
    return WindowsTree(limits) if os.name == 'nt' else LinuxTree(limits)
