import { createHighsSolver, type Solver } from '../src/index.ts';

let solverPromise: Promise<Solver> | null = null;
export function getSolver(): Promise<Solver> {
  solverPromise ??= createHighsSolver();
  return solverPromise;
}
