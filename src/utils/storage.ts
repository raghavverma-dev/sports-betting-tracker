import type { AppState } from '../types';

const STORAGE_KEY = 'sports-betting-tracker';

function defaultState(): AppState {
  return {
    bets: [],
    bankroll: 1000,
    initialBankroll: 1000,
    bankrollHistory: [{ date: new Date().toISOString(), balance: 1000 }],
  };
}

export function loadState(): AppState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultState();
    return JSON.parse(raw) as AppState;
  } catch {
    return defaultState();
  }
}

export function saveState(state: AppState): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}
