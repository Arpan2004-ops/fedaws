import { useEffect, useRef, useState } from "react";
import { predict } from "../api";

/**
 * Upload one chest X-ray and get the federated model's verdict.
 *
 * The preview is drawn from a local object URL, so the browser shows the image
 * without the page ever storing it anywhere. The server behaves the same way.
 */

const LABEL_COLORS = {
  normal: "var(--series-1)",
  pneumonia: "var(--series-2)",
};

export default function PredictPanel({ modelRound, onImageUploaded, activeImage }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  // Sync with activeImage from gallery if provided
  useEffect(() => {
    if (activeImage) {
      if (activeImage.url) setPreviewUrl(activeImage.url);
      if (activeImage.prediction) setResult(activeImage.prediction);
      setError(null);
    }
  }, [activeImage]);

  const submit = async (file) => {
    if (!file) return;
    setError(null);
    setResult(null);
    setBusy(true);

    if (previewUrl && !previewUrl.startsWith("http") && !previewUrl.startsWith("/samples")) {
      URL.revokeObjectURL(previewUrl);
    }
    const localUrl = URL.createObjectURL(file);
    setPreviewUrl(localUrl);

    try {
      const predResult = await predict(file);
      setResult(predResult);
      if (onImageUploaded) {
        onImageUploaded(file, predResult, localUrl);
      }
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (event) => {
    event.preventDefault();
    setDragging(false);
    submit(event.dataTransfer.files?.[0]);
  };

  return (
    <div className="card">
      <h2>Try the federated model</h2>
      <p className="subtitle">
        {modelRound
          ? `Serving the global model from round ${modelRound}.`
          : "Waiting for a trained model."}
      </p>

      <div
        className={`dropzone ${dragging ? "active" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") inputRef.current?.click();
        }}
      >
        {busy ? "Classifying..." : "Drop a chest X-ray here, or click to choose a file"}
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(event) => submit(event.target.files?.[0])}
        />
      </div>

      {error ? <div className="error" style={{ marginTop: 14 }}>{error}</div> : null}

      {result ? (
        <div className="preview">
          {previewUrl ? <img src={previewUrl} alt="Uploaded chest X-ray" /> : null}
          <div className="result" style={{ flex: 1 }}>
            <div className="verdict" style={{ color: LABEL_COLORS[result.label] }}>
              {result.label}
            </div>
            <div style={{ color: "var(--text-secondary)", fontSize: 13 }}>
              {(result.confidence * 100).toFixed(1)}% confidence
            </div>

            {Object.entries(result.probabilities).map(([label, probability]) => (
              <div className="prob-row" key={label}>
                <span style={{ width: 78, color: "var(--text-secondary)" }}>{label}</span>
                <span className="track">
                  <span
                    className="fill"
                    style={{ width: `${probability * 100}%`, background: LABEL_COLORS[label] }}
                  />
                </span>
                <span style={{ width: 46, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {(probability * 100).toFixed(1)}%
                </span>
              </div>
            ))}

            <p className="mono" style={{ marginTop: 12 }}>
              audit hash {result.request_hash?.slice(0, 32)}...
            </p>
            <p style={{ color: "var(--text-muted)", fontSize: 12, margin: 0 }}>
              The image was decoded, classified and discarded. Only this hash was recorded.
            </p>
          </div>
        </div>
      ) : null}

      <div className="callout">
        A teaching demonstration on a public research dataset. Nothing here is a medical device and
        no output should inform a clinical decision.
      </div>
    </div>
  );
}
