"""
Detect whether the WebView2 Evergreen Runtime is installed.

WebView2 ships with Windows 11 and is present on the vast majority of Windows 10
machines, but a small number of Win10 boxes lack it. The real app will run this
check at startup; if missing, it will point the user to
https://developer.microsoft.com/microsoft-edge/webview2/ (or run the ~2 MB
bootstrapper) instead of failing with a blank window.

Returns the runtime version string, or None if not installed.
"""
import winreg

# Official WebView2 Runtime client GUID (per Microsoft docs).
_CLIENT = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
_LOCATIONS = [
    (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_CLIENT}'),
    (winreg.HKEY_CURRENT_USER,  rf'Software\Microsoft\EdgeUpdate\Clients\{_CLIENT}'),
    (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\Microsoft\EdgeUpdate\Clients\{_CLIENT}'),
]


def webview2_version():
    for hive, path in _LOCATIONS:
        try:
            with winreg.OpenKey(hive, path) as key:
                pv, _ = winreg.QueryValueEx(key, 'pv')
                if pv and pv != '0.0.0.0':
                    return pv
        except OSError:
            continue
    return None


if __name__ == '__main__':
    v = webview2_version()
    print(f'WebView2 Runtime: {v}' if v else 'WebView2 Runtime NOT installed')
