"""Room association card desktop/mobile behavior and shared styling."""
from preview_server import preview_server
from playwright.sync_api import sync_playwright, expect

with preview_server() as origin, sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1000, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(origin + "/tests/frontend/association-card-harness.html")
    card = page.locator("cul-max-room-association-card")
    card.get_by_label("Raum").select_option("living")
    expect(card.get_by_text("Heizkörperthermostat mit einem langen vollständigen Gerätenamen", exact=True)).to_be_visible()
    expect(card.get_by_text("An anderen CULs", exact=False)).to_be_visible()
    card.get_by_role("button", name="Geräte verknüpfen").click()
    expect(card.get_by_role("status")).to_contain_text("Wartet auf Fensterkontakt")
    expect(card.get_by_role("button")).to_be_disabled()
    assert page.evaluate("lastRequest.config_entry_id") == "demo"
    assert card.get_by_label("Raum").bounding_box()["height"] >= 44
    page.screenshot(path="/tmp/cul-association-desktop.png", full_page=True)
    page.set_viewport_size({"width":375,"height":900})
    page.evaluate("document.body.classList.add('dark')")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    expect(card.get_by_label("Raum")).to_be_enabled()
    button = card.get_by_role("button").bounding_box()
    select = card.get_by_label("Raum").bounding_box()
    assert abs(button["width"] - select["width"]) < 1
    names = card.locator(".device strong")
    assert names.first.bounding_box()["height"] > names.nth(1).bounding_box()["height"]
    page.screenshot(path="/tmp/cul-association-mobile-dark.png", full_page=True)
    page.evaluate("room.status='partial';room.busy=false;room.can_start=true;pushFixture()")
    expect(card.get_by_role("button",name="Erneut versuchen")).to_be_enabled()
    page.evaluate("room.status='complete';room.can_start=false;pushFixture()")
    expect(card.get_by_role("status")).to_contain_text("Geräte sind verknüpft")
    page.evaluate("room.status='partial';room.can_start=true;room.busy=false;window.failStart=true;pushFixture()")
    card.get_by_role("button", name="Erneut versuchen").click()
    expect(card.get_by_role("alert")).to_have_text("Speichern fehlgeschlagen")
    page.evaluate("pushFixture()")
    expect(card.get_by_role("alert")).to_have_text("Speichern fehlgeschlagen")
    card.get_by_label("Raum").select_option("")
    card.get_by_label("Raum").select_option("living")
    expect(card.get_by_role("alert")).to_have_count(0)
    page.evaluate("window.failStart=false")
    card.get_by_role("button", name="Erneut versuchen").click()
    expect(card.get_by_role("status")).to_contain_text("Wartet auf Fensterkontakt")
    assert not errors, errors
    browser.close()
    print("Association desktop/mobile and pending/retry/complete states passed")
