import { useCallback, useEffect, useMemo, useState } from "react";
import AccuracyChart from "./components/AccuracyChart";
import HospitalPanel from "./components/HospitalPanel";
import PrivacyPanel from "./components/PrivacyPanel";
import PredictPanel from "./components/PredictPanel";
import ImageGalleryPanel from "./components/ImageGalleryPanel";
import { INITIAL_SAMPLE_IMAGES } from "./data/sampleImages";
import { apiBase, fetchBaseline, fetchHealth, fetchModel, fetchPartition, fetchRounds } from "./api";

const POLL_INTERVAL_MS = 5000;

function StatTile({ label, value, note }) {
  return (
    <div className="card tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {note ? <div className="note">{note}</div> : null}
    </div>
  );
}

/**
 * Pull the per-hospital training accuracy for one site out of a round record.
 * Returns null rather than zero when a site did not report, so the chart draws
 * a gap instead of a plunge to the floor.
 */
function hospitalAccuracy(round, hospitalId) {
  const entry = (round.hospitals || []).find(
    (item) => String(item.hospital_id) === String(hospitalId),
  );
  return entry ? Number(entry.train_accuracy) : null;
}

export default function App() {
  const [rounds, setRounds] = useState([]);
  const [model, setModel] = useState(null);
  const [health, setHealth] = useState(null);
  const [partition, setPartition] = useState(null);
  const [baseline, setBaseline] = useState(null);
  const [error, setError] = useState(null);
  const [live, setLive] = useState(true);
  const [loading, setLoading] = useState(true);
  const [activePredictImage, setActivePredictImage] = useState(null);

  // Load custom uploads from localStorage if available
  const [galleryImages, setGalleryImages] = useState(() => {
    try {
      const saved = localStorage.getItem("fedmed_user_uploads");
      if (saved) {
        const parsed = JSON.parse(saved);
        return [...parsed, ...INITIAL_SAMPLE_IMAGES];
      }
    } catch (e) {
      console.warn("Could not load saved uploads:", e);
    }
    return INITIAL_SAMPLE_IMAGES;
  });

  const handleAddGalleryImage = (newOrUpdated) => {
    setGalleryImages((prev) => {
      const existingIdx = prev.findIndex((img) => img.id === newOrUpdated.id);
      let updatedList;
      if (existingIdx >= 0) {
        updatedList = [...prev];
        updatedList[existingIdx] = newOrUpdated;
      } else {
        updatedList = [newOrUpdated, ...prev];
      }

      try {
        const uploadsOnly = updatedList.filter((img) => !img.isDataset);
        localStorage.setItem("fedmed_user_uploads", JSON.stringify(uploadsOnly));
      } catch (err) {
        console.warn("Failed to persist uploads to localStorage:", err);
      }
      return updatedList;
    });
  };

  const handleRemoveUpload = (id) => {
    setGalleryImages((prev) => {
      const updatedList = prev.filter((img) => img.id !== id);
      try {
        const uploadsOnly = updatedList.filter((img) => !img.isDataset);
        localStorage.setItem("fedmed_user_uploads", JSON.stringify(uploadsOnly));
      } catch (err) {
        console.warn("Failed to update localStorage:", err);
      }
      return updatedList;
    });
  };

  const handlePredictUpload = (file, result, previewUrl) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      handleAddGalleryImage({
        id: `upload-${Date.now()}`,
        url: e.target.result || previewUrl,
        name: file.name,
        source: "User Upload",
        label: result.label,
        isDataset: false,
        prediction: result,
        uploadedAt: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      });
    };
    reader.readAsDataURL(file);
  };

  const refresh = useCallback(async () => {
    try {
      const [roundsPayload, healthPayload] = await Promise.all([fetchRounds(), fetchHealth()]);
      setRounds(roundsPayload.rounds || []);
      setHealth(healthPayload);
      setError(null);

      // /model returns 503 until the first checkpoint exists, which is normal
      // during the opening seconds of a demo and is not worth surfacing.
      if (healthPayload.model_available) {
        try {
          setModel(await fetchModel());
        } catch {
          /* the checkpoint is being written right now */
        }
      }
    } catch (caught) {
      setError(caught.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    fetchPartition().then(setPartition);
    fetchBaseline().then(setBaseline);
  }, [refresh]);

  // Poll while a run is in flight. Five seconds is comfortably inside a round,
  // so the chart grows visibly during the demo without hammering the API.
  useEffect(() => {
    if (!live) return undefined;
    const timer = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [live, refresh]);

  const series = useMemo(() => {
    const hospitalIds = (partition?.hospitals || []).map((hospital) => hospital.hospital_id);
    const fallbackIds = rounds.length
      ? [...new Set((rounds[rounds.length - 1].hospitals || []).map((entry) => entry.hospital_id))]
      : [];
    const ids = (hospitalIds.length ? hospitalIds : fallbackIds).slice(0, 3);

    return [
      {
        key: "global",
        label: "global",
        legend: "global model on the held-out test set",
        color: "var(--series-1)",
        emphasis: true,
        accessor: (round) => Number(round.accuracy),
      },
      ...ids.map((id, index) => ({
        key: `hospital-${id}`,
        label: String(id).toUpperCase(),
        legend: `hospital ${String(id).toUpperCase()} local training accuracy`,
        color: `var(--series-${index + 2})`,
        accessor: (round) => hospitalAccuracy(round, id),
      })),
    ];
  }, [partition, rounds]);

  const latest = rounds.length ? rounds[rounds.length - 1] : null;
  const best = rounds.length ? Math.max(...rounds.map((round) => Number(round.accuracy))) : null;
  const totalImages = (partition?.hospitals || []).reduce(
    (sum, hospital) => sum + hospital.examples,
    0,
  );

  return (
    <div className="app">
      <header className="masthead">
        <div>
          <h1>FedMed federation console</h1>
          <p>
            Three hospitals train one pneumonia classifier without exchanging a single image. This
            page reads the aggregator's round history and serves the model it produced.
          </p>
        </div>

        <div className="controls">
          <span className={`pill ${health?.model_available ? "good" : "warn"}`}>
            <span className="dot" />
            {health?.model_available ? `model from round ${health.model_round}` : "no model yet"}
          </span>
          <button onClick={() => setLive((value) => !value)}>
            {live ? "Pause updates" : "Resume updates"}
          </button>
          <button onClick={refresh}>Refresh</button>
        </div>
      </header>

      {error ? (
        <div className="error" style={{ marginBottom: 16 }}>
          Could not reach the API at {apiBase}. {error}
        </div>
      ) : null}

      {loading ? <p className="subtitle">Loading...</p> : null}

      <div className="grid tiles">
        <StatTile
          label="Global accuracy"
          value={latest ? `${(Number(latest.accuracy) * 100).toFixed(1)}%` : "--"}
          note={latest ? `after round ${latest.round}` : "waiting for round 1"}
        />
        <StatTile
          label="Best so far"
          value={best !== null ? `${(best * 100).toFixed(1)}%` : "--"}
          note={`${rounds.length} rounds recorded`}
        />
        <StatTile
          label="Images kept local"
          value={totalImages ? totalImages.toLocaleString() : "--"}
          note="never transmitted, in any round"
        />
        <StatTile
          label="Privacy budget"
          value={
            model?.privacy?.epsilon != null
              ? `e = ${Number(model.privacy.epsilon).toFixed(1)}`
              : model?.privacy?.mechanism === "none"
                ? "off"
                : "--"
          }
          note={model?.privacy ? `at delta = ${model.privacy.delta}` : ""}
        />
      </div>

      <div className="grid split">
        <div className="card">
          <h2>Accuracy by round</h2>
          <p className="subtitle">
            The blue line is the aggregated model measured on a test set no hospital owns. The
            other lines are each site's accuracy on its own patients. The dashed line is what a
            single model reaches when it is allowed to pool all three datasets, which is the
            accuracy this platform gives up in exchange for keeping the images apart.
          </p>
          <AccuracyChart rounds={rounds} series={series} baseline={baseline?.final_accuracy ?? null} />

          <details>
            <summary>Show the numbers as a table</summary>
            <table style={{ marginTop: 10 }}>
              <thead>
                <tr>
                  <th>Round</th>
                  <th>Global accuracy</th>
                  <th>Loss</th>
                  <th>Recall pneumonia</th>
                  <th>Seconds</th>
                </tr>
              </thead>
              <tbody>
                {rounds.map((round) => (
                  <tr key={round.round}>
                    <td>{round.round}</td>
                    <td>{(Number(round.accuracy) * 100).toFixed(2)}%</td>
                    <td>{Number(round.loss).toFixed(4)}</td>
                    <td>
                      {round.recall_pneumonia != null
                        ? `${(Number(round.recall_pneumonia) * 100).toFixed(1)}%`
                        : "--"}
                    </td>
                    <td>{round.round_seconds ?? "--"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>

        <PrivacyPanel model={model} />
      </div>

      <HospitalPanel partition={partition} latestRound={latest} />

      <ImageGalleryPanel
        images={galleryImages}
        onAddImage={handleAddGalleryImage}
        onRemoveUpload={handleRemoveUpload}
        onSelectImage={(file, result) => {
          setActivePredictImage({ file, prediction: result, url: URL.createObjectURL(file) });
        }}
        modelRound={model?.round}
      />

      <div style={{ marginTop: 20 }}>
        <PredictPanel
          modelRound={model?.round}
          activeImage={activePredictImage}
          onImageUploaded={handlePredictUpload}
        />
      </div>

      <footer>
        API {apiBase} · run {latest?.run_id || model?.run_id || "none"} · updates{" "}
        {live ? `every ${POLL_INTERVAL_MS / 1000}s` : "paused"}
      </footer>
    </div>
  );
}
