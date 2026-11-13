"""Windows shell operations with explicit COM lifetime and native diagnostics."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import threading

from .repository import StudioError


_folder_dialog_lock = threading.Lock()


def choose_project_folder(initial=''):
    if not _folder_dialog_lock.acquire(blocking=False):
        raise StudioError('Окно выбора папки уже открыто. Выберите папку или закройте это окно.',409)
    try:
        # A dedicated thread guarantees STA, independent of the API worker's COM state.
        with ThreadPoolExecutor(max_workers=1,thread_name_prefix='studio-folder-picker') as worker:
            return worker.submit(_choose_project_folder,initial).result()
    finally:
        _folder_dialog_lock.release()


def _choose_project_folder(initial):
    with shell_context('Выбор папки проекта') as (shell,ole):
        user = ctypes.WinDLL('user32',use_last_error=True)
        user.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
        user.SetWindowPos.restype = wintypes.BOOL
        user.SetForegroundWindow.argtypes = [wintypes.HWND]
        user.SetForegroundWindow.restype = wintypes.BOOL
        user.SendMessageW.argtypes = [wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        user.SendMessageW.restype = ctypes.c_ssize_t
        start = Path(initial).expanduser() if initial else Path.home()
        if not start.is_absolute() or not start.is_dir():
            start = Path.home()
        start_buffer = ctypes.create_unicode_buffer(str(start))
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int,wintypes.HWND,wintypes.UINT,wintypes.LPARAM,wintypes.LPARAM)

        @callback_type
        def initialize(hwnd,message,lparam,data):
            if message == 1:  # BFFM_INITIALIZED
                user.SendMessageW(hwnd,0x400+103,1,ctypes.addressof(start_buffer))
                # This dialog was explicitly requested by the user in the browser.
                user.SetWindowPos(hwnd,wintypes.HWND(-1),0,0,0,0,0x1|0x2|0x40)
                user.SetForegroundWindow(hwnd)
            return 0

        class BrowseInfo(ctypes.Structure):
            _fields_ = [('hwndOwner',wintypes.HWND),('pidlRoot',ctypes.c_void_p),
                        ('pszDisplayName',wintypes.LPWSTR),('lpszTitle',wintypes.LPCWSTR),
                        ('ulFlags',wintypes.UINT),('lpfn',callback_type),
                        ('lParam',wintypes.LPARAM),('iImage',ctypes.c_int)]

        display = ctypes.create_unicode_buffer(32768)
        info = BrowseInfo()
        info.pszDisplayName = ctypes.cast(display,wintypes.LPWSTR)
        info.lpszTitle = 'Выберите папку Markdown-проекта с document.yaml'
        info.ulFlags = 0x1|0x10|0x40|0x200  # Filesystem folders, edit box, new UI; no folder creation.
        info.lpfn = initialize
        shell.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BrowseInfo)]
        shell.SHBrowseForFolderW.restype = ctypes.c_void_p
        item = shell.SHBrowseForFolderW(ctypes.byref(info))
        if not item:
            return None  # Cancellation is not an error and must not replace the typed path.
        try:
            selected = ctypes.create_unicode_buffer(32768)
            shell.SHGetPathFromIDListEx.argtypes = [ctypes.c_void_p,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD]
            shell.SHGetPathFromIDListEx.restype = wintypes.BOOL
            if not shell.SHGetPathFromIDListEx(item,selected,len(selected),0):
                raise StudioError('Выберите обычную папку файловой системы.',422)
            return selected.value
        finally:
            ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            ole.CoTaskMemFree.restype = None
            ole.CoTaskMemFree(item)


def failure(action, path, code):
    unsigned = code & 0xffffffff
    detail = ctypes.FormatError(unsigned).strip() if os.name == 'nt' else str(code)
    hint = ' Назначьте приложение по умолчанию для .docx в настройках Windows.' if unsigned in (31, 1155, 0x80070483) else ''
    message = f'Не удалось {action}: {path}. Windows 0x{unsigned:08X}: {detail}.{hint}'
    return StudioError(message, 502, [{'code':'WINDOWS_SHELL','severity':'error','source':str(path),'message':message}])


@contextmanager
def shell_context(path):
    if os.name != 'nt':
        raise StudioError('Открытие через системные приложения доступно на Windows. Используйте скачивание.', 422)
    ole = ctypes.WinDLL('ole32', use_last_error=True)
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    status = ole.CoInitializeEx(None, 0x2 | 0x4)  # STA + disable legacy OLE1 DDE.
    if status < 0 and (status & 0xffffffff) != 0x80010106:  # Existing apartment can be reused.
        raise failure('инициализировать Windows Shell', path, status)
    try:
        yield ctypes.WinDLL('shell32', use_last_error=True), ole
    finally:
        if status >= 0:
            ole.CoUninitialize()


def open_in_default_application(path):
    class ExecuteInfo(ctypes.Structure):
        _fields_ = [('cbSize',wintypes.DWORD),('fMask',wintypes.ULONG),('hwnd',wintypes.HWND),
                    ('lpVerb',wintypes.LPCWSTR),('lpFile',wintypes.LPCWSTR),('lpParameters',wintypes.LPCWSTR),
                    ('lpDirectory',wintypes.LPCWSTR),('nShow',ctypes.c_int),('hInstApp',wintypes.HINSTANCE),
                    ('lpIDList',ctypes.c_void_p),('lpClass',wintypes.LPCWSTR),('hkeyClass',wintypes.HKEY),
                    ('dwHotKey',wintypes.DWORD),('hIcon',wintypes.HANDLE),('hProcess',wintypes.HANDLE)]
    with shell_context(path) as (shell, ole):
        info = ExecuteInfo()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x40 | 0x100 | 0x400  # Process handle, synchronous shell handoff, return errors to Studio.
        info.lpVerb, info.lpFile, info.lpDirectory, info.nShow = 'open', str(path), str(path.parent), 1
        shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ExecuteInfo)]
        shell.ShellExecuteExW.restype = wintypes.BOOL
        if not shell.ShellExecuteExW(ctypes.byref(info)):
            raise failure('открыть DOCX', path, ctypes.get_last_error() or info.hInstApp or 31)
        if info.hProcess:
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(info.hProcess)
    return {'opened':True,'path':str(path),'method':'ShellExecuteExW'}


def reveal_in_explorer(path):
    if os.name != 'nt':
        raise StudioError('Проводник доступен только на Windows.',422)
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetWindowsDirectoryW.argtypes = [wintypes.LPWSTR,wintypes.UINT]
    kernel.GetWindowsDirectoryW.restype = wintypes.UINT
    directory = ctypes.create_unicode_buffer(32768)
    length = kernel.GetWindowsDirectoryW(directory,len(directory))
    if not length or length >= len(directory):
        raise failure('найти Проводник Windows',path,ctypes.get_last_error())
    executable = Path(directory.value)/'explorer.exe'
    # Explicitly launch Explorer instead of reusing an unseen shell window via COM.
    # Windows filenames cannot contain quotes; the existing artifact path is verified by the API.
    command = subprocess.list2cmdline([str(executable)]) + ' /n,/select,"' + str(path) + '"'
    try:
        process = subprocess.Popen(command,executable=str(executable),shell=False,
                                   creationflags=subprocess.CREATE_NO_WINDOW,close_fds=True)
    except OSError as exc:
        raise failure('запустить Проводник',path,exc.winerror or 1) from exc
    return {'launched':True,'path':str(path),'method':'explorer.exe /n,/select','pid':process.pid}
