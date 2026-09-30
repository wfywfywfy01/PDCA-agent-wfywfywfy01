"""Check the browser-memory Practice + Perform walkthrough at npm run demo."""
from __future__ import annotations

import re

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:5183/omega")
        expect(page.get_by_text("交互原型 · 模拟数据")).to_be_visible()
        page.get_by_role("group", name="列表类型").get_by_role("button", name=re.compile("记录")).click()
        page.locator(".omega-side button.omega-link", has_text="已结束").first.click()
        expect(page.get_by_text("示例逐字稿没有书面付款承诺。")).to_be_visible()
        expect(page.get_by_text("推荐练 异议处理；当前 40%，目标 70%。", exact=False)).to_be_visible()
        page.get_by_role("button", name="指派这项练习").click()
        expect(page.get_by_text("练习已指派，销售可在待练列表开始。")).to_be_visible()
        page.get_by_role("group", name="列表类型").get_by_role("button", name=re.compile("指派")).click()
        pending = page.locator(".omega-side button.omega-link", has_text="待练")
        expect(pending).to_have_count(2)
        pending.first.click()
        expect(page.get_by_text("来源报告该项：4/10（40%）")).to_be_visible()
        page.get_by_role("button", name="开始本次练习").click()
        page.get_by_label("文字发言").fill("我理解您担心交付延迟。请确认本周五能否付款？")
        page.get_by_role("button", name="发送", exact=True).click()
        expect(page.get_by_text("我可以在本周五安排首笔付款。", exact=False)).to_be_visible()
        page.get_by_role("button", name="结束并复盘").click()
        expect(page.get_by_text("演示评分：练习回应了付款异议，请由主管复核。", exact=True)).to_be_visible()
        expect(page.get_by_text("异议处理：上次 40% · 本轮 80% · 已达标")).to_be_visible()
        page.get_by_role("button", name="继续练本项").click()
        expect(page.get_by_text("本轮只练：异议处理")).to_be_visible()
        page.get_by_role("group", name="列表类型").get_by_role("button", name=re.compile("指派")).click()
        page.locator(".omega-side button.omega-link", has_text="已达标").first.click()
        expect(page.get_by_text("第 1 次：8/10（80%）", exact=False)).to_be_visible()
        page.get_by_role("button", name="新练习").click()
        page.get_by_role("button", name=re.compile("客户要求降价")).click()
        expect(page.get_by_role("heading", name="练习：客户要求降价")).to_be_visible()
        page.reload()
        page.get_by_role("group", name="列表类型").get_by_role("button", name=re.compile("记录")).click()
        page.locator(".omega-side button.omega-link", has_text="已结束").first.click()
        page.get_by_role("button", name="按这个卡点再练").click()
        expect(page.get_by_text("本轮只练：异议处理")).to_be_visible()
        expect(page.get_by_text("先复述交付顾虑，再确认付款日期。", exact=False)).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "targeted practice overflows mobile width"
        if errors:
            raise AssertionError(errors)
        browser.close()
    print("Omega demo Practice + Perform linked walkthrough PASS")


if __name__ == "__main__":
    main()
