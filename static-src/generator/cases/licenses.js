import { $, val } from '../store.js';

/** Which app shells each licence ships with. */
export const LICENSE_CAPABILITIES = {
  com: { native: true, webview: true },
  pinco: { native: true, webview: true },
  zazino: { native: true, pwa: true, webview: false },
};

/** Default site URL per licence; the user may override it in the form. */
export const LICENSE_DEFAULT_SITES = {
  pinco: 'https://pinco.win/',
  com: 'https://pin-up.world/',
  zazino: 'https://zazino.com/',
};

export const licenseApps = () =>
  LICENSE_CAPABILITIES[$('license').value] || { native: false, webview: false };

export const defaultSite = () => LICENSE_DEFAULT_SITES[$('license').value] || 'SITE_URL';

/** Wallet label for the selected payment type, or an empty string. */
export const walletName = () => {
  const wallet = $('wallet').value;
  if (wallet === 'apple') return 'Apple Pay';
  if (wallet === 'google') return 'Google Pay';
  return '';
};

/** Payment method for a platform, honouring the split Google Pay mode. */
export function paymentMethod(platform) {
  const separateGoogle = $('wallet').value === 'google' && $('googleMethodMode').value === 'separate';
  if (separateGoogle && platform === 'Нативное приложение') {
    return val('nativeMethod', 'NATIVE_PAYMENT_METHOD');
  }
  return val('method', 'PAYMENT_METHOD');
}
