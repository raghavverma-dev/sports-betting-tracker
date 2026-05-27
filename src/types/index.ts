export type Sport = 'NBA' | 'NFL' | 'MLB' | 'NHL' | 'NCAAF' | 'NCAAB' | 'MLS' | 'UFC';

export type BetType = 'moneyline' | 'spread' | 'over_under' | 'prop' | 'parlay' | 'teaser';

export type BetStatus = 'pending' | 'won' | 'lost' | 'push';

export type OddsFormat = 'american' | 'decimal' | 'fractional';

export interface Bet {
  id: string;
  sport: Sport;
  betType: BetType;
  status: BetStatus;
  event: string;
  selection: string;
  odds: number; // American odds
  stake: number;
  potentialPayout: number;
  actualPayout: number | null;
  date: string; // ISO date string
  sportsbook: string;
  notes: string;
  estimatedProbability: number | null; // Your estimated true probability (0-1)
  impliedProbability: number; // Implied probability from odds
  expectedValue: number | null; // EV percentage
  kellyStake: number | null; // Kelly criterion recommended stake
}

export interface BetFormData {
  sport: Sport;
  betType: BetType;
  event: string;
  selection: string;
  odds: number;
  stake: number;
  sportsbook: string;
  notes: string;
  estimatedProbability: number | null;
}

export interface BankrollSnapshot {
  date: string;
  balance: number;
}

export interface AppState {
  bets: Bet[];
  bankroll: number;
  initialBankroll: number;
  bankrollHistory: BankrollSnapshot[];
}

// ======= AI Auto-Bettor =======

export interface AutoBetConfig {
  enabled: boolean;
  minEv: number; // Minimum EV% to qualify (e.g. 3)
  maxEv: number; // Maximum EV% — anything above this is likely bad data, not a real edge
  kellyFraction: number; // Fraction of Kelly to use (e.g. 0.25 = quarter-Kelly)
  maxBetsPerDay: number; // Max bets placed per day
  maxStakePercent: number; // Max % of bankroll on a single bet
  sports: Sport[]; // Which sports to bet on
  skipStale: boolean; // Skip stale/outlier lines
}

export type AutoBetStatus = 'pending' | 'won' | 'lost' | 'push';

export interface AutoBet {
  id: string;
  placedAt: string; // ISO timestamp
  sport: Sport;
  event: string;
  selection: string;
  betType: string;
  odds: number; // American odds at time of placement
  book: string;
  stake: number;
  potentialPayout: number;
  ev: number; // EV% at time of placement
  kellyPercent: number; // Kelly fraction used
  status: AutoBetStatus;
  settledAt: string | null;
  payout: number; // 0 if lost, stake if push, stake+profit if won
  gameId: string; // The Odds API game ID for settlement
  commenceTime: string; // Game start time
}

export interface AutoBetState {
  config: AutoBetConfig;
  bets: AutoBet[];
  bankroll: number;
  initialBankroll: number;
  bankrollHistory: BankrollSnapshot[];
  lastRunAt: string | null;
  totalApiCalls: number; // Track API budget usage
}

export interface SportStats {
  sport: Sport;
  totalBets: number;
  wins: number;
  losses: number;
  pushes: number;
  pending: number;
  winRate: number;
  totalStaked: number;
  totalPayout: number;
  netProfit: number;
  roi: number;
  averageOdds: number;
}
