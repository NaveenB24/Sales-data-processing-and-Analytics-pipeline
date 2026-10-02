import type { ReactNode, ThHTMLAttributes, TdHTMLAttributes } from 'react'

/** Horizontal scroll container — keeps wide tables usable at 390px. */
export function TableWrap({
  children,
  label = 'Data table',
}: {
  children: ReactNode
  /** Names the scrollable region for screen readers. */
  label?: string
}) {
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={`${label}, scrollable`}>
      {children}
    </div>
  )
}

export interface DataTableProps {
  caption?: ReactNode
  head: ReactNode
  children: ReactNode
  embedded?: boolean
}

export function DataTable({ caption, head, children, embedded = false }: DataTableProps) {
  return (
    <table className={embedded ? 'table table--embedded' : 'table'}>
      {caption ? <caption>{caption}</caption> : null}
      <thead>
        <tr>{head}</tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  )
}

export interface ThProps extends ThHTMLAttributes<HTMLTableCellElement> {
  numeric?: boolean
}

export function Th({ numeric = false, className, children, ...rest }: ThProps) {
  return (
    <th scope="col" className={[numeric ? 'num' : '', className].filter(Boolean).join(' ')} {...rest}>
      {children}
    </th>
  )
}

export interface TdProps extends TdHTMLAttributes<HTMLTableCellElement> {
  numeric?: boolean
  wrap?: boolean
}

export function Td({ numeric = false, wrap = false, className, children, ...rest }: TdProps) {
  return (
    <td
      className={[numeric ? 'num' : '', wrap ? 'wrap' : '', className].filter(Boolean).join(' ')}
      {...rest}
    >
      {children}
    </td>
  )
}
