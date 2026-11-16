export const pct = (v: number | null | undefined): string =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : `${(v * 100).toFixed(1)}%`;

export const num = (v: number | null | undefined, digits = 3): string =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : v.toFixed(digits);

export const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export const asset = (path: string): string => `${basePath}${path}`;
