import loadHighs from 'highs';

export interface SolveResult {
  status: 'optimal' | 'infeasible' | 'error';
  objective: number;
  values: Record<string, number>;
  message?: string;
}

export interface Solver {
  solve(lp: string): SolveResult;
}

/** Loads HiGHS (WebAssembly). In a browser, pass `locateFile` pointing at the bundled highs.wasm. */
export async function createHighsSolver(options?: { locateFile?: (file: string) => string }): Promise<Solver> {
  const highs = await loadHighs(options);
  return {
    solve(lp: string): SolveResult {
      try {
        const r = highs.solve(lp, { output_flag: false, mip_rel_gap: 0, time_limit: 20 });
        if (r.Status === 'Optimal') {
          const values: Record<string, number> = {};
          for (const [name, col] of Object.entries(r.Columns)) values[name] = (col as { Primal: number }).Primal;
          return { status: 'optimal', objective: r.ObjectiveValue, values };
        }
        if (r.Status === 'Infeasible') return { status: 'infeasible', objective: NaN, values: {} };
        return { status: 'error', objective: NaN, values: {}, message: r.Status };
      } catch (err) {
        return { status: 'error', objective: NaN, values: {}, message: String(err) };
      }
    },
  };
}
