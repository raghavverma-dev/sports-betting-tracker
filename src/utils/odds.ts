/**
 * Convert American odds to decimal odds.
 */
export function americanToDecimal(american: number): number {
  if (american > 0) {
    return american / 100 + 1;
  }
  return 100 / Math.abs(american) + 1;
}

/**
 * Calculate implied probability from American odds.
 */
export function impliedProbability(american: number): number {
  if (american > 0) {
    return 100 / (american + 100);
  }
  return Math.abs(american) / (Math.abs(american) + 100);
}

/**
 * Calculate potential payout from stake and American odds.
 */
export function calculatePayout(stake: number, american: number): number {
  const decimal = americanToDecimal(american);
  return stake * decimal;
}

/**
 * Calculate expected value as a percentage.
 * EV% = (estimatedProb * decimalOdds - 1) * 100
 */
export function calculateEV(estimatedProbability: number, american: number): number {
  const decimal = americanToDecimal(american);
  return (estimatedProbability * decimal - 1) * 100;
}

/**
 * Full Kelly Criterion stake as a fraction of bankroll.
 *   Kelly% = (bp - q) / b
 * where b = decimal odds - 1, p = estimated probability, q = 1 - p.
 *
 * Returns 0 if there is no edge. Callers should typically scale this by
 * a safety fraction (quarter- or eighth-Kelly) before using it to size
 * actual stakes — full Kelly is the theoretical maximum, not a
 * recommendation.
 */
export function kellyStake(estimatedProbability: number, american: number): number {
  const decimal = americanToDecimal(american);
  const b = decimal - 1;
  const p = estimatedProbability;
  const q = 1 - p;
  const kelly = (b * p - q) / b;
  return Math.max(0, kelly);
}

/**
 * Format American odds for display.
 */
export function formatOdds(american: number): string {
  return american > 0 ? `+${american}` : `${american}`;
}

/**
 * Format a probability as a percentage string.
 */
export function formatProbability(prob: number): string {
  return `${(prob * 100).toFixed(1)}%`;
}

/**
 * Format currency.
 */
export function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
  }).format(amount);
}
