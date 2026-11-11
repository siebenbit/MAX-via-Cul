"""Visual pairing fixture: shared styles, long names and device navigation."""
from preview_server import preview_server
from playwright.sync_api import sync_playwright, expect

with preview_server() as origin, sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1000, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(origin + "/tests/frontend/pairing-card-harness.html")
    card = page.locator("cul-max-pairing-card")
    expect(card.get_by_role("heading", name="MAX! Geräte anlernen")).to_be_visible()
    expect(card.get_by_text("Noch keinem Raum zugeordnet")).to_be_visible()
    expect(card.get_by_text("Erneut angelernt", exact=True)).to_be_visible()
    expect(card.get_by_role("link", name="Gerät bearbeiten").first).to_have_attribute("href", "/config/devices/device/demo")
    buttons = card.get_by_role("link", name="Gerät bearbeiten")
    widths = [buttons.nth(i).bounding_box()["width"] for i in range(buttons.count())]
    assert max(widths) - min(widths) < 1, widths
    assert buttons.first.bounding_box()["x"] == buttons.nth(1).bounding_box()["x"]
    page.screenshot(path="/tmp/cul-max-pairing-desktop.png", full_page=True)
    page.set_viewport_size({"width": 375, "height": 900})
    page.evaluate("document.body.classList.add('dark')")
    expect(card.get_by_role("link", name="Gerät bearbeiten").first).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    widths = [buttons.nth(i).bounding_box()["width"] for i in range(buttons.count())]
    assert max(widths) - min(widths) < 1, widths
    page.screenshot(path="/tmp/cul-max-pairing-mobile-dark.png", full_page=True)
    page.evaluate("fixture.controllers[0].devices[0].name='Heizung Bad'; fixture.controllers[0].devices[0].area_name='Bad'; pushFixture()")
    expect(card.get_by_text("Heizung Bad", exact=True)).to_be_visible()
    page.evaluate("window.editor=document.createElement('cul-max-pairing-card-editor');document.body.append(editor);editor.setConfig({});editor.hass=card._hass")
    editor = page.locator("cul-max-pairing-card-editor")
    title = editor.locator('input[data-key="title"]')
    title.fill("Mein neuer Titel")
    page.evaluate("pushFixture()")
    expect(title).to_have_value("Mein neuer Titel")
    expect(title).to_be_focused()
    duration = editor.locator('input[data-key="duration"]')
    duration.fill("120")
    page.evaluate("fixture.controllers[0].name='CUL umbenannt';pushFixture()")
    expect(duration).to_have_value("120")
    expect(duration).to_be_focused()
    expect(editor.locator('select[data-key="config_entry_id"] option').nth(1)).to_have_text("CUL umbenannt")
    assert not errors, errors
    browser.close()
    print("Pairing desktop/mobile, dark theme and registry updates passed")
