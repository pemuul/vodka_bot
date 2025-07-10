from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from base64 import urlsafe_b64encode, urlsafe_b64decode
import os


secret_key = 'fsif8sefwf8wvj8sdfj90-0dfdsfsdf'

def derive_key(hash_key: str, salt: bytes) -> bytes:
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    ).derive(hash_key.encode())

def encrypt(text: str, hash_key: str=None) -> str:
    if not hash_key:
        hash_key = secret_key

    salt, iv = os.urandom(16), os.urandom(12)
    key = derive_key(hash_key, salt)
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend()).encryptor()
    ciphertext = cipher.update(text.encode()) + cipher.finalize()
    return urlsafe_b64encode(salt + iv + cipher.tag + ciphertext).decode('utf-8')

def decrypt(encrypted_text: str, hash_key: str=None) -> str:
    if not hash_key:
        hash_key = secret_key

    data = urlsafe_b64decode(encrypted_text)
    salt, iv, tag, ciphertext = data[:16], data[16:28], data[28:44], data[44:]
    key = derive_key(hash_key, salt)
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag), backend=default_backend()).decryptor()
    return (cipher.update(ciphertext) + cipher.finalize()).decode('utf-8')
