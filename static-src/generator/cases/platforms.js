import { $, val } from '../store.js';
import { regionOf } from './regions.js';
import { paymentMethod } from './licenses.js';

/** Platforms the generator produces cases for. */
export const PLATFORM_NATIVE = 'Нативное приложение';
export const PLATFORM_WEBVIEW = 'WebView';
export const PLATFORM_PWA = 'PWA приложение';

export const currentRegion = () => regionOf($('region').value);

/** Desktop platforms share the desktop browser matrix. */
export const isDesktop = (platform) => platform.startsWith('Desktop') || platform.startsWith('macOS');

/**
 * Ordered platform list for a region.
 * Apple Pay is limited to Safari on Apple hardware; Google Pay covers the
 * browsers plus the native app and WebView, matching the wallet test matrix.
 */
export function platformList(region) {
  const wallet = $('wallet').value;
  if (wallet === 'apple') return ['iOS Safari', 'macOS Safari'];
  if (wallet === 'google') {
    return ['Android Chrome', 'Desktop Chrome', PLATFORM_NATIVE, PLATFORM_WEBVIEW];
  }
  const platforms = [];
  region.android.forEach((browser) => platforms.push(`Android ${browser}`));
  region.ios.forEach((browser) => platforms.push(`iOS ${browser}`));
  region.desktop.forEach((browser) => platforms.push(`Desktop ${browser}`));
  return platforms;
}

/** Map a platform to the payment method the case must use. */
export const methodFor = (platform) => paymentMethod(platform);

/** Currency label for the amount header (USD scenarios reuse the region). */
export const currencyFor = (regionCode, usd = false) => (usd ? 'USD' : regionOf(regionCode).currency);

export { val };
