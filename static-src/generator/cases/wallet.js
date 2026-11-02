import { $, checked, val } from '../store.js';
import { licenseApps } from './licenses.js';
import { currentRegion, isDesktop, platformList, PLATFORM_NATIVE, PLATFORM_WEBVIEW } from './platforms.js';
import { baseSteps, header } from './generate.js';
import { paymentTitleFeatures } from '../translations/translations.js';

/**
 * Deposit case matrix.
 *
 * Rules preserved from the legacy generator (do not "simplify" without a
 * requirement change):
 *  - wallet flows only exist for Apple Pay / Google Pay;
 *  - two saved-payment scenarios (after timer, after cancel) are both kept;
 *  - the cashier-return precheck runs once per platform, in its first case;
 *  - platform coverage counters reset on every generation;
 *  - a receipt adds valid/invalid/no-receipt variants without dropping cases.
 */
export function generateWalletCases(wallet) {
  $('message').textContent = '';
  const region = currentRegion();
  const full = true;
  const change = $('amountChange').value === 'yes';
  const com = $('license').value === 'com';
  const qr = checked('qr');
  const receipt = checked('receipt');
  const cases = [];
  const used = new Set();
  const cashierReturnPlatforms = new Set();
  const browsers = platformList(region);
  const amount = val('amount', 'AMOUNT');
  const scanners = $('qrScanner').value === 'both' ? ['camera', 'app'] : [$('qrScanner').value];
  let scanIndex = 0;

  function pay(steps, platform, paid, currency, card) {
    if (wallet && !qr && !checked('oneClick')) {
      steps.push(
        'Открыть платёжное окно ' + wallet + '.',
        'Выбрать карту ' + card + ' в кошельке.',
        'Проверить платёжные данные и выполнить оплату на сумму ' + paid + ' ' + currency + '.',
        'Подтвердить оплату в кошельке. Убедиться, что результат оплаты отображается на исходной платформе.',
      );
      return;
    }
    if (qr && isDesktop(platform)) {
      const scanner = scanners[scanIndex++ % scanners.length];
      steps.push('Оставить QR-код открытым на экране компьютера.');
      steps.push(scanner === 'camera'
        ? 'Отсканировать QR-код обычной камерой телефона и открыть распознанную ссылку.'
        : 'Открыть платёжное приложение на телефоне и отсканировать QR-код встроенной камерой приложения.');
    } else if (qr && $('qrMobile').value === 'download') {
      steps.push(
        'Скачать QR-код на мобильное устройство.',
        'Открыть платёжное приложение и загрузить сохранённое изображение QR для распознавания.',
      );
    } else if (!isDesktop(platform) && (qr || checked('oneClick'))) {
      steps.push(
        'Нажать кнопку перехода в платёжное приложение.',
        'Убедиться, что именно по кнопке открылось нужное платёжное приложение.',
      );
    } else if (!wallet) {
      steps.push('Скопировать необходимые платёжные реквизиты и использовать их для перевода.');
    }
    if (wallet) {
      steps.push('Открыть платёжное окно ' + wallet + '.', 'Выбрать карту ' + card + ' в кошельке.');
    }
    steps.push('Проверить платёжные данные и выполнить оплату на сумму ' + paid + ' ' + currency + '.');
    if (wallet) {
      steps.push('Подтвердить оплату в кошельке. Убедиться, что результат оплаты отображается на исходной платформе.');
    }
  }

  function add(platform, kind, usd = false) {
    const card = !wallet ? ''
      : $('cardNetwork').value === 'both'
        ? (cases.length === 0 ? 'Visa' : 'Mastercard')
        : $('cardNetwork').value === 'visa' ? 'Visa' : 'Mastercard';

    let sum = amount;
    if (kind === 'over') {
      sum = val(usd ? 'usdOverRequest' : 'overRequest', usd ? 'USD_OVER_REQUEST_AMOUNT' : 'OVER_REQUEST_AMOUNT');
    } else if (kind === 'under') {
      sum = val(usd ? 'usdUnderRequest' : 'underRequest', usd ? 'USD_UNDER_REQUEST_AMOUNT' : 'UNDER_REQUEST_AMOUNT');
    } else if (usd) {
      sum = val('usdAmount', 'USD_AMOUNT');
    }
    const currency = usd ? 'USD' : region.currency;

    let paid = sum;
    if (kind === 'over') paid = val(usd ? 'usdOverPaid' : 'overPaid', usd ? 'USD_OVERPAY_ACTUAL_AMOUNT' : 'OVERPAY_ACTUAL_AMOUNT');
    if (kind === 'under') paid = val(usd ? 'usdUnderPaid' : 'underPaid', usd ? 'USD_UNDERPAY_ACTUAL_AMOUNT' : 'UNDERPAY_ACTUAL_AMOUNT');

    const checkCashierReturn = cases.length > 0
      && $('integration').value === 'HPP'
      && checked('returnToCashier')
      && !cashierReturnPlatforms.has(platform);

    const steps = baseSteps(platform, usd, checkCashierReturn);
    let pre = wallet ? 'На тестовом устройстве настроен ' + wallet + ' и добавлена карта ' + card + '.' : '';
    if (checkCashierReturn) cashierReturnPlatforms.add(platform);

    const returnsFromWallet = !isDesktop(platform)
      && ((qr && $('qrMobile').value === 'button') || checked('oneClick'))
      && (kind === 'expiry' || kind === 'before' || (qr && $('qrMobile').value === 'download'));

    if (returnsFromWallet) {
      steps.push(
        'Нажать кнопку перехода в платёжное приложение.',
        'Убедиться, что именно по кнопке открылось нужное платёжное приложение.',
        'Не выполнять оплату. Вернуться из платёжного приложения к исходной платёжной форме на тестируемой платформе и убедиться, что заявка доступна.',
      );
    }

    if (wallet && !qr && !checked('oneClick') && (kind === 'expiry' || kind === 'before')) {
      steps.push(
        'Открыть платёжное окно ' + wallet + '.',
        'Выбрать карту ' + card + ' в кошельке.',
        'Не подтверждать оплату в кошельке.',
        kind === 'expiry' ? 'Дождаться окончания таймера заявки.' : 'Вернуться к заявке и отменить её кнопкой отмены.',
        'Попробовать подтвердить оплату исходной заявки в кошельке после отмены или окончания таймера. Не создавать новую заявку. Если оплата недоступна, зафиксировать причину и проверить отсутствие списания; оставшиеся шаги оплаты не выполнять.',
      );
    } else if (kind === 'expiry' || kind === 'before') {
      pre += (pre ? ' ' : '') + 'Сохранить платёжные данные ДО '
        + (kind === 'expiry' ? 'окончания таймера' : 'отмены заявки') + '.';
      const savedHint = qr ? ' и QR-код'
        : checked('oneClick') && !isDesktop(platform) ? ' и платёжную ссылку' : '';
      steps.push('До ' + (kind === 'expiry' ? 'окончания таймера' : 'отмены заявки')
        + ' сохранить реквизиты' + savedHint + ' для последующей оплаты.');
      steps.push(kind === 'expiry'
        ? 'Не оплачивать заявку до окончания таймера. Дождаться его завершения и показать состояние страницы.'
        : 'Отменить заявку кнопкой отмены и подтвердить отмену, если требуется.');
      steps.push('После ' + (kind === 'expiry' ? 'окончания таймера' : 'отмены')
        + ' выполнить оплату на сумму ' + paid + ' ' + currency
        + ' по заранее сохранённым платёжным данным. Если оплата недоступна, зафиксировать причину.');
    } else {
      pay(steps, platform, paid, currency, card);
    }

    if (kind === 'over' || kind === 'under') {
      steps.push('Фактическая сумма должна быть ' + (kind === 'over' ? 'больше' : 'меньше') + ' суммы заявки.');
    }

    const h2h = $('integration').value === 'H2H';
    const special = ['after', 'before', 'expiry'].includes(kind);
    if (kind === 'after') {
      steps.push('Сразу после перевода вернуться ' + (h2h ? 'в кассу' : 'к платёжной форме провайдера')
        + ' и нажать кнопку отмены. Подтвердить отмену, если требуется. Если кнопка уже недоступна, показать это на видео.');
    } else {
      steps.push(h2h ? 'Вернуться в кассу.' : 'Вернуться к платёжной форме провайдера.');
    }

    const receiptIndex = steps.length;
    if (kind === 'expiry') {
      steps.push('После фактической оплаты подождать и убедиться, что форма с истёкшим таймером не реагирует на оплату. Затем самостоятельно вернуться в кассу.');
    } else if (h2h) {
      steps.push(special
        ? 'Если после отмены или окончания таймера кнопка «Я оплатил» остаётся доступна, нажать её. Если кнопка недоступна, показать состояние кассы на видео.'
        : 'Нажать кнопку «Я оплатил».');
    } else {
      if (!special) steps.push('Нажать кнопку подтверждения оплаты, если она предусмотрена.');
      steps.push('Дождаться завершения обработки оплаты и возврата в кассу.');
    }

    const titles = {
      regular: 'успешный депозит',
      over: 'переплата',
      under: 'недоплата',
      expiry: 'оплата после окончания таймера',
      before: 'отмена, затем оплата',
      after: 'оплата, затем отмена',
    };
    const features = paymentTitleFeatures.filter(([step]) => steps.includes(step));
    const paymentFeatures = features.map((feature) => (qr && feature === paymentTitleFeatures[3] ? 'QR: ' : '') + feature[1]);
    if (qr && (kind === 'expiry' || kind === 'before')) paymentFeatures.push('QR: оплата по сохранённым платёжным данным');
    const paymentFeature = paymentFeatures.join(' + ');

    cases.push({
      title: (wallet ? wallet + ' / ' + card + ' - ' : '') + platform + ' - ' + (usd ? 'USD + ' : '') + titles[kind] + (paymentFeature ? ' + ' + paymentFeature : ''),
      platform, sum, currency, usd, steps, pre, receiptIndex, kind, card,
    });
    used.add(platform);
  }

  if (wallet) {
    browsers.forEach((platform) => add(platform, 'regular'));
    if (change) {
      add(browsers[0], 'over', com);
      add(browsers[1], 'under');
    } else if (com) {
      add(browsers[0], 'regular', true);
    }
    if (checked('timer')) add(browsers[0], 'expiry');
    if (checked('cancel')) {
      add(browsers[0], 'before');
      add(browsers[1], 'after');
    }
  } else {
    add(browsers[0], 'regular');
    const apps = licenseApps();
    const appPlatform = apps.pwa ? 'PWA приложение' : apps.native ? PLATFORM_NATIVE : null;
    if (change) add(appPlatform || browsers[0], full ? 'over' : 'under', com);
    else if (com) add(appPlatform || browsers[0], 'regular', true);
    if (full) {
      if (appPlatform && !used.has(appPlatform)) add(appPlatform, 'regular');
      if (apps.native && !used.has(PLATFORM_NATIVE)) add(PLATFORM_NATIVE, 'regular');
      if (apps.webview) add(PLATFORM_WEBVIEW, change ? 'under' : 'regular');
      else if (change) add(browsers[0], 'under');
      const scenarios = [];
      if (checked('timer')) scenarios.push('expiry');
      if (checked('cancel')) scenarios.push('before', 'after');
      scenarios.forEach((kind) => {
        // Reserve desktop QR coverage for an ordinary payment to exercise scanning.
        const candidates = browsers.filter((platform) => !qr || !isDesktop(platform));
        add(candidates.find((platform) => !used.has(platform)) || candidates[0], kind);
      });
      browsers.forEach((platform) => { if (!used.has(platform)) add(platform, 'regular'); });
    }
  }

  if ($('integration').value === 'HPP' && checked('returnToCashier') && !cashierReturnPlatforms.has(browsers[0])) {
    add(browsers[0], 'regular');
  }

  if (qr) {
    const desktop = wallet ? browsers.find(isDesktop) : 'Desktop ' + region.desktop[0];
    while (scanIndex < scanners.length) add(desktop, 'regular');
  }

  if (receipt) {
    cases[0].steps.splice(cases[0].receiptIndex, 0, 'Загрузить валидный чек выполненного перевода и убедиться, что он принят.');
    let eligible = cases.filter((item, i) => i > 0 && ['regular', 'over', 'under'].includes(item.kind));
    while (eligible.length < 3) {
      add(wallet ? browsers[browsers.length - 1] : 'Desktop ' + region.desktop[0], 'regular');
      eligible = cases.filter((item, i) => i > 0 && ['regular', 'over', 'under'].includes(item.kind));
    }
    // Keep underpayment with a valid receipt; assign the no-receipt flow elsewhere.
    const without = eligible.find((item) => item.kind === 'over') || eligible.find((item) => item.kind === 'regular');
    const invalid = eligible.find((item) => item !== without && item.kind === 'regular' && isDesktop(item.platform) && !item.usd)
      || eligible.find((item) => item !== without && item.kind === 'regular' && !item.usd)
      || eligible.find((item) => item !== without && item.kind !== 'under');
    eligible.forEach((item) => {
      if (item === without) {
        // Remove form confirmation and waiting: return to cashdesk without a receipt.
        item.steps = item.steps.slice(0, item.receiptIndex - 1);
        item.steps.push('После оплаты, не загружая чек, вернуться в кассу.');
        item.title += ' + без загрузки обязательного чека';
      } else if (item === invalid) {
        item.steps = item.steps.slice(0, item.receiptIndex);
        item.steps.push('Загрузить невалидный чек - чек от другой операции, не соответствующий текущему платежу.');
        item.steps.push('Попробовать подтвердить оплату'
          + ($('integration').value === 'H2H'
            ? ' кнопкой «Я оплатил»'
            : ' кнопкой подтверждения на странице провайдера, если она предусмотрена')
          + '. Показать на видео реакцию формы и отображаемое сообщение.');
        item.steps.push('Не заменять чек валидным. Вернуться в кассу.');
        item.title = item.title.replace('успешный депозит', 'оплата') + ' + невалидный чек';
      } else {
        item.steps.splice(item.receiptIndex, 0, 'Загрузить валидный чек выполненного перевода и убедиться, что он принят.');
        item.title += ' + валидный чек';
      }
    });
  }

  if (wallet === 'Google Pay') {
    // Cover the signed-out Google state once on desktop; site login is independent.
    const signedOut = cases.find((item) => item.platform === 'Desktop Chrome' && item.kind === 'regular');
    cases.forEach((item) => {
      if (item === signedOut) {
        item.pre += ' Пользователь не авторизован в аккаунте Google в тестируемом браузере. Авторизация на сайте выполняется отдельно.';
        item.title += ' + без авторизации в Google';
        const index = item.steps.findIndex((step) => step === 'Открыть платёжное окно Google Pay.');
        item.steps.splice(index + 1, 0, 'Проверить предложение войти в аккаунт Google. Выполнить вход в тестовый Google-аккаунт и продолжить оплату выбранной картой. Если продолжение недоступно, зафиксировать результат и не выполнять оставшиеся шаги оплаты.');
      } else {
        item.pre += ' Пользователь авторизован в аккаунте Google, используемом для Google Pay.';
      }
    });
  }

  // Every return-to-cashier step must be followed by a pending-popup check.
  cases.forEach((item) => {
    item.steps = item.steps.flatMap((step, i) => {
      const returnsToCashier = /вернуться в кассу|возврата в кассу/i.test(step);
      const alreadyChecked = (item.steps[i + 1] || '').includes('pending popup');
      return returnsToCashier && !alreadyChecked
        ? [step, 'Убедиться, что касса открыта и пользователю отображается pending popup.']
        : [step];
    });
  });

  return cases.map((item) => ({
    title: item.title,
    text: header(item.platform, item.sum, item.currency, { usd: item.usd })
      .concat(wallet ? ['Wallet: ' + wallet, 'Card: ' + item.card] : [])
      .join('\n')
      + (item.pre ? '\n\nПредусловие: ' + item.pre : '')
      + '\n\n' + item.steps.map((step, i) => 'Шаг ' + (i + 1) + ' - ' + step).join('\n')
      + '\n\nПросьба записать видео полного флоу от шага 1 до шага ' + item.steps.length + '.'
      + (qr && isDesktop(item.platform)
        ? ' Просим включить в видеозапись экран мобильного телефона: момент сканирования QR-кода и весь последующий процесс оплаты.'
        : ''),
  }));
}
