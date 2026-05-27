/**
 * AI Auto-Bettor strategy engine.
 *
 * Given live ranked bets and a configuration, decides which bets to place
 * and how much to stake using Kelly sizing. Handles settlement via the
 * scores API.
 */

import type { AutoBet, AutoBetConfig, AutoBetState, Sport } from '../types';
import { americanToDecimal, calculatePayout } from './odds';
import { fetchOddsForSport, fetchScoresForSport } from './oddsApiClient';
import type { GameScore } from './oddsApiClient';
import { rankBets } from './ranking';
import type { RankedBet } from './ranking';

// Sports where a draw is a distinct h2h outcome (not a push).
// For these, if you bet Home or Away and the game draws, you lose.
const THREE_WAY_SPORTS = new Set(['MLS']);

const STORAGE_KEY = 'auto-bettor-state';

export const DEFAULT_CONFIG: AutoBetConfig = {
  enabled: false,
  minEv: 3,
  maxEv: 15, // Anything above 15% is almost certainly bad data
  kellyFraction: 0.125,
  maxBetsPerDay: 5,
  maxStakePercent: 5,
  sports: ['MLB', 'NBA', 'NHL'] as Sport[],
  skipStale: true,
};

export function loadAutoBetState(): AutoBetState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return createDefaultState();
    return JSON.parse(raw) as AutoBetState;
  } catch {
    return createDefaultState();
  }
}

const CHANGE_EVENT = 'auto-bettor-state-changed';

export function saveAutoBetState(state: AutoBetState): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  // The native `storage` event only fires across tabs, not within the
  // same tab. We dispatch a CustomEvent so same-tab subscribers
  // (e.g. the sidebar bankroll widget) can re-read on every change.
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT));
}

export function subscribeToAutoBetState(listener: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, listener);
  return () => window.removeEventListener(CHANGE_EVENT, listener);
}

function createDefaultState(): AutoBetState {
  return {
    config: { ...DEFAULT_CONFIG },
    bets: [],
    bankroll: 1000,
    initialBankroll: 1000,
    bankrollHistory: [{ date: new Date().toISOString(), balance: 1000 }],
    lastRunAt: null,
    totalApiCalls: 0,
  };
}

/**
 * Kelly Criterion stake sizing.
 * Returns the dollar amount to bet given current bankroll.
 */
function kellyStakeAmount(
  trueProbability: number,
  american: number,
  bankroll: number,
  kellyFraction: number,
  maxStakePercent: number,
): number {
  const decimal = americanToDecimal(american);
  const b = decimal - 1;
  const p = trueProbability;
  const q = 1 - p;
  const fullKelly = (b * p - q) / b;

  if (fullKelly <= 0) return 0;

  const fractionalKelly = fullKelly * kellyFraction;
  const maxFraction = maxStakePercent / 100;
  const fraction = Math.min(fractionalKelly, maxFraction);

  return Math.round(fraction * bankroll * 100) / 100;
}

function betsPlacedToday(bets: AutoBet[]): number {
  const today = new Date().toISOString().slice(0, 10);
  return bets.filter(b => b.placedAt.slice(0, 10) === today).length;
}

/**
 * Why a bet was rejected from auto-placement.
 */
export interface RejectedBet {
  event: string;
  selection: string;
  sport: string;
  bestOdds: number;
  bestBook: string;
  ev: number;
  reason: string;
  reasonCode: 'wrong_sport' | 'three_way' | 'not_moneyline' | 'duplicate_game'
    | 'stale_no_fallback' | 'below_min_ev' | 'above_max_ev' | 'stake_too_small'
    | 'daily_limit' | 'negative_ev';
}

export interface SelectionResult {
  placed: AutoBet[];
  rejected: RejectedBet[];
}

/**
 * Select which bets to place from the ranked board.
 * Returns both placed bets and a full rejection log.
 */
export function selectBets(
  ranked: RankedBet[],
  state: AutoBetState,
): SelectionResult {
  const { config, bets: existingBets } = state;
  let { bankroll } = state;

  const todayCount = betsPlacedToday(existingBets);
  const slotsLeft = config.maxBetsPerDay - todayCount;

  const usedGameIds = new Set(
    existingBets.filter(b => b.status === 'pending').map(b => b.gameId)
  );

  const sportSet = new Set(config.sports as string[]);
  const selected: AutoBet[] = [];
  const rejected: RejectedBet[] = [];

  function reject(bet: RankedBet, reason: string, reasonCode: RejectedBet['reasonCode']) {
    rejected.push({
      event: bet.event,
      selection: bet.selection,
      sport: bet.sport,
      bestOdds: bet.bestOdds,
      bestBook: bet.bestBook,
      ev: bet.adjustedEv ?? bet.ev,
      reason,
      reasonCode,
    });
  }

  for (const bet of ranked) {
    if (selected.length >= slotsLeft) {
      reject(bet, `Daily limit reached (${config.maxBetsPerDay} bets/day)`, 'daily_limit');
      continue;
    }

    if (!sportSet.has(bet.sport)) continue; // Not selected — not worth logging

    if (THREE_WAY_SPORTS.has(bet.sport)) {
      reject(bet, `${bet.sport} excluded — draw settlement not supported`, 'three_way');
      continue;
    }

    if (bet.betType !== 'h2h') continue; // Spreads/totals — skip silently

    const gameId = bet.gameId;
    if (usedGameIds.has(gameId)) {
      reject(bet, 'Other side of this game already selected or pending', 'duplicate_game');
      continue;
    }

    const hasWarning = bet.staleWarning || bet.outlierWarning;
    let effectiveEv: number;
    let effectiveOdds: number;
    let effectiveBook: string;
    let effectiveMarketProb: number;

    if (hasWarning && config.skipStale) {
      if (bet.adjustedEv == null) {
        const reasons = [];
        if (bet.staleWarning) reasons.push(`stale by ${bet.staleMinutes}min`);
        if (bet.outlierWarning) reasons.push('outlier odds');
        reject(bet, `${reasons.join(' + ')} — no clean fallback book available`, 'stale_no_fallback');
        continue;
      }
      effectiveEv = bet.adjustedEv;
      effectiveOdds = bet.adjustedBestOdds!;
      effectiveBook = bet.adjustedBestBook!;
      effectiveMarketProb = bet.adjustedMarketProbability ?? bet.marketProbability;
    } else {
      effectiveEv = bet.ev;
      effectiveOdds = bet.bestOdds;
      effectiveBook = bet.bestBook;
      effectiveMarketProb = bet.marketProbability;
    }

    if (effectiveEv <= 0) {
      reject(bet, `Negative EV (${effectiveEv.toFixed(1)}%)`, 'negative_ev');
      continue;
    }
    if (effectiveEv < config.minEv) {
      reject(bet, `EV ${effectiveEv.toFixed(1)}% below minimum ${config.minEv}%`, 'below_min_ev');
      continue;
    }
    if (effectiveEv > config.maxEv) {
      reject(bet, `EV ${effectiveEv.toFixed(1)}% exceeds ${config.maxEv}% cap — likely bad data (${bet.bestBook} at ${bet.bestOdds > 0 ? '+' : ''}${bet.bestOdds})`, 'above_max_ev');
      continue;
    }

    const stake = kellyStakeAmount(
      effectiveMarketProb,
      effectiveOdds,
      bankroll,
      config.kellyFraction,
      config.maxStakePercent,
    );

    if (stake < 1) {
      reject(bet, `Kelly stake $${stake.toFixed(2)} too small (< $1)`, 'stake_too_small');
      continue;
    }

    const potentialPayout = calculatePayout(stake, effectiveOdds);

    const autoBet: AutoBet = {
      id: `auto-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      placedAt: new Date().toISOString(),
      sport: bet.sport as Sport,
      event: bet.event,
      selection: bet.selection,
      betType: bet.betType,
      odds: effectiveOdds,
      book: effectiveBook,
      stake,
      potentialPayout: Math.round(potentialPayout * 100) / 100,
      ev: effectiveEv,
      kellyPercent: Math.round((stake / bankroll) * 10000) / 100,
      status: 'pending',
      settledAt: null,
      payout: 0,
      gameId,
      commenceTime: bet.commenceTime,
    };

    selected.push(autoBet);
    usedGameIds.add(gameId); // Block the other side of this game
    bankroll -= stake;
  }

  return { placed: selected, rejected };
}

/**
 * Place the selected bets: deduct from bankroll, append to history.
 */
export function placeBets(state: AutoBetState, betsToPlace: AutoBet[]): AutoBetState {
  if (betsToPlace.length === 0) return state;

  const totalStake = betsToPlace.reduce((sum, b) => sum + b.stake, 0);
  const newBankroll = Math.round((state.bankroll - totalStake) * 100) / 100;

  return {
    ...state,
    bets: [...state.bets, ...betsToPlace],
    bankroll: newBankroll,
    bankrollHistory: [
      ...state.bankrollHistory,
      { date: new Date().toISOString(), balance: newBankroll },
    ],
    lastRunAt: new Date().toISOString(),
  };
}

/**
 * Fetch odds, rank, select, and place bets in one step.
 */
export interface RunResult {
  newState: AutoBetState;
  placed: AutoBet[];
  rejected: RejectedBet[];
  apiCalls: number;
  sportsAttempted: number;
  sportsFailed: string[];
  totalConsidered: number; // h2h bets from ranked board before filtering
}

export async function runAutoBet(state: AutoBetState): Promise<RunResult> {
  const { config } = state;
  const empty: RunResult = { newState: state, placed: [], rejected: [], apiCalls: 0, sportsAttempted: 0, sportsFailed: [], totalConsidered: 0 };
  if (!config.enabled) return empty;

  const eligibleSports = config.sports.filter(s => !THREE_WAY_SPORTS.has(s));
  if (eligibleSports.length === 0) return empty;

  let apiCalls = 0;
  const allGames = [];
  const sportsFailed: string[] = [];

  for (const sport of eligibleSports) {
    try {
      const games = await fetchOddsForSport(sport, 'h2h');
      apiCalls++;
      allGames.push(...games);
    } catch {
      apiCalls++;
      sportsFailed.push(sport);
    }
  }

  if (allGames.length === 0) {
    return {
      newState: { ...state, lastRunAt: new Date().toISOString(), totalApiCalls: state.totalApiCalls + apiCalls },
      placed: [],
      rejected: [],
      apiCalls,
      sportsAttempted: eligibleSports.length,
      sportsFailed,
      totalConsidered: 0,
    };
  }

  const ranked = rankBets(allGames);
  const totalConsidered = ranked.filter(b => b.betType === 'h2h').length;
  const { placed: betsToPlace, rejected } = selectBets(ranked, state);
  const newState = placeBets(state, betsToPlace);

  return {
    newState: { ...newState, totalApiCalls: state.totalApiCalls + apiCalls },
    placed: betsToPlace,
    rejected,
    apiCalls,
    sportsAttempted: eligibleSports.length,
    sportsFailed,
    totalConsidered,
  };
}

/**
 * Compute the lookback window needed to cover all pending bets.
 * Uses the oldest pending bet's commence time, minimum 3 days.
 */
function getLookbackDays(pending: AutoBet[]): number {
  if (pending.length === 0) return 3;
  const now = Date.now();
  let oldest = now;
  for (const bet of pending) {
    const t = new Date(bet.commenceTime).getTime();
    if (!isNaN(t) && t < oldest) oldest = t;
  }
  const daysSinceOldest = Math.ceil((now - oldest) / (24 * 60 * 60 * 1000));
  return Math.max(3, daysSinceOldest + 1); // +1 buffer
}

/**
 * Settle pending bets using the scores API.
 *
 * Fixes applied:
 * - Dynamic lookback window based on oldest pending bet (not hardcoded 3 days)
 * - Three-way sports (MLS): draw = loss for home/away picks
 */
export async function settleBets(state: AutoBetState): Promise<{
  newState: AutoBetState;
  settled: number;
  apiCalls: number;
}> {
  const pending = state.bets.filter(b => b.status === 'pending');
  if (pending.length === 0) return { newState: state, settled: 0, apiCalls: 0 };

  const sportsNeeded = [...new Set(pending.map(b => b.sport))];
  const lookbackDays = getLookbackDays(pending);

  let apiCalls = 0;
  const allScores: GameScore[] = [];

  for (const sport of sportsNeeded) {
    try {
      const scores = await fetchScoresForSport(sport, lookbackDays);
      apiCalls++;
      allScores.push(...scores);
    } catch {
      // Skip on error
    }
  }

  const scoreMap = new Map(allScores.map(s => [s.id, s]));
  let bankroll = state.bankroll;
  let settledCount = 0;

  const updatedBets = state.bets.map(bet => {
    if (bet.status !== 'pending') return bet;

    const score = scoreMap.get(bet.gameId);
    if (!score || !score.completed || !score.scores) return bet;

    const homeScore = score.scores.find(s => s.name === score.home_team);
    const awayScore = score.scores.find(s => s.name === score.away_team);

    if (!homeScore || !awayScore) return bet;

    const homePoints = parseFloat(homeScore.score);
    const awayPoints = parseFloat(awayScore.score);

    if (isNaN(homePoints) || isNaN(awayPoints)) return bet;

    // Determine outcome
    if (homePoints === awayPoints) {
      if (THREE_WAY_SPORTS.has(bet.sport)) {
        // Three-way market: draw is a distinct outcome, not a push.
        // If you bet Home or Away, you lose on a draw.
        if (bet.selection === 'Draw') {
          bankroll += bet.potentialPayout;
          settledCount++;
          return { ...bet, status: 'won' as const, settledAt: new Date().toISOString(), payout: bet.potentialPayout };
        }
        settledCount++;
        return { ...bet, status: 'lost' as const, settledAt: new Date().toISOString(), payout: 0 };
      }
      // Two-way sport: tie = push
      bankroll += bet.stake;
      settledCount++;
      return { ...bet, status: 'push' as const, settledAt: new Date().toISOString(), payout: bet.stake };
    }

    const winner = homePoints > awayPoints ? score.home_team : score.away_team;

    if (bet.selection === winner) {
      const payout = bet.potentialPayout;
      bankroll += payout;
      settledCount++;
      return { ...bet, status: 'won' as const, settledAt: new Date().toISOString(), payout };
    } else {
      settledCount++;
      return { ...bet, status: 'lost' as const, settledAt: new Date().toISOString(), payout: 0 };
    }
  });

  bankroll = Math.round(bankroll * 100) / 100;

  const newState: AutoBetState = {
    ...state,
    bets: updatedBets,
    bankroll,
    bankrollHistory: settledCount > 0
      ? [...state.bankrollHistory, { date: new Date().toISOString(), balance: bankroll }]
      : state.bankrollHistory,
    totalApiCalls: state.totalApiCalls + apiCalls,
  };

  return { newState, settled: settledCount, apiCalls };
}

/**
 * Compute stats from auto-bet history.
 */
export function computeStats(state: AutoBetState) {
  const settled = state.bets.filter(b => b.status !== 'pending');
  const wins = settled.filter(b => b.status === 'won').length;
  const losses = settled.filter(b => b.status === 'lost').length;
  const pushes = settled.filter(b => b.status === 'push').length;
  const pending = state.bets.filter(b => b.status === 'pending').length;

  const totalStaked = settled.reduce((sum, b) => sum + b.stake, 0);
  const totalPayout = settled.reduce((sum, b) => sum + b.payout, 0);
  const netProfit = totalPayout - totalStaked;
  const roi = totalStaked > 0 ? (netProfit / totalStaked) * 100 : 0;
  const winRate = settled.length > 0 ? (wins / settled.length) * 100 : 0;

  const growth = state.bankroll - state.initialBankroll;
  const growthPercent = state.initialBankroll > 0
    ? (growth / state.initialBankroll) * 100 : 0;

  return {
    totalBets: state.bets.length,
    settled: settled.length,
    wins,
    losses,
    pushes,
    pending,
    totalStaked: Math.round(totalStaked * 100) / 100,
    totalPayout: Math.round(totalPayout * 100) / 100,
    netProfit: Math.round(netProfit * 100) / 100,
    roi: Math.round(roi * 100) / 100,
    winRate: Math.round(winRate * 10) / 10,
    growth: Math.round(growth * 100) / 100,
    growthPercent: Math.round(growthPercent * 100) / 100,
  };
}
