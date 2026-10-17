"""M1 骨架测试：应用能启动、欢迎页能打开、数据库建表、中英文切换、来源校验。"""

import sqlite3


def test_welcome_page_default_chinese(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "欢迎来到 Usland" in html
    assert 'lang="zh-CN"' in html


def test_database_tables_created(app):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"island", "members"} <= names


def test_switch_language_to_english(client):
    resp = client.post("/lang", data={"lang": "en", "next": "/"})
    assert resp.status_code == 302
    assert "lang=en" in resp.headers["Set-Cookie"]

    html = client.get("/").get_data(as_text=True)
    assert "Welcome to Usland" in html


def test_post_without_origin_is_rejected(raw_client):
    resp = raw_client.post("/lang", data={"lang": "en"})
    assert resp.status_code == 403


def test_post_from_other_site_is_rejected(raw_client):
    resp = raw_client.post("/lang", data={"lang": "en"}, headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403


def test_lang_redirect_stays_on_site(client):
    resp = client.post("/lang", data={"lang": "zh", "next": "//evil.example"})
    assert resp.headers["Location"] == "/"


# ---------- 部署在反向代理后面（Zenith） ----------


def test_proxy_headers_ignored_by_default(app):
    """默认不信任 X-Forwarded-Host：本地运行时别人不能伪造来源。"""
    c = app.test_client()
    resp = c.post("/lang", data={"lang": "en", "next": "/"},
                  headers={"Origin": "https://usland.zh.run", "X-Forwarded-Host": "usland.zh.run"})
    assert resp.status_code == 403


def test_proxy_headers_used_when_trusted(tmp_path, monkeypatch):
    """TRUST_PROXY=1（Dockerfile 默认）：代理把公开域名放在 X-Forwarded-Host 里，表单来源校验按公开域名判断。"""
    from app import create_app

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("TRUST_PROXY", "1")
    app = create_app({"TESTING": True})
    c = app.test_client()
    headers = {"Origin": "https://usland.zh.run", "X-Forwarded-Host": "usland.zh.run", "X-Forwarded-Proto": "https"}
    assert c.post("/lang", data={"lang": "en", "next": "/"}, headers=headers).status_code == 302
    # 来源和公开域名不一致仍然拒绝
    bad = {"Origin": "https://evil.example", "X-Forwarded-Host": "usland.zh.run"}
    assert c.post("/lang", data={"lang": "en", "next": "/"}, headers=bad).status_code == 403
