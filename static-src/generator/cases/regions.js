// Region reference data: browsers per platform, currency and Cyrillic names.
// Transcribed from the legacy generator output — keep in sync with cases.js.
const CHROME = ['Chrome'];
const SAFARI_CHROME = ['Safari', 'Chrome'];

export const REGIONS = {
  TR: { name: 'Turkey', currency: 'TRY', android: ['Chrome', 'Samsung Internet'], ios: SAFARI_CHROME, desktop: CHROME },
  AZ: { name: 'Azerbaijan', currency: 'AZN', android: ['Chrome', 'Samsung Internet'], ios: SAFARI_CHROME, desktop: CHROME },
  CL: { name: 'Chile', currency: 'CLP', android: ['Chrome', 'Samsung Internet'], ios: SAFARI_CHROME, desktop: CHROME },
  CA: { name: 'Canada', currency: 'CAD', android: ['Chrome', 'Samsung Internet'], ios: SAFARI_CHROME, desktop: CHROME },
  GT: { name: 'Guatemala', currency: 'GTQ', android: ['Chrome', 'Samsung Internet'], ios: SAFARI_CHROME, desktop: CHROME },
  KZ: { name: 'Kazakhstan', currency: 'KZT', android: CHROME, ios: SAFARI_CHROME, desktop: CHROME },
  BO: { name: 'Bolivia', currency: 'BOB', android: CHROME, ios: SAFARI_CHROME, desktop: CHROME },
  UZ: { name: 'Uzbekistan', currency: 'UZS', android: CHROME, ios: SAFARI_CHROME, desktop: CHROME },
  IN: { name: 'India', currency: 'INR', android: CHROME, ios: SAFARI_CHROME, desktop: CHROME },
  KG: { name: 'Kyrgyzstan', currency: 'KGS', android: CHROME, ios: ['Safari'], desktop: CHROME },
  BD: { name: 'Bangladesh', currency: 'BDT', android: CHROME, ios: ['Safari'], desktop: CHROME },
  MX: { name: 'Mexico', currency: 'MXN', android: CHROME, ios: ['Safari'], desktop: CHROME },
  EC: { name: 'Ecuador', currency: 'USD', android: CHROME, ios: ['Safari'], desktop: CHROME },
  HN: { name: 'Honduras', currency: 'HNL', android: CHROME, ios: ['Safari'], desktop: CHROME },
  TJ: { name: 'Tajikistan', currency: 'TJS', android: CHROME, ios: ['Safari'], desktop: CHROME },
  NG: { name: 'Nigeria', currency: 'NGN', android: CHROME, ios: ['Safari'], desktop: CHROME },
  KE: { name: 'Kenya', currency: 'KES', android: CHROME, ios: ['Safari'], desktop: CHROME },
  CG: { name: 'Congo', currency: 'XAF', android: CHROME, ios: ['Safari'], desktop: CHROME },
  RU: { name: 'Russia', currency: 'RUB', android: ['Chrome', 'Yandex'], ios: ['Safari', 'Yandex'], desktop: CHROME },
};

export const REGION_NAMES_RU = {
  Turkey: 'Турция',
  Azerbaijan: 'Азербайджан',
  Chile: 'Чили',
  Canada: 'Канада',
  Guatemala: 'Гватемала',
  Kazakhstan: 'Казахстан',
  Bolivia: 'Боливия',
  Uzbekistan: 'Узбекистан',
  India: 'Индия',
  Kyrgyzstan: 'Кыргызстан',
  Bangladesh: 'Бангладеш',
  Mexico: 'Мексика',
  Ecuador: 'Эквадор',
  Honduras: 'Гондурас',
  Tajikistan: 'Таджикистан',
  Nigeria: 'Нигерия',
  Kenya: 'Кения',
  Congo: 'Конго',
  Russia: 'Россия',
};

/** Region definition for a `<select>` value, falling back to Turkey. */
export const regionOf = (code) => REGIONS[code] || REGIONS.TR;

/** Currency used in case headers. */
export const currencyOf = (code) => regionOf(code).currency;
