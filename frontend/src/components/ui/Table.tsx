import type {
  HTMLAttributes,
  TdHTMLAttributes,
  ThHTMLAttributes,
} from 'react';

/**
 * Thin styled table primitives. `Table` wraps the element in a horizontal
 * scroll container so wide tables stay usable on narrow viewports. Compose
 * with the head/body/row/cell pieces below — same semantic structure as a
 * plain table, consistent spacing + dividers, theme-aware.
 */
export function Table({ className = '', children, ...rest }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className={['w-full border-collapse text-sm', className].filter(Boolean).join(' ')} {...rest}>
        {children}
      </table>
    </div>
  );
}

export function TableHead({ className = '', children, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead className={className} {...rest}>
      {children}
    </thead>
  );
}

export function TableBody({ className = '', children, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <tbody className={className} {...rest}>
      {children}
    </tbody>
  );
}

export function TableRow({ className = '', children, ...rest }: HTMLAttributes<HTMLTableRowElement>) {
  const classes = ['border-b border-subtle last:border-0', className].filter(Boolean).join(' ');
  return (
    <tr className={classes} {...rest}>
      {children}
    </tr>
  );
}

export function TableHeaderCell({ className = '', children, ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  const classes = [
    'px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-subtle',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <th className={classes} {...rest}>
      {children}
    </th>
  );
}

export function TableCell({ className = '', children, ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  const classes = ['px-3 py-2.5 align-middle text-ink', className].filter(Boolean).join(' ');
  return (
    <td className={classes} {...rest}>
      {children}
    </td>
  );
}
