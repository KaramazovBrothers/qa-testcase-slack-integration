import { $, checked, val, state } from '../store.js';
import { defaultSite, licenseApps, paymentMethod, walletName } from './licenses.js';
import { currentRegion, isDesktop, platformList, PLATFORM_NATIVE, PLATFORM_WEBVIEW } from './platforms.js';
import { payoutAmountError } from './payout.js';

/** Cashdesk request header shared by deposit and payout cases. */
export function header(platform, amount, currency, { usd = false, operation = 'deposit' } = {}) {
  const accountId = usd ? 'usdAccount' : 'account';
  const login = usd ? 'usdLogin' : 'login';
  const password = usd ? 'usdPassword' : 'password';
  return [
    'Cashdesk payment request:',
    'Site: ' + val('site', defaultSite()),
    'Region: ' + currentRegion().name,
    'Integration: ' + $('integration').value,
    'Platform: ' + platform,
    'Operation type: ' + operation,
    'AccountID: ' + val(accountId, usd ? 'USD_ACCOUNT_ID' : 'ACCOUNT_ID'),
    'login: ' + val(login, usd ? 'USD_LOGIN' : 'LOGIN'),
    'Password: ' + val(password, usd ? 'USD_PASSWORD' : 'PASSWORD'),
    'Account currency: ' + currency,
    'Payment method: ' + paymentMethod(platform),
    'Sum: ' + amount + ' ' + currency,
  ];
}

/** Opening/login/payment steps that every deposit case starts with. */
export function baseSteps(platform, usd = false, checkCashierReturn = false) {
  const site = val('site', defaultSite());
  const steps = [];
  if (platform === PLATFORM_NATIVE) {
    steps.push(`Открыть ${site}, скачать нативное приложение из футера сайта и установить его. Открыть установленное приложение.`);
  } else if (platform === 'PWA приложение') {
    steps.push(`Открыть ${site}, установить PWA приложение через меню браузера и открыть установленное PWA приложение.`);
  } else if (platform === PLATFORM_WEBVIEW) {
    steps.push('Установить и открыть WebView-приложение из APK-файла, предоставленного вместе с запросом на тестирование.');
  } else {
    steps.push(`Открыть ${site} в ${platform}.`);
  }
  steps.push(usd
    ? 'Авторизоваться указанным отдельным пользователем с валютой аккаунта USD.'
    : 'Авторизоваться указанным тестовым пользователем.');
  steps.push(
    'Открыть кассу, выбрать вкладку «Пополнить» и метод ' + paymentMethod(platform) + '.',
    'Ввести указанную сумму заявки и нажать «Пополнить».',
  );
  steps.push($('integration').value === 'HPP'
    ? 'Дождаться открытия платёжной страницы провайдера.'
    : 'Дождаться платёжных данных в нашей кассе.');
  if (checkCashierReturn) {
    steps.push(
      'Нажать кнопку «Вернуться в кассу».',
      'Убедиться, что касса открыта на исходной платформе, пользователю отображается pending popup и пользователь остался авторизован.',
      'Повторить необходимые действия для возврата на страницу провайдера.',
    );
  }
  return steps;
}

/** Payout cases: plain, with 25% commission, and the COM USD variant. */
export function generatePayoutCases() {
  const error = payoutAmountError();
  if (error) throw new Error(error);
  const specs = [{ fee: false, usd: false }, { fee: true, usd: false }];
  if ($('license').value === 'com') specs.push({ fee: false, usd: true });
  return specs.map(({ fee, usd }) => {
    const currency = usd ? 'USD' : currentRegion().currency;
    const amountField = usd ? 'usdAmount' : fee ? 'payoutFeeAmount' : 'payoutAmount';
    const amountFallback = usd ? 'USD_AMOUNT' : fee ? 'PAYOUT_FEE_AMOUNT' : 'PAYOUT_AMOUNT';
    const amount = val(amountField, amountFallback);
    const lines = header('any', amount, currency, { usd, operation: 'payout' })
      .map((line) => (line === 'Platform: any' ? 'Device: any' : line));
    if (fee) lines.push('Commission: 25%');
    const steps = [
      'Открыть ' + val('site', defaultSite()) + '.',
      usd
        ? 'Авторизоваться указанным отдельным пользователем с валютой аккаунта USD.'
        : 'Авторизоваться указанным тестовым пользователем.',
      'Открыть кассу, выбрать вкладку «Выплата» и метод ' + val('method', 'PAYMENT_METHOD') + '.',
      'Ввести указанную сумму заявки и нажать «Выплата».',
      'После создания заявки на выплату вернуться в кассу на вкладку «Выплата» и зафиксировать, что вывод недоступен: выплата ожидает по выбранному методу.',
    ];
    const title = (usd ? 'USD - ' : '') + (fee ? 'выплата с комиссией 25%' : 'выплата');
    const notice = fee ? '\n\nУведомление: Выплата будет с комиссией 25%' : '';
    return {
      title,
      text: lines.join('\n') + notice + '\n\n'
        + steps.map((step, i) => 'Шаг ' + (i + 1) + ' - ' + step).join('\n')
        + '\n\nПросьба записать видео полного флоу от шага 1 до шага ' + steps.length
        + '. Обязательно прикрепить подтверждение операции - чек о зачислении средств.',
    };
  });
}

export const amountInputIds = [
  'amount', 'overRequest', 'overPaid', 'underRequest', 'underPaid',
  'usdAmount', 'usdUnderRequest', 'usdUnderPaid', 'usdOverRequest', 'usdOverPaid',
  'payoutAmount', 'payoutFeeAmount',
];

export const validAmountInput = (value) => /^\d{0,6}$/.test(value);

/** Entry point used by the form button. */
export function generateCases() {
  for (const id of amountInputIds) {
    if (!validAmountInput($(id).value)) throw new Error('Введите целое число: не более 6 цифр.');
  }
  if ($('integration').value === 'payout') return generatePayoutCases();
  const wallet = walletName();
  return invokeWalletCases(wallet)
    .map((item) => ({ ...item, text: item.text + ' Обязательно прикрепить подтверждение операции - чек об оплате.' }));
}

// `generateWalletCases` lives in wallet.js and is injected to keep the module
// graph acyclic (wallet.js needs baseSteps/header from here).
let walletCaseGenerator = null;
/** @internal wired by cases/index.js */
export function __setWalletCases(fn) { walletCaseGenerator = fn; }

function invokeWalletCases(wallet) {
  if (!walletCaseGenerator) throw new Error('Generator modules not initialised');
  return walletCaseGenerator(wallet);
}

export { state, checked, isDesktop, platformList };
