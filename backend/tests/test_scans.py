PHONE = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"}
MAPS = "https://www.google.com/maps/search/?api=1&query=Salute%2C%20Hartford"


def _link(admin, **extra):
    body = {"label": "Salute", "target_url": MAPS, **extra}
    r = admin.post("/api/admin/qr-links", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_admin_only(client):
    assert client.get("/api/admin/qr-links").status_code == 401
    assert client.post("/api/admin/qr-links", json={"label": "x", "target_url": MAPS}).status_code == 401


def test_scan_redirects_and_counts(admin, client):
    link = _link(admin)
    assert link["short_url"].endswith("/s/" + link["code"])
    assert len(link["code"]) == 6 and link["scans_total"] == 0

    r = client.get(f"/s/{link['code']}", headers=PHONE, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == MAPS
    client.get(f"/s/{link['code']}", headers=PHONE, follow_redirects=False)
    client.get(f"/s/{link['code']}", headers={"User-Agent": "Android Chrome"}, follow_redirects=False)

    [row] = admin.get("/api/admin/qr-links").json()
    assert row["scans_total"] == 3 and row["scans_7d"] == 3 and row["scans_30d"] == 3
    assert row["unique_30d"] == 2  # same phone twice counts once
    assert row["last_scan_at"]

    days = admin.get(f"/api/admin/qr-links/{link['id']}/daily?days=7").json()
    assert len(days) == 7 and days[-1]["scans"] == 3 and days[-1]["unique"] == 2


def test_bots_and_inactive_links_redirect_without_counting(admin, client):
    link = _link(admin)
    r = client.get(f"/s/{link['code']}", headers={"User-Agent": "facebookexternalhit/1.1"}, follow_redirects=False)
    assert r.status_code == 302
    admin.patch(f"/api/admin/qr-links/{link['id']}", json={"active": False})
    client.get(f"/s/{link['code']}", headers=PHONE, follow_redirects=False)
    [row] = admin.get("/api/admin/qr-links").json()
    assert row["scans_total"] == 0 and row["active"] is False


def test_unknown_code_is_404(client):
    assert client.get("/s/nope42", follow_redirects=False).status_code == 404


def test_custom_code_and_update(admin):
    link = _link(admin, code="salute-hfd")
    assert link["code"] == "salute-hfd"
    assert admin.post("/api/admin/qr-links", json={"label": "B", "target_url": MAPS, "code": "salute-hfd"}).status_code == 409
    assert admin.post("/api/admin/qr-links", json={"label": "B", "target_url": "javascript:alert(1)"}).status_code == 422
    r = admin.patch(f"/api/admin/qr-links/{link['id']}", json={"label": "Salute Hartford"})
    assert r.json()["label"] == "Salute Hartford"
    assert admin.delete(f"/api/admin/qr-links/{link['id']}").status_code == 204
    assert admin.get("/api/admin/qr-links").json() == []


def test_links_to_media_title(admin):
    media = admin.post(
        "/api/admin/text-slides",
        json={"title": "ct100-hartford-01-salute", "text": "Salute", "font_size": 80, "text_color": "#FFFFFF", "background_color": "#000000"},
    ).json()
    link = _link(admin, media_id=media["id"])
    assert link["media_title"] == "ct100-hartford-01-salute"
