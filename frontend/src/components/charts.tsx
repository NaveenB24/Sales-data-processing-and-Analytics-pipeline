/**
 * Report charts. Each one pairs the visualisation with a disclosure containing
 * the same numbers as a real table, so the data is reachable without reading
 * colour or hovering a tooltip.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { BreakdownItem, TrendPoint } from '../api/types'
import { seriesColor, tooltipStyles, useChartPalette } from '../lib/charts'
import {
  formatCurrency,
  formatCurrencyCompact,
  formatDelta,
  formatNumber,
  formatPercent,
} from '../lib/format'
import { DataTable, TableWrap, Td, Th } from './Table'
import { EmptyState } from './EmptyState'
import { ChartIcon } from './icons'

const toNumber = (value: unknown): number => {
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : 0
}

function ChartEmpty({ label }: { label: string }) {
  return <EmptyState title={label} icon={<ChartIcon size={18} />} body="No valid rows contributed to this breakdown yet." />
}

/* -------------------------------------------------- revenue by region (bar) */

export function RevenueByRegionChart({ data }: { data: BreakdownItem[] }) {
  const palette = useChartPalette()
  const tip = tooltipStyles(palette)

  if (data.length === 0) return <ChartEmpty label="No revenue by region" />

  const summary = `Bar chart of net revenue by region. ${data
    .slice(0, 5)
    .map((item) => `${item.key}: ${formatCurrency(item.revenue)}`)
    .join('; ')}.`

  return (
    <div className="chart">
      <div className="chart__canvas" role="img" aria-label={summary}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={palette.grid} vertical={false} />
            <XAxis
              dataKey="key"
              stroke={palette.axis}
              tick={{ fill: palette.axis, fontSize: 12 }}
              tickLine={false}
              axisLine={{ stroke: palette.grid }}
              interval={0}
              height={44}
            />
            <YAxis
              stroke={palette.axis}
              tick={{ fill: palette.axis, fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              width={72}
              tickFormatter={(value: unknown) => formatCurrencyCompact(toNumber(value))}
            />
            <Tooltip
              {...tip}
              formatter={(value: unknown) => [formatCurrency(toNumber(value)), 'Net revenue']}
            />
            <Bar dataKey="revenue" radius={[4, 4, 0, 0]} maxBarSize={56}>
              {data.map((item, index) => (
                <Cell key={item.key} fill={seriesColor(palette, index)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <BreakdownDisclosure data={data} keyLabel="Region" />
    </div>
  )
}

/* ----------------------------------------------- revenue by category (pie) */

export function RevenueByCategoryChart({ data }: { data: BreakdownItem[] }) {
  const palette = useChartPalette()
  const tip = tooltipStyles(palette)

  if (data.length === 0) return <ChartEmpty label="No revenue by category" />

  const summary = `Pie chart of net revenue share by product category. ${data
    .slice(0, 5)
    .map((item) => `${item.key}: ${formatPercent(item.share_pct)}`)
    .join('; ')}.`

  return (
    <div className="chart">
      <div className="chart__canvas" role="img" aria-label={summary}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
            <Tooltip
              {...tip}
              cursor={false}
              formatter={(value: unknown, name: unknown) => [
                formatCurrency(toNumber(value)),
                String(name),
              ]}
            />
            <Pie
              data={data}
              dataKey="revenue"
              nameKey="key"
              innerRadius="48%"
              outerRadius="78%"
              paddingAngle={1}
              stroke={palette.surface}
              strokeWidth={2}
              isAnimationActive={false}
            >
              {data.map((item, index) => (
                <Cell key={item.key} fill={seriesColor(palette, index)} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="chart__legend" aria-hidden="true">
        {data.slice(0, 8).map((item, index) => (
          <li key={item.key} className="chart__legend-item">
            <span
              className="chart__swatch"
              style={{ background: seriesColor(palette, index) }}
            />
            {item.key} · {formatPercent(item.share_pct)}
          </li>
        ))}
      </ul>
      <BreakdownDisclosure data={data} keyLabel="Category" />
    </div>
  )
}

/* ---------------------------------------------------- revenue trend (line) */

export function RevenueTrendChart({
  data,
  granularity,
}: {
  data: TrendPoint[]
  granularity: 'daily' | 'monthly'
}) {
  const palette = useChartPalette()
  const tip = tooltipStyles(palette)

  if (data.length === 0) {
    return <ChartEmpty label={`No ${granularity} trend data`} />
  }

  const summary = `Line chart of ${granularity} net revenue across ${data.length} periods, from ${
    data[0]?.period ?? '—'
  } to ${data[data.length - 1]?.period ?? '—'}.`

  return (
    <div className="chart">
      <div className="chart__canvas" role="img" aria-label={summary}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={palette.grid} vertical={false} />
            <XAxis
              dataKey="period"
              stroke={palette.axis}
              tick={{ fill: palette.axis, fontSize: 12 }}
              tickLine={false}
              axisLine={{ stroke: palette.grid }}
              minTickGap={24}
              height={44}
            />
            <YAxis
              stroke={palette.axis}
              tick={{ fill: palette.axis, fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              width={72}
              tickFormatter={(value: unknown) => formatCurrencyCompact(toNumber(value))}
            />
            <Tooltip
              {...tip}
              cursor={{ stroke: palette.axis, strokeDasharray: '3 3' }}
              formatter={(value: unknown) => [formatCurrency(toNumber(value)), 'Net revenue']}
              labelFormatter={(label: unknown) => String(label)}
            />
            <Line
              type="monotone"
              dataKey="revenue"
              stroke={seriesColor(palette, 0)}
              strokeWidth={2}
              dot={{ r: 2.5, fill: seriesColor(palette, 0), strokeWidth: 0 }}
              activeDot={{ r: 5 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <details className="chart__data">
        <summary>View {granularity} trend as a table</summary>
        <TableWrap label="Revenue trend figures">
          <DataTable
            embedded
            head={
              <>
                <Th>Period</Th>
                <Th numeric>Net revenue</Th>
                <Th numeric>Transactions</Th>
                <Th numeric>Change</Th>
              </>
            }
          >
            {data.map((point) => (
              <tr key={point.period}>
                <Td>{point.period}</Td>
                <Td numeric>{formatCurrency(point.revenue)}</Td>
                <Td numeric>{formatNumber(point.transactions)}</Td>
                <Td numeric>{formatDelta(point.change_pct)}</Td>
              </tr>
            ))}
          </DataTable>
        </TableWrap>
      </details>
    </div>
  )
}

/* ------------------------------------------------------------- shared bits */

function BreakdownDisclosure({
  data,
  keyLabel,
}: {
  data: BreakdownItem[]
  keyLabel: string
}) {
  return (
    <details className="chart__data">
      <summary>View {keyLabel.toLowerCase()} figures as a table</summary>
      <TableWrap label={`${keyLabel} revenue figures`}>
        <DataTable
          embedded
          head={
            <>
              <Th>{keyLabel}</Th>
              <Th numeric>Net revenue</Th>
              <Th numeric>Transactions</Th>
              <Th numeric>Share</Th>
            </>
          }
        >
          {data.map((item) => (
            <tr key={item.key}>
              <Td>{item.key}</Td>
              <Td numeric>{formatCurrency(item.revenue)}</Td>
              <Td numeric>{formatNumber(item.transactions)}</Td>
              <Td numeric>{formatPercent(item.share_pct)}</Td>
            </tr>
          ))}
        </DataTable>
      </TableWrap>
    </details>
  )
}
