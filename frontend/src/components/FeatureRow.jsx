import { FEATURES } from '../constants'

export default function FeatureRow() {
  return (
    <ul className="feature-row">
      {FEATURES.map((f) => (
        <li key={f.title}>
          <div className="feat-text">
            <strong>{f.title}</strong>
            <span>{f.desc}</span>
          </div>
        </li>
      ))}
    </ul>
  )
}
