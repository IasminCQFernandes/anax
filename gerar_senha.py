"""
Opcional: gera o hash da senha do login, para não deixar a senha em texto nos Secrets.

    python gerar_senha.py

Cole as duas linhas que aparecerem na seção [login] dos Secrets, no lugar de senha = "...".
Só precisa do Python (nenhuma biblioteca extra).
"""
import base64
import getpass
import hashlib
import secrets

if __name__ == "__main__":
    s1 = getpass.getpass("Nova senha (mínimo 10 caracteres): ")
    if len(s1) < 10:
        raise SystemExit("Use pelo menos 10 caracteres.")
    if getpass.getpass("Repita a senha: ") != s1:
        raise SystemExit("As senhas não conferem.")
    sal, it = secrets.token_bytes(16), 600_000
    h = hashlib.pbkdf2_hmac("sha256", s1.encode("utf-8"), sal, it)
    print("\nCole na seção [login] dos Secrets (e apague a linha senha = ...):\n")
    print(f'senha_hash = "pbkdf2_sha256${it}${base64.b64encode(sal).decode()}${base64.b64encode(h).decode()}"')
    print(f'chave_sessao = "{secrets.token_urlsafe(32)}"')
