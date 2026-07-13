import { chromium } from 'playwright'

const URL = process.argv[2] || 'https://edwards-delegation-tricks-blogging.trycloudflare.com'
const IMG = process.argv[3] || 'C:/Users/User/Desktop/copycat-watch/experiments/dataset/originals/item000.jpg'
const COLOR_SCHEME = process.argv[4] || 'dark'

const browser = await chromium.launch()
const context = await browser.newContext({ colorScheme: COLOR_SCHEME })
const page = await context.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(String(e)))
page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()) })

await page.goto(URL, { waitUntil: 'networkidle' })
await page.screenshot({ path: `screenshots/01-landing-${COLOR_SCHEME}.png`, fullPage: true })

await page.fill('input[placeholder*="라벤더"]', '테스트 상품')
await page.setInputFiles('input[type="file"]', IMG)
await page.screenshot({ path: `screenshots/02-upload-${COLOR_SCHEME}.png`, fullPage: true })

await page.click('button:has-text("AI로 도용 스캔하기")')
await page.waitForSelector('text=새로 스캔하기', { timeout: 60000 })
await page.screenshot({ path: `screenshots/03-results-${COLOR_SCHEME}.png`, fullPage: true })

console.log('ERRORS:', errors.length ? errors : 'none')
await browser.close()
