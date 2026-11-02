/**
 * Case-generation wiring.
 *
 * `generate.js` owns the entry point and payout cases, `wallet.js` owns the
 * deposit matrix. Both need each other's helpers, so the link is injected here
 * exactly once instead of importing each other (which would be a cycle).
 */
import { __setWalletCases } from './generate.js';
import { generateWalletCases } from './wallet.js';

__setWalletCases(generateWalletCases);

export { generateCases, generatePayoutCases, baseSteps, header, amountInputIds, validAmountInput } from './generate.js';
export { generateWalletCases } from './wallet.js';
