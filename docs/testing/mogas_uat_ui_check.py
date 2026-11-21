"""Browser check on a MOGAS UAT copy: the workflow "Submit" action of a UAE
Sales Invoice opens the UAE E-Invoice Details dialog, saves it, and submits.

Prereqs (UAT copy only): `mogas_uat_check.mk_ui_draft` (test user + draft),
2FA off while testing, the accounting period of today open for Sales
Invoice, `bench --site <uat-site> serve --port 8070`. Run where Playwright
is installed (the dev container):

    python3 mogas_uat_ui_check.py http://localhost:8070 <draft SI name> /tmp/shots
"""
import sys, time, glob
from playwright.sync_api import sync_playwright
BASE, SI, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
exe = (sorted(glob.glob("/home/frappe/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")) or [None])[-1]
def log(*a): print(*a, flush=True)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 1000})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/login")
    pg.fill("#login_email", "uae.uat.tester@example.com"); pg.fill("#login_password", "UatTest#2026")
    pg.click(".btn-login"); pg.wait_for_url("**/app**", timeout=60000)
    pg.goto(f"{BASE}/app/sales-invoice/{SI}"); pg.wait_for_selector(".page-title", timeout=60000); time.sleep(4)
    log("indicator/UAE group present:", pg.locator("button:has-text('UAE E-Invoice')").count() > 0)
    actions = pg.locator("button:has-text('Actions')")
    log("workflow Actions button:", actions.count())
    actions.first.click(); time.sleep(1)
    items = [t.strip() for t in pg.locator(".dropdown-menu.show a, .dropdown-menu.show .dropdown-item").all_inner_texts() if t.strip()]
    log("actions:", items)
    pg.locator(".dropdown-menu.show").get_by_text("Submit", exact=True).first.click()
    try:
        pg.wait_for_selector(".modal.show .modal-title:has-text('UAE E-Invoice Details')", timeout=20000)
        log("UAE dialog shown on workflow Submit: True")
    except Exception:
        log("UAE dialog shown on workflow Submit: False"); pg.screenshot(path=f"{OUT}/wf_nodialog.png"); raise
    frozen = pg.locator(".freeze").count() and pg.locator(".freeze").first.is_visible()
    log("screen frozen behind dialog:", bool(frozen))
    pg.screenshot(path=f"{OUT}/wf_dialog.png")
    dlg = pg.locator(".modal.show")
    # choose Zero rated + Export in the dialog
    sel = dlg.locator("select[data-fieldname='vat_category']")
    if sel.count(): sel.select_option(label="Z - Zero rated")
    sel = dlg.locator("select[data-fieldname='invoice_transaction_type_code']")
    if sel.count(): sel.select_option(label="XXXXXXX1 : Export transaction")
    dlg.locator(".btn-primary.btn-modal-primary, .modal-footer .btn-primary").first.click()
    for _ in range(40):
        time.sleep(1)
        st = pg.evaluate("cur_frm && cur_frm.doc.docstatus")
        if st == 1: break
    log("docstatus after:", pg.evaluate("cur_frm.doc.docstatus"), "workflow_state:", pg.evaluate("cur_frm.doc.workflow_state"))
    time.sleep(3)
    pg.screenshot(path=f"{OUT}/wf_submitted.png")
    log("indicators:", pg.locator(".form-dashboard .indicator-pill, .form-dashboard .indicator").all_inner_texts()[:5])
    log("JS errors:", errors)
    b.close()
