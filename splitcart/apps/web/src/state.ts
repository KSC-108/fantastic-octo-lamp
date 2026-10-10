import { useEffect, useState } from 'react';
import { DEFAULT_PREFERENCES, DEFAULT_TRAITS, sampleBasket, type Basket, type Preferences } from '@splitcart/engine';

export interface AppState {
  basket: Basket;
  prefs: Preferences;
  pincode: string;
  /** Where the prices came from, shown so invented data is never mistaken for real quotes. */
  source: { kind: 'sample' | 'import' | 'manual'; label: string };
}

const KEY = 'splitcart:v1';

export function defaultState(): AppState {
  return {
    basket: sampleBasket(),
    prefs: { ...DEFAULT_PREFERENCES, traits: structuredClone(DEFAULT_TRAITS), brandTiers: {} },
    pincode: '400068',
    source: { kind: 'sample', label: 'Sample basket with invented prices' },
  };
}

function load(): AppState {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return { ...defaultState(), ...(JSON.parse(raw) as Partial<AppState>) };
  } catch {
    // Storage can be unavailable (private mode); fall back to defaults.
  }
  return defaultState();
}

export function useAppState() {
  const [state, setState] = useState<AppState>(load);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(state));
    } catch {
      // Ignore quota or privacy-mode errors; the app still works for this session.
    }
  }, [state]);
  return [state, setState] as const;
}

export type SetState = ReturnType<typeof useAppState>[1];
