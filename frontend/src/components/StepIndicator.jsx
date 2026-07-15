import { STEPS } from '../constants'

export default function StepIndicator({ step }) {
  return (
    <ol className="steps">
      {STEPS.map((label, i) => {
        const n = i + 1
        const state = n === step ? 'active' : n < step ? 'done' : ''
        return (
          <li key={label} className={state}>
            <span className="step-dot">{n < step ? '✓' : n}</span>
            <span className="step-label">{label}</span>
          </li>
        )
      })}
    </ol>
  )
}
