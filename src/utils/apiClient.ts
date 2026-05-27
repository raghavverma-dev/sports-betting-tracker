/**
 * Thin fetch wrapper for the BetEdge FastAPI backend.
 *
 * Keeps URL assembly + error handling in one place so pages/components
 * don't repeat try/catch + response.ok checks everywhere.
 */

const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000';

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* non-JSON response */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};

// ============ Typed endpoints ============

export interface BacktestRunSummary {
  id: number;
  strategy: string;
  sport: string;
  market: string;
  start_date: string;
  end_date: string;
  started_at: string;
  finished_at: string | null;
  games_evaluated: number;
  bets_placed: number;
  brier_score: number | null;
  log_loss: number | null;
  initial_bankroll: number;
  final_bankroll: number | null;
  roi: number | null;
  max_drawdown: number | null;
}

export interface CalibrationBin {
  bin_lower: number;
  bin_upper: number;
  predicted_mean: number;
  empirical_mean: number;
  count: number;
}

export interface BacktestRunDetail extends BacktestRunSummary {
  calibration: CalibrationBin[] | null;
  equity_curve: [string, number][] | null;
}

export interface BacktestRequest {
  strategy: 'market-baseline' | 'flat-ev-threshold' | 'kelly-ev-threshold';
  sport?: string;
  market?: 'h2h';
  initial_bankroll?: number;
  min_ev?: number;
  kelly_fraction?: number;
  max_stake_percent?: number;
}

export async function listBacktestRuns(limit = 25): Promise<BacktestRunSummary[]> {
  return api.get(`/backtest/runs?limit=${limit}`);
}

export async function createBacktestRun(req: BacktestRequest): Promise<BacktestRunDetail> {
  return api.post('/backtest/runs', req);
}

export async function getBacktestRun(id: number): Promise<BacktestRunDetail> {
  return api.get(`/backtest/runs/${id}`);
}

export async function health(): Promise<{ status: string; version: string }> {
  return api.get('/health');
}

// ============ Live odds endpoints ============

interface BackendBookOdds {
  book: string;
  odds: number;
  last_update: string | null;
}

interface BackendRankedBet {
  id: string;
  game_id: string;
  sport: string;
  event: string;
  commence_time: string;
  selection: string;
  bet_type: string;
  best_odds: number;
  best_book: string;
  avg_odds: number;
  market_probability: number;
  implied_probability: number;
  ev: number;
  num_books: number;
  all_books: BackendBookOdds[];
  stale_warning: boolean;
  outlier_warning: boolean;
  stale_minutes: number;
  adjusted_ev: number | null;
  adjusted_best_odds: number | null;
  adjusted_best_book: string | null;
  adjusted_market_probability: number | null;
}

export interface RankedOddsBet {
  id: string;
  gameId: string;
  sport: string;
  event: string;
  commenceTime: string;
  selection: string;
  betType: string;
  bestOdds: number;
  bestBook: string;
  avgOdds: number;
  marketProbability: number;
  impliedProbability: number;
  ev: number;
  numBooks: number;
  allBookOdds: { book: string; odds: number; lastUpdate: string | null }[];
  staleWarning: boolean;
  outlierWarning: boolean;
  staleMinutes: number;
  adjustedEv: number | null;
  adjustedBestOdds: number | null;
  adjustedBestBook: string | null;
  adjustedMarketProbability: number | null;
}

function toRankedOddsBet(bet: BackendRankedBet): RankedOddsBet {
  return {
    id: bet.id,
    gameId: bet.game_id,
    sport: bet.sport,
    event: bet.event,
    commenceTime: bet.commence_time,
    selection: bet.selection,
    betType: bet.bet_type,
    bestOdds: bet.best_odds,
    bestBook: bet.best_book,
    avgOdds: bet.avg_odds,
    marketProbability: bet.market_probability,
    impliedProbability: bet.implied_probability,
    ev: bet.ev,
    numBooks: bet.num_books,
    allBookOdds: bet.all_books.map(book => ({
      book: book.book,
      odds: book.odds,
      lastUpdate: book.last_update,
    })),
    staleWarning: bet.stale_warning,
    outlierWarning: bet.outlier_warning,
    staleMinutes: bet.stale_minutes,
    adjustedEv: bet.adjusted_ev,
    adjustedBestOdds: bet.adjusted_best_odds,
    adjustedBestBook: bet.adjusted_best_book,
    adjustedMarketProbability: bet.adjusted_market_probability,
  };
}

export async function fetchRankedOddsForSport(
  sport: string,
  market = 'h2h',
): Promise<RankedOddsBet[]> {
  const params = new URLSearchParams({ sport, market });
  const ranked = await api.get<BackendRankedBet[]>(`/odds/ranked?${params.toString()}`);
  return ranked.map(toRankedOddsBet);
}
