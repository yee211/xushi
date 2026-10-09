import base64
import ctypes
import json
import os
import shutil
import sqlite3
from ctypes import wintypes

from Crypto.Cipher import AES


class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

def dpapi_decrypt(encrypted_bytes):
    blob_in = DATA_BLOB(len(encrypted_bytes), ctypes.create_string_buffer(encrypted_bytes, len(encrypted_bytes)))
    blob_out = DATA_BLOB()
    if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return out
    return None

def get_cookies():
    local_state_path = os.path.expanduser('~') + r'\AppData\Local\Microsoft\Edge\User Data\Local State'
    with open(local_state_path, encoding='utf-8') as f:
        local_state = json.load(f)
    encrypted_key = base64.b64decode(local_state['os_crypt']['encrypted_key'])[5:]
    aes_key = dpapi_decrypt(encrypted_key)

    cookies_path = os.path.expanduser('~') + r'\AppData\Local\Microsoft\Edge\User Data\Default\Network\Cookies'
    temp_cookies = os.path.expanduser('~') + r'\AppData\Local\Temp\Edge_Cookies_Copy.db'
    shutil.copy2(cookies_path, temp_cookies)
    conn = sqlite3.connect(temp_cookies)
    cursor = conn.cursor()
    cursor.execute("SELECT host_key, name, encrypted_value FROM cookies WHERE host_key LIKE '%ccsut.cn%'")
    cookies = {}
    for host, name, enc_val in cursor.fetchall():
        try:
            if enc_val[:3] == b'v10':
                nonce = enc_val[3:15]
                ciphertext = enc_val[15:-16]
                tag = enc_val[-16:]
                cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
                val = cipher.decrypt_and_verify(ciphertext, tag).decode('utf-8', errors='ignore')
                cookies[name] = val
                print(f"[{host}] {name} = {val[:20]}...")
            elif enc_val[:3] == b'v20':
                print(f"[{host}] {name} uses App-Bound encryption (v20)")
        except Exception as e:
            print(f"Decrypt error for {name}: {e}")
    conn.close()
    if os.path.exists(temp_cookies):
        os.remove(temp_cookies)
    return cookies

if __name__ == '__main__':
    res = get_cookies()
    print("Found cookies count:", len(res))
