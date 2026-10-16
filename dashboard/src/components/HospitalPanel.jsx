/**
 * One card per participating site.
 *
 * The class-balance bar is the point of this panel. It shows at a glance that
 * the three hospitals hold very different populations, which is what makes the
 * federated problem hard and what a pooled dataset would hide.
 */

const SERIES_COLORS = ["var(--series-2)", "var(--series-3)", "var(--series-4)"];

function ClassBalanceBar({ counts, total }) {
  const normal = counts.normal || 0;
  const pneumonia = counts.pneumonia || 0;
  const denominator = total || normal + pneumonia || 1;
  const normalShare = (normal / denominator) * 100;

  return (
    <div style={{ marginTop: 12 }}>
      <div
        style={{
          display: "flex",
          height: 10,
          borderRadius: 5,
          overflow: "hidden",
          background: "var(--gridline)",
          // A 2px gap between adjacent fills, drawn in the surface colour.
          gap: 2,
        }}
        role="img"
        aria-label={`${normal} normal and ${pneumonia} pneumonia images`}
      >
        <div style={{ width: `${normalShare}%`, background: "var(--series-1)" }} />
        <div style={{ flex: 1, background: "var(--series-2)" }} />
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 12,
          color: "var(--text-secondary)",
          marginTop: 5,
        }}
      >
        <span>{normal.toLocaleString()} normal</span>
        <span>{pneumonia.toLocaleString()} pneumonia</span>
      </div>
    </div>
  );
}

export default function HospitalPanel({ partition, latestRound }) {
  const hospitals = partition?.hospitals || [];

  if (!hospitals.length) {
    return (
      <div className="card">
        <h2>Participating hospitals</h2>
        <p className="subtitle">
          The partition manifest was not published with this build, so only the counts reported
          during training are available.
        </p>
        <div className="grid hospitals">
          {(latestRound?.hospitals || []).map((entry, index) => (
            <div className="card hospital" key={entry.hospital_id}>
              <div className="name">
                <span className="marker" style={{ background: SERIES_COLORS[index % 3] }} />
                Hospital {String(entry.hospital_id).toUpperCase()}
              </div>
              <dl>
                <dt>Training images</dt>
                <dd>{Number(entry.examples).toLocaleString()}</dd>
                <dt>Local accuracy</dt>
                <dd>{(Number(entry.train_accuracy) * 100).toFixed(1)}%</dd>
              </dl>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Participating hospitals</h2>
      <p className="subtitle">
        Split with {partition.strategy}. Each site keeps its own images and sends only weights.
      </p>

      <div className="grid hospitals">
        {hospitals.map((hospital, index) => {
          const live = (latestRound?.hospitals || []).find(
            (entry) => String(entry.hospital_id) === String(hospital.hospital_id),
          );
          return (
            <div className="card hospital" key={hospital.hospital_id}>
              <div className="name">
                <span className="marker" style={{ background: SERIES_COLORS[index % 3] }} />
                Hospital {String(hospital.hospital_id).toUpperCase()}
              </div>

              <ClassBalanceBar counts={hospital.class_counts} total={hospital.examples} />

              <dl>
                <dt>Images held</dt>
                <dd>{hospital.examples.toLocaleString()}</dd>
                <dt>Pneumonia share</dt>
                <dd>{(hospital.pneumonia_ratio * 100).toFixed(1)}%</dd>
                <dt>Shard size</dt>
                <dd>{hospital.size_mb} MB</dd>
                {live ? (
                  <>
                    <dt>Last local accuracy</dt>
                    <dd>{(Number(live.train_accuracy) * 100).toFixed(1)}%</dd>
                    <dt>Last round time</dt>
                    <dd>{Number(live.local_seconds).toFixed(1)}s</dd>
                  </>
                ) : null}
              </dl>
            </div>
          );
        })}
      </div>

      <div className="callout">
        Hospital shares differ by an order of magnitude and their pneumonia rates differ by more
        than sixty points. Averaging models across sites this unbalanced is the whole difficulty
        of federated learning, and it is why the global curve lags a pooled baseline.
      </div>
    </div>
  );
}
