import { useTheme } from '../../contexts/ThemeContext';
import { Button } from '../Button';
import { Badge } from './Badge';
import { Card, CardHeader, CardTitle } from './Card';
import { EmptyState } from './EmptyState';
import { Field, Input, Textarea } from './Field';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from './Table';
import { useToast } from './Toast';

/**
 * Dev-only primitives showcase (route `/__ui`, gated to import.meta.env.DEV).
 * A lightweight Storybook substitute so the design-system primitives can be
 * eyeballed in BOTH themes before Phase 3 adopts them across real screens.
 * Not linked anywhere; never shown to end users.
 */
export function UiShowcase() {
  const { theme, toggleTheme } = useTheme();
  const { toast } = useToast();

  return (
    <div className="min-h-screen bg-canvas px-6 py-10 text-ink">
      <div className="mx-auto flex max-w-app flex-col gap-8">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold">UI primitives</h1>
            <p className="text-sm text-ink-muted">Phase 1 design system — current theme: {theme}</p>
          </div>
          <Button variant="secondary" onClick={toggleTheme}>
            Toggle theme
          </Button>
        </header>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-subtle">Badges</h2>
          <div className="flex flex-wrap gap-2">
            <Badge variant="neutral">Neutral</Badge>
            <Badge variant="primary">Primary</Badge>
            <Badge variant="success">Sent</Badge>
            <Badge variant="warning">On hold</Badge>
            <Badge variant="danger">Rejected</Badge>
            <Badge variant="info">Invited</Badge>
          </div>
        </section>

        <section className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Card</CardTitle>
              <Badge variant="success">Live</Badge>
            </CardHeader>
            <p className="text-sm text-ink-muted">
              The base surface. Header with a title and trailing action, body content below.
            </p>
          </Card>
          <Card interactive>
            <CardTitle>Interactive card</CardTitle>
            <p className="mt-2 text-sm text-ink-muted">Hover me — subtle border + surface shift.</p>
          </Card>
        </section>

        <section className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardTitle className="mb-4">Form fields</CardTitle>
            <div className="flex flex-col gap-4">
              <Field label="Email" htmlFor="demo-email" hint="We'll never share it.">
                <Input id="demo-email" type="email" placeholder="candidate@example.com" />
              </Field>
              <Field label="Notes" htmlFor="demo-notes" error="This field is required.">
                <Textarea id="demo-notes" rows={3} hasError placeholder="Add a note…" />
              </Field>
            </div>
          </Card>

          <Card>
            <CardTitle className="mb-4">Table</CardTitle>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Candidate</TableHeaderCell>
                  <TableHeaderCell>Status</TableHeaderCell>
                  <TableHeaderCell>Score</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                <TableRow>
                  <TableCell>Alice Smith</TableCell>
                  <TableCell><Badge variant="success">Shortlisted</Badge></TableCell>
                  <TableCell>8.4</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Ben Lee</TableCell>
                  <TableCell><Badge variant="warning">On hold</Badge></TableCell>
                  <TableCell>6.1</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </Card>
        </section>

        <section className="grid gap-4 sm:grid-cols-2">
          <Card padding="none">
            <EmptyState
              title="No candidates yet"
              description="Invite your first candidate and their interviews will appear here."
              action={<Button variant="primary" size="sm">Invite candidate</Button>}
            />
          </Card>
          <Card>
            <CardTitle className="mb-4">Toasts</CardTitle>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" size="sm" onClick={() => toast({ title: 'Saved', variant: 'success' })}>
                Success
              </Button>
              <Button variant="secondary" size="sm" onClick={() => toast({ title: 'Send failed', description: 'Verify your domain in Resend.', variant: 'danger' })}>
                Error
              </Button>
              <Button variant="secondary" size="sm" onClick={() => toast({ title: 'Heads up', variant: 'info' })}>
                Info
              </Button>
            </div>
          </Card>
        </section>
      </div>
    </div>
  );
}
