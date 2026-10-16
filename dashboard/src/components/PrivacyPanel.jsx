/**
 * What the platform actually guarantees, stated without overclaiming.
 *
 * A dashboard that prints "differentially private" beside a green tick and stops
 * there is worse than one with no privacy panel at all. This one shows the
 * mechanism, the parameters, the resulting epsilon, and says plainly when that
 * epsilon is too large to mean much.
 */

function Row({ term, children }) {
  return (
    <>
      <dt>{term}</dt>
      <dd>{children}</dd>
    </>
  );
}

export default function PrivacyPanel({ model }) {
  const privacy = model?.privacy;

  if (!privacy) {
    return (
      <div className="card">
        <h2>Privacy</h2>
        <p className="subtitle">No model has been published yet.</p>
      </div>
    );
  }

  const disabled = privacy.mechanism === "none";
  const epsilon = privacy.epsilon;
  // Below about 10 the budget is in the range research papers treat as
  // meaningful. Above it, the noise is real but the formal guarantee is weak.
  const meaningful = typeof epsilon === "number" && epsilon <= 10;

  return (
    <div className="card">
      <h2>Privacy</h2>
      <p className="subtitle">Applied by the aggregator, before any checkpoint is written.</p>

      <span className={`pill ${disabled ? "warn" : meaningful ? "good" : "warn"}`}>
        <span className="dot" />
        {disabled ? "differential privacy off" : meaningful ? "budget is meaningful" : "noise applied, budget is loose"}
      </span>

      <dl className="hospital" style={{ display: "grid", gridTemplateColumns: "auto auto", gap: "4px 12px", marginTop: 14, fontSize: 13 }}>
        <Row term="Mechanism">{disabled ? "none" : "clip then Gaussian noise"}</Row>
        <Row term="Clipping norm">{privacy.clipping_norm}</Row>
        <Row term="Noise multiplier">{privacy.noise_multiplier}</Row>
        <Row term="Rounds">{privacy.rounds}</Row>
        <Row term="Delta">{privacy.delta}</Row>
        <Row term="Epsilon">
          {typeof epsilon === "number" ? epsilon.toFixed(1) : "unbounded"}
        </Row>
      </dl>

      {!disabled && !meaningful ? (
        <div className="callout">
          This epsilon is large. With three participants all taking part in every round there is no
          subsampling amplification, so a noise level low enough to keep accuracy usable cannot buy
          a tight budget. The clipping and noise still blunt the memorisation of any single
          patient, but the formal guarantee is weak and should be reported as such. A real
          deployment fixes this with more participating sites, not with a bigger number here.
        </div>
      ) : null}

      {disabled ? (
        <div className="callout">
          Differential privacy is switched off for this run. Weight updates leave each hospital
          unclipped and unnoised, which is the correct configuration for measuring the accuracy
          ceiling and the wrong one for anything else.
        </div>
      ) : null}

      <details>
        <summary>What protects the data even without a tight epsilon</summary>
        <ul style={{ marginTop: 8, paddingLeft: 20, color: "var(--text-secondary)", fontSize: 13 }}>
          <li>Images never leave the hospital container. Only weight arrays cross the network.</li>
          <li>Each hospital reads one bucket, its own. There is no pooled image store to breach.</li>
          <li>The training channel is encrypted and the hospitals pin the aggregator certificate.</li>
          <li>Uploaded X-rays are classified in memory; the audit trail keeps a hash, not the image.</li>
        </ul>
      </details>
    </div>
  );
}
