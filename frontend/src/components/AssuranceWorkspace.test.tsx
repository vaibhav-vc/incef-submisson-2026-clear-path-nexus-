import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import AssuranceWorkspace from './AssuranceWorkspace'

describe('AssuranceWorkspace', () => {
  it('renders the judge-facing trust boundary before any API data arrives', () => {
    const markup = renderToStaticMarkup(<AssuranceWorkspace />)

    expect(markup).toContain('Evidence Assurance')
    expect(markup).toContain('authenticated stored evidence')
    expect(markup).toContain('Non-vital research boundary')
    expect(markup).toContain('not movement authority')
    expect(markup).toContain('Loading stored cases')
  })
})
