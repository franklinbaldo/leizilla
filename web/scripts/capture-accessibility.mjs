import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs';

const sha = process.env.CAPTURE_SHA;
const url = process.env.CAPTURE_URL ?? 'http://127.0.0.1:4321/leizilla/';
const outDir = 'visual-evidence';
const cases = [
  ['home-1280x900.png', 1280, 900, false],
  ['home-390x844.png', 390, 844, false],
  ['home-unavailable-1280x900.png', 1280, 900, true],
  ['home-unavailable-390x844.png', 390, 844, true],
];
const interactiveSelector = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

fs.mkdirSync(outDir, { recursive: true });

async function auditKeyboard(page) {
  const expected = await page.locator(interactiveSelector).evaluateAll((elements) => {
    const visible = elements.filter((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    });
    return visible.map((element, index) => {
      const id = `audit-${index}`;
      element.setAttribute('data-cobogo-audit-id', id);
      return id;
    });
  });

  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
  });
  const reached = new Set();
  const focusFailures = [];

  for (let step = 0; step < expected.length + 8; step += 1) {
    await page.keyboard.press('Tab');
    const state = await page.evaluate(() => {
      const element = document.activeElement;
      if (!(element instanceof HTMLElement)) return null;
      const style = getComputedStyle(element);
      const hasOutline = style.outlineStyle !== 'none' && parseFloat(style.outlineWidth || '0') > 0;
      const hasShadow = style.boxShadow !== 'none';
      return {
        id: element.getAttribute('data-cobogo-audit-id'),
        focusVisible: element.matches(':focus-visible'),
        hasIndicator: hasOutline || hasShadow,
      };
    });
    if (!state?.id) continue;
    reached.add(state.id);
    if (!state.focusVisible || !state.hasIndicator) focusFailures.push(state.id);
    if (reached.size === expected.length) break;
  }

  return {
    expected: expected.length,
    reached: reached.size,
    missing: expected.filter((id) => !reached.has(id)),
    focus_failures: [...new Set(focusFailures)],
  };
}

const browser = await chromium.launch({ headless: true });
const results = [];
let fatalError = null;

try {
  for (const [file, width, height, blockDataset] of cases) {
    const context = await browser.newContext({ viewport: { width, height } });
    const page = await context.newPage();
    const pageErrors = [];
    const consoleErrors = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    if (blockDataset) {
      await page.route('https://archive.org/**', (route) => route.abort('failed'));
    }
    const response = await page.goto(url, { waitUntil: 'networkidle', timeout: 60_000 });
    if (blockDataset) {
      await page.getByText('Não foi possível acessar o acervo agora').waitFor({ timeout: 30_000 });
    }
    const bodyText = await page.locator('body').innerText();
    const axe = await new AxeBuilder({ page }).analyze();
    const seriousAxeViolations = axe.violations.filter(
      (violation) => violation.impact === 'serious' || violation.impact === 'critical',
    );
    const keyboard = await auditKeyboard(page);
    await page.screenshot({ path: `${outDir}/${file}`, fullPage: true });
    results.push({
      file,
      viewport: { width, height },
      controlled_dataset_failure: blockDataset,
      status: response?.status() ?? null,
      title: await page.title(),
      page_errors: pageErrors,
      console_errors: consoleErrors,
      axe_serious_or_critical: seriousAxeViolations.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        help: violation.help,
        targets: violation.nodes.map((node) => node.target),
      })),
      keyboard,
      truthful_unavailable_state: blockDataset
        ? bodyText.includes('Não foi possível acessar o acervo agora') &&
          !bodyText.includes('ainda não foi publicado') &&
          !bodyText.includes('ainda não está no ar')
        : null,
    });
    await context.close();
  }
} catch (error) {
  fatalError = error instanceof Error ? { name: error.name, message: error.message, stack: error.stack } : { message: String(error) };
} finally {
  await browser.close();
  fs.writeFileSync(
    `${outDir}/capture-state.json`,
    JSON.stringify({ sha, url, captured_at: new Date().toISOString(), fatal_error: fatalError, results }, null, 2),
  );
}

const failed = fatalError || results.length !== cases.length || results.some(
  (result) =>
    result.status !== 200 ||
    result.page_errors.length > 0 ||
    result.truthful_unavailable_state === false ||
    result.axe_serious_or_critical.length > 0 ||
    result.keyboard.missing.length > 0 ||
    result.keyboard.focus_failures.length > 0,
);

if (failed) {
  console.error(JSON.stringify({ fatal_error: fatalError, results }, null, 2));
  process.exit(1);
}
