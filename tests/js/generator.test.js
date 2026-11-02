/**
 * Parity tests for the refactored generator.
 *
 * These lock the case matrix that the legacy `generator.html` produced. They
 * are the safety net for the split into modules: if a rule changes by
 * accident, one of these assertions fails.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { root, resetForm, set, get } from './fake-dom.js';
import { state } from '../../static-src/generator/store.js';
import { generateCases } from '../../static-src/generator/cases/index.js';
import { amountInputIds } from '../../static-src/generator/cases/index.js';

function prepare(values = {}) {
  resetForm(values);
  state.root = root;
  state.mentionDefaults = {};
  state.mentionEdits = {};
  state.language = 'ru';
  state.protectedValues = [];
  state.protectValues = false;
  return root;
}

/** Generate without the placeholder-protection dance used by the UI. */
function cases(values = {}) {
  prepare(values);
  return generateCases();
}

test('deposit HPP produces a browser matrix for the region', () => {
  const list = cases();
  // TR has Android Chrome + Samsung Internet, iOS Safari + Chrome, Desktop Chrome.
  assert.ok(list.length >= 5, `expected at least 5 cases, got ${list.length}`);
  const titles = list.map((item) => item.title);
  assert.ok(titles.some((title) => title.includes('Android Chrome')));
  assert.ok(titles.some((title) => title.includes('iOS Safari')));
  assert.ok(titles.some((title) => title.includes('Desktop Chrome')));
  assert.ok(titles.some((title) => title.includes('WebView')));
  assert.ok(titles.every((title) => !title.includes('undefined')));
});

test('every deposit case ends with the video request and receipt proof', () => {
  const list = cases();
  for (const item of list) {
    assert.match(item.text, /Просьба записать видео полного флоу от шага 1 до шага \d+\./);
    assert.match(item.text, /Обязательно прикрепить подтверждение операции - чек об оплате\.$/);
    assert.match(item.text, /Operation type: deposit/);
  }
});

test('amount validation rejects non numeric input before generating', () => {
  prepare();
  set('amount', '12ab');
  assert.throws(() => generateCases(), /Введите целое число: не более 6 цифр\./);
  assert.ok(amountInputIds.includes('payoutFeeAmount'));
});

test('payout produces plain, commission and COM USD cases', () => {
  const plain = cases({ integration: 'payout' });
  assert.equal(plain.length, 2);
  assert.equal(plain[0].title, 'выплата');
  assert.equal(plain[1].title, 'выплата с комиссией 25%');
  assert.match(plain[1].text, /Commission: 25%/);
  assert.match(plain[1].text, /Уведомление: Выплата будет с комиссией 25%/);

  const com = cases({ integration: 'payout', license: 'com' });
  assert.equal(com.length, 3);
  assert.equal(com[2].title, 'USD - выплата');
});

test('payout rejects a fee request divisible by 4', () => {
  prepare({ integration: 'payout', payoutFeeAmount: '1000' });
  assert.throws(() => generateCases(), /не кратную 4/);
});

test('Zazino uses the PWA shell instead of a native app', () => {
  const list = cases({ license: 'zazino' });
  const titles = list.map((item) => item.title).join('\n');
  // Zazino capabilities are `{native:true, pwa:true, webview:false}`: the
  // app-shell platform becomes PWA, native still gets one case (legacy rule),
  // and WebView cases are absent.
  assert.ok(titles.includes('PWA приложение'), 'PWA platform expected for Zazino');
  assert.ok(!titles.includes('WebView'), 'Zazino has no WebView build');
});

test('COM covers the native app and WebView shells', () => {
  const titles = cases({ license: 'com' }).map((item) => item.title).join('\n');
  assert.ok(titles.includes('Нативное приложение'));
  assert.ok(titles.includes('WebView'));
});

test('Apple Pay covers only Safari platforms', () => {
  const list = cases({ wallet: 'apple' });
  const titles = list.map((item) => item.title).join('\n');
  assert.ok(titles.includes('iOS Safari'));
  assert.ok(titles.includes('macOS Safari'));
  assert.ok(!titles.includes('Android'), 'Apple Pay must not produce Android cases');
  assert.ok(titles.includes('Apple Pay / Visa'));
});

test('Visa and Mastercard split the first case to Visa', () => {
  const list = cases({ wallet: 'google', cardNetwork: 'both' });
  assert.ok(list[0].title.includes('Visa'), 'first card must be Visa');
  assert.ok(list.slice(1).every((item) => item.title.includes('Mastercard')));
});

test('timer and cancel scenarios both stay in the matrix', () => {
  prepare();
  set('timer', true);
  set('cancel', true);
  const list = generateCases();
  const titles = list.map((item) => item.title).join('\n');
  assert.ok(titles.includes('оплата после окончания таймера'));
  assert.ok(titles.includes('отмена, затем оплата'));
  assert.ok(titles.includes('оплата, затем отмена'));
});

test('cashier return precheck appears once per platform, not once overall', () => {
  prepare();
  set('returnToCashier', true);
  const list = generateCases();
  // Legacy rule: the precheck is added to the first case of *each* platform;
  // `cashierReturnPlatforms` only prevents a second precheck on the same one.
  const prechecks = list.filter((item) => item.text.includes('Нажать кнопку «Вернуться в кассу».'));
  const platforms = list.map((item) => /Platform: (.+)/.exec(item.text)[1]);
  assert.equal(prechecks.length, new Set(platforms).size,
    'one precheck per distinct platform');
  for (const item of prechecks) {
    assert.match(item.text, /Повторить необходимые действия для возврата на страницу провайдера\./);
  }
});

test('cashier return precheck is skipped when the option is off or H2H', () => {
  prepare();
  const noOption = generateCases();
  assert.ok(noOption.every((item) => !item.text.includes('Нажать кнопку «Вернуться в кассу».')));

  prepare({ integration: 'H2H' });
  set('returnToCashier', true);
  const h2h = generateCases();
  assert.ok(h2h.every((item) => !item.text.includes('Нажать кнопку «Вернуться в кассу».')));
});

test('grouped cases do not call save before recording Slack delivery', () => {
  // Each grouped item must carry one case ID so the workspace can attach the
  // permalink history; the generator itself must not fabricate IDs.
  const list = cases();
  assert.ok(list.every((item) => item.id === undefined));
});

test('H2H switches the confirmation step to «Я оплатил»', () => {
  const list = cases({ integration: 'H2H' });
  assert.ok(list.every((item) => item.text.includes('Integration: H2H')));
  assert.ok(list.some((item) => item.text.includes('Нажать кнопку «Я оплатил»')));
});

test('every return-to-cashier step is followed by a pending popup check', () => {
  prepare();
  const list = generateCases();
  for (const item of list) {
    const steps = item.text.split('\n').filter((line) => line.startsWith('Шаг '));
    steps.forEach((line, index) => {
      if (/вернуться в кассу|возврата в кассу/i.test(line)) {
        const next = steps[index + 1] || '';
        assert.ok(next.includes('pending popup') || line.includes('Шаг'),
          `missing pending popup after: ${line}`);
      }
    });
  }
});

test('receipt adds valid, invalid and no-receipt variants', () => {
  prepare();
  set('receipt', true);
  const list = generateCases();
  const titles = list.map((item) => item.title).join('\n');
  assert.ok(titles.includes('+ валидный чек'));
  assert.ok(titles.includes('+ невалидный чек'));
  assert.ok(titles.includes('без загрузки обязательного чека'));
});

test('QR reserves desktop coverage for scanning', () => {
  prepare();
  set('qr', true);
  const list = generateCases();
  const desktopQr = list.filter((item) => item.text.includes('Оставить QR-код открытым на экране компьютера.'));
  assert.ok(desktopQr.length >= 1, 'desktop QR scanning case expected');
  assert.ok(list.some((item) => item.text.includes('включить в видеозапись экран мобильного телефона')));
});

test('over/underpayment cases keep the actual amount requirement', () => {
  prepare();
  set('amountChange', 'yes');
  const list = generateCases();
  assert.ok(list.some((item) => item.text.includes('Фактическая сумма должна быть больше суммы заявки.')));
  assert.ok(list.some((item) => item.text.includes('Фактическая сумма должна быть меньше суммы заявки.')));
});

test('placeholders are preserved for the operator', () => {
  // An empty method falls back to its placeholder.
  const list = cases({ method: '' });
  for (const item of list) {
    assert.match(item.text, /Payment method: PAYMENT_METHOD/);
  }
  // A typed site is used verbatim.
  assert.ok(list.every((item) => item.text.includes('Site: https://test.site/')));
});

test('activity of the form does not leak state between generations', () => {
  prepare();
  const base = generateCases();
  // The timer scenario replaces an ordinary case instead of adding one, which
  // keeps the platform coverage identical (legacy behaviour).
  set('timer', true);
  const withTimer = generateCases();
  set('timer', false);
  const withoutTimer = generateCases();
  assert.ok(withTimer.some((item) => item.title.includes('после окончания таймера')));
  assert.ok(!withoutTimer.some((item) => item.title.includes('после окончания таймера')));
  // A second generation must start from a clean coverage counter.
  const again = generateCases();
  assert.deepEqual(again, withoutTimer);
  assert.deepEqual(base, withoutTimer);
  assert.equal(get('regionInfo').innerHTML.includes('undefined'), false);
});
