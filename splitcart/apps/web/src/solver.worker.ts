/// <reference lib="webworker" />
import wasmUrl from 'highs/runtime?url';
import { createHighsSolver, optimise, PlanError, type Basket, type Preferences, type Solver } from '@splitcart/engine';

let solver: Promise<Solver> | null = null;

self.onmessage = async (event: MessageEvent<{ id: number; basket: Basket; prefs: Preferences }>) => {
  const { id, basket, prefs } = event.data;
  try {
    solver ??= createHighsSolver({ locateFile: () => wasmUrl });
    const plan = optimise(basket, prefs, await solver);
    self.postMessage({ id, plan });
  } catch (err) {
    const message = err instanceof PlanError ? err.message : `Unexpected error: ${String(err)}`;
    self.postMessage({ id, error: message });
  }
};
