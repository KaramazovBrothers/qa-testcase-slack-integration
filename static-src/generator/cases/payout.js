import { $, checked, state } from '../store.js';
import { translate } from '../translations/translations.js';
import { licenseApps, walletName } from './licenses.js';
import { platformList, currentRegion } from './platforms.js';

/**
 * Payout amounts are integers in local currency. A 25% commission must leave
 * a fractional value, so requests divisible by 4 are rejected.
 */
export const payoutInteger = (raw) => {
  if (!/^\d{1,6}$/.test(raw.trim())) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value > 0 && value <= Math.floor(Number.MAX_SAFE_INTEGER / 100)
    ? value
    : null;
};

/** Smallest request near amount/0.75 whose 25% commission lands on a fraction. */
export function suggestedPayoutAmount() {
  const amount = payoutInteger($('payoutAmount').value);
  if (amount === null) return '';
  const near = Math.min(999999, Math.floor(amount / 0.75));
  const candidates = [near - 1, near, near + 1, near + 2]
    .filter((value) => value > 0 && value <= 999999 && value % 4 !== 0);
  // On an equal distance prefer the larger net amount.
  candidates.sort((a, b) => Math.abs(a * 3 - amount * 4) - Math.abs(b * 3 - amount * 4) || b - a);
  return String(candidates[0]);
}

/** Validation message for the payout amount fields, or an empty string. */
export function payoutAmountError() {
  const ids = ['payoutAmount', 'payoutFeeAmount', ...($('license').value === 'com' ? ['usdAmount'] : [])];
  for (const id of ids) {
    if ($(id).value.trim() && payoutInteger($(id).value) === null) {
      return 'Сумма заявки должна быть положительным целым числом.';
    }
  }
  const fee = payoutInteger($('payoutFeeAmount').value);
  return fee !== null && fee % 4 === 0
    ? 'После удержания 25% получится целая сумма. Выберите сумму заявки, не кратную 4.'
    : '';
}

/** Recompute the fee request unless the operator typed a manual value. */
export function updatePayoutAmount() {
  if (!state.payoutFeeManual) $('payoutFeeAmount').value = suggestedPayoutAmount();
  const error = payoutAmountError();
  $('payoutWarning').textContent = error ? translate(error) : '';
}

/** Apply integration/licence/wallet/region visibility rules to the form. */
export function updateUI() {
  const integration = $('integration').value;
  const wallet = walletName();
  const google = $('wallet').value === 'google';

  $('h2hNotice').classList.toggle('hidden', integration !== 'H2H');
  $('cardNetworkWrap').classList.toggle('hidden', !wallet);
  $('walletSettings').classList.toggle('hidden', !wallet);
  $('googleMethodModeWrap').classList.toggle('hidden', !google);
  $('googleMethodHint').classList.toggle('hidden', !google);
  $('googleMethodMode').disabled = !google;
  $('nativeMethodWrap').classList.toggle('hidden', !google || $('googleMethodMode').value !== 'separate');
  $('returnToCashierWrap').classList.toggle('hidden', integration !== 'HPP');
  $('returnToCashier').disabled = integration !== 'HPP';

  const region = currentRegion();
  $('regionInfo').innerHTML =
    'Валюта: <b>' + region.currency + '</b><br>Android: ' + region.android.join(', ') +
    '<br>iOS: ' + region.ios.join(', ') + '<br>Desktop: ' + region.desktop.join(', ');

  $('qrSettings').classList.toggle('hidden', !checked('qr'));

  const apps = licenseApps();
  const extra = [];
  if (apps.webview) extra.push('WebView');
  if (apps.native) extra.push('Нативное приложение');
  if (apps.pwa) extra.push('PWA приложение');
  if (extra.length) $('regionInfo').innerHTML += '<br>Дополнительные платформы: ' + extra.join(', ');

  if (wallet) {
    $('regionInfo').innerHTML =
      'Валюта: <b>' + region.currency + '</b><br>' + wallet + ': ' + platformList(region).join(', ');
  }

  $('comBox').classList.toggle('hidden', $('license').value !== 'com');
  // Over/underpayment actual amounts exist only when the amount may change.
  const amountChange = $('amountChange').value === 'yes';
  $('usdOverWrap').classList.toggle('hidden', !amountChange);
  $('usdUnderWrap').classList.toggle('hidden', !amountChange);
  $('overWrap').classList.toggle('hidden', false);
  $('overRequestWrap').classList.toggle('hidden', false);
  $('usdOverRequestWrap').classList.toggle('hidden', !amountChange);
  $('usdUnderRequestWrap').classList.toggle('hidden', !amountChange);

  const payout = integration === 'payout';
  ['walletWrap', 'amountChangeWrap', 'amountWrap', 'underPaidWrap', 'underRequestWrap',
    'overWrap', 'overRequestWrap', 'depositFeatures']
    .forEach((id) => $(id).classList.toggle('hidden', payout));
  ['payoutAmountWrap', 'payoutFeeAmountWrap', 'payoutHint']
    .forEach((id) => $(id).classList.toggle('hidden', !payout));

  if (payout) {
    ['walletSettings', 'nativeMethodWrap', 'usdOverWrap', 'usdUnderWrap',
      'usdOverRequestWrap', 'usdUnderRequestWrap']
      .forEach((id) => $(id).classList.add('hidden'));
    $('regionInfo').textContent = translate('Валюта:') + ' ' + region.currency + ' · Device: any';
    updatePayoutAmount();
  }
}
