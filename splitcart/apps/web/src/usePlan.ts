import { useEffect, useRef, useState } from 'react';
import type { Basket, PlanResult, Preferences } from '@splitcart/engine';

type Status = { kind: 'idle' } | { kind: 'solving' } | { kind: 'ready'; plan: PlanResult } | { kind: 'error'; message: string };

/** Re-plans in a Web Worker whenever the basket or preferences change, keeping the last good plan on screen. */
export function usePlan(basket: Basket, prefs: Preferences) {
  const worker = useRef<Worker | null>(null);
  const counter = useRef(0);
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  const [plan, setPlan] = useState<PlanResult | null>(null);

  useEffect(() => {
    const w = new Worker(new URL('./solver.worker.ts', import.meta.url), { type: 'module' });
    worker.current = w;
    w.onmessage = (e: MessageEvent<{ id: number; plan?: PlanResult; error?: string }>) => {
      if (e.data.id !== counter.current) return;
      if (e.data.plan) {
        setPlan(e.data.plan);
        setStatus({ kind: 'ready', plan: e.data.plan });
      } else {
        setStatus({ kind: 'error', message: e.data.error ?? 'Unknown error' });
      }
    };
    return () => w.terminate();
  }, []);

  useEffect(() => {
    const id = ++counter.current;
    setStatus({ kind: 'solving' });
    const timer = setTimeout(() => worker.current?.postMessage({ id, basket, prefs }), 250);
    return () => clearTimeout(timer);
  }, [basket, prefs]);

  return { plan, status };
}
