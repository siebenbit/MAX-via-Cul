"""Optional browser checks using Playwright against a local simulated HA page.

Run manually: python3 custom_components/cul_max/tests/frontend/check_queue_card.py
Playwright is a development tool only, not an integration requirement.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

fixture = Path(__file__).with_name("queue-card-harness.html").resolve().as_uri()
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1000, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(fixture)
    card = page.locator("cul-max-queue-card")
    expect(card.get_by_text("Solltemperatur → 23 °C", exact=True)).to_be_visible()
    expect(card.get_by_role("button", name="Nicht löschbar")).to_be_disabled()
    page.evaluate("controller.entries[0].status='debouncing'; controller.entries[0].debounce_until=new Date(Date.now()+2000).toISOString(); card._refresh()")
    expect(card.get_by_text("Wird gesammelt", exact=False)).to_be_visible()
    countdown = card.locator("[data-debounce-until]")
    before = float(countdown.inner_text().split()[0])
    calls_before = page.evaluate("calls.length")
    page.wait_for_timeout(250)
    after = float(countdown.inner_text().split()[0])
    assert after < before
    assert page.evaluate("calls.length") == calls_before
    card.get_by_role("button", name="Löschen", exact=True).click()
    expect(countdown).to_have_count(0)
    page.evaluate("resetFixture()")
    page.screenshot(path="/tmp/cul-max-queue-light.png", full_page=True)
    card.get_by_role("button", name="Löschen", exact=True).click()
    expect(card.get_by_text("Befehl gelöscht.", exact=True)).to_be_visible()
    expect(card.get_by_text("Solltemperatur → 23 °C", exact=True)).to_have_count(0)
    page.evaluate("resetFixture()")
    page.evaluate("failNext=true")
    card.get_by_role("button", name="Löschen", exact=True).click()
    expect(card.get_by_text("Nicht ausgeführt: Status inzwischen geändert", exact=True)).to_be_visible()
    page.evaluate("resetFixture()")
    page.once("dialog", lambda dialog: dialog.dismiss())
    card.get_by_role("button", name="Wartende Befehle leeren").click()
    expect(card.get_by_text("Solltemperatur → 23 °C", exact=True)).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    card.get_by_role("button", name="Wartende Befehle leeren").click()
    expect(card.get_by_text("Solltemperatur → 23 °C", exact=True)).to_have_count(0)
    expect(card.get_by_text("Wochenprofil Montag", exact=True)).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    card.get_by_role("button", name="Auftrag abbrechen").click()
    expect(card.get_by_text("Wochenprofil Montag", exact=True)).to_have_count(0)
    page.evaluate("emptyFixture()")
    expect(card.get_by_text("Keine wartenden Aufträge", exact=True)).to_be_visible()
    page.evaluate("resetFixture(); document.body.classList.add('dark')")
    page.set_viewport_size({"width": 360, "height": 1000})
    expect(card.get_by_text("Solltemperatur → 23 °C", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path="/tmp/cul-max-queue-dark-mobile.png", full_page=True)
    page.evaluate("controller.entries=[]; controller.jobs=[]; reconnectFixture()")
    expect(card.get_by_text("Keine wartenden Aufträge", exact=True)).to_be_visible()
    assert not errors, errors
    browser.close()
    print("Browser checks passed: rendering, delete, errors, confirmations, protected commands, jobs, empty queue, reconnect, dark/mobile")
