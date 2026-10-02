import { Link } from 'react-router-dom'

import { Button } from '../components/Button'
import { Card } from '../components/Card'

export default function NotFoundPage() {
  return (
    <Card>
      <div className="stack">
        <div>
          <p className="stat__label">Error 404</p>
          <h1>This page does not exist</h1>
        </div>
        <p className="muted">
          The link may be out of date, or the job it pointed at has been deleted.
        </p>
        <div className="row">
          <Link to="/" className="btn btn--primary">
            Back to the dashboard
          </Link>
          <Button onClick={() => window.history.back()}>Go back</Button>
        </div>
      </div>
    </Card>
  )
}
