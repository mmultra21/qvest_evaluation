"""
Headless UI capture script using Playwright to take a screenshot of the Gradio Student tab.

Requirements:
- playwright (pip install playwright)
- playwright browsers installed (python -m playwright install)

Usage (from repo root):

    PLAYWRIGHT_BROWSERS_PATH=.playwright .venv/bin/python scripts/capture_gradio.py

This script expects the backend and Gradio to be running locally on 127.0.0.1:8000 and 7860.
It will navigate to the Gradio UI and click "Get my Top 5" to surface the error box (assuming the backend is started with the malformed hook enabled).
"""
import asyncio
import os
from playwright.async_api import async_playwright

URL = os.getenv('GRADIO_URL', 'http://127.0.0.1:7860')
OUT = os.getenv('GRADIO_CAPTURE_OUT', 'gradio_capture.png')

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width':1200,'height':900})
        await page.goto(URL, timeout=60000)
        # Wait for the Student Assistant tab content to load
        await page.wait_for_selector('text=Get my Top 5', timeout=15000)
        # Click the button
        await page.click('text=Get my Top 5')
        # Wait a moment for backend roundtrip
        await page.wait_for_timeout(2000)
        # Take screenshot
        await page.screenshot(path=OUT)
        print(f'Screenshot saved to {OUT}')
        await browser.close()

if __name__ == '__main__':
    asyncio.run(run())
