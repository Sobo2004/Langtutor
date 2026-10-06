"""Passwords, login and rate limits."""
import hashlib
import uuid


def test_passwords_are_hashed_with_bcrypt(app_module):
    hashed = app_module.hash_password("secret123")
    assert hashed.startswith("$2")
    assert hashed != app_module.hash_password("secret123")          # salted: same password, different hash
    assert app_module.verify_password("secret123", hashed) == (True, False)
    assert app_module.verify_password("wrong", hashed) == (False, False)


def test_old_sha256_and_plain_text_passwords_still_work_and_need_upgrade(app_module):
    old = hashlib.sha256(b"secret123").hexdigest()
    assert app_module.verify_password("secret123", old) == (True, True)
    assert app_module.verify_password("secret123", "secret123") == (True, True)
    assert app_module.verify_password("nope", old) == (False, False)


def test_signup_and_login(client):
    name = "u_" + uuid.uuid4().hex[:8]
    assert client.post("/auth/signup", json={"username": name, "password": "secret123"}).status_code == 200
    assert client.post("/auth/signup", json={"username": name, "password": "secret123"}).status_code == 400
    assert client.post("/auth/login", json={"username": name, "password": "wrong-pass"}).status_code == 401
    res = client.post("/auth/login", json={"username": name, "password": "secret123"})
    assert res.status_code == 200
    assert "session_id" in res.cookies or "session_id" in client.cookies


def test_signup_rejects_short_and_overlong_passwords(client):
    assert client.post("/auth/signup", json={"username": "short_pw_user", "password": "abc"}).status_code == 400
    assert client.post("/auth/signup", json={"username": "long_pw_user", "password": "x" * 80}).status_code == 400


def test_legacy_account_is_upgraded_to_bcrypt_on_login(client, app_module):
    name = "legacy_" + uuid.uuid4().hex[:8]
    con = app_module.db()
    con.execute("INSERT INTO users(id, username, password, created_at, last_active) VALUES(?,?,?,date('now'),date('now'))",
                (str(uuid.uuid4()), name, hashlib.sha256(b"oldpass1").hexdigest()))
    con.commit()
    con.close()

    assert client.post("/auth/login", json={"username": name, "password": "oldpass1"}).status_code == 200
    con = app_module.db()
    stored = con.execute("SELECT password FROM users WHERE username=?", (name,)).fetchone()["password"]
    con.close()
    assert stored.startswith("$2")


def test_admin_password_comes_from_env_not_a_default(client):
    assert client.post("/admin/login", json={"username": "admin", "password": "admin123"}).status_code == 401
    assert client.post("/admin/login", json={"username": "admin", "password": "test-admin-password"}).status_code == 200


def test_login_attempts_are_rate_limited(client):
    codes = [client.post("/auth/login", json={"username": "nobody", "password": "guess123"}).status_code
             for _ in range(12)]
    assert codes[:10] == [401] * 10
    assert codes[-1] == 429


def test_paid_endpoints_require_login(client):
    assert client.post("/api/tts", json={"text": "hello"}).status_code == 401
    assert client.post("/api/quiz/generate", json={"count": 5}).status_code == 401


def test_voice_endpoint_is_rate_limited_per_user(user, app_module, monkeypatch):
    client, _, _ = user
    monkeypatch.setitem(app_module.RATE_LIMITS, "tts", (3, 60))
    monkeypatch.setattr(app_module, "OPENAI_API_KEY", None)   # stop before any paid call
    codes = [client.post("/api/tts", json={"text": "hi"}).status_code for _ in range(4)]
    assert codes == [503, 503, 503, 429]
