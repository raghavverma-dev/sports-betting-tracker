/**
 * Barrel re-export for backward compatibility.
 *
 * The actual code now lives in:
 *   - oddsApiClient.ts  — API key, quota, odds/scores fetching
 *   - ranking.ts        — de-vig, EV calculation, stale/outlier detection
 */

export {
  SPORT_KEY_MAP,
  SUPPORTED_SPORTS,
  setApiKey,
  getStoredApiKey,
  checkApiQuota,
  fetchOddsForSport,
  fetchScoresForSport,
} from './oddsApiClient';

export type {
  OddsOutcome,
  OddsMarket,
  BookmakerOdds,
  GameOdds,
  GameScore,
  ApiQuota,
} from './oddsApiClient';

export { rankBets } from './ranking';
export type { RankedBet } from './ranking';
