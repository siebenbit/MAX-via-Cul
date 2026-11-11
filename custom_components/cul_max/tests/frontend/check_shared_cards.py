"""Shared style isolation, versioned imports and legacy card behavior."""
from preview_server import preview_server
from playwright.sync_api import sync_playwright, expect

with preview_server() as origin, sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1100, "height": 1100})
    errors, requests = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: requests.append(r.url))
    page.goto(origin + "/tests/frontend/room-card-harness.html")
    room = page.locator("cul-max-room-config-card")
    expect(room.get_by_role("heading", name="MAX! Raumkonfiguration")).to_be_visible()
    room.get_by_role("button", name="Hilfe zu Komforttemperatur", exact=True).focus()
    page.evaluate("rooms[1].revision.temperature='changed'; pushFixture()")
    expect(room.locator("#help-comfort_temperature")).to_be_visible()
    expect(room.get_by_role("button", name="Hilfe zu Komforttemperatur", exact=True)).to_be_focused()
    page.evaluate("""async () => {
      await import('/frontend/cul-max-week-profile-card.js?v=review1');
      await import('/frontend/cul-max-queue-card.js?v=review1');
      const card = document.createElement('cul-max-week-profile-card');
      document.body.append(card);
      card.setConfig({entity:'climate.demo'});
      card.hass={states:{'climate.demo':{state:'auto',attributes:{address:'123456',pairing_state:'paired',week_profile_monday:'17,06:00,21'}}}};
      window.dialogEvent=null;card.addEventListener('hass-more-info',e=>window.dialogEvent=e.detail);
    }""")
    week = page.locator("cul-max-week-profile-card")
    expect(week.get_by_text("Mo", exact=True)).to_be_visible()
    week.locator("ha-card").click()
    assert page.evaluate("dialogEvent.entityId") == "climate.demo"
    assert any("cul-max-card-styles.js?v=review1" in r for r in requests)
    page.evaluate("import('/frontend/cul-max-week-profile-card.js?v=review2')")
    page.wait_for_function("customElements.get('cul-max-week-profile-card') !== undefined")
    page.screenshot(path="/tmp/cul-max-shared-cards.png", full_page=True)
    assert not errors, errors
    browser.close()
    print("Shared styles, module loading, tooltip preservation and week card checks passed")
