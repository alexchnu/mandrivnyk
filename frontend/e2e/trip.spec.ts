import { type Page, expect, test } from '@playwright/test'

const SHOTS = process.env.PLANNER_SHOTS // when set, screenshots for the documentation are written there

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

async function addPlaces(page: Page, count: number) {
  await expect(page.locator('.card').first()).toBeVisible({ timeout: 60_000 })
  for (let i = 0; i < count; i++) {
    // skip the first card after the first pick so that the trip is spread over the city
    await page.locator('.card .btn--primary').nth(i === 0 ? 0 : 1).click()
    await expect(page.locator('.stop')).toHaveCount(i + 1)
  }
}

test('plan, optimise, save, share and claim a trip', async ({ page, browser }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Пішохідний маршрут')
  await shot(page, '01-home')

  // 1. choose a city and collect places
  await page.getByRole('button', { name: 'Чернівці' }).click()
  await expect(page).toHaveURL(/\/plan$/)
  await addPlaces(page, 5)
  await expect(page.locator('.stop__arrive').first()).toHaveText('09:00')
  await expect(page.locator('.leg').first()).toContainText('пішки')
  await shot(page, '02-planner')

  // suggestions never repeat what is already in the trip, also after asking for more
  const chosen = await page.locator('.stop__name').allTextContents()
  await page.getByRole('button', { name: 'Показати інші місця' }).click()
  await expect(page.locator('.panel__sub').first()).toContainText('поруч з останньою зупинкою')
  await expect(page.locator('.card').first()).toBeVisible()
  const offered = await page.locator('.card__name').allTextContents()
  expect(offered.filter((name) => chosen.includes(name))).toEqual([])

  // 2. optimise: same places, never a longer walk
  const walkBefore = await page.locator('.panel--right .panel__sub').textContent()
  await page.getByRole('button', { name: 'Впорядкувати маршрут' }).click()
  await expect(page.locator('.toast')).toContainText(/Маршрут впорядковано|Порядок уже найкращий/)
  await expect(page.locator('.stop')).toHaveCount(5)
  expect((await page.locator('.stop__name').allTextContents()).sort()).toEqual([...chosen].sort())
  await shot(page, '03-optimised')
  expect(walkBefore).toBeTruthy()

  // 3. two days: stops are split and each day has its own timetable
  await page.getByLabel('Днів').selectOption('2')
  await page.getByRole('button', { name: 'Впорядкувати маршрут' }).click()
  await expect(page.getByRole('tab', { name: /День 2/ })).toBeVisible()
  await page.getByRole('tab', { name: /День 2/ }).click()
  await shot(page, '04-two-days')
  await page.getByLabel('Днів').selectOption('1')

  // 4. save and find it in "My trips"
  await page.getByLabel('Назва маршруту').fill('Тестовий маршрут Чернівцями')
  await page.getByRole('button', { name: 'Зберегти' }).click()
  await expect(page.locator('.toast').last()).toContainText('Маршрут збережено')
  await page.getByRole('link', { name: 'Мої маршрути' }).click()
  await expect(page.getByRole('link', { name: 'Тестовий маршрут Чернівцями' })).toBeVisible()
  await expect(page.locator('.page__note')).toContainText('лише в цьому браузері')
  await shot(page, '05-trips')

  // 5. share: another browser sees it read-only
  await page.getByRole('link', { name: 'Тестовий маршрут Чернівцями' }).click()
  await expect(page.locator('.stop')).toHaveCount(5)
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.getByRole('button', { name: 'Поділитися' }).click()
  await expect(page.locator('.toast').last()).toContainText('Посилання скопійовано')
  const link = await page.evaluate(() => navigator.clipboard.readText())
  expect(link).toMatch(/\/shared\/[\w-]+$/)

  const guestContext = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'uk-UA' })
  const guest = await guestContext.newPage()
  await guest.goto(link)
  await expect(guest.getByRole('heading', { name: 'Тестовий маршрут Чернівцями' })).toBeVisible()
  await expect(guest.locator('.stop')).toHaveCount(5)
  await expect(guest.getByText('Це маршрут, яким з вами поділилися')).toBeVisible()
  await expect(guest.getByRole('button', { name: 'Прибрати з маршруту' })).toHaveCount(0)
  await shot(guest, '06-shared')
  const tripId = page.url().split('/').pop()
  await guest.goto(`/plan/${tripId}`) // the private editor URL must not open for a stranger
  await expect(guest).toHaveURL(/\/trips$/)
  await guestContext.close()

  // 6. register: the anonymous trip moves to the account
  await page.getByRole('button', { name: 'Увійти' }).click()
  await page.getByRole('button', { name: /Зареєструватися/ }).click()
  await shot(page, '07-register')
  await page.getByLabel('Ім’я').fill('Олена')
  await page.getByLabel('Електронна пошта').fill(`olena+${Date.now()}@example.com`)
  await page.getByLabel('Пароль').fill('надійний пароль 1')
  await page.getByRole('button', { name: 'Створити обліковий запис' }).click()
  await expect(page.locator('.header__user')).toHaveText('Олена')
  await page.getByRole('link', { name: 'Мої маршрути' }).click()
  await expect(page.getByRole('link', { name: 'Тестовий маршрут Чернівцями' })).toBeVisible()
  await expect(page.locator('.page__note')).toHaveCount(0)

  // 7. clean up through the interface
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Видалити' }).click()
  await expect(page.getByText('Збережених маршрутів ще немає')).toBeVisible()
})

test('wrong password is explained and the form stays open', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Увійти' }).click()
  await page.getByLabel('Електронна пошта').fill('nobody@example.com')
  await page.getByLabel('Пароль').fill('wrong-password')
  await page.getByRole('button', { name: 'Увійти' }).last().click()
  await expect(page.getByRole('alert')).toHaveText('Неправильна пошта або пароль.')
  await expect(page.getByRole('dialog')).toBeVisible()
})

test('works on a phone and in English', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 })
  await page.goto('/')
  await page.getByRole('button', { name: 'ENG' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('walking day')
  await page.getByRole('button', { name: 'Lviv' }).click()
  await addPlacesMobile(page)
  await page.getByRole('tab', { name: /Trip/ }).click()
  await expect(page.locator('.stop')).toHaveCount(2)
  await expect(page.locator('.leg')).toContainText('walk')
  await shot(page, '08-mobile-trip')
  await page.getByRole('tab', { name: 'Map' }).click()
  await expect(page.locator('.leaflet-container')).toBeVisible()
  await expect(page.locator('.pin--stop')).toHaveCount(2)
  await page.waitForTimeout(2000) // let map tiles load for the documentation screenshot
  await shot(page, '09-mobile-map')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

async function addPlacesMobile(page: Page) {
  await expect(page.locator('.card').first()).toBeVisible({ timeout: 60_000 })
  await page.locator('.card .btn--primary').first().click()
  await page.locator('.card .btn--primary').first().click()
  await expect(page.getByRole('tab', { name: /Trip \(2\)/ })).toBeVisible()
}
