/**
 * The Odds API HTTP client.
 * Handles API key management, quota checks, and raw data fetching.
 * No business logic (de-vigging, ranking) lives here.
 */

const BASE_URL = 'https://api.the-odds-api.com/v4';

// Maps our Sport type to The Odds API sport keys.
export const SPORT_KEY_MAP: Record<string, string> = {
  NBA: 'basketball_nba',
  NFL: 'americanfootball_nfl',
  MLB: 'baseball_mlb',
  NHL: 'icehockey_nhl',
  NCAAF: 'americanfootball_ncaaf',
  NCAAB: 'basketball_ncaab',
  MLS: 'soccer_usa_mls',
  UFC: 'mma_mixed_martial_arts',
};

export const SUPPORTED_SPORTS = Object.keys(SPORT_KEY_MAP);

// ======= Types =======

export interface OddsOutcome {
  name: string;
  price: number;
  point?: number;
}

export interface OddsMarket {
  key: string;
  outcomes: OddsOutcome[];
}

export interface BookmakerOdds {
  key: string;
  title: string;
  last_update: string;
  markets: OddsMarket[];
}

export interface GameOdds {
  id: string;
  sport_key: string;
  sport_title: string;
  commence_time: string;
  home_team: string;
  away_team: string;
  bookmakers: BookmakerOdds[];
}

export interface GameScore {
  id: string;
  sport_key: string;
  sport_title: string;
  commence_time: string;
  home_team: string;
  away_team: string;
  completed: boolean;
  scores: { name: string; score: string }[] | null;
}

export interface ApiQuota {
  used: number;
  remaining: number;
}

// ======= API Key =======

function getApiKey(): string | null {
  return localStorage.getItem('odds-api-key');
}

export function setApiKey(key: string): void {
  localStorage.setItem('odds-api-key', key);
}

export function getStoredApiKey(): string | null {
  return getApiKey();
}

// ======= Quota =======

export async function checkApiQuota(): Promise<ApiQuota> {
  const apiKey = getApiKey();
  if (!apiKey) throw new Error('No API key set.');

  const res = await fetch(`${BASE_URL}/sports/?apiKey=${encodeURIComponent(apiKey)}`);

  const usedHeader = res.headers.get('x-requests-used');
  const remainingHeader = res.headers.get('x-requests-remaining');

  if (usedHeader != null && remainingHeader != null) {
    return { used: parseInt(usedHeader, 10), remaining: parseInt(remainingHeader, 10) };
  }

  if (res.status === 401) throw new Error('Invalid API key.');
  if (res.status === 429) return { used: -1, remaining: 0 };
  if (!res.ok) throw new Error(`API error: ${res.status}`);

  return { used: -1, remaining: -1 };
}

// ======= Odds Fetching =======

export async function fetchOddsForSport(sport: string, markets: string = 'h2h'): Promise<GameOdds[]> {
  const apiKey = getApiKey();
  if (!apiKey) throw new Error('No API key set. Get a free key at the-odds-api.com.');

  const sportKey = SPORT_KEY_MAP[sport];
  if (!sportKey) throw new Error(`Unsupported sport: ${sport}`);

  const url = `${BASE_URL}/sports/${sportKey}/odds/`
    + `?apiKey=${encodeURIComponent(apiKey)}`
    + `&regions=us`
    + `&markets=${markets}`
    + `&oddsFormat=american`;
  const res = await fetch(url);

  if (!res.ok) {
    if (res.status === 401) throw new Error('Invalid API key. Check your key at the-odds-api.com.');
    if (res.status === 429) throw new Error('API rate limit reached. Free tier allows 500 requests/month.');
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }

  return res.json();
}

// ======= Scores Fetching =======

export async function fetchScoresForSport(sport: string, daysFrom: number = 1): Promise<GameScore[]> {
  const apiKey = getApiKey();
  if (!apiKey) throw new Error('No API key set.');

  const sportKey = SPORT_KEY_MAP[sport];
  if (!sportKey) throw new Error(`Unsupported sport: ${sport}`);

  const url = `${BASE_URL}/sports/${sportKey}/scores/`
    + `?apiKey=${encodeURIComponent(apiKey)}`
    + `&daysFrom=${daysFrom}`;
  const res = await fetch(url);

  if (!res.ok) {
    if (res.status === 401) throw new Error('Invalid API key.');
    if (res.status === 429) throw new Error('API rate limit reached.');
    throw new Error(`Scores API error: ${res.status}`);
  }

  return res.json();
}
