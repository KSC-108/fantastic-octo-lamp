const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 });

/** Whole rupees for headline figures; paise only when they matter. */
export function rs(n: number): string {
  return Number.isInteger(Math.round(n * 100) / 100) ? inr.format(n) : inr2.format(n);
}

export function signedRs(n: number): string {
  if (Math.abs(n) < 0.005) return rs(0);
  return `${n > 0 ? '+' : '−'}${rs(Math.abs(n))}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
