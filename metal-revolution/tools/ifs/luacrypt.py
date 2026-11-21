"""Descifrado de lua/lua.bytes de Metal Revolution (XLUAInspector.Utils.ByteArrayUtil.Decrypt):
AES-256-CBC (AesManaged) con clave e IV de PasswordDeriveBytes(password, salt) en su version de Mono (SHA1, 100 iteraciones)."""
import hashlib
PASSWORD = 'klsdfsafsdf'
SALT = bytes([0x43, 0x87, 0x23, 0x72])

class PasswordDeriveBytesMS:
    """PasswordDeriveBytes de .NET (reference source, la que usa Unity 2018 con IL2CPP), con su error historico:
    en la segunda llamada copia los bytes sobrantes desde la posicion equivocada (ib en vez de _extraCount)."""
    def __init__(self, password, salt, iterations=100):
        b = hashlib.sha1(password.encode('utf-8') + salt).digest()
        for _ in range(1, iterations - 1): b = hashlib.sha1(b).digest()
        self.base = b; self.prefix = 0; self.extra = None; self.extra_count = 0
    def _block(self):
        pre = b'' if self.prefix == 0 else str(self.prefix).encode()
        self.prefix += 1; return hashlib.sha1(pre + self.base).digest()
    def _compute(self, cb):
        out = b''
        while len(out) < cb: out += self._block()
        return out
    def get_bytes(self, cb):
        ib = 0; res = bytearray(cb)
        if self.extra is not None:
            ib = len(self.extra) - self.extra_count
            if ib >= cb:
                res[:] = self.extra[self.extra_count:self.extra_count + cb]
                if ib > cb: self.extra_count += cb
                else: self.extra = None
                return bytes(res)
            res[0:ib] = self.extra[ib:ib + ib]          # el error de .NET: deberia ser extra[extra_count:...]
            self.extra = None
        rgb = self._compute(cb - ib)
        res[ib:cb] = rgb[:cb - ib]
        if len(rgb) + ib > cb: self.extra = rgb; self.extra_count = cb - ib
        return bytes(res)

def keys(password=PASSWORD, salt=SALT):
    p = PasswordDeriveBytesMS(password, salt); return p.get_bytes(32), p.get_bytes(16)

def aes_cbc(data, key, iv, decrypt=True):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    c = Cipher(algorithms.AES(key), modes.CBC(iv))
    if decrypt:
        d = c.decryptor(); raw = d.update(data) + d.finalize()
        u = padding.PKCS7(128).unpadder(); return u.update(raw) + u.finalize()
    pd = padding.PKCS7(128).padder(); data = pd.update(data) + pd.finalize()
    e = c.encryptor(); return e.update(data) + e.finalize()

def descifrar(data): k, iv = keys(); return aes_cbc(data, k, iv, True)
def cifrar(data): k, iv = keys(); return aes_cbc(data, k, iv, False)
