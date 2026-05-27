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
