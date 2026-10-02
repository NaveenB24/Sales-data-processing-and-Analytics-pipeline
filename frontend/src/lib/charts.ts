/**
 * Chart theming. Recharts needs literal colour values, so we read the CSS
 * custom properties from :root at runtime — that way the charts follow the
 * same tokens as the rest of the UI and flip with the OS colour scheme.
 */

import { useEffect, useState } from 'react'

export interface ChartPalette {
  series: string[]
  grid: string
  axis: string
  text: string
  surface: string
  border: string
}

const FALLBACK: ChartPalette = {
  series: ['#2f58cd', '#0d8f8f', '#b4751f', '#8347c4', '#19844f', '#c04367'],
  grid: '#e4e7ec',
  axis: '#767d8d',
  text: '#16191f',
  surface: '#ffffff',
  border: '#e2e5ea',
}

function readPalette(): ChartPalette {
  if (typeof window === 'undefined') return FALLBACK
  const styles = window.getComputedStyle(document.documentElement)
  const token = (name: string, fallback: string) =>
    styles.getPropertyValue(name).trim() || fallback

  return {
    series: [1, 2, 3, 4, 5, 6].map((index) =>
      token(`--chart-${index}`, FALLBACK.series[index - 1]),
    ),
    grid: token('--chart-grid', FALLBACK.grid),
    axis: token('--chart-axis', FALLBACK.axis),
    text: token('--text', FALLBACK.text),
    surface: token('--surface', FALLBACK.surface),
    border: token('--border', FALLBACK.border),
  }
}

/** Re-reads the tokens when the OS switches between light and dark. */
export function useChartPalette(): ChartPalette {
  const [palette, setPalette] = useState<ChartPalette>(() => readPalette())

  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const refresh = () => setPalette(readPalette())
    refresh()
    query.addEventListener('change', refresh)
    return () => query.removeEventListener('change', refresh)
  }, [])

  return palette
}

/** Deterministic series colour so a region keeps its colour across charts. */
export function seriesColor(palette: ChartPalette, index: number): string {
  return palette.series[index % palette.series.length]
}

/** Tooltip chrome shared by every chart. */
export function tooltipStyles(palette: ChartPalette) {
  return {
    contentStyle: {
      background: palette.surface,
      border: `1px solid ${palette.border}`,
      borderRadius: 8,
      boxShadow: '0 4px 14px rgb(15 23 42 / 0.12)',
      fontSize: 13,
      padding: '8px 10px',
    },
    labelStyle: { color: palette.text, fontWeight: 600, marginBottom: 2 },
    itemStyle: { color: palette.text },
    cursor: { fill: palette.grid, fillOpacity: 0.45 },
  }
}
